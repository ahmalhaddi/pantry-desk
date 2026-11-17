const TOKEN_KEY = "pantry-desk-token";

export type User = {
  id: number;
  email: string;
  full_name: string;
  role: "coordinator" | "steward";
};

export function token(): string | null {
  return sessionStorage.getItem(TOKEN_KEY);
}

export function setToken(value: string | null) {
  if (value) sessionStorage.setItem(TOKEN_KEY, value);
  else sessionStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body) headers.set("Content-Type", "application/json");
  const current = token();
  if (current) headers.set("Authorization", `Bearer ${current}`);
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    let detail = "Request failed";
    try {
      const body = await response.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      detail = response.statusText || detail;
    }
    if (response.status === 401) setToken(null);
    throw new ApiError(response.status, detail);
  }
  return response.json() as Promise<T>;
}

export function localInputToIso(value: string): string {
  return new Date(value).toISOString();
}
