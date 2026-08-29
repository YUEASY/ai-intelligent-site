import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getShopifyAuthorizationUrl, getShopifyStores } from "./api";
import ShopifyConnectionPage from "./ShopifyConnectionPage";

vi.mock("./api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api")>()),
  getShopifyAuthorizationUrl: vi.fn(),
  getShopifyStores: vi.fn(),
}));

vi.mock("./auth", () => ({
  withAuthenticatedSession: <T,>(operation: (token: string) => Promise<T>) =>
    operation("saved-access-token"),
}));

const mockedGetShopifyStores = vi.mocked(getShopifyStores);
const mockedGetAuthorizationUrl = vi.mocked(getShopifyAuthorizationUrl);

describe("ShopifyConnectionPage", () => {
  beforeEach(() => {
    mockedGetShopifyStores.mockReset();
    mockedGetAuthorizationUrl.mockReset();
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("shows the disconnected state and an authorization button", async () => {
    mockedGetShopifyStores.mockResolvedValue([]);

    render(<ShopifyConnectionPage />);

    expect(
      screen.getByRole("heading", { name: "店铺连接" }),
    ).toBeInTheDocument();
    expect(await screen.findByText("未连接")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "连接 Shopify 店铺" }),
    ).toBeEnabled();
  });

  it("opens Shopify authorization and refreshes the connected state", async () => {
    let poll: (() => void) | undefined;
    vi.spyOn(window, "setInterval").mockImplementation(
      (handler: TimerHandler, timeout?: number) => {
        if (typeof handler === "function" && timeout === 3000) {
          poll = handler as () => void;
        }
        return 987654;
      },
    );
    const popup = {
      close: vi.fn(),
      location: { href: "" },
    } as unknown as Window;
    const openWindow = vi.spyOn(window, "open").mockReturnValue(popup);
    mockedGetShopifyStores
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([
        {
          shop_domain: "merchant.myshopify.com",
          status: "connected",
          granted_scopes: ["write_content", "write_products"],
        },
      ]);
    let resolveAuthorization!: (authorization: {
      authorization_url: string;
    }) => void;
    mockedGetAuthorizationUrl.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveAuthorization = resolve;
        }),
    );
    render(<ShopifyConnectionPage />);
    await screen.findByText("未连接");

    fireEvent.change(screen.getByPlaceholderText("your-store.myshopify.com"), {
      target: { value: "merchant.myshopify.com" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "连接 Shopify 店铺" }),
    );

    expect(openWindow).toHaveBeenCalledWith(
      "",
      "shopify-oauth",
      "popup,width=720,height=760",
    );
    resolveAuthorization({
      authorization_url:
        "https://merchant.myshopify.com/admin/oauth/authorize?state=secure",
    });

    await waitFor(() =>
      expect(mockedGetAuthorizationUrl).toHaveBeenCalledWith(
        "saved-access-token",
        "merchant.myshopify.com",
      ),
    );
    await waitFor(() => expect(popup.location.href).toBe(
      "https://merchant.myshopify.com/admin/oauth/authorize?state=secure",
    ));

    await act(async () => poll?.());

    expect(await screen.findByText("已连接")).toBeInTheDocument();
    expect(screen.getByText("merchant.myshopify.com")).toBeInTheDocument();
  });

  it("shows an errored store distinctly from a disconnected store", async () => {
    mockedGetShopifyStores.mockResolvedValue([
      {
        shop_domain: "broken.myshopify.com",
        status: "error",
        granted_scopes: [],
      },
    ]);

    render(<ShopifyConnectionPage />);

    expect(await screen.findByText("连接异常")).toBeInTheDocument();
    expect(screen.getByText("broken.myshopify.com")).toBeInTheDocument();
  });

  it("does not report a request failure as disconnected", async () => {
    mockedGetShopifyStores.mockRejectedValue(new Error("network unavailable"));

    render(<ShopifyConnectionPage />);

    expect(await screen.findByText("状态未知")).toBeInTheDocument();
    expect(
      screen.getByText("暂时无法获取店铺连接状态"),
    ).toBeInTheDocument();
  });

  it("does not overlap store status refreshes", async () => {
    let poll: (() => void) | undefined;
    vi.spyOn(window, "setInterval").mockImplementation(
      (handler: TimerHandler, timeout?: number) => {
        if (typeof handler === "function" && timeout === 3000) {
          poll = handler as () => void;
        }
        return 987654;
      },
    );
    let resolveStores!: (stores: []) => void;
    mockedGetShopifyStores.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveStores = resolve;
        }),
    );
    render(<ShopifyConnectionPage />);
    await act(async () => undefined);
    expect(mockedGetShopifyStores).toHaveBeenCalledTimes(1);

    await act(async () => poll?.());

    expect(mockedGetShopifyStores).toHaveBeenCalledTimes(1);
    resolveStores([]);
    expect(await screen.findByText("未连接")).toBeInTheDocument();
  });

  it("keeps an authorization error visible across successful status polls", async () => {
    let poll: (() => void) | undefined;
    vi.spyOn(window, "setInterval").mockImplementation(
      (handler: TimerHandler, timeout?: number) => {
        if (typeof handler === "function" && timeout === 3000) {
          poll = handler as () => void;
        }
        return 987654;
      },
    );
    vi.spyOn(window, "open").mockReturnValue(null);
    mockedGetShopifyStores.mockResolvedValue([]);
    render(<ShopifyConnectionPage />);
    await act(async () => undefined);

    fireEvent.change(screen.getByPlaceholderText("your-store.myshopify.com"), {
      target: { value: "merchant.myshopify.com" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "连接 Shopify 店铺" }),
    );
    expect(
      screen.getByText("浏览器阻止了授权窗口，请允许弹窗后重试"),
    ).toBeInTheDocument();

    await act(async () => poll?.());

    expect(
      screen.getByText("浏览器阻止了授权窗口，请允许弹窗后重试"),
    ).toBeInTheDocument();
  });
});
