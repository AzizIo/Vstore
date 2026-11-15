import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { AuthApiError, authenticateTelegram, fetchCurrentUser, type UserProfile } from "./api";
import { getTelegramInitData } from "./telegram";

export type SessionState =
  | { status: "loading" }
  | { status: "unauthenticated"; reason: "missing_init_data" | "invalid_init_data" }
  | { status: "authenticated"; accessToken: string; user: UserProfile }
  | { status: "error"; message: string; retryable: boolean };

const SessionContext = createContext<SessionState | null>(null);
const SessionRetryContext = createContext<(() => void) | null>(null);

function clearPrivateCache(queryClient: ReturnType<typeof useQueryClient>) {
  queryClient.removeQueries({
    predicate: (query) => query.meta?.private === true,
  });
}

function getSessionError(error: unknown): SessionState {
  if (error instanceof AuthApiError && error.status === 401) {
    return { status: "unauthenticated", reason: "invalid_init_data" };
  }
  if (error instanceof AuthApiError && error.status === 403) {
    return {
      status: "error",
      message: "Для этого аккаунта ограничен доступ. Обратитесь в поддержку.",
      retryable: false,
    };
  }
  return {
    status: "error",
    message: "Не удалось подтвердить сессию Telegram. Каталог доступен в режиме просмотра.",
    retryable: true,
  };
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [session, setSession] = useState<SessionState>({ status: "loading" });
  const [sessionAttempt, setSessionAttempt] = useState(0);

  function retrySession() {
    clearPrivateCache(queryClient);
    setSession({ status: "loading" });
    setSessionAttempt((attempt) => attempt + 1);
  }

  useEffect(() => {
    const controller = new AbortController();
    let expirationTimer: number | null = null;

    async function loadSession() {
      try {
        const initData = await getTelegramInitData(controller.signal);
        if (controller.signal.aborted) return;
        if (!initData) {
          setSession({ status: "unauthenticated", reason: "missing_init_data" });
          return;
        }
        const authenticationStartedAt = Date.now();
        const authenticatedSession = await authenticateTelegram(initData, controller.signal);
        const tokenExpiresAt = authenticationStartedAt + authenticatedSession.expiresIn * 1000;
        const user = await fetchCurrentUser(authenticatedSession.accessToken, controller.signal);
        if (!controller.signal.aborted) {
          setSession({
            status: "authenticated",
            accessToken: authenticatedSession.accessToken,
            user,
          });

          // Telegram initData is valid only for a short server-defined window and
          // there is no refresh-token endpoint. Do not mint a new JWT from stale
          // initData: expire this session and require a fresh Mini App launch.
          const remainingLifetimeMs = Math.max(0, tokenExpiresAt - Date.now());
          if (remainingLifetimeMs === 0) {
            clearPrivateCache(queryClient);
            setSession({ status: "unauthenticated", reason: "invalid_init_data" });
            return;
          }
          expirationTimer = window.setTimeout(() => {
            if (controller.signal.aborted) return;
            clearPrivateCache(queryClient);
            setSession({ status: "unauthenticated", reason: "invalid_init_data" });
          }, remainingLifetimeMs);
        }
      } catch (error) {
        if (controller.signal.aborted) return;
        clearPrivateCache(queryClient);
        setSession(error instanceof TypeError
          ? {
              status: "error",
              message: "Не удалось запустить мини-приложение Telegram.",
              retryable: true,
            }
          : getSessionError(error));
      }
    }

    void loadSession();
    return () => {
      controller.abort();
      if (expirationTimer !== null) window.clearTimeout(expirationTimer);
    };
  }, [queryClient, sessionAttempt]);

  return (
    <SessionRetryContext.Provider value={retrySession}>
      <SessionContext.Provider value={session}>{children}</SessionContext.Provider>
    </SessionRetryContext.Provider>
  );
}

export function useSession() {
  const session = useContext(SessionContext);
  if (!session) throw new Error("useSession must be used within SessionProvider.");
  return session;
}

export function useRetrySession() {
  const retrySession = useContext(SessionRetryContext);
  if (!retrySession) throw new Error("useRetrySession must be used within SessionProvider.");
  return retrySession;
}
