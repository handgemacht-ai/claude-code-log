"""Type stubs for pygments.formatter - base formatter class."""

from typing import Any

class Formatter:
    """Base class for formatters."""
    def __init__(self, **options: Any) -> None: ...
