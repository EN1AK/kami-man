"""One semantic Agent client for mentions, translation and explicit Rift aliases."""
import asyncio
import sqlite3
import random
from pathlib import Path
from nonebot import logger
from services.agent_usage import DAILY_LIMIT, usage_store, is_exempt
from nonebot.adapters.onebot.v11 import Message,MessageSegment,PrivateMessageEvent
from services.ygo_rag_agent_api import query_ygo_rag_agent,map_agent_error
from services.ygo_rag_agent_messages import build_rag_agent_message_texts
from services.onebot_forward import make_forward_node,send_group_forward_nodes
from services.ygo_rag_messages import chunk_text
from services.card_translation import CardImageError, card_images, translate_card_image
from services.mention_state import MentionState
from services.persona_reply_segments import split_persona_reply
from services.mention_chat_client import resolve_route,request_casual,clear_sessions,style_context,mention_memes,private_memes

route_state = MentionState(Path(__file__).resolve().parents[1]/"data/mention_routes.db")
CLEAR_COMMANDS = {"清空对话","重置对话","忘记上下文"}

def session_key(bot,event):
    group=getattr(event,"group_id",None)
    if group is None:
        return f"qq:{bot.self_id}:private:user:{event.user_id}"
    return f"qq:{bot.self_id}:group:{group}:user:{event.user_id}"
def quoted_reply(bot,event):
    reply=getattr(event,"reply",None)
    sender=getattr(reply,"sender",None)
    if reply and str(getattr(sender,"user_id",""))==str(bot.self_id):
        return reply.message.extract_plain_text()[:4000]
    return ""
async def handle_question(bot,event,question):
    if isinstance(event,PrivateMessageEvent) and not is_exempt(event.user_id):
        return
    async with route_state.locked(session_key(bot,event)):
        await _handle_question(bot,event,question)


async def _record_text(bot,event,text,route):
    await bot.send(event,MessageSegment.text(text))
    await asyncio.to_thread(route_state.record,session_key(bot,event),route,text)


async def _casual_reply(bot,event,key,question):
    group=getattr(event,"group_id",None)
    profile,expressions = await asyncio.to_thread(style_context,group,question) if group is not None else ("",[])
    library=mention_memes if group is not None else private_memes
    target=group if group is not None else event.user_id
    try:
        categories = await asyncio.to_thread(library.categories,target)
    except Exception:
        categories = []
    reply = await request_casual(group,key,question,profile,expressions,categories)
    if reply is None:
        raise ValueError("Unexpected persona escalation")
    image = None
    if reply.meme_category:
        try:
            image = await asyncio.to_thread(library.reserve,target,reply.meme_category)
        except Exception:
            pass
    text = str(reply) or ("" if image else "嗯。")
    parts = split_persona_reply(text) or [""]
    # Only serialize persona delivery; model generation and specialists stay independent.
    async with route_state.locked(f"persona-delivery:{bot.self_id}:group:{group}" if group is not None else f"persona-delivery:{key}"):
        for index,part in enumerate(parts):
            if index:
                await asyncio.sleep(random.uniform(.8,1.6))
            message = Message(MessageSegment.text(part)) if part else Message()
            if image and index==len(parts)-1:
                message += MessageSegment.image(image.image)
            await bot.send(event,message)
            await asyncio.to_thread(route_state.record,key,"casual",part)
    return True


async def _handle_question(bot,event,question):
    question = question.strip()
    images = card_images(event)
    if len(images) > 1:
        await bot.send(event,"请每次发送一张卡图，我会返回中文卡名和效果。")
        return
    exempt = is_exempt(event.user_id)
    if question in {"用量", "剩余次数", "用量统计"}:
        try:
            if question == "用量统计":
                if not exempt:
                    await bot.send(event,"用量统计仅限管理员使用；你可以发送 @神人 用量 查看自己的额度。")
                    return
                day, totals, rows = await asyncio.to_thread(usage_store.summary)
                text = f"{day} Agent 用量（北京时间）\n使用人数：{totals[0]}；已用：{totals[1]} 次；失败退回：{totals[2]} 次"
                if rows:
                    text += "\n用量前 20：\n" + "\n".join(f"QQ {user}：{used} 次，失败 {failed} 次" for user,used,failed in rows)
            else:
                day, used, failed = await asyncio.to_thread(usage_store.personal,event.user_id)
                text = f"{day} 已用 {used} 次；" + ("管理员不限次数。" if exempt else f"每日上限 {DAILY_LIMIT} 次，剩余 {max(0,DAILY_LIMIT-used)} 次。")
                text += "\n北京时间每天 00:00 换日，跨群共用额度；请求失败不扣次数。"
            await bot.send(event,text)
        except (sqlite3.Error, OSError):
            logger.exception("Agent usage lookup failed")
            await bot.send(event,"用量记录暂时不可用，请稍后再试。")
        return
    if not question.strip() and not images:
        await bot.send(event,"请在 @神人 后写下消息，可以聊天、查卡、翻译或问裁定。")
        return
    if len(question)>8000 and not images:
        await bot.send(event,"消息过长，请分段提问。")
        return
    if question in CLEAR_COMMANDS and not images:
        try:
            await clear_sessions(session_key(bot,event))
            await asyncio.to_thread(route_state.clear,session_key(bot,event))
            await bot.send(event,"已清空你的闲聊和专业问答上下文。")
        except Exception as exc:
            await bot.send(event,map_agent_error(exc))
        return
    ticket = None
    try:
        if images or question not in CLEAR_COMMANDS:
            ticket = await asyncio.to_thread(usage_store.reserve,event.user_id,exempt=exempt)
            if ticket is None:
                await bot.send(event,f"今天的 @神人 额度已用完（{DAILY_LIMIT}/{DAILY_LIMIT} 次）。北京时间明天 00:00 恢复；发送 @神人 用量 可查看记录。")
                return
    except (sqlite3.Error, OSError):
        logger.exception("Agent quota reservation failed")
        await bot.send(event,"用量记录暂时不可用，请稍后再试。")
        return
    try:
        if images:
            translation = await translate_card_image(bot, images[0])
        else:
            key = session_key(bot,event)
            quote = quoted_reply(bot,event)
            previous,quoted_kind = await asyncio.to_thread(route_state.metadata,key,quote)
            route = await resolve_route(question,previous,quoted_kind)
            if route=="casual" and await _casual_reply(bot,event,key,question):
                return
            # Original request and verified professional quote only; no persona fields/history.
            response=await query_ygo_rag_agent(question,session_id=key+":professional",quoted_reply=quote if quoted_kind=="professional" else "")
    except Exception as exc:
        if ticket is not None:
            try:
                await asyncio.to_thread(usage_store.refund,ticket)
            except (sqlite3.Error, OSError):
                logger.exception("Agent quota refund failed")
        await bot.send(event,str(exc) if isinstance(exc,CardImageError) else map_agent_error(exc))
        return
    if images:
        for index, text in enumerate(chunk_text(translation.translation)):
            message = Message()
            if index == 0:
                message += MessageSegment.image(translation.original_image)
            message += MessageSegment.text(text)
            await bot.send(event, message)
            await asyncio.to_thread(route_state.record,session_key(bot,event),"professional",text)
        return
    if not response.tool_blocks:
        for text in chunk_text(response.answer):
            await _record_text(bot,event,text,"professional")
        return
    texts=build_rag_agent_message_texts(question,response)
    nodes=[make_forward_node(int(event.self_id),"神人",Message(MessageSegment.text(text))) for text in texts]
    from services.riftbound_api import card_image,format_riftbound_card
    for block in response.tool_blocks:
        if block.tool!="rift_search_cards" or not block.ok:continue
        for card in block.result.get("results",[]):
            card=dict(card)
            card["editions"]=[{"card_key":code} for code in card.get("editions",[])]
            image,language=await card_image(card)
            message=Message()
            if block.result.get("ambiguous"):message+=MessageSegment.text("候选卡片（请确认卡号）\n")
            if image:message+=MessageSegment.image(image)
            if language=="en":message+=MessageSegment.text("（英文卡图）\n")
            message+=MessageSegment.text(format_riftbound_card(card))
            nodes.append(make_forward_node(int(event.self_id),"神人",message))
    if nodes:
        if isinstance(event,PrivateMessageEvent):
            for node in nodes:
                content=node["data"]["content"]
                await bot.send(event,content)
                await asyncio.to_thread(route_state.record,session_key(bot,event),"professional",content.extract_plain_text())
            return
        await send_group_forward_nodes(bot,event,nodes,"合并转发失败，改为普通消息发送。")
        for node in nodes:
            content=node["data"]["content"]
            await asyncio.to_thread(route_state.record,session_key(bot,event),"professional",content.extract_plain_text())
    else:await _record_text(bot,event,response.answer or "未能获得可用结果。","professional")
