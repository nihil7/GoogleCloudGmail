from flask import Flask, request
import base64
import json
import os
from email_sender import send_email

app = Flask(__name__)

# 配置项
ENABLE_EMAIL_SENDING = True       # 设置为 False 即跳过发邮件
TARGET_LABEL_NAME = "0"
PRINT_LABEL_MAP = True


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
        forward_pubsub_message_email(decoded_json)

        return 'OK', 200
    except Exception as e:
        print(f"❌ 错误：{str(e)[:280]}")
        return 'Internal Server Error', 500


def handle_pubsub_message(envelope: dict) -> dict:
    """解析 Pub/Sub 推送消息，返回解码后的 JSON 数据"""
    if not envelope or 'message' not in envelope or 'data' not in envelope['message']:
        raise ValueError("⚠️ Pub/Sub 格式错误")

    data_b64 = envelope['message']['data']
    decoded_str = base64.urlsafe_b64decode(data_b64).decode('utf-8')
    decoded_json = json.loads(decoded_str)

    print(f"📨 解码后的消息内容：{decoded_json}")
    return decoded_json


def forward_pubsub_message_email(decoded_json: dict):
    """
    将 Gmail 推送的原始 JSON 内容作为邮件正文发送

    参数:
        decoded_json (dict): 由 handle_pubsub_message 解码得到的 Gmail 推送内容
    """
    # 格式化 JSON 内容，确保邮件正文可读性好
    content = json.dumps(decoded_json, ensure_ascii=False, indent=2)

    print("📄 已准备邮件内容")

    if ENABLE_EMAIL_SENDING:
        try:
            send_email(subject="📬 Gmail 推送原始内容", body=content)
        except Exception as e:
            print(f"❌ 邮件发送失败：{str(e)[:280]}")
    else:
        print("🚫 邮件发送功能关闭，未调用 send_email()")






# 本地调试入口
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
