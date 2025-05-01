from flask import Flask, request
import base64
import json
import os
from gmail_history_handler import fetch_and_analyze_history, generate_email_content
from email_sender import send_email

app = Flask(__name__)

# 🛠️ 配置集中区
SEND_FIRST_NOTIFICATION = False  # 是否发送第一封【收到推送】邮件
TARGET_LABEL_NAME = "0"      # 目标标签名称（注意大小写，推荐用 INBOX）
PRINT_LABEL_MAP = True  # 👈 相当于强制开启调试打印


@app.route('/', methods=['POST'])
def receive_pubsub():
    # 第1步：可选发第一封提醒邮件
    if SEND_FIRST_NOTIFICATION:
        try:
            send_email(
                subject="📬 收到Gmail推送提醒",
                body="✅ 成功收到Gmail Pub/Sub推送通知。准备解析并处理。"
            )
            print("✅ 已发送【收到推送】邮件")
        except Exception as e:
            print(f"❌ 发送【收到推送】邮件失败: {str(e)[:280]}")
    else:
        print("ℹ️ 配置关闭了第一封【收到推送】邮件发送")

    # 第2步：解析 Pub/Sub 消息
    envelope = request.get_json()
    if not envelope:
        print("❌ 无有效JSON数据")
        return 'Bad Request: No JSON', 400

    if 'message' not in envelope or 'data' not in envelope['message']:
        print("❌ Pub/Sub格式异常")
        return 'Bad Request: Invalid Pub/Sub message', 400

    try:
        data_b64 = envelope['message']['data']
        decoded_str = base64.urlsafe_b64decode(data_b64).decode('utf-8')
        decoded_json = json.loads(decoded_str)
        print(f"📨 解码后消息内容：{decoded_json}")
    except Exception as e:
        print(f"❌ 解码失败: {str(e)[:280]}")
        return 'Bad Request: Decode Error', 400

    history_id = decoded_json.get('historyId')
    if not history_id:
        print("⚠️ 没有找到 historyId，跳过处理")
        return 'OK', 200

    print(f"📌 收到 historyId: {history_id}")

    # 第3步：拉取 Gmail 历史变更并分析
    try:
        full_changes, matching_message_ids = fetch_and_analyze_history(
            history_id, target_label_name=TARGET_LABEL_NAME
        )
    except Exception as e:
        print(f"❌ 拉取 Gmail 变化失败: {str(e)[:280]}")
        return 'Internal Server Error', 500

    # 第4步：有变化才发第二封邮件
    try:
        if matching_message_ids:
            detailed_content = generate_email_content(full_changes, matching_message_ids)
            send_email(
                subject="🎯 检测到 Gmail 打标签变化",
                body=detailed_content
            )
            print(f"✅ 已发送【标签命中】邮件，匹配数: {len(matching_message_ids)}")
        else:
            print("✅ 本次无标签命中邮件")

    except Exception as e:
        print(f"❌ 发送结果邮件失败: {str(e)[:280]}")

    return 'OK', 200

if __name__ == '__main__':
    app.run(port=8080)
