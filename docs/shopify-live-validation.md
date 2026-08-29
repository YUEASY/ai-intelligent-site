# Shopify 真实店铺验证 Runbook

针对 issue #13 中「Shopify validation」清单里仍需真人 + 真实店铺完成的步骤。按顺序执行，每步核对结果后打勾。

## 前置条件

- [ ] 已创建 Shopify Partner App（`client_id` 已写入 `shopify.app.toml`）。
- [ ] 已创建 Development Store（`ai-intelligent-site-test.myshopify.com`）。
- [ ] 本机已 `shopify login` 并关联到该 App。
- [ ] `.env` 中已配置真实 `SHOPIFY_CLIENT_ID`、`SHOPIFY_CLIENT_SECRET`。
- [ ] `SHOPIFY_TOKEN_ENCRYPTION_KEY` 为 32 字节随机密钥的 Base64（生成命令见下）。
- [ ] 后端 / worker / 前端容器已 `docker compose up --build -d --wait` 且为 healthy。

生成加密密钥：

```powershell
.\.venv\Scripts\python.exe -c "import secrets,base64; print(base64.b64encode(secrets.token_bytes(32)).decode())"
```

## 1. 注册 Scope 与 Webhook 订阅

- [ ] `shopify.app.toml` 的 `[access_scopes] scopes` 为 `"write_products,write_content"`（不含 orders/customers）。
- [ ] `shopify.webhooks.toml` 声明了 `app/uninstalled`、`products/create`、`products/update`、`products/delete`，URI 指向引导租户。
- [ ] 运行 `shopify app deploy`（或 `shopify app config push`）让 Scope、回调 URL 与 Webhook 订阅在 Partner 后台生效。

> 推荐通过 `./scripts/shopify-dev.ps1` 启动联调环境。它会识别 Shopify CLI
> 生成的 Tunnel URL，将回调地址注入 backend/worker，并在退出时恢复 Docker
> frontend 与 `.env` 配置，无需手动修改随机域名。

## 2. 真实安装与 OAuth 回调

- [ ] 登录内部后台（<http://localhost:3000>），进入「店铺连接」。
- [ ] 输入 `ai-intelligent-site-test.myshopify.com`，点击「连接 Shopify 店铺」。
- [ ] 弹窗打开 Shopify 授权页；完成安装并批准权限。
- [ ] 回调成功后前端在 3 秒轮询内显示「已连接」与店铺域名。
- [ ] 授权页展示的 Scope 恰为商品与内容写权限，**不含 orders / customers**。

## 3. 核对 Scope 与 tenant_id 绑定

```sql
SELECT tenant_id, shop_domain, status, granted_scopes, connected_at
FROM shopify_stores;
```

- [ ] `tenant_id` 等于引导租户 `00000000-0000-0000-0000-000000000001`（证明 state → tenant 绑定正确）。
- [ ] `granted_scopes` 仅为 `write_products`、`write_content`。

## 4. 核对 Token 只以密文落库

```sql
SELECT shop_domain,
       status,
       octet_length(encrypted_access_token) AS token_ciphertext_bytes,
       (access_token_nonce IS NOT NULL)     AS has_nonce,
       (encrypted_access_token IS NULL)     AS plaintext_absent
FROM shopify_stores;
```

- [ ] `token_ciphertext_bytes > 0` 且 `has_nonce = true`。
- [ ] 数据库不存在明文字段；前端 `/shopify/stores` 响应与应用日志均不含 Token 明文。

## 5. 真实签名 Webhook

- [ ] 在 Development Store 后台编辑一个商品，触发 `products/update` 投递。
- [ ] ingress 返回 202（`status: accepted`），`shopify_webhook_events` 出现一行并最终为 `processed`。
- [ ] 用错误 `X-Shopify-Hmac-Sha256` 重放同一 body → 返回 401，且不落库、不入队。
- [ ] 用相同 `X-Shopify-Webhook-Id` 再次投递 → 返回 200（`status: duplicate`），表中仍只有一行。

## Issue #17：SEO 自动写入、审核门槛与远端回滚

在卸载 App 前运行以下验证；推荐直接执行仓库向导：

```bash
bash scripts/validate-shopify-live.sh
```

- [ ] 选定一个已发布且 `shopify_product_id` 非空的本地商品，在 Shopify 后台记录 Title、网站 SEO 标题/描述、Tags 和首图 Alt 原值。
- [ ] 点击「SEO 优化」后，审核队列显示「已写入 Shopify」；刷新 Shopify 后上述低风险字段与建议一致。
- [ ] 点击「SEO 标题优化」后，审核前刷新 Shopify，Title 保持不变；通过审核并明确确认发布后，Title 才发生变化。
- [ ] 在本地版本历史中回滚到低风险 SEO 写入前的 publish 快照；重新读取 Shopify 后，Title、Meta、Tags 与 Alt 恢复为记录的原值。

建议在 Issue #17 留下商品的本地 UUID、Shopify Product ID、快照版本、任务 ID 与验证时间；不要粘贴访问令牌。

## 6. 撤销 / 卸载 → 连接状态

- [ ] 在 Development Store 卸载 App（或撤销权限），触发 `app/uninstalled`。
- [ ] 等待 Celery 处理，`shopify_stores` 该行变为 `disconnected`，`encrypted_access_token`/`access_token_nonce` 清空、`disconnected_at` 写入。
- [ ] 前端「店铺连接」页显示「已断开」。

## 7. 重新安装

- [ ] 再次走「连接 Shopify 店铺」流程，状态回到「已连接」。

## 完成后

- [ ] 回填 issue #13 中相应 `[ ]` 复选框并注明结果。
