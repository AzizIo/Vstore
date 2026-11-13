export function getApiErrorMessage(body: unknown, fallback: string): string {
  if (!body || typeof body !== "object" || !("detail" in body)) return fallback;

  const detail: unknown = body.detail;
  if (typeof detail === "string" && detail.trim()) return detail.trim();
  if (Array.isArray(detail)) {
    const messages = detail.flatMap((item) => {
      if (!item || typeof item !== "object" || !("msg" in item)) return [];
      return typeof item.msg === "string" && item.msg.trim() ? [item.msg.trim()] : [];
    });
    if (messages.length) return [...new Set(messages)].join(" ");
  }
  return fallback;
}
