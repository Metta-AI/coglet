# /coach — Start the Coaching Loop

Start an automated coaching loop that continuously improves the coglet CvC tournament policy.

This sets up a `/loop` that runs `/coach.improve` every 30 minutes. Each iteration:
1. Checks for results from previous submissions
2. Analyzes current scores and identifies improvements
3. Makes a focused code change
4. Submits to the tournament
5. Logs everything under `.coach/`

## Instructions

Run the following to start the coaching loop:

```
/loop 30m /coach.improve
```

Then immediately run the first iteration:

```
/coach.improve
```

This ensures the first improvement happens right away, and subsequent iterations run every 30 minutes. If a session stalls or the context resets, the next `/coach.improve` invocation will detect the incomplete session and pick up where it left off.

## Monitoring

Check coaching progress anytime by reading:
- `.coach/state.json` — current best score, session count
- `.coach/todos.md` — improvement backlog and priorities
- `.coach/sessions/` — detailed logs of each coaching session
