"""
NPB（試合ごと方式）の監視フローを、ハンデ(1.9ライン)基準で通しテストする。

discord_bot._handle_pregame に対して、
  - get_session を in-memory DB に差し替え
  - get_games_with_handicap を偽のハンデ階段データに差し替え
  - channel を「送信メッセージを溜めるだけ」の偽物に差し替え
て、時刻を進めながら次を確認する:

  1. 窓に入るとハンデ1.9ライン基準が保存され「監視開始」が通知される
  2. 窓内で Pinnacle の基準point価格が動くと LEVEL 通知が出る
  3. 開始cutoff分前を過ぎると「監視終了」が通知される
  4. 窓に入る前は何もしない
"""

import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta

from sqlalchemy import select

from src import config
from src.db.models import BaseOdds
from src.notifier import discord_bot


COMMENCE_UTC = datetime(2026, 5, 31, 12, 0, tzinfo=timezone.utc)
COMMENCE_ISO = "2026-05-31T12:00:00Z"
NPB_CFG = next(s for s in config.SPORTS if s["sport_key"] == "baseball_npb")


class FakeChannel:
    def __init__(self):
        self.messages: list[str] = []

    async def send(self, text):
        self.messages.append(text)


def _game(hanshin_plus15_price: int):
    """阪神(away) vs 巨人(home)。Pinnacle の alternate_spreads 階段を持つ。"""
    return {
        "id": "npb_g1",
        "away_team": "Hanshin Tigers",
        "home_team": "Yomiuri Giants",
        "commence_time": COMMENCE_ISO,
        "bookmakers": [{
            "title": "Pinnacle",
            "markets": [{"key": "alternate_spreads", "outcomes": [
                {"name": "Hanshin Tigers", "point": 1.5, "price": hanshin_plus15_price},
                {"name": "Hanshin Tigers", "point": 2.0, "price": -150},
                {"name": "Yomiuri Giants", "point": -1.5, "price": -102},
            ]}],
        }],
    }


def _run(coro):
    asyncio.run(coro)


def _patch(monkeypatch, session, games_holder):
    @contextmanager
    def fake_get_session():
        yield session
        session.commit()

    monkeypatch.setattr(discord_bot, "get_session", fake_get_session)
    monkeypatch.setattr(
        discord_bot, "get_games_with_handicap",
        lambda sport_key=None: games_holder["games"],
    )
    # 予定(get_events)も同じ試合を返す（commence_time だけ使われる）
    monkeypatch.setattr(
        discord_bot, "get_events",
        lambda sport_key=None: games_holder["games"],
    )


def test_pregame_handicap_full_flow(session, monkeypatch):
    # 基準: 阪神 +1.5 @ 1.91 (american -110)
    games_holder = {"games": [_game(-110)]}
    _patch(monkeypatch, session, games_holder)

    rt = discord_bot.SportRuntime(NPB_CFG)
    ch = FakeChannel()

    # --- (1) 窓のはるか前(91分前)：何も起きない ---
    t_before = (COMMENCE_UTC - timedelta(minutes=91)).astimezone(config.JST)
    _run(discord_bot._handle_pregame(ch, rt, t_before))
    assert rt.active_games == {}
    assert session.execute(select(BaseOdds)).first() is None
    assert ch.messages == []

    # --- (2) 窓入り(60分前)：ハンデ基準保存＋「監視開始」 ---
    t_in = (COMMENCE_UTC - timedelta(minutes=60)).astimezone(config.JST)
    _run(discord_bot._handle_pregame(ch, rt, t_in))

    assert "npb_g1" in rt.active_games
    rows = session.execute(select(BaseOdds)).scalars().all()
    assert len(rows) == 2  # 阪神(+1.5) と 巨人(-1.5) の1.9ライン
    assert all(r.market == "spreads" for r in rows)
    assert all(r.point is not None for r in rows)
    # 阪神の基準: point +1.5 / 価格1.91
    assert rt.base_points[("npb_g1", "Pinnacle", "Hanshin Tigers")] == 1.5
    assert rt.base_odds_map[("npb_g1", "Pinnacle", "Hanshin Tigers")] == 1.91
    assert any("監視開始" in m for m in ch.messages)

    # --- (3) 窓内で 阪神+1.5 が 1.91→1.80 に下落(american -125, -0.11) → LEVEL3 ---
    games_holder["games"] = [_game(-125)]
    t_move = (COMMENCE_UTC - timedelta(minutes=58)).astimezone(config.JST)
    _run(discord_bot._handle_pregame(ch, rt, t_move))

    level_msgs = [m for m in ch.messages if "LEVEL3" in m]
    assert len(level_msgs) == 1
    assert "ハンデ +1.5" in level_msgs[0]

    # --- (4) cutoff(5分前)を過ぎる(4分前) → 「監視終了」 ---
    t_after = (COMMENCE_UTC - timedelta(minutes=4)).astimezone(config.JST)
    _run(discord_bot._handle_pregame(ch, rt, t_after))

    assert "npb_g1" not in rt.active_games
    assert any("監視終了" in m for m in ch.messages)


def test_pregame_handicap_no_double_open(session, monkeypatch):
    """同じ試合で『監視開始』が二重に出ないこと。"""
    games_holder = {"games": [_game(-110)]}
    _patch(monkeypatch, session, games_holder)

    rt = discord_bot.SportRuntime(NPB_CFG)
    ch = FakeChannel()

    t1 = (COMMENCE_UTC - timedelta(minutes=60)).astimezone(config.JST)
    _run(discord_bot._handle_pregame(ch, rt, t1))
    t2 = (COMMENCE_UTC - timedelta(minutes=58)).astimezone(config.JST)
    _run(discord_bot._handle_pregame(ch, rt, t2))

    start_msgs = [m for m in ch.messages if "監視開始" in m]
    assert len(start_msgs) == 1
    assert len(session.execute(select(BaseOdds)).scalars().all()) == 2
