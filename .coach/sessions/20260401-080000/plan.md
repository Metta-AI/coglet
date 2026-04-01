# Session 58 Plan

## Current Status
- **Freeplay**: #2 at 17.02 (beta:v84). alpha.0:v922 is #1 at 19.81. Gap: 2.79 points.
- **Tournament**: Stage 3 play-ins in progress. v95 qualifying for stage-1.
- **Problem**: All versions after v84 have REGRESSED in freeplay (v86=16.23, v88=9.31, v92=10.75)

## Root Cause Analysis
Changes after v84 that hurt freeplay:
1. Network bonus 0.5→2.0: Over-incentivizes clustering, agents don't spread enough
2. Expansion cap 30→40: Over-rewards dense areas, ignores easier neutral targets
3. Scrambler explore offsets (25): Mid-range offsets may waste time
4. Reachable-blocked scramble targeting: Additional complexity, may misallocate scramblers

## Plan
1. **Revert to v84 code** — our freeplay best
2. **Analyze alpha.0's advantage** — they score 19.81 vs our 17.02
3. **Make a targeted improvement** that helps freeplay (not just self-play)
4. **Submit to freeplay first** to validate before tournament
