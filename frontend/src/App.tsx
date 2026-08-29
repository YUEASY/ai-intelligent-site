import {
  AppstoreOutlined,
  AuditOutlined,
  LogoutOutlined,
  ProductOutlined,
  ShopOutlined,
  UnorderedListOutlined,
} from "@ant-design/icons";
import {
  Alert,
  Avatar,
  Button,
  Card,
  ConfigProvider,
  Form,
  Input,
  Layout,
  Menu,
  Space,
  Spin,
  Tag,
  Typography,
  theme,
} from "antd";
import { useEffect, useState } from "react";

import {
  ApiError,
  type Admin,
  type LoginCredentials,
} from "./api";
import {
  authenticate,
  clearSession,
  hasSavedSession,
  restoreSession,
} from "./auth";
import ShopifyConnectionPage from "./ShopifyConnectionPage";
import ProductsPage from "./ProductsPage";

const { Header, Content, Sider } = Layout;
const { Text, Title } = Typography;

const navigation = [
  { key: "overview", icon: <AppstoreOutlined aria-hidden />, label: "概览" },
  { key: "tasks", icon: <UnorderedListOutlined aria-hidden />, label: "任务" },
  { key: "reviews", icon: <AuditOutlined aria-hidden />, label: "审核" },
  { key: "products", icon: <ProductOutlined aria-hidden />, label: "商品" },
  { key: "shopify", icon: <ShopOutlined aria-hidden />, label: "店铺连接" },
];

const pageCopy: Record<string, { eyebrow: string; title: string; body: string }> = {
  overview: {
    eyebrow: "OPERATIONS OVERVIEW",
    title: "运营概览",
    body: "任务成功率、审核积压与节省工时将在数据接入后显示于此。",
  },
  tasks: {
    eyebrow: "TASK LIFECYCLE",
    title: "任务",
    body: "查看 AI 任务状态、失败原因与完整状态迁移记录。",
  },
  reviews: {
    eyebrow: "HUMAN REVIEW",
    title: "审核",
    body: "查看需要人工介入的任务，并完成通过、驳回与修改操作。",
  },
  products: {
    eyebrow: "CANONICAL PRODUCTS",
    title: "商品",
    body: "浏览商户的商品标准模型、变体、草稿与发布状态。",
  },
};

function LoginScreen({ onAuthenticated }: { onAuthenticated: (admin: Admin) => void }) {
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string>();

  const submit = async (credentials: LoginCredentials) => {
    setSubmitting(true);
    setError(undefined);
    try {
      onAuthenticated(await authenticate(credentials));
    } catch (cause) {
      setError(
        cause instanceof ApiError && cause.status === 401
          ? "租户、邮箱或密码不正确"
          : "暂时无法登录，请确认后台服务已启动",
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="login-page">
      <section className="login-story">
        <div className="brand-mark" aria-hidden="true">曜</div>
        <Text className="login-kicker">YUEASY OPERATIONS</Text>
        <Title className="login-heading">让独立站持续运转，<br />让每次变更都有依据。</Title>
        <Text className="login-description">
          商品、SEO、审核与回滚，在同一个可追溯的运营工作台完成。
        </Text>
        <div className="story-orbit" aria-hidden="true" />
      </section>

      <section className="login-panel">
        <Card className="login-card" bordered={false}>
          <Space direction="vertical" size={6} className="login-card-heading">
            <Tag color="cyan" bordered={false}>内部后台</Tag>
            <Title level={2}>欢迎回来</Title>
            <Text type="secondary">使用商户租户与管理员账号登录</Text>
          </Space>

          {error && <Alert showIcon type="error" message={error} />}

          <Form<LoginCredentials>
            layout="vertical"
            requiredMark={false}
            initialValues={{
              tenant_id: "00000000-0000-0000-0000-000000000001",
              email: "admin@example.com",
            }}
            onFinish={submit}
          >
            <Form.Item
              label="租户 ID"
              name="tenant_id"
              rules={[{ required: true, message: "请输入租户 ID" }]}
            >
              <Input size="large" autoComplete="organization" />
            </Form.Item>
            <Form.Item
              label="管理员邮箱"
              name="email"
              rules={[
                { required: true, message: "请输入管理员邮箱" },
                { type: "email", message: "请输入有效邮箱" },
              ]}
            >
              <Input size="large" autoComplete="username" />
            </Form.Item>
            <Form.Item
              label="密码"
              name="password"
              rules={[{ required: true, message: "请输入密码" }]}
            >
              <Input.Password size="large" autoComplete="current-password" />
            </Form.Item>
            <Button
              block
              size="large"
              type="primary"
              htmlType="submit"
              loading={submitting}
            >
              登录运营后台
            </Button>
          </Form>
        </Card>
      </section>
    </main>
  );
}

function AdminShell({ admin, onLogout }: { admin: Admin; onLogout: () => void }) {
  const [page, setPage] = useState("overview");
  const copy = pageCopy[page];

  return (
    <Layout className="admin-shell">
      <Sider width={248} className="admin-sider" breakpoint="lg" collapsedWidth={0}>
        <div className="sidebar-brand">
          <span className="sidebar-logo">曜</span>
          <span>
            <strong>AI 智能建站</strong>
            <small>运营控制台</small>
          </span>
        </div>
        <Menu
          mode="inline"
          selectedKeys={[page]}
          items={navigation}
          onClick={({ key }) => setPage(key)}
        />
        <div className="sidebar-footnote">可观察 · 可审核 · 可回滚</div>
      </Sider>

      <Layout>
        <Header className="admin-header">
          <Text className="header-context">商户运营空间</Text>
          <Space size={12}>
            <Avatar>{admin.email.slice(0, 1).toUpperCase()}</Avatar>
            <div className="admin-identity">
              <Text strong>{admin.email}</Text>
              <Text type="secondary">内部管理员</Text>
            </div>
            <Button type="text" icon={<LogoutOutlined />} onClick={onLogout}>
              退出
            </Button>
          </Space>
        </Header>

        <Content className="admin-content">
          {page === "products" ? (
            <ProductsPage onSessionExpired={onLogout} />
          ) : page === "shopify" ? (
            <ShopifyConnectionPage />
          ) : (
            <>
              <section className="page-heading">
                <Text className="page-eyebrow">{copy.eyebrow}</Text>
                <Title>{copy.title}</Title>
                <Text>{copy.body}</Text>
              </section>

              <Card className="placeholder-card" bordered={false}>
                <div className="placeholder-icon">{navigation.find((item) => item.key === page)?.icon}</div>
                <Title level={3}>{copy.title}模块已就绪</Title>
                <Text type="secondary">当前为项目骨架，占位内容将在后续业务迭代中接入。</Text>
              </Card>
            </>
          )}
        </Content>
      </Layout>
    </Layout>
  );
}

export default function App() {
  const [admin, setAdmin] = useState<Admin>();
  const [restoring, setRestoring] = useState(hasSavedSession);
  const [restoreFailed, setRestoreFailed] = useState(false);

  useEffect(() => {
    if (!hasSavedSession()) {
      return;
    }
    restoreSession()
      .then((restoredAdmin) => {
        if (restoredAdmin) setAdmin(restoredAdmin);
      })
      .catch(() => setRestoreFailed(true))
      .finally(() => setRestoring(false));
  }, []);

  const logout = () => {
    clearSession();
    setAdmin(undefined);
    setRestoreFailed(false);
  };

  const retryRestore = () => {
    setRestoring(true);
    setRestoreFailed(false);
    restoreSession()
      .then((restoredAdmin) => {
        if (restoredAdmin) setAdmin(restoredAdmin);
      })
      .catch(() => setRestoreFailed(true))
      .finally(() => setRestoring(false));
  };

  return (
    <ConfigProvider
      theme={{
        algorithm: theme.defaultAlgorithm,
        token: {
          colorPrimary: "#0b8069",
          colorInfo: "#0b8069",
          borderRadius: 10,
          fontFamily: 'Inter, "PingFang SC", "Microsoft YaHei", sans-serif',
        },
      }}
    >
      {restoring ? (
        <div className="restore-screen"><Spin size="large" /></div>
      ) : restoreFailed ? (
        <div className="restore-screen">
          <Space direction="vertical" align="center">
            <Alert showIcon type="warning" message="暂时无法恢复登录状态，会话已为你保留" />
            <Space>
              <Button type="primary" onClick={retryRestore}>重试</Button>
              <Button onClick={logout}>重新登录</Button>
            </Space>
          </Space>
        </div>
      ) : admin ? (
        <AdminShell admin={admin} onLogout={logout} />
      ) : (
        <LoginScreen onAuthenticated={setAdmin} />
      )}
    </ConfigProvider>
  );
}
