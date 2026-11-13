import React, { lazy, Suspense } from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App } from "./App";

const AdminPage = lazy(() => import("./admin/AdminPage").then((module) => ({ default: module.AdminPage })));
import "./index.css";
import "./telegram-miniapp.css";
import "./catalog-ui.css";
import "./workspace-ui.css";
import "./shell-ui.css";

const queryClient = new QueryClient();
const Root = window.location.pathname === "/admin" || window.location.pathname === "/admin/"
  ? AdminPage
  : App;

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <Suspense fallback={<main className="admin-route-message" role="status">Загружаем VILTARA…</main>}>
        <Root />
      </Suspense>
    </QueryClientProvider>
  </React.StrictMode>,
);
