# IMPROVE.md — CvC Tournament Agent

Coaching guide for the Cogs vs Clips tournament agent. Currently **#2** in freeplay with 17.02 (beta:v84). alpha.0 leads at ~20.5.

## Objective

Maximize **per-cog score**. Score = total junctions held per step / max steps. Higher = better.

## Setup

```bash
uv venv --python 3.12 .venv
source .venv/bin/activate
uv pip install -e . && uv pip install cogames
```

Verify: `source .venv/bin/activate && cogames --version`

## Workflow: Local → Freeplay → Tournament

### 1. Run Locally

Play a game and check the "per cog" score:

```bash
source .venv/bin/activate
cd cogs/cogames
PYTHONPATH=. cogames play -m machina_1 \
  -p class=cvc.cvc_policy.CvCPolicy \
  -c 8 -r none --seed 42
```

**Test across 5+ seeds** (42–46) and average. Single-seed results are noise.

Without LLM (matches tournament conditions):
```bash
ANTHROPIC_API_KEY= cogames play -m machina_1 \
  -p class=cvc.cvc_policy.CvCPolicy \
  -c 8 -r none --seed 42
```

### 2. Freeplay (`beta-cvc`)

Upload to freeplay to test against real opponents without tournament stakes:

```bash
source .venv/bin/activate
cd cogs/cogames
cogames ship \
  -p class=cvc.cvc_policy.CvCPolicy \
  -n beta \
  -f cvc -f mettagrid_sdk -f setup_policy.py \
  --setup-script setup_policy.py \
  --season beta-cvc \
  --skip-validation
```

Check freeplay results:
```bash
cogames leaderboard beta-cvc --mine
cogames matches --season beta-cvc
cogames match-artifacts <match-id>   # get logs from a specific match
```

Freeplay policies qualify via self-play, then play 20 matches against random partners. Use this to validate changes against diverse opponents before committing to tournament.

### 3. Win Tournaments (`beta-teams-tiny-fixed`)

Submit proven improvements to the ranked tournament:

```bash
cogames ship \
  -p class=cvc.cvc_policy.CvCPolicy \
  -n beta \
  -f cvc -f mettagrid_sdk -f setup_policy.py \
  --setup-script setup_policy.py \
  --season beta-teams-tiny-fixed \
  --skip-validation
```

Check tournament standings:
```bash
cogames leaderboard beta-teams-tiny-fixed --mine
cogames season progress beta-teams-tiny-fixed
cogames matches --season beta-teams-tiny-fixed
```

Tournament format: multi-stage elimination. Policies qualify via self-play, get seeded into teams, teams compete across progressive stages with culling. Final score based on team rank.

### Seasons

| Season | Purpose | Format |
|--------|---------|--------|
| `beta-cvc` | **Freeplay** — test against real opponents, low stakes | Self-play qualifier → 20 matches vs random partners |
| `beta-teams-tiny-fixed` | **Tournament** — ranked competition | Multi-stage elimination, team-based scoring |

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
| `JUNCTION_ALIGN_DISTANCE` | 15 | Friendly junctions extend alignment network by this |
| `JUNCTION_AOE_RANGE` | 10 | Junctions affect nearby junctions within this |
| `RETREAT_MARGIN` | 15 | Base HP safety margin (alpha.0 uses 20) |
| `DEPOSIT_THRESHOLD` | 12 | Miner deposits cargo at this amount |
| `TARGET_CLAIM_STEPS` | 30 | Junction claim expiry |
| `EXTRACTOR_MEMORY` | 600 | Steps to remember extractor locations |
| Hub initial resources | 24 each | num_agents × 3 of each element |

## Team Coordination

**In tournament, your agents play on a team with agents controlled by OTHER policies.** You must perform well across all team compositions, not just a team of your own clones. The team shares a hub, shared inventory, and junctions — but each agent is controlled by its own independent policy instance.

### What You Can See About Teammates

Via `team_summary` (game-provided, read-only):
- `team_summary.members` — list of visible teammates with `entity_id`, `role` (inferred from gear: miner/aligner/scrambler/unknown), `position`, `status`
- `team_summary.shared_inventory` — hub resources (all team members deposit to the same pool)
- `team_summary.shared_objectives` — any shared objectives set by the game

Via `visible_entities` — any teammate in your 13×13 viewport appears as a `SemanticEntity` with:
- `attributes["role"]` — their current gear role
- `attributes["agent_id"]` — their agent ID
- `labels` — includes "friendly"
- Position, inventory visible on the entity

### Vibe Actions (Signaling)

Each action has an optional **vibe** component — a visual signal visible to any agent in the viewport. Current vibes:
- `change_vibe_miner` — signals "I'm mining"
- `change_vibe_aligner` — signals "I'm aligning"
- `change_vibe_scrambler` — signals "I'm scrambling"
- `change_vibe_heart` — signals "I'm getting hearts"
- `change_vibe_gear` — signals "I'm getting gear"
- `change_vibe_default` — neutral/retreat

Vibes are set as the second component of every action: `Action(name="move_north", vibe="change_vibe_aligner")`. Other agents in range can observe the vibe on the entity in their viewport.

**Currently our agent sets vibes based on current role/action but does NOT read teammate vibes.** This is a key improvement opportunity — reading teammate vibes enables:
- Avoiding duplicate targets (if teammate is heading to same junction)
- Complementary role selection (if 3 teammates are already aligning, switch to mining)
- Coordinated expansion (if teammate is aligning nearby, push further out)

### Coordination Challenges

1. **You don't control your teammates.** They may be starter policies, random policies, or other competing agents. Don't assume they'll cooperate
2. **Shared economy.** All agents deposit to the same hub. If teammates are bad miners, your aligners starve. If you over-mine, you waste capacity
3. **Role overlap.** Without coordination, multiple agents may rush the same junction or role. Use vibes + position to infer teammate intent
4. **The LLM can learn to coordinate.** The `analyze` program should observe teammate roles, positions, and vibes to adjust strategy — e.g. "3 teammates are mining, I should align" or "teammate is heading to nearby junction, I'll target a different one"

### Improvement Ideas for Coordination

- **Read teammate vibes** in the engine — when choosing targets, check if a visible friendly agent has `change_vibe_aligner` and is closer to a candidate junction
- **Adaptive role allocation** — observe `team_summary.members` roles and adjust pressure budgets to complement teammates instead of assuming a fixed 8-agent split
- **LLM coordination** — expand the `analyze` prompt to include teammate positions, roles, and vibes, and let it suggest role switches or target avoidance
- **Vibe signaling protocol** — use vibes more expressively (e.g. cycle vibes to encode target direction, or use default vibe to signal "retreating/need help")

## Architecture

CvCPolicy is a **ProgLet** — a unified program table with two executor types:

```
CvCPolicy (MultiAgentPolicy)
  └── per-agent CvCPolicyImpl
       └── GameState (wraps CvcEngine)
       └── Program table (programs.py):
            ├── 31 code programs — fast Python functions (decision tree, pathfinding, roles)
            └── 1 LLM program ("analyze") — slow Claude call for strategic analysis
```

**Two speeds, one table.** The fast path (code programs) runs every tick: `desired_role()` → `step()` → role actions. The slow path (LLM program) runs every ~500 steps: `analyze` reviews game state and adjusts `resource_bias`. Both are entries in the same program dict, both are evolvable.

**The coach can improve both:**
- **Code programs** in `programs.py` — modify the Python functions (decision logic, scoring, thresholds)
- **LLM prompts** in `programs.py` — modify `_build_analysis_prompt()` and `_parse_analysis()` to change what the LLM sees and how its output is interpreted
- **Engine internals** in `agent/` — modify the underlying A*, targeting, pressure logic that programs delegate to

**The LLM can update programs during an episode** — the `analyze` program's output (currently just `resource_bias`) feeds back into GameState, influencing miner target selection in real-time. This is the coglet ProgLet pattern: programs observe, LLM reflects, programs adapt.

**Agents are fully independent. NO shared state between agents.** Each gets its own GameState, WorldModel, program table instance. They may run in separate processes against different opponents. Never use shared dicts, sets, or lists.

### Program Table (`programs.py`)

31 code programs + 1 LLM program, all evolvable by PCO:

| Category | Programs | What they do |
|----------|----------|-------------|
| **Query** | `hp`, `step_num`, `position`, `inventory`, `resource_bias`, `team_resources`, `resource_priority`, `nearest_hub`, `nearest_extractor`, `known_junctions`, `safe_distance`, `has_role_gear`, `team_can_afford_gear`, `needs_emergency_mining`, `is_stalled`, `is_oscillating` | Read-only state from GameState |
| **Action** | `action`, `move_to`, `hold`, `explore`, `unstick` | Movement via A* pathfinding |
| **Decision** | `desired_role`, `should_retreat`, `retreat`, `mine`, `align`, `scramble`, `step`, `summarize` | Compose queries + actions |
| **LLM** | `analyze` | Claude Sonnet reviews game state every ~500 steps, returns `resource_bias` + `analysis` |

### Decision Flow (per tick, per agent)

1. `process_obs()` → build MettagridState, update world model + junction memory
2. `desired_role()` program → pressure-based role allocation (miner/aligner/scrambler)
3. `step()` program → delegates to `engine._choose_action()`:
   hub_camp_heal → early_survival → wipeout_recovery → retreat → unstick → emergency_mine → acquire_gear → **role_action** → explore
4. `finalize_step()` → record navigation observation
5. Every ~500 steps: `analyze` LLM program → update `resource_bias`
6. Every ~500 steps: `summarize` program → collect experience snapshot for PCO

### Key Files

**Program table + policy** (`cogs/cogames/cvc/`):
- `programs.py` — **the 32 programs** (code functions + LLM prompt/parser). Primary evolvable surface
- `cvc_policy.py` — CvCPolicy (MultiAgentPolicy), CvCPolicyImpl (per-agent dispatch), LLM executor, experience collection
- `game_state.py` — GameState adapter wrapping CvcEngine for program table access

**Engine** (`cogs/cogames/cvc/agent/`) — infrastructure that programs delegate to:
- `main.py` — CvcEngine: main decision tree (`_choose_action`)
- `roles.py` — role actions (miner, aligner, scrambler)
- `navigation.py` — A* pathfinding, explore patterns, unstick
- `targeting.py` — target selection, claims, sticky targets
- `pressure.py` — role budgets, retreat thresholds
- `junctions.py` — junction memory, depot lookup
- `helpers/targeting.py` — scoring functions (aligner_target_score, scramble_target_score)
- `helpers/types.py` — constants, KnownEntity
- `helpers/resources.py` — resource/inventory queries

**PCO** (`cogs/cogames/cvc/`) — the optimization loop:
- `pco_runner.py` — `run_pco_epoch()` orchestrator
- `learner.py` — CvCLearner (LLM proposes program patches)
- `critic.py` — CvCCritic (evaluates experience)
- `losses.py` — ResourceLoss, JunctionLoss, SurvivalLoss
- `constraints.py` — SyntaxConstraint, SafetyConstraint

**Reference**: `cogs/cogames/cvc/AGENTS.md` — detailed game rules, full API reference

### PCO (Program Conditioned Optimization)

PCO evolves the program table between episodes. The CvCLearner sees all 32 program source codes + game experience, and proposes patches as `{"program_name": {"type": "code", "source": "def ..."}}`. Patches are validated by SyntaxConstraint + SafetyConstraint before acceptance.

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
# result = {"accepted": bool, "signals": [...], "patch": {...}}
```

Valid GameState API for patches: `gs.hp`, `gs.position`, `gs.step_index`, `gs.role`, `gs.nearest_hub()`, `gs.known_junctions(pred)`, `gs.should_retreat()`, `gs.choose_action(role)`, `gs.miner_action()`, `gs.aligner_action()`, `gs.scrambler_action()`, `gs.move_to_known(entity)`, `gs.explore(role)`, `gs.has_role_gear(role)`, `gs.needs_emergency_mining()`, `gs.team_id()`

## Reference: alpha.0 (tournament rival)

The alpha.0 agent lives at `metta-ai/cogora` (`src/cvc/cogent/player_cog/policy/`). Key differences from our agent:

- **`RETREAT_MARGIN = 20`** (we use 15) — more conservative survival
- **Hotspot tracking**: Tracks scramble history per junction via `_shared_hotspots` counters. Aligners deprioritize junctions with high scramble counts (weight 8.0). We don't track scramble history at all
- **`_DEFAULT_NETWORK_WEIGHT = 0.5`** — small bonus for junctions near friendly network
- **Enemy AOE radius 20** for retreat detection (we use `JUNCTION_AOE_RANGE = 4`)
- **Cyborg architecture**: LLM reviews runtime telemetry and adjusts strategy directives. Detects stagnation (oscillation, target fixation, resource bias mismatch) and rewrites policy to break out
- Same pressure budget phases, same constants in helpers/types.py, same heart batching targets

## Strategies

### What Works
- **Shared junction memory**: All agents on same policy share junction discovery + claims via shared dicts. Massive self-play improvement (+214%). Freeplay testing in progress (v113)
- **Chain-building**: Capture junctions near existing friendly junctions to expand the alignment network outward from hub
- **Pressure budgets**: Phase-based role allocation (more miners early, transition to aligners)
- **Heart batching**: Aligners collect 3+ hearts before heading out
- **Sticky targets**: Persist on a target unless a significantly better one appears (threshold 3.0)
- **Claim system**: Agents claim junctions to avoid duplicating effort

### What To Try
- **LLM stagnation detection**: Use LLM to detect when agents are stuck and adjust directives (alpha.0's key advantage)
- Dynamic role switching based on game state
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
- Enemy avoidance penalty in aligner scoring — helps self-play (+31%) but HURTS freeplay (-33%)
- Remove scramblers entirely — helps self-play (+26%) but HURTS freeplay (-31%). Scramblers needed to deny opponent junctions
- RETREAT_MARGIN=18 — freeplay 7.78 (big regression)
- RETREAT_MARGIN=20 — freeplay 9.99 (regression). Also hurts self-play (-19%)
- Tighter aligner explore offsets (manhattan 15) — agents miss distant junctions (-35%)
- Heart batch cap at 4 (remove 5/6 scaling) — uncertain, tested bundled with other changes
- Self-play improvements DON'T predict freeplay improvements — the two are weakly correlated
- Expansion bonus cap 30→40 — self-play +16% but freeplay 9.31 (regression)
- Network bonus 0.5→2.0 — self-play +51% but freeplay 10.19 (regression)
- Mid-range scrambler explore offsets — self-play +25% but freeplay 10.75 (regression)
- Reachable-blocked scramble targeting — self-play +49% but freeplay 10.00-10.88 (regression)
- enemy_aoe penalty 8.0→4.0 — untested in freeplay, reverted to be safe
- Shared junction memory between agents — self-play +214% but freeplay 14.23 (regression). Coordination asymmetry with mixed teams
- Hub defense bonus for scrambler — self-play +11% but freeplay 11.77 (regression)
- Teammate aligner avoidance penalty (5.0-6.0) — -11% self-play regression
- Faster unstick 12→8 — freeplay 16.23 (slight regression from 17.02)

### Critical Learnings
- **Scrambler is heart-starved**: In self-play with (4,1) budget, the scrambler has 0 hearts for most of the game because 4 aligners consume all team hearts first. The scrambler is effectively useless in self-play, but still matters in freeplay (even occasional scrambles deny opponent)
- **Junction collapse pattern**: Peak at ~7 friendly junctions (step 500), collapse to 0-2 by step 5000 in self-play. Enemy team scrambles faster than we rebuild
- **Early game is critical**: Most score comes from first 500-2000 steps. Late game contributes little
- **Shared state hurts freeplay**: Sharing junction memory/claims between agents helps self-play (+214%) but hurts freeplay (-16%). In mixed teams, coordination within our agents creates asymmetry vs uncoordinated teammates
- **ALL post-v84 scoring changes hurt freeplay**: v84 has been freeplay best (17.02) for 30+ sessions. Every heuristic tweak that improved self-play regressed in freeplay. The two are weakly/negatively correlated
- **Actual game constants**: HUB_ALIGN_DISTANCE=25, JUNCTION_ALIGN_DISTANCE=15, JUNCTION_AOE_RANGE=10 (not 3/4 as originally documented)
- **LLM may be the structural gap**: Alpha.0's cyborg architecture with LLM stagnation detection is likely the key differentiator. Our LLM only adjusts resource_bias. Enhanced to provide role/objective guidance in v42

## Rules & Constraints

1. **No shared state between agents.** Each agent gets its own WorldModel, claims dict, junctions dict. Sharing causes 0.00 score
2. **One change at a time.** Isolate what works vs what breaks
3. **Test across 5+ seeds.** A single seed is meaningless
4. **Local scores lie.** Self-play inflates scores. Validate in freeplay before tournament
5. **Revert on regression.** If average score drops, revert immediately
6. **Tournament has action timeout.** Keep per-step computation fast

## Learnings & Monitoring

Games write experience to `/tmp/coglet_learnings/{game_id}.json` containing snapshots, LLM logs, and per-agent state. Use these for PCO epochs.

```bash
cogames leaderboard beta-cvc --mine              # freeplay standings
cogames leaderboard beta-teams-tiny-fixed --mine  # tournament standings
cogames matches --season <season>                 # recent matches
cogames match-artifacts <match-id>                # logs from a match
cogames season progress <season>                  # stage progression
```
