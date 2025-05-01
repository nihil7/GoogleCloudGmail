import os
import datetime
from gmail_service import get_gmail_service

MAX_RESULTS_PER_PAGE = 100

# 🧭 标签名 => 标签ID 映射表
def get_label_id_map():
    service = get_gmail_service()
    result = service.users().labels().list(userId='me').execute()
    label_map = {label['name']: label['id'] for label in result.get('labels', [])}

    if os.environ.get("PRINT_LABEL_MAP") == "1":
        print("📋 标签名称与ID映射（调试用）:")
        for name, lid in label_map.items():
            print(f"- {name}: {lid}")

    return label_map

# 🔍 获取邮件标题与接收时间
def get_message_info(service, message_id):
    try:
        msg = service.users().messages().get(
            userId='me', id=message_id,
            format='metadata', metadataHeaders=['Subject']
        ).execute()
        headers = msg.get('payload', {}).get('headers', [])
        subject = next((h['value'] for h in headers if h['name'] == 'Subject'), '(无标题)')
        internal_date = int(msg.get('internalDate'))
        return subject, internal_date
    except Exception as e:
        print(f"⚠️ 获取邮件信息失败: {str(e)[:280]}")
        return '(查询失败)', 0

# ⏱️ 毫秒时间戳转北京时间字符串
def format_timestamp(ms):
    dt = datetime.datetime.utcfromtimestamp(ms / 1000) + datetime.timedelta(hours=8)
    return dt.strftime('%Y-%m-%d %H:%M:%S')

# 📨 根据 historyId 拉取变化记录，提取完整邮件信息
def fetch_and_analyze_history(history_id, target_label_name="INBOX"):
    service = get_gmail_service()
    label_map = get_label_id_map()
    target_label_id = label_map.get(target_label_name)

    if not target_label_id:
        print(f"❌ 无法找到标签: {target_label_name}")
        return [], []

    full_changes, matching_message_ids = [], []
    page_token = None

    while True:
        try:
            response = service.users().history().list(
                userId='me',
                startHistoryId=history_id,
                historyTypes=['labelAdded'],
                maxResults=MAX_RESULTS_PER_PAGE,
                pageToken=page_token
            ).execute()

            history_list = response.get('history', [])
            for record in history_list:
                for change in record.get('labelsAdded', []):
                    msg_id = change['message']['id']
                    label_ids = change.get('labelIds', [])
                    subject, timestamp = get_message_info(service, msg_id)
                    full_changes.append({
                        'message_id': msg_id,
                        'added_labels': label_ids,
                        'subject': subject,
                        'time': format_timestamp(timestamp)
                    })
                    if target_label_id in label_ids:
                        matching_message_ids.append(msg_id)

            page_token = response.get('nextPageToken')
            if not page_token:
                break

        except Exception as e:
            print(f"❌ 拉取或分析失败: {str(e)[:280]}")
            break

    print(f"✅ 共拉取变化记录: {len(full_changes)} 条")
    return full_changes, matching_message_ids

# 📝 邮件正文生成（带标题与时间）
def generate_email_content(full_changes, matching_message_ids, label_name="INBOX"):
    lines = [
        f"📬 Gmail 标签变化提醒",
        f"共检测到 {len(full_changes)} 条变化记录。",
        "📋 所有变化详情："
    ]

    for idx, change in enumerate(full_changes, 1):
        lines.append(f"{idx}. ID: {change['message_id']} ➔ 标题:《{change['subject']}》 时间: {change['time']} 标签ID: {', '.join(change['added_labels'])}")

    if matching_message_ids:
        lines.append(f"\n🎯 被打上标签【{label_name}】的邮件：")
        for mid in matching_message_ids:
            lines.append(f"- {mid}")
    else:
        lines.append(f"\n🎯 本次没有检测到打上标签【{label_name}】的邮件。")

    return '\n'.join(lines)
