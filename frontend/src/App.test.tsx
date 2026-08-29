import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";

const admin = {
  id: "10000000-0000-0000-0000-000000000001",
  tenant_id: "00000000-0000-0000-0000-000000000001",
  email: "admin@example.com",
};

const emptyMetrics = {
  tasks_total: 0,
  tasks_published: 0,
  tasks_failed: 0,
  success_rate: null,
  tokens_total: 0,
  cost_total: "0",
  daily: [],
  open_alerts: [],
};

const emptyCost = {
  tenant_id: admin.tenant_id,
  daily_cost: "0",
  daily_threshold: "6.00",
  total_cost: "0",
  total_tokens: 0,
  tasks: [],
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function requestUrl(input: string | Request | URL): string {
  return input instanceof Request ? input.url : input.toString();
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
    const fetchMock = vi.fn<typeof fetch>((input) => {
      const url = requestUrl(input);
      if (url.endsWith("/auth/login")) {
        return Promise.resolve(
          jsonResponse({ access_token: "valid-access-token", token_type: "bearer" }),
        );
      }
      if (url.endsWith("/metrics")) {
        return Promise.resolve(jsonResponse(emptyMetrics));
      }
      return Promise.resolve(jsonResponse(admin));
    });
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

  it("opens the dashboard, task logs, review, product and cost pages", async () => {
    sessionStorage.setItem("ai-site-admin-token", "saved-access-token");
    vi.stubGlobal("fetch", vi.fn<typeof fetch>((input) => {
      const url = requestUrl(input);
      if (url.endsWith("/metrics")) return Promise.resolve(jsonResponse(emptyMetrics));
      if (url.endsWith("/tasks")) return Promise.resolve(jsonResponse([]));
      if (url.endsWith("/reviews/queue")) return Promise.resolve(jsonResponse([]));
      if (url.endsWith("/products")) return Promise.resolve(jsonResponse([]));
      if (url.endsWith("/costs")) return Promise.resolve(jsonResponse(emptyCost));
      if (url.endsWith("/alerts")) return Promise.resolve(jsonResponse([]));
      return Promise.resolve(jsonResponse(admin));
    }));
    const user = userEvent.setup();
    render(<App />);
    await screen.findByText("运营概览");
    expect(await screen.findByText("任务总数")).toBeInTheDocument();

    await user.click(screen.getByRole("menuitem", { name: "任务日志" }));
    expect(
      await screen.findByRole("heading", { name: "任务日志" }),
    ).toBeInTheDocument();
    expect(screen.getByText("暂无任务")).toBeInTheDocument();

    await user.click(screen.getByRole("menuitem", { name: "审核" }));
    expect(
      await screen.findByRole("heading", { name: "审核队列" }),
    ).toBeInTheDocument();
    expect(screen.getByText("暂无待审核草稿")).toBeInTheDocument();

    await user.click(screen.getByRole("menuitem", { name: "商品" }));
    expect(
      await screen.findByRole("heading", { name: "商品列表" }),
    ).toBeInTheDocument();
    expect(screen.getByText("尚未导入商品")).toBeInTheDocument();

    await user.click(screen.getByRole("menuitem", { name: "成本" }));
    expect(
      await screen.findByRole("heading", { name: "成本" }),
    ).toBeInTheDocument();
    expect(screen.getByText("暂无成本记录")).toBeInTheDocument();
  });
});
