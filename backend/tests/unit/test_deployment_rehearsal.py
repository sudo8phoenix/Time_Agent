"""The real-worker rehearsal must never target the application or a remote DB."""
import pytest

from evaluation.deployment_rehearsal import _validate_target


@pytest.mark.parametrize("url", [
    "postgresql+psycopg://progress:progress@127.0.0.1:5432/progress",
    "postgresql+psycopg://progress:progress@127.0.0.1:5432/progress_test",
    "postgresql+psycopg://progress:progress@remote.example/progress_rehearsal_safe",
    "sqlite:///progress_rehearsal_safe",
    "not a database URL",
])
def test_rehearsal_rejects_non_isolated_target_before_any_connection(url):
    with pytest.raises(ValueError):
        _validate_target(url)


def test_rehearsal_accepts_only_named_local_namespace():
    _validate_target("postgresql+psycopg://progress:progress@127.0.0.1:5432/progress_rehearsal_release")
