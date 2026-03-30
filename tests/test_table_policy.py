"""Tests for TablePolicy program-table-driven CvC policy adapter.

Basic construction/structure tests — we can't run cogames without the full
environment, so these verify imports, program table wiring, and dataclass
defaults.
"""
from __future__ import annotations

from cvc.programs import all_programs, seed_programs
from cvc.table_policy import TableAgentState, TablePolicy, TablePolicyImpl

from coglet.proglet import Program


# ---------------------------------------------------------------------------
# TableAgentState
# ---------------------------------------------------------------------------

def test_table_agent_state_defaults():
    """TableAgentState initializes with sane defaults."""
    state = TableAgentState()
    assert state.game_state is None
    assert state.last_llm_step == 0
    assert state.llm_interval == 500
    assert state.llm_latencies == []
    assert state.resource_bias_from_llm is None
    assert state.llm_log == []
    assert state.snapshot_log == []
    assert state.last_snapshot_step == 0
    assert state.experience == []


# ---------------------------------------------------------------------------
# all_programs integration
# ---------------------------------------------------------------------------

def test_all_programs_has_step():
    """all_programs() includes the 'step' program needed by TablePolicyImpl."""
    programs = all_programs()
    assert "step" in programs
    step = programs["step"]
    assert step.executor == "code"
    assert step.fn is not None
    assert callable(step.fn)


def test_seed_programs_has_required_keys():
    """seed_programs() returns all programs needed by TablePolicyImpl."""
    programs = seed_programs()
    required = {"step", "hold", "retreat", "mine", "align", "scramble",
                "explore", "summarize", "analyze", "desired_role"}
    assert required.issubset(programs.keys())


def test_seed_programs_analyze_is_llm():
    """The 'analyze' program is an LLM program with parser."""
    programs = seed_programs()
    analyze = programs["analyze"]
    assert analyze.executor == "llm"
    assert analyze.parser is not None
    assert callable(analyze.parser)


# ---------------------------------------------------------------------------
# TablePolicyImpl._invoke_sync
# ---------------------------------------------------------------------------

def test_invoke_sync_calls_code_program():
    """_invoke_sync dispatches to fn for code programs."""
    called_with = []

    def fake_fn(gs):
        called_with.append(gs)
        return ("action", "summary")

    programs = {"test_prog": Program(executor="code", fn=fake_fn)}

    # We only need _programs for _invoke_sync — no policy_env_info needed
    impl = TablePolicyImpl.__new__(TablePolicyImpl)
    impl._programs = programs

    result = impl._invoke_sync("test_prog", "fake_gs")
    assert result == ("action", "summary")
    assert called_with == ["fake_gs"]


def test_invoke_sync_rejects_llm():
    """_invoke_sync raises ValueError for non-code programs."""
    programs = {"llm_prog": Program(executor="llm")}
    impl = TablePolicyImpl.__new__(TablePolicyImpl)
    impl._programs = programs

    import pytest
    with pytest.raises(ValueError, match="Cannot sync-invoke"):
        impl._invoke_sync("llm_prog", None)


# ---------------------------------------------------------------------------
# TablePolicy class attributes
# ---------------------------------------------------------------------------

def test_table_policy_short_names():
    """TablePolicy registers with expected short names."""
    assert TablePolicy.short_names == ["coglet-table", "table-policy"]


def test_table_policy_minimum_timeout():
    """TablePolicy sets minimum action timeout for LLM calls."""
    assert TablePolicy.minimum_action_timeout_ms == 30_000


# ---------------------------------------------------------------------------
# _adapt_interval
# ---------------------------------------------------------------------------

def test_adapt_interval_decreases_on_fast_latency():
    """LLM interval decreases when latency is low."""
    state = TableAgentState(llm_latencies=[500.0, 600.0, 700.0])
    impl = TablePolicyImpl.__new__(TablePolicyImpl)
    impl._adapt_interval(state)
    assert state.llm_interval < 500


def test_adapt_interval_increases_on_slow_latency():
    """LLM interval increases when latency is high."""
    state = TableAgentState(llm_latencies=[6000.0, 7000.0, 8000.0])
    impl = TablePolicyImpl.__new__(TablePolicyImpl)
    impl._adapt_interval(state)
    assert state.llm_interval > 500


def test_adapt_interval_noop_when_empty():
    """_adapt_interval does nothing with no latency data."""
    state = TableAgentState()
    impl = TablePolicyImpl.__new__(TablePolicyImpl)
    impl._adapt_interval(state)
    assert state.llm_interval == 500
