from flask import Flask, request
import base64
import json
from gmail_history_handler import fetch_and_analyze_history, generate_email_content
from email_sender import send_email

app = Flask(__name__)

# 配置区
SEND_FIRST_NOTIFICATION = False  # 是否发送第一封【收到推送】邮件（True=发送，False=不发）

@app.route('/', methods=['POST'])
def receive_pubsub():
    # 第1步：收到推送，条件控制是否发第一封提醒邮件
    if SEND_FIRST_NOTIFICATION:
        try:
            send_email(
                subject="📬 收到Gmail推送提醒",
                body="✅ 成功收到Gmail Pub/Sub推送通知。准备解析并处理。"
            )
            print("✅ 已发送【收到推送】邮件")
        except Exception as e:
            print(f"❌ 发送【收到推送】邮件失败: {str(e)}")
    else:
        print("ℹ️ 配置关闭了第一封【收到推送】邮件发送")

    # 第2步：解析推送内容
    envelope = request.get_json()
    if not envelope:
        print("❌ 无有效JSON数据")
        return 'Bad Request: No JSON', 400

    if 'message' not in envelope or 'data' not in envelope['message']:
        print("❌ Pub/Sub格式异常")
        return 'Bad Request: Invalid Pub/Sub message', 400

    try:
        data_b64 = envelope['message']['data']
        decoded_bytes = base64.urlsafe_b64decode(data_b64)
        decoded_str = decoded_bytes.decode('utf-8')
        decoded_json = json.loads(decoded_str)
        print(f"✅ 解码后的PubSub消息: {decoded_json}")
    except Exception as e:
        print(f"❌ 解码失败: {str(e)}")
        return 'Bad Request: Decode Error', 400

    history_id = decoded_json.get('historyId')
    if not history_id:
        print("⚠️ 没有找到historyId，跳过处理")
        return 'OK', 200

    # 第3步：拉取变化并分析
    try:
        full_changes, matching_message_ids = fetch_and_analyze_history(history_id)
    except Exception as e:
        print(f"❌ 拉取Gmail变化失败: {str(e)}")
        return 'Internal Server Error', 500

    # 第4步：检查是否有被打标签"0"
    try:
        if matching_message_ids:
            # 如果有符合条件的变化，发第二封邮件
            detailed_content = generate_email_content(full_changes, matching_message_ids)
            send_email(
                subject="🎯 检测到Gmail打标签0变化",
                body=detailed_content
            )
            print(f"✅ 已发送【打标签0】变化邮件，匹配数量: {len(matching_message_ids)}")
        else:
            print("✅ 没有打标签0的变化，本次处理完毕")

    except Exception as e:
        print(f"❌ 检查标签变化或发送第二封邮件时出错: {str(e)}")

    return 'OK', 200

if __name__ == '__main__':
    app.run(port=8080)
