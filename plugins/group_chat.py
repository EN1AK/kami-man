"""Capture ordinary text and occasionally reply in explicitly enabled groups."""
import asyncio
from contextlib import suppress

from nonebot import on_message, get_driver, logger
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageEvent, MessageSegment
from nonebot.rule import Rule
from services.group_chat_client import service, store, meme_library
from services.group_chat_store import ALLOWED_GROUPS, DAILY_LIMIT
from services.group_style import update_style
from services.group_learning import update_learning, budget_status
from services.group_memes import MemeLibrary
from services.ygo_rag_messages import extract_rag_question
from services.group_chat_commands import parse_group_control


def is_exempt(user_id):
    return str(user_id) in {str(user) for user in get_driver().config.superusers}


def control_request(bot, event):
    if not isinstance(event, GroupMessageEvent):
        return None
    mentioned, text = extract_rag_question(event.message, str(bot.self_id), plain_text=event.get_plaintext(), to_me=event.to_me)
    if not mentioned:
        return None
    return parse_group_control(text)


async def is_control(bot: Bot, event: MessageEvent):
    return control_request(bot, event) is not None


control = on_message(rule=Rule(is_control), priority=2, block=True)


@control.handle()
async def handle_control(bot: Bot, event: GroupMessageEvent):
    kind, action = control_request(bot, event)
    if event.group_id not in ALLOWED_GROUPS:
        await bot.send(event, "本群未启用群聊学习、采集和随机接话，因此没有本群的学习或风格记录。")
        return
    if kind == "群聊学习":
        state = await asyncio.to_thread(store.learning_status,event.group_id)
        text = (f"已学习 {state['count']} 条场景表达；新增 {state['new_count']} 条消息，下一批需 {state['threshold']} 条、3 位成员。\n"
                f"今天学习尝试 {state['attempts']}/3 次，完成 {state['successes']}/2 批。")
        try:
            memes = await asyncio.to_thread(MemeLibrary(meme_library.root,store.path).status,event.group_id)
            text += f"\n表情库 {memes['images']} 张可用图片、{memes['categories']} 类；今日发图尝试 {memes['attempts']}/{memes['limit']} 次。"
        except Exception:
            text += "\n暂时无法读取表情库状态。"
        try:
            budget = await budget_status()
            text += (f"\n本月群聊模型费用估算 ¥{budget['estimated_cny']:.4f}/¥{budget['monthly_limit_cny']:g}；"
                     f"今日 ¥{budget['daily_estimated_cny']:.4f}/¥{budget['daily_limit_cny']:g}。"
                     f"\n本月调用 {budget['calls']} 次；输入 {budget['input_tokens']}、输出 {budget['output_tokens']} token。")
            if budget['uncertain_calls']:
                text += f"\n含 {budget['uncertain_calls']} 次在途或用量未核实的预留费用。"
            text += "\n费用按高峰未缓存价格保守估算，非平台账单。"
        except Exception:
            text += "\n暂时无法读取费用统计。"
        await bot.send(event,MessageSegment.text(text))
        return
    if kind == "群聊风格":
        profile = await asyncio.to_thread(store.profile, event.group_id)
        if profile["summary"]:
            text = "当前群聊风格：\n" + profile["summary"]
            text += f"\n\n本次参考 {profile['source_count']} 条消息的统计；新增 {profile['new_count']} 条。"
        else:
            text = f"尚未生成风格描述。当前积累 {profile['new_count']} 条，首次需至少 200 条、3 位成员。"
        await bot.send(event, MessageSegment.text(text))
        return
    if action != "状态":
        role = getattr(event.sender, "role", None)
        if role not in {"owner", "admin"} and not is_exempt(event.user_id):
            await bot.send(event, "仅群主、群管理员和机器人管理员可修改群聊采集与随机聊天设置。")
            return
        if kind == "随机聊天" and action == "清空":
            await bot.send(event, "清空样本请发送：@神人 群聊采集 清空。")
            return
        operation = "clear" if action == "清空" else ("chat_" if kind == "随机聊天" else "collect_") + ("on" if action == "开启" else "off")
        await asyncio.to_thread(store.configure, event.group_id, operation)
    state = await asyncio.to_thread(store.status, event.group_id)
    text = (f"群聊采集：{'开启' if state['collect'] else '关闭'}；随机聊天：{'开启' if state['chat'] else '关闭'}。\n"
            f"已保存 {state['count']} 条文字样本（保留 30 天）。\n"
            f"今天调用 {state['attempts']}/{DAILY_LIMIT} 次，已接话 {state['sent']} 次。\n"
            "触发概率 3%，至少间隔 5 分钟。")
    text += "\n表达学习与费用统计：@神人 群聊学习 状态。"
    if kind == "群聊采集" and action == "开启" and not state["chat"]:
        text += "\n恢复接话请发送：@神人 随机聊天 开启。"
    await bot.send(event, MessageSegment.text(text))


async def is_target(event: MessageEvent):
    return isinstance(event, GroupMessageEvent) and event.group_id in ALLOWED_GROUPS


observer = on_message(rule=Rule(is_target), priority=99, block=False)


@observer.handle()
async def handle_observe(bot: Bot, event: GroupMessageEvent):
    await service.observe(bot, event)


async def cleanup_samples():
    while True:
        try:
            for group in ALLOWED_GROUPS:
                await asyncio.to_thread(store.status, group)
                await update_learning(store, group)
                await update_style(store, group)
        except Exception as exc:
            logger.warning("Group sample cleanup failed ({})", type(exc).__name__)
        await asyncio.sleep(3600)


_cleanup_task = None


@get_driver().on_startup
async def start_cleanup():
    global _cleanup_task
    _cleanup_task = asyncio.create_task(cleanup_samples())


@get_driver().on_shutdown
async def stop_cleanup():
    if _cleanup_task is not None:
        _cleanup_task.cancel()
        with suppress(asyncio.CancelledError):
            await _cleanup_task
