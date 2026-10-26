import copy
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
import pytest
from services.mycard_archive.archetypes import recognize_archetype,classify_archetype,validate_rules,DEFAULT_RULES


def rules():
    return dict(version=1,minimum_copies=8,minimum_unique=3,hybrid_minimum=10,hybrid_ratio=.75,
                ignored_fields=[99],field_names={"1":"甲","2":"乙","3":"子甲","99":"通用"},
                groups=[dict(label="核心甲",fields=[1,3],core_cards=[1],minimum_copies=6,minimum_unique=2)])


def catalog():
    return {1:(1,"A"),2:(1,"B"),3:(3,"C"),4:(2,"D"),5:(2,"E"),6:(2,"F"),
            7:(99,"通用"),8:(0,"无系列"),11:(1,"A")}


def deck(main,extra=(),side=()):return SimpleNamespace(main=main,extra=extra,side=side)


def test_small_engine_order_and_40_60_variants_share_core():
    base=[1]*3+[2]*3+[3]*3+[4]*3
    for cards in (base+[7]*28,list(reversed(base))+[8]*48):
        result=recognize_archetype(deck(cards),rules(),catalog())
        assert result["name"]=="核心甲" and result["cores"]==["核心甲"]


def test_large_independent_cores_preserve_stable_hybrid():
    cards=[1]*3+[2]*3+[3]*4+[4]*3+[5]*3+[6]*4+[7]*20
    a=recognize_archetype(deck(cards),rules(),catalog())
    b=recognize_archetype(deck(list(reversed(cards))),rules(),catalog())
    assert a["name"]==b["name"]=="混合：乙＋核心甲"


def test_overlapping_field_tags_are_not_double_counted_or_fake_hybrids():
    c={1:(1|(2<<16),"A"),2:(1|(2<<16),"B"),3:(1|(2<<16),"C")}
    result=recognize_archetype(deck([1]*4+[2]*3+[3]*3),rules(),c)
    assert len(result["cores"])==1
    assert all(r["copies"]==10 for r in result["evidence"])


def test_merged_related_fields_count_each_card_once():
    c=catalog();c[1]=(1|(3<<16),"A")
    result=recognize_archetype(deck([1]*3+[2]*3),rules(),c)
    assert result["name"]=="核心甲" and result["evidence"][0]["copies"]==6


def test_extra_side_and_generic_cards_do_not_invent_core():
    result=recognize_archetype(deck([7]*20+[8]*20,extra=[1,2,3]*5,side=[4,5,6]*5),rules(),catalog())
    assert result["name"]=="未识别"
    assert recognize_archetype(deck([1]*3+[7]*37),rules(),catalog())["name"]=="未识别"


def test_alternate_artworks_are_one_unique_name_and_support_core_anchor():
    # Distinct artwork IDs alone must not satisfy the distinct-card threshold.
    assert recognize_archetype(deck([1]*3+[11]*3),rules(),catalog())["name"]=="未识别"
    assert recognize_archetype(deck([11]*3+[2]*3),rules(),catalog())["name"]=="核心甲"


def test_explicit_core_cards_work_without_setcode_and_require_anchor():
    r=rules();r["groups"]=[dict(label="特殊体系",fields=[],cards=[1,2],core_cards=[1],require_core=True,minimum_copies=6,minimum_unique=2)]
    c={1:(0,"A"),11:(0,"A"),2:(0,"B")}
    assert recognize_archetype(deck([11]*3+[2]*3),r,c)["name"]=="特殊体系"
    assert recognize_archetype(deck([2]*8),r,c)["name"]=="未识别"


def test_config_and_card_catalog_hot_reload(tmp_path,monkeypatch):
    path=tmp_path/"cards.cdb";rule_path=tmp_path/"archetype-rules.json"
    def install(field):
        temp=tmp_path/"new.cdb"
        with sqlite3.connect(temp) as db:
            db.executescript("CREATE TABLE datas(id INTEGER,setcode INTEGER); CREATE TABLE texts(id INTEGER,name TEXT);")
            db.executemany("INSERT INTO datas VALUES(?,?)",[(1,field),(2,field),(3,field)])
            db.executemany("INSERT INTO texts VALUES(?,?)",[(1,"A"),(2,"B"),(3,"C")])
        temp.replace(path)
    install(1);rule_path.write_text(json.dumps(rules()))
    monkeypatch.setenv("MYCARD_CARD_DB",str(path))
    d=deck([1]*3+[2]*3+[3]*3)
    assert classify_archetype(d,tmp_path/"deck-rules.json")=="核心甲"
    r=rules();r["groups"][0]["label"]="新大类";rule_path.write_text(json.dumps(r))
    assert classify_archetype(d,tmp_path/"deck-rules.json")=="新大类"
    install(2)
    assert classify_archetype(d,tmp_path/"deck-rules.json")=="乙"


def test_bundled_config_valid_and_related_families_merge():
    config=validate_rules(json.loads(DEFAULT_RULES.read_text()))
    c={1:(0x15d,"烙印融合"),2:(0x164,"死狱乡甲"),3:(0x15d|(0x164<<16),"烙印乙")}
    result=recognize_archetype(deck([1]*3+[2]*3+[3]*3),config,c)
    assert result["name"]=="烙印" and result["evidence"][0]["copies"]==9


@pytest.mark.parametrize("change",[
    lambda r:r.update(minimum_copies=0),
    lambda r:r.update(hybrid_ratio=1.2),
    lambda r:r["groups"].append(dict(label="重复字段",fields=[1],core_cards=[])),
    lambda r:r["groups"].append(dict(label="核心甲",fields=[2],core_cards=[])),
])
def test_invalid_rules_fail_explicitly(change):
    r=rules();change(r)
    with pytest.raises(ValueError):validate_rules(r)
