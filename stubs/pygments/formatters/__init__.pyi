"""Type stubs for pygments.formatters - minimal stubs for functions used in this project."""

from typing import Any, Literal

from ..formatter import Formatter

class HtmlFormatter(Formatter):
    """HTML formatter for syntax highlighted code."""
    def __init__(
        self,
        linenos: bool | Literal["table", "inline"] = False,
        cssclass: str = "highlight",
        wrapcode: bool = False,
        linenostart: int = 1,
        **options: Any,
    ) -> None: ...
