"""CvC PolicyCoglet: CodeLet with LLM brain + Python fast policy.

The submitted policy is a CodeLet:
- Fast path: AlphaCogAgentPolicy (Python heuristic) handles every step
- Slow path: LLM analyzes game state periodically, can rewrite the
  macro_directive or pressure_budgets to improve strategy mid-game

PlayerCoglet (GitLet) manages this across many games, committing
improvements to the repo.
"""
from __future__ import annotations

from typing import Any

from cvc.policy.anthropic_pilot import AlphaCyborgPolicy, AlphaCogAgentPolicy
from cvc.policy.semantic_cog import (
    MettagridSemanticPolicy,
    SemanticCogAgentPolicy,
    SharedWorldModel,
)
from mettagrid.policy.policy import AgentPolicy
from mettagrid.policy.policy_env_interface import PolicyEnvInterface


class CogletPolicy(AlphaCyborgPolicy):
    """CodeLet policy: Python heuristic (fast) + LLM improvement (slow).

    This is what gets submitted to cogames. Each agent runs
    AlphaCogAgentPolicy for fast per-step decisions. The LLM
    brain is layered on by PlayerCoglet via the coglet COG/LET
    architecture.
    """
    short_names = ["coglet", "coglet-policy"]
