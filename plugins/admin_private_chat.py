"""Direct private chat for configured bot administrators only."""
from nonebot import on_message
from nonebot.rule import Rule
from nonebot.adapters.onebot.v11 import Bot,MessageEvent,PrivateMessageEvent
from services.agent_usage import is_exempt
from services.ygo_rag_messages import extract_rag_question
from services.group_chat_commands import parse_group_control


async def is_admin_private(bot:Bot,event:MessageEvent):
    return isinstance(event,PrivateMessageEvent) and is_exempt(event.user_id)


admin_private=on_message(rule=Rule(is_admin_private),priority=20,block=True)


@admin_private.handle()
async def handle_admin_private(bot:Bot,event:MessageEvent):
    # Recheck at dispatch as well as matching; never query models for other users.
    if not isinstance(event,PrivateMessageEvent) or not is_exempt(event.user_id):
        return
    _,text=extract_rag_question(event.message,str(bot.self_id),plain_text=event.get_plaintext(),to_me=True)
    if parse_group_control(text):
        await bot.send(event,"私聊不采集群聊风格。请在已启用学习的群内发送该指令查看或管理本群状态。")
        return
    from services.unified_agent import handle_question
    await handle_question(bot,event,text)
