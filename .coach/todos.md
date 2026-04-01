# Coach TODO

## Current Priorities
- [ ] Monitor v117 freeplay (hub defense bonus, reverted to v84 base)
- [ ] Monitor v118 tournament entry
- [ ] Monitor v113 freeplay (shared junctions + pure v84 params — BEST CANDIDATE)
- [ ] If v117 or v113 beats alpha.0: submit to tournament aggressively
- [ ] Update IMPROVE.md with shared junctions finding and corrected constants

## Improvement Ideas
- [ ] Map topology analysis — understand wall patterns to improve exploration
- [ ] Dynamic role switching — let agents switch roles based on game state (gentle version)
- [ ] PCO evolution — run more epochs to evolve program table
- [ ] Better junction discovery — agents may miss junctions behind walls
- [ ] Adaptive role allocation based on game phase (not just step count)
- [ ] Study opponent replays via `cogames match-artifacts <id>` for new strategies
- [ ] Network-dist scoring with conservative blend (50/50 hub+network dist)
- [ ] Scrambler heart priority — ensure scrambler gets hearts before aligners

## Dead Ends (Don't Retry)
- [x] Retreat threshold tuning — always trades deaths for score regression
- [x] Heart batch target changes — 3 for aligners is the sweet spot
- [x] Outer explore ring at manhattan 35 — sends agents too far, they die
- [x] Remove alignment network filter — required by game mechanics
- [x] Expand alignment range +5 — causes targeting unreachable junctions
- [x] Remove scramblers entirely (SCRIMMAGE only) — confirmed twice in self-play
- [x] Resource-aware pressure budgets — too aggressive scaling
- [x] Spread miner resource bias — least-available targeting is better
- [x] Reorder aligner explore offsets — existing order works better
- [x] Increase claim penalty (12→25) — pushes aligners to suboptimal targets
- [x] More aligners (6) / fewer miners (2) — economy can't sustain
- [x] Wider A* margin (12→20) — slower computation wastes ticks
- [x] Emergency mining threshold 50 or 10 — hurts high-scoring seeds
- [x] Early pressure ramp (step 200) — economy can't sustain with only 2 miners
- [x] Wider enemy AOE radius 15 for retreat — agents retreat too much
- [x] Delay scramblers to step 500 — opponent builds unchallenged
- [x] Hotspot recapture bonus — agents waste hearts on contested junctions
- [x] Hotspot decay (every 1000 steps) — -9% regression
- [x] Reading teammate vibes — vibes are NOT visible in game API
- [x] Aggressive adaptive role allocation — killed 1v1 scores
- [x] Pure network-dist scoring — agents venture too far and die
- [x] Removing teammate penalty (v60) — hurt freeplay
- [x] Aligner refill before explore — -29.2% regression
- [x] Scrambler heart batch 2→1 — -34.1% regression
- [x] Teammate aligner avoidance (penalty 5.0) — -11.1% self-play regression
- [x] Network bonus 0.5→2.0 — helps self-play but hurts freeplay (v90=10.19)
- [x] Expansion cap 30→40 — helps self-play but hurts freeplay (v88=9.31)
- [x] Scrambler explore offsets (mid-range 25) — hurts freeplay (v92=10.75)
- [x] Reachable-blocked scramble targeting — freeplay 10.88/10.00 (regression)
- [x] RETREAT_MARGIN=18 — freeplay 7.78 (big regression)
- [x] RETREAT_MARGIN=20 — freeplay 9.99 (regression)
- [x] enemy_aoe penalty 8.0→4.0 — reverted to be safe
- [x] Early pressure 2→3 aligners — untested/likely regression

## Testing Notes
- **ALWAYS test with 7+ seeds minimum for any signal in self-play**
- Self-play has ENORMOUS variance — not deterministic
- Self-play improvements DON'T predict freeplay improvements
- v84 base is the freeplay gold standard (17.02)
- All post-v84 changes regressed in freeplay

## Done
- [x] (ID) Scrambler hub defense bonus — self-play +11.1%, submitted v117/v118
- [x] (ID) Re-enabled shared junction memory + claims — self-play +214%, v105/v106
- [x] (ID) A/B testing RETREAT_MARGIN 18 vs 20 — v102/v103/v104
- [x] (ID) Reverted ALL post-v84 regressions — v100/v101
- [x] (ID) Reachable-blocked scramble targeting — self-play +49.0%, submitted v94/v95
- [x] (ID) Mid-range scrambler explore offsets — self-play +24.9%, submitted v92/v93
- [x] (ID) Expansion bonus cap 30→40 — self-play +16.4%, submitted v88/v89
- [x] (ID) Faster unstick 12→8 steps — variance halved, submitted v86/v87
- [x] (ID) Scramble blocked_neutrals weight 4.0→6.0 — self-play neutral, submitted v84/v85
- [x] (ID) Extractor memory 600→800 — self-play +4.1%, submitted v80/v81
- [x] (ID) Hub-proximal hotspot discount — self-play +9.6%, submitted v76/v77
- [x] (ID) Junction memory 400→800 steps — self-play +8.2%, submitted v72/v73
- [x] (ID) Network proximity bonus (weight 0.5) — self-play neutral, submitted v70/v71
- [x] (ID) Hotspot tracking — self-play +49.5%, submitted v66/v67
