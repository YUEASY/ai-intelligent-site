import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { type CostOverview, getCostOverview } from "./api";
import CostPage from "./CostPage";

vi.mock("./api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api")>()),
  getCostOverview: vi.fn(),
}));

vi.mock("./auth", () => ({
  withAuthenticatedSession: <T,>(operation: (token: string) => Promise<T>) =>
    operation("saved-access-token"),
}));

const mockedGetCost = vi.mocked(getCostOverview);

function overview(overrides: Partial<CostOverview> = {}): CostOverview {
  return {
    tenant_id: "tenant-id",
    daily_cost: "0.000200",
    daily_threshold: "6.00",
    total_cost: "0.000400",
    total_tokens: 60,
    tasks: [
      {
        id: "cost-1",
        tenant_id: "tenant-id",
        task_id: "task-1",
        tier: "small",
        model: "fake:small",
        input_tokens: 10,
        output_tokens: 20,
        api_cost: "0.000005",
        created_at: "2024-01-01T00:00:00Z",
      },
    ],
    ...overrides,
  };
}

describe("CostPage", () => {
  beforeEach(() => {
    mockedGetCost.mockReset();
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("shows merchant cost and per-task model usage", async () => {
    mockedGetCost.mockResolvedValue(overview());

    render(<CostPage />);

    expect(
      await screen.findByRole("heading", { name: "成本" }),
    ).toBeInTheDocument();
    expect(screen.getByText("$0.000200")).toBeInTheDocument();
    expect(screen.getByText("$0.000400")).toBeInTheDocument();
    expect(screen.getByText("60")).toBeInTheDocument();
    expect(screen.getByText("fake:small")).toBeInTheDocument();
  });

  it("shows an empty state when there is no cost data", async () => {
    mockedGetCost.mockResolvedValue(overview({ tasks: [] }));

    render(<CostPage />);

    expect(await screen.findByText("暂无成本记录")).toBeInTheDocument();
  });

  it("does not show zero cost when loading fails", async () => {
    mockedGetCost.mockRejectedValueOnce(new Error("network"));
    mockedGetCost.mockResolvedValueOnce(overview());

    const user = userEvent.setup();
    render(<CostPage />);

    expect(await screen.findByText("暂时无法加载成本数据")).toBeInTheDocument();
    expect(screen.queryByText("$0.000000")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /重\s*试/ }));
    await waitFor(() => expect(mockedGetCost).toHaveBeenCalledTimes(2));
    expect(await screen.findByText("$0.000200")).toBeInTheDocument();
  });
});
