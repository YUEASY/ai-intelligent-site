import {
  Alert,
  Button,
  Card,
  Empty,
  Space,
  Spin,
  Statistic,
  Tag,
  Typography,
} from "antd";
import { useCallback, useEffect, useState } from "react";

import {
  ApiError,
  type AlertKind,
  type DashboardMetrics,
  acknowledgeAlert,
  getDashboardMetrics,
} from "./api";
import { withAuthenticatedSession } from "./auth";
import { formatUsd } from "./format";

const { Text, Title } = Typography;

const alertKindMeta: Record<AlertKind, { label: string; color: string }> = {
  task_failed: { label: "任务失败", color: "red" },
  dead_letter: { label: "死信", color: "volcano" },
  cost_threshold: { label: "成本超阈值", color: "orange" },
  worker_health: { label: "服务健康", color: "purple" },
};

function formatRate(rate: number | null): string {
  return rate === null ? "—" : `${(rate * 100).toFixed(1)}%`;
}

export default function DashboardPage({
  onSessionExpired,
}: {
  onSessionExpired?: () => void;
}) {
  const [metrics, setMetrics] = useState<DashboardMetrics>();
  const [loadError, setLoadError] = useState(false);
  const [acknowledging, setAcknowledging] = useState(false);

  const loadMetrics = useCallback(async () => {
    try {
      setMetrics(
        await withAuthenticatedSession((token) => getDashboardMetrics(token)),
      );
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) {
        onSessionExpired?.();
      }
      setLoadError(true);
    }
  }, [onSessionExpired]);

  useEffect(() => {
    void Promise.resolve().then(loadMetrics);
  }, [loadMetrics]);

  const acknowledge = async (alertId: string) => {
    setAcknowledging(true);
    try {
      await withAuthenticatedSession((token) =>
        acknowledgeAlert(token, alertId),
      );
      await loadMetrics();
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) {
        onSessionExpired?.();
      }
    } finally {
      setAcknowledging(false);
    }
  };

  if (loadError) {
    return (
      <section>
        <Space orientation="vertical" size={8}>
          <Text className="page-eyebrow">OPERATIONS OVERVIEW</Text>
          <Title>运营概览</Title>
        </Space>
        <Alert
          showIcon
          type="error"
          message="暂时无法加载运营概览数据"
          action={
            <Button
              onClick={() => {
                setLoadError(false);
                void loadMetrics();
              }}
            >
              重试
            </Button>
          }
        />
      </section>
    );
  }

  if (metrics === undefined) {
    return (
      <div style={{ padding: 32, textAlign: "center" }}>
        <Spin />
      </div>
    );
  }

  return (
    <section>
      <Space orientation="vertical" size={8}>
        <Text className="page-eyebrow">OPERATIONS OVERVIEW</Text>
        <Title>运营概览</Title>
        <Text type="secondary">
          任务成功率、Token 趋势与成本来自真实 API，仅作分析展示、不实时告警。
        </Text>
      </Space>

      <Space wrap size={16} style={{ marginTop: 16 }}>
        <Card>
          <Statistic title="任务总数" value={metrics.tasks_total} />
        </Card>
        <Card>
          <Statistic title="任务成功率" value={formatRate(metrics.success_rate)} />
        </Card>
        <Card>
          <Statistic title="累计 Token" value={metrics.tokens_total} />
        </Card>
        <Card>
          <Statistic
            title="累计 API 成本"
            value={formatUsd(metrics.cost_total)}
          />
        </Card>
      </Space>

      <Card title="开放告警" style={{ marginTop: 16 }}>
        {metrics.open_alerts.length === 0 ? (
          <Empty description="暂无开放告警" />
        ) : (
          <Space direction="vertical" size={12} style={{ width: "100%" }}>
            {metrics.open_alerts.map((alert) => (
              <Space
                key={alert.id}
                align="start"
                style={{ width: "100%", justifyContent: "space-between" }}
              >
                <Space direction="vertical" size={2}>
                  <Tag color={alertKindMeta[alert.kind].color}>
                    {alertKindMeta[alert.kind].label}
                  </Tag>
                  <Text>{alert.message}</Text>
                  <Text type="secondary">
                    {new Date(alert.created_at).toLocaleString()}
                  </Text>
                </Space>
                <Button
                  size="small"
                  loading={acknowledging}
                  onClick={() => void acknowledge(alert.id)}
                >
                  确认
                </Button>
              </Space>
            ))}
          </Space>
        )}
      </Card>

      <Card title="Token 趋势" style={{ marginTop: 16 }}>
        {metrics.daily.length === 0 ? (
          <Empty description="暂无 Token 记录" />
        ) : (
          <Space direction="vertical" size={4}>
            {metrics.daily.map((day) => (
              <Text key={day.date} type="secondary">
                {day.date} · {day.tokens} Token · {formatUsd(day.cost)}
              </Text>
            ))}
          </Space>
        )}
      </Card>
    </section>
  );
}
