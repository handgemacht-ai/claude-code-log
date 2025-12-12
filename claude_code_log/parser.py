#!/usr/bin/env python3
"""Parse and extract data from Claude transcript JSONL files."""

import json
import re
from typing import Any, Dict, List, Optional, Union, cast
from datetime import datetime

from anthropic.types.text_block import TextBlock
from anthropic.types.thinking_block import ThinkingBlock

from .models import (
    ContentItem,
    TextContent,
    ThinkingContent,
    # User message content models
    SlashCommandContent,
    CommandOutputContent,
    BashInputContent,
)


def extract_text_content(content: Union[str, List[ContentItem], None]) -> str:
    """Extract text content from Claude message content structure.

    Supports both custom models (TextContent, ThinkingContent) and official
    Anthropic SDK types (TextBlock, ThinkingBlock).
    """
    if content is None:
        return ""
    if isinstance(content, list):
        text_parts: List[str] = []
        for item in content:
            # Handle text content (custom TextContent or Anthropic TextBlock)
            if isinstance(item, (TextContent, TextBlock)):
                text_parts.append(item.text)
            # Skip thinking content (custom ThinkingContent or Anthropic ThinkingBlock)
            elif isinstance(item, (ThinkingContent, ThinkingBlock)):
                continue
        return "\n".join(text_parts)
    else:
        return str(content) if content else ""


def parse_timestamp(timestamp_str: str) -> Optional[datetime]:
    """Parse ISO timestamp to datetime object."""
    try:
        return datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


# =============================================================================
# User Message Content Parsing
# =============================================================================


def parse_slash_command(text: str) -> Optional[SlashCommandContent]:
    """Parse slash command tags from text.

    Args:
        text: Raw text that may contain command-name, command-args, command-contents tags

    Returns:
        SlashCommandContent if tags found, None otherwise
    """
    command_name_match = re.search(r"<command-name>([^<]+)</command-name>", text)
    if not command_name_match:
        return None

    command_name = command_name_match.group(1).strip()

    command_args_match = re.search(r"<command-args>([^<]*)</command-args>", text)
    command_args = command_args_match.group(1).strip() if command_args_match else ""

    # Parse command contents, handling JSON format
    command_contents_match = re.search(
        r"<command-contents>(.+?)</command-contents>", text, re.DOTALL
    )
    command_contents = ""
    if command_contents_match:
        contents_text = command_contents_match.group(1).strip()
        # Try to parse as JSON and extract the text field
        try:
            contents_json: Any = json.loads(contents_text)
            if isinstance(contents_json, dict) and "text" in contents_json:
                text_dict = cast(Dict[str, Any], contents_json)
                text_value = text_dict["text"]
                command_contents = str(text_value)
            else:
                command_contents = contents_text
        except json.JSONDecodeError:
            command_contents = contents_text

    return SlashCommandContent(
        command_name=command_name,
        command_args=command_args,
        command_contents=command_contents,
    )


def parse_command_output(text: str) -> Optional[CommandOutputContent]:
    """Parse command output tags from text.

    Args:
        text: Raw text that may contain local-command-stdout tags

    Returns:
        CommandOutputContent if tags found, None otherwise
    """
    stdout_match = re.search(
        r"<local-command-stdout>(.*?)</local-command-stdout>",
        text,
        re.DOTALL,
    )
    if not stdout_match:
        return None

    stdout_content = stdout_match.group(1).strip()
    # Check if content looks like markdown (starts with markdown headers)
    is_markdown = bool(re.match(r"^#+\s+", stdout_content, re.MULTILINE))

    return CommandOutputContent(stdout=stdout_content, is_markdown=is_markdown)


def parse_bash_input(text: str) -> Optional[BashInputContent]:
    """Parse bash input tags from text.

    Args:
        text: Raw text that may contain bash-input tags

    Returns:
        BashInputContent if tags found, None otherwise
    """
    bash_match = re.search(r"<bash-input>(.*?)</bash-input>", text, re.DOTALL)
    if not bash_match:
        return None

    return BashInputContent(command=bash_match.group(1).strip())
