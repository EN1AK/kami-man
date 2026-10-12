"""Independent reader of the official YGOPro replay/deck layout.

Protocol reference: mycard/ygopro gframe/replay.h and replay.cpp.
No Side deck is stored in a replay; only observed substitutions can be recovered.
"""
from collections import Counter
from dataclasses import dataclass
import lzma
import struct

MAX_PAYLOAD = 524288

@dataclass(frozen=True)
class ObservedDeck:
    player: str
    main: tuple[int,...]
    extra: tuple[int,...]
    side: tuple[int,...] = ()

    def ydk(self):
        lines=["# Kami Man - observed deck; Side incomplete", "#main"]
        lines.extend(str(card) for card in sorted(self.main))
        lines.append("#extra");lines.extend(str(card) for card in sorted(self.extra))
        lines.append("!side");lines.extend(str(card) for card in sorted(self.side))
        lines.append("# Unseen Side cards are unknown; this is not a verified full Side deck")
        return "\n".join(lines)+"\n"

@dataclass(frozen=True)
class ReplayData:
    start_time: int
    decks: tuple[ObservedDeck,...]


def parse_replay(raw):
    if not isinstance(raw,bytes) or not 32<=len(raw)<=MAX_PAYLOAD+80:
        raise ValueError("录像大小不受支持")
    signature,version,flags,seed,declared,start=struct.unpack_from("<6I",raw)
    if signature not in {0x31707279,0x32707279}:raise ValueError("不是 YRP1/YRP2 录像")
    if version<0x12D0 or flags&~31 or flags&8:raise ValueError("不支持的录像版本或单人模式")
    if version>=0x1353 and not flags&16:raise ValueError("现代录像缺少统一格式标志")
    header_length=80 if signature==0x32707279 else 32
    if len(raw)<header_length:raise ValueError("录像头不完整")
    if header_length==80 and struct.unpack_from("<I",raw,64)[0]!=1:
        raise ValueError("不支持的扩展录像头")
    payload=raw[header_length:]
    if flags&1:
        if not 0<declared<=MAX_PAYLOAD:raise ValueError("录像解压大小异常")
        framed=raw[24:29]+struct.pack("<Q",declared)+payload
        try:
            decoder=lzma.LZMADecompressor(format=lzma.FORMAT_ALONE,memlimit=64*1024*1024)
            payload=decoder.decompress(framed,max_length=MAX_PAYLOAD+1)
        except lzma.LZMAError:raise ValueError("录像压缩数据无效") from None
        if len(payload)!=declared or not decoder.eof:raise ValueError("录像解压不完整或超限")
    if len(payload)>MAX_PAYLOAD:raise ValueError("录像数据超限")
    cursor=0
    def consume(length):
        nonlocal cursor
        if cursor+length>len(payload):raise ValueError("录像中的卡组数据不完整")
        segment=payload[cursor:cursor+length];cursor+=length
        return segment
    def section():
        count=struct.unpack("<I",consume(4))[0]
        if count>100:raise ValueError("录像卡组数量异常")
        cards=struct.unpack("<"+"I"*count,consume(count*4))
        if any(card==0 for card in cards):raise ValueError("录像包含无效卡号")
        return cards
    seats=4 if flags&2 else 2
    try:names=[consume(40).decode("utf-16-le").split("\x00",1)[0] for _ in range(seats)]
    except UnicodeDecodeError:raise ValueError("录像玩家名编码无效") from None
    if any(not name for name in names) or len(set(names))!=seats:raise ValueError("录像玩家名无效或重复")
    consume(16)
    # Official Replay::GetDeckPlayer swaps deck indices 2/3 in Tag mode.
    player_order=[0,1,3,2] if seats==4 else [0,1]
    decks=tuple(ObservedDeck(names[player_order[index]],section(),section()) for index in range(seats))
    return ReplayData(start,decks)


def consolidate(rounds):
    by_player={}
    for replay in sorted(rounds,key=lambda row:(row.get("start_time",0),row.get("ordinal",0))):
        for data in replay.get("decks",[]):by_player.setdefault(data["player"],[]).append(data)
    merged=[]
    for player,entries in by_player.items():
        first=entries[0];baseline=Counter(first["main"]+first["extra"]);observed_side=Counter()
        for entry in entries[1:]:
            observed_side |= Counter(entry["main"]+entry["extra"])-baseline
        merged.append(ObservedDeck(player,tuple(sorted(first["main"])),tuple(sorted(first["extra"])),tuple(sorted(observed_side.elements()))))
    return merged
