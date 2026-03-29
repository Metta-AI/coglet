"""GitLet mixin — repo-as-policy for persistent, versioned behavior.

The coglet executes from HEAD. Patches are applied as git commits via
guide(handle, Command("commit", patch_str)). Rollback is git revert.
Branching enables parallel policy experiments. No custom serialization —
the patch protocol is pure git diffs.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any

from coglet.coglet import enact


class GitLet:
    """Mixin: repo-as-policy.

    The Coglet executes from HEAD. Patches are applied as git commits.
    Rollback is git revert. Branching enables parallel policy experiments.
    """

    def __init__(self, repo_path: str | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.repo_path: str = repo_path or os.getcwd()

    async def _git(self, *args: str) -> str:
        proc = await asyncio.create_subprocess_exec(
            "git", *args,
            cwd=self.repo_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} failed: {stderr.decode()}")
        return stdout.decode()

    @enact("commit")
    async def _gitlet_commit(self, patch: str) -> None:
        """Apply a patch as a git commit."""
        proc = await asyncio.create_subprocess_exec(
            "git", "apply", "--index", "-",
            cwd=self.repo_path,
            stdin=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate(patch.encode())
        if proc.returncode != 0:
            raise RuntimeError(f"git apply failed: {stderr.decode()}")
        await self._git("commit", "-m", "policy patch")

    async def revert(self, n: int = 1) -> None:
        await self._git("revert", "--no-edit", f"HEAD~{n}..HEAD")

    async def branch(self, name: str) -> None:
        await self._git("checkout", "-b", name)

    async def checkout(self, ref: str) -> None:
        await self._git("checkout", ref)
