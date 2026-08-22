"""
ペーパートレード台帳(paper_bets)の初回バックフィルを手動実行するCLI。

実行(Railwayのデータがある環境で):
    python scripts/backfill_paper_bets.py

本体ロジックは src/monitor/paper_backfill.py。run_bot からは環境変数
BACKFILL_PAPER_BETS=1 で起動時に1回だけ走らせられる（冪等なので複数回でも安全）。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.monitor.paper_backfill import run_backfill  # noqa: E402


if __name__ == "__main__":
    print(run_backfill())
