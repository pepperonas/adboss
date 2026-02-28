"""Circular battery gauge widget."""

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPainter, QColor, QFont, QPen
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QSizePolicy


class BatteryWidget(QWidget):
    """Circular gauge showing battery level with color coding."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._level = 0
        self._status = "Unknown"
        self._temperature = 0.0
        self._voltage = 0
        self._health = "Unknown"
        self._technology = ""

        self.setMinimumSize(200, 280)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._gauge_area = QWidget()
        self._gauge_area.setMinimumSize(180, 180)
        self._gauge_area.paintEvent = self._paint_gauge
        layout.addWidget(self._gauge_area, alignment=Qt.AlignmentFlag.AlignCenter)

        self._info_label = QLabel()
        self._info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._info_label.setObjectName("batteryInfoLabel")
        layout.addWidget(self._info_label)

    def update_data(self, data: dict) -> None:
        """Update battery data and repaint."""
        self._level = data.get("level", 0)
        self._status = data.get("status", "Unknown")
        self._temperature = data.get("temperature", 0.0)
        self._voltage = data.get("voltage", 0)
        self._health = data.get("health", "Unknown")
        self._technology = data.get("technology", "")

        info_parts = [
            f"Status: {self._status}",
            f"Health: {self._health}",
            f"Temp: {self._temperature:.1f} \u00b0C",
            f"Voltage: {self._voltage} mV",
        ]
        if self._technology:
            info_parts.append(f"Tech: {self._technology}")
        self._info_label.setText("\n".join(info_parts))
        self._gauge_area.update()

    def _get_color(self) -> QColor:
        if self._level > 50:
            return QColor("#4CAF50")
        elif self._level > 20:
            return QColor("#FFC107")
        else:
            return QColor("#F44336")

    def _paint_gauge(self, _event) -> None:
        widget = self._gauge_area
        painter = QPainter(widget)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        size = min(widget.width(), widget.height()) - 20
        x = (widget.width() - size) / 2
        y = (widget.height() - size) / 2
        rect = QRectF(x, y, size, size)

        # Background arc
        bg_pen = QPen(QColor("#333333"), 12, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        painter.setPen(bg_pen)
        painter.drawArc(rect, 225 * 16, -270 * 16)

        # Level arc
        color = self._get_color()
        fg_pen = QPen(color, 12, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        painter.setPen(fg_pen)
        span = int(-270 * (self._level / 100.0))
        painter.drawArc(rect, 225 * 16, span * 16)

        # Center text
        painter.setPen(QPen(QColor("#FFFFFF")))
        font = QFont("Helvetica Neue", int(size * 0.2), QFont.Weight.Bold)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, f"{self._level}%")

        # Label below percentage
        small_font = QFont("Helvetica Neue", int(size * 0.07))
        painter.setFont(small_font)
        painter.setPen(QPen(QColor("#AAAAAA")))
        label_rect = QRectF(rect.x(), rect.y() + size * 0.25, rect.width(), rect.height())
        painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, "Battery")

        painter.end()
