from gmail_service import get_gmail_service

def fetch_and_analyze_history(history_id, target_label_id="0"):
    """
    拉取Gmail变化记录，并筛选打了特定标签（默认是'0'）的邮件
    返回：(全部变化记录, 符合条件的messageId列表)
    """
    service = get_gmail_service()

    try:
        response = service.users().history().list(
            userId='me',
            startHistoryId=history_id,
            historyTypes=['labelAdded'],
            maxResults=100
        ).execute()

        history_records = response.get('history', [])
        print(f"✅ 拉取到 {len(history_records)} 条变化记录")

        full_changes = []
        matching_message_ids = []

        for record in history_records:
            if 'labelsAdded' in record:
                for change in record['labelsAdded']:
                    message_id = change['message']['id']
                    added_labels = change.get('labelIds', [])

                    full_changes.append({
                        'message_id': message_id,
                        'added_labels': added_labels
                    })

                    if target_label_id in added_labels:
                        matching_message_ids.append(message_id)

        return full_changes, matching_message_ids

    except Exception as e:
        print(f"❌ 拉取或解析变化记录失败: {str(e)}")
        return [], []

def generate_email_content(full_changes, matching_message_ids):
    """
    根据变化记录生成邮件正文
    """

    lines = []
    lines.append(f"📬 Gmail标签变化提醒\n")
    lines.append(f"本次检测到 {len(full_changes)} 条变化记录。\n")

    lines.append("📋 所有变化详情：")
    for idx, change in enumerate(full_changes, 1):
        lines.append(f"{idx}. messageId: {change['message_id']} ➔ 新加标签: {', '.join(change['added_labels'])}")

    if matching_message_ids:
        lines.append("\n🎯 被打上标签'0'的邮件列表：")
        for mid in matching_message_ids:
            lines.append(f"- {mid}")
    else:
        lines.append("\n🎯 本次没有检测到打标签'0'的邮件。")

    return '\n'.join(lines)
