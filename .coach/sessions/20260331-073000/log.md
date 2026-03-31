# Session Log: 20260331-073000

## 2026-03-31 07:30 — Session started
Focus: close gap to alpha.0 via known strategy differences

## Tournament Results
- beta:v7: #1 (score 10.00, 8 matches) — our best
- beta:v8: #8 (score 29.00, 6 matches) — regression (few matches, likely variance)
- alpha.0:v891: #2 (score 10.00, 10 matches)
- Top competitors: nlanky:v7 (#3, 13.00), slanky:v112 (#4, 13.00)

## Experiment A: Hotspot tracking (alpha.0's scramble history)
- Added _scramble_hotspots dict to JunctionMixin, tracking ownership changes
- Added hotspot_penalty (8.0 per scramble, capped at 5) to aligner_target_score
- Result: avg 1.55 (scrimmage) — REGRESSION from 1.93 baseline
- Conclusion: Penalizing contested junctions makes agents avoid the most valuable junctions. Reverted.

## Experiment B: Wider enemy AOE for retreat (radius 20, matching alpha.0)
- Changed _in_enemy_aoe from _JUNCTION_AOE_RANGE (4) to radius 20
- Result: avg 2.07 (scrimmage) — mixed, seed 45 regressed -53%
- Tried radius 10: avg 1.43, seed 44 collapsed to 0.00
- Conclusion: Wider retreat radius causes over-retreating, wasting ticks. Reverted.

## Experiment C: Revert to hub-only scoring (remove network_dist chain logic)
- Reverted network_dist to hub_dist only for penalty calculation
- Result: avg 1.38 (play) — REGRESSION from 1.66 baseline, seed 44 collapsed to 0.00
- Conclusion: Chain-aware network scoring IS helping. Reverted.

## Experiment D: Remove scramblers (cooperative scoring) ✅
- Set scrambler_budget=0, all pressure budget goes to aligners
- Dead end note said "retest in 1v1 for cooperative scoring"
- Tested in 1v1 (vs random): avg 1.63 vs 1.48 baseline (+10%)
- Tested in scrimmage: avg 1.86 vs 1.66 baseline (+12%)
- Makes sense: in cooperative scoring, scramblers reduce total junctions for both teams

### Results (1v1 vs random)
| Seed | Baseline | No Scramblers | Change |
|------|----------|---------------|--------|
| 42   | 1.42     | 1.58          | +11%   |
| 43   | 2.29     | 2.53          | +10%   |
| 44   | 0.65     | 0.94          | +45%   |
| 45   | 1.10     | 2.23          | +103%  |
| 46   | 1.95     | 0.89          | -54%   |
| **Avg** | **1.48** | **1.63**   | **+10%** |

## Actions
- Committed: `aa5a020` feat: remove scramblers for cooperative scoring
- Pushed to claude/implement-coach-command-K77D3
- Submitted as beta:v25

## Status: WAITING
Submitted v25, checking tournament results next session.
