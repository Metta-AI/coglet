"""Data types for coglet child management: Command, CogletConfig, CogletHandle.

CogletHandle is the opaque reference a parent COG holds to a child. It exposes
only observe() and guide() — the parent never accesses the child directly.
CogletConfig describes how to instantiate a coglet, including restart policy.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Type


@dataclass
class Command:
    """A control-plane command sent via guide()."""
    type: str
    data: Any = None


@dataclass
class CogletConfig:
    """Describes how to instantiate a Coglet."""
    cls: Type
    kwargs: dict[str, Any] = field(default_factory=dict)
    restart: str = "never"      # "never" | "on_error" | "always"
    max_restarts: int = 3
    backoff_s: float = 1.0


class CogletHandle:
    """Opaque reference to a running child Coglet.

    Used by parent COG for observe() and guide().
    """

    def __init__(self, coglet: Any):
        self._coglet = coglet

    async def observe(self, channel: str) -> AsyncIterator[Any]:
        sub = self._coglet._bus.subscribe(channel)
        async for data in sub:
            yield data

    async def guide(self, command: Command) -> None:
        """Fire-and-forget command to child's @enact handlers."""
        await self._coglet._dispatch_enact(command)

    @property
    def coglet(self) -> Any:
        return self._coglet
