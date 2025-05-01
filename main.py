from flask import Flask, request
import base64
import json
import os
import logging
from google.cloud import secretmanager
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import smtplib
from email.mime.text import MIMEText


app = Flask(__name__)

# === 日志配置 ===
logging.basicConfig(level=logging.INFO)

# === 配置项 ===
ENABLE_EMAIL_SENDING = False              # 是否发送原始推送内容邮件
ENABLE_NOTIFY_ON_LABEL = True           # 是否在标签添加后发送邮件通知
TARGET_LABEL_NAME = "Label_264791441972079941"                 # 要监控的标签

# === 主入口 ===
@app.route('/', methods=['POST'])
def receive_pubsub():
    """Flask 主入口：处理 Gmail 推送请求"""
    try:
        envelope = request.get_json()
        decoded_json = handle_pubsub_message(envelope)

        history_id_raw = decoded_json.get("historyId")
        history_id = str(history_id_raw).strip()

        if not history_id.isdigit():
            logging.warning(f"⚠️ 收到无效 historyId：{history_id_raw}（原始类型 {type(history_id_raw).__name__}）")
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


# === 函数：转发原始消息内容（含发件逻辑） ===
def forward_pubsub_message_email(decoded_json: dict):
    """将 Gmail 推送的原始 JSON 内容作为邮件正文发送"""

    content = json.dumps(decoded_json, ensure_ascii=False, indent=2)
    logging.info("📄 已准备邮件内容")

    if not os.environ.get('EMAIL_ADDRESS_QQ') or not os.environ.get('EMAIL_PASSWORD_QQ') or not os.environ.get('FORWARD_EMAIL'):
        logging.warning("⚠️ 缺少邮件环境变量，跳过发送")
        return

    if not ENABLE_EMAIL_SENDING:
        logging.info("🚫 邮件发送功能关闭，未调用发送")
        return

    sender_email = os.environ.get('EMAIL_ADDRESS_QQ')
    sender_password = os.environ.get('EMAIL_PASSWORD_QQ')
    receiver_email = os.environ.get('FORWARD_EMAIL')

    message = MIMEText(content, 'plain', 'utf-8')
    message['From'] = sender_email
    message['To'] = receiver_email
    message['Subject'] = "📬 Gmail 推送原始内容"

    try:
        server = smtplib.SMTP_SSL('smtp.qq.com', 465)
        server.login(sender_email, sender_password)
        server.sendmail(sender_email, [receiver_email], message.as_string())
        server.quit()
        logging.info("✅ 邮件已发送（原始推送）")
    except Exception as e:
        logging.exception(f"❌ 邮件发送失败：{e}")

# === 辅助函数：读取上一次 historyId ===
def read_previous_history_id() -> str:
    """从 Secret Manager 读取上一次成功处理的 historyId"""
    PROJECT_ID = "pushgamiltogithub"
    SECRET_NAME = "gmail_last_history_id"
    previous_id = ""

    try:
        sm_client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{PROJECT_ID}/secrets/{SECRET_NAME}/versions/latest"
        response = sm_client.access_secret_version(request={"name": name})
        previous_id = response.payload.data.decode("utf-8")

        if not previous_id or not previous_id.isdigit():
            logging.warning(f"⚠️ 读取到的 historyId 非数字格式：{previous_id}")

        logging.info(f"📖 读取上次 historyId：{previous_id}")
        return previous_id

    except Exception:
        logging.exception("⚠️ 无法读取上次 historyId，将跳过处理")
        raise

# === 辅助函数：保存当前 historyId ===
def save_current_history_id(history_id: str):
    """将新的 historyId 写入 Secret Manager"""
    try:
        PROJECT_ID = "pushgamiltogithub"
        SECRET_NAME = "gmail_last_history_id"
        sm_client = secretmanager.SecretManagerServiceClient()

        # 防御性处理
        history_id = str(history_id).strip()
        if not history_id.isdigit():
            raise ValueError(f"⚠️ 传入的 history_id 非纯数字：{history_id}")

        payload_bytes = history_id.encode("utf-8")
        parent = f"projects/{PROJECT_ID}/secrets/{SECRET_NAME}"
        sm_client.add_secret_version(
            request={"parent": parent, "payload": {"data": payload_bytes}}
        )

        logging.info(f"💾 已保存新的 historyId：{history_id}")

    except Exception:
        logging.exception(f"❌ 保存 historyId 失败（值：{history_id}）")
        raise


# === 函数：检测标签是否被添加 ===
def detect_label_addition(current_history_id: str, target_label: str) -> bool:
    """分析 Gmail history 是否有邮件被添加了指定标签，并记录变动日志"""
    try:
        logging.info(f"🔍 正在分析标签变更（标签：{target_label}）")

        # === 读取查询起点 ===
        start_id = read_previous_history_id()

        # === Secret 配置 ===
        PROJECT_ID = "pushgamiltogithub"
        SECRET_NAME = "gmail_token_json"
        SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

        sm_client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{PROJECT_ID}/secrets/{SECRET_NAME}/versions/latest"
        response = sm_client.access_secret_version(request={"name": name})
        token_data = json.loads(response.payload.data.decode("utf-8"))
        creds = Credentials.from_authorized_user_info(token_data, SCOPES)

        service = build('gmail', 'v1', credentials=creds)

        # ✅ 查询变更记录
        results = service.users().history().list(
            userId='me',
            startHistoryId=start_id
        ).execute()

        changes = results.get('history', [])
        logging.info(f"📌 共检测到 {len(changes)} 条变更记录")

        found = False
        for idx, change in enumerate(changes, 1):
            useful = False
            logging.info(f"📝 第 {idx} 条 history 变动详情: {json.dumps(change, ensure_ascii=False)}")

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

        # ✅ 处理完成后保存当前 historyId
        save_current_history_id(current_history_id)
        logging.info(f"✅ 标签变更处理完成，是否匹配：{found}")

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

            sender_email = os.environ.get('EMAIL_ADDRESS_QQ')
            sender_password = os.environ.get('EMAIL_PASSWORD_QQ')
            receiver_email = os.environ.get('FORWARD_EMAIL')

            if not all([sender_email, sender_password, receiver_email]):
                logging.warning("⚠️ 缺少邮件环境变量，跳过发送")
                return

            message = MIMEText(body, 'plain', 'utf-8')
            message['From'] = sender_email
            message['To'] = receiver_email
            message['Subject'] = subject

            server = smtplib.SMTP_SSL('smtp.qq.com', 465)
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, [receiver_email], message.as_string())
            server.quit()

            logging.info("✅ 标签通知邮件已发送")

        elif matched:
            logging.info("☑️ 匹配标签，但邮件提醒已关闭")
        else:
            logging.info("📭 未发现匹配标签")

    except Exception as e:
        logging.exception(f"❌ 标签通知邮件发送失败：{e}")


# === 本地调试入口 ===
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
