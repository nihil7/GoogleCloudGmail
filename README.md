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
| `GITHUB_REPO` | `huozao/meidi-auto` | ⚠️ **硬编码**，仓库改名或转移后必须同步改这里并重新部署（2026-09-08 从 `nihil7/MeidiAuto` 改过来一次） |
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

## 生产部署（2026-09-08 用 gcloud 实测定位）

| 项 | 值 |
|---|---|
| GCP 项目 | `pushgamiltogithub` |
| Cloud Run 服务 | `googlecloudgmails`，区域 **asia-east2** |
| 服务 URL | `https://googlecloudgmails-248281792263.asia-east2.run.app` |
| 当前 revision | `googlecloudgmails-00074-5rg`（2026-04-19 部署） |
| 镜像 | `asia-east2-docker.pkg.dev/pushgamiltogithub/cloud-run-source-deploy/googlecloudgmail/googlecloudgmails:<commit sha>` |
| Pub/Sub | topic `gmailtocloud` → 推送订阅 `gmailtocloud-sub` → 上面那个服务 URL |
| Secret Manager | `gmail_token_json`、`gmail_credentials`、`gmail-service-account` |
| watch 续期 | Cloud Scheduler `refresh-gmail-watch` @ asia-east2，`0 18 * * *`（UTC，即北京 02:00），ENABLED |

### 部署方式：Cloud Build 触发器，**push main 即自动构建并部署**

触发器 `gmail-watcher-deploy-main`（global）绑定 `huozao/gmail-watcher`，镜像 tag 就是被构建的 commit sha——判断生产跑的是哪份代码，把 revision 的镜像 tag 和 `git log` 对一下即可（不写死具体 sha，它每次部署都变）。

⚠️ **仓库转移或改名会打断这个触发器**，它绑定的是原 owner/repo。转移后必须重建，否则此后 push 不再部署，而且**不会有任何报错**——表现为「改了代码但线上行为没变」。

2026-09-08 从 `nihil7/GoogleCloudGmail` 转到 `huozao/gmail-watcher` 时实际走的路径，留作下次参考：

1. GitHub 侧把 Cloud Build App 装到新 owner（网页）
2. Cloud Build 侧「Connect repository」建立仓库映射（**网页专属**，region 要选 `global`，和旧触发器一致）。少这一步 `gcloud builds triggers import` 会报 `FAILED_PRECONDITION: Repository mapping does not exist`
3. `gcloud builds triggers describe` 导出旧触发器 JSON → 改 `github.owner`/`github.name`/`name`、删掉 `id`/`createTime`/`resourceName` 和 `substitutions._TRIGGER_ID` → `gcloud builds triggers import`
4. 删掉指向旧路径的触发器

注意 `gcloud builds triggers` **没有 `export` 子命令**，只能从 `describe --format=json` 构造。

### 生产环境变量

Cloud Run 上配置了 `EMAIL_ADDRESS_QQ`、`EMAIL_PASSWORD_QQ`、`FORWARD_EMAIL`、`GITHUB_TOKEN`、`ENABLE_WATCH_REFRESH_EMAIL`，以及 `gmail_credentials` / `gmail_token_json` 两个 secret 引用。

⚠️ `GITHUB_TOKEN` 是**细粒度 PAT，绑定 resource owner**——2026-09-08 转移时实测：转移前那份的 owner 是 `nihil7`，仓库一归 `huozao`，它对 `huozao/meidi-auto` 立刻变 403，dispatch 必断。当前用的是 resource owner 为 `huozao` 的新 PAT。

判据要选对：这类 token 对**公开仓库**返回 200 不能证明有权限（谁都读得到）。要验就拿一个**私有**仓去试，例如 `GET /repos/huozao/infra` 返回 200 才说明它对该组织有实质权限。

### 只读取证命令

```bash
gcloud run services describe googlecloudgmails --region=asia-east2
gcloud run revisions list --service=googlecloudgmails --region=asia-east2
gcloud pubsub subscriptions list
gcloud scheduler jobs list --location=asia-east2
gcloud builds triggers list
```

## 本地运行

见 [`RUN_LOCAL_DOCKER.md`](RUN_LOCAL_DOCKER.md)。
