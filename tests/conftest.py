"""Keep shared conversation writes out of live runtime files during tests."""
import pytest


@pytest.fixture(autouse=True)
def isolated_shared_group_conversation(tmp_path,monkeypatch):
    import sys
    from services import mention_chat_client,group_chat_client
    from services.group_learning import GroupLearningStore
    shared=GroupLearningStore(tmp_path/"group-learning.db")
    monkeypatch.setattr(mention_chat_client,"learned_store",shared)
    monkeypatch.setattr(group_chat_client,"store",shared)
    monkeypatch.setattr(group_chat_client.service,"store",shared)
    if "plugins.group_chat" in sys.modules:monkeypatch.setattr(sys.modules["plugins.group_chat"],"store",shared)
