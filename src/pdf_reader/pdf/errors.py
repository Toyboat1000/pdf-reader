"""Errors raised when a PDF cannot be read, each with a message fit for end users."""

from pathlib import Path


class PdfError(Exception):
    """Base class for PDF loading problems.

    Attributes:
        path: The file that failed to load.
        user_message: A friendly explanation suitable for showing in the UI.
    """

    def __init__(self, path: Path, user_message: str) -> None:
        super().__init__(f"{path}: {user_message}")
        self.path = path
        self.user_message = user_message


class PdfNotFoundError(PdfError):
    """The file does not exist or cannot be opened."""

    def __init__(self, path: Path) -> None:
        super().__init__(path, "The file could not be found or opened.")


class EncryptedPdfError(PdfError):
    """The PDF is password-protected."""

    def __init__(self, path: Path) -> None:
        super().__init__(
            path,
            "This PDF is password-protected. Password-protected documents aren't "
            "supported yet. Try removing the password in another app and open it again.",
        )


class CorruptPdfError(PdfError):
    """The file is damaged or is not a PDF."""

    def __init__(self, path: Path) -> None:
        super().__init__(
            path, "This file appears to be damaged or isn't a valid PDF, so it can't be read."
        )


class NoTextError(PdfError):
    """The PDF contains no extractable text, typically a scanned document."""

    def __init__(self, path: Path, *, scanned: bool = False, ocr_available: bool = True) -> None:
        if not scanned:
            message = "No readable text was found in this PDF. Its pages appear to be blank."
        elif ocr_available:
            message = (
                "No readable text was found in this PDF, even after trying to "
                "recognize text in its page images. The pages may be blank or the "
                "scan may be too faint to read."
            )
        else:
            message = (
                "No readable text was found in this PDF. It looks like a scanned "
                "document, and reading scanned pages needs the Windows text "
                "recognition (OCR) feature, which isn't available. Adding a language "
                "in Windows Settings > Time & language > Language & region usually "
                "installs it."
            )
        super().__init__(path, message)
