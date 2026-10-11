"""team_names（日本語変換）のテスト。"""

from src.utils.team_names import to_ja, format_game_name_ja


def test_soccer_club_to_katakana():
    assert to_ja("AC Milan") == "ミラン"
    assert to_ja("Manchester City") == "マンチェスター・シティ"
    assert to_ja("Paris Saint Germain") == "パリSG"
    assert to_ja("1. FC Köln") == "ケルン"


def test_soccer_national_to_katakana():
    assert to_ja("Germany") == "ドイツ"
    assert to_ja("Netherlands") == "オランダ"


def test_mlb_still_works():
    assert to_ja("Los Angeles Dodgers") == "ドジャース"


def test_unknown_falls_back_to_english():
    assert to_ja("Nonexistent FC") == "Nonexistent FC"


def test_format_game_name_ja_soccer():
    assert format_game_name_ja("AC Milan vs Sassuolo") == "ミラン vs サッスオーロ"
