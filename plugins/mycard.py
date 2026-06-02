import base64
import calendar
import html
import re
from datetime import datetime
from io import BytesIO

import matplotlib.pyplot as plt
import pytz
from matplotlib.ticker import MaxNLocator
from nonebot import get_bot, on_command, on_regex
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message, MessageEvent, MessageSegment
from nonebot.params import CommandArg, EventMessage
from nonebot_plugin_apscheduler import scheduler

from services.mycard_api import (
    add_mycard_user,
    fetch_latest_record,
    fetch_player_history,
    fetch_player_history_rank,
    find_qq_by_mycard_id,
    format_record,
    get_bind_by_qq,
    get_current_rank,
    get_last_match_cache,
    get_match_key,
    get_month_records,
    get_score_after,
    get_score_before,
    get_subscribe_list,
    is_first_win,
    is_zero_delta_match,
    save_last_match_cache,
    subscribe_target,
    unsubscribe_target,
)


def plot_to_base64() -> str:
    buf = BytesIO()
    plt.savefig(buf, format="png", bbox_inches="tight", dpi=150)
    buf.seek(0)
    plt.close()
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def get_at_targets(message: Message, bot_id: str) -> list[str]:
    return [
        seg.data.get("qq")
        for seg in message
        if seg.type == "at"
        and seg.data.get("qq")
        and seg.data.get("qq") not in ("all", str(bot_id))
    ]


mycard_query = on_regex(r".*历史.*", priority=5)


@mycard_query.handle()
async def handle_history(bot: Bot, event: MessageEvent, message: Message = EventMessage()):
    plain_text = event.get_plaintext().strip()
    pattern = r"^(?:(\d{2,4})年)?(?:(1[0-2]|[1-9])月)?历史(?:\s+(.+))?$"
    res = re.match(pattern, plain_text)
    if not res:
        return

    year = int(res.group(1)) if res.group(1) else None
    month = int(res.group(2)) if res.group(2) else None
    username = html.unescape(res.group(3).strip()) if res.group(3) else None

    if not username:
        at_targets = get_at_targets(message, str(bot.self_id))
        if at_targets:
            username = get_bind_by_qq(at_targets[0])
            if not username:
                await mycard_query.finish("对方未绑定 MyCard 用户名！")
        else:
            username = get_bind_by_qq(str(event.user_id))
            if not username:
                await mycard_query.finish("请先绑定或提供 MyCard 用户名！")

    now = datetime.now()
    current_year = now.year
    current_month = now.month

    if not month:
        year = current_year
        month = current_month
    elif not year:
        year = current_year if month <= current_month else current_year - 1
    elif year < 2000:
        year += 2000

    records = await get_month_records(username, month, year)
    if records is None:
        await mycard_query.finish("查询失败，请稍后重试")

    valid_records = [r for r in records if not is_zero_delta_match(r, username)]
    wins = [r for r in valid_records if r.get("winner") == username]

    prefix = f"{year - 2000}年" if year != current_year else ""
    result_message = (
        f"玩家：{username}\n"
        f"{prefix}{month}月场次：{len(valid_records)}\n"
        f"{prefix}{month}月胜率：{(0 if not valid_records else len(wins) * 100 / len(valid_records)):.2f}%"
    )

    if not valid_records:
        await mycard_query.finish(result_message)

    pt_ex = [get_score_before(r, username) for r in valid_records]
    pt = [get_score_after(r, username) for r in valid_records]
    pt.append(pt_ex[-1])
    pt.reverse()

    tz_shanghai = pytz.timezone("Asia/Shanghai")
    now_shanghai = datetime.now(tz_shanghai)
    last_day = calendar.monthrange(year, month)[1]
    settlement_dt = tz_shanghai.localize(datetime(year, month, last_day, 22, 0, 0))

    is_current_month = year == current_year and month == current_month
    is_settled = not is_current_month or now_shanghai >= settlement_dt

    if is_settled:
        result_message += f"\n结算分数：{pt[-1]:.2f}"
        rank = await fetch_player_history_rank(username, year, month)
        if rank is not None:
            result_message += f"\n结算排名：{rank}"
    else:
        result_message += f"\n当前分数：{pt[-1]:.2f}"
        rank = await get_current_rank(username)
        if rank is not None:
            result_message += f"\n当前排名：{rank}"

    plt.figure(figsize=(8, 6))
    plt.plot(pt, marker=".", linestyle="--", linewidth=0.5)
    plt.gca().xaxis.set_major_locator(MaxNLocator(integer=True))
    if pt:
        plt.text(0, pt[0], f"{pt[0]:.2f}", ha="center", va="bottom", fontsize=10)
        max_idx = pt.index(max(pt))
        plt.text(max_idx, pt[max_idx], f"{pt[max_idx]:.2f}", ha="center", va="bottom", fontsize=10)

    image_base64 = plot_to_base64()

    await mycard_query.finish(
        Message([
            MessageSegment.text(result_message),
            MessageSegment.image(f"base64://{image_base64}"),
        ])
    )


bind = on_command("绑定", priority=5)


@bind.handle()
async def handle_bind(event: MessageEvent, args: Message = CommandArg()):
    username = html.unescape(args.extract_plain_text().strip())
    if not username:
        await bind.finish("请提供要绑定的用户名！")
    add_mycard_user(str(event.user_id), username)
    await bind.finish("绑定成功！")


subscribe = on_command("订阅", priority=5)


@subscribe.handle()
async def handle_subscribe(event: MessageEvent, args: Message = CommandArg()):
    username = html.unescape(args.extract_plain_text().strip())
    if not username:
        username = get_bind_by_qq(str(event.user_id))

    if not username:
        await subscribe.finish("请先绑定或提供要订阅的 MyCard 用户名！")

    latest = await fetch_latest_record(username)
    if not latest:
        await subscribe.finish("用户不存在或暂无对战记录！")

    if isinstance(event, GroupMessageEvent):
        subscribe_target("group", str(event.group_id), username)
    else:
        subscribe_target("private", str(event.user_id), username)

    cache = get_last_match_cache()
    cache.setdefault(username, get_match_key(latest))
    save_last_match_cache(cache)

    await subscribe.finish(f"订阅成功：{username}")


unsubscribe = on_command("退订", priority=5)


@unsubscribe.handle()
async def handle_unsubscribe(event: MessageEvent, args: Message = CommandArg()):
    username = html.unescape(args.extract_plain_text().strip())
    if not username:
        username = get_bind_by_qq(str(event.user_id))

    if not username:
        await unsubscribe.finish("请先绑定或提供要退订的 MyCard 用户名！")

    if isinstance(event, GroupMessageEvent):
        ok = unsubscribe_target("group", str(event.group_id), username)
    else:
        ok = unsubscribe_target("private", str(event.user_id), username)

    await unsubscribe.finish("退订成功！" if ok else "未找到该订阅。")


first_win = on_command("首胜查询", aliases={"首赢查询"}, priority=5)


@first_win.handle()
async def handle_first_win(event: MessageEvent, args: Message = CommandArg()):
    username = html.unescape(args.extract_plain_text().strip()) or get_bind_by_qq(str(event.user_id))
    if not username:
        await first_win.finish("请先绑定或提供用户名！")

    ok = await is_first_win(username)
    await first_win.finish(f"{username} {'已完成' if ok else '还未完成'}今日首赢！")


whois = on_command("查询绑定", aliases={"绑定查询"}, priority=5)


@whois.handle()
async def handle_whois(bot: Bot, event: MessageEvent, args: Message = CommandArg(), message: Message = EventMessage()):
    at_targets = get_at_targets(message, str(bot.self_id))

    if at_targets:
        qq = at_targets[0]
        username = get_bind_by_qq(qq)
        await whois.finish(f"该用户绑定的 MyCard 用户名为：{username}" if username else "该用户还未绑定 MyCard 用户名！")

    input_text = html.unescape(args.extract_plain_text().strip())
    if input_text:
        qq_list = find_qq_by_mycard_id(input_text)
        await whois.finish(
            f"以下 QQ 绑定了 MyCard 用户名 {input_text}：{'、'.join(qq_list)}"
            if qq_list else f"暂无用户绑定 MyCard 用户名 {input_text}！"
        )

    username = get_bind_by_qq(str(event.user_id))
    await whois.finish(f"你绑定的 MyCard 用户名为：{username}" if username else "你还未绑定 MyCard 用户名！")


winrate = on_command("胜率查询", aliases={"胜率统计"}, priority=5)


@winrate.handle()
async def handle_winrate(event: MessageEvent, args: Message = CommandArg()):
    username = html.unescape(args.extract_plain_text().strip()) or get_bind_by_qq(str(event.user_id))
    if not username:
        await winrate.finish("请先绑定或提供用户名！")

    records = await fetch_player_history(username)
    if records is None:
        await winrate.finish("查询失败，请稍后重试")
    if not records:
        await winrate.finish(f"玩家 {username} 暂无对战记录")

    valid_records = [r for r in records if not is_zero_delta_match(r, username)]
    monthly_data = {}

    for record in valid_records:
        start_time = datetime.strptime(record["start_time"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=pytz.utc).astimezone(pytz.timezone("Asia/Shanghai"))
        key = f"{start_time.year}-{start_time.month:02d}"
        monthly_data.setdefault(key, {"total": 0, "wins": 0})
        monthly_data[key]["total"] += 1
        if record.get("winner") == username:
            monthly_data[key]["wins"] += 1

    sorted_months = sorted(monthly_data.keys())
    total_games = len(valid_records)
    total_wins = len([r for r in valid_records if r.get("winner") == username])
    overall_rate = total_wins * 100 / total_games if total_games else 0

    result_message = (
        f"玩家：{username}\n"
        f"总场次：{total_games}\n"
        f"总胜率：{overall_rate:.2f}%\n"
        f"有对局的月份：{len(sorted_months)}个"
    )

    if not sorted_months:
        await winrate.finish(result_message)

    labels = []
    rates = []

    for key in sorted_months:
        total = monthly_data[key]["total"]
        wins = monthly_data[key]["wins"]
        rates.append(wins * 100 / total if total else 0)
        y, m = key.split("-")
        labels.append(f"{y[-2:]}/{int(m)}")

    plt.figure(figsize=(12, 6))
    plt.plot(range(len(rates)), rates, marker="o", linestyle="-", linewidth=2)
    plt.ylim(0, 100)
    plt.xticks(range(len(labels)), labels, rotation=45, ha="right")
    plt.grid(True, alpha=0.3)
    for i, rate in enumerate(rates):
        plt.text(i, rate + 2, f"{rate:.1f}%", ha="center", va="bottom", fontsize=9)
    plt.tight_layout()

    image_base64 = plot_to_base64()

    await winrate.finish(
        Message([
            MessageSegment.text(result_message),
            MessageSegment.image(f"base64://{image_base64}"),
        ])
    )


@scheduler.scheduled_job("interval", seconds=60, id="mycard_subscribe_checker")
async def check_mycard_subscribe():
    subs = get_subscribe_list()
    if not subs:
        return

    cache = get_last_match_cache()
    changed = False

    try:
        bot = get_bot()
    except Exception:
        return

    for username, targets in list(subs.items()):
        latest = await fetch_latest_record(username)
        if not latest:
            continue

        latest_key = get_match_key(latest)
        old_key = cache.get(username)

        if old_key is None:
            cache[username] = latest_key
            changed = True
            continue

        if latest_key == old_key:
            continue

        cache[username] = latest_key
        changed = True

        msg = format_record(latest, username)

        for usertype, target_id in targets:
            try:
                if usertype == "group":
                    await bot.call_api("send_group_msg", group_id=int(target_id), message=msg)
                elif usertype == "private":
                    await bot.call_api("send_private_msg", user_id=int(target_id), message=msg)
            except Exception:
                continue

    if changed:
        save_last_match_cache(cache)