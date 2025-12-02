# Message Types in Claude Code Transcripts

This document describes all message types found in Claude Code JSONL transcript files.

## JSONL Entry Types (Top Level)

Each line in a `.jsonl` file is a JSON object with a `type` field:

```
Session
├── user                    # User input or tool results
│   ├── text content        # User typed message
│   ├── tool_result         # Result from tool execution
│   └── image               # User attached image
│
├── assistant               # Claude's response
│   ├── text content        # Assistant's text response
│   ├── thinking content    # Extended thinking (when enabled)
│   └── tool_use content    # Tool invocation
│       ├── Read, Edit, Write, Glob, Grep
│       ├── Bash, BashOutput, KillShell
│       ├── Task (spawns sidechain)
│       ├── TodoWrite, AskUserQuestion
│       ├── WebFetch, WebSearch
│       └── ExitPlanMode, etc.
│
├── system                  # System messages (init command, notifications)
│
├── summary                 # Session summary (generated after session ends)
│
├── queue-operation         # Steering messages (interrupt/continue)
│
└── file-history-snapshot   # File state snapshots
```

## Message Hierarchy (Rendering)

When rendering, messages are organized hierarchically:

```
Level 0: Session header
└── Level 1: User message
    ├── Level 2: System message (info/warning)
    └── Level 2: Assistant response
        └── Level 3: Tool use/result (paired)
            └── Level 4: Sidechain assistant (from Task)
                └── Level 5: Sidechain tools
```

## Detailed Type Descriptions

### `user` Type

User messages contain the human input or tool execution results.

**Common Fields:**
- `type`: "user"
- `sessionId`: Session UUID
- `timestamp`: ISO 8601 timestamp
- `uuid`: Message UUID
- `parentUuid`: UUID of parent message (or null)
- `isSidechain`: Whether this is in a sub-agent context
- `message.role`: "user"
- `message.content`: Array of content items

**Content Types:**
- `text`: User typed message, IDE selection, system reminders
- `tool_result`: Execution result of a tool_use
- `image`: User attached screenshot/image

**See:** [messages/user_text.json](messages/user_text.json), [messages/user_tool_result.json](messages/user_tool_result.json)

### `assistant` Type

Assistant messages contain Claude's responses.

**Common Fields:**
- `type`: "assistant"
- `sessionId`: Session UUID
- `timestamp`: ISO 8601 timestamp
- `uuid`: Message UUID
- `parentUuid`: UUID of parent message
- `message.role`: "assistant"
- `message.model`: Model identifier (e.g., "claude-opus-4-5-20251101")
- `message.content`: Array of content items

**Content Types:**
- `text`: Claude's text response
- `thinking`: Extended thinking content (when enabled)
- `tool_use`: Tool invocation with name, id, and input

**See:** [messages/assistant_text.json](messages/assistant_text.json), [messages/assistant_thinking.json](messages/assistant_thinking.json)

### `system` Type

System messages for commands and notifications.

**Variants:**
- Init command: Shows CLI initialization
- IDE notifications: VS Code integration messages
- Warnings/errors: System-level issues

**See:** [messages/system.json](messages/system.json)

### `summary` Type

Session summaries generated after a session ends.

**Fields:**
- `type`: "summary"
- `summary`: The generated summary text
- `leafUuid`: UUID of the last message (used to link summary to session)

**See:** [messages/summary.json](messages/summary.json)

### `queue-operation` Type

Steering messages for interrupts and user intervention.

**Common Operations:**
- User interrupts assistant's response
- User provides steering input mid-response

**See:** [messages/queue_operation.json](messages/queue_operation.json)

### `file-history-snapshot` Type

Snapshots of file state for undo/redo functionality.

**See:** [messages/file_history_snapshot.json](messages/file_history_snapshot.json)

## Tool Types

Tools are invoked via `tool_use` content items in assistant messages, with results appearing as `tool_result` in subsequent user messages.

### File Operations
- **Read**: Read file contents
- **Edit**: Edit file with old_string/new_string replacement
- **Write**: Write entire file
- **MultiEdit**: Multiple edits in one operation
- **Glob**: Find files by pattern
- **Grep**: Search file contents

### Shell Operations
- **Bash**: Execute shell command
- **BashOutput**: Get output from background shell
- **KillShell**: Terminate background shell

### Agent/Task Operations
- **Task**: Spawn sub-agent (creates sidechain)
- **TodoWrite**: Update task list
- **AskUserQuestion**: Prompt user for input
- **ExitPlanMode**: Complete planning phase

### Web Operations
- **WebFetch**: Fetch URL content
- **WebSearch**: Search the web

**See:** [messages/tools/](messages/tools/) for samples of each tool type.

## Sidechains (Sub-agents)

When Claude uses the `Task` tool, a sub-agent is spawned. Messages from this sub-agent:
- Have `isSidechain: true`
- Have an `agentId` field linking them to the Task
- Appear in the transcript interleaved with main messages
- Are reordered during rendering to appear after their Task result

## Key Relationships

1. **Parent/Child**: `parentUuid` links messages in conversation order
2. **Tool Pairing**: `tool_use.id` matches `tool_result.tool_use_id`
3. **Sidechain Linking**: `agentId` links sidechain messages to Task results
4. **Summary Linking**: `summary.leafUuid` links to the last message's `uuid`

## Rendering Considerations

- Messages with same `uuid` but different `sessionId` are duplicates (from session resume)
- Multiple assistant messages may share the same `requestId` (streaming responses)
- Tool pairs should be visually grouped and foldable together
- Sidechains should be nested under their Task result
- Extended thinking should be collapsible
