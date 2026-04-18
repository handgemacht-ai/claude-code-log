"""Tests for per-level output file naming and variant-aware caching.

Covers:

- `variant_suffix()` matrix across (detail, compact, format).
- `_VARIANT_ENTRY_RE` regex acceptance/rejection.
- `_get_page_html_path(n, suffix)` composition with pagination.
- Converter integration: combined / session / --session-id paths all
  land at the variant-encoded filename; explicit `-o` honours the
  user's literal path.
- Cache coexistence: full and low variants cache independently; a
  second render of the same variant is a cache hit; variants do not
  delete each other's page files.
- Session → combined back-link points to the same variant.
- `_enumerate_project_variants` lists all entry points present.
- CLI --compact help text regression.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from claude_code_log.cache import CacheManager
from claude_code_log.converter import (
    _enumerate_project_variants,
    _get_page_html_path,
    convert_jsonl_to,
    generate_single_session_file,
)
from claude_code_log.models import DetailLevel
from claude_code_log.utils import _VARIANT_ENTRY_RE, variant_suffix


# ---------------------------------------------------------------------------
# variant_suffix() matrix
# ---------------------------------------------------------------------------


class TestVariantSuffix:
    def test_default_is_empty(self) -> None:
        assert variant_suffix(DetailLevel.FULL, False, "html") == ""
        assert variant_suffix(DetailLevel.FULL, False, "md") == ""

    def test_detail_only(self) -> None:
        assert variant_suffix(DetailLevel.HIGH, False, "html") == ".high"
        assert variant_suffix(DetailLevel.LOW, False, "html") == ".low"
        assert variant_suffix(DetailLevel.MINIMAL, False, "md") == ".minimal"

    def test_compact_markdown_only(self) -> None:
        # Compact contributes for Markdown output.
        assert variant_suffix(DetailLevel.FULL, True, "md") == ".compact"
        assert variant_suffix(DetailLevel.FULL, True, "markdown") == ".compact"
        assert variant_suffix(DetailLevel.LOW, True, "md") == ".low.compact"
        # HTML silently drops the compact component.
        assert variant_suffix(DetailLevel.FULL, True, "html") == ""
        assert variant_suffix(DetailLevel.LOW, True, "html") == ".low"

    def test_string_detail_accepted(self) -> None:
        # The CLI passes the already-normalised enum, but convenience callers
        # may pass the string form.
        assert variant_suffix("low", False, "html") == ".low"


# ---------------------------------------------------------------------------
# _VARIANT_ENTRY_RE
# ---------------------------------------------------------------------------


class TestVariantEntryRegex:
    @pytest.mark.parametrize(
        "name,expected_suffix",
        [
            ("combined_transcripts.html", ""),
            ("combined_transcripts.low.html", ".low"),
            ("combined_transcripts.high.html", ".high"),
            ("combined_transcripts.low.compact.html", ".low.compact"),
            ("combined_transcripts.minimal.html", ".minimal"),
        ],
    )
    def test_accepts_entry_points(self, name: str, expected_suffix: str) -> None:
        m = _VARIANT_ENTRY_RE.match(name)
        assert m is not None, name
        assert m.group(1) == expected_suffix

    @pytest.mark.parametrize(
        "name",
        [
            "combined_transcripts_2.html",
            "combined_transcripts.low_2.html",
            "combined_transcripts..html",
            "other_file.html",
            "combined_transcripts.md",
        ],
    )
    def test_rejects_non_entry_points(self, name: str) -> None:
        assert _VARIANT_ENTRY_RE.match(name) is None, name


# ---------------------------------------------------------------------------
# _get_page_html_path
# ---------------------------------------------------------------------------


class TestPageHtmlPath:
    def test_default_page_one(self) -> None:
        assert _get_page_html_path(1) == "combined_transcripts.html"

    def test_default_page_two(self) -> None:
        assert _get_page_html_path(2) == "combined_transcripts_2.html"

    def test_variant_page_one(self) -> None:
        assert _get_page_html_path(1, ".low") == "combined_transcripts.low.html"

    def test_variant_page_two(self) -> None:
        assert _get_page_html_path(2, ".low") == "combined_transcripts.low_2.html"

    def test_variant_with_compact_chain(self) -> None:
        assert (
            _get_page_html_path(3, ".low.compact")
            == "combined_transcripts.low.compact_3.html"
        )


# ---------------------------------------------------------------------------
# Fixtures for converter integration
# ---------------------------------------------------------------------------


def _make_user(
    uuid: str, session_id: str, ts: str, text: str, parent: str | None = None
) -> dict:
    return {
        "type": "user",
        "timestamp": ts,
        "parentUuid": parent,
        "isSidechain": False,
        "userType": "human",
        "cwd": "/tmp",
        "sessionId": session_id,
        "version": "1.0.0",
        "uuid": uuid,
        "message": {
            "role": "user",
            "content": [{"type": "text", "text": text}],
        },
    }


def _make_assistant(uuid: str, session_id: str, ts: str, parent: str) -> dict:
    return {
        "type": "assistant",
        "timestamp": ts,
        "parentUuid": parent,
        "isSidechain": False,
        "userType": "human",
        "cwd": "/tmp",
        "sessionId": session_id,
        "version": "1.0.0",
        "uuid": uuid,
        "requestId": f"req_{uuid}",
        "message": {
            "id": uuid,
            "type": "message",
            "role": "assistant",
            "model": "claude-3-sonnet",
            "content": [{"type": "text", "text": "reply"}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 10, "output_tokens": 5},
        },
    }


def _write_session(path: Path, session_id: str, num_messages: int = 4) -> None:
    """Write a small single-session JSONL file at `path`."""
    entries: list[dict] = []
    prev: str | None = None
    for i in range(num_messages):
        uid = f"{session_id}_{i:03d}"
        if i % 2 == 0:
            entries.append(
                _make_user(
                    uid,
                    session_id,
                    f"2026-01-01T10:{i:02d}:00Z",
                    f"hi {i}",
                    parent=prev,
                )
            )
        else:
            entries.append(
                _make_assistant(
                    uid, session_id, f"2026-01-01T10:{i:02d}:00Z", prev or ""
                )
            )
        prev = uid
    with path.open("w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


# ---------------------------------------------------------------------------
# Converter integration: default path, variant paths, explicit -o
# ---------------------------------------------------------------------------


class TestConverterVariantPaths:
    def test_default_variant_uses_bare_filename(self, tmp_path: Path) -> None:
        _write_session(tmp_path / "sess1.jsonl", "sess1")
        output_path = convert_jsonl_to("html", tmp_path, silent=True)
        assert output_path.name == "combined_transcripts.html"
        assert output_path.exists()

    def test_low_variant_encodes_suffix(self, tmp_path: Path) -> None:
        _write_session(tmp_path / "sess1.jsonl", "sess1")
        output_path = convert_jsonl_to(
            "html", tmp_path, silent=True, detail=DetailLevel.LOW
        )
        assert output_path.name == "combined_transcripts.low.html"
        assert output_path.exists()

    def test_low_and_full_coexist(self, tmp_path: Path) -> None:
        _write_session(tmp_path / "sess1.jsonl", "sess1")
        full = convert_jsonl_to("html", tmp_path, silent=True)
        low = convert_jsonl_to("html", tmp_path, silent=True, detail=DetailLevel.LOW)
        assert full.name == "combined_transcripts.html"
        assert low.name == "combined_transcripts.low.html"
        assert full.exists() and low.exists()
        assert full != low

    def test_md_compact_variant(self, tmp_path: Path) -> None:
        _write_session(tmp_path / "sess1.jsonl", "sess1")
        path = convert_jsonl_to(
            "md",
            tmp_path,
            silent=True,
            detail=DetailLevel.LOW,
            compact=True,
        )
        assert path.name == "combined_transcripts.low.compact.md"
        assert path.exists()

    def test_individual_session_files_pick_up_suffix(self, tmp_path: Path) -> None:
        _write_session(tmp_path / "sess1.jsonl", "sess1")
        convert_jsonl_to(
            "html",
            tmp_path,
            silent=True,
            detail=DetailLevel.LOW,
        )
        assert (tmp_path / "session-sess1.low.html").exists()
        assert not (tmp_path / "session-sess1.html").exists()

    def test_explicit_output_path_honoured(self, tmp_path: Path) -> None:
        _write_session(tmp_path / "sess1.jsonl", "sess1")
        explicit = tmp_path / "custom.html"
        result = convert_jsonl_to(
            "html",
            tmp_path,
            explicit,
            silent=True,
            detail=DetailLevel.LOW,
        )
        # User's literal path wins: no suffix appended.
        assert result == explicit
        assert explicit.exists()

    def test_single_session_export_variant(self, tmp_path: Path) -> None:
        _write_session(tmp_path / "sess1.jsonl", "sess1")
        # Build cache first.
        convert_jsonl_to("html", tmp_path, silent=True)
        out = generate_single_session_file(
            "html",
            tmp_path,
            "sess1",
            use_cache=True,
            detail=DetailLevel.LOW,
        )
        assert out.name == "session-sess1.low.html"

    def test_single_file_input_variant_suffix(self, tmp_path: Path) -> None:
        jsonl = tmp_path / "sess1.jsonl"
        _write_session(jsonl, "sess1")
        out = convert_jsonl_to(
            "html",
            jsonl,
            silent=True,
            detail=DetailLevel.HIGH,
        )
        assert out.name == "sess1.high.html"
        assert out.exists()


# ---------------------------------------------------------------------------
# Cache coexistence
# ---------------------------------------------------------------------------


class TestCacheVariantCoexistence:
    def test_variant_cache_buckets_are_independent(self, tmp_path: Path) -> None:
        _write_session(tmp_path / "sess1.jsonl", "sess1")
        # First: render FULL, populates cache for default variant.
        full1 = convert_jsonl_to("html", tmp_path, silent=True)
        full_mtime = full1.stat().st_mtime

        # Render LOW — must NOT touch the FULL file's cache row.
        low = convert_jsonl_to("html", tmp_path, silent=True, detail=DetailLevel.LOW)
        assert low.exists()
        assert full1.exists()

        # Second FULL render must hit cache (file untouched).
        full2 = convert_jsonl_to("html", tmp_path, silent=True)
        assert full2.stat().st_mtime == full_mtime, (
            "Second FULL render should be a cache hit — file was rewritten"
        )

    def test_low_render_does_not_delete_full_pages(self, tmp_path: Path) -> None:
        _write_session(tmp_path / "sess1.jsonl", "sess1")
        full = convert_jsonl_to("html", tmp_path, silent=True)
        low = convert_jsonl_to("html", tmp_path, silent=True, detail=DetailLevel.LOW)
        # Both exist and are distinct files.
        assert full.exists() and low.exists() and full != low


# ---------------------------------------------------------------------------
# Session → combined back-link
# ---------------------------------------------------------------------------


class TestSessionBackLink:
    def test_low_session_links_to_low_combined(self, tmp_path: Path) -> None:
        _write_session(tmp_path / "sess1.jsonl", "sess1")
        convert_jsonl_to(
            "html",
            tmp_path,
            silent=True,
            detail=DetailLevel.LOW,
        )
        session_file = tmp_path / "session-sess1.low.html"
        html = session_file.read_text()
        # Should link to the LOW combined file, not the bare default.
        assert "combined_transcripts.low.html" in html
        # The bare default may still occur as text elsewhere; ensure it is
        # not the back-link target on its own.
        assert 'href="combined_transcripts.html"' not in html


# ---------------------------------------------------------------------------
# _enumerate_project_variants
# ---------------------------------------------------------------------------


class TestEnumerateProjectVariants:
    def test_lists_all_variants_default_first(self, tmp_path: Path) -> None:
        # Create dummy variant files.
        (tmp_path / "combined_transcripts.html").write_text("x")
        (tmp_path / "combined_transcripts.low.html").write_text("x")
        (tmp_path / "combined_transcripts.high.html").write_text("x")
        # Paginated trailers should be ignored.
        (tmp_path / "combined_transcripts_2.html").write_text("x")
        (tmp_path / "combined_transcripts.low_2.html").write_text("x")

        variants = _enumerate_project_variants(tmp_path, "project")
        suffixes = [v["suffix"] for v in variants]
        labels = [v["label"] for v in variants]
        # Default first.
        assert suffixes[0] == ""
        assert labels[0] == "Full"
        # All three entries present, no paginated trailers.
        assert sorted(suffixes) == ["", ".high", ".low"]

    def test_empty_dir_returns_empty_list(self, tmp_path: Path) -> None:
        assert _enumerate_project_variants(tmp_path, "empty") == []


# ---------------------------------------------------------------------------
# CLI --compact help text regression
# ---------------------------------------------------------------------------


class TestCliHelpText:
    def test_compact_help_notes_markdown_only(self) -> None:
        result = subprocess.run(
            ["uv", "run", "claude-code-log", "--help"],
            capture_output=True,
            text=True,
            check=True,
        )
        # Combined text: flatten whitespace since click wraps help lines.
        flat = re.sub(r"\s+", " ", result.stdout)
        assert "--compact" in flat
        assert "Markdown-only" in flat, (
            f"Expected 'Markdown-only' note in --compact help; got:\n{flat}"
        )


# ---------------------------------------------------------------------------
# Cache API: variant-aware pagination (low-level)
# ---------------------------------------------------------------------------


class TestPaginationCacheVariantApi:
    def test_page_cache_rows_are_variant_scoped(self, tmp_path: Path) -> None:
        _write_session(tmp_path / "sess1.jsonl", "sess1")
        # Trigger an initial render so the cache manager is primed.
        convert_jsonl_to("html", tmp_path, silent=True)

        cache = CacheManager(tmp_path, "0.0.1")

        # Manually insert a page row at the default variant and at .low.
        cache.update_page_cache(
            page_number=1,
            html_path="combined_transcripts.html",
            page_size_config=2000,
            session_ids=["sess1"],
            message_count=10,
            first_timestamp="2026-01-01T10:00:00Z",
            last_timestamp="2026-01-01T10:10:00Z",
            total_input_tokens=0,
            total_output_tokens=0,
            total_cache_creation_tokens=0,
            total_cache_read_tokens=0,
        )
        cache.update_page_cache(
            page_number=1,
            html_path="combined_transcripts.low.html",
            page_size_config=2000,
            session_ids=["sess1"],
            message_count=5,
            first_timestamp="2026-01-01T10:00:00Z",
            last_timestamp="2026-01-01T10:10:00Z",
            total_input_tokens=0,
            total_output_tokens=0,
            total_cache_creation_tokens=0,
            total_cache_read_tokens=0,
            variant_suffix=".low",
        )

        default = cache.get_page_data(1)
        low = cache.get_page_data(1, ".low")
        assert default is not None and low is not None
        assert default.html_path == "combined_transcripts.html"
        assert low.html_path == "combined_transcripts.low.html"
        # The rows are independent — different message_count.
        assert default.message_count != low.message_count
        # Page counts are variant-scoped.
        assert cache.get_page_count() == 1
        assert cache.get_page_count(".low") == 1
