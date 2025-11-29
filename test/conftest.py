"""Pytest configuration and shared fixtures."""

from pathlib import Path

import pytest

from test.snapshot_serializers import NormalisedHTMLSerializer


@pytest.fixture
def test_data_dir() -> Path:
    """Return path to test data directory."""
    return Path(__file__).parent / "test_data"


@pytest.fixture
def html_snapshot(snapshot):
    """Snapshot fixture with HTML normalisation for regression testing."""
    return snapshot.use_extension(NormalisedHTMLSerializer)


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
