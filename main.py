from flask import Flask, request, jsonify
import smtplib
from email.mime.text import MIMEText
import os
import base64
import json

app = Flask(__name__)

# 通用函数：通过SMTP发送邮件
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

@app.route('/', methods=['POST'])
def receive_pubsub():
    envelope = request.get_json()
    if not envelope:
        return 'Bad Request: No JSON', 400

    print(f"✅ 收到Pub/Sub消息（原始）：{envelope}")

    decoded_json = {}
    if 'message' in envelope and 'data' in envelope['message']:
        data_b64 = envelope['message']['data']
        try:
            decoded_bytes = base64.urlsafe_b64decode(data_b64)
            decoded_str = decoded_bytes.decode('utf-8')
            decoded_json = json.loads(decoded_str)
            print(f"✅ 解码后的内容：{decoded_json}")
        except Exception as e:
            print(f"❌ 解码出错: {str(e)}")
    else:
        print("⚠️ Pub/Sub推送消息中缺少'message'或'data'字段")

    # 发一封提醒邮件
    email_subject = "📬 新邮件触发通知"
    email_body = f"收到新的Pub/Sub推送内容：\n\n{json.dumps(decoded_json, ensure_ascii=False, indent=2)}"
    send_email_via_smtp(subject=email_subject, body=email_body)

    return 'OK', 200

@app.route('/refresh', methods=['POST'])
def manual_refresh():
    print("✅ 手动触发了刷新接口（当前没有实际刷新逻辑）")
    return '手动刷新成功', 200

if __name__ == '__main__':
    app.run(port=8080)
