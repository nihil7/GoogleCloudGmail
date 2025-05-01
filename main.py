from flask import Flask, request
import base64
import json
import os
import logging
from email_sender import send_email
from google.cloud import secretmanager
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build


app = Flask(__name__)

# === 日志配置 ===
logging.basicConfig(level=logging.INFO)

# === 配置项 ===
ENABLE_EMAIL_SENDING = True             # 是否发送原始推送内容邮件
ENABLE_NOTIFY_ON_LABEL = True           # 是否在标签添加后发送邮件通知
TARGET_LABEL_NAME = "0"             # 要监控的标签
PRINT_LABEL_MAP = True                  # 保留调试项

# === 主入口 ===
@app.route('/', methods=['POST'])
def receive_pubsub():
    """Flask 主入口：处理 Gmail 推送请求"""
    try:
        envelope = request.get_json()
        decoded_json = handle_pubsub_message(envelope)

        history_id = decoded_json.get("historyId")
        if not history_id:
            logging.warning("⚠️ 未提供 historyId，跳过处理")
            return 'OK', 200

        logging.info(f"📌 收到 historyId: {history_id}")

        forward_pubsub_message_email(decoded_json)
        matched = detect_label_addition(history_id, TARGET_LABEL_NAME)
        notify_if_label_matched(matched, TARGET_LABEL_NAME, history_id)

        return 'OK', 200

    except Exception:
        logging.exception("❌ 程序异常")
        return 'Internal Server Error', 500

# === 函数：解析 Pub/Sub 消息 ===
def handle_pubsub_message(envelope: dict) -> dict:
    """解析 Pub/Sub 推送消息，返回解码后的 JSON 数据"""
    if not envelope or 'message' not in envelope or 'data' not in envelope['message']:
        raise ValueError("⚠️ Pub/Sub 格式错误")

    data_b64 = envelope['message']['data']
    decoded_str = base64.urlsafe_b64decode(data_b64).decode('utf-8')
    decoded_json = json.loads(decoded_str)

    logging.info(f"📨 解码后的消息内容：{decoded_json}")
    return decoded_json

# === 函数：转发原始消息内容 ===
def forward_pubsub_message_email(decoded_json: dict):
    """将 Gmail 推送的原始 JSON 内容作为邮件正文发送"""
    content = json.dumps(decoded_json, ensure_ascii=False, indent=2)
    logging.info("📄 已准备邮件内容")

    if ENABLE_EMAIL_SENDING:
        try:
            send_email(subject="📬 Gmail 推送原始内容", body=content)
            logging.info("✅ 邮件已发送（原始推送）")
        except Exception:
            logging.exception("❌ 邮件发送失败")
    else:
        logging.info("🚫 邮件发送功能关闭，未调用 send_email()")
# === 函数：检测标签是否被添加 ===
def detect_label_addition(history_id: str, target_label: str) -> bool:
    """分析 Gmail history 是否有邮件被添加了指定标签"""
    try:
        logging.info(f"🔍 正在分析标签变更（标签：{target_label}）")

        # === Secret 配置 ===
        PROJECT_ID = "pushgamiltogithub"
        SECRET_NAME = "gmail_token_json"
        SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

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
        logging.info(f"📌 共检测到 {len(changes)} 条变更记录")

        found = False
        for idx, change in enumerate(changes, 1):
            useful = False

            if 'messagesAdded' in change:
                useful = True
                for m in change['messagesAdded']:
                    logging.info(f"🟢 新增邮件 ID: {m['message']['id']}")

            if 'messagesDeleted' in change:
                useful = True
                for m in change['messagesDeleted']:
                    logging.info(f"🔴 删除邮件 ID: {m['message']['id']}")

            if 'labelsAdded' in change:
                useful = True
                for m in change['labelsAdded']:
                    labels = m.get('labelIds', [])
                    logging.info(f"📌 加标签邮件 ID: {m['message']['id']} → {labels}")
                    if target_label in labels:
                        logging.info(f"✅ 匹配成功：添加了标签 {target_label}")
                        found = True

            if 'labelsRemoved' in change:
                useful = True
                for m in change['labelsRemoved']:
                    labels = m.get('labelIds', [])
                    logging.info(f"❌ 去标签邮件 ID: {m['message']['id']} → {labels}")

            if not useful:
                logging.info(f"🔍 第 {idx} 条记录无实际变更字段（跳过）")

        return found

    except Exception:
        logging.exception("❌ 查询变更记录失败")
        return False

# === 函数：根据标签变更决定是否发送邮件通知 ===
def notify_if_label_matched(matched: bool, label: str, history_id: str):
    """根据匹配结果和开关配置决定是否发通知邮件"""
    try:
        if matched and ENABLE_NOTIFY_ON_LABEL:
            subject = f"📌 标签 [{label}] 已添加"
            body = f"收到 Gmail 推送，并发现有邮件添加了标签：{label}\n\n对应 historyId: {history_id}"
            send_email(subject=subject, body=body)
            logging.info("✅ 标签通知邮件已发送")
        elif matched:
            logging.info("☑️ 匹配标签，但邮件提醒已关闭")
        else:
            logging.info("📭 未发现匹配标签")

    except Exception:
        logging.exception("❌ 标签通知邮件发送失败")


# === 本地调试入口 ===
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
