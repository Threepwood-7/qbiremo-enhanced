"""Shared Qt widget/item helpers."""

from PySide6.QtWidgets import QTableWidgetItem


class NumericTableWidgetItem(QTableWidgetItem):
    """Sort table cells using numeric sort values instead of display text."""

    def __init__(self, display_text: str, sort_value: float = 0.0) -> None:
        """Store display text and a numeric key used by Qt sorting."""
        super().__init__(display_text)
        self._sort_value = sort_value

    def set_sort_value(self, sort_value: float) -> None:
        """Update numeric key used for sorting."""
        self._sort_value = float(sort_value)

    def sort_value(self) -> float:
        """Return numeric key currently used for sorting."""
        return float(self._sort_value)

    def __lt__(self, other: object) -> bool:
        """Compare numeric sort keys when both items are numeric wrappers."""
        if isinstance(other, NumericTableWidgetItem):
            return self._sort_value < other._sort_value
        if isinstance(other, QTableWidgetItem):
            return super().__lt__(other)
        return False
