"""Storage and memory bar widgets."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
)


class StorageBar(QWidget):
    """A labeled progress bar for showing used/total storage or RAM."""

    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(2)

        header = QHBoxLayout()
        self._title_label = QLabel(title)
        self._title_label.setObjectName("storageTitle")
        self._detail_label = QLabel()
        self._detail_label.setObjectName("storageDetail")
        self._detail_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        header.addWidget(self._title_label)
        header.addWidget(self._detail_label)
        layout.addLayout(header)

        self._bar = QProgressBar()
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(14)
        self._bar.setRange(0, 100)
        layout.addWidget(self._bar)

    def update_data(self, used_kb: int, total_kb: int, used_str: str = "", total_str: str = "") -> None:
        """Update the bar with new values."""
        if total_kb > 0:
            percent = int((used_kb / total_kb) * 100)
        else:
            percent = 0
        self._bar.setValue(percent)
        self._detail_label.setText(f"{used_str} / {total_str} ({percent}%)")

        if percent > 90:
            self._bar.setStyleSheet("QProgressBar::chunk { background: #F44336; }")
        elif percent > 70:
            self._bar.setStyleSheet("QProgressBar::chunk { background: #FFC107; }")
        else:
            self._bar.setStyleSheet("QProgressBar::chunk { background: #00BCD4; }")
