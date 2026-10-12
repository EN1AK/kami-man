"""Ordinary MyCard account authentication and read-only spectator TCP packets."""
import asyncio
import base64
import json
import hashlib
from pathlib import Path
import struct
import time
import aiohttp

class CredentialsUnavailable(RuntimeError):pass

class Credentials:
    def __init__(self,path,session):
        self.path=Path(path);self.session=session
        self.lock=asyncio.Lock();self.identity=None;self.signature=None;self.expires=0
    def invalidate(self):self.expires=0
    async def get(self):
        async with self.lock:
            try:
                text=await asyncio.to_thread(self.path.read_text,encoding="utf-8")
                signature=hashlib.sha256(text.encode("utf-8")).digest()
                if self.identity and signature==self.signature and time.monotonic()<self.expires:return self.identity
                info=json.loads(text)
                if not isinstance(info,dict):raise CredentialsUnavailable("观战凭据文件格式错误")
                if info.get("token"):
                    if not isinstance(info["token"],str) or len(info["token"])>16384:raise CredentialsUnavailable("观战登录令牌格式错误")
                    async with self.session.get("https://sapi.moecube.com:444/accounts/authUser",headers={"Authorization":"Bearer "+info["token"]},timeout=aiohttp.ClientTimeout(total=20)) as response:
                        if response.status!=200:raise CredentialsUnavailable(f"MyCard 登录已失效（HTTP {response.status}）")
                        auth=await response.json()
                    username,secret=auth.get("username"),auth.get("u16Secret")
                else:username,secret=info.get("username"),info.get("u16_secret")
                if not isinstance(username,str) or not username or "\x00" in username or type(secret) is not int or not 0<=secret<2**64:
                    raise CredentialsUnavailable("凭据缺少有效用户名或观战密钥")
                self.identity=(username,secret);self.signature=signature;self.expires=time.monotonic()+600
                return self.identity
            except FileNotFoundError:raise CredentialsUnavailable("尚未配置 MyCard 观战凭据") from None
            except CredentialsUnavailable:raise
            except Exception:raise CredentialsUnavailable("无法读取或刷新 MyCard 观战凭据") from None


def join_request(identity,room_id,version):
    username,secret=identity
    def wide(value):
        if not isinstance(value,str) or not value or "\x00" in value:raise ValueError("观战名称为空或包含终止符")
        encoded=value.encode("utf-16-le")
        if len(encoded)>38:raise ValueError("观战名称超过协议长度")
        return encoded+b"\0"*(40-len(encoded))
    def packet(kind,payload):return struct.pack("<H",len(payload)+1)+bytes([kind])+payload
    if type(secret) is not int or secret<0 or not 0<=version<=65535:raise ValueError("观战协议参数错误")
    key=secret%65535+1
    invitation=struct.pack("<3H",0x30D0^key,key,key)
    password=base64.b64encode(invitation).decode("ascii")+room_id
    return packet(0x10,wide(username))+packet(0x12,struct.pack("<H2xI",version,0)+wide(password))

async def frame(reader):
    size=struct.unpack("<H",await reader.readexactly(2))[0]
    if size<1:raise ValueError("无效观战数据包")
    payload=await asyncio.wait_for(reader.readexactly(size),30)
    return payload[0],payload[1:]

async def watch(room_id,identity,ended,on_replay,*,host="tiramisu.moecube.com",port=8911,version=0x1362,on_connected=None,drain_seconds=30,handshake_seconds=15):
    request=join_request(identity,room_id,version)
    reader,writer=await asyncio.wait_for(asyncio.open_connection(host,port),20)
    end_task=asyncio.create_task(ended.wait());packet_task=None;observer=False;drain_deadline=None
    loop=asyncio.get_running_loop();handshake_deadline=loop.time()+handshake_seconds
    try:
        writer.write(request);await writer.drain()
        while True:
            packet_task=asyncio.create_task(frame(reader))
            if not ended.is_set():
                done,_=await asyncio.wait([packet_task,end_task],timeout=None if observer else max(0,handshake_deadline-loop.time()),return_when=asyncio.FIRST_COMPLETED)
                if not done:raise TimeoutError("观战身份握手超时")
            if ended.is_set():
                if drain_deadline is None:drain_deadline=loop.time()+drain_seconds
                remaining=drain_deadline-loop.time()
                if remaining<=0:return False
                try:kind,data=await asyncio.wait_for(packet_task,remaining)
                except asyncio.TimeoutError:return False
            else:kind,data=await packet_task
            packet_task=None
            if kind==0x02:raise CredentialsUnavailable("服务器拒绝观战身份；请检查账号、版本或房间权限")
            if kind==0x13:
                if not data or data[0]&15!=7:raise CredentialsUnavailable("未获得只读观战席位")
                observer=True
                if on_connected:on_connected()
            elif kind==0x17:
                if not observer:raise ValueError("身份确认之前收到录像，已拒绝归档")
                await on_replay(data)
            elif kind==0x16:return observer
    except asyncio.IncompleteReadError:return False
    finally:
        tasks=[t for t in [packet_task,end_task] if t is not None]
        for task in tasks:task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        writer.close()
        try:await asyncio.wait_for(writer.wait_closed(),5)
        except (OSError,asyncio.TimeoutError):pass
