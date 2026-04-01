# Session 58 Log

**Timestamp**: 2026-04-01 08:00:00
**Approach**: IntelligentDesign

## Status: WAITING

Submitted beta:v117 (freeplay) and beta:v118 (tournament).

## Key Decision: Revert to v84 base

All versions after v84 regressed in freeplay despite improving self-play:
- v84: **17.02** (freeplay best)
- v86: 16.23 (unstick 12→8)
- v88: 9.31 (expansion cap 40)
- v92: 10.75 (scrambler explore offsets)

Reverted all post-v84 changes (network bonus 2.0, expansion cap 40, scrambler explore, reachable-blocked scramble, unstick 8) back to v84 base.

## Change: Scrambler hub defense bonus

Added hub_defense_bonus to scramble_target_score(): enemy junctions within hub alignment range (25) get a bonus of (25 - hub_dist) * 0.5. This makes scramblers prioritize clearing enemy junctions that directly block our core territory.

Rationale: v82→v84 improvement came from stronger scramble scoring (blocked_neutrals weight 4→6, +1.5 freeplay points). Doubling down on scrambler effectiveness.

## Tried and Reverted: Teammate aligner avoidance

Enabled teammate_closer parameter in aligner scoring (penalty 5.0 when teammate is closer to target).
Result: **-11.1%** regression (8.47→7.53), seed 43 hit 0.00. Reverted.

## Test Results (Self-Play, 7 seeds)

| Seed | Baseline (v84) | +HubDefense | Diff |
|------|----------------|-------------|------|
| 42 | 11.75 | 10.74 | -1.01 |
| 43 | 7.33 | 7.36 | +0.03 |
| 44 | 2.10 | 9.24 | +7.14 |
| 45 | 9.36 | 8.50 | -0.86 |
| 46 | 10.32 | 11.23 | +0.91 |
| 47 | 9.97 | 10.15 | +0.18 |
| 48 | 8.49 | 8.70 | +0.21 |
| **Avg** | **8.47** | **9.42** | **+0.94 (+11.1%)** |

No zero seeds. Min improved dramatically (2.10→7.36). Variance reduced.

## Submissions
- Freeplay: beta:v117 (beta-cvc)
- Tournament: beta:v118 (beta-teams-tiny-fixed)
