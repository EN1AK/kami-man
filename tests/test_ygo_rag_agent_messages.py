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
