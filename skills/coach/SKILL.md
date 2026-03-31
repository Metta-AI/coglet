---
name: coach
description: Start the coaching loop. Initializes state, then runs /coach.step every 30 minutes. Use when asked to "start coaching", "coach the agent", or "start the coaching loop".
---

# Start the Coaching Loop

Initialize coaching state and start the automated improvement loop.

## Instructions

1. Run `/coach.init` to load or create coaching state.
2. Start the recurring loop:
   ```
   /loop 30m /coach.step
   ```
3. Run the first step immediately:
   ```
   /coach.step
   ```
