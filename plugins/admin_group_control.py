"""Private, deterministic group controls for configured bot administrators."""
import asyncio

from nonebot import on_message
from nonebot.permission import SUPERUSER
from nonebot.rule import Rule
from nonebot.adapters.onebot.v11 import Bot, MessageEvent, PrivateMessageEvent, MessageSegment

from services.agent_usage import is_exempt
from services.admin_group_control import is_admin_group_command, execute_admin_group_command
from services.group_chat_client import store


async def is_private_control(event: MessageEvent):
    return isinstance(event, PrivateMessageEvent) and is_admin_group_command(event.get_plaintext())


admin_group_control = on_message(
    rule=Rule(is_private_control), permission=SUPERUSER, priority=1, block=True,
)


@admin_group_control.handle()
async def handle_admin_group_control(bot: Bot, event: MessageEvent):
    # Guard dispatch too: a group administrator is not a bot administrator.
    if not isinstance(event, PrivateMessageEvent) or not is_exempt(event.user_id):
        return
    text = event.get_plaintext()
    if not is_admin_group_command(text):
        return
    reply = await asyncio.to_thread(execute_admin_group_command, store, text)
    await bot.send(event, MessageSegment.text(reply))
