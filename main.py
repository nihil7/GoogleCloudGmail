import os
import smtplib
from flask import Flask, request
from email.mime.text import MIMEText
from email.header import Header

app = Flask(__name__)


@app.route("/", methods=["POST", "GET"])
def home():
    print("✅ Received request at /")

    # 只在 POST 请求时发送邮件
    if request.method == "POST":
        send_email()

    return "✅ Cloud Run is working!", 200


def send_email():
    try:
        smtp_server = 'smtp.qq.com'
        smtp_port = 465
        sender_email = os.environ.get('EMAIL_ADDRESS_QQ')
        sender_password = os.environ.get('EMAIL_PASSWORD_QQ')
        receiver_email = os.environ.get('FORWARD_EMAIL')

        print(f"✅ 准备发邮件：From {sender_email} To {receiver_email}")

        subject = '📬 Cloud Run通知'
        body = '✅ 您的Cloud Run服务收到了一个新请求！'

        # 构建邮件
        message = MIMEText(body, 'plain', 'utf-8')
        message['From'] = Header("Cloud Run Service", 'utf-8')
        message['To'] = Header(receiver_email, 'utf-8')
        message['Subject'] = Header(subject, 'utf-8')

        # 连接并发送邮件
        smtp = smtplib.SMTP_SSL(smtp_server, smtp_port)
        smtp.login(sender_email, sender_password)
        smtp.sendmail(sender_email, [receiver_email], message.as_string())
        smtp.quit()

        print("✅ 邮件发送成功！")
    except Exception as e:
        print(f"❌ 邮件发送失败: {e}")
