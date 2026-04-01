# Session 62 Log

**Timestamp**: 2026-04-01 07:00:00
**Approach**: IntelligentDesign

## Status: WAITING

## Tournament Update
- Freeplay: alpha.0:v922 = 21.30 (#1), beta:v84 = 17.02 (#2) — gap 4.28
- Tournament: EMPTY (season reset)
- v105 (shared junctions): 14.23 — REGRESSION
- v120 (teammate_closer): 13.49 — REGRESSION
- v115 (scrambler bugfix): 12.65 — REGRESSION
- v117 (hub defense): 11.77 — REGRESSION
- v121 (interleaved priorities + hub defense + shared junctions): still running, early scores ~10

## Key Findings
1. ALL post-v84 changes continue to regress in freeplay
2. Shared junctions hurt freeplay (14.23 vs 17.02) — coordination asymmetry
3. Hub defense bonus hurt freeplay (11.77 vs 17.02)
4. Teammate aligner avoidance penalty is a dead end (-11.1% self-play)
5. PCO suggested should_retreat with extra HP<70 caution — skipped (retreat tuning = dead end)

## Change
Reverted shared junctions AND hub defense bonus. Kept interleaved role priorities
(structural fix for freeplay subset balance) and scrambler friendly_junctions bugfix.

This gives: v84 base + interleaved priorities + scrambler bugfix only.

## Self-Play (seed 42 only)
- Current (with all changes): 14.58
- After revert (interleaved only): 11.78

Note: Lower self-play may actually be BETTER for freeplay — self-play improvements
consistently DON'T predict freeplay improvements.

## Submissions
- Freeplay: beta:v126 (beta-cvc)
- Tournament: beta:v127 (beta-teams-tiny-fixed)
