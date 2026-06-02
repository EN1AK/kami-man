import nonebot
from nonebot.adapters.onebot.v11 import Adapter as OneBotV11Adapter

nonebot.init(
    host="0.0.0.0",
    port=18080,
    command_start={"/", ""},
    superusers={"2954452539"},
)

driver = nonebot.get_driver()
driver.register_adapter(OneBotV11Adapter)

nonebot.load_plugin("nonebot_plugin_apscheduler")
nonebot.load_plugins("plugins")

nonebot.run()