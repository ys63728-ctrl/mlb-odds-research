"""
データベースへの接続を管理する場所。

- engine   : データベースへの「接続口」
- Session  : データを読み書きするときの「作業セッション」
- init_db(): 表を実際に作る（まだ無ければ作成する）
"""

from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src import config
from src.db.models import Base

# データベースファイルの置き場所 data/ が無ければ作る
config.DATA_DIR.mkdir(parents=True, exist_ok=True)


def _resolve_db_url(url: str) -> str:
    """
    SQLite の相対パス指定 (sqlite:///./xxx) を、プロジェクトルート基準の
    絶対パスに変換する。どこから python を起動しても同じDBファイルを指す。
    """
    if url.startswith("sqlite:///./"):
        rel = url[len("sqlite:///./") :]
        abs_path = (config.PROJECT_ROOT / rel).resolve()
        return f"sqlite:///{abs_path.as_posix()}"
    return url


# 接続口（engine）を作る。
# SQLite を複数スレッドから使えるように check_same_thread=False を指定。
connect_args = {}
if config.DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(_resolve_db_url(config.DATABASE_URL), connect_args=connect_args)

# 作業セッションを作るための「型」
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    """models.py で定義した表をすべて作成する（既にあるものはそのまま）。"""
    Base.metadata.create_all(engine)


@contextmanager
def get_session():
    """
    データの読み書きに使うセッションを安全に開閉するための仕組み。

    使い方:
        with get_session() as session:
            session.add(...)
    エラーが起きたら自動でロールバック（取り消し）、最後に必ず閉じる。
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
