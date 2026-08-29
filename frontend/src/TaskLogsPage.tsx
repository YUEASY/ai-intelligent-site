import {
  Alert,
  Button,
  Card,
  Empty,
  Space,
  Spin,
  Table,
  Tag,
  Timeline,
  Typography,
} from "antd";
import { useCallback, useEffect, useState } from "react";

import {
  ApiError,
  type Task,
  type TaskStatus,
  type TaskTimeline,
  getTaskTimeline,
  getTasks,
} from "./api";
import { withAuthenticatedSession } from "./auth";
import { formatUsd } from "./format";

const { Text, Title } = Typography;

const statusMeta: Record<TaskStatus, { label: string; color: string }> = {
  pending: { label: "待执行", color: "default" },
  running: { label: "执行中", color: "processing" },
  suggested: { label: "建议已生成", color: "cyan" },
  awaiting_review: { label: "待审核", color: "orange" },
  approved: { label: "已通过", color: "blue" },
  rejected: { label: "已驳回", color: "volcano" },
  published: { label: "已发布", color: "green" },
  failed: { label: "失败", color: "red" },
  rolled_back: { label: "已回滚", color: "purple" },
};

export default function TaskLogsPage({
  onSessionExpired,
}: {
  onSessionExpired?: () => void;
}) {
  const [tasks, setTasks] = useState<Task[]>();
  const [loadError, setLoadError] = useState(false);
  const [selectedId, setSelectedId] = useState<string>();
  const [timeline, setTimeline] = useState<TaskTimeline>();
  const [timelineError, setTimelineError] = useState(false);

  const loadTasks = useCallback(async () => {
    try {
      setTasks(await withAuthenticatedSession((token) => getTasks(token)));
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) {
        onSessionExpired?.();
      }
      setLoadError(true);
    }
  }, [onSessionExpired]);

  useEffect(() => {
    void Promise.resolve().then(loadTasks);
  }, [loadTasks]);

  const selectTask = async (taskId: string) => {
    setSelectedId(taskId);
    setTimeline(undefined);
    setTimelineError(false);
    try {
      setTimeline(
        await withAuthenticatedSession((token) =>
          getTaskTimeline(token, taskId),
        ),
      );
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) {
        onSessionExpired?.();
      }
      setTimelineError(true);
    }
  };

  return (
    <section>
      <Space orientation="vertical" size={8}>
        <Text className="page-eyebrow">TASK LIFECYCLE</Text>
        <Title>任务日志</Title>
        <Text type="secondary">
          单任务全链路可视化：创建 → 执行 → 审核 → 发布/失败/回滚。
        </Text>
      </Space>

      {loadError && (
        <Alert
          showIcon
          type="error"
          message="暂时无法加载任务日志"
          action={
            <Button
              onClick={() => {
                setLoadError(false);
                void loadTasks();
              }}
            >
              重试
            </Button>
          }
        />
      )}

      {tasks === undefined && !loadError ? (
        <div style={{ padding: 32, textAlign: "center" }}><Spin /></div>
      ) : tasks?.length === 0 ? (
        <Card>
          <Empty description="暂无任务" />
        </Card>
      ) : (
        <Table<Task>
          rowKey="id"
          dataSource={tasks}
          pagination={false}
          onRow={(task) => ({
            onClick: () => void selectTask(task.id),
            "aria-label": `查看任务 ${task.id}`,
          })}
          columns={[
            {
              title: "类型",
              dataIndex: "kind",
              render: (kind: Task["kind"]) =>
                kind === "seo" ? "SEO 优化" : "商品生成",
            },
            {
              title: "风险",
              dataIndex: "risk_level",
              render: (level: Task["risk_level"]) => (
                <Tag color={level === "high" ? "red" : level === "medium" ? "orange" : "green"}>
                  {{ high: "高", medium: "中", low: "低" }[level]}
                </Tag>
              ),
            },
            {
              title: "状态",
              dataIndex: "status",
              render: (status: TaskStatus) => (
                <Tag color={statusMeta[status].color}>
                  {statusMeta[status].label}
                </Tag>
              ),
            },
            {
              title: "创建时间",
              dataIndex: "created_at",
              render: (value: string) => new Date(value).toLocaleString(),
            },
          ]}
        />
      )}

      {selectedId && (
        <Card title="全链路" style={{ marginTop: 16 }}>
          {timeline === undefined && !timelineError && <Spin />}
          {timelineError && (
            <Alert
              showIcon
              type="error"
              message="暂时无法加载任务链路"
              action={
                <Button onClick={() => void selectTask(selectedId)}>重试</Button>
              }
            />
          )}
          {timeline && (
            <Space orientation="vertical" size={16} style={{ width: "100%" }}>
              {timeline.task.last_error && (
                <Alert
                  showIcon
                  type="error"
                  message="任务失败"
                  description={timeline.task.last_error}
                />
              )}
              <Timeline
                items={timeline.audit_log.map((entry) => ({
                  color: entry.to_status === "failed" ? "red" : "green",
                  content: (
                    <Space direction="vertical" size={0}>
                      <Text strong>
                        {statusMeta[entry.from_status].label} →{" "}
                        {statusMeta[entry.to_status].label}
                      </Text>
                      <Text type="secondary">
                        {entry.actor} · {new Date(entry.occurred_at).toLocaleString()}
                      </Text>
                    </Space>
                  ),
                }))}
              />
              {timeline.costs.length > 0 && (
                <Space direction="vertical" size={4}>
                  <Text strong>模型用量与成本</Text>
                  {timeline.costs.map((cost) => (
                    <Text key={cost.id} type="secondary">
                      {cost.model} · {cost.input_tokens} 输入 / {cost.output_tokens} 输出
                      Token · {formatUsd(cost.api_cost)}
                    </Text>
                  ))}
                </Space>
              )}
            </Space>
          )}
        </Card>
      )}
    </section>
  );
}
