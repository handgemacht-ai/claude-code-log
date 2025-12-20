# Message Types in Claude Code Transcripts

This document describes all message types found in Claude Code JSONL transcript files and their corresponding output representations. The goal is to define an **intermediate representation** that captures the logical message structure independent of HTML rendering.

## Overview

Claude Code transcripts contain messages in JSONL format. Each line represents an input message that gets transformed through:

1. **Input Layer** (JSONL): Raw Claude Code transcript data
2. **Intermediate Layer** (TemplateMessage): Format-neutral logical representation
3. **Output Layer** (HTML): Rendered visual output

This document maps input types to their intermediate and output representations.

---

## Data Flow: From Transcript Entries to Rendered Messages

```text
JSONL Parsing (parser.py)
│
├── UserTranscriptEntry
│   ├── TextContent → User message variants:
│   │   ├── UserSlashCommandContent (isMeta) or SlashCommandContent (<command-name> tags)
│   │   ├── CommandOutputContent (<local-command-stdout> tags)
│   │   ├── BashInputContent (<bash-input> tags)
│   │   ├── CompactedSummaryContent (compacted conversation)
│   │   └── Plain user text
│   ├── ToolResultContent → Tool result messages:
│   │   ├── ReadOutput (cat-n formatted file content)
│   │   ├── EditOutput (cat-n formatted edit result)
│   │   └── Generic tool result text
│   └── ImageContent → Image messages
│
├── AssistantTranscriptEntry
│   ├── TextContent → AssistantTextContent
│   ├── ThinkingContent → ThinkingContentModel
│   └── ToolUseContent → Tool use messages with parsed inputs:
│       ├── ReadInput, WriteInput, EditInput, MultiEditInput
│       ├── BashInput, GlobInput, GrepInput
│       ├── TaskInput, TodoWriteInput, AskUserQuestionInput
│       └── ExitPlanModeInput
│
├── SystemTranscriptEntry
│   ├── SystemContent (level: info/warning/error)
│   └── HookSummaryContent (subtype: stop_hook_summary)
│
├── SummaryTranscriptEntry → Session metadata (not rendered)
│
└── QueueOperationTranscriptEntry
    └── "remove" operation → Steering message (rendered as user)
```

---

## Intermediate Representation: TemplateMessage

The intermediate representation is `TemplateMessage`, a Python class (in `renderer.py`) that captures all fields needed for rendering.

### Key Fields

```python
class TemplateMessage:
    # Identity
    type: str                  # Base type: "user", "assistant", "tool_use", etc.
    message_id: str            # Unique ID within session (e.g., "msg-0", "tool-1")
    uuid: str                  # Original JSONL uuid

    # Content (format-neutral)
    content: Optional[MessageContent]  # Structured content model
    # Note: HTML is generated during template rendering, not stored in the message

    # Display
    message_title: str         # Display title (e.g., "User", "Assistant")
    css_class: str             # CSS classes (derived from type + modifiers)
    modifiers: MessageModifiers  # Format-neutral display traits

    # Metadata
    raw_timestamp: str         # ISO 8601 timestamp
    session_id: str            # Session UUID

    # Hierarchy
    children: List[TemplateMessage]  # Child messages (tree mode)
    ancestry: List[str]        # Parent message IDs for fold/unfold

    # Pairing
    is_paired: bool            # True if part of a pair
    pair_role: Optional[str]   # "pair_first", "pair_last", "pair_middle"

    # Tool-specific
    tool_use_id: Optional[str]  # ID linking tool_use to tool_result
```

### MessageModifiers → CSS Classes

Display traits are stored in `MessageModifiers` (see [Part 6](#part-6-infrastructure-models)) and converted to CSS classes for HTML rendering:

| css_class | Base Type | MessageModifiers Field |
|-----------|-----------|------------------------|
| `"user"` | user | (none) |
| `"user compacted"` | user | `is_compacted=True` |
| `"user slash-command"` | user | `is_slash_command=True` |
| `"user command-output"` | user | `is_command_output=True` |
| `"user sidechain"` | user | `is_sidechain=True` |
| `"user steering"` | user | `is_steering=True` |
| `"assistant"` | assistant | (none) |
| `"assistant sidechain"` | assistant | `is_sidechain=True` |
| `"tool_use"` | tool_use | (none) |
| `"tool_use sidechain"` | tool_use | `is_sidechain=True` |
| `"tool_result"` | tool_result | (none) |
| `"tool_result error"` | tool_result | `is_error=True` |
| `"tool_result sidechain"` | tool_result | `is_sidechain=True` |
| `"thinking"` | thinking | (none) |
| `"system system-info"` | system | `system_level="info"` |
| `"system system-warning"` | system | `system_level="warning"` |
| `"system system-error"` | system | `system_level="error"` |
| `"system system-hook"` | system | `system_level="hook"` |

**Note**: See [css-classes.md](css-classes.md) for complete CSS support status.

---

# Part 1: User Messages (UserTranscriptEntry)

User transcript entries (`type: "user"`) contain human input, tool results, and images.

## 1.1 Content Types in User Messages

User messages contain `ContentItem` instances that are either:
- **TextContent**: User-typed text (with various semantic variants)
- **ToolResultContent**: Results from tool execution
- **ImageContent**: User-attached images

## 1.2 User Text Variants

Based on flags and tag patterns in `TextContent`, user text messages are classified into specialized content types defined in `models.py`.

### Regular User Prompt

- **Condition**: No special flags or tags
- **Content Model**: Plain `TextContent`
- **CSS Class**: `user`
- **Files**: [user.json](messages/user/user.json) | [user.jsonl](messages/user/user.jsonl)

```json
{
  "type": "user",
  "message": {
    "role": "user",
    "content": [{ "type": "text", "text": "Help me fix this bug..." }]
  },
  "isSidechain": false
}
```

### Slash Command (isMeta)

- **Condition**: `isMeta: true` flag
- **Content Model**: `UserSlashCommandContent` (models.py)
- **CSS Class**: `user slash-command`
- **Files**: [user_slash_command.json](messages/user/user_slash_command.json)

```json
{
  "type": "user",
  "message": { "content": "Caveat: The messages below were generated..." },
  "isMeta": true
}
```

```python
@dataclass
class UserSlashCommandContent(MessageContent):
    text: str  # LLM-generated markdown instruction text
```

> **Note**: These are LLM-generated instruction prompts from slash commands.
> The text is markdown formatted and rendered as collapsible markdown.

### Slash Command (Tags)

- **Condition**: Contains `<command-name>` tags
- **Content Model**: `SlashCommandContent` with parsed name/args/contents
- **CSS Class**: `user slash-command`
- **Files**: [user_command.json](messages/user/user_command.json)

```python
@dataclass
class SlashCommandContent(MessageContent):
    command_name: str      # e.g., "/model", "/context"
    command_args: str      # Arguments after command
    command_contents: str  # Content inside command
```

> **Note**: Both built-in commands (e.g., `/init`, `/model`, `/context`) and
> user-defined commands (e.g., `/my-command` from `~/.claude/commands/my-command.md`)
> use the same `<command-name>` tag format. There is no field in the JSONL to
> differentiate between them.

### Command Output

- **Condition**: Contains `<local-command-stdout>` tags
- **Content Model**: `CommandOutputContent`
- **CSS Class**: `user command-output`
- **Files**: [command_output.json](messages/user/command_output.json)

```python
@dataclass
class CommandOutputContent(MessageContent):
    stdout: str        # Command output text
    is_markdown: bool  # True if content appears to be markdown
```

### Bash Input

- **Condition**: Contains `<bash-input>` tags
- **Content Model**: `BashInputContent`
- **CSS Class**: `bash-input` (filtered by User)
- **Files**: [bash_input.json](messages/user/bash_input.json)

```python
@dataclass
class BashInputContent(MessageContent):
    command: str  # The bash command that was executed
```

### Bash Output

The corresponding output uses `<bash-stdout>` and optionally `<bash-stderr>` tags:

- **Condition**: Contains `<bash-stdout>` tags
- **Content Model**: `BashOutputContent`
- **CSS Class**: `bash-output` (filtered by User)
- **Files**: [bash_output.json](messages/user/bash_output.json)

### Compacted Conversation

- **Condition**: Contains "(compacted conversation)" marker
- **Content Model**: `CompactedSummaryContent`
- **CSS Class**: `user compacted`

```python
@dataclass
class CompactedSummaryContent(MessageContent):
    summary_text: str  # The compacted conversation summary
```

### Sidechain User (Sub-agent)

- **Condition**: `isSidechain: true`
- **CSS Class**: `user sidechain`
- **Note**: Typically skipped during rendering (duplicates Task prompt)
- **Files**: [user_sidechain.json](messages/user/user_sidechain.json)

### IDE Notifications

User messages may contain IDE notification tags that are parsed into structured content:

- **Condition**: Contains `<ide_opened_file>`, `<ide_selection>`, or `<ide_diagnostics>` tags
- **Content Model**: `IdeNotificationContent` containing lists of:
  - `IdeOpenedFile`: File open notifications
  - `IdeSelection`: Code selection notifications
  - `IdeDiagnostic`: Diagnostic messages (parsed JSON or raw text fallback)
- **CSS Class**: Notifications rendered as inline elements within user message

```python
@dataclass
class IdeOpenedFile:
    content: str  # Raw content from the tag

@dataclass
class IdeSelection:
    content: str  # Raw selection content

@dataclass
class IdeDiagnostic:
    diagnostics: Optional[List[Dict[str, Any]]]  # Parsed JSON
    raw_content: Optional[str]  # Fallback if parsing failed

@dataclass
class IdeNotificationContent(MessageContent):
    opened_files: List[IdeOpenedFile]
    selections: List[IdeSelection]
    diagnostics: List[IdeDiagnostic]
    remaining_text: str  # Text after notifications extracted
```

## 1.3 Tool Results (ToolResultContent)

Tool results appear as `ToolResultContent` items in user messages, linked to their corresponding `ToolUseContent` via `tool_use_id`.

### Tool Result Output Models

| Tool | Output Model | Key Fields | Files |
|------|--------------|------------|-------|
| Read | `ReadOutput` | file_path, content, start_line, num_lines, is_truncated | [tool_result](messages/tools/Read-tool_result.json) |
| Edit | `EditOutput` | file_path, success, diffs, message, start_line | [tool_result](messages/tools/Edit-tool_result.json) |
| Write | `WriteOutput` *(TODO)* | file_path, success, message | [tool_result](messages/tools/Write-tool_result.json) |
| Bash | `BashOutput` *(TODO)* | stdout, stderr, exit_code, interrupted, is_image | [tool_result](messages/tools/Bash-tool_result.json) |
| Glob | `GlobOutput` *(TODO)* | pattern, files, truncated | [tool_result](messages/tools/Glob-tool_result.json) |
| Grep | `GrepOutput` *(TODO)* | pattern, matches, output_mode, truncated | [tool_result](messages/tools/Grep-tool_result.json) |
| Task | `TaskOutput` *(TODO)* | agent_id, result, is_background | [tool_result](messages/tools/Task-tool_result.json) |
| (error) | — | is_error: true | [Bash error](messages/tools/Bash-tool_result_error.json) |

**(TODO)**: Output model defined in models.py but not yet used - tool results currently handled as raw strings.

### Generic Tool Result

- **CSS Class**: `tool_result`
- **Content**: Raw string or structured content

```json
{
  "type": "user",
  "message": {
    "content": [{
      "type": "tool_result",
      "tool_use_id": "toolu_xxx",
      "is_error": false,
      "content": "..."
    }]
  }
}
```

### Tool Result Error

- **Condition**: `is_error: true`
- **CSS Class**: `tool_result error`
- **Files**: [Bash-tool_result_error.json](messages/tools/Bash-tool_result_error.json)

### Read Tool Result → ReadOutput

Read tool results in cat-n format are parsed into structured `ReadOutput`:
- **Files**: [Read-tool_result.json](messages/tools/Read-tool_result.json)

```python
@dataclass
class ReadOutput(MessageContent):
    file_path: str
    content: str           # File content (may be truncated)
    start_line: int        # 1-based starting line number
    num_lines: int         # Number of lines in content
    total_lines: int       # Total lines in file
    is_truncated: bool
    system_reminder: Optional[str]  # Embedded system reminder
```

### Edit Tool Result → EditOutput

Edit tool results with cat-n snippets are parsed into structured `EditOutput`:
- **Files**: [Edit-tool_result.json](messages/tools/Edit-tool_result.json)

```python
@dataclass
class EditOutput(MessageContent):
    file_path: str
    success: bool
    diffs: List[EditDiff]  # Changes made
    message: str           # Result message or code snippet
    start_line: int        # Starting line for display
```

### Tool Result Rendering Wrapper

Tool results are wrapped in `ToolResultContentModel` for rendering, which provides additional context:

```python
@dataclass
class ToolResultContentModel(MessageContent):
    tool_use_id: str
    content: Any  # Union[str, List[Dict[str, Any]]]
    is_error: bool = False
    tool_name: Optional[str] = None   # Name of the tool
    file_path: Optional[str] = None   # File path for Read/Edit/Write
```

## 1.4 Images (ImageContent)

- **CSS Class**: `image`
- **Files**: [image.json](messages/user/image.json)

```json
{
  "type": "user",
  "message": {
    "content": [{
      "type": "image",
      "source": {
        "type": "base64",
        "media_type": "image/png",
        "data": "iVBORw0KGgo..."
      }
    }]
  }
}
```

Image data is structured using `ImageSource`:

```python
class ImageSource(BaseModel):
    type: Literal["base64"]
    media_type: str  # e.g., "image/png"
    data: str        # Base64-encoded image data

class ImageContent(BaseModel, MessageContent):
    type: Literal["image"]
    source: ImageSource
```

---

# Part 2: Assistant Messages (AssistantTranscriptEntry)

Assistant transcript entries (`type: "assistant"`) contain Claude's responses.

## 2.1 Content Types in Assistant Messages

Assistant messages contain `ContentItem` instances that are:
- **TextContent**: Claude's text response
- **ThinkingContent**: Extended thinking blocks
- **ToolUseContent**: Tool invocations

## 2.2 Assistant Text → AssistantTextContent

- **Content Model**: `AssistantTextContent` (models.py)
- **CSS Class**: `assistant` (or `assistant sidechain`)
- **Files**: [assistant.json](messages/assistant/assistant.json)

```python
@dataclass
class AssistantTextContent(MessageContent):
    text: str  # The assistant's response text
```

### Sidechain Assistant

- **Condition**: `isSidechain: true`
- **CSS Class**: `assistant sidechain`
- **Title**: "Sub-assistant"
- **Files**: [assistant_sidechain.json](messages/assistant/assistant_sidechain.json)

## 2.3 Thinking Content → ThinkingContentModel

- **Content Model**: `ThinkingContentModel` (models.py)
- **CSS Class**: `thinking`
- **Files**: [thinking.json](messages/assistant/thinking.json)

```python
@dataclass
class ThinkingContentModel(MessageContent):
    thinking: str              # The thinking text
    signature: Optional[str]   # Thinking block signature
```

```json
{
  "type": "assistant",
  "message": {
    "content": [{ "type": "thinking", "thinking": "Let me analyze..." }]
  }
}
```

## 2.4 Tool Use → ToolUseContent with Typed Inputs

Tool invocations contain a `ToolUseContent` item with:
- `name`: The tool name (e.g., "Read", "Bash", "Task")
- `id`: Unique ID for pairing with results
- `input`: Raw input dictionary

The `parsed_input` property returns a typed input model via `parse_tool_input()`.

### Tool Input Models (models.py)

| Tool | Input Model | Key Fields |
|------|-------------|------------|
| Read | `ReadInput` | file_path, offset, limit |
| Write | `WriteInput` | file_path, content |
| Edit | `EditInput` | file_path, old_string, new_string, replace_all |
| MultiEdit | `MultiEditInput` | file_path, edits[] |
| Bash | `BashInput` | command, description, timeout, run_in_background |
| Glob | `GlobInput` | pattern, path |
| Grep | `GrepInput` | pattern, path, glob, type, output_mode |
| Task | `TaskInput` | prompt, subagent_type, description, model |
| TodoWrite | `TodoWriteInput` | todos[] |
| AskUserQuestion | `AskUserQuestionInput` | questions[], question |
| ExitPlanMode | `ExitPlanModeInput` | plan, launchSwarm, teammateCount |

### Tool Input Helper Models

Some tool inputs contain nested structures with their own models:

```python
# MultiEdit tool uses EditItem for individual edits
class EditItem(BaseModel):
    old_string: str
    new_string: str

# TodoWrite tool uses TodoWriteItem for individual todos
class TodoWriteItem(BaseModel):
    content: str = ""
    status: str = "pending"
    activeForm: str = ""
    id: Optional[str] = None
    priority: Optional[str] = None

# AskUserQuestion tool uses nested models for questions/options
class AskUserQuestionOption(BaseModel):
    label: str = ""
    description: Optional[str] = None

class AskUserQuestionItem(BaseModel):
    question: str = ""
    header: Optional[str] = None
    options: List[AskUserQuestionOption] = []
    multiSelect: bool = False
```

### Tool Use Message Structure

- **CSS Class**: `tool_use` (or `tool_use sidechain`)
- **Files**: See [messages/tools/](messages/tools/) (e.g., `Read-tool_use.json`)

```json
{
  "type": "assistant",
  "message": {
    "content": [{
      "type": "tool_use",
      "id": "toolu_xxx",
      "name": "Read",
      "input": { "file_path": "/path/to/file" }
    }]
  }
}
```

---

# Part 3: System Messages (SystemTranscriptEntry)

System transcript entries (`type: "system"`) convey notifications and hook summaries.

## 3.1 Content Types for System Messages

System messages are parsed into structured content models in `models.py`:
- **SystemContent**: For info/warning/error messages
- **HookSummaryContent**: For hook execution summaries

## 3.2 System Info/Warning/Error → SystemContent

- **Content Model**: `SystemContent` (models.py)
- **CSS Class**: `system system-info`, `system system-warning`, `system system-error`
- **Files**: [system_info.json](messages/system/system_info.json)

```python
@dataclass
class SystemContent(MessageContent):
    level: str  # "info", "warning", "error"
    text: str   # Raw text content (may contain ANSI codes)
```

```json
{
  "type": "system",
  "content": "Running PostToolUse:MultiEdit...",
  "level": "info"
}
```

## 3.3 Hook Summary → HookSummaryContent

- **Content Model**: `HookSummaryContent` (models.py)
- **Condition**: `subtype: "stop_hook_summary"`
- **CSS Class**: `system system-hook`

```python
@dataclass
class HookInfo:
    command: str

@dataclass
class HookSummaryContent(MessageContent):
    has_output: bool
    hook_errors: List[str]
    hook_infos: List[HookInfo]
```

---

# Part 4: Metadata Entries

These entry types primarily contain metadata, with some rendered conditionally.

## 4.1 Summary (SummaryTranscriptEntry)

- **Purpose**: Session summary for navigation
- **Files**: [summary.json](messages/system/summary.json)

```json
{
  "type": "summary",
  "summary": "Claude Code warmup for deep-manifest project",
  "leafUuid": "b83b0f5f-8bfc-4b98-8368-16162a6e9320"
}
```

The `leafUuid` links the summary to the last message of the session.

## 4.2 Queue Operation (QueueOperationTranscriptEntry)

- **Purpose**: User interrupts and steering during assistant responses
- **Rendered**: Only `remove` operations (as `user steering`)
- **Files**: [queue_operation.json](messages/system/queue_operation.json)

## 4.3 File History Snapshot

- **Purpose**: File state snapshots for undo/redo
- **Not Rendered**
- **Files**: [file_history_snapshot.json](messages/system/file_history_snapshot.json)

---

# Part 5: Renderer Content Models

These models are created during rendering to represent synthesized content not directly from JSONL entries.

## 5.1 SessionHeaderContent

Session headers are rendered at the start of each session:

```python
@dataclass
class SessionHeaderContent(MessageContent):
    title: str           # e.g., "Session 2025-12-13 10:30"
    session_id: str      # Session UUID
    summary: Optional[str] = None  # Session summary if available
```

## 5.2 DedupNoticeContent

Deduplication notices are shown when content is deduplicated (e.g., sidechain assistant text that duplicates the Task tool result):

```python
@dataclass
class DedupNoticeContent(MessageContent):
    notice_text: str  # e.g., "Content omitted (duplicates Task result)"
```

---

# Part 6: Infrastructure Models

## 6.1 MessageModifiers

Semantic modifiers that affect message display. These are format-neutral flags that renderers use to determine how to display a message:

```python
@dataclass
class MessageModifiers:
    is_sidechain: bool = False      # Sub-agent message
    is_slash_command: bool = False  # Slash command invocation
    is_command_output: bool = False # Command output
    is_compacted: bool = False      # Compacted conversation
    is_error: bool = False          # Error message
    is_steering: bool = False       # Queue remove (steering)
    system_level: Optional[str] = None  # "info", "warning", "error", "hook"
```

## 6.2 UsageInfo

Token usage tracking for assistant messages:

```python
class UsageInfo(BaseModel):
    input_tokens: Optional[int] = None
    cache_creation_input_tokens: Optional[int] = None
    cache_read_input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    service_tier: Optional[str] = None
    server_tool_use: Optional[Dict[str, Any]] = None
```

## 6.3 BaseTranscriptEntry

Base class for all transcript entries, providing common fields:

```python
class BaseTranscriptEntry(BaseModel):
    parentUuid: Optional[str]  # UUID of parent message
    isSidechain: bool          # Whether this is a sub-agent message
    userType: str              # User type identifier
    cwd: str                   # Working directory
    sessionId: str             # Session UUID
    version: str               # Transcript format version
    uuid: str                  # Unique message ID
    timestamp: str             # ISO 8601 timestamp
    isMeta: Optional[bool] = None   # Slash command marker
    agentId: Optional[str] = None   # Sub-agent ID
```

---

# Part 7: Message Relationships

## 7.1 Hierarchy (Parent/Child)

The message hierarchy is determined by **sequence and message type**, not by `parentUuid`:

- Session headers are topmost (Level 0)
- User messages follow at Level 1
- Assistant responses and system messages nest under user messages (Level 2)
- Tool use/result pairs nest under assistant responses (Level 3)
- Sidechain messages nest under their Task result (Level 4+)

```text
Session header (Level 0)
└── User message (Level 1)
    ├── System message (Level 2)
    └── Assistant response (Level 2)
        └── Tool use/result pair (Level 3)
            └── Sidechain messages (Level 4+)
```

**Note**: `parentUuid` links messages temporally (which message preceded this one) but is not used for rendering hierarchy.

## 7.2 Tool Pairing

`tool_use` and `tool_result` messages are paired by `tool_use_id`:

| First | Last | Link |
|-------|------|------|
| `tool_use` | `tool_result` | `tool_use.id` = `tool_result.tool_use_id` |

### Other Pairings

| First | Last | Link |
|-------|------|------|
| `bash-input` | `bash-output` | Sequential |
| `thinking` | `assistant` | Sequential |
| `slash-command` | `command-output` | Sequential |

## 7.3 Sidechain Linking

Sub-agent messages (from `Task` tool):
- Have `isSidechain: true`
- Have `agentId` linking to the Task
- Appear nested under their Task result

---

# Part 8: Tool Reference

## Available Tools by Category

### File Operations

| Tool | Use Sample | Result Sample | Input Model | Output Model |
|------|------------|---------------|-------------|--------------|
| Read | [tool_use](messages/tools/Read-tool_use.json) | [tool_result](messages/tools/Read-tool_result.json) | `ReadInput` | `ReadOutput` |
| Write | [tool_use](messages/tools/Write-tool_use.json) | [tool_result](messages/tools/Write-tool_result.json) | `WriteInput` | `WriteOutput` *(TODO)* |
| Edit | [tool_use](messages/tools/Edit-tool_use.json) | [tool_result](messages/tools/Edit-tool_result.json) | `EditInput` | `EditOutput` |
| MultiEdit | [tool_use](messages/tools/MultiEdit-tool_use.json) | [tool_result](messages/tools/MultiEdit-tool_result.json) | `MultiEditInput` | — |
| Glob | [tool_use](messages/tools/Glob-tool_use.json) | [tool_result](messages/tools/Glob-tool_result.json) | `GlobInput` | `GlobOutput` *(TODO)* |
| Grep | [tool_use](messages/tools/Grep-tool_use.json) | [tool_result](messages/tools/Grep-tool_result.json) | `GrepInput` | `GrepOutput` *(TODO)* |

### Shell Operations

| Tool | Use Sample | Result Sample | Input Model | Output Model |
|------|------------|---------------|-------------|--------------|
| Bash | [tool_use](messages/tools/Bash-tool_use.json) | [tool_result](messages/tools/Bash-tool_result.json) | `BashInput` | `BashOutput` *(TODO)* |
| BashOutput | [tool_use](messages/tools/BashOutput-tool_use.json) | [tool_result](messages/tools/BashOutput-tool_result.json) | — | — |
| KillShell | [tool_use](messages/tools/KillShell-tool_use.json) | [tool_result](messages/tools/KillShell-tool_result.json) | — | — |

### Agent Operations

| Tool | Use Sample | Result Sample | Input Model | Output Model |
|------|------------|---------------|-------------|--------------|
| Task | [tool_use](messages/tools/Task-tool_use.json) | [tool_result](messages/tools/Task-tool_result.json) | `TaskInput` | `TaskOutput` *(TODO)* |
| TodoWrite | [tool_use](messages/tools/TodoWrite-tool_use.json) | [tool_result](messages/tools/TodoWrite-tool_result.json) | `TodoWriteInput` | — |
| AskUserQuestion | [tool_use](messages/tools/AskUserQuestion-tool_use.json) | [tool_result](messages/tools/AskUserQuestion-tool_result.json) | `AskUserQuestionInput` | — |
| ExitPlanMode | [tool_use](messages/tools/ExitPlanMode-tool_use.json) | [tool_result](messages/tools/ExitPlanMode-tool_result.json) | `ExitPlanModeInput` | — |

### Web Operations

| Tool | Use Sample | Result Sample | Input Model | Output Model |
|------|------------|---------------|-------------|--------------|
| WebFetch | [tool_use](messages/tools/WebFetch-tool_use.json) | [tool_result](messages/tools/WebFetch-tool_result.json) | — | — |
| WebSearch | [tool_use](messages/tools/WebSearch-tool_use.json) | [tool_result](messages/tools/WebSearch-tool_result.json) | — | — |

---

## References

- [css-classes.md](css-classes.md) - Complete CSS class reference with support status
- [models.py](../claude_code_log/models.py) - Pydantic models for transcript data
- [renderer.py](../claude_code_log/renderer.py) - Main rendering module
- [html/](../claude_code_log/html/) - HTML-specific formatters (formatting only, content models in models.py)
  - [system_formatters.py](../claude_code_log/html/system_formatters.py) - SystemContent, HookSummaryContent formatting
  - [user_formatters.py](../claude_code_log/html/user_formatters.py) - User message formatting
  - [assistant_formatters.py](../claude_code_log/html/assistant_formatters.py) - AssistantText, Thinking, Image formatting
  - [tool_formatters.py](../claude_code_log/html/tool_formatters.py) - Tool use/result formatting
- [parser.py](../claude_code_log/parser.py) - JSONL parsing module
- [TEMPLATE_MESSAGE_CHILDREN.md](TEMPLATE_MESSAGE_CHILDREN.md) - Tree architecture exploration
- [MESSAGE_REFACTORING.md](MESSAGE_REFACTORING.md) - Refactoring plan
