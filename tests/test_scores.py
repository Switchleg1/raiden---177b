"""High score table: serialisation, corruption handling, ranking, initials."""

import config as C
import persistence as P


def row(initials="AAA", score=1000, sector=1, won=False, created=0):
    return P.ScoreEntry(initials=initials, score=score, sector=sector,
                        won=won, created=created)


# ------------------------------------------------------------------ storage
def test_missing_file_is_an_empty_table_not_a_corruption(tmp_path):
    assert P.load_scores(tmp_path) == []
    assert list(tmp_path.glob("*corrupt*")) == []


def test_round_trip_keeps_ranking_and_fields(tmp_path):
    entries = [row("ZED", 9000, sector=3, won=True),
               row("AAA", 4000, sector=1),
               row("MOK", 6500, sector=2)]
    P.save_scores(entries, tmp_path)
    loaded = P.load_scores(tmp_path)
    assert [e.score for e in loaded] == [9000, 6500, 4000]
    assert [e.initials for e in loaded] == ["ZED", "MOK", "AAA"]
    assert loaded[0].won is True
    assert loaded[1].won is False


def test_corrupt_file_is_quarantined_then_ignored(tmp_path):
    (tmp_path / P.SCORES_FILENAME).write_text("{not json", encoding="utf-8")
    assert P.load_scores(tmp_path) == []
    assert list(tmp_path.glob("*corrupt*")), "the junk file must be kept"
    assert (tmp_path / P.SCORES_FILENAME).exists() is False


def test_junk_rows_are_dropped_and_good_rows_survive(tmp_path):
    (tmp_path / P.SCORES_FILENAME).write_text(
        '{"scores": ['
        '{"initials": "AAA", "score": 5000, "sector": 2}, '
        '{"initials": "BBB"}, '          # score missing
        '{"initials": "CCC", "score": -10}, '
        '{"initials": "DDD", "score": "many"}, '
        '"not a row", '
        '{"initials": "eee!!", "score": 8000, "sector": 0}'
        ']}', encoding="utf-8")
    loaded = P.load_scores(tmp_path)
    assert [(e.initials, e.score) for e in loaded] == [("EEE", 8000),
                                                       ("AAA", 5000)]
    assert loaded[0].sector == 1, "bad sector falls back to 1"


def test_foreign_bare_list_payload_is_quarantined_not_crashed(tmp_path):
    # The writer always emits an object; anything else is foreign data and is
    # kept aside rather than trusted or lost.
    (tmp_path / P.SCORES_FILENAME).write_text(
        '[{"initials": "SOLO", "score": 1234}]', encoding="utf-8")
    assert P.load_scores(tmp_path) == []
    assert list(tmp_path.glob("*corrupt*"))


def test_data_dir_seam_is_used(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "TEST_DATA_DIR", str(tmp_path), raising=False)
    P.save_scores([row("SEA", 777)])
    assert (tmp_path / C.APP_AUTHOR / C.APP_SLUG /
            P.SCORES_FILENAME).exists()
    assert [e.initials for e in P.load_scores()] == ["SEA"]


# ------------------------------------------------------------------- ranking
def test_trim_sorts_best_first_and_caps():
    entries = [row(score=s) for s in (100, 900, 50, 700, 300)]
    trimmed = P.trim_scores(entries, limit=3)
    assert [e.score for e in trimmed] == [900, 700, 300]


def test_ties_keep_the_earlier_run_on_top():
    first = row("AAA", 5000)
    later = row("ZZZ", 5000)
    assert [e.initials for e in P.trim_scores([first, later])] == \
        ["AAA", "ZZZ"]


def test_add_score_inserts_in_place_and_evicts_the_worst():
    table = [row(score=s) for s in (9000, 8000, 7000)]
    out = P.add_score(table, row("NEW", 8500), limit=3)
    assert [e.score for e in out] == [9000, 8500, 8000]
    assert out[1].initials == "NEW"
    assert table[-1].score == 7000, "the caller's table is not mutated"


def test_rank_of_empty_table_is_first_place():
    assert P.rank_of([], 1) == 1


def test_rank_of_partial_table_takes_the_next_slot():
    table = [row(score=s) for s in (9000, 8000, 7000)]
    assert P.rank_of(table, 8500, limit=10) == 2
    assert P.rank_of(table, 100, limit=10) == 4, \
        "an unfinished table always has room"


def test_full_table_needs_to_beat_the_worst_row():
    table = [row(score=s) for s in (9000, 8000, 7000)]
    assert P.rank_of(table, 7500, limit=3) == 3
    assert P.rank_of(table, 7000, limit=3) is None, "ties go to the table"
    assert P.rank_of(table, 6999, limit=3) is None


def test_zero_score_never_asks_for_initials():
    assert P.rank_of([], 0) is None
    assert P.rank_of([row(score=1)], 0) is None


# ----------------------------------------------------------------- initials
def test_sanitize_initials():
    assert C.sanitize_initials("ab") == "AB "
    assert C.sanitize_initials("abc") == "ABC"
    assert C.sanitize_initials("a!b?c1") == "ABC"
    assert C.sanitize_initials("wxyz") == "WXY"
    assert C.sanitize_initials("") == "   "
    assert C.sanitize_initials("12 ") == "12 "
    assert all(ch in C.INITIALS_TYPED for ch in C.INITIALS_START)
    assert len(C.INITIALS_START) == C.INITIALS_LEN


def test_entry_round_trips_through_dict():
    e = row("QX7", 4242, sector=5, won=True, created=123)
    assert P.validate_scores([e.to_dict()])[0] == e
