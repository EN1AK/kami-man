import json
import os
from datetime import datetime

import aiohttp
import pytz

BASE_URL = "https://sapi.moecube.com:444/ygopro/"

DATA_DIR = "data"
MYCARD_USER_FILE = os.path.join(DATA_DIR, "mycard_user.json")
SUBSCRIBE_FILE = os.path.join(DATA_DIR, "subscribe.json")
LAST_MATCH_FILE = os.path.join(DATA_DIR, "last_match.json")

os.makedirs(DATA_DIR, exist_ok=True)


async def api_get(path: str, params: dict) -> dict | None:
    url = BASE_URL + path
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=10) as resp:
                if resp.status == 200:
                    return await resp.json()
                return None
    except Exception:
        return None


def read_json(path: str, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def write_json(path: str, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


async def fetch_player_history(username: str, page_num: int = 999999):
    data = await api_get("arena/history", {
        "username": username,
        "type": 0,
        "page_num": page_num,
    })
    return data.get("data", []) if data else None


async def fetch_player_info(username: str):
    return await api_get("arena/user", {"username": username})


async def fetch_player_history_rank(username: str, year: int, month: int):
    data = await api_get("arena/historyScore", {
        "username": username,
        "season": f"{year}-{month:02}",
    })
    return data.get("rank") if data else None


async def fetch_latest_record(username: str):
    history = await fetch_player_history(username, page_num=1)
    return history[0] if history else None


async def is_first_win(username: str) -> bool:
    data = await api_get("arena/firstwin", {"username": username})
    return bool(data and data.get("today") == "1")


async def get_current_rank(username: str):
    info = await fetch_player_info(username)
    return info.get("arena_rank") if info else None


def to_shanghai(utc_str: str) -> datetime:
    dt = datetime.strptime(utc_str, "%Y-%m-%dT%H:%M:%S.%fZ")
    return dt.replace(tzinfo=pytz.utc).astimezone(pytz.timezone("Asia/Shanghai"))


def is_specific_month(match: dict, month: int, year: int) -> bool:
    return to_shanghai(match["end_time"]).year == year and to_shanghai(match["end_time"]).month == month


async def get_month_records(username: str, month: int, year: int):
    history = await fetch_player_history(username)
    if history is None:
        return None
    return [r for r in history if is_specific_month(r, month, year)]


def get_mycard_user() -> dict:
    return read_json(MYCARD_USER_FILE, {})


def save_mycard_user(data: dict):
    write_json(MYCARD_USER_FILE, data)


def add_mycard_user(qq: str, mycard_id: str):
    users = get_mycard_user()
    users[str(qq)] = mycard_id
    save_mycard_user(users)


def get_bind_by_qq(qq: str) -> str | None:
    return get_mycard_user().get(str(qq))


def find_qq_by_mycard_id(mycard_id: str) -> list[str]:
    users = get_mycard_user()
    return [qq for qq, username in users.items() if username == mycard_id]


def get_subscribe_list() -> dict:
    return read_json(SUBSCRIBE_FILE, {})


def save_subscribe_list(data: dict):
    write_json(SUBSCRIBE_FILE, data)


def subscribe_target(usertype: str, target_id: str, mycard_id: str):
    data = get_subscribe_list()
    data.setdefault(mycard_id, [])
    item = [usertype, str(target_id)]
    if item not in data[mycard_id]:
        data[mycard_id].append(item)
    save_subscribe_list(data)


def unsubscribe_target(usertype: str, target_id: str, mycard_id: str) -> bool:
    data = get_subscribe_list()
    item = [usertype, str(target_id)]

    if mycard_id in data and item in data[mycard_id]:
        data[mycard_id].remove(item)
        if not data[mycard_id]:
            del data[mycard_id]
        save_subscribe_list(data)
        return True

    return False


def get_last_match_cache() -> dict:
    return read_json(LAST_MATCH_FILE, {})


def save_last_match_cache(data: dict):
    write_json(LAST_MATCH_FILE, data)


def get_match_key(record: dict) -> str:
    return str(
        record.get("id")
        or record.get("_id")
        or f"{record.get('usernamea')}-{record.get('usernameb')}-{record.get('end_time')}"
    )


def is_zero_delta_match(record: dict, username: str) -> bool:
    try:
        if record.get("usernamea") == username:
            delta = float(record["pta"]) - float(record["pta_ex"])
        elif record.get("usernameb") == username:
            delta = float(record["ptb"]) - float(record["ptb_ex"])
        else:
            return False
        return abs(delta) < 1e-9
    except Exception:
        return False


def get_score_before(record: dict, username: str):
    return float(record["pta_ex"]) if record["usernamea"] == username else float(record["ptb_ex"])


def get_score_after(record: dict, username: str):
    return float(record["pta"]) if record["usernamea"] == username else float(record["ptb"])


def format_record(record: dict, username: str) -> str:
    a = record.get("usernamea", "")
    b = record.get("usernameb", "")
    winner = record.get("winner", "")
    before = get_score_before(record, username)
    after = get_score_after(record, username)

    try:
        time_text = to_shanghai(record["end_time"]).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        time_text = record.get("end_time", "未知时间")

    result = "胜利" if winner == username else "失败"

    return (
        f"MyCard 新对局\n"
        f"玩家：{username}\n"
        f"对阵：{a} vs {b}\n"
        f"结果：{result}\n"
        f"胜者：{winner}\n"
        f"分数：{before:.2f} → {after:.2f}\n"
        f"时间：{time_text}"
    )