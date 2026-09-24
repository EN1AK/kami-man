from services.rift_rag_api import RagSource, RiftRagResponse
from services.rift_rag_messages import (
    build_rift_rag_nodes,
    extract_text_mention_question,
    get_text_mention_aliases,
    is_rift_alias_message,
)


class FakeSegment:
    def __init__(self, type_, text="", **data):
        self.type = type_
        self.data = data
        self._text = text

    def __str__(self):
        return self._text


def make_response(**overrides) -> RiftRagResponse:
    defaults = {
        "answer": "结论 [R-CR-465.2]",
        "warnings": [],
        "sources": [RagSource(rule_id="R-CR-465.2", topic="465.2 Step 2")],
    }
    defaults.update(overrides)
    return RiftRagResponse(**defaults)


def test_get_text_mention_aliases_uses_default_when_env_unset(monkeypatch):
    monkeypatch.delenv("RIFT_RAG_TEXT_MENTION_ALIASES", raising=False)

    assert get_text_mention_aliases() == ["符文规则", "符文裁定"]


def test_get_text_mention_aliases_parses_comma_list_and_strips_at():
    aliases = get_text_mention_aliases("符文规则, @rf规则 ,＠规则问答，,")

    assert aliases == ["符文规则", "rf规则", "规则问答"]


def test_extract_text_mention_question_accepts_all_supported_aliases():
    assert extract_text_mention_question("符文规则 麦田圈在对方回合能发动吗") == (
        True,
        "麦田圈在对方回合能发动吗",
    )
    assert extract_text_mention_question("符文裁定 什么是迅捷") == (True, "什么是迅捷")


def test_extract_text_mention_question_prefers_longest_alias():
    matched, question = extract_text_mention_question("符文裁定 什么是迅捷")

    assert matched is True
    assert question == "什么是迅捷"


def test_extract_text_mention_question_accepts_at_prefixed_alias():
    matched, question = extract_text_mention_question("＠符文规则 伤害怎么结算")

    assert matched is True
    assert question == "伤害怎么结算"


def test_extract_text_mention_question_handles_empty_remainder():
    matched, question = extract_text_mention_question("符文裁定")

    assert matched is True
    assert question == ""


def test_extract_text_mention_question_ignores_non_matching_text():
    matched, question = extract_text_mention_question("今天符文战场怎么组卡")

    assert matched is False
    assert question == "今天符文战场怎么组卡"


def test_is_rift_alias_message_accepts_alias_message():
    segments = [FakeSegment("text", "符文规则 伤害怎么结算")]

    assert is_rift_alias_message("符文规则 伤害怎么结算", segments, "12345") is True


def test_is_rift_alias_message_rejects_ygo_bot_mention():
    segments = [
        FakeSegment("at", qq="12345"),
        FakeSegment("text", " 符文规则 伤害怎么结算"),
    ]

    assert is_rift_alias_message("符文规则 伤害怎么结算", segments, "12345") is False


def test_is_rift_alias_message_rejects_ygo_text_alias():
    segments = [FakeSegment("text", "@神人 有没有效法我身作盾的卡")]

    assert is_rift_alias_message("@神人 有没有效法我身作盾的卡", segments, "12345") is False


def test_is_rift_alias_message_ignores_plain_text():
    segments = [FakeSegment("text", "随便聊聊")]

    assert is_rift_alias_message("随便聊聊", segments, "12345") is False


def test_build_rift_rag_nodes_builds_question_rules_and_answer_in_order():
    response = make_response(
        answer="结论 [R-CR-465.2]",
        sources=[
            RagSource(rule_id="R-CR-465.2", topic="465.2 Step 2"),
            RagSource(rule_id="R-CR-814.1.d.1", topic=""),
        ],
    )

    nodes = build_rift_rag_nodes(
        "伤害怎么结算",
        response,
        sender_name="tester",
        sender_user_id=111,
        base_url="http://127.0.0.1:7862",
    )

    assert [node["type"] for node in nodes] == ["node"] * 4
    assert nodes[0]["data"]["content"] == "问题：伤害怎么结算"
    assert nodes[1]["data"]["content"] == "规则 R-CR-465.2\n主题 465.2 Step 2"
    assert nodes[2]["data"]["content"] == "规则 R-CR-814.1.d.1"
    assert nodes[3]["data"]["content"] == (
        "结论 [R-CR-465.2]\n\n回答生成自 http://127.0.0.1:7862"
    )
    for node in nodes:
        assert node["data"]["name"] == "tester"
        assert node["data"]["uin"] == "111"


def test_build_rift_rag_nodes_question_includes_coverage_lines():
    response = make_response(
        resolved_cards=[
            {
                "card_id": "OGN-242",
                "mention": "海兽钓钩",
                "name_cn": "海兽钓钩",
                "name_en": "Baited Hook",
            }
        ],
        unresolved_mentions=["某卡名"],
        ambiguous_mentions=[
            {"mention": "蔚", "candidates": [{"card_id": "OGN-066a"}]},
            {
                "mention": "多候选",
                "candidates": [
                    {"card_id": "A-001"},
                    {"card_id": "A-002"},
                    {"card_id": "A-003"},
                    {"card_id": "A-004"},
                ],
            },
        ],
        exhausted=True,
    )

    nodes = build_rift_rag_nodes(
        "海兽钓钩的放逐怎么处理",
        response,
        base_url="http://127.0.0.1:7862",
    )

    assert nodes[0]["data"]["content"] == (
        "问题：海兽钓钩的放逐怎么处理\n"
        "识别卡牌：海兽钓钩（OGN-242）\n"
        "识别失败：某卡名\n"
        "卡名歧义：蔚（OGN-066a）\n"
        "卡名歧义：多候选（A-001、A-002、A-003 等）\n"
        "已达检索步数上限，答案基于部分证据"
    )


def test_build_rift_rag_nodes_omits_coverage_lines_when_fields_empty():
    response = make_response()

    nodes = build_rift_rag_nodes("问题", response, base_url="http://127.0.0.1:7862")

    assert nodes[0]["data"]["content"] == "问题：问题"


def test_build_rift_rag_nodes_appends_warnings_to_question_node():
    response = make_response(warnings=["向量召回失败，已退回关键词召回"])

    nodes = build_rift_rag_nodes("问题", response, base_url="http://127.0.0.1:7862")

    assert nodes[0]["data"]["content"] == (
        "问题：问题\n警告：\n向量召回失败，已退回关键词召回"
    )


def test_build_rift_rag_nodes_omits_topic_line_for_unusable_topic():
    response = make_response(
        sources=[
            RagSource(rule_id="R-CR-1", topic=""),
            RagSource(rule_id="R-CR-2", topic="   "),
        ]
    )

    nodes = build_rift_rag_nodes("问题", response, base_url="http://127.0.0.1:7862")

    assert nodes[1]["data"]["content"] == "规则 R-CR-1"
    assert nodes[2]["data"]["content"] == "规则 R-CR-2"


def test_build_rift_rag_nodes_keeps_empty_question_and_drops_empty_answer():
    response = make_response(answer="")

    nodes = build_rift_rag_nodes("", response, base_url="http://127.0.0.1:7862")

    assert [node["data"]["content"] for node in nodes] == [
        "问题：",
        "规则 R-CR-465.2\n主题 465.2 Step 2",
    ]


def test_build_rift_rag_nodes_tolerates_partial_sender_identity():
    name_only = build_rift_rag_nodes(
        "问题",
        make_response(),
        sender_name="tester",
        base_url="http://127.0.0.1:7862",
    )
    uin_only = build_rift_rag_nodes(
        "问题",
        make_response(),
        sender_user_id=111,
        base_url="http://127.0.0.1:7862",
    )
    no_identity = build_rift_rag_nodes(
        "问题", make_response(), base_url="http://127.0.0.1:7862"
    )

    assert name_only[0]["data"] == {"content": "问题：问题", "name": "tester"}
    assert uin_only[0]["data"] == {"content": "问题：问题", "uin": "111"}
    assert no_identity[0]["data"] == {"content": "问题：问题"}


def test_build_rift_rag_nodes_footer_uses_configured_base_url(monkeypatch):
    monkeypatch.delenv("RIFT_RAG_BASE_URL", raising=False)
    monkeypatch.delenv("RIFT_QA_BASE_URL", raising=False)
    monkeypatch.setenv("RIFT_RAG_BASE_URL", "http://10.0.0.2:7862")

    nodes = build_rift_rag_nodes("问题", make_response())

    assert nodes[-1]["data"]["content"].endswith("回答生成自 http://10.0.0.2:7862")

    monkeypatch.delenv("RIFT_RAG_BASE_URL")
    nodes = build_rift_rag_nodes("问题", make_response())

    assert nodes[-1]["data"]["content"].endswith(
        "回答生成自 http://127.0.0.1:7862"
    )
