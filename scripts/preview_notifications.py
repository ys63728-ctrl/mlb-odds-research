"""
Discord通知のサンプルをプレビューする。
日本語化したチーム名で、実際に飛ぶメッセージを確認できる。

実行: python scripts/preview_notifications.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.monitor.level_check import NotificationEvent
from src.notifier.discord_bot import format_event


SAMPLES = [
    # Pinnacle Level3（ドジャース側に大きく下落）
    NotificationEvent(
        kind="pinnacle_level",
        game_name="Los Angeles Dodgers vs San Francisco Giants",
        team="Los Angeles Dodgers",
        level=3,
        bookmaker="Pinnacle",
        base_odds=1.65,
        current_odds=1.50,
        move=-0.15,
    ),
    # Pinnacle Level1（ヤンキース側に上昇）
    NotificationEvent(
        kind="pinnacle_level",
        game_name="New York Yankees vs Boston Red Sox",
        team="New York Yankees",
        level=1,
        bookmaker="Pinnacle",
        base_odds=1.80,
        current_odds=1.86,
        move=0.06,
    ),
    # Pinnacle 解除
    NotificationEvent(
        kind="pinnacle_clear",
        game_name="New York Yankees vs Boston Red Sox",
        team="New York Yankees",
        level=0,
        bookmaker="Pinnacle",
        base_odds=1.80,
        current_odds=1.80,
        move=0.00,
    ),
    # Steam Move（同方向上昇 3ブック）
    NotificationEvent(
        kind="steam_move",
        game_name="Los Angeles Dodgers vs San Francisco Giants",
        team="San Francisco Giants",
        direction="up",
        books=[
            {"bookmaker": "Pinnacle",     "base": 3.20, "current": 3.30, "move": 0.10},
            {"bookmaker": "BetOnline.ag", "base": 3.25, "current": 3.32, "move": 0.07},
            {"bookmaker": "LowVig.ag",    "base": 3.22, "current": 3.28, "move": 0.06},
        ],
    ),
    # Steam 解除
    NotificationEvent(
        kind="steam_clear",
        game_name="Los Angeles Dodgers vs San Francisco Giants",
        team="San Francisco Giants",
        direction="up",
    ),
]


if __name__ == "__main__":
    for i, ev in enumerate(SAMPLES, start=1):
        print("─" * 56)
        print(f"サンプル {i}: {ev.kind}")
        print("─" * 56)
        print(format_event(ev))
        print()
