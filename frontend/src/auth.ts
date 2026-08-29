import {
  ApiError,
  type Admin,
  type LoginCredentials,
  getCurrentAdmin,
  login,
} from "./api";

const TOKEN_KEY = "ai-site-admin-token";

function savedToken(): string | null {
  return sessionStorage.getItem(TOKEN_KEY);
}

export async function withAuthenticatedSession<T>(
  operation: (token: string) => Promise<T>,
): Promise<T> {
  const token = savedToken();
  if (!token) throw new ApiError("登录状态已失效，请重新登录", 401);
  try {
    return await operation(token);
  } catch (cause) {
    if (cause instanceof ApiError && cause.status === 401) {
      sessionStorage.removeItem(TOKEN_KEY);
    }
    throw cause;
  }
}

async function resolveAdmin(token: string): Promise<Admin> {
  try {
    return await getCurrentAdmin(token);
  } catch (cause) {
    if (cause instanceof ApiError && cause.status === 401) {
      sessionStorage.removeItem(TOKEN_KEY);
    }
    throw cause;
  }
}

export function hasSavedSession(): boolean {
  return Boolean(savedToken());
}

export async function authenticate(credentials: LoginCredentials): Promise<Admin> {
  const token = await login(credentials);
  sessionStorage.setItem(TOKEN_KEY, token.access_token);
  return resolveAdmin(token.access_token);
}

export async function restoreSession(): Promise<Admin | null> {
  const token = savedToken();
  if (!token) return null;
  try {
    return await resolveAdmin(token);
  } catch (cause) {
    if (cause instanceof ApiError && cause.status === 401) return null;
    throw cause;
  }
}

export function clearSession(): void {
  sessionStorage.removeItem(TOKEN_KEY);
}
