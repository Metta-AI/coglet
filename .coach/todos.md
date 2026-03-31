# Coach TODO

## Current Priorities
- [ ] Monitor beta:v46 freeplay and beta:v47 tournament advancement
- [ ] Fix junction cascade: team loses 5→1 junctions between step 500-2000
- [ ] Improve exploration coverage — agents only discover ~20/65 junctions
- [ ] Run PCO epoch with recent game learnings to evolve program table

## Key Findings (Session 38)
- SDK constants differ from IMPROVE.md docs: ALIGN_DIST=15 (not 3), AOE=10 (not 4)
- In `cogames run -c 16` (mixed teams), both policies get SAME score — confirms mixed-team format
- Self-play baseline: avg 2.39 across 7 seeds (42-48)
- Junction cascade: team holds 5 at step 500, drops to 1 by step 2000, never recovers
- Only ~20/65 junctions discovered per game — exploration is the bottleneck
- All parameter changes tested (9 experiments) regressed or matched baseline

## Improvement Ideas
- [ ] Better exploration patterns — current 8 offsets at distance 22 leave 2/3 of map undiscovered
- [ ] Periodic forced exploration even when targets exist — break out of local target cycling
- [ ] PCO evolution — let LLM propose program patches based on game experience
- [ ] Read teammate vibes for coordination (beyond position-based)
- [ ] Map topology analysis — understand wall patterns to improve exploration
- [ ] LLM brain integration — use analyze prompt for stagnation detection (like alpha.0)

## Dead Ends (Don't Retry)
- [x] Retreat threshold tuning — always trades deaths for score regression
- [x] Heart batch target changes — 3 for aligners is the sweet spot
- [x] Outer explore ring at manhattan 35 — sends agents too far, they die
- [x] Remove alignment network filter — required by game mechanics
- [x] Expand alignment range +5 — causes targeting unreachable junctions
- [x] Remove scramblers entirely (SCRIMMAGE only) — confirmed twice in self-play, scramblers help
- [x] Resource-aware pressure budgets — too aggressive scaling, avg 1.68 vs 2.39
- [x] Spread miner resource bias — least-available targeting is better
- [x] Reorder aligner explore offsets — existing order works better
- [x] Increase claim penalty (12→25) — pushes aligners to suboptimal targets
- [x] More aligners (6) / fewer miners (2) — economy can't sustain
- [x] Wider A* margin (12→20) — slower computation wastes ticks
- [x] Emergency mining threshold 50 or 10 — hurts high-scoring seeds more than helps low ones
- [x] Wider enemy AOE radius 15 for retreat — agents retreat too much, avg 1.83 vs 2.10
- [x] Delay scramblers to step 500 — avg 0.99 vs 2.10, opponent builds unchallenged
- [x] Junction memory 600→2000 — stale data causes avg drop from 2.39 to 3.05 (high variance)
- [x] Late-game pressure ramp (5 aligners after 5000) — avg 2.61 vs 2.39
- [x] Earlier scrambler (step 100) + 2 late scramblers — avg 2.00 vs 2.39
- [x] More miners (4 vs 3) — avg 1.76 vs 2.39
- [x] 5 aligners from step 0 — avg 1.63 vs 2.39, economy starved
- [x] Reduce hotspot penalty (3*3 vs 5*8) — avg 1.35, agents waste hearts on contested junctions
- [x] Improve scrambler defense (hub_threat+15 threat bonus) — avg 1.77 vs 2.39
- [x] Adaptive role promotion (miners→aligners when team has surplus) — avg 1.48, destabilizes self-play

## Testing Notes
- **ALWAYS test across 7 seeds (42-48) for reliable averages**
- Scrimmage (`-c 8`): self-play, one policy controls all 8 agents per team
- `cogames run -c 16 -p A -p B`: mixed teams, both policies distributed across teams
- Freeplay uses mixed-team format — agents from different policies on same team

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
- [x] Session 36: teammate-aware aligner targeting (+30% avg self-play), submitted v26/v27
- [x] Session 37 (ID): Fix double role-adjustment + wider enemy retreat + junction memory 400→600 (+11% self-play, v30/v31)
- [x] Session 38: Deep analysis — 9 parameter experiments, all regress. Identified junction cascade + exploration bottleneck. Submitted v46/v47.
