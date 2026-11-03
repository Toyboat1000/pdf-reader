"""What text sources produce, and how they fail."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TextSource:
    """A document as flowing text.

    Attributes:
        title: Display title.
        paragraphs: The text in reading order, one entry per paragraph or heading.
    """

    title: str
    paragraphs: tuple[str, ...]

    @property
    def text(self) -> str:
        """Return the paragraphs separated by blank lines (how the text pipeline splits)."""
        return "\n\n".join(self.paragraphs)


class SourceError(Exception):
    """A document could not be read.

    Attributes:
        user_message: A friendly explanation suitable for showing in the UI.
    """

    def __init__(self, user_message: str) -> None:
        super().__init__(user_message)
        self.user_message = user_message
