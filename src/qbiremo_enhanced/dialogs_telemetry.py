"""Telemetry dialogs and widgets."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from threep_commons.formatters import format_speed_mode

if TYPE_CHECKING:
    from .models.torrent import SessionTimelineSample, TrackerHealthRow


class TrackerHealthDialog(QDialog):
    """Dialog to display aggregated tracker health metrics."""

    refresh_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize tracker health dashboard widgets."""
        super().__init__(parent)
        self.setWindowTitle("Tracker Health Dashboard")
        self.resize(980, 520)
        self._build_ui()

    def _build_ui(self) -> None:
        """Build tracker-health table and control buttons."""
        layout = QVBoxLayout(self)

        self.lbl_summary = QLabel("No tracker data loaded.")
        layout.addWidget(self.lbl_summary)

        self.tbl_health = QTableWidget()
        self.tbl_health.setAlternatingRowColors(True)
        self.tbl_health.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl_health.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl_health.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tbl_health.setSortingEnabled(True)
        self.tbl_health.setColumnCount(9)
        self.tbl_health.setHorizontalHeaderLabels(
            [
                "Tracker",
                "Torrents",
                "Rows",
                "Working",
                "Failing",
                "Fail Rate %",
                "Dead",
                "Avg Next Announce (s)",
                "Last Error",
            ]
        )
        header = self.tbl_health.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)
        layout.addWidget(self.tbl_health, 1)

        controls = QHBoxLayout()
        self.btn_refresh = QPushButton("Refresh")
        self.btn_close = QPushButton("Close")
        self.btn_refresh.clicked.connect(self.refresh_requested.emit)
        self.btn_close.clicked.connect(self.close)
        controls.addWidget(self.btn_refresh)
        controls.addStretch(1)
        controls.addWidget(self.btn_close)
        layout.addLayout(controls)

    def set_busy(self, busy: bool, message: str = "") -> None:
        """Set dialog busy state."""
        self.btn_refresh.setEnabled(not bool(busy))
        if message:
            self.lbl_summary.setText(message)

    def set_rows(self, rows: list[TrackerHealthRow]) -> None:
        """Render aggregated tracker-health rows."""
        self.tbl_health.setSortingEnabled(False)
        self.tbl_health.setRowCount(len(rows))

        for row_idx, row in enumerate(rows):
            values = [
                str(row.get("tracker", "")),
                str(row.get("torrent_count", 0)),
                str(row.get("row_count", 0)),
                str(row.get("working_count", 0)),
                str(row.get("failing_count", 0)),
                f"{float(row.get('fail_rate', 0.0)):.1f}",
                "Yes" if bool(row.get("dead", False)) else "No",
                str(row.get("avg_next_announce", "")),
                str(row.get("last_error", "")),
            ]
            for col_idx, text in enumerate(values):
                item = QTableWidgetItem(text)
                if col_idx in {1, 2, 3, 4, 5, 7}:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                self.tbl_health.setItem(row_idx, col_idx, item)

        self.tbl_health.setSortingEnabled(True)

        total_trackers = len(rows)
        dead_count = sum(1 for row in rows if bool(row.get("dead", False)))
        self.lbl_summary.setText(f"Trackers: {total_trackers}   Dead: {dead_count}")


class TimelineGraphWidget(QWidget):
    """Simple custom graph for session timeline samples."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize timeline graph with an empty sample buffer."""
        super().__init__(parent)
        self._samples: list[SessionTimelineSample] = []
        self.setMinimumHeight(260)

    def set_samples(self, samples: list[SessionTimelineSample]) -> None:
        """Set timeline samples and trigger repaint."""
        self._samples = list(samples or [])
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        """Render timeline graph for speed, active-count, and alt-mode bands."""
        super().paintEvent(event)
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(16, 18, 22))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        samples = self._samples[-240:]
        if len(samples) < 2:
            painter.setPen(QColor(180, 180, 180))
            painter.drawText(
                self.rect(), Qt.AlignmentFlag.AlignCenter, "Timeline waiting for samples..."
            )
            return

        left, top, right, bottom = 48, 24, 14, 32
        chart_w = max(10, self.width() - left - right)
        chart_h = max(10, self.height() - top - bottom)

        # Alt-speed mode background bands.
        painter.setPen(Qt.PenStyle.NoPen)
        band_color = QColor(255, 196, 0, 40)
        for i in range(len(samples) - 1):
            if not bool(samples[i].get("alt_enabled", False)):
                continue
            x1 = left + int(i * chart_w / max(1, len(samples) - 1))
            x2 = left + int((i + 1) * chart_w / max(1, len(samples) - 1))
            painter.fillRect(x1, top, max(1, x2 - x1), chart_h, band_color)

        # Grid
        painter.setPen(QPen(QColor(80, 86, 96), 1))
        for idx in range(5):
            y = top + int(idx * chart_h / 4)
            painter.drawLine(left, y, left + chart_w, y)

        max_speed = max(
            1,
            max(int(s.get("down_bps", 0)) for s in samples),
            max(int(s.get("up_bps", 0)) for s in samples),
        )
        max_active = max(1, max(int(s.get("active_count", 0)) for s in samples))

        def x_for(i: int) -> int:
            """Map sample index to chart x coordinate."""
            return left + int(i * chart_w / max(1, len(samples) - 1))

        def y_for_speed(value: int) -> int:
            """Map speed value to chart y coordinate."""
            return top + chart_h - int(max(0, int(value)) * chart_h / max_speed)

        def y_for_active(value: int) -> int:
            """Map active torrent count to chart y coordinate."""
            return top + chart_h - int(max(0, int(value)) * chart_h / max_active)

        # Down line
        down_pen = QPen(QColor(80, 160, 255), 2)
        painter.setPen(down_pen)
        for i in range(len(samples) - 1):
            painter.drawLine(
                x_for(i),
                y_for_speed(samples[i].get("down_bps", 0)),
                x_for(i + 1),
                y_for_speed(samples[i + 1].get("down_bps", 0)),
            )

        # Up line
        up_pen = QPen(QColor(255, 140, 80), 2)
        painter.setPen(up_pen)
        for i in range(len(samples) - 1):
            painter.drawLine(
                x_for(i),
                y_for_speed(samples[i].get("up_bps", 0)),
                x_for(i + 1),
                y_for_speed(samples[i + 1].get("up_bps", 0)),
            )

        # Active torrents line
        active_pen = QPen(QColor(120, 220, 120), 1)
        active_pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(active_pen)
        for i in range(len(samples) - 1):
            painter.drawLine(
                x_for(i),
                y_for_active(samples[i].get("active_count", 0)),
                x_for(i + 1),
                y_for_active(samples[i + 1].get("active_count", 0)),
            )

        painter.setPen(QColor(220, 220, 220))
        painter.drawText(8, top + 10, f"{max_speed:,} B/s")
        painter.drawText(8, top + chart_h, "0")

        legend_y = 16
        painter.setPen(QColor(80, 160, 255))
        painter.drawText(left, legend_y, "DL")
        painter.setPen(QColor(255, 140, 80))
        painter.drawText(left + 40, legend_y, "UL")
        painter.setPen(QColor(120, 220, 120))
        painter.drawText(left + 80, legend_y, "Active Torrents")
        painter.setPen(QColor(255, 196, 0))
        painter.drawText(left + 210, legend_y, "Alt Mode")


class SessionTimelineDialog(QDialog):
    """Dialog to display timeline of speeds/active torrents/alt mode."""

    refresh_requested = Signal()
    clear_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize session timeline dialog controls."""
        super().__init__(parent)
        self.setWindowTitle("Session Timeline")
        self.resize(980, 420)
        self._build_ui()

    def _build_ui(self) -> None:
        """Build timeline graph panel, summary label, and control row."""
        layout = QVBoxLayout(self)
        self.graph = TimelineGraphWidget()
        layout.addWidget(self.graph, 1)

        self.lbl_summary = QLabel("No timeline samples yet.")
        layout.addWidget(self.lbl_summary)

        controls = QHBoxLayout()
        self.btn_refresh = QPushButton("Refresh")
        self.btn_clear = QPushButton("Clear History")
        self.btn_close = QPushButton("Close")
        self.btn_refresh.clicked.connect(self.refresh_requested.emit)
        self.btn_clear.clicked.connect(self.clear_requested.emit)
        self.btn_close.clicked.connect(self.close)
        controls.addWidget(self.btn_refresh)
        controls.addWidget(self.btn_clear)
        controls.addStretch(1)
        controls.addWidget(self.btn_close)
        layout.addLayout(controls)

    def set_samples(self, samples: list[SessionTimelineSample]) -> None:
        """Update timeline graph and summary."""
        self.graph.set_samples(samples)
        if not samples:
            self.lbl_summary.setText("No timeline samples yet.")
            return
        last = samples[-1]
        summary = (
            f"Samples: {len(samples)}   "
            f"DL: {format_speed_mode(int(last.get('down_bps', 0)), mode='human_readable')}   "
            f"UL: {format_speed_mode(int(last.get('up_bps', 0)), mode='human_readable')}   "
            f"Active: {int(last.get('active_count', 0))}   "
            f"Alt Mode: {'On' if bool(last.get('alt_enabled', False)) else 'Off'}"
        )
        self.lbl_summary.setText(summary)

    def set_busy(self, busy: bool, message: str = "") -> None:
        """Set dialog busy state."""
        enabled = not bool(busy)
        self.btn_refresh.setEnabled(enabled)
        self.btn_clear.setEnabled(enabled)
        if message:
            self.lbl_summary.setText(message)
