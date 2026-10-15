"""Run-wide budget reservation shared by every task and retry."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Callable, Mapping


class BudgetExceeded(RuntimeError):
    def __init__(self, counter: str, limit: int):
        self.counter = counter
        self.limit = limit
        super().__init__(f"run budget exhausted for {counter} (limit {limit})")


@dataclass(frozen=True)
class BudgetLimits:
    supervisor_transitions: int = 12
    model_calls: int = 404
    tool_calls: int = 1200

    def __post_init__(self) -> None:
        if any(value < 0 for value in self.as_dict().values()):
            raise ValueError("budget limits must be non-negative")

    def as_dict(self) -> dict[str, int]:
        return {
            "supervisor_transitions": self.supervisor_transitions,
            "model_calls": self.model_calls,
            "tool_calls": self.tool_calls,
        }


@dataclass
class RootBudget:
    """A single counter set owned by the root run, never copied to children.

    Call ``reserve`` before invoking a model or tool. Reservation is consumed
    even when the external call fails, so retries share the same allowance.
    """

    limits: BudgetLimits = field(default_factory=BudgetLimits)
    used: dict[str, int] = field(default_factory=dict)
    deadline: datetime | None = None
    reservation_hook: Callable[[str, int], int | None] | None = field(default=None, repr=False, compare=False)
    _lock: Lock = field(default_factory=Lock, repr=False, compare=False)

    def __post_init__(self) -> None:
        unknown = set(self.used) - set(self.limits.as_dict())
        if unknown or any(value < 0 for value in self.used.values()):
            raise ValueError("used counters must be known and non-negative")
        self.used = {key: int(self.used.get(key, 0)) for key in self.limits.as_dict()}

    def reserve(self, counter: str, amount: int = 1) -> int:
        if amount <= 0:
            raise ValueError("reservation amount must be positive")
        with self._lock:
            limits = self.limits.as_dict()
            if counter not in limits:
                raise ValueError(f"unknown budget counter: {counter}")
            if self.deadline is not None and datetime.now(timezone.utc) >= self.deadline:
                raise BudgetExceeded("deadline", 0)
            if self.used[counter] + amount > limits[counter]:
                raise BudgetExceeded(counter, limits[counter])
            # A durable hook is called before local work starts. It must commit
            # the reservation or raise, so failed downstream calls still count.
            persisted = self.reservation_hook(counter, amount) if self.reservation_hook else None
            self.used[counter] = persisted if persisted is not None else self.used[counter] + amount
            return self.used[counter]

    def reserve_model_call(self) -> int:
        return self.reserve("model_calls")

    def reserve_tool_call(self) -> int:
        return self.reserve("tool_calls")

    def reserve_transition(self) -> int:
        return self.reserve("supervisor_transitions")

    def snapshot(self) -> dict[str, dict[str, int]]:
        with self._lock:
            return {"used": dict(self.used), "limits": self.limits.as_dict()}

    def apply_usage(self, usage: Mapping[str, int]) -> None:
        """Charge already-executed work reported by a resumed child task."""
        for counter, amount in usage.items():
            self.reserve(counter, amount)
