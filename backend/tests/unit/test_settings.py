"""Documented key-slot environment variables must be usable by real workers."""
import pytest
from pydantic import ValidationError

from app.settings import Settings


@pytest.mark.parametrize("slot", [0, 1, 2])
def test_role_key_slots_parse_from_environment(slot, monkeypatch):
    for role in ("ORCHESTRATOR", "EXTRACTION", "SELECTION"):
        monkeypatch.setenv(role + "_KEY_SLOT", str(slot))
    settings = Settings(_env_file=None)
    assert settings.orchestrator_key_slot == slot
    assert settings.extraction_key_slot == slot
    assert settings.selection_key_slot == slot


@pytest.mark.parametrize("value", ["3", "-1", "0.0", "invalid", True, False])
def test_key_slot_validation_does_not_coerce_unsupported_values(value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, extraction_key_slot=value)
