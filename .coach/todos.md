# Coach TODO

## Current Priorities
- [ ] Wait for v25 tournament results (no scramblers should improve cooperative scoring)
- [ ] Test with 1v1 mode (`cogames run -c 16 -p A -p B`) going forward, not just scrimmage
- [ ] Investigate why seed 44 frequently collapses to 0.00 — map topology issue?

## Improvement Ideas
- [ ] Map topology analysis — understand wall patterns to improve exploration
- [ ] Dynamic role switching — let agents switch roles based on game state
- [ ] LLM brain integration — use analyze prompt for real-time strategic adaptation
- [ ] PCO evolution — run PCO epochs to evolve program table (need ANTHROPIC_API_KEY)
- [ ] Better junction discovery — agents may miss junctions behind walls
- [ ] Tune early game: start aligners sooner (step 0 instead of step 30?)
- [ ] Add defensive re-alignment — prioritize recapturing recently-scrambled friendly junctions

## Dead Ends (Don't Retry)
- [x] Retreat threshold tuning — always trades deaths for score regression
- [x] Heart batch target changes — 3 for aligners is the sweet spot
- [x] Outer explore ring at manhattan 35 — sends agents too far, they die
- [x] Remove alignment network filter — required by game mechanics
- [x] Expand alignment range +5 — causes targeting unreachable junctions
- [x] Resource-aware pressure budgets — too aggressive scaling
- [x] Spread miner resource bias — least-available targeting is better
- [x] Reorder aligner explore offsets — existing order works better
- [x] Increase claim penalty (12→25) — pushes aligners to suboptimal targets
- [x] More aligners (6) / fewer miners (2) — economy can't sustain
- [x] Wider A* margin (12→20) — slower computation wastes ticks
- [x] Emergency mining threshold 50 or 10 — hurts high-scoring seeds more than helps low ones
- [x] Hotspot tracking (scramble history + penalty 8.0) — agents avoid most valuable contested junctions
- [x] Wider enemy AOE for retreat (radius 10 or 20) — over-retreating wastes ticks, seed collapses
- [x] Revert to hub-only scoring (remove network_dist) — chain-aware scoring IS helping

## Testing Notes
- **ALWAYS test 1v1 with `cogames run -c 16 -p A -p B`** not just scrimmage
- Scrimmage (`-c 8`) is self-play where one policy controls all agents — inflated scores
- Previous "remove scramblers" test was scrimmage only — retested in 1v1 and confirmed improvement
- Seed 44 is unreliable (frequently collapses to 0.00) — include but don't base decisions on it alone

## Done
- [x] Establish baseline: 1.31 on machina_1 (seed 42)
- [x] Remove LLM resource herding: 1.31 → 1.72
- [x] Full ProgLet policy (GameState wraps engine): 1.76
- [x] PCO pipeline validated (learner proposes patches)
- [x] Session 5: tested retreat/budget/heart tuning — no improvement found
- [x] Session 6: fixed 4-agent role allocation (0.00 → ~0.95), submitted v13
- [x] Session 7: fixed coglet imports for tournament bundle, limited emergency mining
- [x] Session 8: shared junction memory + wider exploration (0.95 → 1.65 avg, v16)
- [x] Session 9: fixed role misassignment bug (1.65 → 6.18 avg, v17)
- [x] Session 10: chain-aware junction scoring (6.18 → 8.74 avg, v18)
- [x] Session 11: exhaustive parameter search — no improvement found, v18 is well-tuned
- [x] Session 12: emergency mining threshold tests — no improvement found
- [x] Session 13: CRITICAL FIX — agent_id normalization (% 8) for tournament mode (1v1 avg 18.38, v19)
- [x] Session 36: removed scramblers for cooperative scoring (+10% 1v1, +12% scrimmage, v25)
