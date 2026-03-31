# IMPROVE.md — CvC Tournament Agent

Coaching guide for the Cogs vs Clips tournament agent.

## Objective

Maximize **per-cog score** in the CvC tournament. Score = total junctions held per step / max steps. Higher = better. Current tournament best: **6.13** (beta:v8). Tournament leader: **~13**.

## Setup

```bash
uv venv --python 3.12 .venv
source .venv/bin/activate
uv pip install -e . && uv pip install cogames
```

Verify: `source .venv/bin/activate && cogames --version`

## Eval

```bash
source .venv/bin/activate
cd cogs/cogames
PYTHONPATH=. cogames play -m machina_1 \
  -p class=cvc.cvc_policy.CvCPolicy \
  -c 8 -r none --seed 42
```

Look for the "per cog" score in the output table.

**Test across 5+ seeds** (42–46) and average. Single-seed results are noise.

Without LLM (matches tournament conditions):
```bash
ANTHROPIC_API_KEY= cogames play ...
```

## Submit

```bash
source .venv/bin/activate
cd cogs/cogames
cogames upload \
  -p class=cvc.cvc_policy.CvCPolicy \
  -n <policy_name> \
  -f cvc -f mettagrid_sdk -f setup_policy.py \
  --setup-script setup_policy.py \
  --season <season>
```

Policy name: `beta`. Season: `beta-teams-tiny-fixed`.

Check results: `cogames leaderboard --season <season>`, `cogames matches`, `cogames match-artifacts <match-id>`.

## Game Rules

- **Map**: 88×88 grid with walls, ~65 junctions, ~200 extractors
- **Duration**: 10,000 steps, 8 agents per team
- **Scoring**: `score = junctions_held_per_step / max_steps` per cog — holding junctions longer matters more than late captures
- **Junctions**: capturable nodes (neutral → friendly/enemy). Form networks via alignment distance
- **Resources**: carbon, oxygen, germanium, silicon — mined from extractors, deposited at hub, used to craft gear and hearts
- **Hearts**: consumable items for aligning/scrambling. Cost 7 of each element. Obtained at hub
- **Roles**: miner (harvest resources), aligner (capture neutral junctions, costs 1 heart), scrambler (neutralize enemy junctions, costs 1 heart)

### Key Constants

| Constant | Value | Meaning |
|----------|-------|---------|
| `HUB_ALIGN_DISTANCE` | 25 | Hub can align junctions within this range |
| `JUNCTION_ALIGN_DISTANCE` | 3 | Friendly junctions extend alignment network by this |
| `JUNCTION_AOE_RANGE` | 4 | Junctions affect nearby junctions within this |
| `RETREAT_MARGIN` | 15 | Base HP safety margin (alpha.0 uses 20) |
| `DEPOSIT_THRESHOLD` | 12 | Miner deposits cargo at this amount |
| `TARGET_CLAIM_STEPS` | 30 | Junction claim expiry |
| `EXTRACTOR_MEMORY` | 600 | Steps to remember extractor locations |
| Hub initial resources | 24 each | num_agents × 3 of each element |

## Architecture

```
CvCPolicy (MultiAgentPolicy)
  └── per-agent CvCPolicyImpl
       └── CvcEngine (heuristic decision tree)
       └── Program table (programs.py — evolvable by PCO)
       └── LLM brain (periodic analysis, optional)
```

**Agents are fully independent. NO shared state between agents.** Each may run in a separate process against different opponents. Never use shared dicts, sets, or lists between agent instances.

### Decision Flow (per tick, per agent)

1. `process_obs()` → build MettagridState, update world model + junction memory
2. `desired_role()` → pressure-based allocation (miner/aligner/scrambler)
3. `_choose_action()` — priority decision tree:
   hub_camp_heal → early_survival → wipeout_recovery → retreat → unstick → emergency_mine → acquire_gear → **role_action** → explore
4. Role actions: miners extract & deposit, aligners capture neutral junctions, scramblers disrupt enemy junctions

### Key Files

**Policy & programs** (`cogs/cogames/cvc/`):
- `cvc_policy.py` — CvCPolicy wrapper, LLM integration, experience collection
- `programs.py` — program table (evolvable by PCO learner)
- `game_state.py` — GameState adapter wrapping CvcEngine

**Engine** (`cogs/cogames/cvc/agent/`):
- `main.py` — CvcEngine: main decision tree
- `roles.py` — role actions (miner, aligner, scrambler)
- `navigation.py` — A* pathfinding, explore patterns, unstick
- `targeting.py` — target selection, claims, sticky targets
- `pressure.py` — role budgets, retreat thresholds
- `junctions.py` — junction memory, depot lookup
- `helpers/targeting.py` — scoring functions (aligner_target_score, scramble_target_score)
- `helpers/types.py` — constants, KnownEntity
- `helpers/resources.py` — resource/inventory queries

**PCO** (`cogs/cogames/cvc/`):
- `pco_runner.py` — `run_pco_epoch()` orchestrator
- `learner.py` — CvCLearner (LLM proposes program patches)
- `critic.py` — CvCCritic (evaluates experience)
- `losses.py` — ResourceLoss, JunctionLoss, SurvivalLoss
- `constraints.py` — SyntaxConstraint, SafetyConstraint

**Reference**: `cogs/cogames/cvc/AGENTS.md` — detailed game rules, full API reference

### PCO (Program Conditioned Optimization)

Run one PCO epoch to let the LLM propose patches to programs.py:

```python
import asyncio, json, glob, anthropic
from cvc.pco_runner import run_pco_epoch
from cvc.programs import all_programs

f = glob.glob('/tmp/coglet_learnings/*.json')[0]
experience = json.load(open(f))['snapshots']

result = asyncio.run(run_pco_epoch(
    experience=experience,
    programs=all_programs(),
    client=anthropic.Anthropic(),
    max_retries=2,
))
```

Valid GameState API for patches: `gs.hp`, `gs.position`, `gs.step_index`, `gs.role`, `gs.nearest_hub()`, `gs.known_junctions(pred)`, `gs.should_retreat()`, `gs.choose_action(role)`, `gs.miner_action()`, `gs.aligner_action()`, `gs.scrambler_action()`, `gs.move_to_known(entity)`, `gs.explore(role)`, `gs.has_role_gear(role)`, `gs.needs_emergency_mining()`, `gs.team_id()`

## Reference: alpha.0 (scores ~13, tournament leader)

The alpha.0 agent lives at `metta-ai/cogora` (`src/cvc/cogent/player_cog/policy/`). Key differences from our agent:

- **`RETREAT_MARGIN = 20`** (we use 15) — more conservative survival
- **Hotspot tracking**: Tracks scramble history per junction via `_shared_hotspots` counters. Aligners deprioritize junctions with high scramble counts (weight 8.0). We don't track scramble history at all
- **`_DEFAULT_NETWORK_WEIGHT = 0.5`** — small bonus for junctions near friendly network
- **Enemy AOE radius 20** for retreat detection (we use `JUNCTION_AOE_RANGE = 4`)
- **Cyborg architecture**: LLM reviews runtime telemetry and adjusts strategy directives. Detects stagnation (oscillation, target fixation, resource bias mismatch) and rewrites policy to break out
- Same pressure budget phases, same constants in helpers/types.py, same heart batching targets

The biggest gaps are likely: (1) our retreat is less conservative, (2) we don't track scramble hotspots, (3) we don't use LLM for stagnation detection in tournament.

## Strategies

### What Works
- **Chain-building**: Capture junctions near existing friendly junctions to expand the alignment network outward from hub
- **Pressure budgets**: Phase-based role allocation (more miners early, transition to aligners)
- **Heart batching**: Aligners collect 3+ hearts before heading out
- **Sticky targets**: Persist on a target unless a significantly better one appears (threshold 3.0)
- **Claim system**: Agents claim junctions to avoid duplicating effort

### What To Try
- **Hotspot tracking**: Like alpha.0, track scramble events per junction — deprioritize junctions that keep getting scrambled
- **Wider enemy AOE for retreat**: Alpha.0 uses 20, we use 4. May explain survival difference
- **Increase RETREAT_MARGIN to 20**: Match alpha.0's more conservative survival
- **LLM stagnation detection**: Use LLM to detect when agents are stuck and adjust directives
- Remove scramblers for cooperative scoring (test in 1v1, not scrimmage)
- Dynamic role switching based on game state
- Better junction discovery — agents miss junctions behind walls
- PCO evolution — run more epochs to evolve program table
- Study opponent replays via `cogames match-artifacts <id>` for new strategies

### Dead Ends (Don't Retry)
- Heart batch target changes — 3 for aligners is the sweet spot
- Outer explore ring at manhattan 35 — agents die before reaching targets
- Remove alignment network filter — required by game mechanics
- Expand alignment range +5 — targets unreachable junctions
- Remove scramblers in scrimmage — they help in self-play (retest in 1v1)
- Resource-aware pressure budgets — too aggressive scaling
- Spread miner resource bias — least-available targeting is better
- Reorder aligner explore offsets — existing order works better
- Increase claim penalty (12→25) — pushes aligners to suboptimal targets
- More aligners (6) / fewer miners (2) — economy can't sustain
- Wider A* margin (12→20) — slower, wastes ticks
- Emergency mining threshold 50 or 10 — hurts more than helps

## Rules & Constraints

1. **No shared state between agents.** Each agent gets its own WorldModel, claims dict, junctions dict. Sharing causes 0.00 score
2. **One change at a time.** Isolate what works vs what breaks
3. **Test across 5+ seeds.** A single seed is meaningless
4. **Local scores lie.** Self-play inflates scores. Submit and check tournament
5. **Revert on regression.** If average score drops, revert immediately
6. **Tournament has action timeout.** Keep per-step computation fast

## Learnings & Monitoring

Games write experience to `/tmp/coglet_learnings/{game_id}.json` containing snapshots, LLM logs, and per-agent state. Use these for PCO epochs.

Check tournament: `cogames leaderboard --season <season>`, `cogames matches`, `cogames match-artifacts <match-id>`.
