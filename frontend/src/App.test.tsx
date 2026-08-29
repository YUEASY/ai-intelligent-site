import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";

const admin = {
  id: "10000000-0000-0000-0000-000000000001",
  tenant_id: "00000000-0000-0000-0000-000000000001",
  email: "admin@example.com",
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

async function submitLogin(password = "correct-password") {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("密码"), password);
  await user.click(screen.getByRole("button", { name: "登录运营后台" }));
}

describe("internal admin authentication", () => {
  beforeEach(() => {
    sessionStorage.clear();
    window.history.replaceState({}, "", "/");
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("shows the login screen instead of a protected page without a session", () => {
    window.history.replaceState({}, "", "/tasks");

    render(<App />);

    expect(
      screen.getByRole("button", { name: "登录运营后台" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("任务模块已就绪")).not.toBeInTheDocument();
  });

  it("logs in with valid credentials and renders the protected shell", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        jsonResponse({ access_token: "valid-access-token", token_type: "bearer" }),
      )
      .mockResolvedValueOnce(jsonResponse(admin));
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    await submitLogin();

    expect(await screen.findByText("运营概览")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/v1/auth/login",
      expect.objectContaining({ method: "POST" }),
    );
    expect(sessionStorage.getItem("ai-site-admin-token")).toBe(
      "valid-access-token",
    );
  });

  it("keeps the login screen and reports invalid credentials", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockResolvedValue(
        jsonResponse({ detail: "Invalid tenant, email, or password" }, 401),
      ),
    );
    render(<App />);

    await submitLogin("wrong-password");

    expect(await screen.findByText("租户、邮箱或密码不正确")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "登录运营后台" }),
    ).toBeInTheDocument();
    expect(sessionStorage.getItem("ai-site-admin-token")).toBeNull();
  });

  it("renders placeholders and opens the product list", async () => {
    sessionStorage.setItem("ai-site-admin-token", "saved-access-token");
    vi.stubGlobal("fetch", vi.fn<typeof fetch>((input) => {
      const url = input instanceof Request ? input.url : input.toString();
      return Promise.resolve(
        jsonResponse(url.endsWith("/products") ? [] : admin),
      );
    }));
    const user = userEvent.setup();
    render(<App />);
    await screen.findByText("运营概览");

    for (const [navigation, placeholder] of [
      ["任务", "任务模块已就绪"],
      ["审核", "审核模块已就绪"],
    ] as const) {
      await user.click(screen.getByRole("menuitem", { name: navigation }));
      await waitFor(() => expect(screen.getByText(placeholder)).toBeInTheDocument());
    }

    await user.click(screen.getByRole("menuitem", { name: "商品" }));
    expect(
      await screen.findByRole("heading", { name: "商品列表" }),
    ).toBeInTheDocument();
    expect(screen.getByText("尚未导入商品")).toBeInTheDocument();
  });
});
