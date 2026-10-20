"""Reserved group-learning control commands, recognized before persona chat."""

def parse_group_control(text):
    parts=text.split()
    if parts in (["群聊风格"],["群聊风格","查看"],["群聊风格","状态"]):
        return ("群聊风格","状态")
    if parts in (["群聊学习"],["群聊学习","状态"]):
        return ("群聊学习","状态")
    if len(parts)==2 and parts[0] in {"随机聊天","群聊采集"} and parts[1] in {"开启","关闭","状态","清空"}:
        return tuple(parts)
    return None
