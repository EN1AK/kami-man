from services.mycard_archive import semantic_names as semantic
from services.mycard_archive.replay import ObservedDeck


def test_core_requires_multiple_distinct_main_cards(monkeypatch):
    monkeypatch.setattr(semantic,"catalog",lambda *_:{1:"A",2:"B",3:"C",4:"A"})
    assert semantic.jounouchi_core(ObservedDeck("P",(1,)*3,())) is None
    assert semantic.jounouchi_core(ObservedDeck("P",(1,)*3+(2,)*2,())) is None
    assert semantic.jounouchi_core(ObservedDeck("P",(1,)*3+(4,)*3+(2,)*3,())) is None
    assert semantic.jounouchi_core(ObservedDeck("P",(),(1,2,3,1,2,3))) is None
    result=semantic.jounouchi_core(ObservedDeck("P",(1,1,2,2,3,3),()))
    assert result["label"]=="城之内" and result["unique"]==3 and result["copies"]==6


def test_deck_name_replaces_warrior_and_keeps_other_engine(monkeypatch,tmp_path):
    from services.mycard_archive import naming
    monkeypatch.setattr(naming,"recognize_fields",lambda *_:{"name":"战士烙印","counts":{"战士":9,"烙印":3}})
    monkeypatch.setattr(semantic,"jounouchi_core",lambda *_:dict(label="城之内",copies=10))
    assert naming.deck_name(ObservedDeck("P",(1,)*40,()),tmp_path/"missing.json")=="烙印城之内"
    assert naming.deck_name(ObservedDeck("P",(1,)*60,()),tmp_path/"missing.json")=="60烙印城之内"
