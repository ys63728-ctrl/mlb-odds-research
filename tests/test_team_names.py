"""team_names.py のテスト。"""

from src.utils.team_names import to_ja, format_game_name_ja


def test_to_ja_translates_known_team():
    assert to_ja("New York Yankees") == "ヤンキース"
    assert to_ja("Los Angeles Dodgers") == "ドジャース"
    assert to_ja("Boston Red Sox") == "レッドソックス"


def test_to_ja_returns_english_for_unknown_team():
    # NBAや将来の競技は未登録 → 英語のまま
    assert to_ja("Lakers") == "Lakers"
    assert to_ja("FC Barcelona") == "FC Barcelona"


def test_format_game_name_translates_both_teams():
    assert (
        format_game_name_ja("New York Yankees vs Boston Red Sox")
        == "ヤンキース vs レッドソックス"
    )


def test_format_game_name_keeps_unknown_as_is():
    assert (
        format_game_name_ja("Lakers vs Celtics") == "Lakers vs Celtics"
    )


def test_format_game_name_handles_no_vs_marker():
    # "vs" が入っていない文字列はそのまま
    assert format_game_name_ja("Yankees Game") == "Yankees Game"


def test_all_30_mlb_teams_have_translations():
    """MLB 30球団全てが登録されていること（漏れ防止）。"""
    from src.utils.team_names import MLB_TEAM_NAMES_JA
    # "Athletics" と "Oakland Athletics" の重複登録分を除いて 30件以上
    distinct_values = set(MLB_TEAM_NAMES_JA.values())
    assert len(distinct_values) == 30
