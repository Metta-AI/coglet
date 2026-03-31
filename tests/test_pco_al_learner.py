"""Tests for ALLearnerCoglet — Agent Lightning APO inside PCO.

Tests the integration pattern using mocks (agentlightning not required)
and verifies that AL-backed learning works within PCO's constraint retry loop.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from coglet import Coglet, CogBase, CogletRuntime, enact, listen
from coglet.pco.al_learner import (
    ALLearnerCoglet,
    _default_reward,
    _default_context_formatter,
)
from coglet.pco.constraint import ConstraintCoglet
from coglet.pco.loss import LossCoglet
from coglet.pco.optimizer import ProximalCogletOptimizer


# ── Helpers ───────────────────────────────────────────────


class PromptActor(Coglet):
    """Actor whose 'policy' is a prompt string."""

    def __init__(self, *, inputs: list[str], **kwargs):
        super().__init__(**kwargs)
        self.prompt = "default prompt"
        self._inputs = inputs

    @enact("run")
    async def run_rollout(self, data):
        results = [
            {"input": inp, "output": f"[{self.prompt}] {inp}"}
            for inp in self._inputs
        ]
        await self.transmit("experience", {"results": results, "prompt": self.prompt})

    @enact("update")
    async def apply_update(self, patch):
        if "prompt" in patch:
            self.prompt = patch["prompt"]


class QualityCritic(Coglet):
    @listen("experience")
    async def evaluate(self, experience):
        # Score based on prompt length (longer = "better" for this toy example)
        prompt = experience.get("prompt", "")
        await self.transmit("evaluation", {
            "prompt_length": len(prompt),
            "num_results": len(experience["results"]),
        })

    @enact("update")
    async def apply_update(self, patch):
        pass


class PromptLengthLoss(LossCoglet):
    """Loss: penalize short prompts."""

    async def compute_loss(self, experience, evaluation):
        length = evaluation.get("prompt_length", 0)
        # Target: prompt should be >= 50 chars
        deficit = max(0, 50 - length)
        return {"name": "prompt_length", "magnitude": deficit}


class AlwaysAccept(ConstraintCoglet):
    async def check(self, patch):
        return {"accepted": True}


class RejectShortPrompts(ConstraintCoglet):
    """Reject prompts shorter than 20 chars."""

    async def check(self, patch):
        prompt = patch.get("prompt", "")
        if len(prompt) < 20:
            return {"accepted": False, "reason": f"prompt too short ({len(prompt)} chars)"}
        return {"accepted": True}


# ── Unit tests ────────────────────────────────────────────


def test_default_reward():
    signals = [
        {"name": "loss_a", "magnitude": 3},
        {"name": "loss_b", "magnitude": 7},
    ]
    assert _default_reward(signals) == -10.0


def test_default_reward_ignores_rejections():
    signals = [
        {"name": "loss", "magnitude": 5},
        {"rejection": "too big"},
    ]
    assert _default_reward(signals) == -5.0


def test_default_reward_empty():
    assert _default_reward([]) == 0.0


def test_default_context_formatter():
    result = _default_context_formatter(
        experience={"score": 10},
        evaluation={"grade": "B"},
        signals=[
            {"name": "accuracy", "magnitude": 3},
            {"rejection": "nope"},
        ],
    )
    assert "Experience:" in result
    assert "Evaluation:" in result
    assert "accuracy" in result
    assert "magnitude=3" in result
    assert "Rejection feedback: nope" in result


# ── Integration: ALLearnerCoglet in passthrough mode ──────


@pytest.mark.asyncio
async def test_al_learner_passthrough_without_agentlightning():
    """Without agentlightning installed, learn() returns current prompt."""
    learner = ALLearnerCoglet(
        resource_key="prompt",
        initial_prompt="be helpful",
    )
    result = await learner.learn(
        experience={"results": []},
        evaluation={"score": 5},
        signals=[{"name": "loss", "magnitude": 2}],
    )
    assert result["prompt"] == "be helpful"
    assert result["source"] == "agent_lightning_apo"
    assert result["reward"] == -2.0
    assert result["epoch"] == 1


@pytest.mark.asyncio
async def test_al_learner_custom_reward_fn():
    """Custom reward function is used."""
    learner = ALLearnerCoglet(
        initial_prompt="test",
        reward_fn=lambda signals: 42.0,
    )
    result = await learner.learn(
        experience={}, evaluation={}, signals=[],
    )
    assert result["reward"] == 42.0


@pytest.mark.asyncio
async def test_al_learner_tracks_epochs():
    """Epoch counter increments across learn() calls."""
    learner = ALLearnerCoglet(initial_prompt="v0")

    r1 = await learner.learn({}, {}, [])
    r2 = await learner.learn({}, {}, [])
    r3 = await learner.learn({}, {}, [])

    assert r1["epoch"] == 1
    assert r2["epoch"] == 2
    assert r3["epoch"] == 3


# ── Full PCO integration with ALLearnerCoglet ─────────────


@pytest.mark.asyncio
async def test_al_learner_in_pco_epoch():
    """ALLearnerCoglet works as a drop-in for PCO's learner slot."""
    learner = ALLearnerCoglet(
        resource_key="prompt",
        initial_prompt="be concise",
    )

    runtime = CogletRuntime()
    handle = await runtime.spawn(CogBase(
        cls=ProximalCogletOptimizer,
        kwargs=dict(
            actor_config=CogBase(
                cls=PromptActor,
                kwargs=dict(inputs=["hello", "world"]),
            ),
            critic_config=CogBase(cls=QualityCritic),
            losses=[PromptLengthLoss()],
            constraints=[AlwaysAccept()],
            learner=learner,
        ),
    ))
    pco = handle.coglet

    result = await pco.run_epoch()

    assert result["accepted"] is True
    assert result["patch"]["prompt"] == "be concise"
    assert result["patch"]["source"] == "agent_lightning_apo"
    # Actor received the update
    actor = pco._actor_handle.coglet
    assert actor.prompt == "be concise"
    await runtime.shutdown()


@pytest.mark.asyncio
async def test_al_learner_with_constraint_retry():
    """ALLearnerCoglet handles PCO constraint rejection and retry."""

    class GrowingALLearner(ALLearnerCoglet):
        """On rejection, appends to prompt to make it longer."""

        async def learn(self, experience, evaluation, signals):
            result = await super().learn(experience, evaluation, signals)
            # Check if we got rejected — signals will contain rejection feedback
            rejected = any(
                isinstance(s, dict) and "rejection" in s for s in signals
            )
            if rejected:
                # Make prompt longer to satisfy RejectShortPrompts
                result["prompt"] = result["prompt"] + " — improved with more detail"
            return result

    learner = GrowingALLearner(
        resource_key="prompt",
        initial_prompt="short",  # 5 chars, will be rejected
    )

    runtime = CogletRuntime()
    handle = await runtime.spawn(CogBase(
        cls=ProximalCogletOptimizer,
        kwargs=dict(
            actor_config=CogBase(
                cls=PromptActor,
                kwargs=dict(inputs=["test"]),
            ),
            critic_config=CogBase(cls=QualityCritic),
            losses=[PromptLengthLoss()],
            constraints=[RejectShortPrompts()],
            learner=learner,
            max_retries=3,
        ),
    ))
    pco = handle.coglet

    result = await pco.run_epoch()

    # First attempt: "short" (5 chars) rejected
    # Second attempt: "short — improved with more detail" (33 chars) accepted
    assert result["accepted"] is True
    assert "improved" in result["patch"]["prompt"]
    await runtime.shutdown()


@pytest.mark.asyncio
async def test_al_learner_multi_epoch_in_pco():
    """ALLearnerCoglet works across multiple PCO epochs."""
    learner = ALLearnerCoglet(
        resource_key="prompt",
        initial_prompt="v0",
    )

    runtime = CogletRuntime()
    handle = await runtime.spawn(CogBase(
        cls=ProximalCogletOptimizer,
        kwargs=dict(
            actor_config=CogBase(
                cls=PromptActor,
                kwargs=dict(inputs=["a"]),
            ),
            critic_config=CogBase(cls=QualityCritic),
            losses=[PromptLengthLoss()],
            constraints=[AlwaysAccept()],
            learner=learner,
        ),
    ))
    pco = handle.coglet

    results = await pco.run(num_epochs=3)

    assert len(results) == 3
    assert all(r["accepted"] for r in results)
    # Epoch counter advances
    assert results[0]["patch"]["epoch"] == 1
    assert results[1]["patch"]["epoch"] == 2
    assert results[2]["patch"]["epoch"] == 3
    await runtime.shutdown()
