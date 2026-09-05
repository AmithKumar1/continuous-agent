import os
import yaml
import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def test_prometheus_alerts_yaml_validity():
    alert_path = os.path.join(REPO_ROOT, "deploy", "prometheus-alerts.yml")
    assert os.path.exists(alert_path), "deploy/prometheus-alerts.yml must exist"
    
    with open(alert_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    assert "groups" in data, "Alert YAML must contain 'groups'"
    groups = data["groups"]
    assert len(groups) > 0, "At least one alert group required"

    rules = groups[0].get("rules", [])
    assert len(rules) >= 7, "Must contain all specified alert rules"

    rule_names = {r["alert"] for r in rules if "alert" in r}
    expected_rules = {
        "IslandPhenotypicEntropyCollapse",
        "IslandPhenotypicEntropyCritical",
        "IslandProlongedFitnessPlateau",
        "HighLean4ProofFailureRate",
        "Lean4KernelCrashSpike",
        "Z3ContractRefutationSurge",
        "ASTMemoizationCacheDegraded",
        "ContinuousAgentDown",
    }
    assert expected_rules.issubset(rule_names), f"Missing rules: {expected_rules - rule_names}"

    for r in rules:
        if "alert" in r:
            assert "expr" in r, f"Rule {r['alert']} missing 'expr'"
            assert "labels" in r, f"Rule {r['alert']} missing 'labels'"
            assert "annotations" in r, f"Rule {r['alert']} missing 'annotations'"
            assert "summary" in r["annotations"], f"Rule {r['alert']} missing annotation 'summary'"
            assert "description" in r["annotations"], f"Rule {r['alert']} missing annotation 'description'"

def test_test_prometheus_alerts_yaml_validity():
    test_yaml_path = os.path.join(REPO_ROOT, "tests", "test_prometheus_alerts.yml")
    assert os.path.exists(test_yaml_path), "tests/test_prometheus_alerts.yml must exist"
    
    with open(test_yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    assert "rule_files" in data, "Test YAML must contain 'rule_files'"
    assert "tests" in data, "Test YAML must contain 'tests'"
    assert len(data["tests"]) >= 3, "Must have at least 3 alert test cases"
