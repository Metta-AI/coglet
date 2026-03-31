# Session Plan: 20260331-073000

## Current State
- beta:v7 is #1 on leaderboard (score 10.00, 8 matches)
- beta:v8 regressed to #8 (score 29.00, 6 matches)
- alpha.0:v891 is #2 (score 10.00, 10 matches)
- nlanky:v7 is #3 (score 13.00)

## Analysis
v8 regressed significantly from v7. Need to understand what v8 changed and revert if needed. Then try improvements from v7 baseline.

## What to Try
1. **Hotspot tracking** (from alpha.0 reference): track scramble events per junction, deprioritize frequently-scrambled junctions for aligners. Weight 8.0 like alpha.0.
2. **Wider enemy AOE for retreat**: alpha.0 uses 20 for enemy detection range, we use 4. This may improve survival.
3. **RETREAT_MARGIN 20**: match alpha.0's more conservative survival (we use 15).

## Priority
Start with hotspot tracking — it's the biggest architectural gap vs alpha.0 and doesn't risk regression on its own.
