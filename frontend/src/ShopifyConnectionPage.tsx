import { Alert, Button, Card, Input, Space, Spin, Tag, Typography } from "antd";

import type { ShopifyStore } from "./api";
import { useShopifyConnection } from "./useShopifyConnection";

const { Text, Title } = Typography;

const statusPresentation: Record<
  ShopifyStore["status"],
  { color: "success" | "default" | "error"; label: string }
> = {
  connected: { color: "success", label: "已连接" },
  disconnected: { color: "default", label: "已断开" },
  error: { color: "error", label: "连接异常" },
};

export default function ShopifyConnectionPage() {
  const {
    authorize,
    authorizing,
    error,
    setShopDomain,
    shopDomain,
    stores,
  } = useShopifyConnection();
  const store =
    stores?.find((candidate) => candidate.status === "connected") ?? stores?.[0];
  const status = store
    ? statusPresentation[store.status]
    : stores
      ? { color: "default" as const, label: "未连接" }
      : { color: "default" as const, label: "状态未知" };

  return (
    <section className="shopify-connection-page">
      <Space orientation="vertical" size={8}>
        <Text className="page-eyebrow">SHOPIFY CONNECTION</Text>
        <Title>店铺连接</Title>
        <Text type="secondary">授权 Shopify 后，AI 中台才能安全地管理商品与 SEO。</Text>
      </Space>

      {error && <Alert showIcon type="error" message={error} />}

      <Card className="shopify-connection-card" variant="borderless">
        {stores === undefined && !error ? (
          <Spin />
        ) : (
          <Space orientation="vertical" size="large">
            <Space>
              <Text strong>连接状态</Text>
              <Tag color={status.color}>{status.label}</Tag>
            </Space>
            {store && <Text>{store.shop_domain}</Text>}
            <Input
              aria-label="Shopify 店铺域名"
              placeholder="your-store.myshopify.com"
              value={shopDomain}
              onChange={(event) => setShopDomain(event.target.value)}
              onPressEnter={() => void authorize()}
            />
            <Button type="primary" loading={authorizing} onClick={() => void authorize()}>
              连接 Shopify 店铺
            </Button>
          </Space>
        )}
      </Card>
    </section>
  );
}
