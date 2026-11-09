from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

from .orchestrator import InvestigationResult

logger = logging.getLogger(__name__)


class RiskLevel(Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NEGLIGIBLE = "negligible"


class ConfidenceLevel(Enum):
    VERY_HIGH = "very_high"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    VERY_LOW = "very_low"


@dataclass
class EvidenceWeight:
    metrics_correlation: float = 0.30
    stack_trace_match: float = 0.25
    trace_analysis: float = 0.20
    commit_correlation: float = 0.15
    topology_impact: float = 0.10


@dataclass
class RiskScore:
    score: int
    level: RiskLevel
    confidence: ConfidenceLevel
    confidence_value: float
    breakdown: Dict[str, float]
    evidence_summary: List[str]
    recommendation: str


DEFAULT_WEIGHTS = EvidenceWeight()


def calculate_risk_score(investigation: InvestigationResult, weights: Optional[EvidenceWeight] = None) -> RiskScore:
    w = weights or DEFAULT_WEIGHTS
    breakdown = {}
    evidence_summary = []

    metrics_score = _score_metrics_evidence(investigation)
    breakdown["metrics_correlation"] = metrics_score * w.metrics_correlation
    if metrics_score > 0.5:
        evidence_summary.append(f"Metrics correlation: {metrics_score:.0%}")

    stack_score = _score_stack_traces(investigation)
    breakdown["stack_trace_match"] = stack_score * w.stack_trace_match
    if stack_score > 0.5:
        evidence_summary.append(f"Stack trace match: {stack_score:.0%}")

    trace_score = _score_trace_analysis(investigation)
    breakdown["trace_analysis"] = trace_score * w.trace_analysis
    if trace_score > 0.5:
        evidence_summary.append(f"Trace analysis: {trace_score:.0%}")

    commit_score = _score_commit_correlation(investigation)
    breakdown["commit_correlation"] = commit_score * w.commit_correlation
    if commit_score > 0.5:
        evidence_summary.append(f"Commit correlation: {commit_score:.0%}")

    topology_score = _score_topology_impact(investigation)
    breakdown["topology_impact"] = topology_score * w.topology_impact
    if topology_score > 0.5:
        evidence_summary.append(f"Topology impact: {topology_score:.0%}")

    raw_score = sum(breakdown.values())
    final_score = int(round(raw_score * 100))
    final_score = max(0, min(100, final_score))

    level = _score_to_level(final_score)
    confidence = _confidence_to_level(investigation.confidence)
    recommendation = _generate_recommendation(level, investigation.suggested_action, investigation.target_service)

    logger.info(f"Risk score calculated: {final_score} ({level.value}), confidence: {confidence.value} ({investigation.confidence:.2f})")

    return RiskScore(
        score=final_score,
        level=level,
        confidence=confidence,
        confidence_value=investigation.confidence,
        breakdown=breakdown,
        evidence_summary=evidence_summary,
        recommendation=recommendation,
    )


def _score_metrics_evidence(inv: InvestigationResult) -> float:
    score = 0.0
    evidence_text = " ".join(inv.evidence).lower()

    if any(kw in evidence_text for kw in ["z-score", "ewma", "threshold", "anomaly", "spike", "latency"]):
        score += 0.4
    if any(kw in evidence_text for kw in ["error rate", "5xx", "failure"]):
        score += 0.3
    if any(kw in evidence_text for kw in ["p95", "p99", "percentile"]):
        score += 0.2
    if inv.steps:
        for step in inv.steps:
            if step.tool == "query_metrics" and step.result.success:
                score += 0.1

    return min(1.0, score)


def _score_stack_traces(inv: InvestigationResult) -> float:
    score = 0.0
    evidence_text = " ".join(inv.evidence).lower()

    if any(kw in evidence_text for kw in ["stack trace", "exception", "timeout", "error", "traceback"]):
        score += 0.5
    if any(kw in evidence_text for kw in ["payment", "connection", "timeout"]):
        score += 0.3
    for step in inv.steps:
        if step.tool == "extract_stack_traces" and step.result.success:
            score += 0.2

    return min(1.0, score)


def _score_trace_analysis(inv: InvestigationResult) -> float:
    score = 0.0
    evidence_text = " ".join(inv.evidence).lower()

    if any(kw in evidence_text for kw in ["distributed trace", "span", "latency", "propagation"]):
        score += 0.4
    if any(kw in evidence_text for kw in ["error span", "failed span"]):
        score += 0.3
    for step in inv.steps:
        if step.tool == "analyze_traces" and step.result.success:
            score += 0.3

    return min(1.0, score)


def _score_commit_correlation(inv: InvestigationResult) -> float:
    score = 0.0
    evidence_text = " ".join(inv.evidence).lower()

    if any(kw in evidence_text for kw in ["commit", "regression", "deploy", "change", "recent"]):
        score += 0.5
    for step in inv.steps:
        if step.tool == "check_recent_commits" and step.result.success:
            data = step.result.data
            if data and data.get("commit_count", 0) > 0:
                score += 0.3

    return min(1.0, score)


def _score_topology_impact(inv: InvestigationResult) -> float:
    score = 0.0
    for step in inv.steps:
        if step.tool == "get_service_topology" and step.result.success:
            score += 0.5
    if "dependency" in " ".join(inv.evidence).lower():
        score += 0.3

    return min(1.0, score)


def _score_to_level(score: int) -> RiskLevel:
    if score >= 80:
        return RiskLevel.CRITICAL
    elif score >= 60:
        return RiskLevel.HIGH
    elif score >= 40:
        return RiskLevel.MEDIUM
    elif score >= 20:
        return RiskLevel.LOW
    else:
        return RiskLevel.NEGLIGIBLE


def _confidence_to_level(confidence: float) -> ConfidenceLevel:
    if confidence >= 0.9:
        return ConfidenceLevel.VERY_HIGH
    elif confidence >= 0.75:
        return ConfidenceLevel.HIGH
    elif confidence >= 0.5:
        return ConfidenceLevel.MEDIUM
    elif confidence >= 0.25:
        return ConfidenceLevel.LOW
    else:
        return ConfidenceLevel.VERY_LOW


def _generate_recommendation(level: RiskLevel, action: str, target: str) -> str:
    base = {
        RiskLevel.CRITICAL: "IMMEDIATE ACTION REQUIRED",
        RiskLevel.HIGH: "Urgent action recommended",
        RiskLevel.MEDIUM: "Action recommended within 1 hour",
        RiskLevel.LOW: "Monitor and consider action",
        RiskLevel.NEGLIGIBLE: "No immediate action needed",
    }[level]

    action_map = {
        "rollback_deployment": f"Rollback {target} deployment",
        "scale_up": f"Scale up {target} replicas",
        "restart_service": f"Restart {target} pods",
        "investigate_manually": f"Manual investigation needed for {target}",
    }

    specific = action_map.get(action, f"Execute: {action} on {target}")
    return f"{base}: {specific}"