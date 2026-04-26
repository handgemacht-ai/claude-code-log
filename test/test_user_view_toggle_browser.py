"""Playwright tests for the user-content view toggle (Markdown / raw).

Covers scenarios that the server-side unit tests can't reach because
they depend on CSS specificity and live JS state:

- Default page load: Markdown view visible, raw hidden.
- Global toggle: flips untouched messages to raw and back.
- Per-message toggle: flips one message independently.
- Persistence: localStorage choice survives a reload.
- Precedence: explicit per-message "md" wins over global "raw".
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import List

import pytest
from playwright.sync_api import Page, expect

from claude_code_log.converter import load_transcript
from claude_code_log.html.renderer import generate_html
from claude_code_log.models import TranscriptEntry


def _user_entry(uuid: str, text: str, ts: str = "2026-01-01T10:00:00.000Z") -> dict:
    return {
        "type": "user",
        "timestamp": ts,
        "parentUuid": None,
        "isSidechain": False,
        "userType": "external",
        "cwd": "/tmp",
        "sessionId": "test_session",
        "version": "1.0.0",
        "uuid": uuid,
        "message": {
            "role": "user",
            "content": [{"type": "text", "text": text}],
        },
    }


class TestUserViewToggleBrowser:
    """Live-browser tests for Markdown ↔ raw toggles."""

    def setup_method(self) -> None:
        self.temp_files: List[Path] = []

    def teardown_method(self) -> None:
        for f in self.temp_files:
            try:
                f.unlink()
            except FileNotFoundError:
                pass

    def _render(self, entries: List[dict], title: str = "User View Test") -> Path:
        """Write entries to a JSONL, render to HTML, return the HTML path."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
        ) as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")
            jsonl_path = Path(f.name)
        self.temp_files.append(jsonl_path)

        messages: List[TranscriptEntry] = load_transcript(jsonl_path)
        html_content = generate_html(messages, title)
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".html", delete=False, encoding="utf-8"
        ) as f:
            f.write(html_content)
            html_path = Path(f.name)
        self.temp_files.append(html_path)
        return html_path

    def _goto_clean(self, page: Page, html: Path) -> None:
        """Navigate to the rendered HTML with a guaranteed-empty
        localStorage. Chromium shares localStorage across all file://
        URLs (single null origin), so tests in the same session can
        leak the global raw/md preference into each other. Clearing
        + reloading here gives every test a deterministic starting
        state — equivalent to what the user sees on a fresh browser."""
        page.goto(f"file://{html}")
        page.evaluate("() => localStorage.clear()")
        page.reload()

    @pytest.mark.browser
    def test_default_load_shows_markdown(self, page: Page) -> None:
        """On a fresh load, the rendered Markdown is visible and the raw
        pre is hidden."""
        html = self._render([_user_entry("u1", "# Hi\n\n**bold**")])
        self._goto_clean(page, html)
        expect(page.locator(".user-md").first).to_be_visible()
        expect(page.locator(".user-raw").first).to_be_hidden()

    @pytest.mark.browser
    def test_global_toggle_flips_default_messages(self, page: Page) -> None:
        """Regression guard for the bug monk caught: global raw toggle
        had no effect on messages the user hadn't per-message-toggled,
        because every wrapper shipped with data-user-view='md' baked in.
        After the fix, clicking the global toggle flips them correctly."""
        html = self._render([_user_entry("u1", "# Hi\n\n**bold**")])
        self._goto_clean(page, html)

        md = page.locator(".user-md").first
        raw = page.locator(".user-raw").first

        expect(md).to_be_visible()
        expect(raw).to_be_hidden()

        page.locator("#toggleUserView").click()
        expect(md).to_be_hidden()
        expect(raw).to_be_visible()

        page.locator("#toggleUserView").click()
        expect(md).to_be_visible()
        expect(raw).to_be_hidden()

    @pytest.mark.browser
    def test_per_message_toggle_affects_only_that_message(self, page: Page) -> None:
        """Per-message toggle flips one message without affecting others."""
        html = self._render(
            [
                _user_entry("u1", "first message", "2026-01-01T10:00:00.000Z"),
                _user_entry("u2", "second message", "2026-01-01T10:01:00.000Z"),
            ]
        )
        self._goto_clean(page, html)

        mds = page.locator(".user-md")
        raws = page.locator(".user-raw")
        # Both start on md.
        expect(mds.nth(0)).to_be_visible()
        expect(raws.nth(0)).to_be_hidden()
        expect(mds.nth(1)).to_be_visible()
        expect(raws.nth(1)).to_be_hidden()

        # Flip the first one only.
        page.locator(".user-view-toggle").first.click()
        expect(mds.nth(0)).to_be_hidden()
        expect(raws.nth(0)).to_be_visible()
        expect(mds.nth(1)).to_be_visible()  # unchanged
        expect(raws.nth(1)).to_be_hidden()

    @pytest.mark.browser
    def test_per_message_md_overrides_global_raw(self, page: Page) -> None:
        """A message explicitly locked to md via the per-message toggle
        keeps showing Markdown even when the global raw toggle is on."""
        html = self._render(
            [
                _user_entry("u1", "locked to md"),
                _user_entry("u2", "default message", "2026-01-01T10:01:00.000Z"),
            ]
        )
        self._goto_clean(page, html)

        # Click the first message's per-message toggle twice to get an
        # explicit data-user-view='md' (round-trip through 'raw').
        first_toggle = page.locator(".user-view-toggle").first
        first_toggle.click()  # → raw
        first_toggle.click()  # → md (explicit)

        # Now flip the global raw toggle.
        page.locator("#toggleUserView").click()

        mds = page.locator(".user-md")
        raws = page.locator(".user-raw")
        # First message: explicit md wins over global raw.
        expect(mds.nth(0)).to_be_visible()
        expect(raws.nth(0)).to_be_hidden()
        # Second message: no per-message override, global raw applies.
        expect(mds.nth(1)).to_be_hidden()
        expect(raws.nth(1)).to_be_visible()

    @pytest.mark.browser
    def test_per_message_click_under_global_raw_flips_in_one_click(
        self, page: Page
    ) -> None:
        """Regression guard for the 2-click bug (coderabbit review #119).

        Before the JS was taught to read the effective current view,
        clicking a per-message toggle while the global raw toggle was
        active would set ``data-user-view='raw'`` — matching the view
        that was already showing — so nothing changed visually and the
        user needed a second click to actually reach Markdown. After
        the fix, one click is enough."""
        html = self._render([_user_entry("u1", "# Hi\n\n**bold**")])
        self._goto_clean(page, html)

        md = page.locator(".user-md").first
        raw = page.locator(".user-raw").first

        # Turn on the global raw toggle → md hidden, raw visible.
        page.locator("#toggleUserView").click()
        expect(md).to_be_hidden()
        expect(raw).to_be_visible()

        # Per-message button on a message with no explicit override
        # should show 'md' (the view you'd switch to) under global raw.
        per_message = page.locator(".user-view-toggle").first
        expect(per_message).to_have_text("md")

        # One click on the per-message toggle must flip to md.
        per_message.click()
        expect(md).to_be_visible()
        expect(raw).to_be_hidden()

    @pytest.mark.browser
    def test_global_choice_persists_across_reload(self, page: Page) -> None:
        """localStorage persists the global raw/md preference."""
        html = self._render([_user_entry("u1", "# Hi\n\n**bold**")])
        self._goto_clean(page, html)

        page.locator("#toggleUserView").click()  # → raw
        expect(page.locator(".user-raw").first).to_be_visible()

        # Reload — the preference should survive.
        page.reload()
        expect(page.locator(".user-md").first).to_be_hidden()
        expect(page.locator(".user-raw").first).to_be_visible()
