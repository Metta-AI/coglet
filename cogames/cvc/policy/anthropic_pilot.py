"""Alpha policy: optimized semantic heuristic for CvC.

AlphaCogAgentPolicy extends SemanticCogAgentPolicy with:
- Resource-aware macro directives (mine least-available resource)
- Phase-based pressure budgets (aligner/scrambler allocation over time)
- Miner safety retreat logic
"""
from __future__ import annotations

from mettagrid_sdk.sdk import MacroDirective, MettagridState

from cvc.policy import helpers as _h
from cvc.policy.helpers.types import KnownEntity
from cvc.policy.semantic_cog import (
    MettagridSemanticPolicy,
    SemanticCogAgentPolicy,
    SharedWorldModel,
)
from mettagrid.policy.policy import AgentPolicy
from mettagrid.policy.policy_env_interface import PolicyEnvInterface

_ELEMENTS = ("carbon", "oxygen", "germanium", "silicon")
_MINER_MAX_HUB_DISTANCE = 15


def _shared_resources(state: MettagridState) -> dict[str, int]:
    if state.team_summary is None:
        return {r: 0 for r in _ELEMENTS}
    return {r: int(state.team_summary.shared_inventory.get(r, 0)) for r in _ELEMENTS}


def _least_resource(resources: dict[str, int]) -> str:
    return min(_ELEMENTS, key=lambda r: resources[r])


class AlphaCogAgentPolicy(SemanticCogAgentPolicy):
    """Optimized agent policy: aggressive alignment with scrambler defense."""

    def _macro_directive(self, state: MettagridState) -> MacroDirective:
        resources = _shared_resources(state)
        least = _least_resource(resources)
        return MacroDirective(resource_bias=least)

    def _pressure_budgets(self, state: MettagridState, *, objective: str | None = None) -> tuple[int, int]:
        step = state.step or self._step_index
        if step < 10:
            return 2, 0
        if step < 300:
            return 5, 0
        if objective == "resource_coverage":
            return 0, 0
        if objective == "economy_bootstrap":
            return 2, 0
        return 4, 1

    def _should_retreat(self, state: MettagridState, role: str, safe_target: KnownEntity | None) -> bool:
        if super()._should_retreat(state, role, safe_target):
            return True
        if role == "miner" and safe_target is not None:
            pos = _h.absolute_position(state)
            dist = _h.manhattan(pos, safe_target.position)
            hp = int(state.self_state.inventory.get("hp", 0))
            if dist > _MINER_MAX_HUB_DISTANCE and hp < dist + 10:
                return True
        return False


class AlphaCyborgPolicy(MettagridSemanticPolicy):
    """Semantic heuristic policy — no LLM dependencies."""
    short_names: list[str] | None = None

    def agent_policy(self, agent_id: int) -> AgentPolicy:
        if agent_id not in self._agent_policies:
            self._agent_policies[agent_id] = AlphaCogAgentPolicy(
                self.policy_env_info,
                agent_id=agent_id,
                world_model=SharedWorldModel(),
                shared_claims=self._shared_claims,
                shared_junctions=self._shared_junctions,
            )
        return self._agent_policies[agent_id]
