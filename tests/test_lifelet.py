"""Unit tests for coglet.lifelet: LifeLet mixin."""
from __future__ import annotations

from typing import Any

import pytest

from coglet import Coglet, CogletConfig, CogletRuntime, LifeLet


class TrackingLifeLet(Coglet, LifeLet):
    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)
        self.started = False
        self.stopped = False

    async def on_start(self) -> None:
        self.started = True

    async def on_stop(self) -> None:
        self.stopped = True


class FailingLifeLet(Coglet, LifeLet):
    async def on_start(self) -> None:
        raise ValueError("start failed")


@pytest.mark.asyncio
async def test_lifelet_start_stop():
    rt = CogletRuntime()
    handle = await rt.spawn(CogletConfig(cls=TrackingLifeLet))
    cog: TrackingLifeLet = handle.coglet
    assert cog.started is True
    assert cog.stopped is False
    await rt.shutdown()
    assert cog.stopped is True


@pytest.mark.asyncio
async def test_lifelet_start_failure_propagates():
    rt = CogletRuntime()
    with pytest.raises(ValueError, match="start failed"):
        await rt.spawn(CogletConfig(cls=FailingLifeLet))
    await rt.shutdown()
