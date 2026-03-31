---
name: coach.start-session
description: Start a new coaching session. Loads state from .coach/, checks tournament results for previous submissions, creates a new session directory with plan.md and log.md. Use at the beginning of each improvement cycle.
---

# Start Coaching Session

Load state from `.coach/` into context and create a new session.

## Steps

1. **Load state**:
   - Read `.coach/guide.md` — the coaching playbook (objective, strategies, constraints).
   - Read `.coach/state.json` — current scores, latest submission, session count.
   - Read `.coach/session_config.md` — policy name, season, git config.
   - Read `.coach/todos.md` — improvement ideas and dead ends.

2. **If git configured**, pull latest:
   ```bash
   git pull
   ```

3. **Check tournament results** for the latest submission:
   - Run: `cogames submissions --season <season> | grep <policy_name>`
   - Fetch scores from Observatory: `https://softmax.com/observatory/tournament/<season>/players`
   - Log findings: did the last submission improve? What's our rank?

4. **Finalize previous session** if it was WAITING:
   - Read the most recent `sessions/<timestamp>/log.md`
   - If it says WAITING, write tournament findings into it and mark as finalized.

5. **Create new session**:
   - Directory: `.coach/sessions/YYYYMMDD-HHMMSS/`
   - Write `plan.md`: current scores, what to try, why.
   - Start `log.md` with timestamp and plan summary.

6. **Report to user**: current rank, best score, gap to top, what this session will try.
