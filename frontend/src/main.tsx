import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App } from "./App";
import { AdminPage } from "./admin/AdminPage";
import "./index.css";

const queryClient = new QueryClient();
const Root = window.location.pathname === "/admin" || window.location.pathname === "/admin/"
  ? AdminPage
  : App;

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <Root />
    </QueryClientProvider>
  </React.StrictMode>,
);
