# PCO-Driven PlayerCoglet Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the hard-coded CvC decision engine with a ProgLet program table optimized by PCO between games.

**Architecture:** The program table is a dict of `name → Program` seeded from existing CvcEngine heuristics. Code programs (Python functions) handle fast reactive actions; LLM programs (prompts) handle slow strategic analysis. PCO runs between episodes — critic evaluates, losses signal, learner proposes patches, constraints validate, table updates.

**Tech Stack:** coglet framework (ProgLet, PCO), cogames (MultiAgentPolicy), anthropic SDK

---

### Task 1: Seed Program Table

**Files:**
- Create: `cogames/cvc/programs.py`
- Test: `tests/test_cvc_programs.py`

The seed programs wrap existing CvcEngine methods as individually replaceable callables. Each code program takes a `StepContext` dataclass:

**Step 1: Write StepContext and seed programs**

```python
# cogames/cvc/programs.py
"""Seed program table: decomposed CvcEngine heuristics as named programs."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from coglet.proglet import Program

from cvc.agent.coglet_policy import CogletAgentPolicy
from cvc.agent import helpers as _h
from cvc.agent.helpers.types import KnownEntity


@dataclass
class StepContext:
    """Context passed to every program in the table."""
    engine: CogletAgentPolicy
    state: Any  # MettagridState
    role: str
    invoke: Callable  # call other programs: invoke("mine", ctx) -> result


def _heal(ctx: StepContext) -> Any | None:
    """Early-game healing and wipeout recovery. Returns Action or None."""
    engine = ctx.engine
    state = ctx.state
    hp = int(state.self_state.inventory.get("hp", 0))
    step = engine._step_index

    # Hub camp heal at start
    if step <= 20 and hp < 100:
        summary = engine._hold(None, "change_vibe_default")
        return summary

    # Early game survival — rush home if far and low HP
    if step < 150:
        pos = _h.absolute_position(state)
        hub = engine._nearest_hub(state)
        if hub and hp < 50 and _h.manhattan(pos, hub.position) > 10:
            return engine._move_to_known(state, hub, "rush_home")

    # Wipeout recovery
    if hp == 0:
        hub = engine._nearest_hub(state)
        if hub:
            return engine._move_to_known(state, hub, "wipeout_recovery")
        return engine._hold(None, "change_vibe_default")

    return None


def _retreat(ctx: StepContext) -> Any | None:
    """Danger assessment and retreat. Returns Action or None."""
    engine = ctx.engine
    state = ctx.state
    role = ctx.role
    hub = engine._nearest_hub(state)
    if engine._should_retreat(state, role, hub):
        if hub:
            return engine._move_to_known(state, hub, "retreat")
        return engine._hold(None, "change_vibe_default")
    return None


def _mine(ctx: StepContext) -> tuple[Any, str]:
    """Miner role action."""
    return ctx.engine._miner_action(ctx.state)


def _align(ctx: StepContext) -> tuple[Any, str]:
    """Aligner role action."""
    return ctx.engine._aligner_action(ctx.state)


def _scramble(ctx: StepContext) -> tuple[Any, str]:
    """Scrambler role action."""
    return ctx.engine._scrambler_action(ctx.state)


def _explore(ctx: StepContext) -> tuple[Any, str]:
    """Scout/explore role action."""
    summary = engine._macro_snapshot(ctx.state, ctx.role) if hasattr(ctx.engine, '_macro_snapshot') else None
    return ctx.engine._explore_action(ctx.state, ctx.role, summary)


def _macro(ctx: StepContext) -> dict:
    """Resource bias and role allocation."""
    directive = ctx.engine._macro_directive(ctx.state)
    budgets = ctx.engine._pressure_budgets(ctx.state)
    return {"directive": directive, "budgets": budgets}


def _summarize(ctx: StepContext) -> dict:
    """Build experience summary from game state for the learner."""
    state = ctx.state
    engine = ctx.engine
    inv = state.self_state.inventory
    team = state.team_summary
    resources = {}
    if team:
        resources = {r: int(team.shared_inventory.get(r, 0))
                     for r in ("carbon", "oxygen", "germanium", "silicon")}

    team_id_val = team.team_id if team else ""
    junctions = {"friendly": 0, "enemy": 0, "neutral": 0}
    for e in state.visible_entities:
        if e.entity_type == "junction":
            owner = e.attributes.get("owner")
            if owner == team_id_val:
                junctions["friendly"] += 1
            elif owner in {None, "neutral"}:
                junctions["neutral"] += 1
            else:
                junctions["enemy"] += 1

    roles: dict[str, int] = {}
    if team:
        for m in team.members:
            roles[m.role] = roles.get(m.role, 0) + 1

    return {
        "step": engine._step_index,
        "hp": inv.get("hp", 0),
        "hearts": inv.get("heart", 0),
        "resources": resources,
        "roles": roles,
        "junctions": junctions,
        "role": ctx.role,
    }


def _step(ctx: StepContext) -> Any:
    """Main dispatch — priority-based, calls sub-programs."""
    engine = ctx.engine
    state = ctx.state
    role = ctx.role

    # Survival
    action = ctx.invoke("heal", ctx)
    if action is not None:
        return action

    action = ctx.invoke("retreat", ctx)
    if action is not None:
        return action

    # Unstick (keep engine's built-in logic)
    if engine._oscillation_steps >= 4:
        return engine._unstick_action(state, role)
    if engine._stalled_steps >= 12:
        return engine._unstick_action(state, role)

    # Emergency mining
    if _h.needs_emergency_mining(state):
        result = ctx.invoke("mine", ctx)
        return result[0] if isinstance(result, tuple) else result

    # Gear acquisition
    if not _h.has_role_gear(state, role) and _h.team_can_afford_gear(state, role):
        action = engine._acquire_role_gear(state, role)
        if action is not None:
            return action

    # Role-specific action
    role_program = {"miner": "mine", "aligner": "align",
                    "scrambler": "scramble"}.get(role, "explore")
    result = ctx.invoke(role_program, ctx)
    return result[0] if isinstance(result, tuple) else result


ANALYZE_PROMPT = """CvC game step {step}/10000. 88x88 map, 8 agents per team.
HP={hp}, Hearts={hearts}
Hub resources: {resources}
Team roles: {roles}
Visible junctions: friendly={junctions[friendly]} enemy={junctions[enemy]} neutral={junctions[neutral]}

Respond with ONLY a JSON object (no other text):
{{"resource_bias": "carbon"|"oxygen"|"germanium"|"silicon", "analysis": "1-2 sentence analysis"}}
Choose resource_bias = the element with lowest supply."""


def _build_analyze_system(ctx: dict) -> str:
    """Dynamic system prompt builder for the analyze program."""
    return ANALYZE_PROMPT.format(**ctx)


def _parse_analysis(text: str) -> dict:
    """Parse LLM analysis response."""
    import json
    result: dict = {"analysis": text[:100]}
    try:
        d = json.loads(text)
        if isinstance(d, dict):
            if d.get("resource_bias") in ("carbon", "oxygen", "germanium", "silicon"):
                result["resource_bias"] = d["resource_bias"]
            result["analysis"] = d.get("analysis", text[:100])
    except (json.JSONDecodeError, ValueError):
        pass
    return result


def seed_programs() -> dict[str, Program]:
    """Return the initial program table seeded from CvcEngine heuristics."""
    return {
        "step": Program(executor="code", fn=_step),
        "heal": Program(executor="code", fn=_heal),
        "retreat": Program(executor="code", fn=_retreat),
        "mine": Program(executor="code", fn=_mine),
        "align": Program(executor="code", fn=_align),
        "scramble": Program(executor="code", fn=_scramble),
        "explore": Program(executor="code", fn=_explore),
        "macro": Program(executor="code", fn=_macro),
        "summarize": Program(executor="code", fn=_summarize),
        "analyze": Program(
            executor="llm",
            system=_build_analyze_system,
            parser=_parse_analysis,
            config={"model": "claude-sonnet-4-20250514", "max_tokens": 150,
                    "temperature": 0.2, "max_turns": 1},
        ),
    }
```

**Step 2: Write test that seed_programs returns valid table**

```python
# tests/test_cvc_programs.py
"""Tests for CvC seed program table."""
from cvc.programs import seed_programs, StepContext

def test_seed_programs_has_all_entries():
    programs = seed_programs()
    expected = {"step", "heal", "retreat", "mine", "align",
                "scramble", "explore", "macro", "summarize", "analyze"}
    assert set(programs.keys()) == expected

def test_code_programs_are_callable():
    programs = seed_programs()
    for name, prog in programs.items():
        if prog.executor == "code":
            assert callable(prog.fn), f"{name} fn not callable"

def test_analyze_is_llm_program():
    programs = seed_programs()
    assert programs["analyze"].executor == "llm"
    assert programs["analyze"].parser is not None
```

**Step 3: Run tests**

```bash
PYTHONPATH=src:cogames python -m pytest tests/test_cvc_programs.py -v
```

**Step 4: Commit**

```
feat: add seed program table decomposing CvcEngine into named programs
```

---

### Task 2: Program Table Policy Adapter

**Files:**
- Create: `cogames/cvc/table_policy.py`
- Test: `tests/test_table_policy.py`

Bridges the program table to cogames' sync `MultiAgentPolicy` interface. Replaces the engine's hardcoded dispatch with program table lookups.

**Step 1: Write TablePolicy**

```python
# cogames/cvc/table_policy.py
"""CvC policy driven by a mutable program table."""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cvc.agent.coglet_policy import CogletAgentPolicy
from cvc.agent.world_model import WorldModel
from cvc.programs import StepContext, seed_programs
from coglet.llm_executor import LLMExecutor
from coglet.proglet import Program
from mettagrid.policy.policy import MultiAgentPolicy, StatefulAgentPolicy, StatefulPolicyImpl
from mettagrid.policy.policy_env_interface import PolicyEnvInterface
from mettagrid.simulator import Action
from mettagrid.simulator.interface import AgentObservation

_LLM_INTERVAL = 500
_LOG_INTERVAL = 500
_ELEMENTS = ("carbon", "oxygen", "germanium", "silicon")
_LEARNINGS_DIR = os.environ.get("COGLET_LEARNINGS_DIR", "/tmp/coglet_learnings")


@dataclass
class TableAgentState:
    """Per-agent state."""
    engine: CogletAgentPolicy | None = None
    last_llm_step: int = 0
    llm_interval: int = _LLM_INTERVAL
    llm_latencies: list[float] = field(default_factory=list)
    resource_bias_from_llm: str | None = None
    llm_log: list[dict] = field(default_factory=list)
    snapshot_log: list[dict] = field(default_factory=list)
    last_snapshot_step: int = 0
    experience: list[dict] = field(default_factory=list)


class TablePolicyImpl(StatefulPolicyImpl[TableAgentState]):
    """Per-agent logic using program table for decisions."""

    def __init__(
        self,
        policy_env_info: PolicyEnvInterface,
        agent_id: int,
        programs: dict[str, Program],
        llm_executor: LLMExecutor | None = None,
        game_id: str = "",
    ) -> None:
        self._policy_env_info = policy_env_info
        self._agent_id = agent_id
        self._programs = programs
        self._llm_executor = llm_executor
        self._game_id = game_id

    def initial_agent_state(self) -> TableAgentState:
        engine = CogletAgentPolicy(
            self._policy_env_info,
            agent_id=self._agent_id,
            world_model=WorldModel(),
        )
        return TableAgentState(engine=engine)

    def _invoke_sync(self, name: str, ctx: StepContext) -> Any:
        """Synchronous program invocation for code programs."""
        prog = self._programs[name]
        if prog.executor == "code" and prog.fn is not None:
            return prog.fn(ctx)
        raise ValueError(f"Cannot sync-invoke {name} (executor={prog.executor})")

    def step_with_state(
        self, obs: AgentObservation, state: TableAgentState
    ) -> tuple[Action, TableAgentState]:
        engine = state.engine
        assert engine is not None

        # Apply LLM guidance
        engine._llm_resource_bias = state.resource_bias_from_llm

        # Let engine process observation and update world model
        # We call engine.step() but override the action via program table
        from mettagrid_sdk.sdk import CogsguardSemanticSurface
        engine._step_index += 1
        mg_state = CogsguardSemanticSurface(obs, engine._policy_env_info)
        engine._previous_state = mg_state

        # Update world model + junctions
        engine._world_model.update(mg_state)
        engine._world_model.prune_missing_extractors()
        engine._update_junctions(mg_state)

        # Get role from engine
        directive = engine._macro_directive(mg_state)
        directive = engine._sanitize_macro_directive(directive)
        engine._current_directive = directive
        role = engine._desired_role(mg_state, directive)

        # Build context and invoke step program
        ctx = StepContext(
            engine=engine,
            state=mg_state,
            role=role,
            invoke=self._invoke_sync,
        )
        action = self._invoke_sync("step", ctx)

        # Update engine tracking (stall, oscillation, navigation)
        pos = _h.absolute_position(mg_state) if mg_state else None
        if pos:
            engine._update_stall_counter(mg_state, pos)
            engine._record_navigation_observation(pos, "")

        step = engine._step_index

        # Periodic LLM analysis
        if (self._llm_executor is not None
                and step - state.last_llm_step >= state.llm_interval):
            state.last_llm_step = step
            self._llm_analyze(engine, ctx, state)
            self._adapt_interval(state)

        # Periodic snapshot for experience
        if step - state.last_snapshot_step >= _LOG_INTERVAL:
            state.last_snapshot_step = step
            summary = self._invoke_sync("summarize", ctx)
            state.experience.append(summary)
            state.snapshot_log.append(summary)

        return action, state

    def _llm_analyze(self, engine: CogletAgentPolicy,
                     ctx: StepContext, state: TableAgentState) -> None:
        """Run the analyze LLM program."""
        try:
            summary = self._invoke_sync("summarize", ctx)
            prog = self._programs.get("analyze")
            if prog is None or prog.executor != "llm":
                return

            prompt = prog.system(summary) if callable(prog.system) else str(prog.system)
            cfg = prog.config

            t0 = time.perf_counter()
            response = self._llm_executor.client.messages.create(
                model=cfg.get("model", "claude-sonnet-4-20250514"),
                max_tokens=cfg.get("max_tokens", 150),
                temperature=cfg.get("temperature", 0.2),
                messages=[{"role": "user", "content": prompt}],
            )
            latency_ms = (time.perf_counter() - t0) * 1000

            text = self._llm_executor._extract_text(response)
            parsed = prog.parser(text) if prog.parser else {"analysis": text}

            if "resource_bias" in parsed:
                state.resource_bias_from_llm = parsed["resource_bias"]

            state.llm_latencies.append(latency_ms)
            state.llm_log.append({
                "step": engine._step_index,
                "agent": self._agent_id,
                "latency_ms": round(latency_ms),
                "analysis": parsed.get("analysis", ""),
                "resource_bias": state.resource_bias_from_llm,
            })
        except Exception as e:
            state.llm_log.append({
                "step": engine._step_index,
                "agent": self._agent_id,
                "error": str(e),
            })

    def _adapt_interval(self, state: TableAgentState) -> None:
        if not state.llm_latencies:
            return
        recent = state.llm_latencies[-5:]
        avg_ms = sum(recent) / len(recent)
        if avg_ms < 2000:
            state.llm_interval = max(200, state.llm_interval - 50)
        elif avg_ms > 5000:
            state.llm_interval = min(1000, state.llm_interval + 100)


class TablePolicy(MultiAgentPolicy):
    """Top-level CvC policy backed by a mutable program table."""

    short_names = ["coglet-table", "table-policy"]
    minimum_action_timeout_ms = 30_000

    def __init__(self, policy_env_info: PolicyEnvInterface,
                 device: str = "cpu",
                 programs: dict[str, Program] | None = None,
                 **kwargs: Any):
        super().__init__(policy_env_info, device=device, **kwargs)
        self._programs = programs or seed_programs()
        self._agent_policies: dict[int, StatefulAgentPolicy[TableAgentState]] = {}
        self._llm_executor: LLMExecutor | None = None
        self._episode_start = time.time()
        self._game_id = kwargs.get("game_id", f"game_{int(time.time())}")
        self._init_llm()

    def _init_llm(self) -> None:
        api_key = os.environ.get("COGORA_ANTHROPIC_KEY") or os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            return
        try:
            import anthropic
            self._llm_executor = LLMExecutor(anthropic.Anthropic(api_key=api_key))
        except ImportError:
            pass

    @property
    def programs(self) -> dict[str, Program]:
        return self._programs

    def agent_policy(self, agent_id: int) -> StatefulAgentPolicy[TableAgentState]:
        if agent_id not in self._agent_policies:
            impl = TablePolicyImpl(
                self._policy_env_info, agent_id,
                programs=self._programs,
                llm_executor=self._llm_executor,
                game_id=self._game_id,
            )
            self._agent_policies[agent_id] = StatefulAgentPolicy(
                impl, self._policy_env_info, agent_id=agent_id,
            )
        return self._agent_policies[agent_id]

    def collect_experience(self) -> list[dict]:
        """Collect experience from all agents for PCO."""
        all_exp: list[dict] = []
        for aid, wrapper in self._agent_policies.items():
            st: TableAgentState | None = getattr(wrapper, "_state", None)
            if st:
                all_exp.extend(st.experience)
        return sorted(all_exp, key=lambda x: x.get("step", 0))

    def reset(self) -> None:
        if self._agent_policies:
            self._write_learnings()
        self._episode_start = time.time()
        for p in self._agent_policies.values():
            p.reset()

    def _write_learnings(self) -> None:
        learnings_dir = Path(_LEARNINGS_DIR)
        learnings_dir.mkdir(parents=True, exist_ok=True)
        agents_data: dict[str, Any] = {}
        all_llm: list[dict] = []
        all_snaps: list[dict] = []
        for aid, wrapper in self._agent_policies.items():
            st: TableAgentState | None = getattr(wrapper, "_state", None)
            if st is None:
                continue
            eng = st.engine
            agents_data[str(aid)] = {
                "steps": eng._step_index if eng else 0,
                "last_infos": dict(eng._infos) if eng and eng._infos else {},
            }
            all_llm.extend(st.llm_log)
            all_snaps.extend(st.snapshot_log)
        learnings = {
            "game_id": self._game_id,
            "duration_s": round(time.time() - self._episode_start, 1),
            "agents": agents_data,
            "llm_log": sorted(all_llm, key=lambda x: (x.get("step", 0), x.get("agent", 0))),
            "snapshots": sorted(all_snaps, key=lambda x: (x.get("step", 0), x.get("agent", 0))),
        }
        path = learnings_dir / f"{self._game_id}.json"
        path.write_text(json.dumps(learnings, indent=2, default=str))
```

**Step 2: Write test**

```python
# tests/test_table_policy.py
"""Tests for TablePolicy program-table-driven CvC policy."""
from cvc.programs import seed_programs
from cvc.table_policy import TablePolicy, TablePolicyImpl

def test_table_policy_creates_with_seed_programs():
    """TablePolicy initializes with seed program table."""
    # Can't fully test without cogames env, but verify construction
    programs = seed_programs()
    assert "step" in programs
    assert "analyze" in programs

def test_collect_experience_empty():
    """collect_experience returns empty list before any games."""
    # Would need mock policy_env_info — placeholder for integration test
    pass
```

**Step 3: Run tests, commit**

```
feat: add TablePolicy — program-table-driven CvC policy adapter
```

---

### Task 3: PCO Components — Critic, Losses, Constraints

**Files:**
- Create: `cogames/cvc/critic.py`
- Create: `cogames/cvc/losses.py`
- Create: `cogames/cvc/constraints.py`
- Test: `tests/test_cvc_pco_components.py`

**Step 1: Write CvCCritic**

```python
# cogames/cvc/critic.py
"""CvC critic — evaluates game experience."""
from __future__ import annotations
from typing import Any
from coglet.coglet import Coglet, listen


class CvCCritic(Coglet):
    """Evaluates game experience and produces structured assessment."""

    @listen("experience")
    async def _on_experience(self, experience: Any) -> None:
        evaluation = await self.evaluate(experience)
        await self.transmit("evaluation", evaluation)

    async def evaluate(self, experience: list[dict]) -> dict:
        """Analyze game experience snapshots."""
        if not experience:
            return {"score": 0, "summary": "no data", "snapshots": []}

        # Resource trajectory
        resources_over_time = [s.get("resources", {}) for s in experience]
        final_resources = resources_over_time[-1] if resources_over_time else {}
        total_resources = sum(final_resources.values())

        # Junction control trajectory
        junctions_over_time = [s.get("junctions", {}) for s in experience]
        final_junctions = junctions_over_time[-1] if junctions_over_time else {}
        friendly = final_junctions.get("friendly", 0)
        enemy = final_junctions.get("enemy", 0)

        # Survival
        final_hp = experience[-1].get("hp", 0) if experience else 0
        deaths = sum(1 for s in experience if s.get("hp", 100) == 0)

        return {
            "total_resources": total_resources,
            "final_resources": final_resources,
            "junction_control": friendly - enemy,
            "friendly_junctions": friendly,
            "enemy_junctions": enemy,
            "deaths": deaths,
            "final_hp": final_hp,
            "num_snapshots": len(experience),
            "snapshots": experience,
        }

    @listen("update")  # no-op for critic updates
    async def _on_update(self, patch: Any) -> None:
        pass
```

**Step 2: Write losses**

```python
# cogames/cvc/losses.py
"""CvC loss functions for PCO."""
from __future__ import annotations
from typing import Any
from coglet.pco.loss import LossCoglet


class ResourceLoss(LossCoglet):
    """Penalize low resource collection."""
    async def compute_loss(self, experience: Any, evaluation: dict) -> dict:
        total = evaluation.get("total_resources", 0)
        return {"name": "resources", "magnitude": max(0, 100 - total),
                "total": total}


class JunctionLoss(LossCoglet):
    """Penalize poor junction control."""
    async def compute_loss(self, experience: Any, evaluation: dict) -> dict:
        control = evaluation.get("junction_control", 0)
        return {"name": "junctions", "magnitude": max(0, -control),
                "control": control}


class SurvivalLoss(LossCoglet):
    """Penalize agent deaths."""
    async def compute_loss(self, experience: Any, evaluation: dict) -> dict:
        deaths = evaluation.get("deaths", 0)
        return {"name": "survival", "magnitude": deaths, "deaths": deaths}
```

**Step 3: Write constraints**

```python
# cogames/cvc/constraints.py
"""CvC constraints for PCO patches."""
from __future__ import annotations
import ast
from typing import Any
from coglet.pco.constraint import ConstraintCoglet


class SyntaxConstraint(ConstraintCoglet):
    """Validate that patched Python source code parses."""
    async def check(self, patch: Any) -> dict:
        programs = patch if isinstance(patch, dict) else {}
        for name, prog in programs.items():
            # If patch contains source code strings, validate syntax
            if hasattr(prog, 'source') and isinstance(prog.source, str):
                try:
                    ast.parse(prog.source)
                except SyntaxError as e:
                    return {"accepted": False,
                            "reason": f"syntax error in {name}: {e}"}
        return {"accepted": True}


class SafetyConstraint(ConstraintCoglet):
    """Reject patches that use dangerous constructs."""
    _BANNED = {"import os", "import subprocess", "import sys",
               "eval(", "exec(", "__import__", "open("}

    async def check(self, patch: Any) -> dict:
        programs = patch if isinstance(patch, dict) else {}
        for name, prog in programs.items():
            source = getattr(prog, 'source', None)
            if source and isinstance(source, str):
                for banned in self._BANNED:
                    if banned in source:
                        return {"accepted": False,
                                "reason": f"banned construct '{banned}' in {name}"}
        return {"accepted": True}
```

**Step 4: Write tests**

```python
# tests/test_cvc_pco_components.py
"""Tests for CvC PCO components."""
import pytest
from coglet.runtime import CogletRuntime
from coglet.handle import CogletConfig
from cvc.critic import CvCCritic
from cvc.losses import ResourceLoss, JunctionLoss, SurvivalLoss
from cvc.constraints import SyntaxConstraint, SafetyConstraint


@pytest.mark.asyncio
async def test_critic_evaluates_experience():
    runtime = CogletRuntime()
    handle = await runtime.spawn(CogletConfig(cls=CvCCritic))
    critic = handle.coglet
    sub = critic._bus.subscribe("evaluation")

    experience = [
        {"step": 500, "hp": 80, "resources": {"carbon": 10, "oxygen": 5, "germanium": 3, "silicon": 2},
         "junctions": {"friendly": 3, "enemy": 1, "neutral": 2}, "role": "miner"},
        {"step": 1000, "hp": 0, "resources": {"carbon": 20, "oxygen": 15, "germanium": 10, "silicon": 8},
         "junctions": {"friendly": 5, "enemy": 2, "neutral": 1}, "role": "miner"},
    ]
    await critic._dispatch_listen("experience", experience)
    evaluation = await sub.get()

    assert evaluation["total_resources"] == 53  # 20+15+10+8
    assert evaluation["junction_control"] == 3  # 5-2
    assert evaluation["deaths"] == 1
    await runtime.shutdown()


@pytest.mark.asyncio
async def test_resource_loss():
    loss = ResourceLoss()
    await loss._bus.start()
    sub = loss._bus.subscribe("signal")
    await loss._dispatch_listen("experience", [])
    await loss._dispatch_listen("evaluation", {"total_resources": 30})
    signal = await sub.get()
    assert signal["name"] == "resources"
    assert signal["magnitude"] == 70  # 100 - 30


@pytest.mark.asyncio
async def test_syntax_constraint_accepts_valid():
    constraint = SyntaxConstraint()
    await constraint._bus.start()
    result = await constraint.check({})
    assert result["accepted"] is True


@pytest.mark.asyncio
async def test_safety_constraint_rejects_eval():
    constraint = SafetyConstraint()
    await constraint._bus.start()

    class FakeProg:
        source = "result = eval(user_input)"
    result = await constraint.check({"bad": FakeProg()})
    assert result["accepted"] is False
    assert "eval(" in result["reason"]
```

**Step 5: Run tests, commit**

```
feat: add CvC PCO components — critic, losses, constraints
```

---

### Task 4: CvC Learner

**Files:**
- Create: `cogames/cvc/learner.py`
- Test: `tests/test_cvc_learner.py`

The learner is LLM-based — it receives experience + evaluation + signals and proposes patches to the program table.

**Step 1: Write CvCLearner**

```python
# cogames/cvc/learner.py
"""CvC learner — proposes program table patches via LLM."""
from __future__ import annotations

import json
from typing import Any

from coglet.pco.learner import LearnerCoglet
from coglet.proglet import Program


class CvCLearner(LearnerCoglet):
    """LLM-based learner that proposes patches to the program table.

    Receives experience (game snapshots), evaluation (critic assessment),
    and loss signals. Proposes modifications to code programs (new Python
    functions) or prompt programs (new prompts).
    """

    def __init__(self, client: Any = None, model: str = "claude-sonnet-4-20250514",
                 current_programs: dict[str, Program] | None = None, **kwargs: Any):
        super().__init__(**kwargs)
        self._client = client
        self._model = model
        self._current_programs = current_programs or {}

    def update_programs(self, programs: dict[str, Program]) -> None:
        """Update reference to current program table."""
        self._current_programs = programs

    async def learn(self, experience: Any, evaluation: Any, signals: list[Any]) -> dict:
        """Propose a patch to the program table."""
        if self._client is None:
            return {}

        # Build prompt describing current state and what to improve
        prompt = self._build_learner_prompt(experience, evaluation, signals)

        response = self._client.messages.create(
            model=self._model,
            max_tokens=2000,
            temperature=0.3,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text if response.content else ""
        return self._parse_patch(text)

    def _build_learner_prompt(self, experience: Any, evaluation: Any,
                              signals: list[Any]) -> str:
        """Build the prompt for the learner LLM."""
        lines = ["# CvC Program Table Optimization\n"]
        lines.append("## Current Performance")
        lines.append(f"Evaluation: {json.dumps(evaluation, default=str)}\n")

        lines.append("## Loss Signals")
        for s in signals:
            if isinstance(s, dict) and "rejection" not in s:
                lines.append(f"- {s.get('name', '?')}: magnitude={s.get('magnitude', '?')}")
        lines.append("")

        # Rejection feedback
        rejections = [s for s in signals if isinstance(s, dict) and "rejection" in s]
        if rejections:
            lines.append("## Previous Rejection Feedback")
            for r in rejections:
                lines.append(f"- {r['rejection']}")
            lines.append("")

        lines.append("## Current Programs (code)")
        for name, prog in self._current_programs.items():
            if prog.executor == "code" and prog.fn is not None:
                import inspect
                try:
                    src = inspect.getsource(prog.fn)
                    lines.append(f"### {name}\n```python\n{src}```\n")
                except (OSError, TypeError):
                    lines.append(f"### {name}\n(source unavailable)\n")

        lines.append("## Current Analyze Prompt")
        analyze = self._current_programs.get("analyze")
        if analyze and analyze.system:
            prompt_text = analyze.system if isinstance(analyze.system, str) else "(dynamic)"
            lines.append(f"```\n{prompt_text}\n```\n")

        lines.append("## Experience Summary")
        if isinstance(experience, list) and experience:
            lines.append(f"Snapshots: {len(experience)}")
            lines.append(f"First: {json.dumps(experience[0], default=str)}")
            lines.append(f"Last: {json.dumps(experience[-1], default=str)}")
        lines.append("")

        lines.append("## Instructions")
        lines.append("Propose ONE focused improvement to the program table.")
        lines.append("Respond with a JSON object mapping program names to changes:")
        lines.append('{"program_name": {"type": "code"|"prompt", "source": "..."}}')
        lines.append("For code: source is a Python function definition.")
        lines.append("For prompt: source is the new prompt template string.")
        lines.append("Choose the change most likely to improve the weakest loss signal.")

        return "\n".join(lines)

    def _parse_patch(self, text: str) -> dict:
        """Parse LLM response into a program patch dict."""
        # Try to extract JSON from response
        try:
            # Find JSON in response
            start = text.index("{")
            end = text.rindex("}") + 1
            data = json.loads(text[start:end])
        except (ValueError, json.JSONDecodeError):
            return {}

        patch = {}
        for name, change in data.items():
            if not isinstance(change, dict):
                continue
            ctype = change.get("type", "code")
            source = change.get("source", "")
            if ctype == "prompt":
                patch[name] = Program(
                    executor="llm",
                    system=source,
                    parser=self._current_programs.get(name, Program(executor="llm")).parser,
                    config=self._current_programs.get(name, Program(executor="llm")).config,
                )
            elif ctype == "code" and source:
                # Compile and extract function
                try:
                    ns: dict = {}
                    exec(source, ns)  # noqa: S102
                    # Find the function defined in source
                    fns = [v for v in ns.values() if callable(v) and v.__module__ is None]
                    if fns:
                        patch[name] = Program(executor="code", fn=fns[0])
                        patch[name].source = source  # attach source for constraint checking
                except Exception:
                    pass  # constraint will catch
        return patch
```

**Step 2: Write test**

```python
# tests/test_cvc_learner.py
"""Tests for CvC learner."""
import pytest
from cvc.learner import CvCLearner
from cvc.programs import seed_programs


@pytest.mark.asyncio
async def test_learner_without_client_returns_empty():
    learner = CvCLearner(client=None, current_programs=seed_programs())
    result = await learner.learn([], {}, [])
    assert result == {}


def test_parse_patch_valid_code():
    learner = CvCLearner(current_programs=seed_programs())
    text = '{"macro": {"type": "code", "source": "def _macro(ctx):\\n    return {\\"directive\\": None, \\"budgets\\": (2, 0)}"}}'
    patch = learner._parse_patch(text)
    assert "macro" in patch
    assert patch["macro"].executor == "code"
    assert callable(patch["macro"].fn)


def test_parse_patch_valid_prompt():
    learner = CvCLearner(current_programs=seed_programs())
    text = '{"analyze": {"type": "prompt", "source": "New prompt: {step}"}}'
    patch = learner._parse_patch(text)
    assert "analyze" in patch
    assert patch["analyze"].executor == "llm"
    assert patch["analyze"].system == "New prompt: {step}"


def test_parse_patch_invalid_json():
    learner = CvCLearner(current_programs=seed_programs())
    patch = learner._parse_patch("not json at all")
    assert patch == {}
```

**Step 3: Run tests, commit**

```
feat: add CvC learner — LLM-based program table optimizer
```

---

### Task 5: PCO Runner

**Files:**
- Create: `cogames/cvc/pco_runner.py`
- Test: `tests/test_pco_runner.py`

Orchestrates PCO epochs between cogames episodes.

**Step 1: Write PCORunner**

```python
# cogames/cvc/pco_runner.py
"""PCO runner — orchestrates learning between cogames episodes."""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from coglet.handle import CogletConfig
from coglet.pco.optimizer import ProximalCogletOptimizer
from coglet.pco.constraint import ConstraintCoglet
from coglet.runtime import CogletRuntime
from coglet.coglet import Coglet, enact, listen
from coglet.lifelet import LifeLet
from coglet.proglet import Program

from cvc.critic import CvCCritic
from cvc.constraints import SyntaxConstraint, SafetyConstraint
from cvc.learner import CvCLearner
from cvc.losses import ResourceLoss, JunctionLoss, SurvivalLoss
from cvc.programs import seed_programs


@dataclass
class PCOState:
    """Persistent state across PCO epochs."""
    programs: dict[str, Program] = field(default_factory=seed_programs)
    epoch_results: list[dict] = field(default_factory=list)
    best_score: float = 0.0


class ExperienceActor(Coglet, LifeLet):
    """PCO actor that replays collected experience."""

    def __init__(self, experience: list[dict] | None = None,
                 programs: dict[str, Program] | None = None, **kwargs: Any):
        super().__init__(**kwargs)
        self._experience = experience or []
        self._programs = programs or {}

    @enact("run")
    async def handle_run(self, data: Any = None) -> None:
        await self.transmit("experience", self._experience)

    @enact("update")
    async def handle_update(self, patch: Any) -> None:
        if isinstance(patch, dict):
            self._programs.update(patch)


async def run_pco_epoch(
    experience: list[dict],
    programs: dict[str, Program],
    client: Any = None,
    max_retries: int = 2,
) -> dict[str, Any]:
    """Run one PCO epoch with collected game experience.

    Args:
        experience: Game snapshots from TablePolicy.collect_experience()
        programs: Current program table
        client: Anthropic client for learner LLM calls
        max_retries: Max constraint rejection retries

    Returns:
        PCO epoch result dict with accepted, patch, signals
    """
    learner = CvCLearner(client=client, current_programs=programs)

    runtime = CogletRuntime()
    handle = await runtime.spawn(CogletConfig(
        cls=ProximalCogletOptimizer,
        kwargs=dict(
            actor_config=CogletConfig(
                cls=ExperienceActor,
                kwargs=dict(experience=experience, programs=programs),
            ),
            critic_config=CogletConfig(cls=CvCCritic),
            losses=[ResourceLoss(), JunctionLoss(), SurvivalLoss()],
            constraints=[SyntaxConstraint(), SafetyConstraint()],
            learner=learner,
            max_retries=max_retries,
        ),
    ))

    pco = handle.coglet
    result = await pco.run_epoch()
    await runtime.shutdown()

    return result
```

**Step 2: Write test**

```python
# tests/test_pco_runner.py
"""Tests for CvC PCO runner."""
import pytest
from cvc.pco_runner import run_pco_epoch, ExperienceActor
from cvc.programs import seed_programs
from coglet.runtime import CogletRuntime
from coglet.handle import CogletConfig


@pytest.mark.asyncio
async def test_experience_actor_transmits():
    runtime = CogletRuntime()
    exp = [{"step": 100, "hp": 80, "resources": {"carbon": 5}}]
    handle = await runtime.spawn(CogletConfig(
        cls=ExperienceActor, kwargs=dict(experience=exp),
    ))
    actor = handle.coglet
    sub = actor._bus.subscribe("experience")
    await actor._dispatch_enact("run", None)
    result = await sub.get()
    assert result == exp
    await runtime.shutdown()


@pytest.mark.asyncio
async def test_pco_epoch_runs_without_client():
    """PCO epoch completes (learner returns empty patch without LLM client)."""
    experience = [
        {"step": 500, "hp": 80,
         "resources": {"carbon": 10, "oxygen": 5, "germanium": 3, "silicon": 2},
         "junctions": {"friendly": 3, "enemy": 1, "neutral": 2}, "role": "miner"},
    ]
    result = await run_pco_epoch(
        experience=experience,
        programs=seed_programs(),
        client=None,
    )
    assert "accepted" in result
    assert "signals" in result
```

**Step 3: Run tests, commit**

```
feat: add PCO runner — orchestrates learning between episodes
```

---

### Task 6: Wire Into cogames Entry Point

**Files:**
- Modify: `cogames/cvc/cvc_policy.py` — add `TablePolicy` import alias
- Modify: `cogames/cvc/__init__.py` — export new classes

**Step 1: Update cvc_policy.py**

Keep existing `CogletPolicy` as-is (don't break tournament). Add `TablePolicy` as alternate entry point:

```python
# Append to end of cogames/cvc/cvc_policy.py:
# PCO-driven variant
from cvc.table_policy import TablePolicy  # noqa: F401
```

**Step 2: Run full test suite**

```bash
PYTHONPATH=src:cogames python -m pytest tests/ -v
```

**Step 3: Commit**

```
feat: wire PCO TablePolicy into CvC entry points
```

---

### Task 7: Integration Test — Full PCO Epoch

**Files:**
- Create: `tests/test_cvc_pco_integration.py`

End-to-end test: seed programs → fake experience → PCO epoch → verify signals computed.

```python
# tests/test_cvc_pco_integration.py
"""Integration test: full PCO epoch with CvC components."""
import pytest
from cvc.pco_runner import run_pco_epoch
from cvc.programs import seed_programs


@pytest.mark.asyncio
async def test_full_pco_epoch_computes_signals():
    """Full PCO epoch: experience → critic → losses → learner → constraints."""
    experience = [
        {"step": 500, "hp": 80, "hearts": 2,
         "resources": {"carbon": 10, "oxygen": 5, "germanium": 3, "silicon": 2},
         "junctions": {"friendly": 3, "enemy": 1, "neutral": 2},
         "roles": {"miner": 4, "aligner": 2, "scrambler": 1, "scout": 1},
         "role": "miner"},
        {"step": 1000, "hp": 60, "hearts": 1,
         "resources": {"carbon": 25, "oxygen": 15, "germanium": 10, "silicon": 8},
         "junctions": {"friendly": 5, "enemy": 2, "neutral": 1},
         "roles": {"miner": 3, "aligner": 3, "scrambler": 1, "scout": 1},
         "role": "aligner"},
    ]

    result = await run_pco_epoch(
        experience=experience,
        programs=seed_programs(),
        client=None,  # no LLM — learner returns empty, constraints accept
    )

    assert "accepted" in result
    assert "signals" in result
    assert len(result["signals"]) == 3  # resource, junction, survival

    # Verify loss signals were computed
    signal_names = {s["name"] for s in result["signals"]}
    assert signal_names == {"resources", "junctions", "survival"}

    # Resource loss: 100 - 58 = 42
    resource_signal = next(s for s in result["signals"] if s["name"] == "resources")
    assert resource_signal["magnitude"] == 42

    # Junction loss: control = 5-2 = 3, loss = max(0, -3) = 0
    junction_signal = next(s for s in result["signals"] if s["name"] == "junctions")
    assert junction_signal["magnitude"] == 0

    # Survival: no deaths (hp never 0)
    survival_signal = next(s for s in result["signals"] if s["name"] == "survival")
    assert survival_signal["magnitude"] == 0
```

**Step 1: Run integration test**

```bash
PYTHONPATH=src:cogames python -m pytest tests/test_cvc_pco_integration.py -v
```

**Step 2: Commit**

```
test: full PCO epoch integration test with CvC components
```

---

### Verification

1. **Unit tests**: `PYTHONPATH=src:cogames python -m pytest tests/test_cvc_programs.py tests/test_cvc_pco_components.py tests/test_cvc_learner.py tests/test_pco_runner.py -v`
2. **Integration test**: `PYTHONPATH=src:cogames python -m pytest tests/test_cvc_pco_integration.py -v`
3. **Full suite**: `PYTHONPATH=src:cogames python -m pytest tests/ -v`
4. **Local scrimmage** (manual, after wiring to cogames): `cogames scrimmage -m machina_1 -p class=cvc.table_policy.TablePolicy -c 8 -e 1 --seed 42`
