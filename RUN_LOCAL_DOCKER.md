# 本地运行（PyCharm / 命令行）

## 1) 安装依赖
```bash
pip install -r requirements.txt
```

## 2) 准备环境变量
复制 `.env.example` 为 `.env`，并按需修改：
```bash
cp .env.example .env
```

在 local 模式下，确保以下文件存在：
- `secrets/gmail_token.json`

## 3) 启动
```bash
export $(grep -v '^#' .env | xargs)
gunicorn main:app -b 0.0.0.0:8080
```

---

# Docker 本地运行

## 1) 构建镜像
```bash
docker build -t googlecloudgmail:local .
```

## 2) 运行容器（local 模式）
```bash
docker run --rm -p 8080:8080 \
  --env-file .env \
  -v $(pwd)/secrets:/app/secrets \
  -v $(pwd)/data:/app/data \
  googlecloudgmail:local
```

> 说明：`secrets` 和 `data` 通过 volume 挂载，便于本地调试时保留 token 与 historyId。
