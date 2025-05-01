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

        # ✅ 可选：转发原始 Pub/Sub 内容邮件
        forward_pubsub_message_email(decoded_json)

        # ✅ 获取新增邮件 (msg_id, subject) 清单
        new_messages = detect_new_messages_only(history_id)  # 返回 List[Tuple[str, str]]

        # ✅ 筛选关键词“对账”，并发送邮件通知（如匹配）
        notify_if_subject_contains_keyword(new_messages, keyword="对账")

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


def detect_new_messages_only(current_history_id: str):
    """仅分析 Gmail 的新增邮件变动，返回 [(msg_id, subject)] 列表"""
    try:
        logging.info("🔍 正在获取 Gmail 变动记录（仅筛选新增邮件）")

        # === 读取上一次 historyId ===
        start_id = read_previous_history_id()

        # === Secret 配置 ===
        PROJECT_ID = "pushgamiltogithub"
        SECRET_NAME = "gmail_token_json"
        SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

        # === 获取 Gmail 凭据 ===
        sm_client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{PROJECT_ID}/secrets/{SECRET_NAME}/versions/latest"
        response = sm_client.access_secret_version(request={"name": name})
        token_data = json.loads(response.payload.data.decode("utf-8"))
        creds = Credentials.from_authorized_user_info(token_data, SCOPES)

        # === 构建 Gmail 客户端 ===
        service = build('gmail', 'v1', credentials=creds)

        # ✅ 查询历史变更记录
        results = service.users().history().list(
            userId='me',
            startHistoryId=start_id
        ).execute()

        changes = results.get('history', [])
        logging.info(f"📌 共检测到 {len(changes)} 条变更记录")

        message_info = []

        for idx, change in enumerate(changes, 1):
            if 'messagesAdded' in change:
                for m in change['messagesAdded']:
                    msg_id = m['message']['id']
                    try:
                        msg = service.users().messages().get(
                            userId='me', id=msg_id, format='metadata'
                        ).execute()
                        headers = msg.get('payload', {}).get('headers', [])
                        subject = next((h['value'] for h in headers if h['name'].lower() == 'subject'), '[无主题]')

                        logging.info(f"🆕 新邮件 ID: {msg_id}，主题: {subject}")
                        message_info.append((msg_id, subject))  # ✅ 添加 (id, subject)

                    except Exception as e:
                        logging.warning(f"⚠️ 获取邮件 {msg_id} 的主题失败：{e}")

        # ✅ 保存当前 historyId
        save_current_history_id(current_history_id)

        logging.info(f"✅ 本轮共检测到 {len(message_info)} 封新增邮件")
        return message_info

    except Exception:
        logging.exception("❌ 查询变动记录失败")
        return []

def notify_if_subject_contains_keyword(message_list: list, keyword: str):
    """
    筛选新邮件列表，若有主题包含关键词，则发送提醒邮件。
    :param message_list: List[Tuple[str, str]] or List[dict] - 每项为 (msg_id, subject) 或 {"id":..., "subject":...}
    :param keyword: 要匹配的关键词（如“对账”）
    """
    try:
        # 统一转换为 (msg_id, subject) 格式
        normalized = []
        for item in message_list:
            if isinstance(item, dict):
                msg_id = item.get("id") or item.get("messageId") or item.get("message_id")
                subject = item.get("subject", "")
                if msg_id and subject:
                    normalized.append((msg_id, subject))
            elif isinstance(item, (tuple, list)) and len(item) == 2:
                normalized.append((item[0], item[1]))
            else:
                logging.warning(f"⚠️ 无法识别的消息项结构：{item}")

        # 筛选匹配项
        matched = [(msg_id, subject) for msg_id, subject in normalized if keyword in subject]

        if not matched:
            logging.info(f"📭 未发现包含关键词“{keyword}”的邮件，跳过通知")
            return

        # 构造邮件正文
        body_lines = [f"🔎 共检测到 {len(matched)} 封包含关键词“{keyword}”的邮件：\n"]
        for idx, (msg_id, subject) in enumerate(matched, 1):
            body_lines.append(f"{idx}. 📧 主题: {subject}\n   🆔 ID: {msg_id}")
        body = "\n".join(body_lines)
        email_subject = f"📌 Gmail 新邮件提醒：包含“{keyword}”"

        # 获取环境变量
        sender_email = os.environ.get('EMAIL_ADDRESS_QQ')
        sender_password = os.environ.get('EMAIL_PASSWORD_QQ')
        receiver_email = os.environ.get('FORWARD_EMAIL')

        if not all([sender_email, sender_password, receiver_email]):
            logging.warning("⚠️ 缺少邮件环境变量，跳过发送")
            return

        # 构造并发送邮件
        message = MIMEText(body, 'plain', 'utf-8')
        message['From'] = sender_email
        message['To'] = receiver_email
        message['Subject'] = email_subject

        server = smtplib.SMTP_SSL('smtp.qq.com', 465)
        server.login(sender_email, sender_password)
        server.sendmail(sender_email, [receiver_email], message.as_string())
        server.quit()

        logging.info(f"✅ 邮件通知已发送，共匹配：{len(matched)} 封")

    except Exception as e:
        logging.exception(f"❌ 邮件提醒发送失败：{e}")




# === 本地调试入口 ===
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
