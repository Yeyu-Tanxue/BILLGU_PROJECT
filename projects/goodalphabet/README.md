---
title: Gu的辞書
emoji: 
colorFrom: gray
colorTo: pink
sdk: docker
app_port: 7860
---

## 前端改造（Next.js + shadcn/ui）

项目里新增了 `frontend/` 目录作为新前端（Next.js App Router）。

## Vercel 部署（默认显示 shadcn 页面）

这个仓库已经改成 **同一个 Vercel 项目里同时部署 Next.js 前端 + Python API**：

- `/api/*` -> `api/index.py` (FastAPI)
- 其余路径 -> `frontend/` (Next.js 页面)

也就是说部署后默认打开域名根路径 `/`，看到的就是 Next.js(shadcn) 页面。

### 你要配什么

1. Vercel 导入这个仓库（Root 保持仓库根目录，不要改成 `frontend`）。
2. 不需要额外改 Build Command，使用仓库里的 `vercel.json`。
3. 环境变量：
   - **生产环境建议不设置** `NEXT_PUBLIC_API_BASE_URL`（留空即走同域 `/api`）。
   - 只有本地开发时才在 `frontend/.env.local` 里设置 `NEXT_PUBLIC_API_BASE_URL=http://localhost:7860`。

## 本地开发

### 1) 只跑 Next.js 前端（推荐）

```bash
# 终端 1：启动后端 API
pip install -r requirements.txt
python main.py

# 终端 2：启动 Next.js 前端
cd frontend
npm install
npm run dev
```

然后访问：

- Next.js 页面：`http://localhost:3000`
- 后端 API：`http://localhost:7860/api/*`

### 2) 后端根路径 `/` 自动跳到 Next.js（本地联调可选）

```bash
export FRONTEND_MODE=next
export NEXT_DEV_SERVER=http://localhost:3000
python main.py
```

此时：

- `http://localhost:7860/` 会重定向到 `http://localhost:3000`
- `http://localhost:7860/login` 也会重定向到 `http://localhost:3000`
- `http://localhost:7860/frontend-info` 可查看当前前端路由配置

## Stripe 一次性支付开通 30 天

本项目的会员不是自动续费订阅，而是一次性 Stripe Checkout 支付。每次支付成功后，后端 webhook 会按 fin-agent 的结构写入 `public."user"`：`stripe_subscription` 保存本次 Checkout Session ID，`stripe_customer` 保存 Stripe Customer ID，`last_payment_time` 保存付款时间。访问权限由 `last_payment_time + 30 天` 动态判断。

需要配置的环境变量：

- `STRIPE_SECRET_KEY`: Stripe 服务端密钥，生产环境建议使用受限密钥（`rk_`）。
- `STRIPE_MONTH_ACCESS_PRICE_ID`: Stripe Dashboard 里创建的一次性 Price ID。
- `STRIPE_WEBHOOK_SECRET`: `checkout.session.completed` webhook 的签名密钥。
- `APP_BASE_URL`: 应用公开域名，例如 `https://example.com`，用于生成 Checkout 成功/取消返回地址。
- `STRIPE_MONTH_ACCESS_DAYS`: 可选，默认 `30`。

本地 webhook 调试示例：

```bash
stripe listen --forward-to localhost:7860/api/webhooks/stripe
```

前端入口是 `/billing`，后端接口是 `/api/billing/status`、`/api/billing/checkout` 和 `/api/webhooks/stripe`。

新 Auth0 用户首次同步时会在 `public."user"` 中创建记录并赠送 `50000` tokens。AI 调用会按服务返回的 `usage.total_tokens` 扣减；流式调用拿不到 usage 时按输入和输出文本长度估算扣减。
