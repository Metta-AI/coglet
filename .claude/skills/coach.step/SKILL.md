---
name: coach.step
description: Run one full coaching step — start session, run PCO improvement, save session. This is the skill that /loop calls every 30 minutes. Use when asked to "run a coaching step" or "coach step".
---

# Coaching Step

One full improvement cycle. Run these skills in order:

1. `/coach.start-session` — load state, check tournament results, create session dir
2. `/coach.improve` — play game, run PCO, test patch, submit if improved
3. `/coach.save-session` — write logs, update state, commit and push

If invoked with an argument (e.g. `/coach.step beta`), pass it through to each sub-skill as the policy name.
