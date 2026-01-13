"""Test timezone conversion in index.html."""

import pytest
from pathlib import Path


@pytest.mark.browser
def test_index_timezone_conversion(page):
    """Test that timestamps are converted to local timezone in index page."""
    # Generate index page
    index_path = Path.home() / ".claude" / "projects" / "index.html"

    if not index_path.exists():
        pytest.skip("Index file not found")

    # Load the page
    page.goto(f"file://{index_path}")

    # Wait for DOM to be ready
    page.wait_for_load_state("domcontentloaded")

    # Check if there are any timestamp elements with data-timestamp attribute
    timestamp_elements = page.query_selector_all(".timestamp[data-timestamp]")

    if len(timestamp_elements) == 0:
        pytest.skip("No timestamps found in index page")

    # Get the first timestamp element
    first_timestamp = timestamp_elements[0]

    # Check that the timestamp has been converted (should contain timezone info)
    timestamp_text = first_timestamp.inner_text()

    # Should contain either a timezone abbreviation or "(UTC)"
    assert "(" in timestamp_text and ")" in timestamp_text, (
        f"Timestamp should contain timezone info in parentheses: {timestamp_text}"
    )

    # Check that the title attribute contains UTC and local time info
    title = first_timestamp.get_attribute("title")
    assert title is not None, "Timestamp should have a title attribute"
    assert "UTC:" in title, f"Title should contain UTC time: {title}"

    # Check that timestamps don't have commas between date and time
    assert ", " not in timestamp_text.split("(")[0], (
        f"Timestamp should not have comma between date and time: {timestamp_text}"
    )

    # If there's a time range, check it's formatted correctly
    if first_timestamp.get_attribute("data-timestamp-end"):
        # Should have " to " in the middle
        assert " to " in timestamp_text, (
            f"Time range should contain ' to ': {timestamp_text}"
        )

        # Title should show the range for both UTC and local
        assert " to " in title, f"Title should show time range: {title}"

    print(f"✓ Timestamp conversion working: {timestamp_text}")
    print(f"✓ Title: {title}")
    print("✓ No comma in timestamp format")


@pytest.mark.browser
def test_session_navigation_timezone_conversion(page):
    """Test that session navigation timestamps are converted to local timezone."""
    # Use test data file
    test_html_path = Path("/tmp/test_output_tz.html")

    if not test_html_path.exists():
        pytest.skip("Test HTML file not found")

    # Load the page
    page.goto(f"file://{test_html_path}")

    # Wait for DOM to be ready
    page.wait_for_load_state("domcontentloaded")

    # Find session navigation timestamps
    session_timestamps = page.query_selector_all(
        ".session-link-meta .timestamp[data-timestamp]"
    )

    if len(session_timestamps) == 0:
        pytest.skip("No session navigation timestamps found")

    # Get the first session timestamp
    first_session_ts = session_timestamps[0]
    session_text = first_session_ts.inner_text()

    # Check that it has timezone info
    assert "(" in session_text and ")" in session_text, (
        f"Session timestamp should have timezone info: {session_text}"
    )

    # Check no comma in format
    assert ", " not in session_text.split("(")[0], (
        f"Session timestamp should not have comma: {session_text}"
    )

    # Check title attribute
    title = first_session_ts.get_attribute("title")
    assert title is not None, "Session timestamp should have title"
    assert "UTC:" in title, f"Title should contain UTC: {title}"

    print(f"✓ Session navigation timezone conversion working: {session_text}")
    print(f"✓ Title: {title}")
