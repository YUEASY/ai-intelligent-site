import {
  Alert,
  Button,
  Card,
  Checkbox,
  Empty,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Spin,
  Tag,
  Typography,
} from "antd";
import { useCallback, useEffect, useState } from "react";

import {
  ApiError,
  type RejectionReason,
  type ReviewDraft,
  type RiskLevel,
  approveDrafts,
  editDraft,
  getReviewQueue,
  publishDraft,
  regenerateDraft,
  rejectDrafts,
} from "./api";
import { withAuthenticatedSession } from "./auth";
import "./ReviewQueuePage.css";

const { Text, Title } = Typography;

const riskMeta: Record<RiskLevel, { label: string; color: string }> = {
  high: { label: "高风险", color: "red" },
  medium: { label: "中风险", color: "orange" },
  low: { label: "低风险", color: "green" },
};

const rejectionReasons: { value: RejectionReason; label: string }[] = [
  { value: "fact_error", label: "事实错误" },
  { value: "expression", label: "表达问题" },
  { value: "seo", label: "SEO" },
  { value: "brand_style", label: "品牌风格" },
  { value: "other", label: "其他" },
];

type Notice = { type: "success" | "error"; message: string };

export default function ReviewQueuePage({
  onSessionExpired,
}: {
  onSessionExpired?: () => void;
}) {
  const [drafts, setDrafts] = useState<ReviewDraft[]>();
  const [loadError, setLoadError] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<Notice>();
  const [rejecting, setRejecting] = useState<ReviewDraft[]>();
  const [editing, setEditing] = useState<ReviewDraft>();
  const [editForm] = Form.useForm();

  const loadQueue = useCallback(async () => {
    try {
      const loadedDrafts = await withAuthenticatedSession((token) =>
        getReviewQueue(token),
      );
      setDrafts(loadedDrafts);
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) {
        onSessionExpired?.();
      }
      setLoadError(true);
    }
  }, [onSessionExpired]);

  useEffect(() => {
    void Promise.resolve().then(loadQueue);
  }, [loadQueue]);

  const run = async (
    operation: (token: string) => Promise<unknown>,
    success: string,
  ) => {
    setBusy(true);
    setNotice(undefined);
    try {
      await withAuthenticatedSession(operation);
      setNotice({ type: "success", message: success });
      setSelected(new Set());
      await loadQueue();
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) {
        onSessionExpired?.();
      }
      setNotice({
        type: "error",
        message: cause instanceof ApiError ? cause.message : "操作失败，请稍后重试",
      });
    } finally {
      setBusy(false);
    }
  };

  const approveSelected = () => {
    if (selected.size === 0) return;
    void run(
      (token: string) => approveDrafts(token, Array.from(selected)),
      `已通过 ${selected.size} 个草稿`,
    );
  };

  const rejectSelected = () => {
    if (selected.size === 0) return;
    setRejecting(drafts?.filter((draft) => selected.has(draft.id)) ?? []);
  };

  const submitReject = (reason: RejectionReason) => {
    const ids = (rejecting ?? []).map((draft) => draft.id);
    setRejecting(undefined);
    void run(
      (token: string) => rejectDrafts(token, ids, reason),
      `已驳回 ${ids.length} 个草稿`,
    );
  };

  const submitEdit = async (values: {
    title?: string;
    description?: string;
    meta_title?: string;
    meta_description?: string;
    seo_tags?: string;
  }) => {
    if (!editing) return;
    setBusy(true);
    setNotice(undefined);
    try {
      await withAuthenticatedSession((token) =>
        editDraft(token, editing.id, {
          ...values,
          seo_tags: values.seo_tags
            ? values.seo_tags.split(",").map((tag) => tag.trim()).filter(Boolean)
            : undefined,
        }),
      );
      setEditing(undefined);
      setNotice({ type: "success", message: "草稿已修改" });
      await loadQueue();
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) {
        onSessionExpired?.();
      }
      setNotice({
        type: "error",
        message: cause instanceof ApiError ? cause.message : "修改失败，请稍后重试",
      });
    } finally {
      setBusy(false);
    }
  };

  const regenerate = (draft: ReviewDraft) => {
    void run(
      (token: string) => regenerateDraft(token, draft.id),
      `已为 ${draft.title} 触发重新生成`,
    );
  };

  const publish = (draft: ReviewDraft) => {
    void run(
      (token: string) => publishDraft(token, draft.id, true),
      `已发布 ${draft.title}`,
    );
  };

  const toggleSelected = (draftId: string, checked: boolean) => {
    setSelected((current) => {
      const next = new Set(current);
      if (checked) next.add(draftId);
      else next.delete(draftId);
      return next;
    });
  };

  return (
    <section className="review-queue-page">
      <Space orientation="vertical" size={8}>
        <Text className="page-eyebrow">HUMAN REVIEW</Text>
        <Title>审核队列</Title>
        <Text type="secondary">按商户、风险等级与创建时间排序，高风险优先处理。</Text>
      </Space>

      {notice && (
        <Alert showIcon type={notice.type} message={notice.message} />
      )}

      {loadError && (
        <Alert
          showIcon
          type="error"
          message="暂时无法加载审核队列"
          action={
            <Button
              onClick={() => {
                setLoadError(false);
                void loadQueue();
              }}
            >
              重试
            </Button>
          }
        />
      )}

      {drafts !== undefined && drafts.length > 0 && (
        <Space wrap>
          <Button
            type="primary"
            disabled={selected.size === 0}
            loading={busy}
            onClick={approveSelected}
          >
            批量通过
          </Button>
          <Button
            danger
            disabled={selected.size === 0}
            loading={busy}
            onClick={rejectSelected}
          >
            批量驳回
          </Button>
        </Space>
      )}

      {drafts === undefined && !loadError ? (
        <div className="review-queue-loading"><Spin /></div>
      ) : drafts?.length === 0 ? (
        <Card className="review-queue-empty">
          <Empty description="暂无待审核草稿" />
        </Card>
      ) : (
        <div className="review-draft-list">
          {drafts?.map((draft) => (
            <Card key={draft.id} className="review-draft-card" variant="borderless">
              <Space orientation="vertical" size={8}>
                <Space wrap align="start">
                  {draft.status === "pending_review" && (
                    <Checkbox
                      aria-label={`选择 ${draft.title}`}
                      checked={selected.has(draft.id)}
                      onChange={(event) =>
                        toggleSelected(draft.id, event.target.checked)
                      }
                    />
                  )}
                  <Tag color={riskMeta[draft.risk_level].color}>
                    {riskMeta[draft.risk_level].label}
                  </Tag>
                  {draft.status === "approved" && <Tag color="blue">已通过</Tag>}
                  <Text type="secondary">
                    {new Date(draft.created_at).toLocaleString()}
                  </Text>
                </Space>
                <Title level={3}>{draft.title}</Title>
                <Text>{draft.description}</Text>
                {draft.seo_tags.length > 0 && (
                  <Space wrap>
                    {draft.seo_tags.map((tag) => <Tag key={tag}>{tag}</Tag>)}
                  </Space>
                )}
                <Space wrap>
                  {draft.status === "approved" ? (
                    <Popconfirm
                      title="确认发布到 Shopify？"
                      description="发布属于高风险操作，将写入商户店铺并生成版本快照。"
                      okText="确认发布"
                      cancelText="取消"
                      onConfirm={() => publish(draft)}
                    >
                      <Button type="primary" disabled={busy}>
                        发布
                      </Button>
                    </Popconfirm>
                  ) : (
                    <>
                      <Button disabled={busy} onClick={() => setEditing(draft)}>
                        编辑
                      </Button>
                      <Button disabled={busy} onClick={() => regenerate(draft)}>
                        重生成
                      </Button>
                    </>
                  )}
                </Space>
              </Space>
            </Card>
          ))}
        </div>
      )}

      <Modal
        title="驳回原因"
        open={rejecting !== undefined}
        onCancel={() => setRejecting(undefined)}
        footer={null}
        destroyOnHidden
      >
        <RejectForm
          count={(rejecting ?? []).length}
          onSubmit={submitReject}
        />
      </Modal>

      <Modal
        title={editing ? `编辑 ${editing.title}` : "编辑草稿"}
        open={editing !== undefined}
        onCancel={() => setEditing(undefined)}
        onOk={() => editForm.submit()}
        okText="保存"
        cancelText="取消"
        confirmLoading={busy}
        destroyOnHidden
      >
        <Form
          form={editForm}
          layout="vertical"
          initialValues={
            editing
              ? {
                  title: editing.title,
                  description: editing.description,
                  meta_title: editing.meta_title,
                  meta_description: editing.meta_description,
                  seo_tags: editing.seo_tags.join(", "),
                }
              : undefined
          }
          onFinish={submitEdit}
        >
          <Form.Item label="标题" name="title">
            <Input />
          </Form.Item>
          <Form.Item label="描述" name="description">
            <Input.TextArea rows={4} />
          </Form.Item>
          <Form.Item label="Meta 标题" name="meta_title">
            <Input />
          </Form.Item>
          <Form.Item label="Meta 描述" name="meta_description">
            <Input.TextArea rows={2} />
          </Form.Item>
          <Form.Item label="SEO 标签（逗号分隔）" name="seo_tags">
            <Input />
          </Form.Item>
        </Form>
      </Modal>
    </section>
  );
}

function RejectForm({
  count,
  onSubmit,
}: {
  count: number;
  onSubmit: (reason: RejectionReason) => void;
}) {
  const [reason, setReason] = useState<RejectionReason>("other");

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Text type="secondary">将为 {count} 个草稿记录结构化驳回原因。</Text>
      <Select
        aria-label="驳回原因"
        value={reason}
        onChange={(value) => setReason(value)}
        options={rejectionReasons}
        style={{ width: "100%" }}
      />
      <Button danger block onClick={() => onSubmit(reason)}>
        确认驳回
      </Button>
    </Space>
  );
}
