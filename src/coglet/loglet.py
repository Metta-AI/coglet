"""LogLet mixin — separate log stream with level filtering.

Logs are transmitted on the "log" channel, independent of application data.
The COG subscribes via observe(handle, "log") and controls verbosity via
guide(handle, Command("log_level", "debug")). Levels: debug, info, warn, error.
"""
from __future__ import annotations

from typing import Any, TYPE_CHECKING

from coglet.coglet import enact

if TYPE_CHECKING:
    from coglet.coglet import Coglet


class LogLet:
    """Mixin: separate log stream.

    Adds a log channel independent of transmit. The COG subscribes to
    observe(handle, "log") and controls verbosity via guide.

    Must be mixed with Coglet to access transmit().
    """

    LOG_LEVELS = ("debug", "info", "warn", "error")

    def __init__(self, log_level: str = "info", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._log_level: str = log_level

    def _level_value(self, level: str) -> int:
        try:
            return self.LOG_LEVELS.index(level)
        except ValueError:
            return 0

    async def log(self, level: str, data: Any) -> None:
        if self._level_value(level) >= self._level_value(self._log_level):
            # transmit() is provided by Coglet when mixed in
            await self.transmit("log", {"level": level, "data": data})  # type: ignore[attr-defined]

    @enact("log_level")
    async def _loglet_set_level(self, level: str) -> None:
        self._log_level = level
