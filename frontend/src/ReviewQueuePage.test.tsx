import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, type ReviewDraft, getReviewQueue } from "./api";
import ReviewQueuePage from "./ReviewQueuePage";

vi.mock("./api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api")>()),
  getReviewQueue: vi.fn(),
}));

vi.mock("./auth", () => ({
  withAuthenticatedSession: <T,>(operation: (token: string) => Promise<T>) =>
    operation("saved-access-token"),
}));

const mockedGetReviewQueue = vi.mocked(getReviewQueue);

function draft(
  id: string,
  title: string,
  riskLevel: ReviewDraft["risk_level"],
  createdAt: string,
): ReviewDraft {
  return {
    id,
    tenant_id: "tenant-id",
    product_id: `product-${id}`,
    task_id: `task-${id}`,
    title,
    description: `${title} 描述`,
    meta_title: title,
    meta_description: "",
    alt_text: {},
    seo_tags: [],
    risk_level: riskLevel,
    status: "pending_review",
    created_at: createdAt,
    updated_at: createdAt,
  };
}

describe("ReviewQueuePage", () => {
  beforeEach(() => {
    mockedGetReviewQueue.mockReset();
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("shows drafts with their risk level in the server-sorted order", async () => {
    mockedGetReviewQueue.mockResolvedValue([
      draft("high", "High Product", "high", "2024-01-01T00:00:00Z"),
      draft("medium-old", "Medium Old", "medium", "2024-01-01T00:00:00Z"),
      draft("medium-new", "Medium New", "medium", "2024-01-01T00:00:01Z"),
      draft("low", "Low Product", "low", "2024-01-01T00:00:02Z"),
    ]);

    render(<ReviewQueuePage />);

    expect(
      await screen.findByRole("heading", { name: "审核队列" }),
    ).toBeInTheDocument();
    expect(screen.getByText("高风险")).toBeInTheDocument();
    expect(screen.getAllByText("中风险")).toHaveLength(2);
    expect(screen.getByText("低风险")).toBeInTheDocument();
    expect(mockedGetReviewQueue).toHaveBeenCalledWith("saved-access-token");

    const titles = screen
      .getAllByRole("heading", { level: 3 })
      .map((heading) => heading.textContent);
    expect(titles).toEqual([
      "High Product",
      "Medium Old",
      "Medium New",
      "Low Product",
    ]);
  });

  it("shows an empty state when there are no drafts to review", async () => {
    mockedGetReviewQueue.mockResolvedValue([]);

    render(<ReviewQueuePage />);

    expect(await screen.findByText("暂无待审核草稿")).toBeInTheDocument();
  });

  it("shows a failure state and retries loading the queue", async () => {
    mockedGetReviewQueue
      .mockRejectedValueOnce(new ApiError("加载失败", 503))
      .mockResolvedValueOnce([]);
    const user = userEvent.setup();

    render(<ReviewQueuePage />);

    expect(await screen.findByText("暂时无法加载审核队列")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /重\s*试/ }));

    expect(await screen.findByText("暂无待审核草稿")).toBeInTheDocument();
    expect(mockedGetReviewQueue).toHaveBeenCalledTimes(2);
  });

  it("notifies the shell when the review session has expired", async () => {
    mockedGetReviewQueue.mockRejectedValue(new ApiError("会话已过期", 401));
    const onSessionExpired = vi.fn();

    render(<ReviewQueuePage onSessionExpired={onSessionExpired} />);

    expect(await screen.findByText("暂时无法加载审核队列")).toBeInTheDocument();
    expect(onSessionExpired).toHaveBeenCalledOnce();
  });
});
