"""Unit tests for coglet.codelet: CodeLet mixin."""
from __future__ import annotations

import pytest

from coglet import Coglet, CodeLet, Command


class PolicyCodeLet(Coglet, CodeLet):
    pass


@pytest.mark.asyncio
async def test_codelet_register():
    cog = PolicyCodeLet()
    assert cog.functions == {}

    def my_fn(x):
        return x * 2

    await cog._dispatch_enact(Command("register", {"double": my_fn}))
    assert "double" in cog.functions
    assert cog.functions["double"](5) == 10


@pytest.mark.asyncio
async def test_codelet_update():
    cog = PolicyCodeLet()
    await cog._dispatch_enact(Command("register", {"f": lambda x: x}))
    await cog._dispatch_enact(Command("register", {"f": lambda x: x + 1}))
    assert cog.functions["f"](0) == 1


@pytest.mark.asyncio
async def test_codelet_multiple():
    cog = PolicyCodeLet()
    await cog._dispatch_enact(Command("register", {
        "add": lambda a, b: a + b,
        "mul": lambda a, b: a * b,
    }))
    assert cog.functions["add"](2, 3) == 5
    assert cog.functions["mul"](2, 3) == 6
