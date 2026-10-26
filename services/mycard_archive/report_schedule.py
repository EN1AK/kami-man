"""Refresh chart files daily without sending messages or requiring a bot connection."""
import asyncio
from contextlib import suppress
from nonebot import get_driver,logger
from nonebot_plugin_apscheduler import scheduler

def register_daily_refresh(service):
    task=None
    async def refresh():
        try:
            await service().refresh()
            logger.info("[mycard_reports] 今日统计图表缓存已就绪（未发送群消息）")
        except asyncio.CancelledError:raise
        except Exception as exc:
            logger.warning("[mycard_reports] 图表缓存更新失败：{}",type(exc).__name__)
    scheduler.add_job(refresh,"cron",hour=0,minute=10,timezone="Asia/Shanghai",
        id="mycard_daily_charts_refresh",replace_existing=True,max_instances=1,coalesce=True,misfire_grace_time=3600)
    @get_driver().on_startup
    async def startup():
        nonlocal task
        task=asyncio.create_task(refresh(),name="mycard-daily-charts-warmup")
    @get_driver().on_shutdown
    async def shutdown():
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):await task
