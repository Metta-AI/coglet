"""Async pub/sub channel system for coglet communication.

Each Coglet owns a ChannelBus. transmit() pushes data to all subscribers on a
named channel. Each subscribe() call creates an independent queue — no message
loss from slow consumers, but subscribers must exist before transmit (no replay).
"""
from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator


class Channel:
    """Single named async channel backed by an asyncio.Queue."""

    def __init__(self, maxsize: int = 0):
        self._queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=maxsize)

    async def put(self, data: Any) -> None:
        await self._queue.put(data)

    def put_nowait(self, data: Any) -> None:
        self._queue.put_nowait(data)

    async def get(self) -> Any:
        return await self._queue.get()

    async def __aiter__(self) -> AsyncIterator[Any]:
        while True:
            yield await self.get()

    def subscribe(self) -> ChannelSubscription:
        """Create a new subscription (separate queue) for this channel."""
        return ChannelSubscription(self)


class ChannelSubscription:
    """Independent subscriber to a channel. Each subscriber gets its own queue."""

    def __init__(self, parent: Channel):
        self._queue: asyncio.Queue[Any] = asyncio.Queue()
        self._parent = parent

    async def get(self) -> Any:
        return await self._queue.get()

    async def __aiter__(self) -> AsyncIterator[Any]:
        while True:
            yield await self.get()


class ChannelBus:
    """Per-Coglet outbound channel registry.

    transmit() pushes to named channels. Observers subscribe to get
    independent async iterators over channel data.
    """

    def __init__(self):
        self._channels: dict[str, Channel] = {}
        self._subscribers: dict[str, list[ChannelSubscription]] = {}

    def _ensure_channel(self, name: str) -> Channel:
        if name not in self._channels:
            self._channels[name] = Channel()
            self._subscribers[name] = []
        return self._channels[name]

    async def transmit(self, channel: str, data: Any) -> None:
        self._ensure_channel(channel)
        for sub in self._subscribers[channel]:
            await sub._queue.put(data)

    def transmit_nowait(self, channel: str, data: Any) -> None:
        self._ensure_channel(channel)
        for sub in self._subscribers[channel]:
            sub._queue.put_nowait(data)

    def subscribe(self, channel: str) -> ChannelSubscription:
        self._ensure_channel(channel)
        sub = ChannelSubscription(self._channels[channel])
        self._subscribers[channel].append(sub)
        return sub
