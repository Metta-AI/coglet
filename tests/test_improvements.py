"""Tests for coglet improvements: SuppressLet, tree, trace, ticker errors, restart, on_child_error."""
from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from typing import Any

import pytest

from coglet import (
    Coglet, CogletConfig, CogletHandle, CogletRuntime, CogletTrace,
    Command, LifeLet, LogLet, SuppressLet, TickLet, enact, every, listen,
)


# ---- Helpers ----

class Collector(Coglet):
    """Simple coglet that collects listen events."""
    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)
        self.received: list[Any] = []

    @listen("data")
    async def on_data(self, data: Any) -> None:
        self.received.append(data)
        await self.transmit("out", data)


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


class FailingTicker(Coglet, TickLet, LogLet):
    """Ticker that fails on first call then succeeds."""
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


class FailingStart(Coglet, LifeLet):
    """Coglet that fails on_start N times then succeeds."""
    def __init__(self, fail_count: int = 1, **kwargs: Any):
        super().__init__(**kwargs)
        self.fail_count = fail_count
        self.start_calls = 0

    async def on_start(self) -> None:
        self.start_calls += 1
        if self.start_calls <= self.fail_count:
            raise RuntimeError(f"start failure #{self.start_calls}")


class Parent(Coglet):
    """Parent that restarts children on error."""
    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)
        self.child_errors: list[Exception] = []

    async def on_child_error(self, handle: CogletHandle, error: Exception) -> str:
        self.child_errors.append(error)
        return "restart"


class StopParent(Coglet):
    """Parent that stops children on error (default)."""
    pass


class EscalateParent(Coglet):
    """Parent that escalates child errors."""
    async def on_child_error(self, handle: CogletHandle, error: Exception) -> str:
        return "escalate"


# ---- Tests ----

@pytest.mark.asyncio
async def test_suppresslet_channels():
    """SuppressLet gates transmit on suppressed channels."""
    rt = CogletRuntime()
    handle = await rt.spawn(CogletConfig(cls=SuppressedCollector))
    cog: SuppressedCollector = handle.coglet

    # Subscribe to output
    sub = cog._bus.subscribe("out")

    # Normal transmit works
    await cog._dispatch_listen("data", "hello")
    assert cog.received == ["hello"]
    msg = await asyncio.wait_for(sub.get(), timeout=1.0)
    assert msg == "hello"

    # Suppress the "out" channel
    await cog._dispatch_enact(Command("suppress", {"channels": ["out"]}))
    assert "out" in cog._suppressed_channels

    # Transmit is silenced
    await cog._dispatch_listen("data", "world")
    assert cog.received == ["hello", "world"]  # listen still fires
    # But nothing should be in the sub queue
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(sub.get(), timeout=0.05)

    # Unsuppress
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

    # Command is ignored
    await cog._dispatch_enact(Command("action", "stop"))
    assert ("action", "stop") not in cog.received

    # suppress/unsuppress always pass through
    await cog._dispatch_enact(Command("unsuppress", {"commands": ["action"]}))
    await cog._dispatch_enact(Command("action", "resume"))
    assert ("action", "resume") in cog.received

    await rt.shutdown()


@pytest.mark.asyncio
async def test_tree_visualization():
    """Runtime.tree() shows the coglet hierarchy."""
    rt = CogletRuntime()
    parent_handle = await rt.spawn(CogletConfig(cls=Parent))
    parent: Parent = parent_handle.coglet

    child_handle = await parent.create(CogletConfig(cls=Collector))

    output = rt.tree()
    assert "Parent" in output
    assert "Collector" in output
    assert "CogletRuntime" in output

    await rt.shutdown()


@pytest.mark.asyncio
async def test_tree_empty():
    rt = CogletRuntime()
    assert "empty" in rt.tree()
    await rt.shutdown()


@pytest.mark.asyncio
async def test_trace():
    """CogletTrace records transmit and enact events to jsonl."""
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
        trace_path = f.name

    try:
        trace = CogletTrace(trace_path)
        rt = CogletRuntime(trace=trace)
        handle = await rt.spawn(CogletConfig(cls=Collector))
        cog: Collector = handle.coglet

        await cog.transmit("out", {"msg": "hello"})
        await cog._dispatch_enact(Command("unknown", "test"))

        await rt.shutdown()

        entries = CogletTrace.load(trace_path)
        assert len(entries) >= 1
        transmit_entries = [e for e in entries if e["op"] == "transmit"]
        assert len(transmit_entries) >= 1
        assert transmit_entries[0]["target"] == "out"
        assert transmit_entries[0]["coglet"] == "Collector"
        assert "t" in transmit_entries[0]
    finally:
        Path(trace_path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_ticker_error_handling():
    """Ticker errors call on_ticker_error and continue running."""
    rt = CogletRuntime()
    handle = await rt.spawn(CogletConfig(cls=FailingTicker))
    cog: FailingTicker = handle.coglet

    # Wait for at least 2 tick cycles
    await asyncio.sleep(0.15)

    assert cog.tick_calls >= 2, f"Expected >=2 tick calls, got {cog.tick_calls}"
    assert len(cog.errors) == 1
    assert "boom" in str(cog.errors[0])

    await rt.shutdown()


@pytest.mark.asyncio
async def test_on_child_error_restart():
    """Parent with on_child_error='restart' restarts failed children."""
    rt = CogletRuntime()
    parent_handle = await rt.spawn(CogletConfig(cls=Parent))
    parent: Parent = parent_handle.coglet

    config = CogletConfig(
        cls=FailingStart, kwargs={"fail_count": 1},
        restart="on_error", max_restarts=3, backoff_s=0.01,
    )

    # Spawn will fail on on_start, so we need to handle this differently.
    # The restart logic is in handle_child_error, which is called externally.
    # Let's simulate: spawn fails, then we call handle_child_error.
    try:
        child_handle = await rt.spawn(config, parent=parent)
        # If we get here, start succeeded (fail_count=1, first call fails)
        # Actually on_start raises, so spawn raises
        assert False, "Should have raised"
    except RuntimeError:
        pass

    # The restart mechanism is for runtime errors during operation.
    # Let's test with a coglet that starts fine but we manually trigger error handling.
    config2 = CogletConfig(
        cls=Collector, restart="on_error", max_restarts=3, backoff_s=0.01,
    )
    child_handle2 = await rt.spawn(config2, parent=parent)
    old_coglet = child_handle2.coglet

    await rt.handle_child_error(child_handle2, RuntimeError("test error"))

    assert len(parent.child_errors) == 1
    assert str(parent.child_errors[0]) == "test error"
    # Handle should point to a new coglet instance
    assert child_handle2.coglet is not old_coglet

    await rt.shutdown()


@pytest.mark.asyncio
async def test_on_child_error_stop():
    """Default parent stops children on error."""
    rt = CogletRuntime()
    parent_handle = await rt.spawn(CogletConfig(cls=StopParent))
    parent: StopParent = parent_handle.coglet

    config = CogletConfig(cls=Collector, restart="on_error", max_restarts=3)
    child_handle = await rt.spawn(config, parent=parent)
    child = child_handle.coglet

    await rt.handle_child_error(child_handle, RuntimeError("test"))

    # Child should have been stopped (removed from runtime)
    assert child not in rt._coglets

    await rt.shutdown()


@pytest.mark.asyncio
async def test_on_child_error_escalate():
    """Escalate parent re-raises child error."""
    rt = CogletRuntime()
    parent_handle = await rt.spawn(CogletConfig(cls=EscalateParent))
    parent: EscalateParent = parent_handle.coglet

    config = CogletConfig(cls=Collector)
    child_handle = await rt.spawn(config, parent=parent)

    with pytest.raises(RuntimeError, match="escalated"):
        await rt.handle_child_error(child_handle, RuntimeError("escalated"))

    await rt.shutdown()


@pytest.mark.asyncio
async def test_config_restart_fields():
    """CogletConfig has restart, max_restarts, backoff_s."""
    config = CogletConfig(cls=Collector)
    assert config.restart == "never"
    assert config.max_restarts == 3
    assert config.backoff_s == 1.0

    config2 = CogletConfig(cls=Collector, restart="on_error", max_restarts=5, backoff_s=0.5)
    assert config2.restart == "on_error"
    assert config2.max_restarts == 5
    assert config2.backoff_s == 0.5
