from __future__ import annotations

import sqlite3
import threading
import time

import pytest

from hermes_state import SessionDB


def _seed_session_db(db_path) -> None:
    db = SessionDB(db_path=db_path)
    try:
        db.create_session(session_id="seed-session", source="cli")
    finally:
        db.close()


def test_read_only_sessiondb_reads_existing_rows_without_writable_connection(tmp_path) -> None:
    db_path = tmp_path / "state.db"
    _seed_session_db(db_path)

    db = SessionDB(db_path=db_path, read_only=True)
    try:
        row = db.get_session("seed-session")
        assert row is not None
        assert row["id"] == "seed-session"

        with pytest.raises(sqlite3.OperationalError):
            db.create_session(session_id="should-not-write", source="cli")
    finally:
        db.close()


def test_sessiondb_open_survives_short_external_writer_lock(tmp_path) -> None:
    db_path = tmp_path / "state.db"
    _seed_session_db(db_path)

    blocker = sqlite3.connect(str(db_path), timeout=1.0, isolation_level=None)
    blocker.execute("BEGIN IMMEDIATE")

    opened: dict[str, object] = {}
    started = threading.Event()

    def open_db() -> None:
        started.set()
        try:
            db = SessionDB(db_path=db_path)
            try:
                opened["row"] = db.get_session("seed-session")
            finally:
                db.close()
        except Exception as exc:  # pragma: no cover - asserted below
            opened["error"] = exc

    thread = threading.Thread(target=open_db)
    thread.start()
    assert started.wait(timeout=1)
    time.sleep(1.2)
    blocker.rollback()
    blocker.close()

    thread.join(timeout=4)

    assert not thread.is_alive()
    assert "error" not in opened
    row = opened.get("row")
    assert row is not None
    assert row["id"] == "seed-session"  # type: ignore[index]
