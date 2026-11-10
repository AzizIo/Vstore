import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { AuthApiError, authenticateTelegram, fetchCurrentUser, type UserProfile } from "./api";
import { getTelegramInitData } from "./telegram";

export type SessionState =
  | { status: "loading" }
  | { status: "unauthenticated"; reason: "missing_init_data" | "invalid_init_data" }
  | { status: "authenticated"; accessToken: string; user: UserProfile }
  | { status: "error"; message: string };

const SessionContext = createContext<SessionState | null>(null);

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
    return { status: "error", message: "This account is restricted. Contact support for assistance." };
  }
  return {
    status: "error",
    message: "Unable to verify your Telegram session. The public catalog is still available.",
  };
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [session, setSession] = useState<SessionState>({ status: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    async function loadSession() {
      try {
        const initData = await getTelegramInitData(controller.signal);
        if (controller.signal.aborted) return;
        if (!initData) {
          setSession({ status: "unauthenticated", reason: "missing_init_data" });
          return;
        }
        const accessToken = await authenticateTelegram(initData, controller.signal);
        const user = await fetchCurrentUser(accessToken, controller.signal);
        if (!controller.signal.aborted) setSession({ status: "authenticated", accessToken, user });
      } catch (error) {
        if (controller.signal.aborted) return;
        if (error instanceof AuthApiError && error.status === 401) clearPrivateCache(queryClient);
        setSession(error instanceof TypeError
          ? { status: "error", message: "Telegram Mini App could not be initialized." }
          : getSessionError(error));
      }
    }

    void loadSession();
    return () => controller.abort();
  }, [queryClient]);

  return <SessionContext.Provider value={session}>{children}</SessionContext.Provider>;
}

export function useSession() {
  const session = useContext(SessionContext);
  if (!session) throw new Error("useSession must be used within SessionProvider.");
  return session;
}