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

export type ProductVariant = {
  id: string;
  sku: string;
  options: Record<string, string>;
  price: string;
  cost: string | null;
  inventory: number;
  image: string | null;
};

export type Product = {
  id: string;
  tenant_id: string;
  source: string;
  source_id: string;
  sku: string;
  title: string;
  description: string;
  category: string;
  tags: string[];
  images: string[];
  meta_title: string;
  meta_description: string;
  handle: string;
  status: "draft" | "active" | "archived";
  variants: ProductVariant[];
};

export type ProductImportResult = {
  imported_products: number;
  imported_variants: number;
  imported_images: number;
  products: Product[];
};

export type RiskLevel = "low" | "medium" | "high";
export type DraftStatus =
  | "pending_review"
  | "approved"
  | "published"
  | "rejected"
  | "rolled_back";
export type RejectionReason =
  | "fact_error"
  | "expression"
  | "seo"
  | "brand_style"
  | "other";
export type SnapshotKind = "publish" | "rollback";

export type ReviewDraft = {
  id: string;
  tenant_id: string;
  product_id: string;
  task_id: string;
  title: string;
  description: string;
  meta_title: string;
  meta_description: string;
  alt_text: Record<string, string>;
  seo_tags: string[];
  risk_level: RiskLevel;
  status: DraftStatus;
  rejection_reason: RejectionReason | null;
  created_at: string;
  updated_at: string;
};

export type ProductSnapshot = {
  id: string;
  product_id: string;
  version: number;
  kind: SnapshotKind;
  payload: Record<string, unknown>;
  field_diff: Record<string, { from: unknown; to: unknown }>;
  actor: string;
  restored_version: number | null;
  created_at: string;
};

export type PublishResult = {
  draft: ReviewDraft;
  task: Task;
  snapshot: ProductSnapshot;
  remote_id: string;
};

export type RollbackResult = {
  product: Product;
  task: Task | null;
  snapshot: ProductSnapshot;
};

export type Task = {
  id: string;
  tenant_id: string;
  kind: "product" | "seo";
  operation_type: string;
  changed_fields: string[];
  risk_level: RiskLevel;
  status: string;
  last_error: string | null;
  product_id: string | null;
  created_at: string;
  updated_at: string;
};

export type ApiValidationIssue = {
  line: number;
  message: string;
};

type TokenResponse = {
  access_token: string;
  token_type: "bearer";
};

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly validationIssues: ApiValidationIssue[] = [],
  ) {
    super(message);
  }
}

async function parseResponse<T>(response: Response): Promise<T> {
  if (response.ok) {
    return (await response.json()) as T;
  }

  const payload = (await response.json().catch(() => null)) as {
    detail?: unknown;
  } | null;
  const validationIssues = Array.isArray(payload?.detail)
    ? payload.detail.filter(
        (issue): issue is ApiValidationIssue =>
          typeof issue === "object" &&
          issue !== null &&
          typeof (issue as ApiValidationIssue).line === "number" &&
          typeof (issue as ApiValidationIssue).message === "string",
      )
    : [];
  const message =
    typeof payload?.detail === "string"
      ? payload.detail
      : validationIssues.length
        ? "请求内容校验失败"
        : "请求失败，请稍后重试";
  throw new ApiError(message, response.status, validationIssues);
}

async function getAuthenticated<T>(path: string, token: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return parseResponse<T>(response);
}

async function authenticatedMutation<T>(
  path: string,
  token: string,
  method: "POST" | "PATCH",
  body?: unknown,
): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method,
    headers: {
      Authorization: `Bearer ${token}`,
      ...(body === undefined ? {} : { "Content-Type": "application/json" }),
    },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
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

export async function getProducts(token: string): Promise<Product[]> {
  return getAuthenticated<Product[]>("/products", token);
}

export async function importProducts(
  token: string,
  csvFile: File,
  images: File[],
): Promise<ProductImportResult> {
  const body = new FormData();
  body.append("file", csvFile);
  images.forEach((image) => body.append("images", image));
  const response = await fetch(`${API_BASE}/products/import`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body,
  });
  return parseResponse<ProductImportResult>(response);
}

export async function getShopifyStores(token: string): Promise<ShopifyStore[]> {
  return getAuthenticated<ShopifyStore[]>("/shopify/stores", token);
}

export async function getReviewQueue(token: string): Promise<ReviewDraft[]> {
  return getAuthenticated<ReviewDraft[]>("/reviews/queue", token);
}

export async function generateProductDraft(
  token: string,
  productId: string,
): Promise<Task> {
  const response = await fetch(`${API_BASE}/products/${productId}/generate`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
  return parseResponse<Task>(response);
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

export async function approveDrafts(
  token: string,
  draftIds: string[],
): Promise<ReviewDraft[]> {
  return authenticatedMutation<ReviewDraft[]>(
    "/reviews/approve",
    token,
    "POST",
    { draft_ids: draftIds },
  );
}

export async function rejectDrafts(
  token: string,
  draftIds: string[],
  reason: RejectionReason,
): Promise<ReviewDraft[]> {
  return authenticatedMutation<ReviewDraft[]>(
    "/reviews/reject",
    token,
    "POST",
    { draft_ids: draftIds, reason },
  );
}

export async function editDraft(
  token: string,
  draftId: string,
  edits: {
    title?: string;
    description?: string;
    meta_title?: string;
    meta_description?: string;
    alt_text?: Record<string, string>;
    seo_tags?: string[];
  },
): Promise<ReviewDraft> {
  return authenticatedMutation<ReviewDraft>(
    `/reviews/${draftId}`,
    token,
    "PATCH",
    edits,
  );
}

export async function regenerateDraft(
  token: string,
  draftId: string,
): Promise<Task> {
  return authenticatedMutation<Task>(
    `/reviews/${draftId}/regenerate`,
    token,
    "POST",
  );
}

export async function publishDraft(
  token: string,
  draftId: string,
  confirmed: boolean,
): Promise<PublishResult> {
  return authenticatedMutation<PublishResult>(
    `/reviews/${draftId}/publish`,
    token,
    "POST",
    { confirmed },
  );
}

export async function getProductVersions(
  token: string,
  productId: string,
): Promise<ProductSnapshot[]> {
  return getAuthenticated<ProductSnapshot[]>(
    `/products/${productId}/versions`,
    token,
  );
}

export async function rollbackProduct(
  token: string,
  productId: string,
  version: number,
): Promise<RollbackResult> {
  return authenticatedMutation<RollbackResult>(
    `/products/${productId}/rollback`,
    token,
    "POST",
    { version },
  );
}
