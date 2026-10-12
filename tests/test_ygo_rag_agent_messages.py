from services.ygo_rag_agent_api import AgentToolBlock, YgoRagAgentResponse
from services.ygo_rag_agent_messages import build_rag_agent_message_texts


def test_build_agent_messages_includes_answer_warnings_and_nested_card_blocks():
    response = YgoRagAgentResponse(
        answer="这些卡比较接近。",
        warnings=["LLM rerank fallback"],
        exhausted=False,
        tool_blocks=[
            AgentToolBlock(
                tool="search_cards",
                ok=True,
                summary="查卡完成。",
                result={
                    "structured": {
                        "blocks": [
                            {
                                "type": "card",
                                "text": "1. 我身作盾\n理由：...",
                                "truncated": False,
                            },
                            {
                                "type": "card",
                                "text": "2. 神之宣告\n理由：...",
                                "truncated": True,
                            },
                        ]
                    }
                },
            )
        ],
    )

    texts = build_rag_agent_message_texts("类似我身作盾的卡", response)

    assert texts == [
        "问题：类似我身作盾的卡\n回答：这些卡比较接近。\n警告：\nLLM rerank fallback",
        "1. 我身作盾\n理由：...",
        "2. 神之宣告\n理由：...\n\n（此结果块已截断）",
    ]


def test_build_agent_messages_uses_adjudication_natural_answer():
    response = YgoRagAgentResponse(
        answer="可以发动，见裁定依据。",
        warnings=[],
        exhausted=True,
        tool_blocks=[
            AgentToolBlock(
                tool="adjudicate",
                ok=True,
                summary="裁定完成。",
                result={"natural_answer": "裁定依据：不能代替破坏。"},
            )
        ],
    )

    texts = build_rag_agent_message_texts("这个场景怎么处理？", response)

    assert texts == [
        "问题：这个场景怎么处理？\n回答：可以发动，见裁定依据。\n警告：\nAgent 已达到最大工具轮次，以下结果可能不完整。",
        "裁定依据：不能代替破坏。",
    ]


def test_build_agent_messages_falls_back_to_answer_when_no_tool_details():
    response = YgoRagAgentResponse(
        answer="abcdef",
        warnings=[],
        exhausted=False,
        tool_blocks=[],
    )

    texts = build_rag_agent_message_texts("原问题", response, fallback_chunk_size=3)

    assert texts == ["问题：原问题\n回答：abcdef"]


def test_rift_catalogue_detail_includes_count_stats_and_effect():
    from services.ygo_rag_agent_messages import _extract_tool_fallback_text
    from services.ygo_rag_agent_api import AgentToolBlock
    block=AgentToolBlock(tool="rift_search_cards",ok=True,summary="完成",result={"answer":"共找到 12 种，本页展示 1-10。","search_mode":"semantic","results":[{"card_key":"OGN-001","title":"守护者","color_cn":"红色","type_cn":"单位","might":7,"energy":3,"text_cn":"保护其他单位"}]})
    text=_extract_tool_fallback_text(block)
    assert all(x in text for x in ["12","战力 7","能量 3","红色","保护其他单位","OGN-001"])
