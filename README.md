# AI 智能建站

FastAPI + Celery + PostgreSQL + Redis 项目骨架，包含多租户任务状态机、审计日志和内部后台登录 API。

## 启动

1. 复制 `.env.example` 为 `.env`，至少修改 `JWT_SECRET` 和管理员密码。
2. 运行 `docker compose up --build`。
3. 打开 <http://localhost:8000/docs>；`GET /health` 返回 `{"status":"healthy"}` 时所有依赖均可用。

Compose 会运行 Alembic 数据库迁移，并创建 `.env` 中配置的初始租户管理员。默认租户 ID 为 `00000000-0000-0000-0000-000000000001`。

## API 流程

- `POST /api/v1/auth/login`：使用 `tenant_id`、`email`、`password` 登录。
- `GET /api/v1/auth/me`：验证 Bearer token 并返回当前内部管理员。
- `POST /api/v1/tasks`：提交任务类型、操作类型与变更字段；确定性规则计算风险等级后创建并投递 Celery 任务。
- `GET /api/v1/tasks`：仅列出当前租户的任务。
- `POST /api/v1/tasks/{task_id}/transitions`：按状态机推进审核、发布或回滚。
- `GET /api/v1/tasks/{task_id}/audit-log`：查看每次状态迁移的操作者、时间和前后状态。

创建 SEO 字段更新任务的请求示例：

```json
{
  "kind": "seo",
  "operation_type": "update",
  "changed_fields": ["meta_title", "meta_description"]
}
```

客户端不能提交 `risk_level`；服务按操作类型与变更字段的白名单确定风险，未知或混合的高风险字段按最高风险处理。

低风险任务由 worker 从 `pending → running → published`；中/高风险任务推进到 `awaiting_review`。可恢复异常按 1、2、4 秒指数退避重试 3 次后进入 `failed`，确定性错误直接进入 `failed`。

## 本地检查

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m mypy app tests
.\.venv\Scripts\python.exe -m ruff check .
```
