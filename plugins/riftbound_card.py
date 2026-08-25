from nonebot import on_command

# 符文（Riftbound）查卡功能已停用。
# 保留命令注册以占用这些指令前缀，命中后静默结束，不发送任何回复，
# 并通过 block=True 阻止事件继续向下层匹配器传播。
rb = on_command("rb", aliases={"符文查卡", "符文"}, priority=5, block=True)
rb_pl = on_command("rbpl", aliases={"符文批量", "符文批量查卡"}, priority=5, block=True)


@rb.handle()
async def handle_rb():
    return


@rb_pl.handle()
async def handle_rb_pl():
    return
