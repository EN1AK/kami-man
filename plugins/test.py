from nonebot import on_command
from nonebot.adapters.onebot.v11 import MessageEvent

test = on_command("test", aliases={"测试", "ping"}, priority=5)


@test.handle()
async def handle_test(event: MessageEvent):
    await test.finish("bot 正常运行")