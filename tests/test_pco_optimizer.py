import asyncio
import pytest
from coglet import Coglet, CogletRuntime, CogletConfig, listen, enact
from coglet.handle import Command
from coglet.pco.optimizer import ProximalCogletOptimizer
from coglet.pco.loss import LossCoglet
from coglet.pco.constraint import ConstraintCoglet
from coglet.pco.learner import LearnerCoglet


class FakeActor(Coglet):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.version = 0

    @enact("run")
    async def run_rollout(self, data):
        await self.transmit("experience", {"score": 10 + self.version})

    @enact("update")
    async def apply_update(self, patch):
        self.version += 1


class FakeCritic(Coglet):
    @listen("experience")
    async def evaluate(self, experience):
        await self.transmit("evaluation", {"score": experience["score"]})

    @enact("update")
    async def apply_update(self, patch):
        pass


class ScoreLoss(LossCoglet):
    async def compute_loss(self, experience, evaluation):
        return {"name": "score", "magnitude": evaluation["score"]}


class AlwaysAccept(ConstraintCoglet):
    async def check(self, patch):
        return {"accepted": True}


class FakeLearner(LearnerCoglet):
    async def learn(self, signals):
        return {"diff": "improve things"}


class RejectFirstConstraint(ConstraintCoglet):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._calls = 0

    async def check(self, patch):
        self._calls += 1
        if self._calls == 1:
            return {"accepted": False, "reason": "try again"}
        return {"accepted": True}


class RetryLearner(LearnerCoglet):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._calls = 0

    async def learn(self, signals):
        self._calls += 1
        return {"diff": f"attempt {self._calls}"}


@pytest.mark.asyncio
async def test_pco_runs_one_epoch():
    runtime = CogletRuntime()
    pco_handle = await runtime.spawn(CogletConfig(
        cls=ProximalCogletOptimizer,
        kwargs=dict(
            actor_config=CogletConfig(cls=FakeActor),
            critic_config=CogletConfig(cls=FakeCritic),
            losses=[ScoreLoss()],
            constraints=[AlwaysAccept()],
            learner=FakeLearner(),
        ),
    ))
    pco = pco_handle.coglet

    result = await pco.run_epoch()

    assert result["accepted"] is True
    assert result["signals"][0]["name"] == "score"
    assert pco._actor_handle.coglet.version == 1
    await runtime.shutdown()


@pytest.mark.asyncio
async def test_pco_retries_on_rejection():
    learner = RetryLearner()
    constraint = RejectFirstConstraint()
    runtime = CogletRuntime()
    pco_handle = await runtime.spawn(CogletConfig(
        cls=ProximalCogletOptimizer,
        kwargs=dict(
            actor_config=CogletConfig(cls=FakeActor),
            critic_config=CogletConfig(cls=FakeCritic),
            losses=[ScoreLoss()],
            constraints=[constraint],
            learner=learner,
            max_retries=3,
        ),
    ))
    pco = pco_handle.coglet

    result = await pco.run_epoch()

    assert result["accepted"] is True
    assert learner._calls == 2
    assert constraint._calls == 2
    await runtime.shutdown()


@pytest.mark.asyncio
async def test_pco_multi_epoch():
    runtime = CogletRuntime()
    pco_handle = await runtime.spawn(CogletConfig(
        cls=ProximalCogletOptimizer,
        kwargs=dict(
            actor_config=CogletConfig(cls=FakeActor),
            critic_config=CogletConfig(cls=FakeCritic),
            losses=[ScoreLoss()],
            constraints=[AlwaysAccept()],
            learner=FakeLearner(),
        ),
    ))
    pco = pco_handle.coglet

    epochs = []
    async def collect():
        async for e in pco_handle.observe("epoch"):
            epochs.append(e)
            if len(epochs) >= 3:
                break

    task = asyncio.create_task(collect())
    await asyncio.sleep(0.01)

    await pco.run(num_epochs=3)

    await asyncio.wait_for(task, timeout=5.0)
    assert len(epochs) == 3
    assert all(e["accepted"] for e in epochs)
    assert pco._actor_handle.coglet.version == 3
    await runtime.shutdown()
