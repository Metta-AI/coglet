"""Unit tests for coglet.suppresslet: SuppressLet mixin."""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from coglet import (
    Coglet, CogletConfig, CogletRuntime, Command, SuppressLet, enact, listen,
)


class SuppressedCollector(SuppressLet, Coglet):
    """Collector with suppress support."""
    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)
        self.received: list[Any] = []

    @listen("data")
    async def on_data(self, data: Any) -> None:
        self.received.append(data)
        await self.transmit("out", data)

    @enact("action")
    async def on_action(self, data: Any) -> None:
        self.received.append(("action", data))


@pytest.mark.asyncio
async def test_suppresslet_channels():
    """SuppressLet gates transmit on suppressed channels."""
    rt = CogletRuntime()
    handle = await rt.spawn(CogletConfig(cls=SuppressedCollector))
    cog: SuppressedCollector = handle.coglet

    sub = cog._bus.subscribe("out")

    # Normal transmit works
    await cog._dispatch_listen("data", "hello")
    assert cog.received == ["hello"]
    msg = await asyncio.wait_for(sub.get(), timeout=1.0)
    assert msg == "hello"

    # Suppress the "out" channel
    await cog._dispatch_enact(Command("suppress", {"channels": ["out"]}))
    assert "out" in cog._suppressed_channels

    # Transmit is silenced but listen still fires
    await cog._dispatch_listen("data", "world")
    assert cog.received == ["hello", "world"]
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(sub.get(), timeout=0.05)

    # Unsuppress restores output
    await cog._dispatch_enact(Command("unsuppress", {"channels": ["out"]}))
    await cog._dispatch_listen("data", "back")
    msg = await asyncio.wait_for(sub.get(), timeout=1.0)
    assert msg == "back"

    await rt.shutdown()


@pytest.mark.asyncio
async def test_suppresslet_commands():
    """SuppressLet gates enact on suppressed commands."""
    rt = CogletRuntime()
    handle = await rt.spawn(CogletConfig(cls=SuppressedCollector))
    cog: SuppressedCollector = handle.coglet

    # Normal command works
    await cog._dispatch_enact(Command("action", "go"))
    assert ("action", "go") in cog.received

    # Suppress the "action" command
    await cog._dispatch_enact(Command("suppress", {"commands": ["action"]}))
    await cog._dispatch_enact(Command("action", "stop"))
    assert ("action", "stop") not in cog.received

    # suppress/unsuppress always pass through
    await cog._dispatch_enact(Command("unsuppress", {"commands": ["action"]}))
    await cog._dispatch_enact(Command("action", "resume"))
    assert ("action", "resume") in cog.received

    await rt.shutdown()


@pytest.mark.asyncio
async def test_suppresslet_transmit_sync():
    """SuppressLet also gates transmit_sync."""
    cog = SuppressedCollector()
    sub = cog._bus.subscribe("out")

    cog.transmit_sync("out", "visible")
    result = await asyncio.wait_for(sub.get(), timeout=1.0)
    assert result == "visible"

    cog._suppressed_channels.add("out")
    cog.transmit_sync("out", "invisible")
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(sub.get(), timeout=0.05)


@pytest.mark.asyncio
async def test_suppresslet_meta_commands_pass_through():
    """suppress/unsuppress meta-commands pass even when commands are suppressed."""
    cog = SuppressedCollector()

    # Suppress the suppress command itself — should still work
    cog._suppressed_commands.add("action")
    await cog._dispatch_enact(Command("suppress", {"channels": ["out"]}))
    assert "out" in cog._suppressed_channels

    await cog._dispatch_enact(Command("unsuppress", {"channels": ["out"]}))
    assert "out" not in cog._suppressed_channels
