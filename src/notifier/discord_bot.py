"""
Discord BOT 本体（複数スポーツ対応）。

監視対象は config.SPORTS で定義する。各スポーツは「窓タイプ」を持つ:

- WINDOW_FIXED_CLOCK（MLB方式）:
    毎日きまった時刻帯(21:00〜23:59 JST)を一律監視。窓の開始時に全試合の基準を
    一括取得し、以後1分ごとに判定・5分ごとにスナップショット保存。

- WINDOW_PREGAME（NPB方式）:
    試合ごとに窓が動く。各試合の開始90分前〜5分前を個別に監視。
    試合が窓に入った瞬間にその試合の基準を保存し「監視開始」を通知、
    窓内は1分ごとに判定、開始5分前を過ぎたら「監視終了」を通知。
    API節約のため、窓が近い試合がある時だけ毎分ポーリングする。

通知文は format_* 関数が組み立て、先頭にスポーツのラベル(⚾MLB / ⚾NPB)を付ける。
"""

import asyncio
import traceback
from datetime import datetime, timezone, timedelta

import discord

from sqlalchemy import select

from src import config
from src.api.odds_api import get_games_with_handicap, get_events, get_scores, get_current_games
from src.db.database import get_session
from src.db.models import PaperBet
from src.monitor.base_odds import (
    create_base_odds_handicap,
    create_base_odds_for_game_handicap,
    create_h2h_favorite_base_for_game,
    has_base_odds_for_date,
    has_base_odds_for_game,
    load_base_odds_handicap,
    load_h2h_base_map,
)
from src.monitor.level_check import MonitorState, NotificationEvent, evaluate
from src.monitor.paper_trade import (
    record_paper_bets,
    settle_paper_bets,
    scores_lookup_from_oddsapi,
    summary as paper_summary,
)
from src.api.odds_api import _fetch_one_event_handicap
from src.monitor.handicap_report import (
    kickoff_in_window,
    pick_due_slot,
    extract_pinnacle_zero_line,
)
from src.monitor.snapshot import save_snapshot_handicap
from src.utils.team_names import format_game_name_ja, to_ja
from src.utils.time_utils import (
    in_monitor_window,
    in_pregame_window,
    now_jst,
    parse_commence_time,
    window_session_date,
)


# =====================================================================
# Discord クライアント＆グローバル状態
# =====================================================================
intents = discord.Intents.default()
client = discord.Client(intents=intents)

_startup_sent = False
_monitor_task: asyncio.Task | None = None  # 稼働中の監視ループ。二重起動を防ぐ
_paper_settled_date = None  # ペーパートレードを最後に決済・報告したJST日付（1日1回）
_report_events_cache: dict = {}   # sport_key -> (events, last_fetch_jst) ハンデ速報の予定キャッシュ
_report_fired: dict = {}          # game_id -> {"slots": set, "commence": utc} 発火済みスロット

# ループの基本間隔（秒）。各スポーツの「1分ごと判定」「5分ごと保存」は
# この間隔で回しつつ、最終実行時刻との差で間引いて実現する。
TICK_SECONDS = 30

# NPB（試合ごと方式）で、監視対象の試合が近くに無いときの軽いポーリング間隔（秒）。
# 試合予定（開始時刻）を把握し続けるためだけの低頻度フェッチ。
NPB_SCHEDULE_REFRESH_SECONDS = 1800  # 30分

# NPB で「窓が開く何分前から毎分ポーリングに切り替えるか」。
# これにより窓が開く(=開始90分前)瞬間の基準を取りこぼさない。
NPB_PREPOLL_MINUTES = 3


# =====================================================================
# 通知文の整形
# =====================================================================
def _point_str(point: float | None) -> str:
    """ハンデのライン値を ' (ハンデ +1.0)' のような表記にする。None なら空文字。"""
    if point is None:
        return ""
    return f"（ハンデ {point:+g}）"


def format_pinnacle_level(e: NotificationEvent, emoji: str = "⚾") -> str:
    badge = {
        1: "🟢 LEVEL1",
        2: "🟠 LEVEL2",
        3: "🔴 LEVEL3",
        4: "🟣 LEVEL4",
        5: "🟤 LEVEL5",
        6: "⚫ LEVEL6",
        7: "🚨 LEVEL7",
    }.get(e.level, "LEVEL?")
    direction = "📈 オッズ上昇" if (e.move or 0) > 0 else "📉 オッズ低下"
    tag = f"【{e.note}】 " if e.note else ""
    return (
        f"{tag}{badge}\n"
        f"{emoji} {format_game_name_ja(e.game_name)}\n"
        f"🎯 {to_ja(e.team)}{_point_str(e.point)}\n"
        f"📚 {e.bookmaker}\n\n"
        f"基準: {e.base_odds:.2f}\n"
        f"現在: {e.current_odds:.2f}\n"
        f"変動: {e.move:+.2f}\n\n"
        f"{direction}"
    )


def format_pinnacle_clear(e: NotificationEvent, emoji: str = "⚾") -> str:
    tag = f"【{e.note}】 " if e.note else ""
    return (
        f"{tag}⚪ LEVEL解除\n"
        f"{emoji} {format_game_name_ja(e.game_name)}\n"
        f"🎯 {to_ja(e.team)}{_point_str(e.point)}\n"
        f"📚 {e.bookmaker}\n\n"
        f"基準: {e.base_odds:.2f}\n"
        f"現在: {e.current_odds:.2f}\n"
        f"変動: {e.move:+.2f}"
    )


def format_steam_move(e: NotificationEvent, emoji: str = "⚾") -> str:
    arrow = "📈 上昇" if e.direction == "up" else "📉 低下"
    lines = [
        f"⚡ Steam Move 検知（{arrow} / {len(e.books)}ブック同方向）",
        f"{emoji} {format_game_name_ja(e.game_name)}",
        f"🎯 {to_ja(e.team)}",
        "",
        "参加ブック:",
    ]
    for b in e.books:
        pt = _point_str(b.get("point"))
        lines.append(
            f"  - {b['bookmaker']}{pt}: {b['base']:.2f} → {b['current']:.2f} ({b['move']:+.2f})"
        )
    return "\n".join(lines)


def format_steam_clear(e: NotificationEvent, emoji: str = "⚾") -> str:
    arrow = "上昇" if e.direction == "up" else "低下"
    return (
        f"⚪ Steam Move 解除（直前: {arrow}）\n"
        f"{emoji} {format_game_name_ja(e.game_name)}\n"
        f"🎯 {to_ja(e.team)}\n"
        f"（同方向ブック数が {config.STEAM_MIN_BOOKS} 未満になった）"
    )


_FORMATTERS = {
    "pinnacle_level": format_pinnacle_level,
    "pinnacle_clear": format_pinnacle_clear,
    "steam_move": format_steam_move,
    "steam_clear": format_steam_clear,
}


def format_event(e: NotificationEvent, emoji: str = "⚾") -> str:
    return _FORMATTERS[e.kind](e, emoji)


async def _send(channel, label: str, text: str) -> None:
    """先頭にスポーツのラベルを付けて送信する。送信失敗はログのみ。"""
    try:
        await channel.send(f"{label}\n{text}")
    except Exception as send_err:
        print(f"[discord] 通知送信エラー: {send_err}")


async def _run_h2h_watch(channel, rt: "SportRuntime", now: datetime, allowed_gids=None) -> None:
    """
    1×2(勝敗オッズ)の「人気側(オッズ最小)」を監視する（NPB・サッカーのみ）。
    ハンデ監視とは別トラッキング。基準が未保存の試合は初回に人気側基準を作る（冪等）。
    人気側が基準から Level1(0.05)以上動いたら「1×2」ラベル付きで通知する。
    allowed_gids を渡すと、その試合IDだけを対象にする（NPBの窓内試合に限定）。
    """
    if not config.sport_h2h_watch(rt.cfg):
        return
    base_date = now.date()
    h2h_games = await asyncio.to_thread(get_current_games, rt.sport_key, None, "h2h")
    if allowed_gids is not None:
        h2h_games = [g for g in h2h_games if g.get("id") in allowed_gids]
    if not h2h_games:
        return

    events = []
    with get_session() as s:
        # 基準がまだ無い試合だけ、人気側の基準を保存（冪等: game_id×market='h2h'で判定）
        for g in h2h_games:
            gid = g.get("id")
            if not gid:
                continue
            if not has_base_odds_for_game(s, gid, sport=rt.sport_key, market="h2h"):
                create_h2h_favorite_base_for_game(s, g, base_date, sport=rt.sport_key)
        s.flush()
        rt.h2h_base_map = load_h2h_base_map(s, base_date, sport=rt.sport_key)
        if rt.h2h_base_map:
            events = evaluate(
                s, h2h_games, rt.h2h_base_map, rt.h2h_state,
                alert_time=now, sport=rt.sport_key, base_points=None,
            )

    for e in events:
        if e.kind in ("pinnacle_level", "pinnacle_clear"):
            e.note = "1×2"
            await _send(channel, rt.label, format_event(e, rt.emoji))


# =====================================================================
# スポーツごとの実行時状態
# =====================================================================
class SportRuntime:
    """1スポーツ分の監視状態をまとめて持つ入れ物。"""

    def __init__(self, sport_cfg: dict):
        self.cfg = sport_cfg
        self.sport_key = sport_cfg["sport_key"]
        self.label = sport_cfg["label"]
        self.emoji = sport_cfg.get("emoji", "⚾")
        self.window = sport_cfg["window"]
        # 監視窓(スポーツ別)。MLB=21:00〜23:59 / サッカー6リーグ=20:00〜23:59。
        self.base_hour, self.base_minute, self.end_hour, self.end_minute = (
            config.sport_window(sport_cfg)
        )

        self.state = MonitorState()
        self.base_odds_map: dict[tuple[str, str, str], float] = {}       # 基準価格(decimal)
        self.base_points: dict[tuple[str, str, str], float] = {}         # 基準のハンデ点
        self.last_check_time: datetime | None = None
        self.last_snapshot_time: datetime | None = None

        # --- 1×2(h2h) 人気側 監視用（NPB・サッカーのみ）---
        self.h2h_state = MonitorState()
        self.h2h_base_map: dict[tuple[str, str, str], float] = {}

        # --- 固定時刻方式(MLB)用 ---
        self.last_base_date = None
        self.was_in_window = False
        self.paper_recorded_date = None   # ペーパートレードを記録済みのJST日付

        # --- 試合ごと方式(NPB)用 ---
        self.cached_games: list[dict] = []          # 予定(get_events)のキャッシュ。窓判定に使う
        self.last_schedule_time: datetime | None = None  # 予定を最後に更新した時刻
        self.last_fetch_time: datetime | None = None     # ハンデ階段を最後に取った時刻
        # game_id -> {"name": 試合名, "commence": 開始UTC}
        self.active_games: dict[str, dict] = {}
        self.last_seen_date = None

    def reset_day(self) -> None:
        """日付が変わったときに当日ぶんの状態をまっさらにする。"""
        self.state = MonitorState()
        self.base_odds_map = {}
        self.base_points = {}
        self.last_check_time = None
        self.last_snapshot_time = None
        self.last_base_date = None
        self.active_games = {}
        self.last_fetch_time = None
        self.paper_recorded_date = None
        self.h2h_state = MonitorState()
        self.h2h_base_map = {}


# =====================================================================
# 監視ループ（全スポーツを1つのループで回す）
# =====================================================================
async def _run_one_sport(channel, rt: "SportRuntime", now: datetime) -> None:
    """1スポーツ分のハンドラを実行（例外はここで握りつぶしてループを止めない）。"""
    try:
        if rt.window == config.WINDOW_FIXED_CLOCK:
            await _handle_fixed_clock(channel, rt, now)
        elif rt.window == config.WINDOW_PREGAME:
            await _handle_pregame(channel, rt, now)
    except Exception as e:
        print(f"[monitor_loop:{rt.sport_key}] エラー: {e}")
        traceback.print_exc()


async def monitor_loop(channel: discord.abc.Messageable) -> None:
    runtimes = [SportRuntime(s) for s in config.SPORTS]

    while not client.is_closed():
        now = now_jst()
        # 全スポーツを「同時並行」で処理する。以前は for で直列に await していたため、
        # 後ろのスポーツ(サッカー/NPB)が前(MLB等)の取得完了を待って遅延していた。
        # gather で各スポーツを独立に走らせ、遅延をスポーツ間で切り離す。
        await asyncio.gather(*(_run_one_sport(channel, rt, now) for rt in runtimes))

        # 全スポーツ共通: ペーパートレードの決済＆日次レポート（1日1回）
        try:
            await _handle_paper_settlement(channel, now)
        except Exception as e:
            print(f"[monitor_loop:paper_settlement] エラー: {e}")
            traceback.print_exc()

        # サッカー: 開始が近い試合のハンデ速報（開始30〜5分前に計6回）
        try:
            await _handle_handicap_report(channel, now)
        except Exception as e:
            print(f"[monitor_loop:handicap_report] エラー: {e}")
            traceback.print_exc()

        await asyncio.sleep(TICK_SECONDS)


# =====================================================================
# ハンデ速報（サッカー）: 開始30〜5分前に Pinnacleハンデ倍率を計6回通知
# =====================================================================
def _report_channel(default_channel):
    """ハンデ速報の送信先。HANDICAP_REPORT_CHANNEL_ID があればそのチャンネル、無ければ通常。"""
    cid = config.HANDICAP_REPORT_CHANNEL_ID
    if cid:
        ch = client.get_channel(cid)
        if ch is not None:
            return ch
    return default_channel


def _sport_channel(sport_key: str, default_channel):
    """スポーツ別の専用チャンネル。設定が無ければ通常チャンネルへ（NBA等だけ分ける）。"""
    cid = config.sport_channel_id(sport_key)
    if cid:
        ch = client.get_channel(cid)
        if ch is not None:
            return ch
    return default_channel


def _format_handicap_report(event: dict, commence_jst: datetime, zero_line: list, slot: int) -> str | None:
    """Pinnacleの0ハンデを速報文面にする。0ラインが無ければ None。"""
    if not zero_line:
        return None
    away = to_ja(event.get("away_team", ""))
    home = to_ja(event.get("home_team", ""))
    lines = [
        f"📊 ピナクル ハンデ速報（0ライン / 開始{slot}分前）",
        f"🕙 {commence_jst.strftime('%H:%M')}開始  {away} vs {home}",
    ]
    for team, _point, dec in zero_line:
        lines.append(f"・{to_ja(team)} {dec:.2f}")
    return "\n".join(lines)


async def _handle_handicap_report(channel, now: datetime) -> None:
    """
    対応サッカー全大会で、JST 20:00〜翌1:30 に始まる試合について、
    開始30〜5分前に5分おき（計6回）Pinnacleのハンデ倍率を速報する。
    予定(get_events,無料)で発火タイミングを判定し、発火する試合があるときだけ
    spreads(有料,一括/odds)を取得して送信直前の新鮮なオッズを届ける。
    """
    now_utc = now.astimezone(timezone.utc)

    for s in config.SPORTS:
        if not s["sport_key"].startswith("soccer_"):
            continue
        sport = s["sport_key"]

        # 予定を15分おきに更新（無料）
        evs, last = _report_events_cache.get(sport, (None, None))
        if last is None or (now - last).total_seconds() >= config.HANDICAP_REPORT_EVENTS_REFRESH_SECONDS:
            fetched = await asyncio.to_thread(get_events, sport)
            if fetched:
                evs = fetched
            _report_events_cache[sport] = (evs or [], now)
        if not evs:
            continue

        # 発火すべき試合を集める
        due = []  # (event, commence_jst, fire_slot, marks)
        for e in evs:
            cs = e.get("commence_time")
            gid = e.get("id")
            if not cs or not gid:
                continue
            try:
                commence = parse_commence_time(cs)
            except Exception:
                continue
            commence_jst = commence.astimezone(config.JST)
            if not kickoff_in_window(commence_jst):
                continue
            minutes_before = (commence - now_utc).total_seconds() / 60
            fired = _report_fired.get(gid, {}).get("slots", set())
            fire, marks = pick_due_slot(minutes_before, fired)
            if fire is not None:
                due.append((e, commence_jst, fire, marks))

        if not due:
            continue

        # 発火する試合だけ、その試合の alternate_spreads を取得（送信直前＝新鮮）して0ライン抽出
        report_ch = _report_channel(channel)
        for e, commence_jst, fire, marks in due:
            data, _ = await asyncio.to_thread(
                _fetch_one_event_handicap, sport, e["id"], config.ODDS_REGIONS, "alternate_spreads"
            )
            zero_line = extract_pinnacle_zero_line(data) if data else []
            msg = _format_handicap_report(e, commence_jst, zero_line, fire)
            if not msg:
                continue   # Pinnacleの0ラインがまだ無い → 済みにせず次tickで再試行
            await _send(report_ch, s["label"], msg)
            rec = _report_fired.setdefault(e["id"], {"slots": set(), "commence": None})
            rec["slots"].update(marks)
            rec["commence"] = parse_commence_time(e["commence_time"])

    # 終了済み(キックオフ1時間超過)の試合の発火記録を掃除
    stale = [
        gid for gid, rec in _report_fired.items()
        if rec.get("commence") and (now_utc - rec["commence"]).total_seconds() > 3600
    ]
    for gid in stale:
        _report_fired.pop(gid, None)


# =====================================================================
# ペーパートレード: 日次の決済＆レポート
# =====================================================================
async def _handle_paper_settlement(channel, now: datetime) -> None:
    """
    JST RESULT_FETCH_HOUR 以降に1日1回、未決済ベットを /scores で決済し、
    本日ぶんと累計の損益を Discord に報告する。
    """
    global _paper_settled_date
    if now.hour < config.RESULT_FETCH_HOUR:
        return
    if _paper_settled_date == now.date():
        return

    with get_session() as s:
        # 未決済ベットが在るスポーツだけ /scores を叩く（クレジット節約）
        sports = [
            r[0] for r in s.execute(
                select(PaperBet.sport).where(PaperBet.settled == 0).distinct()
            ).all()
        ]
        if not sports:
            _paper_settled_date = now.date()   # 何も無ければ静かに終了
            return

        total_settled = 0
        for sp in sports:
            lookup = scores_lookup_from_oddsapi(get_scores(sp))
            total_settled += settle_paper_bets(s, lookup, sport=sp, settled_time=now)

        s.flush()
        report = _build_paper_report(s, now.date())

    _paper_settled_date = now.date()
    if total_settled or report:
        await _send(channel, "📊ペーパートレード", report)


def _build_paper_report(session, today_jst) -> str:
    """本日ぶん＋累計の損益レポート文面を作る。"""
    overall = paper_summary(session)
    today = paper_summary(session, bet_date=today_jst)

    def line(tag, x):
        if x["bets"] == 0:
            return f"{tag}: なし"
        return (
            f"{tag}: {x['total_pt']:+.2f}pt "
            f"(勝{x['win']}/負{x['lose']}/分{x['push']}"
            + (f"/半勝{x['half_win']}/半負{x['half_lose']}"
               if (x['half_win'] or x['half_lose']) else "")
            + f" 的中{x['hit_rate']}%)"
        )

    lines = ["📊 ペーパートレード結果", line("本日", today), line("累計", overall)]

    # スポーツ別の累計（登録があるものだけ）
    per = []
    for s in config.SPORTS:
        x = paper_summary(session, sport=s["sport_key"])
        if x["bets"]:
            per.append(f"　{s['label']}: {x['total_pt']:+.2f}pt ({x['bets']}件)")
    if per:
        lines.append("―― スポーツ別累計 ――")
        lines.extend(per)
    return "\n".join(lines)


# =====================================================================
# 固定時刻方式(MLB)のハンドラ
# =====================================================================
async def _handle_fixed_clock(channel, rt: SportRuntime, now: datetime) -> None:
    # 日跨ぎ窓(例 21:00〜翌01:00)では、深夜0時以降も「窓が始まった日」を today とする。
    # これで0時をまたいでも基準(21:00取得)を作り直さずに使い続ける。
    today = window_session_date(
        now, rt.base_hour, rt.base_minute, rt.end_hour, rt.end_minute
    )
    currently_in = in_monitor_window(
        now, rt.base_hour, rt.base_minute, rt.end_hour, rt.end_minute
    )
    # このスポーツの通知先（NBA等は専用チャンネル、他は通常チャンネル）
    send_ch = _sport_channel(rt.sport_key, channel)

    # --- 日付変更によるリセット ---
    if rt.last_base_date is not None and today != rt.last_base_date:
        print(f"[{now}] {rt.sport_key} 日付変更 → 状態クリア")
        rt.reset_day()

    # --- ウィンドウから抜けた瞬間の通知 ---
    if rt.was_in_window and not currently_in:
        await _send(
            send_ch, rt.label,
            f"⏹ 監視終了 (JST {now.strftime('%H:%M')})\n"
            f"翌日 {rt.base_hour:02d}:{rt.base_minute:02d} に再開",
        )
    rt.was_in_window = currently_in

    if not currently_in:
        return

    # --- 今日の基準がまだロードされていなければ準備 ---
    if rt.last_base_date != today:
        await _prepare_today_base(send_ch, rt, today, now)
        return

    # --- 1分ごとの判定（間引き） ---
    if (
        rt.last_check_time is not None
        and (now - rt.last_check_time).total_seconds() < config.CHECK_INTERVAL_SECONDS
    ):
        return
    rt.last_check_time = now

    games = await asyncio.to_thread(get_games_with_handicap, rt.sport_key)
    paper_msg = None
    with get_session() as s:
        events = evaluate(
            s, games, rt.base_odds_map, rt.state,
            alert_time=now, sport=rt.sport_key, base_points=rt.base_points,
        )
        if _should_snapshot(rt, now):
            saved = save_snapshot_handicap(s, games, now, sport=rt.sport_key)
            rt.last_snapshot_time = now
            print(f"[{now}] {rt.sport_key} スナップショット保存: {saved}行")

        # --- ペーパートレード記録（判定時刻を過ぎたら1日1回） ---
        ch, cm = config.sport_check_time(rt.cfg)
        if rt.paper_recorded_date != today and (now.hour, now.minute) >= (ch, cm):
            n = record_paper_bets(
                s, games, rt.base_odds_map, rt.base_points,
                sport=rt.sport_key, bet_date=today, check_time=now,
            )
            rt.paper_recorded_date = today
            if n:
                paper_msg = (
                    f"📝 ペーパートレード記録 (JST {now.strftime('%H:%M')})\n"
                    f"有利化(縮み≥{config.LEVEL1})したハンデ {n}件を 1pt仮想BET として記録"
                )

    for e in events:
        await _send(send_ch, rt.label, format_event(e, rt.emoji))
    if paper_msg:
        await _send(send_ch, rt.label, paper_msg)

    # 1×2(勝敗オッズ)人気側の監視（サッカーのみ。MLBは h2h_watch=False で即return）
    await _run_h2h_watch(send_ch, rt, now)


async def _prepare_today_base(channel, rt: SportRuntime, today, now) -> None:
    """今日の基準オッズ(ハンデ1.9ライン)をDBに作る(または再起動時に復元する)。"""
    games_for_base = await asyncio.to_thread(get_games_with_handicap, rt.sport_key)

    # API取得が空（ネット瞬断・DNS失敗など）の場合は、今日を「準備済み」にしない。
    # ここで確定させてしまうと空の基準で監視が始まり、Level通知も出ず、やり直しも
    # されない（実際に発生）。last_base_date を更新せず return し、次のtickで再試行する。
    if not games_for_base:
        print(f"[{now}] {rt.sport_key} 基準オッズの取得に失敗(空)。今日は未確定のまま次のtickで再試行する")
        return

    base_created_now = False
    msg_base_saved = None

    with get_session() as s:
        if not has_base_odds_for_date(s, today, sport=rt.sport_key, market="spreads"):
            saved = create_base_odds_handicap(
                s, games_for_base, today, sport=rt.sport_key,
                target_decimal=config.sport_target_odds(rt.cfg),
            )
            base_created_now = True
            if saved == 0:
                print(f"⚠️ [{rt.sport_key}] 試合はあるがハンデ(alternate_spreads)が0件。"
                      f"この競技はハンデ非対応の可能性。基準が空のため検知できません")
            msg_base_saved = (
                f"📌 基準オッズ保存完了 (JST {now.strftime('%H:%M')})\n"
                f"対象: {rt.sport_key} / ハンデ1.9ライン / 24時間以内\n"
                f"監視ウィンドウ: {rt.base_hour:02d}:{rt.base_minute:02d}"
                f" 〜 {rt.end_hour:02d}:{rt.end_minute:02d}\n"
                f"単体通知主軸: {config.PRIMARY_BOOKMAKER}\n"
                f"Steam: 同方向{config.STEAM_MIN_BOOKS}ブック以上 / 2.1倍以下 / 閾値{config.STEAM_THRESHOLD}\n"
                f"基準保存件数: {saved}"
            )
        s.flush()
        hb = load_base_odds_handicap(s, today, sport=rt.sport_key)
        rt.base_odds_map = {k: v["odds"] for k, v in hb.items()}
        rt.base_points = {k: v["point"] for k, v in hb.items()}

    rt.last_base_date = today
    rt.state = MonitorState()
    rt.last_snapshot_time = None
    rt.last_check_time = None

    if base_created_now:
        await _send(channel, rt.label, msg_base_saved)
        await _send(
            channel, rt.label,
            f"👀 監視開始 (JST {rt.base_hour:02d}:{rt.base_minute:02d}〜"
            f"{rt.end_hour:02d}:{rt.end_minute:02d})",
        )
    else:
        await _send(
            channel, rt.label,
            f"🔁 再起動を検知。今日の基準({today}) を復元して監視継続。",
        )


# =====================================================================
# 試合ごと方式(NPB)のハンドラ
# =====================================================================
def _lead_cutoff(rt: SportRuntime) -> tuple[int, int]:
    return (
        rt.cfg.get("lead_minutes", config.NPB_LEAD_MINUTES),
        rt.cfg.get("cutoff_minutes", config.NPB_CUTOFF_MINUTES),
    )


def _pregame_active_and_imminent(
    games: list[dict], now_utc_dt: datetime, lead: int, cutoff: int
) -> tuple[list[dict], bool]:
    """
    games のうち「今まさに監視窓内」の試合一覧と、
    「もうすぐ(NPB_PREPOLL_MINUTES分以内に)窓が開く試合があるか」を返す。
    """
    active: list[dict] = []
    imminent = False
    for g in games:
        cs = g.get("commence_time")
        if not cs:
            continue
        try:
            commence = parse_commence_time(cs)
        except Exception:
            continue
        if in_pregame_window(commence, now_utc_dt, lead_minutes=lead, cutoff_minutes=cutoff):
            active.append(g)
        else:
            window_start = commence - timedelta(minutes=lead)
            prepoll_start = window_start - timedelta(minutes=NPB_PREPOLL_MINUTES)
            if prepoll_start <= now_utc_dt < window_start:
                imminent = True
    return active, imminent


async def _handle_pregame(channel, rt: SportRuntime, now: datetime) -> None:
    today = now.date()
    now_utc_dt = now.astimezone(timezone.utc)
    lead, cutoff = _lead_cutoff(rt)

    # --- 日付変更によるリセット ---
    if rt.last_seen_date is not None and today != rt.last_seen_date:
        print(f"[{now}] {rt.sport_key} 日付変更 → 状態クリア")
        rt.reset_day()
    rt.last_seen_date = today

    # --- 窓を抜けた試合の「監視終了」通知（API不要・毎tick判定）---
    closed = [
        gid
        for gid, info in rt.active_games.items()
        if now_utc_dt > info["commence"] - timedelta(minutes=cutoff)
    ]
    for gid in closed:
        info = rt.active_games.pop(gid)
        await _send(
            channel, rt.label,
            f"⏹ 監視終了（開始{cutoff}分前を経過）\n"
            f"{rt.emoji} {format_game_name_ja(info['name'])}",
        )

    # --- 1) 予定(無料 get_events)を低頻度で更新。窓判定に必要な commence_time を持つ ---
    schedule_due = (
        rt.last_schedule_time is None
        or (now - rt.last_schedule_time).total_seconds() >= NPB_SCHEDULE_REFRESH_SECONDS
    )
    if schedule_due:
        ev = get_events(rt.sport_key)
        if ev:
            rt.cached_games = ev
        rt.last_schedule_time = now

    # --- 2) 予定から「窓内/もうすぐ窓」を判定。近くに無ければ何もしない（無料のまま）---
    active_sched, imminent = _pregame_active_and_imminent(
        rt.cached_games, now_utc_dt, lead, cutoff
    )
    if not (active_sched or imminent):
        return

    # --- 3) 窓が近い → ハンデ階段(有料)を毎分取得して基準保存・判定 ---
    if (
        rt.last_fetch_time is not None
        and (now - rt.last_fetch_time).total_seconds() < config.CHECK_INTERVAL_SECONDS
    ):
        return
    rt.last_fetch_time = now

    games = await asyncio.to_thread(get_games_with_handicap, rt.sport_key)
    if not games:
        return
    active_now, _ = _pregame_active_and_imminent(games, now_utc_dt, lead, cutoff)
    if not active_now:
        return

    with get_session() as s:
        # 窓に入った試合の基準を保存（または再起動時に復元）
        for g in active_now:
            gid = g.get("id") or ""
            if gid and gid not in rt.active_games:
                await _open_npb_game(channel, rt, s, g, lead)

        # 窓内の試合だけで判定
        events = evaluate(
            s, active_now, rt.base_odds_map, rt.state,
            alert_time=now, sport=rt.sport_key, base_points=rt.base_points,
        )
        if _should_snapshot(rt, now):
            saved = save_snapshot_handicap(s, active_now, now, sport=rt.sport_key)
            rt.last_snapshot_time = now
            print(f"[{now}] {rt.sport_key} スナップショット保存: {saved}行")

    for e in events:
        await _send(channel, rt.label, format_event(e, rt.emoji))

    # 1×2(勝敗オッズ)人気側の監視（窓内の試合だけに限定）
    await _run_h2h_watch(
        channel, rt, now,
        allowed_gids={g.get("id") for g in active_now if g.get("id")},
    )


async def _open_npb_game(channel, rt: SportRuntime, session, game: dict, lead: int) -> None:
    """1試合が監視窓に入った瞬間の処理: 基準保存(or復元)＋通知＋登録。"""
    gid = game.get("id") or ""
    away = game.get("away_team", "")
    home = game.get("home_team", "")
    game_name = f"{away} vs {home}"
    commence = parse_commence_time(game["commence_time"])
    base_date = commence.astimezone(config.JST).date()

    existed = has_base_odds_for_game(session, gid, sport=rt.sport_key, market="spreads")
    saved = 0
    if not existed:
        saved = create_base_odds_for_game_handicap(
            session, game, base_date, sport=rt.sport_key,
            target_decimal=config.sport_target_odds(rt.cfg),
        )
        session.flush()
        if saved == 0:
            print(f"⚠️ [{rt.sport_key}] {game_name}: ハンデ(alternate_spreads)が0件。"
                  f"NPBはハンデ非対応の可能性。基準が空のため検知できません")
    # メモリ上の基準マップにこの試合ぶんを取り込む（再起動時もここでDBから復元）
    hb = load_base_odds_handicap(session, base_date, sport=rt.sport_key)
    rt.base_odds_map.update({k: v["odds"] for k, v in hb.items()})
    rt.base_points.update({k: v["point"] for k, v in hb.items()})

    rt.active_games[gid] = {"name": game_name, "commence": commence}

    if not existed:
        await _send(
            channel, rt.label,
            f"👀 監視開始（開始{lead}分前）\n"
            f"{rt.emoji} {format_game_name_ja(game_name)}\n"
            f"📌 基準オッズ保存(ハンデ1.9ライン) {saved}行\n"
            f"単体通知主軸: {config.PRIMARY_BOOKMAKER}\n"
            f"Steam: 同方向{config.STEAM_MIN_BOOKS}ブック以上 / 2.1倍以下 / 閾値 {config.STEAM_THRESHOLD}",
        )
    else:
        await _send(
            channel, rt.label,
            f"🔁 再起動を検知。{format_game_name_ja(game_name)} の監視を継続。",
        )


def _should_snapshot(rt: SportRuntime, now: datetime) -> bool:
    return (
        rt.last_snapshot_time is None
        or (now - rt.last_snapshot_time).total_seconds() >= config.SNAPSHOT_INTERVAL_SECONDS
    )


# =====================================================================
# Discord イベント
# =====================================================================
@client.event
async def on_ready():
    global _startup_sent, _monitor_task
    channel = client.get_channel(config.CHANNEL_ID)
    if channel is None:
        print(f"❌ チャンネルが見つかりません (CHANNEL_ID={config.CHANNEL_ID})")
        print("   .env の CHANNEL_ID と、BOTがそのサーバ/チャンネルに参加しているかを確認してください。")
        return

    print(f"✅ ログイン成功: {client.user}")

    if not _startup_sent:
        _startup_sent = True
        now = now_jst()
        sport_lines = []
        for s in config.SPORTS:
            if s["window"] == config.WINDOW_FIXED_CLOCK:
                bh, bm, eh, em = config.sport_window(s)
                sport_lines.append(
                    f"・{s['label']}: 毎日 {bh:02d}:{bm:02d}〜{eh:02d}:{em:02d} 監視"
                )
            else:
                lead = s.get("lead_minutes", config.NPB_LEAD_MINUTES)
                cutoff = s.get("cutoff_minutes", config.NPB_CUTOFF_MINUTES)
                sport_lines.append(
                    f"・{s['label']}: 各試合 開始{lead}分前〜{cutoff}分前 監視"
                )
        await channel.send(
            "🤖 監視BOT 起動\n"
            f"JST: {now.strftime('%Y-%m-%d %H:%M:%S')}\n"
            + "\n".join(sport_lines)
            + f"\n単体通知主軸: {config.PRIMARY_BOOKMAKER}"
            f"\nSteam: 同方向{config.STEAM_MIN_BOOKS}ブック以上 / 閾値 {config.STEAM_THRESHOLD}"
        )
    # on_ready は再接続のたびに呼ばれる。監視ループ本体は client が閉じない限り
    # 動き続けるので、ここで毎回 create_task するとループが増殖し、通知が多重送信
    # されてしまう（実際に16重送信で送信制限に達した）。
    # そこで「既に動いているループがあるなら起動しない／死んでいたら起動し直す」。
    if _monitor_task is None or _monitor_task.done():
        _monitor_task = asyncio.create_task(monitor_loop(channel))
        print("監視ループを起動しました")
    else:
        print("（再接続を検知。監視ループは稼働中のため新規起動はしない）")


# =====================================================================
# エントリーポイント
# =====================================================================
def run() -> None:
    """BOTを起動する。"""
    if not config.DISCORD_TOKEN or config.DISCORD_TOKEN == "YOUR_DISCORD_TOKEN_HERE":
        raise RuntimeError(
            ".env の DISCORD_TOKEN が未設定です。.env ファイルにあなたのBOTトークンを入れてください。"
        )
    if not config.CHANNEL_ID:
        raise RuntimeError(
            ".env の CHANNEL_ID が未設定 (0) です。通知を流すDiscordチャンネルIDを設定してください。"
        )
    client.run(config.DISCORD_TOKEN)
