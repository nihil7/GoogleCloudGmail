import json
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# === 配置区域 ===
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']
TOKEN_PATH = 'token.json'

def get_gmail_service():
    """初始化 Gmail API 客户端（使用本地 token.json）"""
    with open(TOKEN_PATH, 'r') as f:
        token_data = json.load(f)
    creds = Credentials.from_authorized_user_info(token_data, SCOPES)
    return build('gmail', 'v1', credentials=creds)

def fetch_meaningful_gmail_changes(history_id: str):
    """仅打印有实际变更类型的 Gmail history 记录"""
    service = get_gmail_service()
    results = service.users().history().list(
        userId='me',
        startHistoryId=history_id
    ).execute()

    changes = results.get('history', [])
    print(f"📌 总共返回 {len(changes)} 条变更记录（包含无效记录）")

    count = 0
    for change in changes:
        meaningful = False

        if 'messagesAdded' in change:
            meaningful = True
            for m in change['messagesAdded']:
                print(f"🟢 新增邮件 ID: {m['message']['id']}")
        if 'messagesDeleted' in change:
            meaningful = True
            for m in change['messagesDeleted']:
                print(f"🔴 删除邮件 ID: {m['message']['id']}")
        if 'labelsAdded' in change:
            meaningful = True
            for m in change['labelsAdded']:
                labels = m.get('labelIds', [])
                print(f"📌 加标签邮件 ID: {m['message']['id']} → {labels}")
        if 'labelsRemoved' in change:
            meaningful = True
            for m in change['labelsRemoved']:
                labels = m.get('labelIds', [])
                print(f"❌ 去标签邮件 ID: {m['message']['id']} → {labels}")

        if meaningful:
            count += 1

    print(f"\n✅ 实际有用变更记录：{count} 条")

if __name__ == '__main__':
    history_id_input = input("请输入 historyId：").strip()
    fetch_meaningful_gmail_changes(history_id_input)
