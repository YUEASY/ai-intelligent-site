import { Alert, Button, Card, Input, Space, Spin, Tag, Typography } from "antd";
import { useCallback, useEffect, useState } from "react";

import {
  ApiError,
  type ShopifyStore,
  getShopifyAuthorizationUrl,
  getShopifyStores,
} from "./api";
import { getSavedAccessToken } from "./auth";

const { Text, Title } = Typography;

export default function ShopifyConnectionPage() {
  const [stores, setStores] = useState<ShopifyStore[]>();
  const [error, setError] = useState<string>();
  const [shopDomain, setShopDomain] = useState("");
  const [authorizing, setAuthorizing] = useState(false);

  const refreshStores = useCallback(async () => {
    const token = getSavedAccessToken();
    if (!token) {
      setError("登录状态已失效，请重新登录");
      setStores([]);
      return;
    }
    try {
      setStores(await getShopifyStores(token));
      setError(undefined);
    } catch {
      setError("暂时无法获取店铺连接状态");
      setStores([]);
    }
  }, []);

  useEffect(() => {
    const initialRequestId = window.setTimeout(() => void refreshStores(), 0);
    const pollId = window.setInterval(() => void refreshStores(), 3000);
    return () => {
      window.clearTimeout(initialRequestId);
      window.clearInterval(pollId);
    };
  }, [refreshStores]);

  const authorize = async () => {
    const token = getSavedAccessToken();
    if (!token) {
      setError("登录状态已失效，请重新登录");
      return;
    }
    const normalizedDomain = shopDomain.trim().toLowerCase();
    if (!/^[a-z0-9][a-z0-9-]*\.myshopify\.com$/.test(normalizedDomain)) {
      setError("请输入有效的 Shopify 店铺域名");
      return;
    }

    setAuthorizing(true);
    setError(undefined);
    try {
      const { authorization_url: authorizationUrl } =
        await getShopifyAuthorizationUrl(token, normalizedDomain);
      const popup = window.open(
        authorizationUrl,
        "shopify-oauth",
        "popup,width=720,height=760",
      );
      if (!popup) setError("浏览器阻止了授权窗口，请允许弹窗后重试");
    } catch (cause) {
      setError(
        cause instanceof ApiError ? cause.message : "暂时无法发起 Shopify 授权",
      );
    } finally {
      setAuthorizing(false);
    }
  };

  const connectedStore = stores?.find((store) => store.status === "connected");

  return (
    <section className="shopify-connection-page">
      <Space orientation="vertical" size={8}>
        <Text className="page-eyebrow">SHOPIFY CONNECTION</Text>
        <Title>店铺连接</Title>
        <Text type="secondary">授权 Shopify 后，AI 中台才能安全地管理商品与 SEO。</Text>
      </Space>

      {error && <Alert showIcon type="error" message={error} />}

      <Card className="shopify-connection-card" variant="borderless">
        {stores === undefined ? (
          <Spin />
        ) : (
          <Space orientation="vertical" size="large">
            <Space>
              <Text strong>连接状态</Text>
              <Tag color={connectedStore ? "success" : "default"}>
                {connectedStore ? "已连接" : "未连接"}
              </Tag>
            </Space>
            {connectedStore && <Text>{connectedStore.shop_domain}</Text>}
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
