import smtplib
from email.mime.text import MIMEText
import os

def send_email(subject, body):
    """
    发送一封邮件
    :param subject: 邮件标题
    :param body: 邮件正文
    """

    sender_email = os.environ.get('EMAIL_ADDRESS_QQ')
    sender_password = os.environ.get('EMAIL_PASSWORD_QQ')
    receiver_email = os.environ.get('FORWARD_EMAIL')

    if not all([sender_email, sender_password, receiver_email]):
        raise ValueError("❌ 缺少必要的环境变量，请检查 EMAIL_ADDRESS_QQ, EMAIL_PASSWORD_QQ, FORWARD_EMAIL")

    message = MIMEText(body, 'plain', 'utf-8')
    message['From'] = sender_email
    message['To'] = receiver_email
    message['Subject'] = subject

    try:
        server = smtplib.SMTP_SSL('smtp.qq.com', 465)
        server.login(sender_email, sender_password)
        server.sendmail(sender_email, [receiver_email], message.as_string())
        server.quit()
        print("✅ 邮件发送成功")

    except Exception as e:
        print(f"❌ 邮件发送失败: {str(e)}")
        raise
