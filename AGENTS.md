# gmail-watcher

Gmail 监听与流水线触发器，跑在 Google Cloud Run。是「美的存量对帐」链路的
**上游触发端**，下游是 [`meidi-auto`](../meidi-auto/) 的 GitHub Actions 流水线。
**每天在生产运行。**

先读 `README.md`——链路图、关键常量、生产部署实测参数（服务名/区域/Pub-Sub/
Scheduler）、排障表、只读取证命令都在里面。

## 动手前必须知道的

- **`push main` 会自动构建并部署到生产**。Cloud Build 触发器
  `gmail-watcher-deploy-main`（region `global`）监听 main，镜像 tag 就是
  commit sha。判断线上跑的是哪份代码：把 Cloud Run revision 的镜像 tag 和
  `git log` 对一下。**这里没有「先合并再择时部署」这一步**，合了就上线。

- **`GITHUB_REPO` 在 `main.py:43` 是硬编码**。仓库改名或转移后不同步改并
  重新部署，dispatch 直接失效。

- **`GITHUB_TOKEN` 是细粒度 PAT，绑定 resource owner**。2026-09-08 转移当天
  实测：owner 为 `nihil7` 的旧 token，在仓库归 `huozao` 后对
  `huozao/meidi-auto` 及其 `actions/workflows` **双双 403**。
  ⚠️ 验这类 token **必须拿私有仓做判据**——`huozao/meidi-auto` 是公开仓，
  任何有效 token 读它都返回 200，看着有权限其实什么也没证明。用
  `GET /repos/huozao/infra`（私有）才算数。

- **Gmail watch 最长 7 天到期**，靠 Cloud Scheduler `refresh-gmail-watch`
  （asia-east2，`0 18 * * *` UTC）每天调 `/refresh_watch` 续期。过期后邮件
  不再推送，链路**静默失效、不报错**。

- **服务不对 `allUsers` 开放**，手工调用要带身份令牌：
  `curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" <URL>/refresh_watch`

- **凭据正本在 `infra/secrets/gmail-watcher.enc.env` 与
  `gmail-watcher-token.enc.json`**（SOPS）。改那里不等于改生产——环境变量要
  `gcloud run services update --update-env-vars` 推上去，token 要
  `gcloud secrets versions add gmail_token_json` 推上去。

- **`.gitignore` 必须保持 UTF-8**。它曾经是 UTF-16LE，git 完全不解析，
  `token.json` / `.env` / `credentials.json` 全都处于未忽略状态。改完用
  `git check-ignore -v <文件>` 双向验证。

## gcloud 在 WSL 里登录

`gio` 打不开浏览器，而手工复制那条超长 OAuth URL 会被终端截断，表现为
`Error 400: invalid_scope`（invalid 项是被截断的 scope，看着像 scope 配错了，
其实是 URL 断了）。解法是让脚本把 URL 交给 Windows 浏览器：

```bash
# BROWSER 指向一个 exec powershell.exe -Command "Start-Process \"$1\"" 的脚本
BROWSER=/path/to/open-win-browser.sh gcloud auth login
```

## 提交

走 PR（`gh pr create --repo huozao/gmail-watcher`）。合并即部署，见上。

工作区级规矩见顶层 [`AGENTS.md`](../AGENTS.md)。
