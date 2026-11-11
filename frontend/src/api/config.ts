// Keep API requests on the Mini App origin. Vite proxies /api to the
// FastAPI container during development, so this also works through HTTPS tunnels.
export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");
