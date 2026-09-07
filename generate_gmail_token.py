import json
import os
import sys
import tempfile
from pathlib import Path

from dotenv import load_dotenv
from google_auth_oauthlib.flow import InstalledAppFlow


TOKEN_FILE = "token.json"
DEFAULT_SCOPE = "https://www.googleapis.com/auth/gmail.modify"


def print_step(text: str) -> None:
    print(f"\n=== {text} ===")


def get_env(name: str, required: bool = True, default: str = "") -> str:
    value = os.getenv(name, default).strip()
    if required and not value:
        raise ValueError(f"缺少环境变量：{name}")
    return value


def build_credentials_dict() -> dict:
    client_id = get_env("GMAIL_CLIENT_ID")
    client_secret = get_env("GMAIL_CLIENT_SECRET")
    project_id = get_env("GMAIL_PROJECT_ID", required=False, default="pushgamiltogithub")

    return {
        "installed": {
            "client_id": client_id,
            "project_id": project_id,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_secret": client_secret,
            "redirect_uris": [
                "http://localhost"
            ]
        }
    }


def get_scopes() -> list[str]:
    scopes_raw = get_env("GMAIL_SCOPES", required=False, default=DEFAULT_SCOPE)
    scopes = [x.strip() for x in scopes_raw.split(",") if x.strip()]
    if not scopes:
        raise ValueError("GMAIL_SCOPES 为空")
    return scopes


def generate_token() -> None:
    print_step("读取 .env")
    load_dotenv(override=True)

    credentials_data = build_credentials_dict()
    scopes = get_scopes()

    print("GMAIL_CLIENT_ID 已读取")
    print("GMAIL_CLIENT_SECRET 已读取")
    print("授权范围：", ", ".join(scopes))

    print_step("创建临时 credentials.json")
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".json",
        delete=False
    ) as tmp_file:
        json.dump(credentials_data, tmp_file, ensure_ascii=False, indent=2)
        temp_credentials_path = tmp_file.name

    print(f"临时凭据文件已生成：{temp_credentials_path}")

    try:
        print_step("启动 Google OAuth 浏览器授权")
        print("请使用你实际要监控的 Gmail 账号登录并授权。")

        flow = InstalledAppFlow.from_client_secrets_file(
            temp_credentials_path,
            scopes,
        )

        creds = flow.run_local_server(
            host="localhost",
            port=0,
            authorization_prompt_message="请在浏览器中完成 Google 授权。",
            success_message="授权成功，可以关闭此页面并返回程序。",
            open_browser=True,
        )

        print_step("写入 token.json")
        token_path = Path.cwd() / TOKEN_FILE
        with token_path.open("w", encoding="utf-8") as f:
            f.write(creds.to_json())

        print(f"已生成：{token_path}")

        refresh_token_exists = bool(getattr(creds, "refresh_token", None))

        print_step("结果检查")
        print(f"是否拿到 refresh_token：{refresh_token_exists}")

        if not refresh_token_exists:
            print("警告：本次 token.json 未包含 refresh_token，后续可能仍无法自动续期。")
        else:
            print("成功：token.json 中包含 refresh_token。")

        print_step("下一步")
        print(
            "请把 token.json 上传到 Secret Manager。\n"
            "示例：\n"
            "gcloud secrets versions add gmail_token_json "
            "--project=pushgamiltogithub --data-file=token.json"
        )

    finally:
        try:
            os.remove(temp_credentials_path)
            print("\n临时 credentials 文件已删除。")
        except Exception:
            print("\n注意：临时 credentials 文件删除失败，请手动删除。")


def main() -> int:
    try:
        generate_token()
        return 0
    except KeyboardInterrupt:
        print("\n用户中断。")
        return 1
    except Exception as e:
        print("\n程序执行失败：")
        print(str(e))
        return 1


if __name__ == "__main__":
    sys.exit(main())