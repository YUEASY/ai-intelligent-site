const API_BASE = "/api/v1";

export type LoginCredentials = {
  tenant_id: string;
  email: string;
  password: string;
};

export type Admin = {
  id: string;
  tenant_id: string;
  email: string;
};

type TokenResponse = {
  access_token: string;
  token_type: "bearer";
};

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function parseResponse<T>(response: Response): Promise<T> {
  if (response.ok) {
    return (await response.json()) as T;
  }

  const payload = (await response.json().catch(() => null)) as {
    detail?: string;
  } | null;
  throw new ApiError(payload?.detail ?? "请求失败，请稍后重试", response.status);
}

export async function login(
  credentials: LoginCredentials,
): Promise<TokenResponse> {
  const response = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(credentials),
  });
  return parseResponse<TokenResponse>(response);
}

export async function getCurrentAdmin(token: string): Promise<Admin> {
  const response = await fetch(`${API_BASE}/auth/me`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return parseResponse<Admin>(response);
}

