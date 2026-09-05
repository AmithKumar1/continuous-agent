import pytest
from benchmark_efficacy import (
    generate_falkenauer_u120,
    generate_weibull_suite,
    evaluate_algorithm,
    next_fit,
    best_fit,
    run_empirical_benchmark
)

def test_falkenauer_generator_dimensions():
    suite = generate_falkenauer_u120(num_instances=4, items_per_instance=50)
    assert len(suite) == 4
    assert len(suite[0]) == 50
    for seq in suite:
        for val in seq:
            assert 20.0 <= val <= 100.0

def test_weibull_generator_dimensions():
    suite = generate_weibull_suite(num_instances=3, items_per_instance=40)
    assert len(suite) == 3
    assert len(suite[0]) == 40
    for seq in suite:
        for val in seq:
            assert val > 0.0

def test_baseline_hierarchy():
    suite = generate_falkenauer_u120(num_instances=5, items_per_instance=60)
    res_nf = evaluate_algorithm("NF", next_fit, suite, "Falkenauer", is_next_fit=True)
    res_bf = evaluate_algorithm("BF", best_fit, suite, "Falkenauer", is_next_fit=False)

    # Next Fit must use more bins than Best Fit
    assert res_nf.total_bins_used > res_bf.total_bins_used
    assert res_bf.average_utilization > res_nf.average_utilization

def test_run_empirical_benchmark_full():
    results = run_empirical_benchmark()
    assert len(results) == 8  # 4 candidates x 2 benchmark sets
    for r in results:
        assert r.total_bins_used > 0
        assert r.average_utilization > 50.0
