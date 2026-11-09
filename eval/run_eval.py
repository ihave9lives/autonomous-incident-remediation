from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from engine import run_investigation, calculate_risk_score, run_full_verification


@dataclass
class GoldenScenario:
    name: str
    incident_description: str
    context: Dict
    expected_root_cause_contains: List[str]
    expected_action: str
    expected_target: str
    min_confidence: float = 0.5
    min_risk_score: int = 40


SCENARIOS = [
    GoldenScenario(
        name="payment_timeout_cascade",
        incident_description="Checkout service experiencing high latency and 5xx errors. Payment service calls timing out.",
        context={"target_service": "checkout-service"},
        expected_root_cause_contains=["payment", "timeout", "latency"],
        expected_action="rollback_deployment",
        expected_target="checkout-service",
        min_confidence=0.7,
        min_risk_score=50,
    ),
    GoldenScenario(
        name="memory_leak_checkout",
        incident_description="Checkout service memory usage growing unbounded, leading to OOM kills and restart loops.",
        context={"target_service": "checkout-service"},
        expected_root_cause_contains=["memory", "leak", "oom"],
        expected_action="restart_service",
        expected_target="checkout-service",
        min_confidence=0.6,
        min_risk_score=15,
    ),
    GoldenScenario(
        name="deployment_regression",
        incident_description="Error rate spike after recent deployment. New code introduced regression in payment integration.",
        context={"target_service": "checkout-service"},
        expected_root_cause_contains=["commit", "regression", "deploy"],
        expected_action="rollback_deployment",
        expected_target="checkout-service",
        min_confidence=0.75,
        min_risk_score=50,
    ),
    GoldenScenario(
        name="payment_service_down",
        incident_description="Payment service completely unavailable. All checkout requests failing with 502.",
        context={"target_service": "payment-service"},
        expected_root_cause_contains=["payment", "unavailable", "down"],
        expected_action="restart_service",
        expected_target="payment-service",
        min_confidence=0.8,
        min_risk_score=20,
    ),
    GoldenScenario(
        name="database_connection_pool_exhaustion",
        incident_description="Checkout service unable to acquire database connections. Connection pool exhausted.",
        context={"target_service": "checkout-service"},
        expected_root_cause_contains=["database", "connection", "pool"],
        expected_action="scale_up",
        expected_target="checkout-service",
        min_confidence=0.65,
        min_risk_score=30,
    ),
]


def run_scenario(scenario: GoldenScenario) -> Dict:
    print(f"\n{'='*60}")
    print(f"Running scenario: {scenario.name}")
    print(f"{'='*60}")

    investigation = run_investigation(scenario.incident_description, scenario.context)
    risk_score = calculate_risk_score(investigation)
    verification = run_full_verification(
        investigation_target=scenario.expected_target,
        suggested_action=scenario.expected_action,
    )

    root_cause_lower = investigation.root_cause.lower()
    evidence_text = " ".join(investigation.evidence).lower()

    root_cause_match = all(
        kw.lower() in root_cause_lower or kw.lower() in evidence_text
        for kw in scenario.expected_root_cause_contains
    )

    action_match = investigation.suggested_action == scenario.expected_action
    target_match = investigation.target_service == scenario.expected_target
    confidence_ok = investigation.confidence >= scenario.min_confidence
    risk_ok = risk_score.score >= scenario.min_risk_score

    passed = all([
        root_cause_match,
        action_match,
        target_match,
        confidence_ok,
        risk_ok,
    ])

    result = {
        "scenario": scenario.name,
        "passed": passed,
        "root_cause_match": root_cause_match,
        "action_match": action_match,
        "target_match": target_match,
        "confidence_ok": confidence_ok,
        "risk_ok": risk_ok,
        "details": {
            "root_cause": investigation.root_cause,
            "expected_keywords": scenario.expected_root_cause_contains,
            "suggested_action": investigation.suggested_action,
            "expected_action": scenario.expected_action,
            "target_service": investigation.target_service,
            "expected_target": scenario.expected_target,
            "confidence": investigation.confidence,
            "min_confidence": scenario.min_confidence,
            "risk_score": risk_score.score,
            "min_risk_score": scenario.min_risk_score,
            "verification_status": verification.overall_status.value,
        },
    }

    status = "✅ PASS" if passed else "❌ FAIL"
    print(f"{status} - {scenario.name}")
    if not passed:
        print(f"  Root cause match: {root_cause_match}")
        print(f"  Action match: {action_match}")
        print(f"  Target match: {target_match}")
        print(f"  Confidence: {investigation.confidence:.2f} (min: {scenario.min_confidence})")
        print(f"  Risk score: {risk_score.score} (min: {scenario.min_risk_score})")

    return result


def run_all_scenarios() -> Dict:
    results = []
    for scenario in SCENARIOS:
        results.append(run_scenario(scenario))

    passed = sum(1 for r in results if r["passed"])
    total = len(results)

    summary = {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": passed / total if total > 0 else 0,
        "results": results,
    }

    print(f"\n{'='*60}")
    print(f"EVAL SUMMARY: {passed}/{total} passed ({summary['pass_rate']:.0%})")
    print(f"{'='*60}")

    return summary


if __name__ == "__main__":
    summary = run_all_scenarios()
    print(json.dumps(summary, indent=2))
    exit(0 if summary["passed"] == summary["total"] else 1)