"""Priority account leases; each authenticated username can watch one room."""
import asyncio
import time
from .protocol import CredentialsUnavailable


class AccountPool:
    def __init__(self, credentials, *, capacity=None):
        self.credentials = tuple(credentials)
        self.capacity = len(self.credentials) if capacity is None else min(capacity, len(self.credentials))
        self.leases = {}
        self.busy = {}
        self.refresh_locks = {c: asyncio.Lock() for c in self.credentials}
        self.failed_until = {}
        self.checks = {}
        self.checked_at = {}
        self.waiting = {}
        self.sequence = 0

    async def identity(self, credential):
        async with self.refresh_locks[credential]:
            if self.failed_until.get(credential, 0) > time.monotonic():
                raise CredentialsUnavailable("观战账号暂不可用")
            try:
                return await credential.get()
            except CredentialsUnavailable:
                self.failed_until[credential] = time.monotonic() + 30
                raise

    async def check(self, credential):
        try:
            return await self.identity(credential)
        except CredentialsUnavailable:
            return None
        finally:
            self.checked_at[credential] = time.monotonic()

    def start_checks(self):
        now = time.monotonic()
        for credential in self.credentials:
            if any(owner[0] is credential for owner in self.leases.values()):
                continue
            previous = self.checks.get(credential)
            if previous is not None and not previous.done():
                continue
            retry = max(self.checked_at.get(credential, 0) + 1,
                        self.failed_until.get(credential, 0))
            if previous is None or now >= retry:
                self.checks[credential] = asyncio.create_task(self.check(credential))

    async def get_for(self, players, ended, priority=None):
        task = asyncio.current_task()
        if task in self.leases:
            credential, username = self.leases[task]
            identity = await self.identity(credential)
            if identity[0] != username:
                raise CredentialsUnavailable("观战凭据账号已变化，请等待当前连接退出")
            return identity
        self.sequence += 1
        self.waiting[task] = (set(players), ended, priority or (lambda: (0,)), self.sequence)
        try:
            while not ended.is_set():
                self.start_checks()
                for credential in self.credentials:
                    if len(self.busy) >= self.capacity:
                        break
                    check = self.checks.get(credential)
                    if check is None or not check.done() or check.cancelled():
                        continue
                    identity = check.result()
                    if identity is None or identity[0] in self.busy:
                        continue
                    username = identity[0]
                    candidates = [(waiting[2](), waiting[3], owner)
                                  for owner, waiting in self.waiting.items()
                                  if not owner.done() and not waiting[1].is_set()
                                  and username not in waiting[0]]
                    if not candidates or min(candidates, key=lambda item: item[:2])[2] is not task:
                        continue
                    # Selection and username reservation are atomic within the event loop.
                    self.busy[username] = task
                    self.leases[task] = (credential, username)
                    return identity
                if (not self.busy and self.checks and
                    all(c.done() and not c.cancelled() and c.result() is None
                        for c in self.checks.values())):
                    raise CredentialsUnavailable("没有可用的观战账号，请检查凭据及邮箱验证")
                try:
                    await asyncio.wait_for(ended.wait(), 0.1)
                except asyncio.TimeoutError:
                    pass
            return None
        finally:
            self.waiting.pop(task, None)

    def invalidate(self):
        lease = self.leases.get(asyncio.current_task())
        if lease:
            lease[0].invalidate()
            self.checks.pop(lease[0], None)

    def release(self):
        task = asyncio.current_task()
        lease = self.leases.pop(task, None)
        if lease and self.busy.get(lease[1]) is task:
            self.busy.pop(lease[1])
            self.checks.pop(lease[0], None)

    async def close(self):
        tasks = list(self.checks.values())
        for task in tasks:
            if not task.done(): task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.checks.clear()
