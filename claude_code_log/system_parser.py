"""Parser for system transcript entries.

This module handles parsing of SystemTranscriptEntry into MessageContent subclasses:
- SystemMessage: Regular system messages with level (info, warning, error)
- HookSummaryMessage: Hook execution summaries
"""

from typing import Optional, Union

from .models import (
    HookInfo,
    HookSummaryMessage,
    SystemMessage,
    SystemTranscriptEntry,
)
from .parser import parse_meta


def parse_system_transcript(
    transcript: SystemTranscriptEntry,
) -> Optional[Union[SystemMessage, HookSummaryMessage]]:
    """Parse a system transcript entry into a MessageContent.

    Handles:
    - Hook summaries (subtype="stop_hook_summary")
    - Regular system messages with level-specific styling (info, warning, error)

    Args:
        transcript: The system transcript entry to parse

    Returns:
        SystemMessage or HookSummaryMessage (with meta attached),
        or None if the message should be skipped (e.g., silent hook successes)

    Note:
        Slash command messages (<command-name>, <local-command-stdout>) are user messages,
        not system messages. They are handled separately.
    """
    if transcript.subtype == "stop_hook_summary":
        # Skip silent hook successes (no output, no errors)
        if not transcript.hasOutput and not transcript.hookErrors:
            return None
        # Create structured hook summary content
        meta = parse_meta(transcript)
        hook_infos = [
            HookInfo(command=info.get("command", "unknown"))
            for info in (transcript.hookInfos or [])
        ]
        return HookSummaryMessage(
            has_output=bool(transcript.hasOutput),
            hook_errors=transcript.hookErrors or [],
            hook_infos=hook_infos,
            meta=meta,
        )

    if not transcript.content:
        # Skip system messages without content (shouldn't happen normally)
        return None

    # Create structured system content
    meta = parse_meta(transcript)
    level = getattr(transcript, "level", "info")
    return SystemMessage(level=level, text=transcript.content, meta=meta)
