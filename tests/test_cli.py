"""Tests for coglet CLI."""

import textwrap
from pathlib import Path

import pytest

from coglet.cli import build_config, load_manifest, resolve_class, load_cogbase
from coglet.runtime import CogletRuntime


@pytest.fixture
def cog_dir(tmp_path: Path) -> Path:
    """Create a minimal .cog directory."""
    d = tmp_path / "app.cog"
    d.mkdir()

    (d / "manifest.toml").write_text(textwrap.dedent("""\
        [coglet]
        class = "hello.HelloCoglet"

        [coglet.kwargs]
        greeting = "test"

        [config]
        restart = "on_error"
        max_restarts = 5
    """))

    (d / "hello.py").write_text(textwrap.dedent("""\
        from coglet import Coglet, LifeLet

        class HelloCoglet(Coglet, LifeLet):
            def __init__(self, greeting="default", **kwargs):
                super().__init__(**kwargs)
                self.greeting = greeting

            async def on_start(self):
                pass
    """))

    return d


@pytest.fixture
def cog_dir_with_children(tmp_path: Path) -> Path:
    """Create a .cog directory where root spawns a child."""
    d = tmp_path / "parent.cog"
    d.mkdir()

    (d / "manifest.toml").write_text(textwrap.dedent("""\
        [coglet]
        class = "parent.ParentCoglet"
    """))

    (d / "parent.py").write_text(textwrap.dedent("""\
        from coglet import Coglet, LifeLet, CogBase

        class ChildCoglet(Coglet, LifeLet):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                self.started = False

            async def on_start(self):
                self.started = True

        class ParentCoglet(Coglet, LifeLet):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                self.child_handle = None

            async def on_start(self):
                config = CogBase(cls=ChildCoglet)
                self.child_handle = await self.create(config)
    """))

    return d


def test_load_manifest(cog_dir: Path):
    manifest = load_manifest(cog_dir)
    assert manifest["coglet"]["class"] == "hello.HelloCoglet"
    assert manifest["coglet"]["kwargs"]["greeting"] == "test"
    assert manifest["config"]["restart"] == "on_error"


def test_load_manifest_missing(tmp_path: Path):
    d = tmp_path / "empty.cog"
    d.mkdir()
    with pytest.raises(SystemExit):
        load_manifest(d)


def test_resolve_class(cog_dir: Path):
    cls = resolve_class("hello.HelloCoglet", cog_dir)
    assert cls.__name__ == "HelloCoglet"


def test_resolve_class_bad_format(cog_dir: Path):
    with pytest.raises(SystemExit):
        resolve_class("NoModule", cog_dir)


def test_build_config(cog_dir: Path):
    manifest = load_manifest(cog_dir)
    cls = resolve_class(manifest["coglet"]["class"], cog_dir)
    config = build_config(manifest, cls)

    assert config.cls.__name__ == "HelloCoglet"
    assert config.kwargs == {"greeting": "test"}
    assert config.restart == "on_error"
    assert config.max_restarts == 5


@pytest.mark.asyncio
async def test_run_spawns_root(cog_dir: Path):
    """Verify run() creates runtime and spawns the root coglet."""
    base = load_cogbase(cog_dir)
    runtime = CogletRuntime()
    handle = await runtime.run(base)

    assert handle.coglet.greeting == "test"
    assert "HelloCoglet" in runtime.tree()

    await runtime.shutdown()


@pytest.mark.asyncio
async def test_child_spawning_via_runtime(cog_dir_with_children: Path):
    """Verify a coglet can spawn children through the runtime capability."""
    base = load_cogbase(cog_dir_with_children)
    runtime = CogletRuntime()
    handle = await runtime.run(base)

    parent = handle.coglet
    assert parent.child_handle is not None
    assert parent.child_handle.coglet.started is True
    assert "ChildCoglet" in runtime.tree()
    assert "ParentCoglet" in runtime.tree()

    await runtime.shutdown()
