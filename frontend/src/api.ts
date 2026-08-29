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

export type ShopifyStore = {
  shop_domain: string;
  status: "connected" | "disconnected" | "error";
  granted_scopes: string[];
};

export type ShopifyAuthorization = {
  authorization_url: string;
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

async function getAuthenticated<T>(path: string, token: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return parseResponse<T>(response);
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
  return getAuthenticated<Admin>("/auth/me", token);
}

export async function getShopifyStores(token: string): Promise<ShopifyStore[]> {
  return getAuthenticated<ShopifyStore[]>("/shopify/stores", token);
}

export async function getShopifyAuthorizationUrl(
  token: string,
  shopDomain: string,
): Promise<ShopifyAuthorization> {
  const query = new URLSearchParams({ shop_domain: shopDomain });
  return getAuthenticated<ShopifyAuthorization>(
    `/shopify/oauth/authorize?${query.toString()}`,
    token,
  );
}
