import os
import pickle
import logging
import traceback
import datetime
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
import google.auth.transport.requests

# 🔵 设置日志等级为DEBUG
logging.basicConfig(level=logging.DEBUG)
logging.getLogger('googleapiclient.discovery_cache').setLevel(logging.DEBUG)
logging.getLogger('googleapiclient.discovery').setLevel(logging.DEBUG)
logging.getLogger('googleapiclient.http').setLevel(logging.DEBUG)
logging.getLogger('urllib3').setLevel(logging.DEBUG)

# 🔵 需要的权限范围
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

def get_gmail_service():
    """
    获取 Gmail API service对象（OAuth 2.0用户授权方式）
    """
    creds = None
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)

        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)

    service = build('gmail', 'v1', credentials=creds)
    return service

def get_label_name_by_id(service, label_id):
    """
    通过 label_id 查询真实的标签名字
    """
    try:
        labels_result = service.users().labels().list(userId='me').execute()
        labels = labels_result.get('labels', [])
        if not labels:
            print("❌ 标签列表为空！")
            return None
        for label in labels:
            if label.get('id') == label_id:
                label_name = label.get('name', None)
                if label_name:
                    return label_name
                else:
                    print(f"⚠️ 标签ID {label_id} 找到了，但是名字为空！")
                    return None
        print(f"❌ 没有找到对应的标签ID: {label_id}")
        return None
    except Exception as e:
        print(f"❌ 查询标签列表失败: {str(e)}")
        traceback.print_exc()
        return None

def get_message_info(service, message_id):
    """
    查询某封邮件的标题和接收时间
    """
    try:
        message = service.users().messages().get(userId='me', id=message_id, format='metadata', metadataHeaders=['Subject']).execute()
        headers = message.get('payload', {}).get('headers', [])
        subject = next((h['value'] for h in headers if h['name'] == 'Subject'), '(无标题)')
        internal_date = int(message.get('internalDate'))  # internalDate是毫秒级时间戳
        return subject, internal_date
    except Exception as e:
        print(f"❌ 查询邮件失败: {str(e)}")
        traceback.print_exc()
        return '(查询失败)', 0

def format_timestamp(ms):
    """
    把 internalDate 毫秒时间戳转成人类可读格式（北京时间）
    """
    dt = datetime.datetime.utcfromtimestamp(ms / 1000.0) + datetime.timedelta(hours=8)
    return dt.strftime('%Y-%m-%d %H:%M:%S')

def check_mail_changes_and_labels(service, start_history_id):
    """
    查询邮件变化，并解析标签名字，同时拉取邮件标题和接收时间
    """
    try:
        print(f"🔵 正在从 historyId {start_history_id} 查询邮件变化...")
        results = service.users().history().list(
            userId='me',
            startHistoryId=start_history_id,
            historyTypes=['messageAdded', 'messageDeleted', 'labelAdded', 'labelRemoved']
        ).execute()

        histories = results.get('history', [])

        if not histories:
            print("✅ 没有检测到任何变化。")
            return

        print(f"✅ 检测到 {len(histories)} 个变化记录：")
        for item in histories:
            print("🧩 变化记录ID:", item.get('id'))

            if 'messagesAdded' in item:
                for added in item['messagesAdded']:
                    msg = added['message']
                    message_id = msg.get('id')
                    subject, internal_date = get_message_info(service, message_id)
                    human_time = format_timestamp(internal_date)
                    print(f"📩 新邮件 - ID: {message_id}, 标题: {subject}, 接收时间: {human_time}")

            if 'labelsAdded' in item:
                for label_added in item['labelsAdded']:
                    msg = label_added['message']
                    message_id = msg.get('id')
                    label_ids = label_added['labelIds']
                    subject, internal_date = get_message_info(service, message_id)
                    human_time = format_timestamp(internal_date)
                    print(f"🏷️ 邮件 {message_id} (标题: {subject}, 接收时间: {human_time}) 新增了标签IDs: {label_ids}")
                    for label_id in label_ids:
                        label_name = get_label_name_by_id(service, label_id)
                        if label_name:
                            print(f"🔖 标签名字: {label_name}")
                        else:
                            print(f"⚠️ 找不到标签ID: {label_id}")

            if 'labelsRemoved' in item:
                for label_removed in item['labelsRemoved']:
                    msg = label_removed['message']
                    message_id = msg.get('id')
                    label_ids = label_removed['labelIds']
                    subject, internal_date = get_message_info(service, message_id)
                    human_time = format_timestamp(internal_date)
                    print(f"🗑️ 邮件 {message_id} (标题: {subject}, 接收时间: {human_time}) 移除了标签IDs: {label_ids}")
                    for label_id in label_ids:
                        label_name = get_label_name_by_id(service, label_id)
                        if label_name:
                            print(f"🔖 移除的标签名字: {label_name}")
                        else:
                            print(f"⚠️ 找不到标签ID: {label_id}")

    except Exception as e:
        print(f"❌ 查询变化失败: {str(e)}")
        traceback.print_exc()

if __name__ == "__main__":
    try:
        service = get_gmail_service()

        old_history_id = '42199'  # 🔥 这里填你的起始historyId
        check_mail_changes_and_labels(service, old_history_id)

    except Exception as e:
        print(f"❌ 程序整体异常: {str(e)}")
        traceback.print_exc()
