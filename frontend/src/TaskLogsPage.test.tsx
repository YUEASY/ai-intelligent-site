import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  type Task,
  type TaskTimeline,
  getTaskTimeline,
  getTasks,
} from "./api";
import TaskLogsPage from "./TaskLogsPage";

vi.mock("./api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api")>()),
  getTasks: vi.fn(),
  getTaskTimeline: vi.fn(),
}));

vi.mock("./auth", () => ({
  withAuthenticatedSession: <T,>(operation: (token: string) => Promise<T>) =>
    operation("saved-access-token"),
}));

const mockedGetTasks = vi.mocked(getTasks);
const mockedGetTimeline = vi.mocked(getTaskTimeline);

function task(overrides: Partial<Task> = {}): Task {
  return {
    id: "task-1",
    tenant_id: "tenant-id",
    kind: "product",
    operation_type: "update",
    changed_fields: ["title"],
    risk_level: "medium",
    status: "awaiting_review",
    last_error: null,
    product_id: "product-1",
    page_id: null,
    created_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-01T00:00:00Z",
    ...overrides,
  };
}

function timeline(overrides: Partial<TaskTimeline> = {}): TaskTimeline {
  return {
    task: task(),
    audit_log: [
      {
        id: "audit-1",
        tenant_id: "tenant-id",
        task_id: "task-1",
        actor: "admin@example.com",
        from_status: "pending",
        to_status: "running",
        occurred_at: "2024-01-01T00:00:00Z",
      },
      {
        id: "audit-2",
        tenant_id: "tenant-id",
        task_id: "task-1",
        actor: "admin@example.com",
        from_status: "running",
        to_status: "awaiting_review",
        occurred_at: "2024-01-01T00:00:01Z",
      },
    ],
    costs: [
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

describe("TaskLogsPage", () => {
  beforeEach(() => {
    mockedGetTasks.mockReset();
    mockedGetTimeline.mockReset();
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("lists tasks and renders the full lifecycle timeline on selection", async () => {
    mockedGetTasks.mockResolvedValue([task()]);
    mockedGetTimeline.mockResolvedValue(timeline());

    const user = userEvent.setup();
    render(<TaskLogsPage />);

    expect(
      await screen.findByRole("heading", { name: "任务日志" }),
    ).toBeInTheDocument();
    await user.click(screen.getByText("商品生成"));

    expect(await screen.findByText("全链路")).toBeInTheDocument();
    expect(screen.getByText("待执行 → 执行中")).toBeInTheDocument();
    expect(screen.getByText("执行中 → 待审核")).toBeInTheDocument();
    expect(screen.getByText(/fake:small · 10 输入 \/ 20 输出 Token/)).toBeInTheDocument();
  });

  it("shows the failed reason on a failed task timeline", async () => {
    mockedGetTasks.mockResolvedValue([
      task({ status: "failed", last_error: "SEO 写入失败" }),
    ]);
    mockedGetTimeline.mockResolvedValue(
      timeline({ task: task({ status: "failed", last_error: "SEO 写入失败" }) }),
    );

    const user = userEvent.setup();
    render(<TaskLogsPage />);

    await user.click(await screen.findByText("失败"));
    expect(await screen.findByText("SEO 写入失败")).toBeInTheDocument();
  });

  it("shows an empty state when there are no tasks", async () => {
    mockedGetTasks.mockResolvedValue([]);

    render(<TaskLogsPage />);

    expect(await screen.findByText("暂无任务")).toBeInTheDocument();
  });

  it("shows an error state and retries loading", async () => {
    mockedGetTasks.mockRejectedValueOnce(new Error("network"));
    mockedGetTasks.mockResolvedValueOnce([task()]);

    const user = userEvent.setup();
    render(<TaskLogsPage />);

    expect(
      await screen.findByText("暂时无法加载任务日志"),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /重\s*试/ }));

    await waitFor(() => expect(mockedGetTasks).toHaveBeenCalledTimes(2));
    expect(await screen.findByText("商品生成")).toBeInTheDocument();
  });
});
