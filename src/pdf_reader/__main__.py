"""Entry point: ``python -m pdf_reader [file.pdf]`` or the ``pdf-reader`` command."""

import sys


def main() -> None:
    """Run the application and exit with its status code."""
    from pdf_reader.ui.app import run

    sys.exit(run())


if __name__ == "__main__":
    main()
