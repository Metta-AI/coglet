"""Unit tests for coglet.mullet: MulLet mixin."""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from coglet import Coglet, CogletConfig, CogletRuntime, Command, MulLet, listen, enact


class Worker(Coglet):
    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)
        self.received: list[Any] = []

    @listen("task")
    async def on_task(self, data: Any) -> None:
        self.received.append(data)
        await self.transmit("result", f"done:{data}")

    @enact("cmd")
    async def on_cmd(self, data: Any) -> None:
        self.received.append(("cmd", data))


class Fleet(Coglet, MulLet):
    pass


class CustomFleet(Coglet, MulLet):
    def map(self, event: Any) -> list[tuple[int, Any]]:
        return [(0, event)]

    def reduce(self, results: list[Any]) -> Any:
        return ",".join(str(r) for r in results)


@pytest.mark.asyncio
async def test_mullet_create_mul():
    rt = CogletRuntime()
    handle = await rt.spawn(CogletConfig(cls=Fleet))
    fleet: Fleet = handle.coglet
    await fleet.create_mul(3, CogletConfig(cls=Worker))
    assert len(fleet._mul_children) == 3
    await rt.shutdown()


@pytest.mark.asyncio
async def test_mullet_guide_mapped():
    rt = CogletRuntime()
    handle = await rt.spawn(CogletConfig(cls=Fleet))
    fleet: Fleet = handle.coglet
    await fleet.create_mul(3, CogletConfig(cls=Worker))
    await fleet.guide_mapped(Command("cmd", "hello"))
    for child_handle in fleet._mul_children:
        assert ("cmd", "hello") in child_handle.coglet.received
    await rt.shutdown()


@pytest.mark.asyncio
async def test_mullet_scatter_broadcast():
    rt = CogletRuntime()
    handle = await rt.spawn(CogletConfig(cls=Fleet))
    fleet: Fleet = handle.coglet
    await fleet.create_mul(3, CogletConfig(cls=Worker))
    await fleet.scatter("task", "job1")
    for child_handle in fleet._mul_children:
        assert "job1" in child_handle.coglet.received
    await rt.shutdown()


@pytest.mark.asyncio
async def test_mullet_gather():
    rt = CogletRuntime()
    handle = await rt.spawn(CogletConfig(cls=Fleet))
    fleet: Fleet = handle.coglet
    await fleet.create_mul(2, CogletConfig(cls=Worker))

    subs = []
    for child_handle in fleet._mul_children:
        subs.append(child_handle.coglet._bus.subscribe("result"))

    await fleet.scatter("task", "x")

    results = []
    for sub in subs:
        results.append(await asyncio.wait_for(sub.get(), timeout=1.0))
    assert len(results) == 2
    assert all(r == "done:x" for r in results)
    await rt.shutdown()


@pytest.mark.asyncio
async def test_mullet_default_map_broadcast():
    fleet = Fleet()
    fleet._mul_children = [None, None, None]  # type: ignore
    mappings = fleet.map("event")
    assert mappings == [(0, "event"), (1, "event"), (2, "event")]


@pytest.mark.asyncio
async def test_mullet_default_reduce():
    fleet = Fleet()
    assert fleet.reduce([1, 2, 3]) == [1, 2, 3]


@pytest.mark.asyncio
async def test_mullet_custom_map():
    rt = CogletRuntime()
    handle = await rt.spawn(CogletConfig(cls=CustomFleet))
    fleet: CustomFleet = handle.coglet
    await fleet.create_mul(3, CogletConfig(cls=Worker))
    await fleet.scatter("task", "only-first")
    assert "only-first" in fleet._mul_children[0].coglet.received
    assert fleet._mul_children[1].coglet.received == []
    assert fleet._mul_children[2].coglet.received == []
    await rt.shutdown()


@pytest.mark.asyncio
async def test_mullet_custom_reduce():
    fleet = CustomFleet()
    result = fleet.reduce(["a", "b", "c"])
    assert result == "a,b,c"
