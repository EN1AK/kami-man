"""Bounded sentence-aware delivery for explicit persona mentions only."""
import math
import re

MAX_REPLY_CHARS=2000
MAX_SEGMENTS=4
BOUNDARY=re.compile(r'[。！？!?；;]+[”’"）)】]*\s*|\n+|(?<!\d)\.(?=\s|$)\s*')


def split_persona_reply(text):
    text=text.strip()
    if len(text)>MAX_REPLY_CHARS:
        raise ValueError("Persona reply exceeds delivery limit")
    if not text:return []
    # Preserve fenced code rather than breaking its structure across messages.
    if '```' in text:return [text]
    # Explicit line/paragraph breaks are delivery boundaries even for short text.
    cuts=[m.end() for m in re.finditer(r"\r?\n[ \t]*(?:\r?\n[ \t]*)*",text)
          if text[:m.start()].strip() and text[m.end():].strip()]
    if cuts:
        if len(cuts)>=MAX_SEGMENTS:
            cuts=[cuts[((len(cuts)+1)*i//MAX_SEGMENTS)-1] for i in range(1,MAX_SEGMENTS)]
        points=[0,*cuts,len(text)]
        return [text[a:b] for a,b in zip(points,points[1:])]
    if len(text)<=240:return [text]
    target=max(240,math.ceil(len(text)/MAX_SEGMENTS))
    parts=[];offset=0
    while len(text)-offset>target and len(parts)<MAX_SEGMENTS-1:
        minimum=offset+80;ceiling=min(len(text)-80,offset+target+80)
        cuts=[m.end() for m in BOUNDARY.finditer(text,offset,ceiling) if minimum<=m.end()<=ceiling]
        cut=min(cuts,key=lambda p:abs(p-offset-target)) if cuts else offset+target
        parts.append(text[offset:cut]);offset=cut
    parts.append(text[offset:])
    return parts
