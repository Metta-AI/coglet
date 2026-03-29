"""CodeLet mixin — mutable function table for runtime code hot-swap.

Functions are stored in self.functions dict and can be registered/replaced
at runtime via guide(handle, Command("register", {"name": callable})).
No persistence — ephemeral, in-memory only. Use GitLet for persistent policy.
"""
from __future__ import annotations

from typing import Any, Callable

from coglet.coglet import enact


class CodeLet:
    """Mixin: mutable function table.

    Behavior is a dict[str, Callable]. Functions are registered and
    replaced at runtime via @enact("register").
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.functions: dict[str, Callable] = {}

    @enact("register")
    async def _codelet_register(self, funcs: dict[str, Callable]) -> None:
        self.functions.update(funcs)
