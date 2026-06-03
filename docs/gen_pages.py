"""Generate live documentation pages at MkDocs build time.

Run by the ``mkdocs-gen-files`` plugin (see ``mkdocs.yml``). It introspects the
TUI to produce an always-current reference page:

* TUI screenshots (SVG), captured by driving the real screens headlessly.
* A keybindings table per screen, read from the Textual ``BINDINGS``.

Screenshot capture is wrapped in error handling: if it fails (e.g. in a
constrained CI runner) the page still builds, just without images, so prose
docs are never blocked by a screenshot hiccup.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import mkdocs_gen_files

# Make the standalone generator scripts importable.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

from generate_tui_docs import build_keybindings_markdown  # noqa: E402
from generate_tui_screenshots import Screenshot, generate_screenshots  # noqa: E402


def _emit_screenshots() -> list[Screenshot]:
    """Capture TUI screenshots into the virtual site under assets/tui/."""
    with tempfile.TemporaryDirectory() as tmp:
        out_dir = Path(tmp)
        shots = generate_screenshots(out_dir)
        for shot in shots:
            data = (out_dir / shot.filename).read_bytes()
            with mkdocs_gen_files.open(f"assets/tui/{shot.filename}", "wb") as fh:
                fh.write(data)
        return shots


def _build_page() -> str:
    parts: list[str] = [
        "# TUI Reference",
        "",
        (
            "The interactive terminal UI (`claude-code-log --tui`) lets you "
            "browse, export, and resume sessions. The screenshots and "
            "keybinding tables below are generated from the running TUI at "
            "build time, so they stay in sync with the shipped interface."
        ),
        "",
        "## Screenshots",
        "",
    ]

    try:
        shots = _emit_screenshots()
    except Exception as exc:  # noqa: BLE001 - never let a screenshot break docs
        print(f"WARNING: TUI screenshot generation failed: {exc}", file=sys.stderr)
        parts.append(
            "_Screenshots could not be generated in this build environment. "
            "Run `just docs-gen` locally to preview them._"
        )
        parts.append("")
    else:
        for shot in shots:
            parts.append(f"### {shot.title}")
            parts.append("")
            parts.append(f"![{shot.title}](../assets/tui/{shot.filename})")
            parts.append("")
            parts.append(f"*{shot.caption}*")
            parts.append("")

    # Append the keybindings reference (drop its top-level H1; this page owns it).
    keybindings = build_keybindings_markdown()
    keybindings = keybindings.split("\n", 1)[1].lstrip("\n")
    parts.append("## Keybindings")
    parts.append("")
    parts.append(keybindings)

    return "\n".join(parts).rstrip() + "\n"


with mkdocs_gen_files.open("reference/tui.md", "w") as fh:
    fh.write(_build_page())
