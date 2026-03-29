"""Unit tests for coglet.loglet: LogLet mixin."""
from __future__ import annotations

import asyncio

import pytest

from coglet import Coglet, Command, LogLet


class LoggingCoglet(Coglet, LogLet):
    pass


@pytest.mark.asyncio
async def test_loglet_default_level():
    cog = LoggingCoglet()
    assert cog._log_level == "info"


@pytest.mark.asyncio
async def test_loglet_log_at_level():
    cog = LoggingCoglet()
    sub = cog._bus.subscribe("log")
    await cog.log("info", "test message")
    result = await asyncio.wait_for(sub.get(), timeout=1.0)
    assert result == {"level": "info", "data": "test message"}


@pytest.mark.asyncio
async def test_loglet_filters_below_level():
    cog = LoggingCoglet()
    sub = cog._bus.subscribe("log")
    await cog.log("debug", "should be filtered")
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(sub.get(), timeout=0.05)


@pytest.mark.asyncio
async def test_loglet_set_level():
    cog = LoggingCoglet()
    sub = cog._bus.subscribe("log")
    await cog._dispatch_enact(Command("log_level", "debug"))
    assert cog._log_level == "debug"
    await cog.log("debug", "now visible")
    result = await asyncio.wait_for(sub.get(), timeout=1.0)
    assert result["level"] == "debug"


@pytest.mark.asyncio
async def test_loglet_error_always_passes():
    cog = LoggingCoglet(log_level="error")
    sub = cog._bus.subscribe("log")
    await cog.log("warn", "filtered")
    await cog.log("error", "passes")
    result = await asyncio.wait_for(sub.get(), timeout=1.0)
    assert result["level"] == "error"


def test_loglet_level_values():
    cog = LoggingCoglet()
    assert cog._level_value("debug") == 0
    assert cog._level_value("info") == 1
    assert cog._level_value("warn") == 2
    assert cog._level_value("error") == 3
    assert cog._level_value("unknown") == 0
