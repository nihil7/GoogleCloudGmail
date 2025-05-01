from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import os.path

# 🛡 授权范围：只读 Gmail 权限（可访问 history 接口）
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

def get_gmail_service():
    """初始化 Gmail API 服务对象，含本地 token 缓存"""
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    return build('gmail', 'v1', credentials=creds)

def fetch_gmail_changes(history_id):
    """查询 Gmail 邮件变更历史"""
    service = get_gmail_service()

    results = service.users().history().list(
        userId='me',
        startHistoryId=history_id,
        historyTypes=['messageAdded']
    ).execute()

    changes = results.get('history', [])
    print(f"📌 总共变更记录：{len(changes)}")

    for change in changes:
        for msg in change.get('messagesAdded', []):
            msg_id = msg['message']['id']
            msg_detail = service.users().messages().get(userId='me', id=msg_id, format='metadata', metadataHeaders=['From', 'Subject']).execute()
            headers = msg_detail.get('payload', {}).get('headers', [])
            sender = next((h['value'] for h in headers if h['name'] == 'From'), '未知发件人')
            subject = next((h['value'] for h in headers if h['name'] == 'Subject'), '无主题')
            print(f"✉️ 新邮件：{sender} - {subject}")

if __name__ == '__main__':
    # ✅ 示例：使用手动输入的 historyId
    history_id = input("请输入 historyId：")
    fetch_gmail_changes(history_id)
