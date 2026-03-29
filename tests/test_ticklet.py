"""Unit tests for coglet.ticklet: TickLet mixin and @every decorator."""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from coglet import Coglet, CogletConfig, CogletRuntime, LogLet, TickLet, every


class CounterTicker(Coglet, TickLet):
    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)
        self.time_count = 0
        self.tick_count_manual = 0

    @every(0.05, "s")
    async def fast_tick(self) -> None:
        self.time_count += 1

    @every(3, "ticks")
    async def manual_tick(self) -> None:
        self.tick_count_manual += 1


class SyncTicker(Coglet, TickLet):
    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)
        self.count = 0

    @every(2, "ticks")
    def sync_tick(self) -> None:
        self.count += 1


class MinuteTicker(Coglet, TickLet):
    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)
        self.count = 0

    @every(1, "m")
    async def minute_tick(self) -> None:
        self.count += 1


class FailingTicker(Coglet, TickLet, LogLet):
    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)
        self.tick_calls: int = 0
        self.errors: list[Exception] = []

    @every(0.05, "s")
    async def bad_tick(self) -> None:
        self.tick_calls += 1
        if self.tick_calls == 1:
            raise ValueError("boom")

    async def on_ticker_error(self, method_name: str, error: Exception) -> None:
        self.errors.append(error)
        await super().on_ticker_error(method_name, error)


@pytest.mark.asyncio
async def test_ticklet_time_based():
    rt = CogletRuntime()
    handle = await rt.spawn(CogletConfig(cls=CounterTicker))
    cog: CounterTicker = handle.coglet
    await asyncio.sleep(0.15)
    assert cog.time_count >= 2
    await rt.shutdown()


@pytest.mark.asyncio
async def test_ticklet_manual():
    cog = CounterTicker()
    cog._tick_count = 0
    for _ in range(9):
        await cog.tick()
    assert cog.tick_count_manual == 3


@pytest.mark.asyncio
async def test_ticklet_stop_cancels_tasks():
    rt = CogletRuntime()
    handle = await rt.spawn(CogletConfig(cls=CounterTicker))
    cog: CounterTicker = handle.coglet
    assert len(cog._tick_tasks) == 1
    await rt.shutdown()
    assert len(cog._tick_tasks) == 0


@pytest.mark.asyncio
async def test_ticklet_sync_handler():
    cog = SyncTicker()
    for _ in range(4):
        await cog.tick()
    assert cog.count == 2


def test_ticklet_minute_unit():
    assert len(MinuteTicker._every_handlers) == 1
    name, interval, unit = MinuteTicker._every_handlers[0]
    assert unit == "m"
    assert interval == 1


@pytest.mark.asyncio
async def test_ticklet_error_handling():
    """Ticker errors call on_ticker_error and continue running."""
    rt = CogletRuntime()
    handle = await rt.spawn(CogletConfig(cls=FailingTicker))
    cog: FailingTicker = handle.coglet
    await asyncio.sleep(0.15)
    assert cog.tick_calls >= 2
    assert len(cog.errors) == 1
    assert "boom" in str(cog.errors[0])
    await rt.shutdown()
