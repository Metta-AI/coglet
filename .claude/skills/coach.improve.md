# /coach.improve — Improve the CvC Policy

You are the Coach for the coglet CvC tournament player. Your job is to iteratively improve the policy code, test it, and submit improved versions to the `beta-cvc` tournament season.

## Directory Layout

All coaching state lives under `.coach/`:

```
.coach/
  state.json          # persistent state (best score, last session, etc.)
  todos.md            # running TODO list of improvement ideas
  sessions/
    <timestamp>/
      plan.md         # what this session is trying and why
      log.md          # running log of actions, results, observations
      diff.patch      # the code diff attempted (if any)
      results.json    # tournament/local results collected
```

## Session Protocol

### Step 1: Load State & Check for Incomplete Sessions

1. Read `.coach/state.json` for persistent state.
2. Read `.coach/todos.md` for the current improvement backlog.
3. Scan `.coach/sessions/` for the most recent session folder.
4. If the last session's `log.md` indicates it was **waiting for tournament results** or **incomplete**:
   - Check tournament API for those results now (see "Checking Scores" below).
   - Write findings into THIS session's log.
   - Finalize the old session: update its `results.json`, mark it done in `log.md`.
   - If the old session's changes improved scores, keep them. If not, consider reverting.

### Step 2: Create a New Session

1. Create a new session folder: `.coach/sessions/YYYYMMDD-HHMMSS/`
2. Write an initial `plan.md` describing:
   - Current best score and rank
   - What improvement you're attempting and why
   - Which files you plan to modify
3. Start `log.md` with a timestamp and the plan summary.

### Step 3: Analyze & Identify Improvements

Read the current policy code to understand what can be improved:

**Key files to read:**
- `cogames/cvc/cvc_policy.py` — Top-level policy with LLM brain
- `cogames/cvc/policy/anthropic_pilot.py` — CogletAgentPolicy with macro directives
- `cogames/cvc/policy/semantic_cog.py` — Base semantic policy (~1300 lines, the core logic)
- `cogames/cvc/policy/helpers/targeting.py` — Target scoring for aligners/scramblers
- `cogames/cvc/policy/helpers/resources.py` — Resource/inventory/phase logic
- `cogames/cvc/policy/helpers/geometry.py` — Movement and navigation
- `cogames/cvc/policy/helpers/types.py` — Constants and tuning parameters

**Analysis approach:**
- Check the current tournament leaderboard scores (see below)
- Look at match results for recent coglet submissions
- Identify the weakest aspect: economy, combat, alignment strategy, resource management
- Check `.coach/todos.md` for previously identified improvement ideas
- Focus on ONE focused improvement per session (not a big rewrite)

**Common improvement areas:**
- Tuning constants (HP thresholds, heart batch targets, hub penalties, claim penalties)
- Role allocation strategy (aligner/scrambler/miner ratios over game phases)
- Target selection scoring (aligner_target_score, scramble_target_score weights)
- Resource management (when to mine, when to deposit, emergency thresholds)
- Retreat logic (when to retreat, safety margins)
- Heart batching (how many hearts to collect before acting)
- LLM brain prompts and directive handling

### Step 4: Make the Improvement

1. Make a focused, small change. Don't rewrite large sections.
2. Log what you changed and why in the session `log.md`.
3. Save the diff: `git diff > .coach/sessions/<session>/diff.patch`
4. Commit the change with a descriptive message.

### Step 5: Submit to Tournament

Upload the improved policy to the tournament:

```bash
cd /home/user/coglet/cogames && cogames upload \
  -p class=cvc.cvc_policy.CogletPolicy \
  -n coglet-v0 \
  -f cvc -f mettagrid_sdk -f setup_policy.py \
  --setup-script setup_policy.py \
  --season beta-cvc
```

**IMPORTANT**: The `cogames` CLI may not be installed. If not, the upload must be done via the tournament API directly. Check if `cogames` is available first. If not available, skip submission and note it in the log — the user can submit manually, or a future session can retry.

### Step 6: Log & Update State

1. Update `log.md` with:
   - What was submitted (version number if available)
   - "WAITING: submitted version N, checking results next session"
2. Update `.coach/state.json` with `last_session` timestamp.
3. Update `.coach/todos.md`:
   - Mark completed items as done
   - Add new ideas discovered during analysis
   - Prioritize next improvements

## Checking Scores (Tournament API)

Since `cogames` CLI may not be installed, use the API directly:

```bash
# Get leaderboard
curl -s -H "Authorization: Bearer $COGAMES_TOKEN" \
  "https://api.observatory.softmax-research.net/tournament/seasons/beta-cvc/leaderboard" \
  | python3 -c "
import sys, json
data = json.load(sys.stdin)
coglet = [e for e in data if 'coglet' in e.get('policy',{}).get('name','').lower()]
for e in coglet:
    p = e['policy']
    print(f\"Rank #{e['rank']}/{len(data)}: {p['name']} v{p['version']} — Score: {e['score']:.3f} +/- {e['score_stddev']:.3f} ({e['matches']} matches)\")
print(f'Top score: {data[0][\"score\"]:.3f} ({data[0][\"policy\"][\"name\"]} v{data[0][\"policy\"][\"version\"]})')
"

# Get recent match results for our policy
curl -s -H "Authorization: Bearer $COGAMES_TOKEN" \
  "https://api.observatory.softmax-research.net/tournament/seasons/beta-cvc/matches?limit=20" \
  | python3 -c "
import sys, json
data = json.load(sys.stdin)
if isinstance(data, list):
    for m in data[:10]:
        print(json.dumps(m, indent=2, default=str)[:200])
"
```

## Key Principles

1. **One change at a time.** Make one focused improvement, submit, wait for results. Don't stack multiple changes.
2. **Log everything.** Every session should leave a clear trail of what was tried and what happened.
3. **Don't break what works.** If the current policy scores 2.3, a change that might score 0 is not worth the risk. Be conservative.
4. **Learn from the leaderboard.** The top policies score ~6.4. Understand what they might be doing differently.
5. **Prioritize high-impact changes.** Constants tuning is low-risk. Role allocation changes are medium. Algorithm rewrites are high-risk.
6. **Git discipline.** Always commit before submitting. Use descriptive commit messages. Push to the feature branch.

## Session Finalization

At the end of each session, ensure:
- `log.md` has a clear final status (DONE, WAITING, or FAILED with reason)
- `results.json` has any scores collected
- `.coach/state.json` is updated
- `.coach/todos.md` reflects current priorities
- All changes are committed and pushed to `claude/get-coglet-score-xxlME`
