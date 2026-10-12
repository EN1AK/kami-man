"""Configure an ordinary MyCard login token without echoing it or storing passwords."""
import argparse
import asyncio
import getpass
import json
import os
from pathlib import Path
import sys
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import aiohttp

async def configure(path):
    token=getpass.getpass("MyCard login token (hidden): ").strip()
    if not token:raise ValueError("Token is empty")
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
        async with session.get("https://sapi.moecube.com:444/accounts/authUser",headers={"Authorization":"Bearer "+token}) as response:
            if response.status!=200:raise ValueError("MyCard authentication failed")
            info=await response.json()
    if not isinstance(info,dict) or not isinstance(info.get("username"),str) or type(info.get("u16Secret")) is not int:raise ValueError("MyCard spectator identity is unavailable")
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+"."+uuid.uuid4().hex+".tmp")
    try:
        fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,"w",encoding="utf-8") as file:json.dump({"token":token},file)
        temporary.replace(path);path.chmod(0o600)
    finally:temporary.unlink(missing_ok=True)
    print("Credentials saved securely. Active pending rooms will resume automatically.")

if __name__=="__main__":
    default=Path(__file__).resolve().parents[1]/"data/mycard_archive/credentials.json"
    parser=argparse.ArgumentParser();parser.add_argument("--path",type=Path,default=default)
    args=parser.parse_args()
    try:asyncio.run(configure(args.path.resolve()))
    except Exception:raise SystemExit("Unable to configure MyCard credentials; no token or password was logged.")
