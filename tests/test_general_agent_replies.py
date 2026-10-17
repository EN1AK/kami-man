from services.ygo_rag_agent_api import AgentToolBlock,YgoRagAgentResponse,_chat_ready_response

def test_basic_tools_display_as_chat_with_verified_sources():
    block=AgentToolBlock("web_search",True,"search",{"sources":[{"title":"Official","url":"https://example.org/article"}]})
    original=YgoRagAgentResponse("Answer",[],False,[block])
    result=_chat_ready_response(original)
    assert result.tool_blocks==[]
    assert "Official" in result.answer and "https://example.org/article" in result.answer
    assert original.tool_blocks==[block]

def test_mixed_specialist_tools_keep_structured_card_results():
    blocks=[AgentToolBlock("web_search",True,"search",{}),AgentToolBlock("search_cards",True,"cards",{})]
    response=YgoRagAgentResponse("Answer",[],False,blocks)
    assert _chat_ready_response(response) is response

def test_basic_failure_warnings_not_hidden():
    response=YgoRagAgentResponse("Cannot read",["网页读取失败"],True,[AgentToolBlock("read_webpage",False,"failed",{})])
    result=_chat_ready_response(response)
    assert not result.tool_blocks and "网页读取失败" in result.answer and "工具轮次上限" in result.answer

def test_sources_not_duplicated_and_time_answer_is_plain_chat():
    response=YgoRagAgentResponse("Now",[],False,[AgentToolBlock("current_time",True,"ok",{})])
    assert _chat_ready_response(response).answer=="Now"
    response=YgoRagAgentResponse("See https://example.org/article",[],False,[
        AgentToolBlock("web_search",True,"ok",{"sources":[{"title":"Example","url":"https://example.org/article"}]})])
    assert _chat_ready_response(response).answer.count("https://example.org/article")==1
