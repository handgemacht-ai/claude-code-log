"""Type stubs for pygments.lexer - base lexer class."""

from typing import Any

class Lexer:
    """Base class for lexers."""
    def __init__(self, **options: Any) -> None: ...
