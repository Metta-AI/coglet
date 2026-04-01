# Session 62 Plan

**Timestamp**: 2026-04-01 07:00:00

## Current Status
- Freeplay: #2 (beta:v84 = 17.02), alpha.0 = 20.64 (gap: 3.62)
- Tournament: EMPTY (season reset?)
- v105 shared junctions: 14.69 — REGRESSION (-14% from v84)
- All post-v84 submissions (v86-v113) scored WORSE than v84 in freeplay

## Key Insight
Shared junction memory helped self-play (+214%) but hurt freeplay (-14%).
In freeplay, agents from different policies play together — sharing state
only among our agents creates coordination asymmetry.

## Plan
1. Revert shared junctions — return to exact v84 codebase
2. Submit clean v84 to tournament (empty leaderboard)
3. Try new improvement: smarter target selection based on game phase
   - Early game (steps 0-2000): prioritize hub-proximal junctions for fast network
   - Mid game (steps 2000-5000): expand outward from established network
   - Late game (steps 5000+): focus on defense/holding, reduce exploration
   This addresses the "junction collapse" pattern (peak at step 500, collapse by 5000)
