"""Live-browser tests for the spliced dynamic-workflow run tree (#174 PR3).

The phase/agent cards are synthesized nodes attached via ``.children`` on the
same nested DOM the rest of the transcript uses (PR0 / #191), so the existing
fold machine must drive them: folding a Workflow *phase* hides its agent
children (and their grafted side-channel transcripts) exactly like any other
foldable node — provided the synthetic nodes carry the fold-state fields the
splice sets.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import Page

from claude_code_log.converter import load_directory_transcripts
from claude_code_log.html.renderer import generate_html

WORKFLOW_DIR = Path(__file__).parent / "test_data" / "workflow_basic"


def _render(tmp_path: Path) -> str:
    """Render the workflow_basic directory (Workflow tool_use with a spliced
    phase/agent sub-tree) to an HTML file and return a ``file://`` URL."""
    msgs, tree = load_directory_transcripts(WORKFLOW_DIR, silent=True)
    html = generate_html(msgs, session_tree=tree)
    out = tmp_path / "workflow.html"
    out.write_text(html, encoding="utf-8")
    return f"file://{out}"


class TestWorkflowPhaseFold:
    """A spliced ``workflow_phase`` card drives its ``workflow_agent`` children
    through the shared nested-DOM fold machine: clicking its fold control
    toggles the agents' visibility, and a second click restores it.

    (Deeply-nested subtrees start folded by default, so this asserts a *toggle*
    rather than a fixed initial state — proving the fold machine operates on the
    synthetic nodes, which requires the fold-state fields the splice sets.)"""

    @pytest.mark.browser
    def test_phase_fold_control_toggles_agents(
        self, page: Page, tmp_path: Path
    ) -> None:
        page.goto(_render(tmp_path))
        page.wait_for_timeout(300)

        result = page.evaluate(
            """() => {
                // A workflow_phase card whose sibling .children holds an agent.
                // (Non-session/non-user nodes start folded, so we assert the
                // fold control TOGGLES the phase's own children container —
                // independent of any ancestor's fold state, i.e. offsetParent.)
                const phases = Array.from(
                    document.querySelectorAll('.message.workflow_phase[data-message-id]'));
                for (const phase of phases) {
                    const cc = phase.parentElement &&
                        phase.parentElement.querySelector(':scope > .children');
                    const agent = cc && cc.querySelector('.message.workflow_agent');
                    const mid = phase.getAttribute('data-message-id');
                    const bar = document.querySelector(
                        `.fold-bar[data-message-id="${mid}"] `
                        + `.fold-bar-section.fold-one-level`);
                    if (!agent || !bar || !cc) continue;

                    const hidden = () => cc.style.display === 'none';
                    const d0 = hidden();
                    bar.click();
                    const d1 = hidden();
                    bar.click();
                    const d2 = hidden();
                    return { found: true, phaseId: mid, d0, d1, d2 };
                }
                return { found: false };
            }"""
        )

        assert result.get("found"), "no workflow_phase with agents + fold bar found"
        # One click flips the children container's hidden state; a second
        # restores it — the fold machine operates on the synthetic phase node.
        assert result["d1"] != result["d0"]
        assert result["d2"] == result["d0"]
