"""Regression coverage for desktop REST transcript hydration across compression chains."""

import asyncio
from pathlib import Path

import pytest

from hermes_cli import web_server
from hermes_state import SessionDB


def test_get_session_messages_returns_root_to_tip_compression_lineage(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Opening a compressed root in Desktop must hydrate the full logical thread.

    The REST fallback/prefetch endpoint resolves the requested root to the live
    compression tip. It must not then return only the tip's rows: doing so lets
    the frontend overwrite a complete ``session.resume`` transcript with a
    truncated REST response, making older messages appear to vanish.
    """
    db_path = tmp_path / "state.db"
    db = SessionDB(db_path=db_path)
    try:
        db.create_session("root", source="desktop")
        db.append_message("root", role="user", content="before compression")
        db.append_message("root", role="assistant", content="answer before compression")
        db.end_session("root", "compression")

        db.create_session("tip", source="desktop", parent_session_id="root")
        db.append_message("tip", role="user", content="after compression")
        db.append_message("tip", role="assistant", content="answer after compression")
    finally:
        db.close()

    def open_test_db(profile: str | None = None) -> SessionDB:
        assert profile is None
        return SessionDB(db_path=db_path)

    monkeypatch.setattr(web_server, "_open_session_db_for_profile", open_test_db)

    response = asyncio.run(web_server.get_session_messages("root"))

    assert response["session_id"] == "tip"
    assert [message["content"] for message in response["messages"]] == [
        "before compression",
        "answer before compression",
        "after compression",
        "answer after compression",
    ]
