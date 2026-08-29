import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  type PublishResult,
  type ReviewDraft,
  type Task,
  approveDrafts,
  editDraft,
  getReviewQueue,
  publishDraft,
  regenerateDraft,
  rejectDrafts,
} from "./api";
import ReviewQueuePage from "./ReviewQueuePage";

vi.mock("./api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api")>()),
  getReviewQueue: vi.fn(),
  approveDrafts: vi.fn(),
  rejectDrafts: vi.fn(),
  editDraft: vi.fn(),
  regenerateDraft: vi.fn(),
  publishDraft: vi.fn(),
}));

vi.mock("./auth", () => ({
  withAuthenticatedSession: <T,>(operation: (token: string) => Promise<T>) =>
    operation("saved-access-token"),
}));

const mockedGetReviewQueue = vi.mocked(getReviewQueue);
const mockedApproveDrafts = vi.mocked(approveDrafts);
const mockedRejectDrafts = vi.mocked(rejectDrafts);
const mockedEditDraft = vi.mocked(editDraft);
const mockedRegenerateDraft = vi.mocked(regenerateDraft);
const mockedPublishDraft = vi.mocked(publishDraft);

function draft(
  id: string,
  title: string,
  riskLevel: ReviewDraft["risk_level"],
  createdAt: string,
  status: ReviewDraft["status"] = "pending_review",
  kind: ReviewDraft["kind"] = "product",
  taskStatus = "awaiting_review",
): ReviewDraft {
  return {
    id,
    tenant_id: "tenant-id",
    product_id: `product-${id}`,
    task_id: `task-${id}`,
    title,
    description: `${title} 描述`,
    meta_title: title,
    meta_description: `${title} 的 Meta 描述`,
    alt_text: {},
    seo_tags: [],
    risk_level: riskLevel,
    status,
    rejection_reason: null,
    kind,
    task_status: taskStatus,
    created_at: createdAt,
    updated_at: createdAt,
  };
}

describe("ReviewQueuePage", () => {
  beforeEach(() => {
    mockedGetReviewQueue.mockReset();
    mockedApproveDrafts.mockReset();
    mockedRejectDrafts.mockReset();
    mockedEditDraft.mockReset();
    mockedRegenerateDraft.mockReset();
    mockedPublishDraft.mockReset();
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

  it("batch approves selected drafts", async () => {
    mockedGetReviewQueue.mockResolvedValueOnce([
      draft("high", "High Product", "high", "2024-01-01T00:00:00Z"),
    ]);
    mockedGetReviewQueue.mockResolvedValue([]);
    mockedApproveDrafts.mockResolvedValue([]);
    const user = userEvent.setup();

    render(<ReviewQueuePage />);
    await screen.findByText("High Product");

    await user.click(screen.getByRole("checkbox", { name: "选择 High Product" }));
    await user.click(screen.getByRole("button", { name: "批量通过" }));

    await waitFor(() =>
      expect(mockedApproveDrafts).toHaveBeenCalledWith("saved-access-token", [
        "high",
      ]),
    );
  });

  it("keeps approved drafts visible with a publish-only action", async () => {
    mockedGetReviewQueue.mockResolvedValue([
      draft(
        "approved",
        "Approved Product",
        "medium",
        "2024-01-01T00:00:00Z",
        "approved",
      ),
    ]);

    render(<ReviewQueuePage />);

    await screen.findByText("Approved Product");
    expect(screen.getByText("已通过")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /发\s*布/ })).toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /编\s*辑/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "重生成" })).not.toBeInTheDocument();
  });

  it("does not offer publish before a draft has been approved", async () => {
    mockedGetReviewQueue.mockResolvedValue([
      draft("pending", "Pending Product", "high", "2024-01-01T00:00:00Z"),
    ]);

    render(<ReviewQueuePage />);

    await screen.findByText("Pending Product");
    expect(screen.queryByRole("button", { name: /发\s*布/ })).not.toBeInTheDocument();
  });

  it("batch rejects selected drafts with a structured reason", async () => {
    mockedGetReviewQueue.mockResolvedValueOnce([
      draft("high", "High Product", "high", "2024-01-01T00:00:00Z"),
    ]);
    mockedGetReviewQueue.mockResolvedValue([]);
    mockedRejectDrafts.mockResolvedValue([]);
    const user = userEvent.setup();

    render(<ReviewQueuePage />);
    await screen.findByText("High Product");

    await user.click(screen.getByRole("checkbox", { name: "选择 High Product" }));
    await user.click(screen.getByRole("button", { name: "批量驳回" }));
    await user.click(await screen.findByText("确认驳回"));

    await waitFor(() =>
      expect(mockedRejectDrafts).toHaveBeenCalledWith(
        "saved-access-token",
        ["high"],
        "other",
      ),
    );
  });

  it("edits a draft and saves the changes", async () => {
    mockedGetReviewQueue.mockResolvedValue([
      draft("high", "High Product", "high", "2024-01-01T00:00:00Z"),
    ]);
    mockedEditDraft.mockResolvedValue(
      draft("high", "High Product", "high", "2024-01-01T00:00:00Z"),
    );
    const user = userEvent.setup();

    render(<ReviewQueuePage />);
    await screen.findByText("High Product");

    await user.click(screen.getByRole("button", { name: /编\s*辑/ }));
    await user.clear(await screen.findByLabelText("标题"));
    await user.type(screen.getByLabelText("标题"), "Fixed Title");
    await user.click(screen.getByRole("button", { name: /保\s*存/ }));

    await waitFor(() =>
      expect(mockedEditDraft).toHaveBeenCalledWith(
        "saved-access-token",
        "high",
        expect.objectContaining({ title: "Fixed Title" }),
      ),
    );
  });

  it("regenerates a draft on demand", async () => {
    mockedGetReviewQueue.mockResolvedValue([
      draft("high", "High Product", "high", "2024-01-01T00:00:00Z"),
    ]);
    mockedRegenerateDraft.mockResolvedValue({} as Task);
    const user = userEvent.setup();

    render(<ReviewQueuePage />);
    await screen.findByText("High Product");

    await user.click(screen.getByRole("button", { name: "重生成" }));

    await waitFor(() =>
      expect(mockedRegenerateDraft).toHaveBeenCalledWith(
        "saved-access-token",
        "high",
      ),
    );
  });

  it("confirms before publishing a draft to Shopify", async () => {
    mockedGetReviewQueue.mockResolvedValue([
      draft(
        "high",
        "High Product",
        "high",
        "2024-01-01T00:00:00Z",
        "approved",
      ),
    ]);
    mockedPublishDraft.mockResolvedValue({} as PublishResult);
    const user = userEvent.setup();

    render(<ReviewQueuePage />);
    await screen.findByText("High Product");

    await user.click(screen.getByRole("button", { name: /发\s*布/ }));
    await user.click(await screen.findByRole("button", { name: "确认发布" }));

    await waitFor(() =>
      expect(mockedPublishDraft).toHaveBeenCalledWith(
        "saved-access-token",
        "high",
        true,
      ),
    );
  });

  it("shows SEO suggestions with their task type and status", async () => {
    mockedGetReviewQueue.mockResolvedValue([
      {
        ...draft(
          "seo",
          "Classic T-Shirt",
          "low",
          "2024-01-01T00:00:00Z",
          "pending_review",
          "seo",
          "awaiting_review",
        ),
        meta_title: "Optimized Meta Title",
        meta_description: "Optimized meta description",
        alt_text: { "front.jpg": "Optimized alt" },
      },
    ]);

    render(<ReviewQueuePage />);

    await screen.findByText("SEO 优化");
    expect(screen.getByText("等待审核")).toBeInTheDocument();
    expect(screen.getByText("SEO 优化建议")).toBeInTheDocument();
    expect(screen.getByText(/Optimized Meta Title/)).toBeInTheDocument();
  });

  it("distinguishes the four SEO lifecycle states", async () => {
    mockedGetReviewQueue.mockResolvedValue([
      draft("suggested", "Suggested", "low", "2024-01-01T00:00:00Z", "pending_review", "seo", "running"),
      draft("awaiting", "Awaiting", "low", "2024-01-01T00:00:01Z", "pending_review", "seo", "awaiting_review"),
      draft("written", "Written", "low", "2024-01-01T00:00:02Z", "published", "seo", "published"),
      draft("failed", "Failed", "low", "2024-01-01T00:00:03Z", "pending_review", "seo", "failed"),
    ]);

    render(<ReviewQueuePage />);

    expect(await screen.findByText("建议已生成")).toBeInTheDocument();
    expect(screen.getByText("等待审核")).toBeInTheDocument();
    expect(screen.getByText("已写入 Shopify")).toBeInTheDocument();
    expect(screen.getByText("写入失败")).toBeInTheDocument();
  });

  it("does not offer review actions for written or failed SEO items", async () => {
    mockedGetReviewQueue.mockResolvedValue([
      draft("written", "Written", "low", "2024-01-01T00:00:00Z", "published", "seo", "published"),
      draft("failed", "Failed", "low", "2024-01-01T00:00:01Z", "pending_review", "seo", "failed"),
    ]);

    render(<ReviewQueuePage />);

    await screen.findByText("已写入 Shopify");
    expect(screen.queryByRole("button", { name: /发\s*布/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /编\s*辑/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  });
});
