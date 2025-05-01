import os
import json
from googleapiclient.discovery import build
from google.oauth2 import service_account

def get_gmail_service():
    """
    初始化并返回Gmail API服务对象
    """
    SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

    # 直接从环境变量中读取JSON内容
    service_account_json = os.environ.get('GMAIL_SECRET_JSON')
    if not service_account_json:
        raise ValueError("❌ 环境变量 GMAIL_SECRET_JSON 未设置")

    try:
        credentials_info = json.loads(service_account_json)
        credentials = service_account.Credentials.from_service_account_info(
            credentials_info, scopes=SCOPES
        )

        service = build('gmail', 'v1', credentials=credentials)
        print("✅ Gmail服务对象初始化成功")
        return service

    except Exception as e:
        print(f"❌ 初始化Gmail服务失败: {str(e)}")
        raise
