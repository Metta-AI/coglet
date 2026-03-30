# Full ProgLet Policy — No Engine

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the CvcEngine-backed TablePolicy with a pure program table where everything — queries, movement, decisions — is a named program. All programs are evolvable by PCO. No engine.

**Architecture:** `GameState` holds raw infrastructure state (world model, pathfinding data, stall counters). All logic lives in a flat program table: query programs (`hp`, `nearest_hub`), action programs (`move_to`, `hold`), and decision programs (`step`, `mine`, `retreat`). Programs compose via `invoke`. PCO can evolve any program.

**Tech Stack:** coglet (ProgLet, Program, PCO), cogames (MultiAgentPolicy), mettagrid_sdk

---

### Task 1: GameState — Raw State Container

**Files:**
- Create: `cogames/cvc/game_state.py`
- Test: `tests/test_game_state.py`

GameState holds raw state only — no logic methods. Programs read from it.

```python
# cogames/cvc/game_state.py
"""GameState: raw infrastructure state for the program table.

Contains world model, observation state, navigation counters.
All logic lives in programs, not methods on this class.
"""
from __future__ import annotations

from collections import deque
from typing import Any

from mettagrid_sdk.games.cogsguard import CogsguardSemanticSurface
from mettagrid_sdk.sdk import MettagridState
from mettagrid.policy.policy_env_interface import PolicyEnvInterface
from mettagrid.simulator import Action
from mettagrid.simulator.interface import AgentObservation

from cvc.agent.world_model import WorldModel
from cvc.agent import helpers as _h

_COGSGUARD_SURFACE = CogsguardSemanticSurface()
_ELEMENTS = ("carbon", "oxygen", "germanium", "silicon")


class GameState:
    """Raw state container. Programs operate on this via invoke()."""

    def __init__(self, policy_env_info: PolicyEnvInterface, agent_id: int) -> None:
        self.policy_env_info = policy_env_info
        self.agent_id = agent_id
        self.world_model = WorldModel()

        # Action validation
        self.action_names = set(policy_env_info.action_names)
        self.vibe_actions = set(policy_env_info.vibe_action_names)
        self.fallback = "noop" if "noop" in self.action_names else policy_env_info.action_names[0]

        # Observation state
        self.mg_state: MettagridState | None = None
        self.previous_state: MettagridState | None = None
        self.step_index = 0

        # Navigation state
        self.last_global_pos: tuple[int, int] | None = None
        self.temp_blocks: dict[tuple[int, int], int] = {}
        self.stalled_steps = 0
        self.oscillation_steps = 0
        self.last_inventory_signature: tuple[tuple[str, int], ...] | None = None
        self.recent_navigation: deque = deque(maxlen=6)
        self.explore_index = 0

        # Junction memory
        self.junctions: dict[tuple[int, int], tuple[str | None, int]] = {}

        # Per-agent defaults
        self.resource_bias = _ELEMENTS[agent_id % len(_ELEMENTS)]

        # Targeting state
        self.current_target_position: tuple[int, int] | None = None
        self.current_target_kind: str | None = None
        self.claimed_target: tuple[int, int] | None = None
        self.sticky_target_position: tuple[int, int] | None = None
        self.sticky_target_kind: str | None = None
        self.claims: dict[tuple[int, int], tuple[int, int]] = {}

        # Role
        self.role: str = "miner"

    def process_obs(self, obs: AgentObservation) -> None:
        """Process raw observation into MettagridState and update world model."""
        self.step_index += 1
        self.mg_state = _COGSGUARD_SURFACE.build_state_with_events(
            obs,
            policy_env_info=self.policy_env_info,
            step=self.step_index,
            previous_state=self.previous_state,
        )
        self.previous_state = self.mg_state
        self.world_model.update(self.mg_state)
        pos = _h.absolute_position(self.mg_state)
        self.world_model.prune_missing_extractors(
            current_position=pos,
            visible_entities=self.mg_state.visible_entities,
            obs_width=self.policy_env_info.obs_width,
            obs_height=self.policy_env_info.obs_height,
        )
        # Update stall counter
        sig = _h.inventory_signature(self.mg_state)
        if pos == self.last_global_pos and sig == self.last_inventory_signature:
            self.stalled_steps += 1
        else:
            self.stalled_steps = 0
        self.last_global_pos = pos
        self.last_inventory_signature = sig
        # Expire temp blocks
        expired = [k for k, v in self.temp_blocks.items() if self.step_index - v > 10]
        for k in expired:
            del self.temp_blocks[k]
        # Reset per-tick state
        self.current_target_position = None
        self.current_target_kind = None

    def reset(self) -> None:
        self.world_model.reset()
        self.mg_state = None
        self.previous_state = None
        self.step_index = 0
        self.last_global_pos = None
        self.temp_blocks.clear()
        self.stalled_steps = 0
        self.oscillation_steps = 0
        self.junctions.clear()
        self.recent_navigation.clear()
        self.current_target_position = None
        self.claimed_target = None
        self.sticky_target_position = None
        self.sticky_target_kind = None
        self.claims.clear()
        self.role = "miner"
```

**Test:** Basic init checks (resource bias round-robin, reset).

**Commit:** `feat: add GameState raw state container`

---

### Task 2: All Programs in One Table

**Files:**
- Rewrite: `cogames/cvc/programs.py` — flat table with ALL programs (queries, actions, decisions)
- Delete: `cogames/cvc/infra_programs.py` (if exists)
- Test: `tests/test_programs.py`

One `all_programs()` function returns every program. All evolvable.

```python
# cogames/cvc/programs.py
"""Program table: ALL programs — queries, actions, decisions.

Every program is evolvable by PCO. Programs operate on GameState
and compose via invoke(name, gs, *args).
"""
from __future__ import annotations

import json
from typing import Any

from coglet.proglet import Program
from cvc.game_state import GameState
from cvc.agent import helpers as _h
from cvc.agent.helpers.types import KnownEntity

_ELEMENTS = ("carbon", "oxygen", "germanium", "silicon")


# ── Query programs ──────────────────────────────────────────

def _hp(gs: GameState) -> int:
    return int(gs.mg_state.self_state.inventory.get("hp", 0)) if gs.mg_state else 0

def _step_num(gs: GameState) -> int:
    return gs.step_index

def _position(gs: GameState) -> tuple[int, int]:
    return _h.absolute_position(gs.mg_state) if gs.mg_state else (0, 0)

def _inventory(gs: GameState) -> dict:
    return dict(gs.mg_state.self_state.inventory) if gs.mg_state else {}

def _resource_bias(gs: GameState) -> str:
    return gs.resource_bias

def _team_resources(gs: GameState) -> dict[str, int]:
    if gs.mg_state is None or gs.mg_state.team_summary is None:
        return {r: 0 for r in _ELEMENTS}
    return {r: int(gs.mg_state.team_summary.shared_inventory.get(r, 0)) for r in _ELEMENTS}

def _resource_priority(gs: GameState) -> list[str]:
    if gs.mg_state is None:
        return list(_ELEMENTS)
    return _h.resource_priority(gs.mg_state, resource_bias=gs.resource_bias)

def _nearest_hub(gs: GameState) -> KnownEntity | None:
    if gs.mg_state is None:
        return None
    team = _h.team_id(gs.mg_state)
    return gs.world_model.nearest(
        position=_position(gs),
        entity_type="hub",
        predicate=lambda e: _h.attr_str(e, "team") == team,
    )

def _nearest_extractor(gs: GameState, resource: str) -> KnownEntity | None:
    return gs.world_model.nearest(
        position=_position(gs),
        entity_type=f"{resource}_extractor",
        predicate=lambda e: _h.is_usable_recent_extractor(e, step=gs.step_index),
    )

def _known_junctions(gs: GameState, predicate=None) -> list[KnownEntity]:
    entities = list(gs.world_model.entities(entity_type="junction"))
    if predicate:
        entities = [e for e in entities if predicate(e)]
    return entities

def _safe_distance(gs: GameState) -> int:
    hub = _nearest_hub(gs)
    if hub is None:
        return 0
    return _h.manhattan(_position(gs), hub.position)

def _has_role_gear(gs: GameState, role: str) -> bool:
    return _h.has_role_gear(gs.mg_state, role) if gs.mg_state else False

def _team_can_afford_gear(gs: GameState, role: str) -> bool:
    return _h.team_can_afford_gear(gs.mg_state, role) if gs.mg_state else False

def _needs_emergency_mining(gs: GameState) -> bool:
    return _h.needs_emergency_mining(gs.mg_state) if gs.mg_state else False

def _is_stalled(gs: GameState) -> bool:
    return gs.stalled_steps >= 12

def _is_oscillating(gs: GameState) -> bool:
    return gs.oscillation_steps >= 4


# ── Action programs ─────────────────────────────────────────

def _action(gs: GameState, name: str, vibe: str | None = None) -> Any:
    from mettagrid.simulator import Action
    if name not in gs.action_names:
        name = gs.fallback
    return Action(name=name, vibe=vibe)

def _move_to(gs: GameState, target: Any) -> Any:
    pos = target.position if hasattr(target, "position") else target
    current = _position(gs)
    occupied = gs.world_model.occupied_cells() | set(gs.temp_blocks.keys())
    step = _h.greedy_step(current, pos, occupied)
    if step is None:
        return _action(gs, gs.fallback)
    direction = _h.direction_from_step(current, step)
    return _action(gs, f"move_{direction}")

def _hold(gs: GameState) -> Any:
    return _action(gs, "noop")

def _explore(gs: GameState, role: str = "miner") -> Any:
    hub = _nearest_hub(gs)
    if hub is None:
        return _hold(gs)
    offsets = _h.explore_offsets(role)
    if not offsets:
        return _hold(gs)
    idx = (gs.agent_id + gs.explore_index) % len(offsets)
    target = (hub.position[0] + offsets[idx][0], hub.position[1] + offsets[idx][1])
    return _move_to(gs, target)

def _unstick(gs: GameState, role: str = "miner") -> Any:
    directions = _h.unstick_directions(gs.agent_id, gs.step_index)
    for d in directions:
        name = f"move_{d}"
        if name in gs.action_names:
            return _action(gs, name)
    return _hold(gs)


# ── Decision programs ───────────────────────────────────────

def _desired_role(gs: GameState) -> str:
    """Allocate role based on agent_id and game phase."""
    step = gs.step_index
    aligner_budget = 2 if step < 300 else 4
    scrambler_budget = 0 if step < 300 else 1
    aid = gs.agent_id
    if aid >= 8 - scrambler_budget:
        return "scrambler"
    if aid >= 8 - scrambler_budget - aligner_budget:
        return "aligner"
    return "miner"

def _should_retreat(gs: GameState) -> bool:
    if gs.mg_state is None:
        return False
    threshold = _h.retreat_threshold(gs.mg_state, gs.role)
    return _hp(gs) < threshold and _safe_distance(gs) > 2

def _retreat(gs: GameState) -> Any:
    hub = _nearest_hub(gs)
    if hub:
        return _move_to(gs, hub)
    return _hold(gs)

def _mine(gs: GameState) -> Any:
    for resource in _resource_priority(gs):
        ext = _nearest_extractor(gs, resource)
        if ext:
            return _move_to(gs, ext)
    return _explore(gs, "miner")

def _align(gs: GameState) -> Any:
    team = _h.team_id(gs.mg_state) if gs.mg_state else ""
    junctions = _known_junctions(gs,
        predicate=lambda e: _h.attr_str(e, "owner") in {None, "neutral"})
    if junctions:
        pos = _position(gs)
        nearest = min(junctions, key=lambda j: _h.manhattan(pos, j.position))
        return _move_to(gs, nearest)
    return _explore(gs, "aligner")

def _scramble(gs: GameState) -> Any:
    team = _h.team_id(gs.mg_state) if gs.mg_state else ""
    junctions = _known_junctions(gs,
        predicate=lambda e: _h.attr_str(e, "owner") not in {None, "neutral", team})
    if junctions:
        pos = _position(gs)
        nearest = min(junctions, key=lambda j: _h.manhattan(pos, j.position))
        return _move_to(gs, nearest)
    return _explore(gs, "scrambler")

def _step_dispatch(gs: GameState) -> Any:
    """Main dispatch — priority-based decision tree."""
    hp = _hp(gs)
    step = _step_num(gs)
    dist = _safe_distance(gs)

    # Heal at hub
    if 0 < hp < 100 and dist <= 3 and step <= 20:
        return _hold(gs)

    # Early retreat
    if step < 150 and dist > 8 and (hp < 40 or (hp < 50 and dist > 15)):
        return _retreat(gs)

    # Wipeout recovery
    if hp == 0:
        if dist > 5:
            return _retreat(gs)
        return _mine(gs)

    # Retreat
    if _should_retreat(gs):
        return _retreat(gs)

    # Unstick
    if _is_oscillating(gs) or _is_stalled(gs):
        return _unstick(gs, gs.role)

    # Emergency mining
    if gs.role != "miner" and _needs_emergency_mining(gs):
        return _mine(gs)

    # Gear acquisition
    if not _has_role_gear(gs, gs.role):
        if not _team_can_afford_gear(gs, gs.role):
            return _mine(gs)
        hub = _nearest_hub(gs)
        if hub:
            return _move_to(gs, hub)
        return _explore(gs, gs.role)

    # Role action
    if gs.role == "miner":
        return _mine(gs)
    if gs.role == "aligner":
        return _align(gs)
    if gs.role == "scrambler":
        return _scramble(gs)
    return _explore(gs, gs.role)


def _summarize(gs: GameState) -> dict[str, Any]:
    """Build experience snapshot for the learner."""
    resources = _team_resources(gs)
    team = gs.mg_state.team_summary if gs.mg_state else None
    team_id = team.team_id if team else ""
    junctions = {"friendly": 0, "enemy": 0, "neutral": 0}
    if gs.mg_state:
        for e in gs.mg_state.visible_entities:
            if e.entity_type == "junction":
                owner = e.attributes.get("owner")
                if owner == team_id:
                    junctions["friendly"] += 1
                elif owner in {None, "neutral"}:
                    junctions["neutral"] += 1
                else:
                    junctions["enemy"] += 1
    return {
        "step": gs.step_index,
        "agent_id": gs.agent_id,
        "hp": _hp(gs),
        "resources": resources,
        "junctions": junctions,
        "role": gs.role,
    }


# ── LLM programs ───────────────────────────────────────────

def _build_analysis_prompt(context: dict) -> str:
    lines = [
        f"CvC game step {context['step']}/10000.",
        f"Agent {context['agent_id']}: HP={context['hp']}",
        f"Resources: {context['resources']}",
        f"Junctions: {context['junctions']}",
        '\nRespond JSON: {"resource_bias": "carbon"|"oxygen"|"germanium"|"silicon", "analysis": "..."}',
    ]
    return "\n".join(lines)

def _parse_analysis(text: str) -> dict:
    result: dict[str, Any] = {"analysis": text[:100]}
    try:
        d = json.loads(text)
        if isinstance(d, dict):
            if d.get("resource_bias") in _ELEMENTS:
                result["resource_bias"] = d["resource_bias"]
            result["analysis"] = d.get("analysis", text[:100])
    except (json.JSONDecodeError, ValueError):
        pass
    return result


# ── Full program table ──────────────────────────────────────

def all_programs() -> dict[str, Program]:
    """Return the complete program table. All programs are evolvable."""
    return {
        # Queries
        "hp": Program(executor="code", fn=_hp),
        "step_num": Program(executor="code", fn=_step_num),
        "position": Program(executor="code", fn=_position),
        "inventory": Program(executor="code", fn=_inventory),
        "resource_bias": Program(executor="code", fn=_resource_bias),
        "team_resources": Program(executor="code", fn=_team_resources),
        "resource_priority": Program(executor="code", fn=_resource_priority),
        "nearest_hub": Program(executor="code", fn=_nearest_hub),
        "nearest_extractor": Program(executor="code", fn=_nearest_extractor),
        "known_junctions": Program(executor="code", fn=_known_junctions),
        "safe_distance": Program(executor="code", fn=_safe_distance),
        "has_role_gear": Program(executor="code", fn=_has_role_gear),
        "team_can_afford_gear": Program(executor="code", fn=_team_can_afford_gear),
        "needs_emergency_mining": Program(executor="code", fn=_needs_emergency_mining),
        "is_stalled": Program(executor="code", fn=_is_stalled),
        "is_oscillating": Program(executor="code", fn=_is_oscillating),
        # Actions
        "action": Program(executor="code", fn=_action),
        "move_to": Program(executor="code", fn=_move_to),
        "hold": Program(executor="code", fn=_hold),
        "explore": Program(executor="code", fn=_explore),
        "unstick": Program(executor="code", fn=_unstick),
        # Decisions
        "desired_role": Program(executor="code", fn=_desired_role),
        "should_retreat": Program(executor="code", fn=_should_retreat),
        "retreat": Program(executor="code", fn=_retreat),
        "mine": Program(executor="code", fn=_mine),
        "align": Program(executor="code", fn=_align),
        "scramble": Program(executor="code", fn=_scramble),
        "step": Program(executor="code", fn=_step_dispatch),
        "summarize": Program(executor="code", fn=_summarize),
        # LLM
        "analyze": Program(
            executor="llm", system=_build_analysis_prompt,
            parser=_parse_analysis,
            config={"model": "claude-sonnet-4-20250514", "max_tokens": 150,
                    "temperature": 0.2, "max_turns": 1},
        ),
    }
```

**Test:** Verify all programs present, code programs callable, analyze is LLM.

**Commit:** `refactor: flat program table — all programs evolvable, no engine`

---

### Task 3: Rewrite TablePolicy

**Files:**
- Rewrite: `cogames/cvc/table_policy.py`
- Update: `tests/test_table_policy.py`

`TablePolicyImpl` creates `GameState` per agent. `step_with_state` calls `process_obs` then invokes `"step"` program.

Key flow:
```python
def step_with_state(self, obs, state):
    gs = state.game_state
    gs.process_obs(obs)
    gs.role = self._programs["desired_role"].fn(gs)
    action = self._programs["step"].fn(gs)
    return action, state
```

**Commit:** `refactor: TablePolicy uses GameState + flat program table`

---

### Task 4: Update PCO Components

**Files:**
- Modify: `cogames/cvc/learner.py` — remove infra/decision split guard
- Modify: `cogames/cvc/pco_runner.py` — use `all_programs()`
- Update tests

**Commit:** `refactor: PCO components use flat program table`

---

### Task 5: Update Tests + Integration

**Files:**
- Update: all test files to use new imports
- Run full suite + scrimmage

**Commit:** `test: verify full ProgLet policy, score >= 1.72`

---

## Verification

1. `PYTHONPATH=src:cogames python -m pytest tests/ -v` — all pass
2. `cogames scrimmage -m machina_1 -p class=cvc.table_policy.TablePolicy -c 8 -e 1 --seed 42` — score >= 1.72
3. `run_pco_epoch()` with new programs — completes successfully
