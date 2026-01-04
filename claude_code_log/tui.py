#!/usr/bin/env python3
"""Interactive Terminal User Interface for Claude Code Log."""

import os
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar, List, Optional, cast

from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Container, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    DataTable,
    Footer,
    Header,
    Label,
    MarkdownViewer,
    Static,
    Tree,
)
from textual.reactive import reactive

from .cache import CacheManager, SessionCacheData, get_library_version
from .converter import (
    ensure_fresh_cache,
    get_file_extension,
    load_directory_transcripts,
)
from .renderer import get_renderer
from .utils import get_project_display_name


class ProjectSelector(App[Path]):
    """TUI for selecting a Claude project when multiple are found."""

    CSS = """
    #info-container {
        height: 3;
        border: solid $primary;
        margin-bottom: 1;
    }

    DataTable {
        height: auto;
    }
    """

    TITLE = "Claude Code Log - Project Selector"
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("q", "quit", "Quit"),
        Binding("s", "select_project", "Select Project"),
    ]

    selected_project_path: reactive[Optional[Path]] = reactive(
        cast(Optional[Path], None)
    )
    projects: list[Path]
    matching_projects: list[Path]
    archived_projects: set[Path]

    def __init__(
        self,
        projects: list[Path],
        matching_projects: list[Path],
        archived_projects: Optional[set[Path]] = None,
    ):
        """Initialize the project selector."""
        super().__init__()
        self.theme = "gruvbox"
        self.projects = projects
        self.matching_projects = matching_projects
        self.archived_projects = archived_projects or set()

    def compose(self) -> ComposeResult:
        """Create the UI layout."""
        yield Header()

        with Container(id="main-container"):
            with Vertical():
                # Info
                with Container(id="info-container"):
                    info_text = f"Found {len(self.projects)} projects total"
                    if self.matching_projects:
                        info_text += (
                            f", {len(self.matching_projects)} match current directory"
                        )
                    yield Label(info_text, id="info")

                # Project table
                yield DataTable[str](id="projects-table", cursor_type="row")

        yield Footer()

    def on_mount(self) -> None:
        """Initialize the application when mounted."""
        self.populate_table()

    def on_resize(self) -> None:
        """Handle terminal resize events."""
        self.populate_table()

    def populate_table(self) -> None:
        """Populate the projects table."""
        table = cast(DataTable[str], self.query_one("#projects-table", DataTable))
        table.clear(columns=True)

        # Add columns
        table.add_column("Project", width=self.size.width - 13)
        table.add_column("Sessions", width=10)

        # Add rows
        for project_path in self.projects:
            is_archived = project_path in self.archived_projects
            try:
                cache_manager = CacheManager(project_path, get_library_version())
                project_cache = cache_manager.get_cached_project_data()

                if not project_cache or not project_cache.sessions:
                    if not is_archived:
                        # Only try to build cache for non-archived projects
                        try:
                            ensure_fresh_cache(project_path, cache_manager, silent=True)
                            # Reload cache after ensuring it's fresh
                            project_cache = cache_manager.get_cached_project_data()
                        except Exception:
                            # If cache building fails, continue with empty cache
                            project_cache = None

                # Get project info
                session_count = (
                    len(project_cache.sessions)
                    if project_cache and project_cache.sessions
                    else 0
                )

                # Create project display - just use the directory name
                project_display = f"  {project_path.name}"

                # Add indicator if matches current directory
                if project_path in self.matching_projects:
                    project_display = f"→ {project_display[2:]}"

                # Add archived indicator
                if is_archived:
                    project_display = f"{project_display} [ARCHIVED]"

                table.add_row(
                    project_display,
                    str(session_count),
                )
            except Exception:
                # If we can't read cache, show basic info
                project_display = f"  {project_path.name}"
                if project_path in self.matching_projects:
                    project_display = f"→ {project_display[2:]}"
                if is_archived:
                    project_display = f"{project_display} [ARCHIVED]"

                table.add_row(
                    project_display,
                    "Unknown",
                )

    def on_data_table_row_highlighted(self, _event: DataTable.RowHighlighted) -> None:
        """Handle row highlighting (cursor movement) in the projects table."""
        self._update_selected_project_from_cursor()

    def _update_selected_project_from_cursor(self) -> None:
        """Update the selected project based on the current cursor position."""
        try:
            table = cast(DataTable[str], self.query_one("#projects-table", DataTable))
            row_data = table.get_row_at(table.cursor_row)
            if row_data:
                # Extract project display from the first column
                project_display = str(row_data[0]).strip()

                # Remove the arrow indicator if present
                if project_display.startswith("→"):
                    project_display = project_display[1:].strip()

                # Remove the archived indicator if present
                if project_display.endswith(" [ARCHIVED]"):
                    project_display = project_display[:-11].strip()

                # Find the matching project path
                for project_path in self.projects:
                    if project_path.name == project_display:
                        self.selected_project_path = project_path
                        break
        except Exception:
            # If widget not mounted yet or we can't get the row data, don't update selection
            pass

    def action_select_project(self) -> None:
        """Select the highlighted project."""
        if self.selected_project_path:
            self.exit(self.selected_project_path)
        else:
            # If no selection, use the first project
            if self.projects:
                self.exit(self.projects[0])

    async def action_quit(self) -> None:
        """Quit the application with proper cleanup."""
        self.exit(None)


class MarkdownViewerScreen(ModalScreen[None]):
    """Modal screen for viewing Markdown content with table of contents."""

    CSS = """
    MarkdownViewerScreen {
        align: center middle;
    }

    #md-container {
        width: 95%;
        height: 95%;
        border: solid $primary;
        background: $surface;
    }

    #md-header {
        dock: top;
        height: 3;
        background: $primary;
        color: $text;
        text-align: center;
        padding: 1;
    }

    #md-viewer {
        height: 1fr;
    }

    /* Limit ToC width to ~1/3 of the viewer */
    #md-viewer MarkdownTableOfContents {
        max-width: 60;
    }

    #md-footer {
        dock: bottom;
        height: 1;
        background: $primary-darken-2;
        color: $text-muted;
        text-align: center;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "dismiss", "Close", show=True),
        Binding("q", "dismiss", "Close", show=False),
    ]

    def __init__(self, content: str, title: str = "Markdown Viewer") -> None:
        super().__init__()
        self.md_content = content
        self.md_title = title

    def compose(self) -> ComposeResult:
        with Container(id="md-container"):
            yield Static(self.md_title, id="md-header")
            yield MarkdownViewer(
                self.md_content, id="md-viewer", show_table_of_contents=True
            )
            yield Static("Press ESC or q to close | t: toggle ToC", id="md-footer")

    def on_mount(self) -> None:
        """Customize ToC tree after mount."""
        self.call_later(self._customize_toc_tree)

    def _customize_toc_tree(self) -> None:
        """Customize ToC: collapse to 3 levels and remove roman numeral prefixes."""
        try:
            viewer = self.query_one("#md-viewer", MarkdownViewer)
            toc = viewer.query_one("MarkdownTableOfContents")
            tree = cast(Tree[Any], toc.query_one(Tree))

            # Clean up labels (remove roman numerals and message type prefixes)
            self._clean_toc_labels(tree.root)

            # Collapse all, then expand root, children, and grandchildren
            tree.root.collapse_all()
            tree.root.expand()
            for child in tree.root.children:
                child.expand()
                for grandchild in child.children:
                    grandchild.expand()
        except Exception:
            pass  # ToC might not be ready yet, or tree structure differs

    def _clean_toc_labels(self, node: Any) -> None:
        """Recursively clean tree node labels for a cleaner ToC."""
        import re

        # Unicode roman numerals used by Textual's MarkdownTableOfContents
        roman_numerals = "ⅠⅡⅢⅣⅤⅥ"
        # Message type prefixes that add clutter in ToC context
        clutter_prefixes = (
            "User: ",
            "Assistant: ",
            "Thinking: ",
            "Sub-assistant: ",
        )

        label = str(node.label)

        # Strip leading roman numeral and space (e.g., "Ⅱ Heading" -> "Heading")
        if label and label[0] in roman_numerals:
            label = label[2:] if len(label) > 1 else label

        # Strip message type prefixes wherever they appear
        # (they come after the emoji, e.g., "🤷 User: *text*" -> "🤷 *text*")
        for prefix in clutter_prefixes:
            if prefix in label:
                label = label.replace(prefix, "", 1)
                break

        # Simplify "Task (details): " to "Task: " (details are redundant)
        label = re.sub(r"Task \([^)]+\): ", "Task: ", label)

        node.set_label(label)
        for child in node.children:
            self._clean_toc_labels(child)

    async def action_dismiss(self, result: None = None) -> None:
        self.dismiss(result)


class DeleteConfirmScreen(ModalScreen[bool]):
    """Modal screen for confirming session deletion."""

    CSS = """
    DeleteConfirmScreen {
        align: center middle;
    }

    #delete-container {
        width: 60;
        height: auto;
        border: solid $error;
        background: $surface;
        padding: 1 2;
    }

    #delete-title {
        text-align: center;
        text-style: bold;
        color: $error;
        margin-bottom: 1;
    }

    #delete-message {
        margin-bottom: 1;
    }

    #delete-warning {
        color: $warning;
        margin-bottom: 1;
    }

    #delete-buttons {
        layout: horizontal;
        align: center middle;
        height: auto;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("y", "confirm", "Yes, delete"),
        Binding("n", "cancel", "No, cancel"),
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(self, session_id: str, is_archived: bool = False) -> None:
        super().__init__()
        self.session_id = session_id
        self.is_archived = is_archived

    def compose(self) -> ComposeResult:
        with Container(id="delete-container"):
            yield Static("Delete Session from Cache", id="delete-title")
            yield Static(
                f"Session: {self.session_id[:8]}...",
                id="delete-message",
            )
            if self.is_archived:
                yield Static(
                    "This is an archived session with no JSONL file.\n"
                    "Deletion is PERMANENT and cannot be undone!",
                    id="delete-warning",
                )
            else:
                yield Static(
                    "The JSONL file will remain.\n"
                    "The session can be restored from the file.",
                    id="delete-warning",
                )
            yield Static("Press [y] to delete or [n] to cancel", id="delete-buttons")

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class SessionBrowser(App[Optional[str]]):
    """Interactive TUI for browsing and managing Claude Code Log sessions."""

    CSS = """
    #main-container {
        padding: 0;
        height: 100%;
    }
    
    #stats-container {
        height: auto;
        min-height: 3;
        max-height: 5;
        border: solid $primary;
    }
    
    .stat-label {
        color: $primary;
        text-style: bold;
    }
    
    .stat-value {
        color: $accent;
    }
    
    #sessions-table {
        height: 1fr;
    }
    
    #expanded-content {
        display: none;
        height: 1fr;
        border: solid $secondary;
        overflow-y: auto;
    }
    """

    TITLE = "Claude Code Log - Session Browser"
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("q", "quit", "Quit"),
        Binding("a", "toggle_view_mode", "Toggle Archived"),
        Binding("h", "export_selected", "Open HTML page"),
        Binding("m", "export_markdown", "Open Markdown"),
        Binding("v", "view_markdown", "View Markdown"),
        # Hidden "force regenerate" variants (uppercase)
        Binding("H", "force_export_html", "Force HTML", show=False),
        Binding("M", "force_export_markdown", "Force Markdown", show=False),
        Binding("V", "force_view_markdown", "Force View", show=False),
        Binding("c", "resume_selected", "Resume in Claude Code"),
        Binding("r", "restore_jsonl", "Restore JSONL"),
        Binding("d", "delete_from_cache", "Delete from Cache"),
        Binding("e", "toggle_expanded", "Toggle Expanded View"),
        Binding("p", "back_to_projects", "Open Project Selector"),
        Binding("?", "toggle_help", "Help"),
    ]

    selected_session_id: reactive[Optional[str]] = reactive(cast(Optional[str], None))
    is_expanded: reactive[bool] = reactive(False)
    view_mode: reactive[str] = reactive("current")  # "current" or "archived"
    project_path: Path
    cache_manager: CacheManager
    sessions: dict[str, SessionCacheData]
    archived_sessions: dict[str, SessionCacheData]

    def __init__(self, project_path: Path, is_archived: bool = False):
        """Initialize the session browser with a project path."""
        super().__init__()
        self.theme = "gruvbox"
        self.project_path = project_path
        self.is_archived_project = is_archived
        self.cache_manager = CacheManager(project_path, get_library_version())
        self.sessions = {}
        self.archived_sessions = {}

    def compose(self) -> ComposeResult:
        """Create the UI layout."""
        yield Header()

        with Container(id="main-container"):
            with Vertical():
                # Project statistics
                with Container(id="stats-container"):
                    yield Label("Loading project information...", id="stats")

                # Session table
                yield DataTable[str](id="sessions-table", cursor_type="row")

                # Expanded content container (initially hidden)
                yield Static("", id="expanded-content")

        yield Footer()

    def on_mount(self) -> None:
        """Initialize the application when mounted."""
        self.load_sessions()

    def on_resize(self) -> None:
        """Handle terminal resize events."""
        # Only update if we have sessions loaded
        if self.sessions:
            self.populate_table()
            self.update_stats()

    def load_sessions(self) -> None:
        """Load session information from cache or build cache if needed."""
        # For archived projects, just load from cache (no JSONL files to check)
        if self.is_archived_project:
            project_cache = self.cache_manager.get_cached_project_data()
            if project_cache and project_cache.sessions:
                # All sessions are "archived" for fully archived projects
                self.sessions = {}
                self.archived_sessions = project_cache.sessions
                # Automatically switch to archived view mode
                self.view_mode = "archived"
            else:
                self.sessions = {}
                self.archived_sessions = {}
            # Update UI
            try:
                self.populate_table()
                self.update_stats()
            except Exception:
                pass
            return

        # Check if we need to rebuild cache by checking for modified files
        # Exclude agent files - they are loaded via session references
        jsonl_files = [
            f
            for f in self.project_path.glob("*.jsonl")
            if not f.name.startswith("agent-")
        ]
        valid_session_ids = {f.stem for f in jsonl_files}
        modified_files = self.cache_manager.get_modified_files(jsonl_files)

        # Get cached project data
        project_cache = self.cache_manager.get_cached_project_data()

        if project_cache and project_cache.sessions and not modified_files:
            # Use cached session data - cache is up to date
            self.sessions = project_cache.sessions
        else:
            # Need to build cache - use ensure_fresh_cache to populate cache if needed
            try:
                # Use ensure_fresh_cache to build cache (it handles all the session processing)
                ensure_fresh_cache(self.project_path, self.cache_manager, silent=True)

                # Now get the updated cache data
                project_cache = self.cache_manager.get_cached_project_data()
                if project_cache and project_cache.sessions:
                    self.sessions = project_cache.sessions
                else:
                    self.sessions = {}

            except Exception:
                # Don't show notification during startup - just return
                return

        # Only compute archived sessions if there are JSONL files to compare against
        # (in test environments, there may be cached sessions but no JSONL files)
        if valid_session_ids:
            # Load archived sessions (cached but JSONL deleted)
            self.archived_sessions = self.cache_manager.get_archived_sessions(
                valid_session_ids
            )

            # Filter current sessions to only those with existing JSONL files
            self.sessions = {
                sid: data
                for sid, data in self.sessions.items()
                if sid in valid_session_ids
            }
        else:
            # No JSONL files to compare - treat all sessions as current
            self.archived_sessions = {}

        # Only update UI if we're in app context
        try:
            self.populate_table()
            self.update_stats()
        except Exception:
            # Not in app context, skip UI updates
            pass

    def populate_table(self) -> None:
        """Populate the sessions table with session data."""
        table = cast(DataTable[str], self.query_one("#sessions-table", DataTable))
        table.clear(columns=True)

        # Calculate responsive column widths based on terminal size
        terminal_width = self.size.width

        # Fixed widths for specific columns
        session_id_width = 10
        messages_width = 10
        tokens_width = 14

        # Responsive time column widths - shorter on narrow terminals
        time_width = 16 if terminal_width >= 120 else 12

        # Calculate remaining space for title column
        fixed_width = (
            session_id_width + messages_width + tokens_width + (time_width * 2)
        )
        padding_estimate = 8  # Account for column separators and padding
        title_width = max(30, terminal_width - fixed_width - padding_estimate)

        # Add columns with calculated widths
        table.add_column("Session ID", width=session_id_width)
        table.add_column("Title or First Message", width=title_width)
        table.add_column("Start Time", width=time_width)
        table.add_column("End Time", width=time_width)
        table.add_column("Messages", width=messages_width)
        table.add_column("Tokens", width=tokens_width)

        # Select sessions based on view mode
        display_sessions = (
            self.archived_sessions if self.view_mode == "archived" else self.sessions
        )

        # Sort sessions by start time (newest first)
        sorted_sessions = sorted(
            display_sessions.items(), key=lambda x: x[1].first_timestamp, reverse=True
        )

        # Add rows
        for session_id, session_data in sorted_sessions:
            # Format timestamps - use short format for narrow terminals
            use_short_format = terminal_width < 120
            start_time = self.format_timestamp(
                session_data.first_timestamp, short_format=use_short_format
            )
            end_time = self.format_timestamp(
                session_data.last_timestamp, short_format=use_short_format
            )

            # Format token count
            total_tokens = (
                session_data.total_input_tokens + session_data.total_output_tokens
            )
            token_display = f"{total_tokens:,}" if total_tokens > 0 else "-"

            # Get summary or first user message
            preview = (
                session_data.summary
                or session_data.first_user_message
                or "No preview available"
            )
            # Let Textual handle truncation based on column width

            table.add_row(
                session_id[:8],
                preview,
                start_time,
                end_time,
                str(session_data.message_count),
                token_display,
            )

    def update_stats(self) -> None:
        """Update the project statistics display."""
        # Use appropriate session dict based on view mode
        display_sessions = (
            self.archived_sessions if self.view_mode == "archived" else self.sessions
        )
        total_sessions = len(display_sessions)
        total_messages = sum(s.message_count for s in display_sessions.values())
        total_tokens = sum(
            s.total_input_tokens + s.total_output_tokens
            for s in display_sessions.values()
        )

        # Get project name using shared logic
        working_directories: List[str] = []
        try:
            working_directories = self.cache_manager.get_working_directories()
        except Exception:
            # Fall back to directory name if cache fails
            pass

        project_name = get_project_display_name(
            self.project_path.name, working_directories
        )

        # Find date range
        if display_sessions:
            timestamps = [
                s.first_timestamp
                for s in display_sessions.values()
                if s.first_timestamp
            ]
            earliest = min(timestamps) if timestamps else ""
            latest = (
                max(
                    s.last_timestamp
                    for s in display_sessions.values()
                    if s.last_timestamp
                )
                if display_sessions
                else ""
            )

            date_range = ""
            if earliest and latest:
                earliest_date = self.format_timestamp(earliest, date_only=True)
                latest_date = self.format_timestamp(latest, date_only=True)
                if earliest_date == latest_date:
                    date_range = earliest_date
                else:
                    date_range = f"{earliest_date} to {latest_date}"
        else:
            date_range = "No sessions found"

        # Create spaced layout: Project (left), Sessions info (center), Date range (right)
        terminal_width = self.size.width

        # View mode indicator with counts
        if self.view_mode == "archived":
            mode_indicator = (
                f"[bold yellow]ARCHIVED[/bold yellow] ({len(self.archived_sessions)})"
            )
        else:
            archived_count = len(self.archived_sessions)
            if archived_count > 0:
                mode_indicator = (
                    f"[bold green]CURRENT[/bold green] ({archived_count} archived)"
                )
            else:
                mode_indicator = "[bold green]CURRENT[/bold green]"

        # Project section (left aligned)
        project_section = f"[bold]Project:[/bold] {project_name} {mode_indicator}"

        # Sessions info section (center)
        sessions_section = f"[bold]Sessions:[/bold] {total_sessions:,} | [bold]Messages:[/bold] {total_messages:,} | [bold]Tokens:[/bold] {total_tokens:,}"

        # Date range section (right aligned)
        date_section = f"[bold]Date Range:[/bold] {date_range}"

        if terminal_width >= 120:
            # Wide terminal: single row with proper spacing
            # Calculate spacing to distribute sections across width
            project_len = len(
                project_section.replace("[bold]", "").replace("[/bold]", "")
            )
            sessions_len = len(
                sessions_section.replace("[bold]", "").replace("[/bold]", "")
            )
            date_len = len(date_section.replace("[bold]", "").replace("[/bold]", ""))

            # Calculate spaces needed for center and right alignment
            total_content_width = project_len + sessions_len + date_len
            available_space = (
                terminal_width - total_content_width - 4
            )  # Account for margins

            if available_space > 0:
                left_padding = available_space // 2
                right_padding = available_space - left_padding
                stats_text = f"{project_section}{' ' * left_padding}{sessions_section}{' ' * right_padding}{date_section}"
            else:
                # Fallback if terminal too narrow for proper spacing
                stats_text = f"{project_section}  {sessions_section}  {date_section}"
        else:
            # Narrow terminal: multi-row layout
            stats_text = f"{project_section}\n{sessions_section}\n{date_section}"

        stats_label = self.query_one("#stats", Label)
        stats_label.update(stats_text)

    def format_timestamp(
        self, timestamp: str, date_only: bool = False, short_format: bool = False
    ) -> str:
        """Format timestamp for display."""
        try:
            dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            if date_only:
                return dt.strftime("%Y-%m-%d")
            elif short_format:
                return dt.strftime("%m-%d %H:%M")
            else:
                return dt.strftime("%m-%d %H:%M")
        except (ValueError, AttributeError):
            return "Unknown"

    def on_data_table_row_highlighted(self, _event: DataTable.RowHighlighted) -> None:
        """Handle row highlighting (cursor movement) in the sessions table."""
        self._update_selected_session_from_cursor()

        # Update expanded content if it's visible
        if self.is_expanded:
            self._update_expanded_content()

    def _update_selected_session_from_cursor(self) -> None:
        """Update the selected session based on the current cursor position."""
        try:
            table = cast(DataTable[str], self.query_one("#sessions-table", DataTable))
            row_data = table.get_row_at(table.cursor_row)
            if row_data:
                # Extract session ID from the first column (now just first 8 chars)
                session_id_display = str(row_data[0])
                # Find the full session ID in the appropriate dict
                display_sessions = (
                    self.archived_sessions
                    if self.view_mode == "archived"
                    else self.sessions
                )
                for full_session_id in display_sessions.keys():
                    if full_session_id.startswith(session_id_display):
                        self.selected_session_id = full_session_id
                        break
        except Exception:
            # If widget not mounted yet or we can't get the row data, don't update selection
            pass

    def _export_to_browser(self, format: str, *, force: bool = False) -> None:
        """Export session to file and open in browser.

        Args:
            format: Output format - "html" or "md".
            force: If True, always regenerate even if file is up-to-date.
        """
        if not self.selected_session_id:
            self.notify("No session selected", severity="warning")
            return

        format_name = "HTML" if format == "html" else "Markdown"
        try:
            session_file = self._ensure_session_file(
                self.selected_session_id, format, force=force
            )
            if session_file is None:
                self.notify(f"Failed to generate {format_name} file", severity="error")
                return

            webbrowser.open(f"file://{session_file}")
            msg = (
                f"Regenerated: {session_file.name}"
                if force
                else f"Opened: {session_file.name}"
            )
            self.notify(msg)

        except Exception as e:
            self.notify(f"Error with {format_name}: {e}", severity="error")

    def _view_markdown_embedded(self, *, force: bool = False) -> None:
        """View session Markdown in embedded viewer.

        Args:
            force: If True, always regenerate even if file is up-to-date.
        """
        if not self.selected_session_id:
            self.notify("No session selected", severity="warning")
            return

        try:
            session_file = self._ensure_session_file(
                self.selected_session_id, "md", force=force
            )
            if session_file is None:
                self.notify("Failed to generate Markdown file", severity="error")
                return

            content = session_file.read_text(encoding="utf-8")
            title = f"Session: {self.selected_session_id[:8]}..."
            self.push_screen(MarkdownViewerScreen(content, title))
            if force:
                self.notify(f"Regenerated: {session_file.name}")

        except Exception as e:
            self.notify(f"Error viewing Markdown: {e}", severity="error")

    def action_export_selected(self) -> None:
        """Export the selected session to HTML and open in browser."""
        self._export_to_browser("html")

    def action_export_markdown(self) -> None:
        """Export the selected session to Markdown and open in browser."""
        self._export_to_browser("md")

    def action_view_markdown(self) -> None:
        """View the selected session's Markdown in an embedded viewer."""
        self._view_markdown_embedded()

    def action_force_export_html(self) -> None:
        """Force regenerate HTML and open in browser (hidden shortcut: H)."""
        self._export_to_browser("html", force=True)

    def action_force_export_markdown(self) -> None:
        """Force regenerate Markdown and open in browser (hidden shortcut: M)."""
        self._export_to_browser("md", force=True)

    def action_force_view_markdown(self) -> None:
        """Force regenerate and view Markdown in embedded viewer (hidden shortcut: V)."""
        self._view_markdown_embedded(force=True)

    def action_resume_selected(self) -> None:
        """Resume the selected session in Claude Code."""
        if not self.selected_session_id:
            self.notify("No session selected", severity="warning")
            return

        try:
            # Get the session's working directory if available
            session_data = self.sessions.get(self.selected_session_id)
            if session_data and session_data.cwd:
                # Change to the session's working directory
                target_dir = Path(session_data.cwd)
                if target_dir.exists() and target_dir.is_dir():
                    os.chdir(target_dir)
                else:
                    self.notify(
                        f"Warning: Session working directory not found: {session_data.cwd}",
                        severity="warning",
                    )

            # Use Textual's suspend context manager for proper terminal cleanup
            with self.suspend():
                # Terminal is properly restored here by Textual
                # Replace the current process with claude -r <sessionId>
                os.execvp("claude", ["claude", "-r", self.selected_session_id])
        except FileNotFoundError:
            self.notify(
                "Claude Code CLI not found. Make sure 'claude' is in your PATH.",
                severity="error",
            )
        except Exception as e:
            self.notify(f"Error resuming session: {e}", severity="error")

    def _escape_rich_markup(self, text: str) -> str:
        """Escape Rich markup characters in text to prevent parsing errors."""
        if not text:
            return text
        # Escape square brackets which are used for Rich markup
        return text.replace("[", "\\[").replace("]", "\\]")

    def _update_expanded_content(self) -> None:
        """Update the expanded content for the currently selected session."""
        # Use appropriate session dict based on view mode
        display_sessions = (
            self.archived_sessions if self.view_mode == "archived" else self.sessions
        )
        if (
            not self.selected_session_id
            or self.selected_session_id not in display_sessions
        ):
            return

        expanded_content = self.query_one("#expanded-content", Static)
        session_data = display_sessions[self.selected_session_id]

        # Build expanded content
        content_parts: list[str] = []

        # Session ID (safe - UUID format)
        content_parts.append(f"[bold]Session ID:[/bold] {self.selected_session_id}")

        # Summary (if available) - escape markup
        if session_data.summary:
            escaped_summary = self._escape_rich_markup(session_data.summary)
            content_parts.append(f"\n[bold]Summary:[/bold] {escaped_summary}")

        # First user message - escape markup
        if session_data.first_user_message:
            escaped_message = self._escape_rich_markup(session_data.first_user_message)
            content_parts.append(
                f"\n[bold]First User Message:[/bold] {escaped_message}"
            )

        # Working directory (if available) - escape markup
        if session_data.cwd:
            escaped_cwd = self._escape_rich_markup(session_data.cwd)
            content_parts.append(f"\n[bold]Working Directory:[/bold] {escaped_cwd}")

        # Token usage (safe - numeric data)
        total_tokens = (
            session_data.total_input_tokens + session_data.total_output_tokens
        )
        if total_tokens > 0:
            token_details = f"Input: {session_data.total_input_tokens:,} | Output: {session_data.total_output_tokens:,}"
            if session_data.total_cache_creation_tokens > 0:
                token_details += (
                    f" | Cache Creation: {session_data.total_cache_creation_tokens:,}"
                )
            if session_data.total_cache_read_tokens > 0:
                token_details += (
                    f" | Cache Read: {session_data.total_cache_read_tokens:,}"
                )
            content_parts.append(f"\n[bold]Token Usage:[/bold] {token_details}")

        expanded_content.update("\n".join(content_parts))

    def _ensure_session_file(
        self, session_id: str, format: str, *, force: bool = False
    ) -> Optional[Path]:
        """Ensure the session file exists and is up-to-date.

        Regenerates the file if it doesn't exist or is outdated.

        Args:
            session_id: The session ID to generate a file for.
            format: Output format - "html" or "md".
            force: If True, always regenerate even if file is up-to-date.

        Returns:
            Path to the file if successful, None if regeneration failed.
        """
        ext = get_file_extension(format)
        session_file = self.project_path / f"session-{session_id}.{ext}"
        renderer = get_renderer(format)

        # Check if we need to regenerate
        needs_regeneration = (
            force or not session_file.exists() or renderer.is_outdated(session_file)
        )

        if not needs_regeneration:
            return session_file

        # Load messages - from cache for archived sessions, from JSONL otherwise
        try:
            is_archived = session_id in self.archived_sessions
            if is_archived:
                # Load from cache for archived sessions
                messages = self.cache_manager.load_session_entries(session_id)
            else:
                # Load from JSONL files for current sessions
                messages = load_directory_transcripts(
                    self.project_path, self.cache_manager, silent=True
                )
            if not messages:
                return None

            # Build session title - check both dicts
            session_data = self.sessions.get(session_id) or self.archived_sessions.get(
                session_id
            )
            project_cache = self.cache_manager.get_cached_project_data()
            project_name = get_project_display_name(
                self.project_path.name,
                project_cache.working_directories if project_cache else None,
            )
            if session_data and session_data.summary:
                session_title = f"{project_name}: {session_data.summary}"
            elif session_data and session_data.first_user_message:
                preview = session_data.first_user_message
                if len(preview) > 50:
                    preview = preview[:50] + "..."
                session_title = f"{project_name}: {preview}"
            else:
                session_title = f"{project_name}: Session {session_id[:8]}"

            # Generate session content
            session_content = renderer.generate_session(
                messages,
                session_id,
                session_title,
                self.cache_manager,
                self.project_path,
            )
            if session_content:
                session_file.write_text(session_content, encoding="utf-8")
                return session_file
        except Exception:
            return None

        return None

    def action_toggle_expanded(self) -> None:
        """Toggle the expanded view for the selected session."""
        if (
            not self.selected_session_id
            or self.selected_session_id not in self.sessions
        ):
            return

        expanded_content = self.query_one("#expanded-content", Static)

        if self.is_expanded:
            # Hide expanded content
            self.is_expanded = False
            expanded_content.set_styles("display: none;")
            expanded_content.update("")
        else:
            # Show expanded content
            self.is_expanded = True
            expanded_content.set_styles("display: block;")
            self._update_expanded_content()

    def action_toggle_help(self) -> None:
        """Show help information."""
        help_text = (
            "Claude Code Log - Session Browser\n\n"
            "Navigation:\n"
            "- Use arrow keys to select sessions\n"
            "- Expanded content updates automatically when visible\n\n"
            "Actions:\n"
            "- a: Toggle between current and archived sessions\n"
            "- e: Toggle expanded view for session\n"
            "- h: Open selected session's HTML page\n"
            "- m: Open selected session's Markdown file (in browser)\n"
            "- v: View Markdown in embedded viewer\n"
            "- c: Resume selected session in Claude Code (current only)\n"
            "- r: Restore archived session to JSONL (archived only)\n"
            "- p: Open project selector\n"
            "- q: Quit\n\n"
        )
        self.notify(help_text, timeout=10)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """Conditionally enable/disable actions based on view mode."""
        # Resume is only available in current mode
        if action == "resume_selected" and self.view_mode == "archived":
            return False
        # Restore is only available in archived mode
        if action == "restore_jsonl" and self.view_mode == "current":
            return False
        return True

    def action_toggle_view_mode(self) -> None:
        """Toggle between current and archived session views."""
        if self.view_mode == "current":
            if not self.archived_sessions:
                self.notify("No archived sessions found", severity="warning")
                return
            self.view_mode = "archived"
        else:
            self.view_mode = "current"

        # Clear selection and refresh
        self.selected_session_id = None
        self.populate_table()
        self.update_stats()

        # Hide expanded content when switching modes
        if self.is_expanded:
            expanded_content = self.query_one("#expanded-content", Static)
            self.is_expanded = False
            expanded_content.set_styles("display: none;")
            expanded_content.update("")

    def action_restore_jsonl(self) -> None:
        """Restore the selected archived session to a JSONL file."""
        if self.view_mode != "archived":
            self.notify(
                "Restore is only available in archived mode", severity="warning"
            )
            return

        if not self.selected_session_id:
            self.notify("No session selected", severity="warning")
            return

        if self.selected_session_id not in self.archived_sessions:
            self.notify(
                "Selected session not found in archived sessions", severity="error"
            )
            return

        try:
            # Export messages from cache
            messages = self.cache_manager.export_session_to_jsonl(
                self.selected_session_id
            )
            if not messages:
                self.notify("No messages found for session", severity="error")
                return

            # Write to JSONL file
            output_path = self.project_path / f"{self.selected_session_id}.jsonl"
            with open(output_path, "w", encoding="utf-8") as f:
                for msg in messages:
                    f.write(msg + "\n")

            self.notify(
                f"Restored {len(messages)} messages to {output_path.name}",
                severity="information",
            )

            # Ask user if they want to switch to current view
            self._prompt_switch_to_current()

        except Exception as e:
            self.notify(f"Error restoring session: {e}", severity="error")

    def _prompt_switch_to_current(self) -> None:
        """Refresh sessions after restore and switch to current view."""
        # If this was a fully archived project, it's no longer archived
        # since we just restored a JSONL file
        if self.is_archived_project:
            self.is_archived_project = False

        # Reload sessions - this will now detect the restored JSONL file
        self.load_sessions()

        # Switch to current view mode to show the restored session
        if self.view_mode == "archived":
            self.view_mode = "current"
            self.populate_table()
            self.update_stats()

        self.notify(
            "Session restored! Switched to current sessions.",
            timeout=5,
        )

    def action_delete_from_cache(self) -> None:
        """Delete the selected session from the cache."""
        if not self.selected_session_id:
            self.notify("No session selected", severity="warning")
            return

        # Check if session exists in either current or archived sessions
        if (
            self.selected_session_id not in self.sessions
            and self.selected_session_id not in self.archived_sessions
        ):
            self.notify("Selected session not found", severity="error")
            return

        # Determine if this is an archived session (no JSONL to fall back on)
        is_archived_session = self.selected_session_id in self.archived_sessions

        # Push confirmation screen
        self.push_screen(
            DeleteConfirmScreen(
                session_id=self.selected_session_id,
                is_archived=is_archived_session,
            ),
            callback=self._on_delete_confirm,
        )

    def _on_delete_confirm(self, confirmed: Optional[bool]) -> None:
        """Handle deletion confirmation result."""
        if not confirmed or not self.selected_session_id:
            return

        try:
            # Delete from cache
            success = self.cache_manager.delete_session(self.selected_session_id)
            if success:
                self.notify(
                    f"Session {self.selected_session_id[:8]} deleted from cache",
                    severity="information",
                )
                # Clear selection and reload
                self.selected_session_id = None
                self.load_sessions()
            else:
                self.notify("Failed to delete session from cache", severity="error")
        except Exception as e:
            self.notify(f"Error deleting session: {e}", severity="error")

    def action_back_to_projects(self) -> None:
        """Navigate to the project selector."""
        # Exit with a special return value to signal we want to go to project selector
        self.exit(result="back_to_projects")

    async def action_quit(self) -> None:
        """Quit the application with proper cleanup."""
        self.exit()


def run_project_selector(
    projects: list[Path],
    matching_projects: list[Path],
    archived_projects: Optional[set[Path]] = None,
) -> Optional[Path]:
    """Run the project selector TUI and return the selected project path."""
    if not projects:
        print("Error: No projects provided")
        return None

    app = ProjectSelector(projects, matching_projects, archived_projects)
    try:
        return app.run()
    except KeyboardInterrupt:
        # Textual handles terminal cleanup automatically
        print("\nInterrupted")
        return None


def run_session_browser(project_path: Path, is_archived: bool = False) -> Optional[str]:
    """Run the session browser TUI for the given project path."""
    if not project_path.exists():
        # For archived projects, the directory may not exist but cache may
        if is_archived:
            # Try to load from cache
            try:
                cache_manager = CacheManager(project_path, get_library_version())
                project_cache = cache_manager.get_cached_project_data()
                if project_cache and project_cache.sessions:
                    app = SessionBrowser(project_path, is_archived=True)
                    return app.run()
            except Exception:
                pass
        print(f"Error: Project path {project_path} does not exist")
        return None

    if not project_path.is_dir():
        print(f"Error: {project_path} is not a directory")
        return None

    # Check if there are any JSONL files
    jsonl_files = list(project_path.glob("*.jsonl"))
    if not jsonl_files:
        # For archived projects, check if we have cached sessions
        if is_archived:
            try:
                cache_manager = CacheManager(project_path, get_library_version())
                project_cache = cache_manager.get_cached_project_data()
                if project_cache and project_cache.sessions:
                    app = SessionBrowser(project_path, is_archived=True)
                    return app.run()
            except Exception:
                pass
        print(f"Error: No JSONL transcript files found in {project_path}")
        return None

    app = SessionBrowser(project_path, is_archived=is_archived)
    try:
        return app.run()
    except KeyboardInterrupt:
        # Textual handles terminal cleanup automatically
        print("\nInterrupted")
        return None
