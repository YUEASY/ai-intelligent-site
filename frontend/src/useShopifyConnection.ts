import { useEffect, useRef, useState } from "react";

import {
  ApiError,
  type ShopifyStore,
  getShopifyAuthorizationUrl,
  getShopifyStores,
} from "./api";
import { withAuthenticatedSession } from "./auth";

const POLL_INTERVAL_MS = 3000;
const POPUP_FEATURES = "popup,width=720,height=760";

function errorMessage(cause: unknown, fallback: string): string {
  return cause instanceof ApiError ? cause.message : fallback;
}

export function useShopifyConnection() {
  const [stores, setStores] = useState<ShopifyStore[]>();
  const [error, setError] = useState<string>();
  const [shopDomain, setShopDomain] = useState("");
  const [authorizing, setAuthorizing] = useState(false);
  const sessionExpired = useRef(false);

  useEffect(() => {
    let active = true;
    let refreshPending = false;

    const refresh = async () => {
      if (!active || refreshPending || sessionExpired.current) return;
      refreshPending = true;
      try {
        const currentStores = await withAuthenticatedSession(getShopifyStores);
        if (active) {
          setStores(currentStores);
          setError(undefined);
        }
      } catch (cause) {
        if (cause instanceof ApiError && cause.status === 401) {
          sessionExpired.current = true;
        }
        if (active) {
          setError(errorMessage(cause, "暂时无法获取店铺连接状态"));
        }
      } finally {
        refreshPending = false;
      }
    };

    void Promise.resolve().then(refresh);
    const pollId = window.setInterval(() => void refresh(), POLL_INTERVAL_MS);
    return () => {
      active = false;
      window.clearInterval(pollId);
    };
  }, []);

  const authorize = async () => {
    const normalizedDomain = shopDomain.trim().toLowerCase();
    if (!/^[a-z0-9][a-z0-9-]*\.myshopify\.com$/.test(normalizedDomain)) {
      setError("请输入有效的 Shopify 店铺域名");
      return;
    }

    const popup = window.open("", "shopify-oauth", POPUP_FEATURES);
    if (!popup) {
      setError("浏览器阻止了授权窗口，请允许弹窗后重试");
      return;
    }

    setAuthorizing(true);
    setError(undefined);
    try {
      const { authorization_url: authorizationUrl } =
        await withAuthenticatedSession((token) =>
          getShopifyAuthorizationUrl(token, normalizedDomain),
        );
      popup.location.href = authorizationUrl;
    } catch (cause) {
      popup.close();
      if (cause instanceof ApiError && cause.status === 401) {
        sessionExpired.current = true;
      }
      setError(errorMessage(cause, "暂时无法发起 Shopify 授权"));
    } finally {
      setAuthorizing(false);
    }
  };

  return {
    authorize,
    authorizing,
    error,
    setShopDomain,
    shopDomain,
    stores,
  };
}
