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

from src import config
from src.api.odds_api import get_current_games
from src.db.database import get_session
from src.monitor.base_odds import (
    create_base_odds,
    create_base_odds_for_game,
    has_base_odds_for_date,
    has_base_odds_for_game,
    load_base_odds_map,
)
from src.monitor.level_check import MonitorState, NotificationEvent, evaluate
from src.monitor.snapshot import save_snapshot
from src.utils.team_names import format_game_name_ja, to_ja
from src.utils.time_utils import (
    in_monitor_window,
    in_pregame_window,
    now_jst,
    parse_commence_time,
)


# =====================================================================
# Discord クライアント＆グローバル状態
# =====================================================================
intents = discord.Intents.default()
client = discord.Client(intents=intents)

_startup_sent = False
_monitor_task: asyncio.Task | None = None  # 稼働中の監視ループ。二重起動を防ぐ

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
def format_pinnacle_level(e: NotificationEvent) -> str:
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
    return (
        f"{badge}\n"
        f"⚾ {format_game_name_ja(e.game_name)}\n"
        f"🎯 {to_ja(e.team)}\n"
        f"📚 {e.bookmaker}\n\n"
        f"基準: {e.base_odds:.2f}\n"
        f"現在: {e.current_odds:.2f}\n"
        f"変動: {e.move:+.2f}\n\n"
        f"{direction}"
    )


def format_pinnacle_clear(e: NotificationEvent) -> str:
    return (
        f"⚪ LEVEL解除\n"
        f"⚾ {format_game_name_ja(e.game_name)}\n"
        f"🎯 {to_ja(e.team)}\n"
        f"📚 {e.bookmaker}\n\n"
        f"基準: {e.base_odds:.2f}\n"
        f"現在: {e.current_odds:.2f}\n"
        f"変動: {e.move:+.2f}"
    )


def format_steam_move(e: NotificationEvent) -> str:
    arrow = "📈 上昇" if e.direction == "up" else "📉 低下"
    lines = [
        f"⚡ Steam Move 検知（{arrow} / {len(e.books)}ブック同方向）",
        f"⚾ {format_game_name_ja(e.game_name)}",
        f"🎯 {to_ja(e.team)}",
        "",
        "参加ブック:",
    ]
    for b in e.books:
        lines.append(
            f"  - {b['bookmaker']}: {b['base']:.2f} → {b['current']:.2f} ({b['move']:+.2f})"
        )
    return "\n".join(lines)


def format_steam_clear(e: NotificationEvent) -> str:
    arrow = "上昇" if e.direction == "up" else "低下"
    return (
        f"⚪ Steam Move 解除（直前: {arrow}）\n"
        f"⚾ {format_game_name_ja(e.game_name)}\n"
        f"🎯 {to_ja(e.team)}\n"
        f"（同方向ブック数が {config.STEAM_MIN_BOOKS} 未満になった）"
    )


_FORMATTERS = {
    "pinnacle_level": format_pinnacle_level,
    "pinnacle_clear": format_pinnacle_clear,
    "steam_move": format_steam_move,
    "steam_clear": format_steam_clear,
}


def format_event(e: NotificationEvent) -> str:
    return _FORMATTERS[e.kind](e)


async def _send(channel, label: str, text: str) -> None:
    """先頭にスポーツのラベルを付けて送信する。送信失敗はログのみ。"""
    try:
        await channel.send(f"{label}\n{text}")
    except Exception as send_err:
        print(f"[discord] 通知送信エラー: {send_err}")


# =====================================================================
# スポーツごとの実行時状態
# =====================================================================
class SportRuntime:
    """1スポーツ分の監視状態をまとめて持つ入れ物。"""

    def __init__(self, sport_cfg: dict):
        self.cfg = sport_cfg
        self.sport_key = sport_cfg["sport_key"]
        self.label = sport_cfg["label"]
        self.window = sport_cfg["window"]

        self.state = MonitorState()
        self.base_odds_map: dict[tuple[str, str, str], float] = {}
        self.last_check_time: datetime | None = None
        self.last_snapshot_time: datetime | None = None

        # --- 固定時刻方式(MLB)用 ---
        self.last_base_date = None
        self.was_in_window = False

        # --- 試合ごと方式(NPB)用 ---
        self.cached_games: list[dict] = []          # 直近に取得した試合一覧
        self.last_fetch_time: datetime | None = None
        # game_id -> {"name": 試合名, "commence": 開始UTC}
        self.active_games: dict[str, dict] = {}
        self.last_seen_date = None

    def reset_day(self) -> None:
        """日付が変わったときに当日ぶんの状態をまっさらにする。"""
        self.state = MonitorState()
        self.base_odds_map = {}
        self.last_check_time = None
        self.last_snapshot_time = None
        self.last_base_date = None
        self.active_games = {}


# =====================================================================
# 監視ループ（全スポーツを1つのループで回す）
# =====================================================================
async def monitor_loop(channel: discord.abc.Messageable) -> None:
    runtimes = [SportRuntime(s) for s in config.SPORTS]

    while not client.is_closed():
        now = now_jst()
        for rt in runtimes:
            try:
                if rt.window == config.WINDOW_FIXED_CLOCK:
                    await _handle_fixed_clock(channel, rt, now)
                elif rt.window == config.WINDOW_PREGAME:
                    await _handle_pregame(channel, rt, now)
            except Exception as e:
                print(f"[monitor_loop:{rt.sport_key}] エラー: {e}")
                traceback.print_exc()
        await asyncio.sleep(TICK_SECONDS)


# =====================================================================
# 固定時刻方式(MLB)のハンドラ
# =====================================================================
async def _handle_fixed_clock(channel, rt: SportRuntime, now: datetime) -> None:
    today = now.date()
    currently_in = in_monitor_window(now)

    # --- 日付変更によるリセット ---
    if rt.last_base_date is not None and today != rt.last_base_date:
        print(f"[{now}] {rt.sport_key} 日付変更 → 状態クリア")
        rt.reset_day()

    # --- ウィンドウから抜けた瞬間の通知 ---
    if rt.was_in_window and not currently_in:
        await _send(
            channel, rt.label,
            f"⏹ 監視終了 (JST {now.strftime('%H:%M')})\n"
            f"翌日 {config.BASE_HOUR:02d}:{config.BASE_MINUTE:02d} に再開",
        )
    rt.was_in_window = currently_in

    if not currently_in:
        return

    # --- 今日の基準がまだロードされていなければ準備 ---
    if rt.last_base_date != today:
        await _prepare_today_base(channel, rt, today, now)
        return

    # --- 1分ごとの判定（間引き） ---
    if (
        rt.last_check_time is not None
        and (now - rt.last_check_time).total_seconds() < config.CHECK_INTERVAL_SECONDS
    ):
        return
    rt.last_check_time = now

    games = get_current_games(rt.sport_key)
    with get_session() as s:
        events = evaluate(
            s, games, rt.base_odds_map, rt.state, alert_time=now, sport=rt.sport_key
        )
        if _should_snapshot(rt, now):
            saved = save_snapshot(s, games, now, sport=rt.sport_key)
            rt.last_snapshot_time = now
            print(f"[{now}] {rt.sport_key} スナップショット保存: {saved}行")

    for e in events:
        await _send(channel, rt.label, format_event(e))


async def _prepare_today_base(channel, rt: SportRuntime, today, now) -> None:
    """今日の基準オッズをDBに作る(または再起動時に復元する)。"""
    games_for_base = get_current_games(rt.sport_key)
    base_created_now = False
    msg_base_saved = None

    with get_session() as s:
        if not has_base_odds_for_date(s, today, sport=rt.sport_key):
            saved = create_base_odds(s, games_for_base, today, sport=rt.sport_key)
            base_created_now = True
            msg_base_saved = (
                f"📌 基準オッズ保存完了 (JST {now.strftime('%H:%M')})\n"
                f"対象: {rt.sport_key} / 24時間以内\n"
                f"監視ウィンドウ: {config.BASE_HOUR:02d}:{config.BASE_MINUTE:02d}"
                f" 〜 {config.END_HOUR:02d}:{config.END_MINUTE:02d}\n"
                f"単体通知主軸: {config.PRIMARY_BOOKMAKER}\n"
                f"Steam: {config.STEAM_THRESHOLD:+}/{config.STEAM_MIN_BOOKS}ブック同方向\n"
                f"全ブック保存件数: {saved}"
            )
        s.flush()
        rt.base_odds_map = load_base_odds_map(s, today, sport=rt.sport_key)

    rt.last_base_date = today
    rt.state = MonitorState()
    rt.last_snapshot_time = None
    rt.last_check_time = None

    if base_created_now:
        await _send(channel, rt.label, msg_base_saved)
        await _send(
            channel, rt.label,
            f"👀 監視開始 (JST {config.BASE_HOUR:02d}:{config.BASE_MINUTE:02d}〜"
            f"{config.END_HOUR:02d}:{config.END_MINUTE:02d})",
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
            f"⚾ {format_game_name_ja(info['name'])}",
        )

    # --- ポーリング頻度を決める（窓が近い試合がある時だけ毎分）---
    active_cached, imminent = _pregame_active_and_imminent(
        rt.cached_games, now_utc_dt, lead, cutoff
    )
    need_fast = bool(active_cached) or imminent
    interval = config.CHECK_INTERVAL_SECONDS if need_fast else NPB_SCHEDULE_REFRESH_SECONDS
    should_fetch = (
        rt.last_fetch_time is None
        or (now - rt.last_fetch_time).total_seconds() >= interval
    )
    if not should_fetch:
        return

    # --- フェッチ（失敗時=空は既存の予定を保持して次回再試行）---
    games = get_current_games(rt.sport_key)
    rt.last_fetch_time = now
    if games:
        rt.cached_games = games

    active_now, _ = _pregame_active_and_imminent(
        rt.cached_games, now_utc_dt, lead, cutoff
    )
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
            s, active_now, rt.base_odds_map, rt.state, alert_time=now, sport=rt.sport_key
        )
        if _should_snapshot(rt, now):
            saved = save_snapshot(s, active_now, now, sport=rt.sport_key)
            rt.last_snapshot_time = now
            print(f"[{now}] {rt.sport_key} スナップショット保存: {saved}行")

    for e in events:
        await _send(channel, rt.label, format_event(e))


async def _open_npb_game(channel, rt: SportRuntime, session, game: dict, lead: int) -> None:
    """1試合が監視窓に入った瞬間の処理: 基準保存(or復元)＋通知＋登録。"""
    gid = game.get("id") or ""
    away = game.get("away_team", "")
    home = game.get("home_team", "")
    game_name = f"{away} vs {home}"
    commence = parse_commence_time(game["commence_time"])
    base_date = commence.astimezone(config.JST).date()

    existed = has_base_odds_for_game(session, gid, sport=rt.sport_key)
    if not existed:
        saved = create_base_odds_for_game(session, game, base_date, sport=rt.sport_key)
        session.flush()
    # メモリ上の基準マップにこの試合ぶんを取り込む（再起動時もここでDBから復元）
    rt.base_odds_map.update(load_base_odds_map(session, base_date, sport=rt.sport_key))

    rt.active_games[gid] = {"name": game_name, "commence": commence}

    if not existed:
        await _send(
            channel, rt.label,
            f"👀 監視開始（開始{lead}分前）\n"
            f"⚾ {format_game_name_ja(game_name)}\n"
            f"📌 基準オッズ保存・全ブック {saved}行\n"
            f"単体通知主軸: {config.PRIMARY_BOOKMAKER}\n"
            f"Steam: 同方向{config.STEAM_MIN_BOOKS}ブック以上 / 閾値 {config.STEAM_THRESHOLD}",
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
                sport_lines.append(
                    f"・{s['label']}: 毎日 {config.BASE_HOUR:02d}:{config.BASE_MINUTE:02d}"
                    f"〜{config.END_HOUR:02d}:{config.END_MINUTE:02d} 監視"
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
