---
name: coach.improve
description: This skill should be used when the user asks to "improve the agent", "run a coaching session", "coach improve", "iterate on the policy", or wants to test and submit agent changes to the CvC tournament. Runs one PCO-driven improvement iteration with local testing, tournament submission, and logging.
---

# PCO-Driven Agent Improvement Session

Act as the Coach. Each session: play a game, run a PCO epoch to evolve the program table, test locally, submit to tournament, and log results.

**Read `cvc/agent/README.md` first** for the full guide to how the agent works, testing, submission, and debugging.

## Architecture

The agent uses a **program table** (`cogames/cvc/programs.py`) with three evolvable surfaces:

1. **Python functions** (LET) — fast reactive actions: `step`, `heal`, `retreat`, `mine`, `align`, `scramble`, `explore`
2. **Prompts** (COG) — slow strategic analysis: `analyze`
3. **Observation programs** — what the learner sees: `summarize`, `macro`

**PCO** (Proximal Coglet Optimizer) runs between games to evolve these programs:
- `CvCCritic` evaluates game experience (resources, junctions, deaths)
- `ResourceLoss`, `JunctionLoss`, `SurvivalLoss` compute signals
- `CvCLearner` (LLM-based) proposes patches to any program
- `SyntaxConstraint`, `SafetyConstraint` validate patches
- Accepted patches update the program table for the next game

Key files:
- `cogames/cvc/programs.py` — seed program table, `StepContext`
- `cogames/cvc/table_policy.py` — `TablePolicy` (MultiAgentPolicy using program table)
- `cogames/cvc/pco_runner.py` — `run_pco_epoch()` orchestrates one PCO epoch
- `cogames/cvc/learner.py` — LLM-based learner
- `cogames/cvc/critic.py`, `losses.py`, `constraints.py` — PCO components

## Directory Layout

```
.coach/
  state.json          # persistent state (best score, program table snapshot)
  todos.md            # running TODO list of improvement ideas
  sessions/
    <timestamp>/
      plan.md         # what this session is trying and why
      log.md          # running log: actions, results, observations, wait status
      diff.patch      # the code diff attempted (if any)
      results.json    # local + tournament results collected
      programs.json   # program table state after this session
```

## Session Protocol

### Step 1: Load State & Finalize Incomplete Sessions

1. Read `.coach/state.json` and `.coach/todos.md`.
2. Scan `.coach/sessions/` for the most recent session folder.
3. If the last session's `log.md` says **WAITING** (submitted but no results yet):
   - Check tournament scores now (see README for how).
   - Write findings into THIS session's log.
   - If the old session's changes improved scores, keep them. If scores dropped, consider reverting.
   - Update the old session's `results.json` and mark it finalized.

### Step 2: Create New Session

1. Create `.coach/sessions/YYYYMMDD-HHMMSS/`
2. Write `plan.md`: current best score/rank, what to try, which programs to evolve, and why.
3. Start `log.md` with a timestamp and plan summary.

### Step 3: Play a Game & Collect Experience

Run a local scrimmage using `TablePolicy`:

```bash
cd /home/user/coglet/cogames
/home/user/.venv-cogames/bin/cogames scrimmage \
  -m machina_1 \
  -p class=cvc.table_policy.TablePolicy \
  -c 8 -e 1 --seed 42 \
  --action-timeout-ms 30000
```

Collect the experience from `$COGLET_LEARNINGS_DIR` (default `/tmp/coglet_learnings/`).

### Step 4: Run PCO Epoch

Use `run_pco_epoch()` to analyze the game and propose improvements:

```python
import asyncio
from cvc.pco_runner import run_pco_epoch
from cvc.programs import seed_programs

experience = [...]  # loaded from learnings JSON
result = asyncio.run(run_pco_epoch(
    experience=experience,
    programs=seed_programs(),  # or current evolved programs
    client=anthropic_client,   # for LLM-based learner
))
```

The result contains:
- `accepted`: whether the patch passed constraints
- `signals`: loss values (resource, junction, survival)
- `patch`: proposed program changes (if any)

Log the PCO result in `log.md`: which programs were patched, loss signals, acceptance status.

### Step 5: Apply & Test Changes

If the PCO epoch produced an accepted patch:

1. Review the proposed changes (code functions or prompt modifications)
2. Apply them to the program table source files in `cogames/cvc/programs.py`
3. Run a scrimmage with the updated programs to verify improvement:

```bash
/home/user/.venv-cogames/bin/cogames scrimmage \
  -m machina_1 \
  -p class=cvc.table_policy.TablePolicy \
  -c 8 -e 1 --seed 42 \
  --action-timeout-ms 30000
```

- Compare "Average Per-Agent Reward" against baseline.
- If score dropped, revert the change.
- Log results in `log.md`.

If no accepted patch (learner had no client, or constraints rejected), manually analyze the loss signals to identify the weakest area and make a targeted code change.

### Step 6: Commit & Submit

1. Save diff: `git diff > .coach/sessions/<session>/diff.patch`
2. Commit with a descriptive message. Push to the feature branch.
3. Submit to tournament (see README for the `ship` command).
4. Log: "WAITING: submitted, checking results next session"

### Step 7: Update State

1. Update `.coach/state.json` (last_session, loss signals, local score)
2. Update `.coach/todos.md` (mark done items, add new ideas from PCO signals)
3. Ensure `log.md` has a clear final status: DONE, WAITING, or FAILED

## Manual Improvement (Without Full PCO)

If PCO infrastructure isn't available or you want direct control:

1. Read the program table in `cogames/cvc/programs.py`
2. Identify the weakest program based on game logs and tournament scores
3. Modify one program function (e.g. improve `_mine` or adjust `_retreat` thresholds)
4. Test locally with `cogames scrimmage`
5. Commit and submit

## Principles

1. **Test locally first.** Never submit untested changes to tournament.
2. **One change at a time.** Modify one program per session.
3. **Don't break what works.** Conservative > ambitious. A regression is worse than no change.
4. **Log everything.** Loss signals, PCO results, local scores, tournament scores.
5. **Learn from PCO signals.** The loss breakdown (resource/junction/survival) tells you where to focus.
6. **Evolve all three surfaces.** Don't just tweak code — also improve prompts and what the learner observes.
7. **Git discipline.** Commit before submitting. Push to the feature branch.
