# AI 智能建站

FastAPI + Celery + PostgreSQL + Redis 后端与 React + Vite + Ant Design 内部后台，包含多租户任务状态机、审计日志和管理员登录。

## 启动

1. 复制 `.env.example` 为 `.env`，修改 `JWT_SECRET`、管理员密码与 Shopify 配置。`SHOPIFY_TOKEN_ENCRYPTION_KEY` 必须是 Base64 编码的 32 字节随机密钥。
2. 运行 `docker compose up --build --detach --wait`。(`docker compose up -d --force-recreate backend worker`)
3. 打开内部后台 <http://localhost:3000>；API 文档位于 <http://localhost:8000/docs>。`GET /health` 返回 `{"status":"healthy"}` 时后端依赖均可用。

若 Windows 的 Docker 配置启用了 Bake，且仓库路径包含中文，使用下面的一键兼容命令避开 BuildKit 的路径编码问题：

```powershell
$env:DOCKER_BUILDKIT = "0"; docker compose up --build --detach --wait
```

Compose 会运行 Alembic 数据库迁移，并创建 `.env` 中配置的初始租户管理员。默认租户 ID 为 `00000000-0000-0000-0000-000000000001`。
开发环境默认还会幂等创建 4 个本地演示商品及审核草稿，不会创建 Shopify 店铺连接或访问令牌。如需关闭，设置 `BOOTSTRAP_DEMO_DATA=false`。

内部后台使用相同租户 ID、`.env` 中的 `BOOTSTRAP_ADMIN_EMAIL` 与 `BOOTSTRAP_ADMIN_PASSWORD` 登录。登录后可看到概览、任务、审核、商品占位导航；前端 Nginx 将 `/api` 请求代理到 FastAPI。

Shopify App 的最小 Scope（`write_products,write_content`）配置在 `shopify.app.toml`，Webhook 订阅声明在 `shopify.webhooks.toml`（默认指向引导租户的 ingress）。真实店铺授权与 Webhook 的验证步骤见 `docs/shopify-live-validation.md`。

## API 流程

- `POST /api/v1/auth/login`：使用 `tenant_id`、`email`、`password` 登录。
- `GET /api/v1/auth/me`：验证 Bearer token 并返回当前内部管理员。
- `POST /api/v1/tasks`：提交任务类型、操作类型与变更字段；确定性规则计算风险等级后创建并投递 Celery 任务。
- `GET /api/v1/tasks`：仅列出当前租户的任务。
- `POST /api/v1/tasks/{task_id}/transitions`：按状态机推进审核、发布或回滚。
- `GET /api/v1/tasks/{task_id}/audit-log`：查看每次状态迁移的操作者、时间和前后状态。
- `POST /api/v1/products/import`：以 multipart 字段 `file` 上传 UTF-8 CSV，并用可重复字段 `images` 上传图片包；归一化并持久化商品、变体与图片，任一非法行都会让整次导入失败并返回行号。
- `GET /api/v1/products`：列出当前商户的商品标准模型与变体。
- `POST /api/v1/products/{product_id}/generate`：为商品触发 AI 生成任务（pending → running），用真实商品数据生成英文 Title/详情/SEO 字段并写入草稿；低风险自动推进，中/高风险进入审核队列。
- `GET /api/v1/reviews/queue`：查看待审核草稿与风险等级，按商户 + 风险（高→低）+ 创建时间排序。
- `GET /api/v1/products/{product_id}/images/{filename}`：读取当前商户已导入的商品图片。
- `GET /api/v1/shopify/oauth/authorize?shop_domain=...`：生成仅含商品与内容写权限的 Shopify 授权 URL。
- `GET /api/v1/shopify/oauth/callback`：Shopify OAuth 回调；Token 仅以 AES-GCM 密文落库。
- `GET /api/v1/shopify/stores`：查看当前商户的店铺连接状态。
- `POST /api/v1/shopify/webhooks/ingress/{tenant_id}`：Shopify Webhook 接收端点，先 HMAC 验签、再按事件 ID 幂等入队。
- `GET /api/v1/shopify/webhooks/dead-letters`：查看当前商户的死信事件。
- `POST /api/v1/shopify/webhooks/{event_id}/replay`：重放死信事件。

创建 SEO 字段更新任务的请求示例：

```json
{
  "kind": "seo",
  "operation_type": "update",
  "changed_fields": ["meta_title", "meta_description"]
}
```

客户端不能提交 `risk_level`；服务按操作类型与变更字段的白名单确定风险，未知或混合的高风险字段按最高风险处理。

商品 CSV 每行表示一个变体；相同 `source + source_id` 的行合并为一个商品。`tags`、`images` 使用 `|` 分隔。HTTP(S) 图片可直接写 URL；文件名引用必须在同次请求中用 `images` 上传并会持久化，单张上限 10 MB。变体最多使用两个选项维度：

```csv
source,source_id,sku,title,description,category,tags,images,meta_title,meta_description,handle,status,variant_sku,option1_name,option1_value,option2_name,option2_value,price,cost,inventory,variant_image
merchant_csv,product-1,TSHIRT,Classic T-Shirt,Heavy cotton tee,Apparel,summer|cotton,front.jpg|back.jpg,Classic Cotton T-Shirt,Shop our classic cotton T-shirt,classic-t-shirt,draft,TSHIRT-BLK-S,Color,Black,Size,S,29.90,12.50,8,black-small.jpg
```

低风险任务由 worker 从 `pending → running → published`；中/高风险任务推进到 `awaiting_review`。可恢复异常按 1、2、4 秒指数退避重试 3 次后进入 `failed`，确定性错误直接进入 `failed`。

## 本地检查

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m mypy app tests
.\.venv\Scripts\python.exe -m ruff check .
Set-Location frontend
pnpm install --frozen-lockfile
pnpm typecheck
pnpm lint
pnpm build
```
