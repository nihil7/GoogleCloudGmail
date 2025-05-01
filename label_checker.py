import json
from google.cloud import secretmanager
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# === 配置区域 ===
PROJECT_ID = "pushgamiltogithub"
SECRET_NAME = "gmail_token_json"
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

def analyze_gmail_history(history_id: str, target_label: str) -> bool:
    """
    打印 Gmail 变更记录并判断是否添加了指定标签
    参数:
        history_id (str): Gmail 推送提供的起始变更 ID
        target_label (str): 目标标签 ID，如 'INBOX'
    返回:
        bool: 是否发现该标签被添加
    """
    try:
        # ✅ 从 Secret Manager 获取 token.json
        sm_client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{PROJECT_ID}/secrets/{SECRET_NAME}/versions/latest"
        response = sm_client.access_secret_version(request={"name": name})
        token_data = json.loads(response.payload.data.decode("utf-8"))
        creds = Credentials.from_authorized_user_info(token_data, SCOPES)

        # ✅ 构建 Gmail 客户端
        service = build('gmail', 'v1', credentials=creds)

        # ✅ 查询变更记录
        results = service.users().history().list(
            userId='me',
            startHistoryId=history_id
        ).execute()

        changes = results.get('history', [])
        print(f"📌 检测到 {len(changes)} 条变更记录：")

        found = False
        for idx, change in enumerate(changes, 1):
            useful = False

            if 'messagesAdded' in change:
                useful = True
                for m in change['messagesAdded']:
                    print(f"🟢 新增邮件 ID: {m['message']['id']}")

            if 'messagesDeleted' in change:
                useful = True
                for m in change['messagesDeleted']:
                    print(f"🔴 删除邮件 ID: {m['message']['id']}")

            if 'labelsAdded' in change:
                useful = True
                for m in change['labelsAdded']:
                    labels = m.get('labelIds', [])
                    print(f"📌 加标签邮件 ID: {m['message']['id']} → {labels}")
                    if target_label in labels:
                        print(f"✅ 匹配成功：添加了标签 {target_label}")
                        found = True

            if 'labelsRemoved' in change:
                useful = True
                for m in change['labelsRemoved']:
                    labels = m.get('labelIds', [])
                    print(f"❌ 去标签邮件 ID: {m['message']['id']} → {labels}")

            if not useful:
                print(f"🔍 第 {idx} 条记录无实际变更字段（跳过）")

        return found

    except Exception as e:
        print(f"❌ 查询出错: {str(e)[:200]}")
        return False
