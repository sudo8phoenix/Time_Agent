"""Precision-preserving contract for the explicitly local prototype connector."""
from typing import Protocol

LABEL = "MOCK PMIS — prototype"


class PermanentDeliveryError(Exception):
    pass


class Connector(Protocol):
    def deliver(self, payload: dict) -> dict: ...
