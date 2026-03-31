---
name: coach.init
description: Initialize a coaching engagement. Asks for a guide document, brainstorms a coaching strategy, generates guide.md, and creates .coach/ state. Use when starting a new coaching engagement or "coach init".
---

# Initialize Coaching

Set up a new coaching engagement by understanding the codebase, generating a coaching guide, and creating persistent state.

## Steps

### 1. Check for Existing State

Read `.coach/guide.md` — if it exists, this engagement is already initialized. Report current status from `.coach/state.json` and skip to step 6.

### 2. Ask for Instructions

Ask the user for a guide document — an `.md` file (or URL) that describes:
- **What the code does** — what is being optimized (a game agent, a service, a model, etc.)
- **How to run things** — build, test, play, submit commands
- **Strategies** — what approaches have worked, what to avoid
- **Rules & constraints** — things that must not change, invariants
- **Code structure** — key files, architecture, entry points

Example prompt: *"Point me to an .md file (or paste instructions) that describes what we're optimizing, how to run/test/submit, and any rules or strategies I should know about."*

If the user provides a file path, read it. If they provide a URL, fetch it. If they paste text, use that directly.

### 3. Explore the Codebase

With the user's instructions as context, explore the code to understand:
- Directory structure and key files
- The evolvable surface (what can the coach change?)
- Test and submission infrastructure
- Current performance (scores, baselines)

### 4. Brainstorm the Coaching Guide

Use the `/brainstorming` skill to develop a coaching strategy. The brainstorm should cover:

- **Objective**: What metric are we optimizing? What does "better" mean?
- **Evolvable surface**: What code/prompts/config can the coach modify?
- **Improvement loop**: How does one iteration work? (play → analyze → change → test → submit)
- **Testing strategy**: How to validate changes locally before submitting
- **Known dead ends**: What has been tried and failed (from user's instructions)
- **Constraints**: What must not break, rules about the code
- **Tools available**: PCO learner, local testing, tournament submission, etc.

### 5. Generate guide.md

Write the brainstormed strategy to `.coach/guide.md`. This is the coach's playbook — it gets loaded at the start of every session. Structure:

```markdown
# Coaching Guide

## Objective
What we're optimizing and how success is measured.

## Architecture
Key files, code structure, evolvable surface.

## How to Run
Commands for play, test, submit. Working directories.

## Improvement Loop
Step-by-step: what one coaching iteration looks like.

## Strategies
What works, what to try next, priorities.

## Dead Ends
What has been tried and failed — don't retry these.

## Rules & Constraints
Invariants, things that must not change.
```

### 6. Create .coach/ State

If `.coach/` doesn't exist, create:

```
.coach/
  guide.md             # Coaching playbook (generated above)
  state.json           # {"last_session": null, "best_score": 0, "total_sessions": 0, ...}
  todos.md             # Initial TODO list seeded from guide strategies
  session_config.md    # Session configuration (see below)
  sessions/            # Empty directory for session logs
```

### 7. Create session_config.md

Ask the user (or infer from guide.md):
- Policy name (e.g. "beta")
- Tournament season (e.g. "beta-teams-tiny-fixed")
- Git repo: "git" (this repo) or a URL
- Policy class path (e.g. "cvc.cvc_policy.CvCPolicy")
- Working directory for commands (e.g. "cogs/cogames")

### 8. Report

Summarize: what we're coaching, the strategy, first priorities from todos.md, and how to start the loop (`/coach` or `/loop 30m /coach.step`).
