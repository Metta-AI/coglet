# Session 47 Log

**Timestamp**: 2026-04-01 02:45:00
**Approach**: IntelligentDesign

## Status: DONE (no improvement)

No code changes this session. Both ideas regressed.

## Changes Attempted

### 1. Aligner refill before explore (REVERTED)
When aligner has no junction target and hearts < batch_target, go to hub to refill before exploring.
- Result: **-29.2%** regression (1.67→1.18). Aligners go to hub too often instead of discovering junctions.
- Reverted immediately. Dead end.

## Dead Ends
- Aligner refill before explore: causes aligners to waste time at hub instead of discovering new junctions
- Scrambler batch 2→1 (session 46): wastes hearts, disrupts economy
