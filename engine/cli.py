#!/usr/bin/env python3
"""
Autonomous Incident Remediation Agent - CLI Entry Point
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import uuid
from datetime import datetime

from engine import (
    run_investigation,
    calculate_risk_score,
    run_full_verification,
    create_incident_runbook,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Autonomous Incident Remediation Agent")
    parser.add_argument("incident", help="Incident description")
    parser.add_argument("--context", help="JSON context for investigation")
    parser.add_argument("--target", default="checkout-service", help="Target service")
    parser.add_argument("--action", default="rollback_deployment", help="Suggested action")
    parser.add_argument("--commit", help="Commit hash for git revert verification")
    parser.add_argument("--namespace", default="default", help="Kubernetes namespace")
    parser.add_argument("--repo", default=".", help="Repository path")
    parser.add_argument("--output", help="Output runbook path")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of markdown")

    args = parser.parse_args()

    context = json.loads(args.context) if args.context else {}
    context.setdefault("target_service", args.target)

    logger.info(f"Starting investigation for: {args.incident}")

    investigation = run_investigation(args.incident, context)

    logger.info(f"Investigation complete: {investigation.root_cause}")
    logger.info(f"Confidence: {investigation.confidence:.2f}")
    logger.info(f"Suggested action: {investigation.suggested_action}")

    risk_score = calculate_risk_score(investigation)
    logger.info(f"Risk score: {risk_score.score}/100 ({risk_score.level.value})")

    verification = run_full_verification(
        investigation_target=args.target,
        suggested_action=args.action,
        commit_hash=args.commit,
        namespace=args.namespace,
        repo_path=args.repo,
    )
    logger.info(f"Verification: {verification.overall_status.value}")

    incident_id = f"INC-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    runbook = create_incident_runbook(
        incident_id=incident_id,
        title=args.incident[:80],
        investigation=investigation,
        risk_score=risk_score,
        verification=verification,
        output_path=args.output,
    )

    if args.json:
        output = {
            "incident_id": incident_id,
            "root_cause": investigation.root_cause,
            "evidence": investigation.evidence,
            "confidence": investigation.confidence,
            "suggested_action": investigation.suggested_action,
            "target_service": investigation.target_service,
            "risk_score": risk_score.score,
            "risk_level": risk_score.level.value,
            "confidence_level": risk_score.confidence.value,
            "verification_status": verification.overall_status.value,
            "safe_to_proceed": verification.safe_to_proceed,
            "runbook": runbook.to_markdown() if args.output else None,
        }
        print(json.dumps(output, indent=2))
    else:
        if not args.output:
            print(runbook.to_markdown())

    sys.exit(0 if verification.safe_to_proceed else 1)


if __name__ == "__main__":
    main()