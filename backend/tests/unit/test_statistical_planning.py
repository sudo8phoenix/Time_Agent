import pytest

from evaluation.statistical_planning import planning_report, zero_error_plan


@pytest.mark.parametrize(('rate', 'expected'), [(0.02, 149), (0.01, 299), (0.001, 2995)])
def test_exact_zero_error_plan_is_minimal_at_declared_one_sided_confidence(rate, expected):
    plan = zero_error_plan(rate)
    n = plan['independent_trials_required']
    assert n == expected
    # Direct binomial tail checks, independently of the inverse formula.
    assert (1-rate)**n <= 0.05
    assert (1-rate)**(n-1) > 0.05
    assert plan['exact_one_sided_upper_error_bound'] <= rate


@pytest.mark.parametrize('bad', [0, 1, -0.1, float('nan'), float('inf'), True, '0.02'])
def test_invalid_rates_or_confidence_cannot_produce_a_sample_plan(bad):
    with pytest.raises(ValueError):
        zero_error_plan(bad)
    with pytest.raises(ValueError):
        zero_error_plan(0.02, alpha=bad)


def test_unrepresentable_sample_size_fails_with_a_clear_validation_error():
    with pytest.raises(ValueError, match='numerical precision'):
        zero_error_plan(5e-324)


def test_smoke_samples_do_not_establish_high_precision_or_zero_population_risk():
    report = planning_report()
    assert report['link_precision_98_percent_zero_error']['independent_trials_required'] > 6
    assert report['release_accepted'] is False
    assert any('finite sample never proves' in row for row in report['requirements'])
