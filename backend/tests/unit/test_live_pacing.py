import json

import pytest

from evaluation.live_pacing import wait_before_case


class Clock:
    value = 0

    def now(self):
        return self.value

    def sleep(self, seconds):
        assert 0 < seconds <= 5
        self.value += seconds


def test_live_pacing_waits_for_cooldown_even_inside_a_group(tmp_path):
    clock = Clock()
    waited = wait_before_case(tmp_path, 'B', 1, cooldown=lambda: max(0, 12 - clock.now()),
        clock=clock.now, sleep=clock.sleep)
    assert waited == 12
    row = json.loads((tmp_path/'pacing.jsonl').read_text())
    assert row['pre_submission_wait_seconds'] == 12
    assert row['excluded_from_per_report_readiness'] is True


def test_live_pacing_uses_the_longer_of_batch_pause_and_provider_cooldown(tmp_path):
    clock = Clock()
    waited = wait_before_case(tmp_path, 'F', 5, cooldown=lambda: max(0, 90 - clock.now()),
        clock=clock.now, sleep=clock.sleep)
    assert waited == 90


def test_live_pacing_pauses_between_groups_of_five(tmp_path):
    clock = Clock()
    for index in range(6):
        wait_before_case(tmp_path, str(index), index, cooldown=lambda: 0,
            clock=clock.now, sleep=clock.sleep)
    rows = [json.loads(line) for line in (tmp_path/'pacing.jsonl').read_text().splitlines()]
    assert [row['pre_submission_wait_seconds'] for row in rows] == [0, 0, 0, 0, 0, 60]


def test_live_pacing_fails_closed_if_the_wait_cannot_fit_its_budget(tmp_path):
    clock = Clock()
    with pytest.raises(RuntimeError, match='wait budget exceeded'):
        wait_before_case(tmp_path, 'A', 0, cooldown=lambda: 100, max_wait_seconds=90,
            clock=clock.now, sleep=clock.sleep)
    assert clock.value == 0


@pytest.mark.parametrize('batch_size', [0, 6])
def test_live_pacing_rejects_groups_larger_than_the_authorized_limit(tmp_path, batch_size):
    with pytest.raises(ValueError, match='at most five'):
        wait_before_case(tmp_path, 'A', 0, batch_size=batch_size)
