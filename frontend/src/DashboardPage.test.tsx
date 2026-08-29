import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  type DashboardMetrics,
  acknowledgeAlert,
  getDashboardMetrics,
} from "./api";
import DashboardPage from "./DashboardPage";

vi.mock("./api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api")>()),
  getDashboardMetrics: vi.fn(),
  acknowledgeAlert: vi.fn(),
}));

vi.mock("./auth", () => ({
  withAuthenticatedSession: <T,>(operation: (token: string) => Promise<T>) =>
    operation("saved-access-token"),
}));

const mockedGetMetrics = vi.mocked(getDashboardMetrics);
const mockedAcknowledge = vi.mocked(acknowledgeAlert);

function metrics(overrides: Partial<DashboardMetrics> = {}): DashboardMetrics {
  return {
    tasks_total: 5,
    tasks_published: 3,
    tasks_failed: 1,
    success_rate: 0.75,
    tokens_total: 120,
    cost_total: "0.000400",
    daily: [{ date: "2024-01-01", tokens: 120, cost: "0.000400" }],
    open_alerts: [
      {
        id: "alert-1",
        tenant_id: "tenant-id",
        kind: "task_failed",
        status: "open",
        message: "Task failed: boom",
        task_id: "task-1",
        dedup_key: "task:task-1",
        created_at: "2024-01-01T00:00:00Z",
        acknowledged_at: null,
      },
    ],
    ...overrides,
  };
}

describe("DashboardPage", () => {
  beforeEach(() => {
    mockedGetMetrics.mockReset();
    mockedAcknowledge.mockReset();
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("shows real metrics and open alerts", async () => {
    mockedGetMetrics.mockResolvedValue(metrics());

    render(<DashboardPage />);

    expect(
      await screen.findByRole("heading", { name: "运营概览" }),
    ).toBeInTheDocument();
    expect(screen.getByText("5")).toBeInTheDocument();
    expect(screen.getByText("75.0%")).toBeInTheDocument();
    expect(screen.getByText("Task failed: boom")).toBeInTheDocument();
    expect(screen.getByText("任务失败")).toBeInTheDocument();
  });

  it("shows dead-letter alerts", async () => {
    mockedGetMetrics.mockResolvedValue(
      metrics({
        open_alerts: [
          {
            id: "alert-dl",
            tenant_id: "tenant-id",
            kind: "dead_letter",
            status: "open",
            message: "Webhook event reached the dead letter",
            task_id: null,
            dedup_key: "webhook:event-1",
            created_at: "2024-01-01T00:00:00Z",
            acknowledged_at: null,
          },
        ],
      }),
    );

    render(<DashboardPage />);

    expect(await screen.findByText("死信")).toBeInTheDocument();
    expect(
      screen.getByText("Webhook event reached the dead letter"),
    ).toBeInTheDocument();
  });

  it("acknowledges an alert and reloads metrics", async () => {
    mockedGetMetrics.mockResolvedValueOnce(metrics());
    mockedGetMetrics.mockResolvedValueOnce(metrics({ open_alerts: [] }));
    mockedAcknowledge.mockResolvedValue(metrics().open_alerts[0]);

    const user = userEvent.setup();
    render(<DashboardPage />);

    await user.click(
      await screen.findByRole("button", { name: /确\s*认/ }),
    );

    await waitFor(() => expect(mockedAcknowledge).toHaveBeenCalledWith(
      "saved-access-token",
      "alert-1",
    ));
    expect(await screen.findByText("暂无开放告警")).toBeInTheDocument();
  });

  it("does not render zero metrics as healthy when loading fails", async () => {
    mockedGetMetrics.mockRejectedValueOnce(new Error("network"));
    mockedGetMetrics.mockResolvedValueOnce(metrics());

    const user = userEvent.setup();
    render(<DashboardPage />);

    expect(
      await screen.findByText("暂时无法加载运营概览数据"),
    ).toBeInTheDocument();
    expect(screen.queryByText("任务总数")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /重\s*试/ }));
    await waitFor(() => expect(mockedGetMetrics).toHaveBeenCalledTimes(2));
    expect(await screen.findByText("任务总数")).toBeInTheDocument();
  });
});
