"""Registered agent roles and the only legal delegation edges."""
from __future__ import annotations

from dataclasses import dataclass

from .contracts import AgentRole, TaskEnvelope


@dataclass(frozen=True)
class RoleSpec:
    role: AgentRole
    allowed_children: frozenset[AgentRole]
    max_children: int
    specialist: bool


ROLE_REGISTRY: dict[AgentRole, RoleSpec] = {
    AgentRole.ROOT: RoleSpec(AgentRole.ROOT, frozenset({AgentRole.INTAKE, AgentRole.ANALYSIS, AgentRole.REVIEW}), 3, False),
    AgentRole.INTAKE: RoleSpec(AgentRole.INTAKE, frozenset({AgentRole.CLARIFICATION}), 1, False),
    AgentRole.ANALYSIS: RoleSpec(AgentRole.ANALYSIS, frozenset({AgentRole.EXTRACTION, AgentRole.MATCHING, AgentRole.EVIDENCE}), 406, False),
    AgentRole.REVIEW: RoleSpec(AgentRole.REVIEW, frozenset(), 0, False),
    AgentRole.CLARIFICATION: RoleSpec(AgentRole.CLARIFICATION, frozenset(), 0, True),
    AgentRole.EXTRACTION: RoleSpec(AgentRole.EXTRACTION, frozenset(), 0, True),
    AgentRole.MATCHING: RoleSpec(AgentRole.MATCHING, frozenset({AgentRole.SELECTION}), 400, False),
    AgentRole.EVIDENCE: RoleSpec(AgentRole.EVIDENCE, frozenset(), 0, True),
    AgentRole.SELECTION: RoleSpec(AgentRole.SELECTION, frozenset(), 0, True),
}


class DelegationError(ValueError):
    """A role is unknown, unregistered, or has an illegal parent/child edge."""


def get_role(role: AgentRole | str) -> RoleSpec:
    try:
        return ROLE_REGISTRY[AgentRole(role)]
    except (ValueError, KeyError) as exc:
        raise DelegationError(f"unregistered agent role: {role}") from exc


def validate_child(parent: TaskEnvelope, child: TaskEnvelope) -> None:
    spec = get_role(parent.agent_role)
    if child.parent_task_id != parent.task_id:
        raise DelegationError("child parent_task_id does not identify the parent")
    if child.agent_role not in spec.allowed_children:
        raise DelegationError(f"{parent.agent_role.value} cannot delegate to {child.agent_role.value}")
    if child.run_id != parent.run_id:
        raise DelegationError("child run_id differs from parent")
    if (child.project_id, child.source_id, child.schedule_version_id) != (
        parent.project_id, parent.source_id, parent.schedule_version_id
    ):
        raise DelegationError("child changed pinned project, source, or schedule scope")
    if child.task_id == parent.task_id:
        raise DelegationError("child task identity must differ from parent")
