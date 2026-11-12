import { useEffect, useState } from "react";
import { SessionProvider, useSession } from "../auth/SessionProvider";
import { fetchAdminAccess } from "./api";
import { AdminCenter } from "./AdminCenter";

function AdminPageContent() {
  const session = useSession();
  const [isAdmin, setIsAdmin] = useState<boolean | null>(null);

  useEffect(() => {
    if (session.status !== "authenticated") {
      setIsAdmin(null);
      return;
    }
    const controller = new AbortController();
    void fetchAdminAccess(session.accessToken, controller.signal)
      .then(setIsAdmin)
      .catch(() => setIsAdmin(false));
    return () => controller.abort();
  }, [session.status, session.status === "authenticated" ? session.accessToken : null]);

  if (session.status === "loading") {
    return <main className="admin-route-message" role="status">Verifying Telegram session…</main>;
  }
  if (session.status !== "authenticated") {
    return <main className="admin-route-message" role="alert">A verified Telegram session is required.</main>;
  }
  if (isAdmin === null) {
    return <main className="admin-route-message" role="status">Checking administrator access…</main>;
  }
  if (!isAdmin) {
    return <main className="admin-route-message" role="alert">Administrator access required.</main>;
  }
  return <AdminCenter accessToken={session.accessToken} active />;
}

export function AdminPage() {
  return <SessionProvider><AdminPageContent /></SessionProvider>;
}
