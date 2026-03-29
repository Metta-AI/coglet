"""Integration test: full PCO epoch pipeline with CvC components."""

import pytest

from cvc.pco_runner import run_pco_epoch
from cvc.programs import seed_programs


@pytest.mark.asyncio
async def test_full_pco_epoch_computes_signals():
    """Full PCO epoch: experience -> critic -> losses -> learner -> constraints."""
    experience = [
        {
            "step": 500,
            "hp": 80,
            "hearts": 2,
            "resources": {"carbon": 10, "oxygen": 5, "germanium": 3, "silicon": 2},
            "junctions": {"friendly": 3, "enemy": 1, "neutral": 2},
            "roles": {"miner": 4, "aligner": 2, "scrambler": 1, "scout": 1},
            "role": "miner",
        },
        {
            "step": 1000,
            "hp": 60,
            "hearts": 1,
            "resources": {"carbon": 25, "oxygen": 15, "germanium": 10, "silicon": 8},
            "junctions": {"friendly": 5, "enemy": 2, "neutral": 1},
            "roles": {"miner": 3, "aligner": 3, "scrambler": 1, "scout": 1},
            "role": "aligner",
        },
    ]
    result = await run_pco_epoch(
        experience=experience,
        programs=seed_programs(),
        client=None,
    )
    assert "accepted" in result
    assert "signals" in result
    assert len(result["signals"]) == 3

    signal_names = {s["name"] for s in result["signals"]}
    assert signal_names == {"resource", "junction", "survival"}

    # Resource loss: total_resources = (10+5+3+2)+(25+15+10+8) = 78
    # loss = max(0, 100 - 78) = 22
    resource_signal = next(s for s in result["signals"] if s["name"] == "resource")
    assert resource_signal["magnitude"] == 22

    # Junction loss: junction_control = (3-1)+(5-2) = 5, loss = max(0, -5) = 0
    junction_signal = next(s for s in result["signals"] if s["name"] == "junction")
    assert junction_signal["magnitude"] == 0

    # Survival: no deaths (hp > 0 in both snapshots)
    survival_signal = next(s for s in result["signals"] if s["name"] == "survival")
    assert survival_signal["magnitude"] == 0

    # With client=None, learner returns empty patch -> constraints accept
    assert result["accepted"] is True
    assert result["patch"] == {}
