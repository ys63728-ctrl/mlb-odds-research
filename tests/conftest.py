"""共有 pytest fixture（テストで使う部品）。"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base


@pytest.fixture
def session():
    """
    テストごとにまっさらな in-memory SQLite を用意する。
    1テスト終了後にエンジンが破棄されるので、テスト同士はデータが干渉しない。
    """
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


@pytest.fixture
def fixed_now_utc():
    """テストで使う固定の「今」: 2026-05-28 12:00 UTC（= JST 21:00 と同じ瞬間）。"""
    return datetime(2026, 5, 28, 12, 0, 0, tzinfo=timezone.utc)
