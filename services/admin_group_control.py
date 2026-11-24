"""Explicit private administrator controls for enabled groups."""
from services.group_chat_store import ALLOWED_GROUPS

HELP = (
    "群管理指令（机器人管理员私聊）：\n"
    "群管理 列表\n"
    "群管理 <群号> 状态\n"
    "群管理 <群号> 随机聊天 开启/关闭\n"
    "群管理 <群号> 群聊采集 开启/关闭\n"
    "群管理 <群号> 群聊学习\n"
    "群管理 <群号> 群聊风格\n"
    "关闭采集会同时停止学习、清除近期对话并关闭随机聊天；已有样本和风格保留。\n"
    "重新开启采集后，随机聊天需单独开启。只管理已开放的群。"
)


def is_admin_group_command(text):
    parts = text.strip().removeprefix('/').split()
    return bool(parts and parts[0] == '群管理')


def status_text(store, group):
    state = store.status(group)
    return (
        f"群 {group}\n"
        f"群聊采集：{'开启' if state['collect'] else '关闭'}；"
        f"随机聊天：{'开启' if state['chat'] else '关闭'}。\n"
        f"文字样本：{state['count']} 条；今日接话 {state['sent']} 次。"
    )


def execute_admin_group_command(store, text):
    """Called only after the plugin has checked private SUPERUSER permission."""
    parts = text.strip().removeprefix('/').split()
    if not parts or parts[0] != '群管理':
        raise ValueError('Not an administrator group command')
    if parts in (['群管理'], ['群管理', '帮助']):
        return HELP
    if parts == ['群管理', '列表']:
        return '\n\n'.join(status_text(store, group) for group in sorted(ALLOWED_GROUPS))
    if len(parts) not in {3, 4} or not parts[1].isascii() or not parts[1].isdigit():
        return HELP
    group = int(parts[1])
    if group not in ALLOWED_GROUPS:
        return f"群 {group} 尚未开放群聊学习功能，未修改任何设置。"
    feature = parts[2]
    if len(parts) == 3:
        if feature == '状态':
            return status_text(store, group)
        if feature == '群聊风格':
            profile = store.profile(group)
            if not profile.get('enabled', True):
                return f'群 {group} 的风格总结已关闭，不再生成或用于回复。'
            return f"群 {group} 的风格：\n{profile['summary']}" if profile['summary'] else (
                f"群 {group} 尚未生成风格，当前新增 {profile['new_count']} 条；首次需 200 条、3 位成员。")
        if feature == '群聊学习':
            state = store.learning_status(group)
            return (f"群 {group} 已学习 {state['count']} 条表达；新增 {state['new_count']} 条，"
                    f"下一批需 {state['threshold']} 条、3 位成员。\n"
                    f"今日尝试 {state['attempts']}/3 次，完成 {state['successes']}/2 批。")
        return HELP
    action = parts[3]
    if feature not in {'随机聊天', '群聊采集'} or action not in {'开启', '关闭'}:
        return HELP
    operation = ('chat_' if feature == '随机聊天' else 'collect_') + ('on' if action == '开启' else 'off')
    state = store.configure(group, operation)
    result = status_text(store, group)
    if operation == 'chat_on' and not state['collect']:
        result += '\n采集已关闭，无法开启随机聊天；请先开启本群采集。'
    elif operation == 'collect_on' and not state['chat']:
        result += '\n采集与学习已开启，随机聊天保持关闭。'
    return result
