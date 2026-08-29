import { Alert, Button, Card, Empty, Space, Spin, Tag, Typography } from "antd";
import { useCallback, useEffect, useState } from "react";

import { ApiError, type ReviewDraft, type RiskLevel, getReviewQueue } from "./api";
import { withAuthenticatedSession } from "./auth";
import "./ReviewQueuePage.css";

const { Text, Title } = Typography;

const riskMeta: Record<RiskLevel, { label: string; color: string }> = {
  high: { label: "高风险", color: "red" },
  medium: { label: "中风险", color: "orange" },
  low: { label: "低风险", color: "green" },
};

export default function ReviewQueuePage({
  onSessionExpired,
}: {
  onSessionExpired?: () => void;
}) {
  const [drafts, setDrafts] = useState<ReviewDraft[]>();
  const [loadError, setLoadError] = useState(false);

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

  return (
    <section className="review-queue-page">
      <Space orientation="vertical" size={8}>
        <Text className="page-eyebrow">HUMAN REVIEW</Text>
        <Title>审核队列</Title>
        <Text type="secondary">按商户、风险等级与创建时间排序，高风险优先处理。</Text>
      </Space>

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
                <Space wrap>
                  <Tag color={riskMeta[draft.risk_level].color}>
                    {riskMeta[draft.risk_level].label}
                  </Tag>
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
              </Space>
            </Card>
          ))}
        </div>
      )}
    </section>
  );
}
