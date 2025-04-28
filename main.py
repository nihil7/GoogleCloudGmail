from flask import Flask, request, jsonify
import smtplib
from email.mime.text import MIMEText
import os

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

    # 下面是正常发邮件逻辑
    message = MIMEText(body, 'plain', 'utf-8')
    message['From'] = sender_email
    message['To'] = receiver_email
    message['Subject'] = subject

    server = smtplib.SMTP_SSL('smtp.qq.com', 465)
    server.login(sender_email, sender_password)
    server.sendmail(sender_email, [receiver_email], message.as_string())
    server.quit()

    print("✅ 邮件发送成功")

# 接收Pub/Sub推送
@app.route('/', methods=['POST'])
def receive_pubsub():
    envelope = request.get_json()
    if not envelope:
        return 'Bad Request: No JSON', 400

    print(f"✅ 收到Pub/Sub消息：{envelope}")

    # 收到消息后发送一封邮件
    send_email_via_smtp(
        subject="📬 新邮件触发通知",
        body="你收到了新的邮件通知！（由Cloud Run自动发送）"
    )

    return 'OK', 200

# 保留的刷新接口（占位）
@app.route('/refresh', methods=['POST'])
def manual_refresh():
    print("✅ 手动触发了刷新接口（当前没有实际刷新操作）")
    return '手动刷新成功', 200

if __name__ == '__main__':
    app.run(port=8080)
