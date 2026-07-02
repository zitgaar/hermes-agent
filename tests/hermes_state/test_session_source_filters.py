import pytest

from hermes_state import SessionDB


@pytest.fixture
def db(tmp_path):
    database = SessionDB(tmp_path / "state.db")
    try:
        yield database
    finally:
        database.close()


def _session(db: SessionDB, session_id: str, source: str) -> None:
    db.create_session(session_id=session_id, source=source)
    db.append_message(session_id=session_id, role="user", content=f"hello from {session_id}")


def test_list_sessions_rich_excludes_source_prefixes_and_count_matches(db):
    _session(db, "real", "cli")
    _session(db, "tool-row", "tool")
    _session(db, "ma-row", "ma_protocol_search_003_taxonomy_redteam")
    _session(db, "bench-row", "ma_bench_003b")
    _session(db, "bench-hyphen-row", "ma-bench-002-blind_judge_1")
    _session(db, "control-row", "control_surface_stage5_rerun_control")

    rows = db.list_sessions_rich(
        exclude_sources=["tool"],
        exclude_source_prefixes=[
            "ma_protocol_search_",
            "ma_bench_",
            "ma-bench-",
            "control_surface_",
        ],
        order_by_last_active=True,
    )

    assert [row["id"] for row in rows] == ["real"]
    assert db.session_count(
        exclude_children=True,
        exclude_sources=["tool"],
        exclude_source_prefixes=[
            "ma_protocol_search_",
            "ma_bench_",
            "ma-bench-",
            "control_surface_",
        ],
    ) == 1


def test_explicit_source_lookup_is_still_available(db):
    _session(db, "ma-row", "ma_protocol_search_003_taxonomy_redteam")

    rows = db.list_sessions_rich(source="ma_protocol_search_003_taxonomy_redteam")

    assert [row["id"] for row in rows] == ["ma-row"]
