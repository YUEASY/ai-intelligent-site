import {
  Alert,
  Button,
  Card,
  Empty,
  Space,
  Spin,
  Statistic,
  Table,
  Tag,
  Typography,
} from "antd";
import { useCallback, useEffect, useState } from "react";

import {
  ApiError,
  type CostOverview,
  getCostOverview,
} from "./api";
import { withAuthenticatedSession } from "./auth";
import { formatUsd } from "./format";

const { Text, Title } = Typography;

export default function CostPage({
  onSessionExpired,
}: {
  onSessionExpired?: () => void;
}) {
  const [overview, setOverview] = useState<CostOverview>();
  const [loadError, setLoadError] = useState(false);

  const loadCost = useCallback(async () => {
    try {
      setOverview(
        await withAuthenticatedSession((token) => getCostOverview(token)),
      );
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) {
        onSessionExpired?.();
      }
      setLoadError(true);
    }
  }, [onSessionExpired]);

  useEffect(() => {
    void Promise.resolve().then(loadCost);
  }, [loadCost]);

  return (
    <section>
      <Space orientation="vertical" size={8}>
        <Text className="page-eyebrow">COST ATTRIBUTION</Text>
        <Title>成本</Title>
        <Text type="secondary">
          单商户与单任务的模型、Token 与 API 成本归因。
        </Text>
      </Space>

      {loadError && (
        <Alert
          showIcon
          type="error"
          message="暂时无法加载成本数据"
          action={
            <Button
              onClick={() => {
                setLoadError(false);
                void loadCost();
              }}
            >
              重试
            </Button>
          }
        />
      )}

      {overview === undefined && !loadError ? (
        <div style={{ padding: 32, textAlign: "center" }}><Spin /></div>
      ) : overview ? (
        <>
          <Space wrap size={16} style={{ marginTop: 16 }}>
            <Card>
              <Statistic
                title="今日 API 成本"
                value={formatUsd(overview.daily_cost)}
              />
              <Text type="secondary">
                阈值 {formatUsd(overview.daily_threshold)}
              </Text>
            </Card>
            <Card>
              <Statistic
                title="累计 API 成本"
                value={formatUsd(overview.total_cost)}
              />
            </Card>
            <Card>
              <Statistic title="累计 Token" value={overview.total_tokens} />
            </Card>
          </Space>

          {overview.tasks.length === 0 ? (
            <Card style={{ marginTop: 16 }}>
              <Empty description="暂无成本记录" />
            </Card>
          ) : (
            <Table
              rowKey="id"
              dataSource={overview.tasks}
              pagination={false}
              style={{ marginTop: 16 }}
              columns={[
                {
                  title: "任务",
                  dataIndex: "task_id",
                  render: (taskId: string) => <Text code>{taskId.slice(0, 8)}</Text>,
                },
                {
                  title: "模型",
                  dataIndex: "model",
                },
                {
                  title: "层级",
                  dataIndex: "tier",
                  render: (tier: "small" | "large") => (
                    <Tag color={tier === "large" ? "purple" : "cyan"}>
                      {tier === "large" ? "大模型" : "小模型"}
                    </Tag>
                  ),
                },
                {
                  title: "输入 Token",
                  dataIndex: "input_tokens",
                },
                {
                  title: "输出 Token",
                  dataIndex: "output_tokens",
                },
                {
                  title: "API 成本",
                  dataIndex: "api_cost",
                  render: (cost: string) => formatUsd(cost),
                },
                {
                  title: "时间",
                  dataIndex: "created_at",
                  render: (value: string) => new Date(value).toLocaleString(),
                },
              ]}
            />
          )}
        </>
      ) : null}
    </section>
  );
}
