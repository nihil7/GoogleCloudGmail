# === 标准库 ===
import os
import json
import time
import base64
import logging
import threading
import smtplib
from email.mime.text import MIMEText
from datetime import datetime

# === 第三方库 ===
from flask import Flask, request
from google.cloud import secretmanager
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.cloud import firestore
import requests


app = Flask(__name__)

# === 日志配置 ===
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# === 配置项 ===
APP_ENV = os.environ.get("APP_ENV", "cloud").lower()  # cloud | local
GCP_PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "pushgamiltogithub")
GMAIL_TOKEN_SECRET = os.environ.get("GMAIL_TOKEN_SECRET", "gmail_token_json")
GMAIL_TOKEN_FILE = os.environ.get("GMAIL_TOKEN_FILE", "secrets/gmail_token.json")
STATE_BACKEND = os.environ.get("STATE_BACKEND", "firestore" if APP_ENV == "cloud" else "file").lower()  # firestore | file
LOCAL_STATE_FILE = os.environ.get("LOCAL_STATE_FILE", "data/last_history_id.json")
DEFAULT_HISTORY_ID = os.environ.get("DEFAULT_HISTORY_ID", "50702")

ENABLE_EMAIL_SENDING = False
ENABLE_NOTIFY_ON_LABEL = True
ENABLE_GITHUB_NOTIFY = True
ENABLE_TRIGGER_GITHUB = True
ENABLE_WATCH_REFRESH_EMAIL = os.environ.get("ENABLE_WATCH_REFRESH_EMAIL", "false").lower() == "true"
TARGET_LABEL_NAME = "Label_264791441972079941"
GITHUB_REPO = "nihil7/MeidiAuto"
GITHUB_WORKFLOW = "run-daily.yml"
GITHUB_REF = "main"
KEYWORDS = ["骏都对帐表"]
WATCH_TOPIC_NAME = os.environ.get("WATCH_TOPIC_NAME", f"projects/{GCP_PROJECT_ID}/topics/gmailtocloud")


def _ensure_parent_dir(file_path: str):
    parent = os.path.dirname(file_path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def load_token_data() -> dict:
    """根据运行模式读取 Gmail token json。"""
    if APP_ENV == "local":
        with open(GMAIL_TOKEN_FILE, "r", encoding="utf-8") as f:
            return json.load(f)

    sm_client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{GCP_PROJECT_ID}/secrets/{GMAIL_TOKEN_SECRET}/versions/latest"
    response = sm_client.access_secret_version(request={"name": name})
    return json.loads(response.payload.data.decode("utf-8"))


def load_gmail_service():
    """从 Secret Manager 加载 Gmail token，并返回可用的 Gmail service。"""
    scopes = ['https://www.googleapis.com/auth/gmail.modify']

    token_data = load_token_data()
    creds = Credentials.from_authorized_user_info(token_data, scopes)

    # 提前刷新一次，便于在调用 Gmail API 前给出可读性更好的错误日志
    if creds.expired or not creds.valid:
        creds.refresh(Request())

    return build('gmail', 'v1', credentials=creds, cache_discovery=False)


def load_gmail_service():
    """从 Secret Manager 加载 Gmail token，并返回可用的 Gmail service。"""
    project_id = "pushgamiltogithub"
    secret_name = "gmail_token_json"
    scopes = ['https://www.googleapis.com/auth/gmail.modify']

    sm_client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project_id}/secrets/{secret_name}/versions/latest"
    response = sm_client.access_secret_version(request={"name": name})
    token_data = json.loads(response.payload.data.decode("utf-8"))
    creds = Credentials.from_authorized_user_info(token_data, scopes)

    # 提前刷新一次，便于在调用 Gmail API 前给出可读性更好的错误日志
    if creds.expired or not creds.valid:
        creds.refresh(Request())

    return build('gmail', 'v1', credentials=creds, cache_discovery=False)

@app.route('/', methods=['POST'])
def receive_pubsub():
    start_time = time.time()
    envelope = request.get_json()
    logging.info("\U0001f4e8 收到 Pub/Sub 消息：%s", envelope)

    t = threading.Thread(target=process_pubsub_message, args=(envelope,))
    t.daemon = True
    t.start()

    elapsed_ms = round((time.time() - start_time) * 1000)
    logging.info(f"\U0001f4e4 已立即返回 200 OK（耗时 {elapsed_ms}ms）")
    return 'OK', 200

def process_pubsub_message(envelope):
    start_time = time.time()
    try:
        decoded_json = handle_pubsub_message(envelope)
        if not decoded_json:
            logging.warning("⚠️ 解码失败")
            return

        if ENABLE_EMAIL_SENDING:
            forward_pubsub_message_email(decoded_json)

        history_id_raw = decoded_json.get("historyId")
        history_id = str(history_id_raw).strip()
        if not history_id.isdigit():
            logging.warning(f"⚠️ 无效 historyId：{history_id_raw}")
            return

        last_history_id = read_history_id_from_firestore()

        if int(history_id) <= int(last_history_id):
            logging.warning(f"⚠️ 收到的 historyId（{history_id}）不大于已保存的（{last_history_id}），跳过本轮处理")
            return

        logging.info(f"📌 异步处理中 historyId: {history_id}，线程ID: {threading.get_ident()}")

        new_messages = detect_new_messages_only(history_id)

        for keyword in KEYWORDS:
            matched = find_messages_with_keyword(new_messages, keyword=keyword)
            if matched:
                if ENABLE_NOTIFY_ON_LABEL:
                    send_keyword_notification(matched, keyword=keyword)
                    time.sleep(2)  # 防止连续发信被拒绝
                if ENABLE_TRIGGER_GITHUB:
                    triggered, github_response = trigger_github_workflow()
                    if triggered and ENABLE_GITHUB_NOTIFY:
                        send_github_trigger_email(github_response)
                        time.sleep(2)  # 防止连续发信被拒绝
        elapsed = round(time.time() - start_time, 2)
        logging.info(f"✅ 异步处理完成（耗时 {elapsed}s）")

    except Exception as e:
        logging.exception(f"❌ 异步处理异常：{e}")

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
def read_history_id_from_firestore() -> str:
    if STATE_BACKEND == "file":
        if not os.path.exists(LOCAL_STATE_FILE):
            logging.warning(f"⚠️ 本地 historyId 文件不存在，初始化：{LOCAL_STATE_FILE}")
            _ensure_parent_dir(LOCAL_STATE_FILE)
            with open(LOCAL_STATE_FILE, "w", encoding="utf-8") as f:
                json.dump({"value": DEFAULT_HISTORY_ID}, f, ensure_ascii=False)
            return "0"

        with open(LOCAL_STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        value = str(data.get("value", "0"))
        logging.info(f"📖 本地文件读取到 historyId：{value}")
        return value

    db = firestore.Client()
    doc_ref = db.collection("gmail_state").document("last_history_id")
    doc = doc_ref.get()

    if doc.exists:
        value = doc.to_dict().get("value", "")
        logging.info(f"📖 Firestore 读取到 historyId：{value}")
        return value

    logging.warning("⚠️ Firestore 中未找到 historyId，正在初始化默认值 '0'")
    doc_ref.set({"value": DEFAULT_HISTORY_ID})
    return "0"



# === 辅助函数：保存当前 historyId ===
def save_history_id_to_firestore(history_id: str):
    if STATE_BACKEND == "file":
        _ensure_parent_dir(LOCAL_STATE_FILE)
        with open(LOCAL_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"value": history_id}, f, ensure_ascii=False)
        logging.info(f"✅ 本地文件已保存 historyId：{history_id}")
        return

    db = firestore.Client()
    doc_ref = db.collection("gmail_state").document("last_history_id")
    doc_ref.set({"value": history_id})
    logging.info(f"✅ Firestore 已保存 historyId：{history_id}")



def detect_new_messages_only(current_history_id: str):
    """仅分析 Gmail 的新增未读邮件变动，返回 [(msg_id, subject)] 列表"""
    try:
        logging.info("🔍 正在获取 Gmail 变动记录（仅筛选新增未读邮件）")

        # === 读取上一次 historyId ===
        # 替换后（改用 Firestore）
        start_id = read_history_id_from_firestore()

        # === 构建 Gmail 客户端 ===
        service = load_gmail_service()

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

                        # ✅ 仅处理包含 UNREAD 标签的新增邮件
                        if 'UNREAD' not in msg.get('labelIds', []):
                            logging.info(f"⏩ 已读邮件跳过（ID: {msg_id}）")
                            continue

                        headers = msg.get('payload', {}).get('headers', [])
                        subject = next((h['value'] for h in headers if h['name'].lower() == 'subject'), '[无主题]')

                        logging.info(f"🆕 新邮件 ID: {msg_id}，主题: {subject}")
                        message_info.append((msg_id, subject))

                    except Exception as e:
                        logging.warning(f"⚠️ 获取邮件 {msg_id} 的主题失败：{e}")

        # ✅ 保存当前 historyId
        save_history_id_to_firestore(current_history_id)

        logging.info(f"✅ 本轮共检测到 {len(message_info)} 封新增未读邮件")
        return message_info

    except RefreshError:
        logging.exception(
            "❌ Gmail 授权失效（invalid_grant）。请重新执行 OAuth 授权并更新 Secret "
            f"projects/{GCP_PROJECT_ID}/secrets/{GMAIL_TOKEN_SECRET}。"
        )
        return []
    except Exception:
        logging.exception("❌ 查询变动记录失败")
        return []

def find_messages_with_keyword(message_list: list, keyword: str):
    try:
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

        matched = [(msg_id, subject) for msg_id, subject in normalized if keyword in subject]

        if not matched:
            logging.info(f"📭 未发现包含关键词“{keyword}”的邮件")
            return []

        logging.info(f"📬 找到 {len(matched)} 封包含关键词“{keyword}”的邮件：")
        for msg_id, subject in matched:
            logging.info(f"🧾 ID: {msg_id} | 主题: {subject}")

        return matched

    except Exception as e:
        logging.exception(f"❌ 查找关键词异常：{e}")
        return []


def send_keyword_notification(matched: list, keyword: str):
    try:
        if not ENABLE_NOTIFY_ON_LABEL:
            logging.info("🚫 邮件发送功能关闭，未调用发送")
            return

        body_lines = [f"🔎 共检测到 {len(matched)} 封包含关键词“{keyword}”的邮件：\n"]
        for idx, (msg_id, subject) in enumerate(matched, 1):
            body_lines.append(f"{idx}. 📧 主题: {subject}\n   🆔 ID: {msg_id}")
        body = "\n".join(body_lines)
        email_subject = f"📌 Gmail 新邮件提醒：包含“{keyword}”"

        sender_email = os.environ.get('EMAIL_ADDRESS_QQ')
        sender_password = os.environ.get('EMAIL_PASSWORD_QQ')
        receiver_email = os.environ.get('FORWARD_EMAIL')

        if not all([sender_email, sender_password, receiver_email]):
            logging.warning("⚠️ 缺少邮件环境变量，跳过发送")
            return

        message = MIMEText(body, 'plain', 'utf-8')
        message['From'] = sender_email
        message['To'] = receiver_email
        message['Subject'] = email_subject

        with smtplib.SMTP_SSL('smtp.qq.com', 465) as server:
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, [receiver_email], message.as_string())

        logging.info(f"✅ 邮件通知已发送，共匹配：{len(matched)} 封")

    except Exception as e:
        logging.exception(f"❌ 邮件提醒发送失败：{e}")

def trigger_github_workflow():
    try:
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            logging.error("❌ GitHub Token 缺失")
            return False, "Missing GitHub Token"

        url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/workflows/{GITHUB_WORKFLOW}/dispatches"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json"
        }
        payload = json.dumps({"ref": GITHUB_REF})

        response = requests.post(url, headers=headers, data=payload)
        logging.info(f"📡 GitHub 响应状态码: {response.status_code}")
        logging.info(f"📦 GitHub 响应内容: {response.text}")

        return response.status_code == 204, response.text
    except Exception as e:
        logging.exception("❌ GitHub 请求异常")
        return False, str(e)


def send_github_trigger_email(response_text):
    try:
        sender_email = os.environ.get('EMAIL_ADDRESS_QQ')
        sender_password = os.environ.get('EMAIL_PASSWORD_QQ')
        receiver_email = os.environ.get('FORWARD_EMAIL')

        if not all([sender_email, sender_password, receiver_email]):
            logging.warning("⚠️ 缺少邮件环境变量，跳过发送")
            return

        body = f"✅ Google Cloud已触发GitHub Actions工作流：{GITHUB_WORKFLOW}\n\n返回信息：\n{response_text}"
        message = MIMEText(body, 'plain', 'utf-8')
        message['From'] = sender_email
        message['To'] = receiver_email
        message['Subject'] = "✅ Google Cloud已触发GitHub Actions"

        server = smtplib.SMTP_SSL('smtp.qq.com', 465)
        server.login(sender_email, sender_password)
        server.sendmail(sender_email, [receiver_email], message.as_string())
        server.quit()

        logging.info("✉️ GitHub 触发通知邮件已发送")

    except Exception as e:
        logging.exception("❌ GitHub 通知邮件发送失败")

@app.route("/refresh_watch", methods=["GET"])
def refresh_gmail_watch():
    try:
        logging.info("📡 正在刷新 Gmail Watch 设置...")
        service = load_gmail_service()

        request_body = {
            "topicName": WATCH_TOPIC_NAME
        }

        logging.info("📤 Watch 请求体: %s", json.dumps(request_body, indent=2))

        result = service.users().watch(userId='me', body=request_body).execute()
        expiration = result.get("expiration")
        logging.info(f"✅ Watch 刷新成功，有效期至: {expiration}")
        logging.info("📦 返回内容: %s", json.dumps(result, indent=2))

        if expiration:
            expire_time = datetime.fromtimestamp(int(expiration) / 1000)
            logging.info(f"🕒 Watch 到期时间: {expire_time}")

        if expiration and os.environ.get("ENABLE_WATCH_REFRESH_EMAIL", "false").lower() == "true":
            send_watch_refresh_email(expiration)

        return "✅ Gmail Watch 刷新成功", 200

    except RefreshError:
        logging.exception(
            "❌ Gmail Watch 刷新失败：授权已失效（invalid_grant）。请重新授权并更新 Secret。"
        )
        return "❌ 刷新失败：Gmail 授权失效，请更新 token", 500
    except Exception as e:
        logging.exception("❌ Gmail Watch 刷新失败")
        return "❌ 刷新失败", 500


def send_watch_refresh_email(expiration):
    try:
        expire_time = datetime.fromtimestamp(int(expiration) / 1000)
        subject = "✅ Gmail Watch 已刷新（Cloud Run）"
        body = f"""✅ Gmail Watch 已成功刷新

🕒 到期时间（北京时间）：{expire_time.strftime('%Y-%m-%d %H:%M:%S')}

⏰ 建议设置每日刷新，避免 Watch 到期失效。
"""
        send_email_via_qq(subject, body)

    except Exception as e:
        logging.exception("❌ Watch 刷新通知封装失败")


def send_email_via_qq(subject: str, body: str) -> bool:
    """
    使用 QQ 邮箱发送邮件。需配置以下环境变量：
    EMAIL_ADDRESS_QQ、EMAIL_PASSWORD_QQ、FORWARD_EMAIL
    """
    try:
        sender_email = os.environ.get('EMAIL_ADDRESS_QQ')
        sender_password = os.environ.get('EMAIL_PASSWORD_QQ')
        receiver_email = os.environ.get('FORWARD_EMAIL')

        if not all([sender_email, sender_password, receiver_email]):
            logging.warning("⚠️ 缺少邮件环境变量，跳过发信")
            return False

        message = MIMEText(body, 'plain', 'utf-8')
        message['From'] = sender_email
        message['To'] = receiver_email
        message['Subject'] = subject

        try:
            server = smtplib.SMTP_SSL('smtp.qq.com', 465, timeout=10)
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, [receiver_email], message.as_string())
            server.quit()
            logging.info("📧 邮件发送成功")
            return True
        except Exception as e:
            logging.exception("❌ SMTP 邮件发送失败")
            return False

    except Exception as e:
        logging.exception("❌ 邮件模块异常")
        return False
