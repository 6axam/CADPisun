"""Desktop entry point."""

from __future__ import annotations

import sys
from collections.abc import Sequence

from PySide6.QtWidgets import QApplication

from handwriting_plotter.version import __version__

from .main_window import MainWindow
from .theme import apply_theme


def create_application(argv: Sequence[str] | None = None) -> tuple[QApplication, MainWindow]:
    app = QApplication.instance() or QApplication(list(argv) if argv is not None else sys.argv)
    app.setApplicationName("Handwriting Plotter")
    app.setApplicationDisplayName("Handwriting Plotter")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("Handwriting Plotter")
    apply_theme(app)
    window = MainWindow()
    return app, window


def main(argv: Sequence[str] | None = None) -> int:
    app, window = create_application(argv)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
