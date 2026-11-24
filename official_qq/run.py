"""Start only the official QQ interface; never load the OneBot plugins."""
import json
import os
from pathlib import Path
import sys

import nonebot
from nonebot.adapters.qq import Adapter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
cred = json.loads(Path(os.environ["KAMI_OFFICIAL_CREDENTIALS"]).read_text())
backend = Path(os.environ["KAMI_OFFICIAL_BACKENDS"])
for key, value in json.loads(backend.read_text()).items():
    os.environ[key] = value
nonebot.init(
    driver="~fastapi+~httpx+~websockets", host="127.0.0.1", port=18081,
    log_level="WARNING", command_start={"", "/"},
    qq_bots=[{"id": cred["app_id"], "secret": cred["app_secret"],
              "use_websocket": True,
              "intent": {"guilds": False, "guild_members": False,
                         "guild_message_reactions": False, "at_messages": False,
                         "message_audit": False, "c2c_group_at_messages": True}}],
)
driver = nonebot.get_driver()
driver.register_adapter(Adapter)

@driver.on_bot_connect
async def gateway_ready():
    import logging
    logging.getLogger("kami-official").warning("Official QQ gateway connected")

if nonebot.load_plugin("official_qq.queries") is None:
    raise RuntimeError("Official QQ query plugin failed to load")
nonebot.run()
