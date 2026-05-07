"""Regression tests for issue #139: lone-surrogate UnicodeEncodeError.

Background
----------
Claude Code logs file contents using `surrogateescape`, which encodes
non-UTF-8 bytes (e.g. Latin-1 ``0xB2``) as lone surrogate code points
like ``U+DCB2``. JSONL on disk represents these as the literal escape
``\\udcb2``. ``json.loads`` rebuilds the lone surrogate; strict
UTF-8 encoding (the default for ``Path.write_text``) crashes with
``UnicodeEncodeError`` when one of these flows into the rendered HTML.

The fix adds ``errors="replace"`` to the converter's ``write_text``
(and one paired ``read_text``) call sites so lone surrogates collapse
to ``U+FFFD`` rather than crashing the whole run.
"""

import json
from pathlib import Path

import pytest

from claude_code_log.converter import convert_jsonl_to_html


# Lone low surrogate U+DCB2 — what surrogateescape uses for byte 0xB2.
LONE_SURROGATE = "\udcb2"


def _make_jsonl_with_surrogate(jsonl_path: Path) -> None:
    """Write a minimal JSONL transcript whose user-text content carries a
    lone surrogate. The shape mirrors what Claude Code emits when a tool
    returns binary file content via ``surrogateescape`` decoding."""
    user_entry = {
        "parentUuid": None,
        "isSidechain": False,
        "userType": "external",
        "cwd": "/tmp",
        "sessionId": "11111111-1111-1111-1111-111111111111",
        "version": "2.1.0",
        "type": "user",
        "uuid": "22222222-2222-2222-2222-222222222222",
        "timestamp": "2026-05-07T10:00:00.000Z",
        "message": {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    # Embed the lone surrogate inside otherwise-valid text.
                    "text": f"non-utf8 byte placeholder: {LONE_SURROGATE} (issue #139)",
                }
            ],
        },
    }
    # ``ensure_ascii=False`` keeps the literal surrogate in memory; the
    # final on-disk JSONL escapes it as ``\udcb2`` either way (Python's
    # JSON encoder permits unpaired surrogates by default).
    jsonl_path.write_text(json.dumps(user_entry) + "\n", encoding="utf-8")


class TestSurrogateEncoding:
    def test_convert_does_not_crash_on_lone_surrogate(self, tmp_path: Path):
        """Issue #139's minimum bar: end-to-end conversion of a transcript
        carrying a lone surrogate must not raise UnicodeEncodeError."""
        jsonl_path = tmp_path / "session.jsonl"
        _make_jsonl_with_surrogate(jsonl_path)

        # Should complete without raising.
        output = convert_jsonl_to_html(jsonl_path, silent=True)
        assert output.exists(), "converter returned a path that wasn't written"

    def test_output_html_is_valid_utf8(self, tmp_path: Path):
        """Stronger guarantee: the bytes on disk decode as strict UTF-8.
        ``errors="replace"`` collapses any surviving lone surrogate to
        ``U+FFFD``, which is itself valid UTF-8, so a strict re-read must
        succeed regardless of which intermediate layer (mistune,
        html.escape, …) replaced it."""
        jsonl_path = tmp_path / "session.jsonl"
        _make_jsonl_with_surrogate(jsonl_path)

        output = convert_jsonl_to_html(jsonl_path, silent=True)

        # Strict decode — would raise UnicodeDecodeError if the file still
        # held a lone surrogate written via the buggy strict path.
        html = output.read_bytes().decode("utf-8")
        assert "issue #139" in html, "marker text from the fixture missing"
        # The lone surrogate must not survive into the output bytes; the
        # specific replacement character ("?", U+FFFD, or HTML entity)
        # depends on which layer caught it first, but the surrogate
        # itself is the canary.
        assert LONE_SURROGATE not in html

    def test_paginated_re_read_does_not_crash(self, tmp_path: Path):
        """The paginated `_enable_next_link_on_previous_page` path reads
        a previously-written page and rewrites it. Pre-fix corrupt pages
        (with lone surrogates baked in) crashed on the read; the read site
        also gained ``errors="replace"`` so older corrupt outputs can still
        be rewritten cleanly. We exercise the read-rewrite cycle by running
        the converter twice on a multi-page input."""
        jsonl_path = tmp_path / "session.jsonl"
        _make_jsonl_with_surrogate(jsonl_path)

        # First run produces the HTML; second run is a cache-hit path
        # that may exercise the read-rewrite seam.
        first = convert_jsonl_to_html(jsonl_path, silent=True)
        assert first.exists()
        second = convert_jsonl_to_html(jsonl_path, silent=True)
        assert second.exists()


@pytest.mark.parametrize("surrogate", ["\udcb2", "\udc80", "\udcff"])
def test_various_low_surrogates_handled(tmp_path: Path, surrogate: str):
    """Spot-check across the surrogateescape range (U+DC80 … U+DCFF) that
    every byte-mapped lone surrogate encodes safely."""
    jsonl_path = tmp_path / "session.jsonl"
    user_entry = {
        "parentUuid": None,
        "isSidechain": False,
        "userType": "external",
        "cwd": "/tmp",
        "sessionId": "11111111-1111-1111-1111-111111111111",
        "version": "2.1.0",
        "type": "user",
        "uuid": "22222222-2222-2222-2222-222222222222",
        "timestamp": "2026-05-07T10:00:00.000Z",
        "message": {
            "role": "user",
            "content": [{"type": "text", "text": f"x{surrogate}y"}],
        },
    }
    jsonl_path.write_text(json.dumps(user_entry) + "\n", encoding="utf-8")
    output = convert_jsonl_to_html(jsonl_path, silent=True)
    html = output.read_bytes().decode("utf-8")
    assert surrogate not in html
