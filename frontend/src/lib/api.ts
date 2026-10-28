export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details: Record<string, unknown> = {},
  ) {
    super(message);
  }
}

function csrfToken(): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.match(/(?:^|;\s*)ashore_csrf=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : null;
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  const init: RequestInit = { method, credentials: "same-origin", headers };
  if (method !== "GET") {
    const token = csrfToken();
    if (token) headers["x-csrf-token"] = token;
  }
  if (body instanceof FormData) {
    init.body = body;
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  let response: Response;
  try {
    response = await fetch(path, init);
  } catch {
    throw new ApiError(0, "network", "Нет связи с сервером. Проверьте подключение.");
  }
  if (response.status === 204) return undefined as T;
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const err = data?.error ?? {};
    if (response.status === 401 && typeof window !== "undefined" && !path.startsWith("/api/auth/")) {
      window.location.href = `/login?next=${encodeURIComponent(window.location.pathname)}`;
    }
    throw new ApiError(response.status, err.code ?? "error", err.message ?? "Что-то пошло не так", err.details ?? {});
  }
  return data as T;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body),
  put: <T>(path: string, body?: unknown) => request<T>("PUT", path, body),
  patch: <T>(path: string, body?: unknown) => request<T>("PATCH", path, body),
  del: <T>(path: string) => request<T>("DELETE", path),
};

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  return "Что-то пошло не так";
}
