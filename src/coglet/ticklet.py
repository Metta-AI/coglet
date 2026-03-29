"""TickLet mixin — time-driven and tick-driven periodic execution.

Time-based (@every with "s" or "m") runs as asyncio background tasks.
Tick-based (@every with "ticks") fires when self.tick() is called manually.
Ticker errors are caught and routed to on_ticker_error() (overridable).
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable


def every(interval: int | float, unit: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator: schedule a method to run periodically.

    Units:
        "s" — seconds
        "m" — minutes
        "ticks" — manual tick-driven (call tick() on the coglet)
    """
    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        fn._every_interval = interval  # type: ignore[attr-defined]
        fn._every_unit = unit  # type: ignore[attr-defined]
        return fn
    return decorator


class TickLet:
    """Mixin: time-driven and tick-driven periodic behavior.

    Time-based (@every with "s" or "m") uses asyncio tasks.
    Tick-based (@every with "ticks") requires calling self.tick().
    """

    _every_handlers: list[tuple[str, int | float, str]]  # (method_name, interval, unit)

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        handlers: list[tuple[str, int | float, str]] = []
        for base in reversed(cls.__mro__):
            base_handlers = getattr(base, "_every_handlers", None)
            if isinstance(base_handlers, list):
                handlers.extend(base_handlers)

        for name in vars(cls):
            method = vars(cls)[name]
            interval = getattr(method, "_every_interval", None)
            unit = getattr(method, "_every_unit", None)
            if interval is not None and unit is not None:
                handlers.append((name, interval, unit))

        cls._every_handlers = handlers

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._tick_count: int = 0
        self._tick_tasks: list[asyncio.Task[None]] = []

    async def _start_tickers(self) -> None:
        for method_name, interval, unit in self._every_handlers:
            if unit in ("s", "m"):
                seconds = interval if unit == "s" else interval * 60
                task = asyncio.create_task(
                    self._time_ticker(method_name, float(seconds))
                )
                self._tick_tasks.append(task)

    async def _stop_tickers(self) -> None:
        for task in self._tick_tasks:
            task.cancel()
        self._tick_tasks.clear()

    async def _time_ticker(self, method_name: str, seconds: float) -> None:
        while True:
            await asyncio.sleep(seconds)
            try:
                method = getattr(self, method_name)
                result = method()
                if hasattr(result, "__await__"):
                    await result
            except asyncio.CancelledError:
                raise
            except Exception as e:
                await self.on_ticker_error(method_name, e)

    async def on_ticker_error(self, method_name: str, error: Exception) -> None:
        """Called when a ticker raises. Override to customize.

        Default: log via LogLet if available, otherwise ignore and continue.
        """
        from coglet.loglet import LogLet
        if isinstance(self, LogLet):
            await self.log("error", f"ticker {method_name} failed: {error}")

    async def tick(self) -> None:
        """Call this to advance tick-based @every handlers."""
        self._tick_count += 1
        for method_name, interval, unit in self._every_handlers:
            if unit == "ticks" and self._tick_count % int(interval) == 0:
                method = getattr(self, method_name)
                result = method()
                if hasattr(result, "__await__"):
                    await result
