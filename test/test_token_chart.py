#!/usr/bin/env python3
"""Unit tests for the token-usage chart data builder.

These exercise ``build_token_chart_data`` end-to-end through
``generate_template_messages`` so the double-count guard (one entry per API
response even when usage lands on a thinking-first chunk, and one entry per
``requestId``) is covered against the real pipeline.
"""

import json
import tempfile
from pathlib import Path

from claude_code_log.converter import load_transcript
from claude_code_log.html.renderer import build_token_chart_data
from claude_code_log.renderer import generate_template_messages


def _chart_entries(*lines: dict) -> list[dict]:
    """Write the given entries to a temp JSONL, build chart data, return list."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "transcript.jsonl"
        path.write_text(
            "\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8"
        )
        messages = load_transcript(path)
    _roots, _nav, ctx = generate_template_messages(messages)
    return json.loads(build_token_chart_data(ctx))


def _user(uuid: str, ts: str, *, parent: str | None = None) -> dict:
    return {
        "type": "user",
        "timestamp": ts,
        "parentUuid": parent,
        "isSidechain": False,
        "userType": "human",
        "cwd": "/tmp",
        "sessionId": "s",
        "version": "1.0.0",
        "uuid": uuid,
        "message": {"role": "user", "content": [{"type": "text", "text": "hi"}]},
    }


def _assistant(
    uuid: str,
    ts: str,
    *,
    parent: str | None = None,
    request_id: str | None = "req",
    content: list | None = None,
    usage: dict | None = None,
    sidechain: bool = False,
) -> dict:
    entry: dict = {
        "type": "assistant",
        "timestamp": ts,
        "parentUuid": parent,
        "isSidechain": sidechain,
        "userType": "human",
        "cwd": "/tmp",
        "sessionId": "s",
        "version": "1.0.0",
        "uuid": uuid,
        "message": {
            "id": uuid,
            "type": "message",
            "role": "assistant",
            "model": "claude-3",
            "content": content
            if content is not None
            else [{"type": "text", "text": "hello"}],
        },
    }
    if request_id is not None:
        entry["requestId"] = request_id
    if usage is not None:
        entry["message"]["usage"] = usage
    return entry


def _usage(inp=0, cache_read=0, output=0, cache_write=0) -> dict:
    return {
        "input_tokens": inp,
        "cache_read_input_tokens": cache_read,
        "output_tokens": output,
        "cache_creation_input_tokens": cache_write,
    }


def test_basic_entries_and_segment_values():
    """One entry per response with the four segment values mapped correctly."""
    entries = _chart_entries(
        _user("u1", "2025-01-01T10:00:00Z"),
        _assistant(
            "a1",
            "2025-01-01T10:00:01Z",
            parent="u1",
            request_id="req1",
            usage=_usage(inp=10, cache_read=40, output=20, cache_write=3),
        ),
        _user("u2", "2025-01-01T10:01:00Z", parent="a1"),
        _assistant(
            "a2",
            "2025-01-01T10:01:01Z",
            parent="u2",
            request_id="req2",
            usage=_usage(inp=5, cache_read=0, output=7, cache_write=0),
        ),
    )
    assert len(entries) == 2
    first = entries[0]
    assert first["input"] == 10
    assert first["cache_read"] == 40
    assert first["output"] == 20
    assert first["cache_write"] == 3
    assert first["type"] == "assistant"
    assert first["sidechain"] is False
    assert first["id"].startswith("d-")
    assert first["ts"]


def test_thinking_and_text_share_one_usage_counts_once():
    """A response with both a thinking and a text block yields ONE entry."""
    entries = _chart_entries(
        _user("u1", "2025-01-01T10:00:00Z"),
        _assistant(
            "a1",
            "2025-01-01T10:00:01Z",
            parent="u1",
            request_id="req1",
            content=[
                {"type": "thinking", "thinking": "reasoning", "signature": "sig"},
                {"type": "text", "text": "answer"},
            ],
            usage=_usage(inp=11, cache_read=22, output=33, cache_write=44),
        ),
    )
    assert len(entries) == 1
    assert entries[0]["input"] == 11
    assert entries[0]["cache_read"] == 22
    assert entries[0]["output"] == 33
    assert entries[0]["cache_write"] == 44


def test_same_request_id_counts_once():
    """Two assistant entries sharing a requestId are counted once."""
    entries = _chart_entries(
        _user("u1", "2025-01-01T10:00:00Z"),
        _assistant(
            "a1",
            "2025-01-01T10:00:01Z",
            parent="u1",
            request_id="shared",
            usage=_usage(inp=10, output=20),
        ),
        _assistant(
            "a2",
            "2025-01-01T10:00:02Z",
            parent="a1",
            request_id="shared",
            usage=_usage(inp=10, output=20),
        ),
    )
    assert len(entries) == 1


def test_no_usage_excluded():
    """A response without usage produces no chart entry."""
    entries = _chart_entries(
        _user("u1", "2025-01-01T10:00:00Z"),
        _assistant("a1", "2025-01-01T10:00:01Z", parent="u1", usage=None),
    )
    assert entries == []


def test_all_zero_bar_dropped():
    """A response whose usage is all zeros is dropped."""
    entries = _chart_entries(
        _user("u1", "2025-01-01T10:00:00Z"),
        _assistant(
            "a1",
            "2025-01-01T10:00:01Z",
            parent="u1",
            request_id="req1",
            usage=_usage(),
        ),
    )
    assert entries == []


def test_sidechain_flag():
    """Sub-assistant (sidechain) responses are tagged sidechain=True."""
    entries = _chart_entries(
        _user("u1", "2025-01-01T10:00:00Z"),
        _assistant(
            "a1",
            "2025-01-01T10:00:01Z",
            parent="u1",
            request_id="req1",
            usage=_usage(inp=10, output=20),
        ),
        _assistant(
            "a2",
            "2025-01-01T10:00:02Z",
            parent="a1",
            request_id="req2",
            usage=_usage(inp=5, output=6),
            sidechain=True,
        ),
    )
    by_sidechain = {e["sidechain"] for e in entries}
    assert by_sidechain == {True, False}
    sidechain_entries = [e for e in entries if e["sidechain"]]
    assert len(sidechain_entries) == 1
    assert sidechain_entries[0]["input"] == 5


def test_empty_island_is_valid_json_array():
    """No assistant usage at all → an empty (but valid) island."""
    entries = _chart_entries(_user("u1", "2025-01-01T10:00:00Z"))
    assert entries == []
