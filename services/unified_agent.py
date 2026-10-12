"""One semantic Agent client for mentions, translation and explicit Rift aliases."""
import asyncio
import sqlite3
from nonebot import logger
from services.agent_usage import DAILY_LIMIT, usage_store, is_exempt
from nonebot.adapters.onebot.v11 import Message,MessageSegment
from services.ygo_rag_agent_api import query_ygo_rag_agent,map_agent_error
from services.ygo_rag_agent_messages import build_rag_agent_message_texts
from services.onebot_forward import make_forward_node,send_group_forward_nodes
from services.ygo_rag_messages import chunk_text

def session_key(bot,event):
    return f"qq:{bot.self_id}:group:{event.group_id}:user:{event.user_id}"
def quoted_reply(bot,event):
    reply=getattr(event,"reply",None)
    sender=getattr(reply,"sender",None)
    if reply and str(getattr(sender,"user_id",""))==str(bot.self_id):
        return reply.message.extract_plain_text()[:4000]
    return ""
async def handle_question(bot,event,question):
    question = question.strip()
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
    if not question.strip():
        await bot.send(event,"请在 @神人 后写下消息，可以聊天、查卡、翻译或问裁定。")
        return
    if len(question)>8000:
        await bot.send(event,"消息过长，请分段提问。")
        return
    ticket = None
    try:
        if question != "清空对话":
            ticket = await asyncio.to_thread(usage_store.reserve,event.user_id,exempt=exempt)
            if ticket is None:
                await bot.send(event,f"今天的 @神人 额度已用完（{DAILY_LIMIT}/{DAILY_LIMIT} 次）。北京时间明天 00:00 恢复；发送 @神人 用量 可查看记录。")
                return
    except (sqlite3.Error, OSError):
        logger.exception("Agent quota reservation failed")
        await bot.send(event,"用量记录暂时不可用，请稍后再试。")
        return
    try:
        response=await query_ygo_rag_agent(question,session_id=session_key(bot,event),quoted_reply=quoted_reply(bot,event))
    except Exception as exc:
        if ticket is not None:
            try:
                await asyncio.to_thread(usage_store.refund,ticket)
            except (sqlite3.Error, OSError):
                logger.exception("Agent quota refund failed")
        await bot.send(event,map_agent_error(exc))
        return
    if not response.tool_blocks:
        for text in chunk_text(response.answer):
            await bot.send(event,MessageSegment.text(text))
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
        await send_group_forward_nodes(bot,event,nodes,"合并转发失败，改为普通消息发送。")
    else:await bot.send(event,MessageSegment.text(response.answer or "未能获得可用结果。"))
