"""Live clock widget that refreshes every second."""

from datetime import datetime

from textual.widgets import Static


class ClockWidget(Static):
    """A small clock that renders HH:MM:SS and updates each second."""

    DEFAULT_CSS = """
    ClockWidget {
        width: 100%;
        content-align: right middle;
        color: #6b6b6b;
        padding: 0 1;
    }
    """

    def on_mount(self) -> None:
        self._refresh()
        self.set_interval(1.0, self._refresh)

    def _refresh(self) -> None:
        self.update(datetime.now().strftime("%H:%M:%S"))
