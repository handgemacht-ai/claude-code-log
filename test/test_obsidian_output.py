"""End-to-end tests for the Obsidian-friendly output flags (issue #151).

Drives the converter through ``process_projects_hierarchy`` with each
flag combination from the matrix and asserts the produced directory
tree. **Markdown-scoped per Q1 resolution** — the flag mechanics live
in ``converter.py``/``utils.py``, not the renderers, so HTML/JSON parity
is asserted by code inspection rather than by re-running the matrix
per format.
"""

import json
from pathlib import Path

import pytest

from claude_code_log.converter import process_projects_hierarchy


def _build_fake_projects_dir(
    root: Path,
    projects: list[tuple[str, str]],
) -> Path:
    """Create a fake `~/.claude/projects/`-shaped directory.

    Args:
        root: tmp_path-style scratch directory.
        projects: list of (encoded_name, real_cwd) pairs.
    Returns:
        The projects-dir path.
    """
    projects_dir = root / "projects"
    projects_dir.mkdir()
    for encoded, cwd in projects:
        proj = projects_dir / encoded
        proj.mkdir()
        # Minimal session JSONL — enough for the loader to find one
        # session and produce one combined transcript.
        entry = {
            "parentUuid": None,
            "isSidechain": False,
            "userType": "external",
            "cwd": cwd,
            "sessionId": f"session-{encoded.lstrip('-')[:32]}",
            "version": "2.1.0",
            "type": "user",
            "uuid": f"uuid-{encoded.lstrip('-')[:32]}",
            "timestamp": "2026-05-10T10:00:00.000Z",
            "message": {
                "role": "user",
                "content": [{"type": "text", "text": f"hi from {encoded}"}],
            },
        }
        (proj / "session.jsonl").write_text(json.dumps(entry) + "\n", encoding="utf-8")
    return projects_dir


@pytest.fixture
def fake_projects(tmp_path: Path) -> Path:
    """Three encoded projects with realistic absolute cwds (which is
    what the JSONL-peek tier of `project_dir_to_real_path` will pick up).
    """
    return _build_fake_projects_dir(
        tmp_path,
        projects=[
            ("-home-joe-project-A", "/home/joe/project/A"),
            ("-home-joe-project-B", "/home/joe/project/B"),
            ("-home-jane-project-C", "/home/jane/project/C"),
        ],
    )


@pytest.fixture
def isolated_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Steer the cache to tmp so the test doesn't pollute / depend on
    the user's real `~/.claude/projects/` cache."""
    cache_path = tmp_path / "cache.db"
    monkeypatch.setenv("CLAUDE_CODE_LOG_CACHE_PATH", str(cache_path))
    return cache_path


# Keep usage explicit so the fixture clearly applies even when its
# return value isn't read directly in the test body.
_ = isolated_cache


class TestObsidianOutputMatrix:
    """The matrix from work/obsidian-friendly-output.md, end-to-end.
    Each test asserts the produced directory shape under the relevant
    flag combination."""

    def test_legacy_no_output(self, fake_projects: Path, isolated_cache: Path):
        """Legacy: `--output` unset → outputs land inside each
        source project_dir under the projects tree (current behaviour
        from before #151)."""
        process_projects_hierarchy(
            fake_projects,
            output_format="md",
        )

        # Each project gets a combined_transcripts.md under its source.
        for encoded in [
            "-home-joe-project-A",
            "-home-joe-project-B",
            "-home-jane-project-C",
        ]:
            assert (fake_projects / encoded / "combined_transcripts.md").exists()
        # Index at the projects-dir root.
        assert (fake_projects / "index.md").exists()

    def test_output_only_flat_copy(
        self,
        fake_projects: Path,
        isolated_cache: Path,
        tmp_path: Path,
    ):
        """`--output` alone → flat copy of each project under
        <output>/<encoded>/. Closes the implicit gap (`--output` was
        previously silently ignored for `--all-projects`)."""
        out = tmp_path / "out-flat"
        process_projects_hierarchy(
            fake_projects,
            output_format="md",
            output_dir=out,
        )
        assert (out / "-home-joe-project-A" / "combined_transcripts.md").exists()
        assert (out / "-home-joe-project-B" / "combined_transcripts.md").exists()
        assert (out / "-home-jane-project-C" / "combined_transcripts.md").exists()
        assert (out / "index.md").exists()

    def test_expand_paths_full_tree(
        self,
        fake_projects: Path,
        isolated_cache: Path,
        tmp_path: Path,
    ):
        """`--output --expand-paths` → expanded real-path tree under
        <output>/. Encoded names are resolved via JSONL peek (the
        fixture's cwd field)."""
        out = tmp_path / "out-expanded"
        process_projects_hierarchy(
            fake_projects,
            output_format="md",
            output_dir=out,
            expand_paths=True,
        )
        assert (out / "home/joe/project/A/combined_transcripts.md").exists()
        assert (out / "home/joe/project/B/combined_transcripts.md").exists()
        assert (out / "home/jane/project/C/combined_transcripts.md").exists()
        assert (out / "index.md").exists()
        # The encoded-name flat directories must NOT exist — we
        # expanded, didn't both expand and copy.
        assert not (out / "-home-joe-project-A").exists()

    def test_expand_paths_filter_match_truncates(
        self,
        fake_projects: Path,
        isolated_cache: Path,
        tmp_path: Path,
    ):
        """`--filter-path /home/joe --expand-paths`: filter against
        real path; truncate the prefix; matching projects land at
        <output>/<rel-to-prefix>/."""
        out = tmp_path / "out-filtered"
        process_projects_hierarchy(
            fake_projects,
            output_format="md",
            output_dir=out,
            expand_paths=True,
            filter_path="/home/joe",
        )
        # Projects under /home/joe matched, prefix truncated.
        assert (out / "project/A/combined_transcripts.md").exists()
        assert (out / "project/B/combined_transcripts.md").exists()
        # Project under /home/jane filtered out — no output produced.
        assert not (out / "project/C").exists()
        assert not (out / "home").exists()  # would only exist if /home/joe survived
        assert (out / "index.md").exists()

    def test_filter_flat_no_expand(
        self,
        fake_projects: Path,
        isolated_cache: Path,
        tmp_path: Path,
    ):
        """`--filter-path -home-joe`without `--expand-paths`: filter
        against the encoded dir name; no truncation; matching
        projects land at <output>/<encoded>/."""
        out = tmp_path / "out-flat-filtered"
        process_projects_hierarchy(
            fake_projects,
            output_format="md",
            output_dir=out,
            expand_paths=False,
            filter_path="-home-joe",
        )
        # Two `-home-joe-...` projects matched; flat name preserved.
        assert (out / "-home-joe-project-A" / "combined_transcripts.md").exists()
        assert (out / "-home-joe-project-B" / "combined_transcripts.md").exists()
        # `-home-jane-...` doesn't start with `-home-joe`.
        assert not (out / "-home-jane-project-C").exists()
