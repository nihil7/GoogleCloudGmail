# gmail-watcher

Gmail 邮件监听与流水线触发器。部署在 Google Cloud Run，是「美的存量对帐」自动化链路的**上游触发端**，下游是 [`meidi-auto`](../meidi-auto/) 的 GitHub Actions 流水线。

## 链路

```
Gmail 收到邮件
  → Gmail watch 推送到 Pub/Sub topic (gmailtocloud)
  → Pub/Sub 推送订阅 POST 到本服务 /
  → 立即返回 200，后台线程处理（避免 Pub/Sub 重投）
  → 比对 historyId（存 Firestore，防重复处理）
  → 拉取新邮件，按 KEYWORDS 匹配
  → 命中则打标签 + POST GitHub workflow_dispatch
  → meidi-auto 的 run-daily.yml 开跑
```

## 关键常量（`main.py` 顶部）

| 常量 | 值 | 说明 |
|---|---|---|
| `KEYWORDS` | `["骏都对帐表"]` | 匹配到才触发下游 |
| `TARGET_LABEL_NAME` | `Label_264791441972079941` | 命中后打的 Gmail 标签 |
| `GITHUB_REPO` | `nihil7/MeidiAuto` | ⚠️ **硬编码**，仓库改名或转移后必须同步改这里并重新部署 |
| `GITHUB_WORKFLOW` | `run-daily.yml` | dispatch 目标工作流 |
| `ENABLE_EMAIL_SENDING` | `False` | 转发原始 Pub/Sub 消息的调试开关，默认关 |

## 路由

- `POST /` — Pub/Sub 推送入口
- `GET /refresh_watch` — 续期 Gmail watch。**Gmail watch 最长 7 天到期**，必须周期性调用，否则邮件不再推送、链路静默失效

## Token

`token.json` 是 Gmail end-user OAuth 凭据（含 refresh_token），生产上存在 GCP Secret Manager 的 `gmail_token_json`，由 `GMAIL_TOKEN_SECRET` 指定。

重新生成用本仓的 `generate_gmail_token.py`（需要 `.env` 里的 `GMAIL_CLIENT_ID` / `GMAIL_CLIENT_SECRET`），然后：

```bash
gcloud secrets versions add gmail_token_json --project=pushgamiltogithub --data-file=token.json
```

**gcloud CLI 替代不了这个脚本**：`gcloud auth` 产出的是 GCP 服务账号 / ADC 凭据，scope 不覆盖 `gmail.modify`；个人 Gmail 账号也不支持服务账号域委派（那只对 Workspace 有效）。所以这里必须走浏览器 OAuth 授权流程。

## 凭据正本

密钥统一源在 `infra/secrets/`（SOPS）：

- `gmail-watcher.enc.env` — OAuth client 与运行配置
- `gmail-watcher-token.enc.json` — token 备份副本

⚠️ 两处已知缺口，别当成完整正本：`GITHUB_TOKEN` 只配在 Cloud Run 上、本机 `.env` 是空的；token 备份不保证与 Secret Manager 的最新版本一致（生产侧会自行刷新）。

## 排障

| 现象 | 先查 |
|---|---|
| 收到邮件但流水线没跑 | ① Cloud Run 日志有没有收到 Pub/Sub ② `historyId` 是否被判成「不大于已保存值」而跳过 ③ 关键词是否命中 ④ dispatch 返回码 |
| 一直没有任何推送 | Gmail watch 是否过期（≤7 天），调 `/refresh_watch` |
| dispatch 返回 404 | `GITHUB_REPO` 与实际仓库不符（改名/转移后没同步），或 token 权限不足 |
| 重复处理同一封 | Firestore 里的 `historyId` 状态异常 |

## 待定位

本机没有这个服务的部署记录，仓库里也没有 workflow 或 `cloudbuild.yaml`。以下需要 `gcloud` 登录后确认并补进本文：Cloud Run 服务名与区域、部署方式（Console 手工 / `--source` / Cloud Build 触发器）、Pub/Sub 推送订阅指向的 URL、`/refresh_watch` 由谁周期性调用。

## 本地运行

见 [`RUN_LOCAL_DOCKER.md`](RUN_LOCAL_DOCKER.md)。
