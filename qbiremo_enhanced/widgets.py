"""Shared Qt widget/item helpers."""

from PySide6.QtWidgets import QTableWidgetItem


class NumericTableWidgetItem(QTableWidgetItem):
    """Sort table cells using numeric sort values instead of display text."""

    def __init__(self, display_text: str, sort_value: float = 0.0) -> None:
        """Store display text and a numeric key used by Qt sorting."""
        super().__init__(display_text)
        self._sort_value = sort_value

    def __lt__(self, other: object) -> bool:
        """Compare numeric sort keys when both items are numeric wrappers."""
        if isinstance(other, NumericTableWidgetItem):
            return self._sort_value < other._sort_value
        return super().__lt__(other)


