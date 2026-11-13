import { useEffect, useState } from "react";
import { SessionProvider, useSession } from "../auth/SessionProvider";
import { fetchAdminAccess } from "./api";
import { AdminCenter } from "./AdminCenter";

function AdminPageContent() {
  const session = useSession();
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
  if (session.status !== "authenticated") {
    return <main className="admin-route-message" role="alert">Требуется подтверждённая сессия Telegram.</main>;
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
  return <AdminCenter accessToken={session.accessToken} active />;
}

export function AdminPage() {
  return <SessionProvider><AdminPageContent /></SessionProvider>;
}
