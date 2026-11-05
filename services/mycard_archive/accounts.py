"""One room per authenticated account, including duplicate credential files."""
import asyncio
import time
from .protocol import CredentialsUnavailable


class AccountPool:
    def __init__(self, credentials):
        self.credentials = tuple(credentials)
        self.leases = {}
        self.busy = {}
        self.refresh_locks = {c: asyncio.Lock() for c in self.credentials}
        self.failed_until = {}

    async def identity(self, credential):
        async with self.refresh_locks[credential]:
            if self.failed_until.get(credential, 0) > time.monotonic():
                raise CredentialsUnavailable("观战账号暂不可用")
            try:
                return await credential.get()
            except CredentialsUnavailable:
                self.failed_until[credential] = time.monotonic() + 30
                raise

    async def get_for(self, players, ended):
        task = asyncio.current_task()
        if task in self.leases:
            credential, username = self.leases[task]
            identity = await self.identity(credential)
            if identity[0] != username:
                raise CredentialsUnavailable("观战凭据账号已变化，请等待当前连接退出")
            return identity
        while not ended.is_set():
            occupied = False
            for credential in self.credentials:
                if any(owner[0] is credential for owner in self.leases.values()):
                    occupied = True
                    continue
                try:
                    identity = await self.identity(credential)
                except CredentialsUnavailable:
                    continue
                username = identity[0]
                if username in players:
                    continue
                if username in self.busy:
                    occupied = True
                    continue
                # No await between checking the username and reserving it.
                self.busy[username] = task
                self.leases[task] = (credential, username)
                return identity
            if not occupied:
                raise CredentialsUnavailable("没有可用的观战账号，请检查凭据、邮箱验证及账号是否参赛")
            try:
                await asyncio.wait_for(ended.wait(), 0.25)
            except asyncio.TimeoutError:
                pass
        return None

    def invalidate(self):
        lease = self.leases.get(asyncio.current_task())
        if lease:
            lease[0].invalidate()

    def release(self):
        task = asyncio.current_task()
        lease = self.leases.pop(task, None)
        if lease and self.busy.get(lease[1]) is task:
            self.busy.pop(lease[1])
