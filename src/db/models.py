"""
データベースの「表（テーブル）」の設計図。

各クラス = 1つの表。
クラスの中の各行 = 表の「列（カラム）」。
SQLAlchemy という道具を使い、Pythonのクラスとして表を定義しています。
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import String, Integer, Numeric, DateTime, Date
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """すべての表の共通の親。SQLAlchemyのお約束。"""
    pass


class OddsSnapshot(Base):
    """5分ごとに撮る、全オッズの「写真」。一番たくさん貯まる表。"""

    __tablename__ = "odds_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    sport: Mapped[str] = mapped_column(String(50), index=True)        # 競技（baseball_mlb 等）
    snapshot_time: Mapped[datetime] = mapped_column(DateTime, index=True)  # 撮影時刻(JST)
    game_id: Mapped[str] = mapped_column(String(64), index=True)      # The Odds APIの試合ID
    game_name: Mapped[str] = mapped_column(String(120))               # "Away vs Home"
    away_team: Mapped[str] = mapped_column(String(80))
    home_team: Mapped[str] = mapped_column(String(80))
    commence_time: Mapped[datetime] = mapped_column(DateTime)         # 試合開始(UTC)
    bookmaker: Mapped[str] = mapped_column(String(60), index=True)    # ブック名
    market: Mapped[str] = mapped_column(String(20))                   # 'h2h' 等
    team: Mapped[str] = mapped_column(String(80))                     # どのチーム/結果のオッズか
    odds_decimal: Mapped[Decimal] = mapped_column(Numeric(5, 2))      # デシマルオッズ
    odds_american: Mapped[int] = mapped_column(Integer)               # アメリカン形式
    point: Mapped[Decimal | None] = mapped_column(Numeric(4, 1), nullable=True)  # ハンデ/トータル


class BaseOdds(Base):
    """毎日 JST21:00 に保存する「基準オッズ」。1日1セット。"""

    __tablename__ = "base_odds"

    id: Mapped[int] = mapped_column(primary_key=True)
    sport: Mapped[str] = mapped_column(String(50), index=True)
    base_date: Mapped[date] = mapped_column(Date, index=True)         # 基準を取ったJST日付
    game_id: Mapped[str] = mapped_column(String(64), index=True)
    game_name: Mapped[str] = mapped_column(String(120))
    bookmaker: Mapped[str] = mapped_column(String(60))
    market: Mapped[str] = mapped_column(String(20))
    team: Mapped[str] = mapped_column(String(80))
    base_odds_decimal: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    commence_time: Mapped[datetime] = mapped_column(DateTime)


class GameResult(Base):
    """試合結果（勝敗・スコア）。MLB Stats API から取得して保存。"""

    __tablename__ = "game_results"

    game_id: Mapped[str] = mapped_column(String(64), primary_key=True)  # Odds APIのIDに対応
    sport: Mapped[str] = mapped_column(String(50), index=True)
    mlb_game_pk: Mapped[int | None] = mapped_column(Integer, nullable=True)  # MLB公式ID
    home_team: Mapped[str] = mapped_column(String(80))
    away_team: Mapped[str] = mapped_column(String(80))
    home_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    away_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    winner: Mapped[str | None] = mapped_column(String(10), nullable=True)    # 'home' / 'away'
    commence_time: Mapped[datetime] = mapped_column(DateTime)
    final_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Alert(Base):
    """通知を出した履歴。あとで「いつ何を知らせたか」を振り返るため。"""

    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    sport: Mapped[str] = mapped_column(String(50), index=True)
    alert_time: Mapped[datetime] = mapped_column(DateTime, index=True)
    alert_type: Mapped[str] = mapped_column(String(20))   # 'level1'/'level2'/'level3'/'level_clear'
    game_id: Mapped[str] = mapped_column(String(64), index=True)
    bookmaker: Mapped[str] = mapped_column(String(60))
    team: Mapped[str] = mapped_column(String(80))
    base_odds: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    current_odds: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    move: Mapped[Decimal] = mapped_column(Numeric(4, 2))
