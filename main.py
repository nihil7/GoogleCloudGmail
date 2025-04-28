from flask import Flask, request
import smtplib
from email.mime.text import MIMEText
import os
import base64
import json
from googleapiclient.discovery import build
from google.oauth2 import service_account

app = Flask(__name__)

# 初始化 Gmail API 服务
def get_gmail_service():
    SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']
    SERVICE_ACCOUNT_FILE = 'your-service-account.json'  # ⚡换成你上传到Cloud Run的文件名

    credentials = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES)

    service = build('gmail', 'v1', credentials=credentials)
    return service

# 发送邮件
def send_email_via_smtp(subject, body):
    sender_email = os.environ.get('EMAIL_ADDRESS_QQ')
    sender_password = os.environ.get('EMAIL_PASSWORD_QQ')
    receiver_email = os.environ.get('FORWARD_EMAIL')

    missing_vars = []
    if not sender_email:
        missing_vars.append('EMAIL_ADDRESS_QQ')
    if not sender_password:
        missing_vars.append('EMAIL_PASSWORD_QQ')
    if not receiver_email:
        missing_vars.append('FORWARD_EMAIL')

    if missing_vars:
        raise ValueError(f"❌ 缺少以下环境变量: {', '.join(missing_vars)}")

    message = MIMEText(body, 'plain', 'utf-8')
    message['From'] = sender_email
    message['To'] = receiver_email
    message['Subject'] = subject

    server = smtplib.SMTP_SSL('smtp.qq.com', 465)
    server.login(sender_email, sender_password)
    server.sendmail(sender_email, [receiver_email], message.as_string())
    server.quit()

    print("✅ 邮件发送成功")

# 拉取历史变化记录
def get_gmail_history(service, start_history_id):
    try:
        response = service.users().history().list(
            userId='me',
            startHistoryId=start_history_id,
            historyTypes=['labelAdded'],
            maxResults=100
        ).execute()

        history_records = response.get('history', [])
        print(f"✅ 拉取到变化记录数量: {len(history_records)}")
        return history_records

    except Exception as e:
        print(f"❌ 拉取history变化出错: {str(e)}")
        return []

# 提取打标签变化
def extract_label_added_changes(history_records):
    label_changes = []

    for record in history_records:
        if 'labelsAdded' in record:
            for change in record['labelsAdded']:
                message_id = change['message']['id']
                added_labels = change.get('labelIds', [])

                label_changes.append({
                    'message_id': message_id,
                    'added_labels': added_labels
                })

    print(f"✅ 提取到{len(label_changes)}条打标签变化")
    return label_changes

# 生成邮件正文
def generate_label_added_email_body(label_changes):
    if not label_changes:
        return "✅ 本次没有检测到任何打标签变化。"

    lines = []
    lines.append("📬 Gmail变动提醒（打标签事件）\n")
    lines.append("以下邮件打了新的标签：\n")

    for change in label_changes:
        msg_id = change['message_id']
        labels = ', '.join(change['added_labels'])
        lines.append(f"- 邮件ID: {msg_id} ➔ 添加标签: {labels}")

    lines.append(f"\n（本次共检测到{len(label_changes)}条变化）")

    email_body = '\n'.join(lines)
    return email_body

@app.route('/', methods=['POST'])
def receive_pubsub():
    envelope = request.get_json()
    if not envelope:
        return 'Bad Request: No JSON', 400

    if 'message' not in envelope or 'data' not in envelope['message']:
        return 'Bad Request: Invalid Pub/Sub message format', 400

    try:
        data_b64 = envelope['message']['data']
        decoded_bytes = base64.urlsafe_b64decode(data_b64)
        decoded_str = decoded_bytes.decode('utf-8')
        decoded_json = json.loads(decoded_str)
        print(f"✅ 解码后的PubSub消息：{decoded_json}")
    except Exception as e:
        print(f"❌ 解码失败: {str(e)}")
        return 'Bad Request: Decode Error', 400

    history_id = decoded_json.get('historyId')
    if not history_id:
        print("⚠️ 没有发现historyId，跳过处理")
        return 'OK', 200

    # 正式处理变化
    service = get_gmail_service()
    history_records = get_gmail_history(service, start_history_id=history_id)
    label_changes = extract_label_added_changes(history_records)

    if label_changes:
        email_body = generate_label_added_email_body(label_changes)
        send_email_via_smtp(subject="📬 Gmail打标签变动提醒", body=email_body)
    else:
        print("✅ 本次没有打标签变化，不发邮件")

    return 'OK', 200

if __name__ == '__main__':
    app.run(port=8080)
