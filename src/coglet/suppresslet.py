"""SuppressLet mixin — COG-controlled output gating (inspired by subsumption architecture).

A COG can suppress specific channels or commands on a LET without stopping it.
The LET keeps running and processing internally, but suppressed outputs are silenced.
Must appear before Coglet in MRO: class MyLET(SuppressLet, Coglet): ...
"""

from __future__ import annotations

from typing import Any

from coglet.coglet import enact
from coglet.handle import Command


class SuppressLet:
    """Mixin: COG can suppress/unsuppress channels and commands.

    A suppressed channel silences transmit() — the LET keeps running
    but output is gated. A suppressed command is ignored by _dispatch_enact().
    Meta-commands (suppress/unsuppress) always pass through.

    Must be mixed with Coglet to access transmit() and _dispatch_enact().
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._suppressed_channels: set[str] = set()
        self._suppressed_commands: set[str] = set()

    async def transmit(self, channel: str, data: Any) -> None:
        if channel not in self._suppressed_channels:
            await super().transmit(channel, data)  # type: ignore[misc]

    def transmit_sync(self, channel: str, data: Any) -> None:
        if channel not in self._suppressed_channels:
            super().transmit_sync(channel, data)  # type: ignore[misc]

    async def _dispatch_enact(self, command: Command) -> None:
        if command.type in ("suppress", "unsuppress"):
            await super()._dispatch_enact(command)  # type: ignore[misc]
        elif command.type not in self._suppressed_commands:
            await super()._dispatch_enact(command)  # type: ignore[misc]

    @enact("suppress")
    async def _suppresslet_suppress(self, data: dict) -> None:
        for ch in data.get("channels", []):
            self._suppressed_channels.add(ch)
        for cmd in data.get("commands", []):
            self._suppressed_commands.add(cmd)

    @enact("unsuppress")
    async def _suppresslet_unsuppress(self, data: dict) -> None:
        for ch in data.get("channels", []):
            self._suppressed_channels.discard(ch)
        for cmd in data.get("commands", []):
            self._suppressed_commands.discard(cmd)
