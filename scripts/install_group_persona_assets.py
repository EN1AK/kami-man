"""Install pinned public persona/media assets; no third-party code is executed."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
import os
from pathlib import Path,PurePosixPath
import tempfile
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

PROMPT_REPO = "shirachino/astrbot-persona-prompts"
PROMPT_REF = "869d6793b93a756a410f00da44852f8b774e48f1"
PROMPT_PATH = "deepseek/大肥鱼群友提示词 Beta.docx"
PACK_REPO = "shirachino/astrbot-deepseek-meme-pack"
PACK_REF = "7b9d61b09ce068cac621ff2c520ecab11d35d967"


def fetch(url, maximum=16*1024*1024):
    for attempt in range(3):
        try:
            request = urllib.request.Request(url,headers={"User-Agent":"kami-man-persona-assets"})
            with urllib.request.urlopen(request,timeout=30) as response:
                data = response.read(maximum+1)
            if len(data)>maximum:
                raise ValueError("Asset exceeds download limit")
            return data
        except OSError:
            if attempt==2:
                raise
            time.sleep(attempt+1)


def tree(repo, ref):
    data = json.loads(fetch(f"https://api.github.com/repos/{repo}/git/trees/{ref}?recursive=1",2*1024*1024).decode("utf-8"))
    if data.get("truncated"):
        raise ValueError("Incomplete upstream tree")
    files = [x for x in data["tree"] if x["type"]=="blob"]
    for item in files:
        path = PurePosixPath(item["path"])
        if path.is_absolute() or ".." in path.parts or "\\" in item["path"] or item.get("mode") not in {"100644","100755"}:
            raise ValueError("Unsafe upstream asset path")
    return files


def verify(data, item):
    digest = hashlib.sha1(b"blob "+str(len(data)).encode("ascii")+b"\0"+data).hexdigest()
    if len(data)!=item["size"] or digest!=item["sha"]:
        raise ValueError("Asset integrity mismatch")


def paragraph_text(docx):
    ns = {"w":"http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    with zipfile.ZipFile(io.BytesIO(docx)) as archive:
        if archive.getinfo("word/document.xml").file_size>1024*1024:
            raise ValueError("Persona document XML too large")
        xml = archive.read("word/document.xml")
    root = ET.fromstring(xml)
    return "\n".join("".join(p.itertext()) for p in root.findall(".//w:p",ns))


def install(bot_root, rag_root):
    persona_parent = rag_root/"personas"
    persona_parent.mkdir(parents=True,exist_ok=True)
    target = persona_parent/"deepseek-group"
    prompt = next(x for x in tree(PROMPT_REPO,PROMPT_REF) if x["path"]==PROMPT_PATH)
    docx = fetch(f"https://raw.githubusercontent.com/{PROMPT_REPO}/{PROMPT_REF}/"+urllib.parse.quote(PROMPT_PATH))
    verify(docx,prompt)
    text = paragraph_text(docx)
    if target.exists():
        if (target/"source.docx").read_bytes()!=docx or (target/"persona.txt").read_text(encoding="utf-8")!=text:
            raise ValueError("Existing persona differs; explicit migration required")
    else:
        stage = Path(tempfile.mkdtemp(prefix=".persona-download-",dir=persona_parent))
        (stage/"source.docx").write_bytes(docx)
        (stage/"persona.txt").write_text(text,encoding="utf-8")
        (stage/"provenance.json").write_text(json.dumps(dict(repo=PROMPT_REPO,revision=PROMPT_REF,path=PROMPT_PATH,
            document_blob_sha1=prompt["sha"],text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            extraction="Original word/document.xml paragraph text joined with LF; no wording edits or substitutions."),ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        os.replace(stage,target)
        target.chmod(0o755)

    files = tree(PACK_REPO,PACK_REF)
    if len(files)>500 or sum(x["size"] for x in files)>160*1024*1024:
        raise ValueError("Pack exceeds installation limits")
    parent = bot_root/"data/group_memes"
    parent.mkdir(parents=True,exist_ok=True)
    pack = parent/"deepseek-girl-pack"
    if pack.exists():
        for item in files:
            verify((pack/item["path"]).read_bytes(),item)
    else:
        stage = Path(tempfile.mkdtemp(prefix=".meme-download-",dir=parent))
        def download(item):
            data = fetch(f"https://raw.githubusercontent.com/{PACK_REPO}/{PACK_REF}/"+urllib.parse.quote(item["path"]))
            verify(data,item)
            path = stage/item["path"]
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(data)
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(download,files))
        (stage/"provenance.json").write_text(json.dumps(dict(repo=PACK_REPO,revision=PACK_REF,
            total_bytes=sum(x["size"] for x in files),files=[{k:x[k] for k in ("path","sha","size")} for x in files]),ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        os.replace(stage,pack)
        pack.chmod(0o755)
    print(json.dumps(dict(persona_chars=len(text),persona_verbatim=True,pack_files=len(files),
        pack_mib=round(sum(x["size"] for x in files)/1048576,2),persona_path=str(target/"persona.txt"),pack_path=str(pack)),ensure_ascii=False),flush=True)


if __name__=="__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bot-root",type=Path,default=Path.cwd())
    parser.add_argument("--rag-root",type=Path)
    args = parser.parse_args()
    install(args.bot_root.resolve(),(args.rag_root or args.bot_root.parent/"ygo-rag").resolve())
