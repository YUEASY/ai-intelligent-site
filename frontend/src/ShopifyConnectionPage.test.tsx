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

vi.mock("./api", () => ({
  getShopifyAuthorizationUrl: vi.fn(),
  getShopifyStores: vi.fn(),
}));

vi.mock("./auth", () => ({
  getSavedAccessToken: () => "saved-access-token",
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
        return 1;
      },
    );
    const openWindow = vi
      .spyOn(window, "open")
      .mockReturnValue({} as Window);
    mockedGetShopifyStores
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([
        {
          shop_domain: "merchant.myshopify.com",
          status: "connected",
          granted_scopes: ["write_content", "write_products"],
        },
      ]);
    mockedGetAuthorizationUrl.mockResolvedValue({
      authorization_url:
        "https://merchant.myshopify.com/admin/oauth/authorize?state=secure",
    });
    render(<ShopifyConnectionPage />);
    await screen.findByText("未连接");

    fireEvent.change(screen.getByPlaceholderText("your-store.myshopify.com"), {
      target: { value: "merchant.myshopify.com" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "连接 Shopify 店铺" }),
    );

    await waitFor(() =>
      expect(mockedGetAuthorizationUrl).toHaveBeenCalledWith(
        "saved-access-token",
        "merchant.myshopify.com",
      ),
    );
    expect(openWindow).toHaveBeenCalledWith(
      "https://merchant.myshopify.com/admin/oauth/authorize?state=secure",
      "shopify-oauth",
      "popup,width=720,height=760",
    );

    await act(async () => poll?.());

    expect(await screen.findByText("已连接")).toBeInTheDocument();
    expect(screen.getByText("merchant.myshopify.com")).toBeInTheDocument();
  });
});
