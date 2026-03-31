---
name: coach.save-session
description: Save current coaching session state. Writes log, updates state.json and todos.md, commits and pushes if git is configured. Use at the end of each improvement cycle.
---

# Save Coaching Session

Persist the current session's results to `.coach/` and optionally push to git.

## Steps

1. **Read session config**:
   - Read `.coach/session_config.md` for git config and policy details.

2. **Write session log**:
   - Ensure the current session's `log.md` has a final status (DONE, WAITING, or FAILED).
   - Include: tournament scores checked, changes attempted, test results, submission version.

3. **Update state.json**:
   - `last_session`: current session timestamp
   - `total_sessions`: increment
   - `latest_submission`: version if submitted
   - `tournament_best`: update if improved
   - `key_fix`: what changed

4. **Update todos.md**:
   - Mark completed items as done
   - Add new dead ends discovered this session
   - Add new improvement ideas from PCO signals

5. **If git configured**, commit and push:
   ```bash
   git add .coach/state.json .coach/todos.md .coach/sessions/<current>/
   git add <any modified code files>
   git commit -m "coach: session N — <summary>"
   git push
   ```

6. **Report**: session summary — what changed, what was submitted, current rank.
