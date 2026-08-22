"""settle.py（ハンデ・カバー決済）のテスト。"""

from src.monitor.settle import settle_handicap


def S(team_is_home, hs, aw, point, entry=1.92):
    return settle_handicap(
        team_is_home=team_is_home, home_score=hs, away_score=aw,
        point=point, entry_odds=entry,
    )


# ---------- 整数・ハーフライン ----------
def test_half_line_favorite_covers():
    # ホームが -1.5、2点差勝ち(3-1) → カバー勝ち
    assert S(True, 3, 1, -1.5) == ("win", 0.92)


def test_half_line_favorite_wins_by_one_is_loss():
    # -1.5 で1点差勝ち(2-1) → ハンデ負け（ユーザーの例）
    assert S(True, 2, 1, -1.5) == ("lose", -1.0)


def test_whole_line_push_on_exact_margin():
    # -1.0 でちょうど1点差勝ち(2-1) → adj=0 → push
    assert S(True, 2, 1, -1.0) == ("push", 0.0)


def test_whole_line_favorite_win_by_two():
    assert S(True, 3, 1, -1.0) == ("win", 0.92)


def test_underdog_plus_line_wins():
    # アウェイが +1.5、1点差負け(home2-away1→away視点 -1) adj=-1+1.5=0.5>0 勝ち
    assert S(False, 2, 1, 1.5) == ("win", 0.92)


def test_pk_line_zero_draw_is_push():
    # point 0（引き分けハンデ）で同点 → push
    assert S(True, 1, 1, 0.0) == ("push", 0.0)


# ---------- クォーターライン ----------
def test_quarter_minus_025_draw_is_half_lose():
    # -0.25 = 半分0.0 / 半分-0.5。同点(1-1): 0.0はpush, -0.5は負け → half_lose(-0.5)
    assert S(True, 1, 1, -0.25) == ("half_lose", -0.5)


def test_quarter_minus_025_win_is_full_win():
    # -0.25 で勝ち(2-1): 両方勝ち → win(0.92)
    assert S(True, 2, 1, -0.25) == ("win", 0.92)


def test_quarter_minus_075_win_by_one_is_half_win():
    # -0.75 = 半分-0.5 / 半分-1.0。1点差勝ち(2-1): -0.5勝ち, -1.0push → half_win(+0.46)
    assert S(True, 2, 1, -0.75) == ("half_win", 0.46)


def test_quarter_minus_075_win_by_two_full_win():
    assert S(True, 3, 1, -0.75) == ("win", 0.92)


def test_quarter_plus_025_draw_is_half_win():
    # +0.25 = 半分0.0 / 半分+0.5。同点(1-1): 0.0 push, +0.5 勝ち → half_win(+0.46)
    assert S(True, 1, 1, 0.25) == ("half_win", 0.46)


def test_entry_odds_reflected_in_payout():
    # 倍率2.10で勝ち → +1.10
    assert S(True, 3, 1, -1.5, entry=2.10) == ("win", 1.1)
