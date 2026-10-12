"""One semantic Agent client for mentions, translation and explicit Rift aliases."""
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
    if not question.strip():
        await bot.send(event,"请在 @神人 后写下消息，可以聊天、查卡、翻译或问裁定。")
        return
    if len(question)>8000:
        await bot.send(event,"消息过长，请分段提问。")
        return
    try:
        response=await query_ygo_rag_agent(question,session_id=session_key(bot,event),quoted_reply=quoted_reply(bot,event))
    except Exception as exc:
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
        if block.tool!="rift_search_cards" or not block.ok or block.result.get("ambiguous"):continue
        for card in block.result.get("results",[])[:3]:
            card=dict(card)
            card["editions"]=[{"card_key":code} for code in card.get("editions",[])]
            image,language=await card_image(card)
            message=Message()
            if image:message+=MessageSegment.image(image)
            if language=="en":message+=MessageSegment.text("（英文卡图）\n")
            message+=MessageSegment.text(format_riftbound_card(card))
            nodes.append(make_forward_node(int(event.self_id),"神人",message))
    if nodes:
        await send_group_forward_nodes(bot,event,nodes,"合并转发失败，改为普通消息发送。")
    else:await bot.send(event,MessageSegment.text(response.answer or "未能获得可用结果。"))
