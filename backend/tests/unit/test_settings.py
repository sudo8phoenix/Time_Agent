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


@pytest.mark.parametrize("secret", [
    "development-only-change-me",
    "replace-with-a-random-value-at-least-16-characters",
    "short-production-secret",
])
def test_production_rejects_default_placeholder_and_short_secrets(secret):
    with pytest.raises(ValidationError, match="Production requires"):
        Settings(_env_file=None, environment="production", secret_key=secret)


@pytest.mark.parametrize("environment, override, expected", [
    ("production", None, False),
    ("development", None, True),
    ("test", None, True),
    ("production", True, True),
    ("development", False, False),
])
def test_registration_policy(environment, override, expected):
    settings = Settings(
        _env_file=None, environment=environment,
        secret_key="test-only-production-secret-with-32-characters",
        registration_enabled=override,
    )
    assert settings.public_registration_enabled is expected
