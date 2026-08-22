"""
MLB Odds Research BOT のエントリーポイント。

実行方法:
    python scripts/run_bot.py

事前準備:
    1. プロジェクトルートで `pip install -r requirements.txt`
    2. `.env` に DISCORD_TOKEN / CHANNEL_ID / ODDS_API_KEY を設定
    3. BOTを通知先のDiscordサーバ＆チャンネルに参加させておく
"""

import os
import socket
import sys
from pathlib import Path

# 多重起動防止用に握る localhost ポート（他用途と被りにくい高番号）
_LOCK_PORT = 47591
_lock_socket = None  # プロセス存続中ポートを握り続けるため参照を保持する


def _acquire_single_instance_lock() -> None:
    """
    同時に複数のBOTが起動して通知が二重送信されるのを防ぐ。

    localhost の固定ポートを握り、既に握られていたら「別のBOTが稼働中」とみなして
    このプロセスは静かに終了する。プロセスが死ねば OS がポートを解放するので、
    自動再起動のときは問題なく握り直せる（古いロックが残る心配がない）。
    """
    global _lock_socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", _LOCK_PORT))
    except OSError:
        print("⚠ 既に別のBOTが稼働中です。多重起動(通知の二重送信)を防ぐため、この起動は終了します。")
        sys.exit(0)
    _lock_socket = s

# Windows の日本語環境では画面出力が cp932 になり、絵文字(✅など)を含む
# print がエラー(UnicodeEncodeError)で落ちる。出力を UTF-8 に切り替えて防ぐ。
for _stream in (sys.stdout, sys.stderr):
    try:
        # line_buffering=True: バックグラウンド実行でもログが1行ごとに出るようにする
        _stream.reconfigure(encoding="utf-8", line_buffering=True)
    except (AttributeError, ValueError):
        pass

# このスクリプトを scripts/ から実行しても src を import できるよう、
# プロジェクトルートを sys.path に追加する。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.db.database import init_db  # noqa: E402
from src.notifier.discord_bot import run  # noqa: E402


if __name__ == "__main__":
    _acquire_single_instance_lock()  # 多重起動を防ぐ（先頭で確認）
    init_db()  # DBの表がまだ無ければここで作る（paper_bets もここで作成される）

    # 初回だけ環境変数 BACKFILL_PAPER_BETS=1 で過去ぶんの台帳を生成する。
    # 冪等なので複数回でも安全だが、済んだら環境変数を外してよい。
    if os.getenv("BACKFILL_PAPER_BETS") == "1":
        try:
            from src.monitor.paper_backfill import run_backfill
            print("[backfill] " + run_backfill())
        except Exception as e:
            print(f"[backfill] エラー: {e}")

    run()
