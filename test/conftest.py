"""Pytest configuration and shared fixtures."""

from pathlib import Path
from typing import TYPE_CHECKING, Generator

import pytest

if TYPE_CHECKING:
    from claude_code_log.cache import CacheManager

from test.snapshot_serializers import (
    NormalisedHTMLSerializer,
    NormalisedMarkdownSerializer,
)


# ========== Cache Test Fixtures ==========
# These fixtures use explicit db_path for true test isolation,
# enabling parallel test execution without database conflicts.


@pytest.fixture
def isolated_cache_dir(tmp_path: Path) -> Path:
    """Create an isolated project directory with explicit db_path.

    This fixture ensures each test gets its own SQLite database,
    enabling full parallel execution with pytest-xdist.
    """
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    return project_dir


@pytest.fixture
def isolated_db_path(tmp_path: Path) -> Path:
    """Return an isolated database path for cache tests."""
    return tmp_path / "test-cache.db"


@pytest.fixture
def isolated_cache_manager(
    isolated_cache_dir: Path, isolated_db_path: Path
) -> Generator["CacheManager", None, None]:
    """Create a CacheManager with explicit db_path for test isolation.

    This fixture is preferred over the older temp_project_dir pattern
    as it guarantees database isolation for parallel test execution.
    """
    from claude_code_log.cache import CacheManager

    yield CacheManager(isolated_cache_dir, "1.0.0-test", db_path=isolated_db_path)


@pytest.fixture
def test_data_dir() -> Path:
    """Return path to test data directory."""
    return Path(__file__).parent / "test_data"


@pytest.fixture
def html_snapshot(snapshot):
    """Snapshot fixture with HTML normalisation for regression testing."""
    return snapshot.use_extension(NormalisedHTMLSerializer)


@pytest.fixture
def markdown_snapshot(snapshot):
    """Snapshot fixture with Markdown normalisation for regression testing."""
    return snapshot.use_extension(NormalisedMarkdownSerializer)


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    """Configure browser context for tests."""
    return {
        **browser_context_args,
        "viewport": {"width": 1280, "height": 720},
        "ignore_https_errors": True,
    }


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args):
    """Configure browser launch arguments."""
    return {
        **browser_type_launch_args,
        "headless": True,  # Set to False for debugging
        "slow_mo": 0,  # Add delay for debugging
    }


@pytest.fixture(scope="session")
def _browser_user_data_dir(worker_id):
    """Create a per-worker directory for browser user data (enables HTTP caching).

    Uses a fixed directory in the project that persists across test runs,
    allowing vis-timeline CDN resources to remain cached between runs.
    Each xdist worker gets its own subdirectory to avoid Chromium lock conflicts.
    """
    # Use a fixed cache directory that persists across runs
    cache_base = Path(__file__).parent.parent / ".playwright_cache"
    # Each worker needs its own user data dir to avoid Chromium lock conflicts
    # worker_id is "master" for non-xdist runs, or "gw0", "gw1", etc. for xdist
    worker_dir = cache_base / worker_id
    worker_dir.mkdir(parents=True, exist_ok=True)
    return worker_dir


@pytest.fixture(scope="session")
def _persistent_context(playwright, browser_type_launch_args, _browser_user_data_dir):
    """Create a persistent browser context that shares HTTP cache across tests.

    This solves flaky CDN loading issues by caching resources like vis-timeline
    after the first load.
    """
    browser_type = playwright.chromium
    context = browser_type.launch_persistent_context(
        _browser_user_data_dir,
        **{
            **browser_type_launch_args,
            "viewport": {"width": 1280, "height": 720},
            "ignore_https_errors": True,
        },
    )
    yield context
    context.close()


@pytest.fixture
def context(_persistent_context):
    """Override pytest-playwright's context fixture to use persistent context.

    This ensures all browser tests share the same HTTP cache.
    """
    return _persistent_context


@pytest.fixture
def page(context):
    """Create a new page for each test using the shared persistent context."""
    page = context.new_page()
    yield page
    page.close()
