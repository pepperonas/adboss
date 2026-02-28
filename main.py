"""ADBOSS — Android Debug Bridge Desktop Manager."""

import logging
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon

from ui.main_window import MainWindow

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


def load_stylesheet() -> str:
    """Load the QSS stylesheet."""
    qss_path = Path(__file__).parent / "assets" / "styles.qss"
    if qss_path.exists():
        return qss_path.read_text(encoding="utf-8")
    logger.warning("Stylesheet not found: %s", qss_path)
    return ""


def main() -> None:
    """Application entry point."""
    app = QApplication(sys.argv)
    app.setApplicationName("ADBOSS")
    app.setOrganizationName("celox.io")

    # Icon
    icon_path = Path(__file__).parent / "assets" / "icon.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    # Stylesheet
    stylesheet = load_stylesheet()
    if stylesheet:
        app.setStyleSheet(stylesheet)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
