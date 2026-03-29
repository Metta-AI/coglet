"""Integration tests: PCO teaches actors progressively harder target functions.

Each test uses the same PCO components (Actor, Critic, Loss, Constraint) but
with different target functions and learners of increasing difficulty.

1. Odd/Even — two linear rules, learnable in 2 epochs
2. Collatz step — non-obvious odd rule (3x+1), needs ratio inference
3. Tax brackets — three piecewise ranges, one bracket per epoch
4. Modular dispatch — three rules keyed on x%3, each a different operation
5. Constraint rejection — learner proposes a change that's too big, retries
"""

import asyncio

import pytest

from coglet import Coglet, CogletConfig, CogletRuntime, enact, listen
from coglet.pco.constraint import ConstraintCoglet
from coglet.pco.learner import LearnerCoglet
from coglet.pco.loss import LossCoglet
from coglet.pco.optimizer import ProximalCogletOptimizer


# ── Shared components ──────────────────────────────────────


class FnActor(Coglet):
    """Actor with a replaceable function. Starts as identity."""

    def __init__(self, *, inputs: list[int], target, **kwargs):
        super().__init__(**kwargs)
        self.fn = lambda x: x
        self._inputs = inputs
        self._target = target

    @enact("run")
    async def run_rollout(self, data):
        results = [
            {"input": x, "output": self.fn(x), "expected": self._target(x)}
            for x in self._inputs
        ]
        await self.transmit("experience", {"results": results})

    @enact("update")
    async def apply_update(self, patch):
        self.fn = patch["fn"]


class ErrorCritic(Coglet):
    @listen("experience")
    async def evaluate(self, experience):
        errors = [r for r in experience["results"] if r["output"] != r["expected"]]
        await self.transmit("evaluation", {
            "errors": errors,
            "correct": len(experience["results"]) - len(errors),
            "total": len(experience["results"]),
        })

    @enact("update")
    async def apply_update(self, patch):
        pass


class ErrorCountLoss(LossCoglet):
    async def compute_loss(self, experience, evaluation):
        return {
            "name": "error_count",
            "magnitude": len(evaluation["errors"]),
            "errors": evaluation["errors"],
        }


class AlwaysAccept(ConstraintCoglet):
    async def check(self, patch):
        return {"accepted": True}


async def run_pco(*, target, inputs, learner, epochs, constraints=None):
    """Helper: run PCO for N epochs and return (results, actor)."""
    runtime = CogletRuntime()
    handle = await runtime.spawn(CogletConfig(
        cls=ProximalCogletOptimizer,
        kwargs=dict(
            actor_config=CogletConfig(
                cls=FnActor,
                kwargs=dict(inputs=inputs, target=target),
            ),
            critic_config=CogletConfig(cls=ErrorCritic),
            losses=[ErrorCountLoss()],
            constraints=constraints or [AlwaysAccept()],
            learner=learner,
        ),
    ))
    pco = handle.coglet
    results = await pco.run(num_epochs=epochs)
    actor = pco._actor_handle.coglet
    await runtime.shutdown()
    return results, actor


# ═══════════════════════════════════════════════════════════
# Test 1: Odd/Even — two linear rules
# Target: 2*x if odd, x-1 if even
# ═══════════════════════════════════════════════════════════


class OddEvenLearner(LearnerCoglet):
    """Learns one parity rule per epoch from (input, expected) examples."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._odd_mult: float | None = None
        self._even_offset: float | None = None

    async def learn(self, experience, evaluation, signals):
        errors = evaluation["errors"]
        odd_errors = [e for e in errors if e["input"] % 2 == 1]
        even_errors = [e for e in errors if e["input"] % 2 == 0]

        if odd_errors and self._odd_mult is None:
            e = odd_errors[0]
            self._odd_mult = e["expected"] / e["input"]
        elif even_errors and self._even_offset is None:
            e = even_errors[0]
            self._even_offset = e["expected"] - e["input"]

        om = self._odd_mult or 1
        eo = self._even_offset or 0

        def fn(x, _om=om, _eo=eo):
            return int(x * _om) if x % 2 == 1 else int(x + _eo)

        return {"fn": fn}


@pytest.mark.asyncio
async def test_odd_even():
    target = lambda x: 2 * x if x % 2 == 1 else x - 1
    results, actor = await run_pco(
        target=target,
        inputs=list(range(1, 11)),
        learner=OddEvenLearner(),
        epochs=3,
    )

    errors = [r["signals"][0]["magnitude"] for r in results]
    assert errors == [10, 5, 0]
    for x in range(1, 11):
        assert actor.fn(x) == target(x)


# ═══════════════════════════════════════════════════════════
# Test 2: Collatz step — non-obvious rules
# Target: x/2 if even, 3*x+1 if odd
# Harder because odd rule isn't a simple multiple.
# ═══════════════════════════════════════════════════════════


class CollatzLearner(LearnerCoglet):
    """Infers Collatz rules from error examples.

    Even rule: discovers division by looking at expected/input ratio.
    Odd rule: needs two examples to solve ax+b (two unknowns).
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._even_divisor: float | None = None
        self._odd_a: float | None = None
        self._odd_b: float | None = None

    async def learn(self, experience, evaluation, signals):
        errors = evaluation["errors"]
        even_errors = [e for e in errors if e["input"] % 2 == 0]
        odd_errors = [e for e in errors if e["input"] % 2 == 1]

        if even_errors and self._even_divisor is None:
            e = even_errors[0]
            self._even_divisor = e["input"] / e["expected"]

        if odd_errors and self._odd_a is None and len(odd_errors) >= 2:
            # Solve: expected = a*input + b with two examples
            e1, e2 = odd_errors[0], odd_errors[1]
            x1, y1 = e1["input"], e1["expected"]
            x2, y2 = e2["input"], e2["expected"]
            if x1 != x2:
                self._odd_a = (y2 - y1) / (x2 - x1)
                self._odd_b = y1 - self._odd_a * x1

        ed = self._even_divisor or 1
        oa = self._odd_a or 1
        ob = self._odd_b or 0

        def fn(x, _ed=ed, _oa=oa, _ob=ob):
            if x % 2 == 0:
                return int(x / _ed)
            return int(x * _oa + _ob)

        return {"fn": fn}


@pytest.mark.asyncio
async def test_collatz_step():
    target = lambda x: x // 2 if x % 2 == 0 else 3 * x + 1
    inputs = list(range(1, 13))

    results, actor = await run_pco(
        target=target,
        inputs=inputs,
        learner=CollatzLearner(),
        epochs=4,
    )

    errors = [r["signals"][0]["magnitude"] for r in results]
    assert errors[0] > 0  # starts wrong
    assert errors[-1] == 0  # converges
    for x in inputs:
        assert actor.fn(x) == target(x), f"collatz({x}): got {actor.fn(x)}, want {target(x)}"


# ═══════════════════════════════════════════════════════════
# Test 3: Tax brackets — three piecewise ranges
# Target: x<=10: 0, 11-50: (x-10)*10%, 51+: (x-50)*20% + 4
# Learner discovers one bracket per epoch.
# ═══════════════════════════════════════════════════════════


def tax(x: int) -> int:
    """Piecewise linear: 0 for x<=10, 2*x-20 for 11-50, 3*x+10 for 51+."""
    if x <= 10:
        return 0
    if x <= 50:
        return 2 * x - 20
    return 3 * x + 10


class BracketLearner(LearnerCoglet):
    """Discovers piecewise rules one bracket at a time.

    Groups errors into ranges, fits a linear rule (y = a*x + b) for the
    range with the most errors. Handles constant-output brackets specially.
    """

    BRACKETS = [(0, 10), (11, 50), (51, 200)]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._rules: dict[tuple[int, int], tuple[float, float]] = {}

    async def learn(self, experience, evaluation, signals):
        errors = evaluation["errors"]
        if not errors:
            return {"fn": self._build_fn()}

        # Group errors by bracket
        groups: dict[tuple[int, int], list[dict]] = {b: [] for b in self.BRACKETS}
        for e in errors:
            for lo, hi in self.BRACKETS:
                if lo <= e["input"] <= hi:
                    groups[(lo, hi)].append(e)
                    break

        # Fix the unlearned bracket with the most errors
        for bracket in sorted(groups, key=lambda b: -len(groups[b])):
            group = groups[bracket]
            if not group or bracket in self._rules:
                continue

            # Constant bracket: all expected values are the same
            if all(e["expected"] == group[0]["expected"] for e in group):
                self._rules[bracket] = (0, group[0]["expected"])
                break

            # Linear fit from two examples
            if len(group) >= 2:
                e1, e2 = group[0], group[1]
                x1, y1 = e1["input"], e1["expected"]
                x2, y2 = e2["input"], e2["expected"]
                if x1 != x2:
                    a = (y2 - y1) / (x2 - x1)
                    b = y1 - a * x1
                    self._rules[bracket] = (a, b)
                    break

        return {"fn": self._build_fn()}

    def _build_fn(self):
        rules = dict(self._rules)
        brackets = sorted(rules.keys())

        def fn(x, _rules=rules, _brackets=brackets):
            for lo, hi in _brackets:
                if lo <= x <= hi:
                    a, b = _rules[(lo, hi)]
                    return int(a * x + b)
            return x

        return fn


@pytest.mark.asyncio
async def test_tax_brackets():
    inputs = [5, 10, 15, 20, 30, 40, 50, 55, 60, 70, 80, 100]

    results, actor = await run_pco(
        target=tax,
        inputs=inputs,
        learner=BracketLearner(),
        epochs=5,
    )

    errors = [r["signals"][0]["magnitude"] for r in results]
    assert errors[0] > 0
    assert errors[-1] == 0
    for x in inputs:
        assert actor.fn(x) == tax(x), f"tax({x}): got {actor.fn(x)}, want {tax(x)}"


# ═══════════════════════════════════════════════════════════
# Test 4: Modular dispatch — three operations keyed on x%3
# Target: x%3==0: x*3, x%3==1: x+7, x%3==2: x-2
# ═══════════════════════════════════════════════════════════


def mod_dispatch(x: int) -> int:
    if x % 3 == 0:
        return x * 3
    if x % 3 == 1:
        return x + 7
    return x - 2


class ModularLearner(LearnerCoglet):
    """Discovers one modular rule per epoch via linear fit."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._rules: dict[int, tuple[float, float]] = {}  # mod_class -> (a, b)

    async def learn(self, experience, evaluation, signals):
        errors = evaluation["errors"]
        if not errors:
            return {"fn": self._build_fn()}

        # Group by mod class
        by_mod: dict[int, list[dict]] = {0: [], 1: [], 2: []}
        for e in errors:
            by_mod[e["input"] % 3].append(e)

        # Fit the largest unlearned group
        for mod_class in sorted(by_mod, key=lambda k: -len(by_mod[k])):
            group = by_mod[mod_class]
            if mod_class in self._rules or len(group) < 2:
                continue
            e1, e2 = group[0], group[1]
            x1, y1 = e1["input"], e1["expected"]
            x2, y2 = e2["input"], e2["expected"]
            if x1 != x2:
                a = (y2 - y1) / (x2 - x1)
                b = y1 - a * x1
                self._rules[mod_class] = (a, b)
                break

        return {"fn": self._build_fn()}

    def _build_fn(self):
        rules = dict(self._rules)

        def fn(x, _rules=rules):
            mod = x % 3
            if mod in _rules:
                a, b = _rules[mod]
                return int(a * x + b)
            return x

        return fn


@pytest.mark.asyncio
async def test_modular_dispatch():
    inputs = list(range(1, 16))

    results, actor = await run_pco(
        target=mod_dispatch,
        inputs=inputs,
        learner=ModularLearner(),
        epochs=5,
    )

    errors = [r["signals"][0]["magnitude"] for r in results]
    assert errors[0] > 0
    assert errors[-1] == 0
    for x in inputs:
        assert actor.fn(x) == mod_dispatch(x), f"mod({x}): got {actor.fn(x)}, want {mod_dispatch(x)}"


# ═══════════════════════════════════════════════════════════
# Test 5: Constraint rejection forces smaller updates
# Learner tries to fix everything at once, constraint rejects,
# learner falls back to partial fix.
# ═══════════════════════════════════════════════════════════


class MaxNewRulesConstraint(ConstraintCoglet):
    """Rejects patches that change too many rules at once."""

    async def check(self, patch):
        new_rules = patch.get("new_rules_count", 0)
        if new_rules > 1:
            return {"accepted": False, "reason": f"too many new rules: {new_rules}"}
        return {"accepted": True}


class GreedyThenCarefulLearner(LearnerCoglet):
    """First attempt: tries to fix everything. On rejection: fixes one rule.

    Target: same odd/even rules.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._odd_mult: float | None = None
        self._even_offset: float | None = None

    async def learn(self, experience, evaluation, signals):
        errors = evaluation["errors"]
        rejected = any(
            isinstance(s, dict) and "rejection" in s for s in signals
        )

        odd_errors = [e for e in errors if e["input"] % 2 == 1]
        even_errors = [e for e in errors if e["input"] % 2 == 0]

        new_rules = 0
        if not rejected:
            # Greedy: try to learn everything at once
            if odd_errors and self._odd_mult is None:
                e = odd_errors[0]
                self._odd_mult = e["expected"] / e["input"]
                new_rules += 1
            if even_errors and self._even_offset is None:
                e = even_errors[0]
                self._even_offset = e["expected"] - e["input"]
                new_rules += 1
        else:
            # Careful: learn only one rule
            if odd_errors and self._odd_mult is None:
                e = odd_errors[0]
                self._odd_mult = e["expected"] / e["input"]
                new_rules = 1
            elif even_errors and self._even_offset is None:
                e = even_errors[0]
                self._even_offset = e["expected"] - e["input"]
                new_rules = 1

        om = self._odd_mult or 1
        eo = self._even_offset or 0

        def fn(x, _om=om, _eo=eo):
            return int(x * _om) if x % 2 == 1 else int(x + _eo)

        return {"fn": fn, "new_rules_count": new_rules}


@pytest.mark.asyncio
async def test_constraint_forces_incremental_learning():
    target = lambda x: 2 * x if x % 2 == 1 else x - 1

    results, actor = await run_pco(
        target=target,
        inputs=list(range(1, 11)),
        learner=GreedyThenCarefulLearner(),
        constraints=[MaxNewRulesConstraint()],
        epochs=4,
    )

    # First epoch: greedy attempt rejected (2 rules), retry with 1 rule accepted
    assert results[0]["accepted"] is True

    # Should converge
    errors = [r["signals"][0]["magnitude"] for r in results]
    assert errors[-1] == 0
    for x in range(1, 11):
        assert actor.fn(x) == target(x)
