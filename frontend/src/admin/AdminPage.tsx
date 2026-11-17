import { useEffect, useState } from "react";
import { SessionProvider, useRetrySession, useSession } from "../auth/SessionProvider";
import { fetchAdminAccess } from "./api";
import { AdminDashboard } from "./AdminDashboard";

function AdminPageContent() {
  const session = useSession();
  const retrySession = useRetrySession();
  const [isAdmin, setIsAdmin] = useState<boolean | null>(null);
  const [accessError, setAccessError] = useState("");
  const [accessRetry, setAccessRetry] = useState(0);

  useEffect(() => {
    if (session.status !== "authenticated") {
      setIsAdmin(null);
      setAccessError("");
      return;
    }
    const controller = new AbortController();
    setIsAdmin(null);
    setAccessError("");
    void fetchAdminAccess(session.accessToken, controller.signal)
      .then(setIsAdmin)
      .catch((caught: unknown) => {
        if (controller.signal.aborted) return;
        const status = (caught as { status?: number } | null)?.status;
        if (status === 403) {
          setIsAdmin(false);
          return;
        }
        setAccessError(caught instanceof Error
          ? caught.message
          : "Не удалось проверить права администратора.");
      });
    return () => controller.abort();
  }, [session.status, session.status === "authenticated" ? session.accessToken : null, accessRetry]);

  if (session.status === "loading") {
    return <main className="admin-route-message" role="status">Проверяем сессию Telegram…</main>;
  }
  if (session.status === "unauthenticated") {
    const sessionMessage = session.reason === "missing_init_data"
      ? "Telegram не передал данные запуска. Закройте это окно, отправьте боту /admin и откройте панель кнопкой внутри Telegram."
      : "Сессия Telegram устарела. Закройте панель и откройте её заново через команду /admin в боте.";
    return <main className="admin-route-message" role="alert">{sessionMessage}</main>;
  }
  if (session.status === "error") {
    return <main className="admin-route-message" role="alert">
      <p>{session.message}</p>
      {session.retryable && (
        <button type="button" onClick={retrySession}>Повторить проверку сессии</button>
      )}
    </main>;
  }
  if (accessError) {
    return <main className="admin-route-message" role="alert">
      <p>{accessError}</p>
      <button type="button" onClick={() => setAccessRetry((value) => value + 1)}>Повторить проверку</button>
    </main>;
  }
  if (isAdmin === null) {
    return <main className="admin-route-message" role="status">Проверяем права администратора…</main>;
  }
  if (!isAdmin) {
    return <main className="admin-route-message" role="alert">Требуются права администратора.</main>;
  }
  return <AdminDashboard accessToken={session.accessToken} />;
}

export function AdminPage() {
  return <SessionProvider><AdminPageContent /></SessionProvider>;
}
