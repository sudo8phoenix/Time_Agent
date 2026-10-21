"""Safety and failure-output contracts for the bounded admission probe."""
import pytest

from evaluation.probe_hosted_admission_soak import (
    exception_type,
    open_exclusive,
    summarize_ms,
    validate_target,
)


def test_target_guard_allows_only_local_progress_test():
    assert validate_target(
        "postgresql+psycopg://user:secret@127.0.0.1/progress_test"
    ).database == "progress_test"
    for url in (
        "postgresql+psycopg://user:secret@127.0.0.1/progress",
        "postgresql+psycopg://user:secret@example.test/progress_test",
        "sqlite:///progress_test",
    ):
        with pytest.raises(ValueError):
            validate_target(url)


def test_exclusive_output_never_truncates_existing_evidence(tmp_path):
    path = tmp_path / "nested" / "evidence.json"
    with open_exclusive(path) as stream:
        stream.write("original")
    with pytest.raises(FileExistsError):
        open_exclusive(path)
    assert path.read_text() == "original"


def test_empty_samples_and_exception_messages_are_safe():
    assert summarize_ms([]) == {"count": 0, "p50": None, "p95": None, "max": None}
    secret = "postgresql://user:password@host/db"
    error = RuntimeError(secret)
    assert exception_type(error) == "RuntimeError"
    assert secret not in exception_type(error)
