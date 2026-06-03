"""
NPB（試合ごと方式）の監視フローを通しでテストする。

discord_bot._handle_pregame に対して、
  - get_session を in-memory DB に差し替え
  - get_current_games を偽データに差し替え
  - channel を「送信メッセージを溜めるだけ」の偽物に差し替え
て、時刻を進めながら次を確認する:

  1. 窓に入ると基準が保存され「監視開始」が通知される
  2. 窓内で Pinnacle が動くと LEVEL 通知が出る
  3. 開始cutoff分前を過ぎると「監視終了」が通知される
  4. 窓に入る前は何もしない
"""

import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta

import pytest
from sqlalchemy import select

from src import config
from src.db.models import BaseOdds
from src.notifier import discord_bot
from tests._factories import make_game, make_bookmaker, make_outcome


# 試合開始 = JST 21:00 (= UTC 12:00) に固定
COMMENCE_UTC = datetime(2026, 5, 31, 12, 0, tzinfo=timezone.utc)
COMMENCE_ISO = "2026-05-31T12:00:00Z"

NPB_CFG = next(s for s in config.SPORTS if s["sport_key"] == "baseball_npb")


class FakeChannel:
    def __init__(self):
        self.messages: list[str] = []

    async def send(self, text):
        self.messages.append(text)


def _game(pinnacle_away_price: int):
    """阪神(away) vs 巨人(home)。Pinnacle と もう1社のオッズを持つ。"""
    return make_game(
        game_id="npb_g1",
        away="Hanshin Tigers",
        home="Yomiuri Giants",
        commence_time_iso=COMMENCE_ISO,
        bookmakers=[
            make_bookmaker("Pinnacle", [
                make_outcome("Hanshin Tigers", pinnacle_away_price),
                make_outcome("Yomiuri Giants", -120),
            ]),
            make_bookmaker("William Hill", [
                make_outcome("Hanshin Tigers", 130),
                make_outcome("Yomiuri Giants", -120),
            ]),
        ],
    )


def _run(coro):
    asyncio.run(coro)


def _patch(monkeypatch, session, games_holder):
    @contextmanager
    def fake_get_session():
        # テスト中は同じ session を使い回す（閉じない）
        yield session
        session.commit()

    monkeypatch.setattr(discord_bot, "get_session", fake_get_session)
    monkeypatch.setattr(
        discord_bot, "get_current_games", lambda sport_key=None: games_holder["games"]
    )


def test_pregame_full_flow(session, monkeypatch):
    games_holder = {"games": [_game(pinnacle_away_price=130)]}  # +130 -> 2.30
    _patch(monkeypatch, session, games_holder)

    rt = discord_bot.SportRuntime(NPB_CFG)
    ch = FakeChannel()

    # --- (1) 窓のはるか前(91分前)：何も起きない ---
    t_before = (COMMENCE_UTC - timedelta(minutes=91)).astimezone(config.JST)
    _run(discord_bot._handle_pregame(ch, rt, t_before))
    assert rt.active_games == {}
    assert session.execute(select(BaseOdds)).first() is None
    assert ch.messages == []

    # --- (2) 窓入り(60分前)：基準保存＋「監視開始」 ---
    t_in = (COMMENCE_UTC - timedelta(minutes=60)).astimezone(config.JST)
    _run(discord_bot._handle_pregame(ch, rt, t_in))

    assert "npb_g1" in rt.active_games
    rows = session.execute(select(BaseOdds)).scalars().all()
    assert len(rows) == 4  # 2ブック × 2アウトカム
    assert all(r.sport == "baseball_npb" for r in rows)
    start_msgs = [m for m in ch.messages if "監視開始" in m]
    assert len(start_msgs) == 1
    assert NPB_CFG["label"] in start_msgs[0]
    # 基準マップに取り込まれている
    assert rt.base_odds_map[("npb_g1", "Pinnacle", "Hanshin Tigers")] == 2.30

    # --- (3) 窓内で Pinnacle が +0.15 動く(+145 -> 2.45) → LEVEL5 ---
    games_holder["games"] = [_game(pinnacle_away_price=145)]
    t_move = (COMMENCE_UTC - timedelta(minutes=58)).astimezone(config.JST)
    _run(discord_bot._handle_pregame(ch, rt, t_move))

    level_msgs = [m for m in ch.messages if "LEVEL5" in m]
    assert len(level_msgs) == 1
    assert "Hanshin Tigers" in level_msgs[0] or "阪神" in level_msgs[0]

    # --- (4) cutoff(5分前)を過ぎる(4分前) → 「監視終了」 ---
    t_after = (COMMENCE_UTC - timedelta(minutes=4)).astimezone(config.JST)
    _run(discord_bot._handle_pregame(ch, rt, t_after))

    assert "npb_g1" not in rt.active_games
    end_msgs = [m for m in ch.messages if "監視終了" in m]
    assert len(end_msgs) == 1


def test_pregame_no_double_open(session, monkeypatch):
    """同じ試合で『監視開始』が二重に出ないこと。"""
    games_holder = {"games": [_game(pinnacle_away_price=130)]}
    _patch(monkeypatch, session, games_holder)

    rt = discord_bot.SportRuntime(NPB_CFG)
    ch = FakeChannel()

    t1 = (COMMENCE_UTC - timedelta(minutes=60)).astimezone(config.JST)
    _run(discord_bot._handle_pregame(ch, rt, t1))
    t2 = (COMMENCE_UTC - timedelta(minutes=58)).astimezone(config.JST)
    _run(discord_bot._handle_pregame(ch, rt, t2))

    start_msgs = [m for m in ch.messages if "監視開始" in m]
    assert len(start_msgs) == 1
    # 基準も1セット(4行)のまま
    assert len(session.execute(select(BaseOdds)).scalars().all()) == 4
