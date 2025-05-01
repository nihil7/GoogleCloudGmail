from flask import Flask, request
import base64
import json
import os
from email_sender import send_email
from label_checker import analyze_gmail_history  # ✅ 子程序导入

app = Flask(__name__)

# === 配置项 ===
ENABLE_EMAIL_SENDING = True             # 是否发送原始推送内容邮件
ENABLE_NOTIFY_ON_LABEL = True           # 是否在标签添加后发送邮件通知
TARGET_LABEL_NAME = "INBOX"             # 要监控的标签（建议 INBOX, UNREAD 等大写）
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
            print("⚠️ 未提供 historyId，跳过处理")
            return 'OK', 200

        print(f"📌 收到 historyId: {history_id}")

        # 邮件通知 1：原始推送内容
        forward_pubsub_message_email(decoded_json)

        # 邮件通知 2：标签变更分析
        check_label_and_notify(history_id, TARGET_LABEL_NAME)

        return 'OK', 200

    except Exception as e:
        print(f"❌ 错误：{str(e)[:280]}")
        return 'Internal Server Error', 500

# === 函数：解析 Pub/Sub 消息 ===
def handle_pubsub_message(envelope: dict) -> dict:
    """解析 Pub/Sub 推送消息，返回解码后的 JSON 数据"""
    if not envelope or 'message' not in envelope or 'data' not in envelope['message']:
        raise ValueError("⚠️ Pub/Sub 格式错误")

    data_b64 = envelope['message']['data']
    decoded_str = base64.urlsafe_b64decode(data_b64).decode('utf-8')
    decoded_json = json.loads(decoded_str)

    print(f"📨 解码后的消息内容：{decoded_json}")
    return decoded_json

# === 函数：转发原始消息内容 ===
def forward_pubsub_message_email(decoded_json: dict):
    """将 Gmail 推送的原始 JSON 内容作为邮件正文发送"""
    content = json.dumps(decoded_json, ensure_ascii=False, indent=2)
    print("📄 已准备邮件内容")

    if ENABLE_EMAIL_SENDING:
        try:
            send_email(subject="📬 Gmail 推送原始内容", body=content)
        except Exception as e:
            print(f"❌ 邮件发送失败：{str(e)[:280]}")
    else:
        print("🚫 邮件发送功能关闭，未调用 send_email()")

# === 函数：调用子程序并决定是否发邮件 ===
def check_label_and_notify(history_id: str, target_label: str):
    """调用标签分析函数，并根据配置决定是否发送提醒邮件"""
    try:
        print(f"🔍 正在分析标签变更（标签：{target_label}）")
        matched = analyze_gmail_history(history_id, target_label)

        if matched and ENABLE_NOTIFY_ON_LABEL:
            subject = f"📌 标签 [{target_label}] 已添加"
            body = f"收到 Gmail 推送，并发现有邮件添加了标签：{target_label}\n\n对应 historyId: {history_id}"
            send_email(subject=subject, body=body)
        elif matched:
            print("☑️ 匹配标签，但邮件提醒已关闭")
        else:
            print("📭 未发现匹配标签")

    except Exception as e:
        print(f"❌ 检测标签或发送邮件失败：{str(e)[:280]}")

# === 本地调试入口 ===
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
