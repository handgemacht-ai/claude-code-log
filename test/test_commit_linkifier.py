"""Tests for the git-commit linkifier (issue #156).

Covers two modules and their integration:

- ``markdown_plugins.make_sha_plugin`` and ``linkify_shas_in_text``:
  unit-level checks of the inline-parser plugin and the
  Markdown-side text substitution helper. Resolver is mocked.

- ``git_remote.resolve_sha`` + ``render_with_repo_context``: end-to-
  end against the project's own git repo (cheap, deterministic, no
  network — uses local remote-tracking refs only).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Optional

import pytest

from claude_code_log.git_remote import (
    _parse_git_url,
    canonical_cwd_from_messages,
    clear_resolver_caches,
    render_with_repo_context,
    resolve_sha,
    resolve_sha_for_current_render,
)
from claude_code_log.html.utils import render_markdown, render_user_markdown
from claude_code_log.markdown_plugins import (
    SHA_PATTERN,
    linkify_shas_in_text,
    make_sha_plugin,
)


# ---------------------------------------------------------------------------
# Fixture: a deterministic resolver that maps known SHAs to URLs.


_KNOWN_URLS = {
    "abc1234": "https://example.com/abc1234",
    "deadbeefcafe": "https://example.com/deadbeefcafe",
}


def _mock_resolve(sha: str) -> Optional[str]:
    return _KNOWN_URLS.get(sha)


# ---------------------------------------------------------------------------
# SHA_PATTERN regex


class TestShaPattern:
    def test_matches_short_sha(self):
        assert re.fullmatch(SHA_PATTERN, "abc1234")

    def test_matches_full_sha(self):
        assert re.fullmatch(SHA_PATTERN, "0" * 40)

    def test_rejects_too_short(self):
        # 6 chars: below the 7-char minimum.
        assert re.fullmatch(SHA_PATTERN, "abc123") is None

    def test_rejects_too_long(self):
        # 41 chars: above the 40-char maximum.
        assert re.fullmatch(SHA_PATTERN, "0" * 41) is None

    def test_rejects_non_hex(self):
        assert re.fullmatch(SHA_PATTERN, "abcg123") is None

    def test_rejects_uppercase(self):
        # Pattern is lowercase-only; git short SHAs are conventionally
        # lowercase. Tighten if real-world data shows uppercase.
        assert re.fullmatch(SHA_PATTERN, "ABC1234") is None


# ---------------------------------------------------------------------------
# make_sha_plugin: HTML mistune integration


def _render_with_plugin(text: str, resolve=_mock_resolve) -> str:
    """Build a fresh mistune renderer with our plugin and render *text*."""
    import mistune

    md = mistune.create_markdown(plugins=[make_sha_plugin(resolve)])
    return str(md(text)).strip()


class TestShaPluginInline:
    def test_emits_link_for_resolvable_sha(self):
        out = _render_with_plugin("See abc1234 in the diff")
        assert '<a href="https://example.com/abc1234">abc1234</a>' in out

    def test_passes_through_unresolved_sha(self):
        out = _render_with_plugin("Local-only commit ffffeee")
        assert "ffffeee" in out
        assert "<a" not in out

    def test_fires_inside_emphasis(self):
        # Confirms main's research finding: the inline plugin recurses
        # through `parse_emphasis` so registered rules fire inside
        # *…* and **…**.
        out = _render_with_plugin("**before abc1234 after**")
        assert "<strong>" in out
        assert '<a href="https://example.com/abc1234">' in out

    def test_does_not_fire_inside_codespan(self):
        out = _render_with_plugin("`abc1234` stays code")
        assert "<code>abc1234</code>" in out
        assert "<a" not in out

    def test_does_not_fire_inside_fenced_block(self):
        out = _render_with_plugin("```\nabc1234\n```")
        assert "abc1234" in out
        assert "<a" not in out

    def test_does_not_double_wrap_existing_link(self):
        # The existing-link guard (state.in_link) keeps us from emitting
        # a nested <a> when the SHA appears inside a Markdown link.
        out = _render_with_plugin("[abc1234](http://manual.example/x)")
        assert out.count("<a ") == 1
        assert "manual.example" in out

    def test_pluralized_sha_does_not_match(self):
        # 'abc12347' (8 chars) IS a valid SHA shape, but the trailing
        # punctuation cases below shouldn't break the match.
        out = _render_with_plugin("Commit abc1234.")
        assert '<a href="https://example.com/abc1234">abc1234</a>' in out


# ---------------------------------------------------------------------------
# linkify_shas_in_text: Markdown-side text substitution


class TestLinkifyShasInText:
    def test_substitutes_resolvable(self):
        out = linkify_shas_in_text("See abc1234 here", _mock_resolve)
        assert out == "See [abc1234](https://example.com/abc1234) here"

    def test_leaves_unresolved_alone(self):
        out = linkify_shas_in_text("Local commit ffffeee", _mock_resolve)
        assert out == "Local commit ffffeee"

    def test_handles_multiple_shas(self):
        out = linkify_shas_in_text("First abc1234 then deadbeefcafe", _mock_resolve)
        assert "[abc1234](https://example.com/abc1234)" in out
        assert "[deadbeefcafe](https://example.com/deadbeefcafe)" in out

    def test_empty_text_returns_unchanged(self):
        assert linkify_shas_in_text("", _mock_resolve) == ""


# ---------------------------------------------------------------------------
# git_remote URL parsing


class TestParseGitUrl:
    def test_https_with_dot_git(self):
        assert _parse_git_url("https://github.com/owner/repo.git") == (
            "github.com",
            "owner/repo",
        )

    def test_https_no_dot_git(self):
        assert _parse_git_url("https://github.com/owner/repo") == (
            "github.com",
            "owner/repo",
        )

    def test_ssh(self):
        assert _parse_git_url("git@github.com:owner/repo.git") == (
            "github.com",
            "owner/repo",
        )

    def test_https_with_token(self):
        assert _parse_git_url("https://x-token@github.com/owner/repo.git") == (
            "github.com",
            "owner/repo",
        )

    def test_https_with_subgroup(self):
        # Multi-segment paths (GitLab subgroups) preserved verbatim.
        assert _parse_git_url("https://gitlab.com/group/sub/repo.git") == (
            "gitlab.com",
            "group/sub/repo",
        )

    def test_rejects_local_path(self):
        assert _parse_git_url("/srv/git/repo.git") is None

    def test_rejects_empty(self):
        assert _parse_git_url("") is None

    def test_rejects_no_owner(self):
        assert _parse_git_url("git@github.com:repo.git") is None


# ---------------------------------------------------------------------------
# canonical_cwd_from_messages


class _M:
    def __init__(self, cwd: str = ""):
        self.cwd = cwd


class TestCanonicalCwd:
    def test_picks_only_cwd(self):
        assert canonical_cwd_from_messages([_M("/a"), _M("/a")]) == "/a"

    def test_picks_most_common(self):
        msgs = [_M("/a"), _M("/b"), _M("/b"), _M("/c")]
        assert canonical_cwd_from_messages(msgs) == "/b"

    def test_returns_none_when_no_cwds(self):
        assert canonical_cwd_from_messages([_M(""), _M("")]) is None

    def test_returns_none_for_empty_list(self):
        assert canonical_cwd_from_messages([]) is None

    def test_skips_messages_without_cwd_attr(self):
        class NoCwd:
            pass

        assert canonical_cwd_from_messages([NoCwd(), _M("/x")]) == "/x"


# ---------------------------------------------------------------------------
# render_with_repo_context: ContextVar plumbing


class TestRenderRepoContext:
    def setup_method(self):
        clear_resolver_caches()

    def teardown_method(self):
        clear_resolver_caches()

    def test_outside_context_resolver_returns_none(self):
        # No active context → resolver returns None for any input.
        assert resolve_sha_for_current_render("abc1234") is None

    def test_context_is_reset_on_exit(self):
        with render_with_repo_context("/some/repo"):
            pass
        assert resolve_sha_for_current_render("abc1234") is None


# ---------------------------------------------------------------------------
# Integration: the project's own git repo
#
# This repo has the commit 7c2e6f6 on origin/main (the sidechain
# filter dashed-border commit, used as a real fixture in main's task
# description). If the test environment doesn't have origin set to
# the daaain/claude-code-log GitHub remote (e.g. a fork), the test
# skips.


def _project_repo_origin_is_daaain_repo() -> bool:
    """Skip integration tests if origin doesn't point at the canonical repo."""
    try:
        result = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
            cwd=Path(__file__).parent.parent,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if result.returncode != 0:
        return False
    return "daaain/claude-code-log" in result.stdout


_KNOWN_LOCAL_SHA = "7c2e6f6"  # On origin/main as of writing.


@pytest.mark.skipif(
    not _project_repo_origin_is_daaain_repo(),
    reason="origin not set to daaain/claude-code-log; skipping integration",
)
class TestIntegrationLocalRepo:
    def setup_method(self):
        clear_resolver_caches()

    def teardown_method(self):
        clear_resolver_caches()

    def test_resolve_sha_returns_github_url(self):
        cwd = str(Path(__file__).parent.parent)
        url = resolve_sha(cwd, _KNOWN_LOCAL_SHA)
        assert url is not None
        assert url.startswith("https://github.com/daaain/claude-code-log/commit/")
        # Full 40-char SHA in the URL.
        assert len(url.rsplit("/", 1)[-1]) == 40

    def test_resolve_sha_returns_none_for_unknown(self):
        cwd = str(Path(__file__).parent.parent)
        # Plausible-looking SHA that doesn't exist in the repo.
        assert resolve_sha(cwd, "deadbeefcafe1234567890abcdef1234567890ab") is None

    def test_html_render_with_repo_context_produces_anchor(self):
        cwd = str(Path(__file__).parent.parent)
        with render_with_repo_context(cwd):
            html = render_markdown(f"See commit {_KNOWN_LOCAL_SHA} for details.")
        assert '<a href="https://github.com/daaain/claude-code-log/commit/' in html
        assert f">{_KNOWN_LOCAL_SHA}</a>" in html

    def test_user_html_render_with_repo_context_produces_anchor(self):
        cwd = str(Path(__file__).parent.parent)
        with render_with_repo_context(cwd):
            html = render_user_markdown(f"Check {_KNOWN_LOCAL_SHA} please")
        assert '<a href="https://github.com/daaain/claude-code-log/commit/' in html

    def test_markdown_text_helper_with_repo_context(self):
        cwd = str(Path(__file__).parent.parent)
        with render_with_repo_context(cwd):
            md = linkify_shas_in_text(
                f"diff at {_KNOWN_LOCAL_SHA} introduces it",
                resolve_sha_for_current_render,
            )
        assert (
            f"[{_KNOWN_LOCAL_SHA}](https://github.com/daaain/claude-code-log/commit/"
            in md
        )

    def test_codespan_unchanged_with_repo_context(self):
        cwd = str(Path(__file__).parent.parent)
        with render_with_repo_context(cwd):
            html = render_markdown(f"`{_KNOWN_LOCAL_SHA}` is a code span")
        assert f"<code>{_KNOWN_LOCAL_SHA}</code>" in html
        # The substring "claude-code-log/commit/" mustn't appear; the
        # SHA inside the code span shouldn't have been linkified.
        assert "claude-code-log/commit/" not in html

    def test_no_context_produces_plain_text(self):
        # Without entering the context, even a real reachable SHA
        # renders as plain text. This is the behavioural baseline:
        # rendering paths that don't bind a cwd must not surprise
        # the user with surprise links.
        html = render_markdown(f"See commit {_KNOWN_LOCAL_SHA} for details.")
        assert "<a " not in html
        assert _KNOWN_LOCAL_SHA in html
