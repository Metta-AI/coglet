---
name: coach.improve
description: Run one PCO improvement iteration. Plays a game, collects experience, runs CvCLearner to propose patches, tests locally, and submits if improved. Assumes session is already started (use coach.start-session first). Use when asked to "improve the agent" or "run PCO".
---

# PCO Improvement Iteration

Run one PCO (Proximal Coglet Optimizer) cycle: play → collect experience → learn → test → submit.

Assumes `.coach/state.json` and the current session directory already exist (via `/coach.start-session`).

## Steps

### 1. Play a Game & Collect Experience

```bash
cd <cogames_dir>  # from session_config.md
rm -f /tmp/coglet_learnings/*.json
ANTHROPIC_API_KEY= cogames scrimmage \
  -m machina_1 \
  -p class=<policy_class> \
  -c 8 -e 1 --seed <random_seed> \
  --action-timeout-ms 10000
```

Use `ANTHROPIC_API_KEY=` to match tournament (no LLM). Pick a random seed 42-100.

### 2. Run PCO Epoch

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

Log signals (resource, junction, survival magnitudes) and proposed patches.

### 3. Review & Apply Patch

If `result["accepted"]` and patch looks reasonable:
- Fix any invalid API calls (the learner sometimes invents methods)
- Apply to `programs.py` — only modify the specific function
- **Valid GameState API**: `gs.hp`, `gs.position`, `gs.step_index`, `gs.role`, `gs.nearest_hub()`, `gs.known_junctions(predicate)`, `gs.should_retreat()`, `gs.choose_action(role)`, `gs.miner_action()`, `gs.aligner_action()`, `gs.scrambler_action()`, `gs.move_to_known(entity)`, `gs.explore(role)`, `gs.has_role_gear(role)`, `gs.needs_emergency_mining()`, `gs.team_id()`
- **Valid helpers**: `_h.manhattan(pos1, pos2)`, `_h.team_id(state)`, `_h.resource_total(state)`

### 4. Test Across Seeds

Run 3+ seeds without LLM:
```bash
ANTHROPIC_API_KEY= cogames scrimmage -m machina_1 -p class=<policy_class> -c 8 -e 1 --seed <N> --action-timeout-ms 10000
```

If average score drops vs baseline, **revert the patch**.

### 5. Submit if Improved

```bash
cogames upload -p class=<policy_class> -n <policy_name> \
  -f cvc -f mettagrid_sdk -f setup_policy.py \
  --setup-script setup_policy.py --season <season> --skip-validation
```

Log the submission version and "WAITING" status.

## Principles

- **One patch per iteration.** Don't stack changes.
- **Revert on regression.** A single bad seed collapse means revert.
- **No shared state between agents.** Never use shared dicts.
- **Check dead ends in todos.md** before trying anything.
