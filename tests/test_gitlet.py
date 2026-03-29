"""Unit tests for coglet.gitlet: GitLet mixin."""
from __future__ import annotations

import asyncio
import os
import tempfile

import pytest

from coglet import Coglet, GitLet


class PolicyGitLet(Coglet, GitLet):
    pass


@pytest.mark.asyncio
async def test_gitlet_default_repo_path():
    cog = PolicyGitLet()
    assert cog.repo_path == os.getcwd()


@pytest.mark.asyncio
async def test_gitlet_custom_repo_path():
    cog = PolicyGitLet(repo_path="/tmp/test-repo")
    assert cog.repo_path == "/tmp/test-repo"


@pytest.mark.asyncio
async def test_gitlet_git_command():
    """_git runs git commands in repo_path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cog = PolicyGitLet(repo_path=tmpdir)
        proc = await asyncio.create_subprocess_exec(
            "git", "init", cwd=tmpdir,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        result = await cog._git("status")
        assert "On branch" in result or "No commits" in result


@pytest.mark.asyncio
async def test_gitlet_git_failure():
    with tempfile.TemporaryDirectory() as tmpdir:
        cog = PolicyGitLet(repo_path=tmpdir)
        with pytest.raises(RuntimeError, match="git .* failed"):
            await cog._git("log")


@pytest.mark.asyncio
async def test_gitlet_commit_enact():
    """GitLet has a 'commit' enact handler registered."""
    assert "commit" in PolicyGitLet._enact_handlers
