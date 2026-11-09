from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from .orchestrator import InvestigationResult
from .risk import RiskScore
from .verifier import SandboxVerification, VerificationStatus

logger = logging.getLogger(__name__)


@dataclass
class Runbook:
    incident_id: str
    title: str
    created_at: str
    status: str
    root_cause: str
    evidence: List[str]
    risk_score: RiskScore
    investigation_steps: List[Dict]
    verification: SandboxVerification
    remediation_steps: List[str]
    rollback_commands: List[str]
    verification_commands: List[str]
    post_mortem_template: str
    metadata: Dict = field(default_factory=dict)

    def to_markdown(self) -> str:
        lines = [
            f"# Incident Runbook: {self.title}",
            f"**Incident ID:** {self.incident_id}",
            f"**Created:** {self.created_at}",
            f"**Status:** {self.status}",
            f"**Risk Score:** {self.risk_score.score}/100 ({self.risk_score.level.value.upper()})",
            f"**Confidence:** {self.risk_score.confidence.value.upper()} ({self.risk_score.confidence_value:.0%})",
            "",
            "## Root Cause Analysis",
            self.root_cause,
            "",
            "## Evidence",
        ]

        for i, ev in enumerate(self.evidence, 1):
            lines.append(f"{i}. {ev}")

        lines.extend([
            "",
            "## Risk Assessment",
            f"- **Overall Score:** {self.risk_score.score}/100",
            f"- **Level:** {self.risk_score.level.value.upper()}",
            f"- **Confidence:** {self.risk_score.confidence.value.upper()}",
            f"- **Recommendation:** {self.risk_score.recommendation}",
            "",
            "### Score Breakdown",
        ])

        for component, value in self.risk_score.breakdown.items():
            lines.append(f"- {component}: {value:.2f}")

        lines.extend([
            "",
            "## Investigation Steps",
        ])

        for step in self.investigation_steps:
            lines.extend([
                f"### {step['tool']}",
                f"- **Arguments:** `{json.dumps(step['args'])}`",
                f"- **Success:** {step['success']}",
                f"- **Reasoning:** {step['reasoning']}",
                "",
            ])

        lines.extend([
            "## Sandbox Verification",
            f"**Overall Status:** {self.verification.overall_status.value.upper()}",
            f"**Safe to Proceed:** {'✅ YES' if self.verification.safe_to_proceed else '❌ NO'}",
            "",
        ])

        for vr in self.verification.results:
            status_icon = {
                VerificationStatus.PASSED: "✅",
                VerificationStatus.FAILED: "❌",
                VerificationStatus.SKIPPED: "⏭️",
                VerificationStatus.ERROR: "⚠️",
            }.get(vr.status, "❓")
            lines.extend([
                f"### {status_icon} {vr.check}",
                f"- **Status:** {vr.status.value}",
                f"- **Details:** {vr.details}",
                f"- **Command:** `{vr.command}`",
                "",
            ])

        if self.verification.rollback_command:
            lines.extend([
                "### Rollback Command",
                f"```bash\n{self.verification.rollback_command}\n```",
                "",
            ])

        if self.verification.git_revert_patch:
            lines.extend([
                "### Git Revert Patch",
                "```diff",
                self.verification.git_revert_patch[:2000],
                "```",
                "",
            ])

        lines.extend([
            "## Remediation Steps",
        ])

        for i, step in enumerate(self.remediation_steps, 1):
            lines.append(f"{i}. {step}")

        lines.extend([
            "",
            "## Verification Commands",
        ])

        for cmd in self.verification_commands:
            lines.append(f"```bash\n{cmd}\n```")

        lines.extend([
            "",
            "---",
            "## Post-Mortem Template",
            self.post_mortem_template,
        ])

        return "\n".join(lines)

    def save(self, path: str) -> None:
        with open(path, "w") as f:
            f.write(self.to_markdown())
        logger.info(f"Runbook saved to {path}")


def generate_runbook(
    incident_id: str,
    title: str,
    investigation: InvestigationResult,
    risk_score: RiskScore,
    verification: SandboxVerification,
    metadata: Optional[Dict] = None,
) -> Runbook:
    remediation_steps = _generate_remediation_steps(investigation, risk_score, verification)
    rollback_commands = _generate_rollback_commands(investigation, verification)
    verification_commands = _generate_verification_commands(investigation, risk_score)

    post_mortem = _generate_post_mortem_template(incident_id, investigation, risk_score)

    investigation_steps = [
        {
            "tool": step.tool,
            "args": step.args,
            "success": step.result.success,
            "reasoning": step.reasoning,
        }
        for step in investigation.steps
    ]

    return Runbook(
        incident_id=incident_id,
        title=title,
        created_at=datetime.utcnow().isoformat() + "Z",
        status="investigated",
        root_cause=investigation.root_cause,
        evidence=investigation.evidence,
        risk_score=risk_score,
        investigation_steps=investigation_steps,
        verification=verification,
        remediation_steps=remediation_steps,
        rollback_commands=rollback_commands,
        verification_commands=verification_commands,
        post_mortem_template=post_mortem,
        metadata=metadata or {},
    )


def _generate_remediation_steps(
    inv: InvestigationResult,
    risk: RiskScore,
    verify: SandboxVerification,
) -> List[str]:
    steps = []

    if risk.level.value in ("critical", "high"):
        steps.append("🔴 **IMMEDIATE**: Page on-call engineer and initiate incident response")
        steps.append("🔴 **IMMEDIATE**: Create incident channel and communicate status to stakeholders")

    if inv.suggested_action == "rollback_deployment":
        if verify.safe_to_proceed and verify.rollback_command:
            steps.append(f"✅ Execute rollback: `{verify.rollback_command}`")
        else:
            steps.append(f"⚠️ Rollback verification failed - manual review required before: `{verify.rollback_command}`")
        if verify.git_revert_patch:
            steps.append("📝 Apply git revert patch after deployment rollback")

    elif inv.suggested_action == "scale_up":
        steps.append(f"📈 Scale up {inv.target_service} deployment: `kubectl scale deployment {inv.target_service} --replicas=5`")
        steps.append("📊 Monitor metrics for 5 minutes after scaling")

    elif inv.suggested_action == "restart_service":
        steps.append(f"🔄 Restart {inv.target_service} pods: `kubectl rollout restart deployment/{inv.target_service}`")
        steps.append("📊 Verify health endpoints recover within 2 minutes")

    else:
        steps.append("🔍 Manual investigation required - review evidence and determine action")

    steps.extend([
        "📋 Document timeline and actions in incident channel",
        "📊 Monitor key metrics (latency, error rate, throughput) for 30 minutes",
        "✅ Confirm resolution with synthetic transaction test",
        "📝 Schedule post-mortem within 48 hours",
    ])

    return steps


def _generate_rollback_commands(inv: InvestigationResult, verify: SandboxVerification) -> List[str]:
    cmds = []
    if verify.rollback_command:
        cmds.append(verify.rollback_command)
    if verify.git_revert_patch:
        cmds.append("git revert <commit-hash>")
    return cmds


def _generate_verification_commands(inv: InvestigationResult, risk: RiskScore) -> List[str]:
    return [
        f"kubectl get pods -l app={inv.target_service}",
        f"kubectl logs -l app={inv.target_service} --tail=50",
        f"curl -f http://{inv.target_service}/health",
        "kubectl top pods -l app=" + inv.target_service,
    ]


def _generate_post_mortem_template(
    incident_id: str,
    inv: InvestigationResult,
    risk: RiskScore,
) -> str:
    return f"""# Post-Mortem: {incident_id}

## Incident Summary
- **ID:** {incident_id}
- **Title:** {inv.root_cause}
- **Root Cause:** {inv.root_cause}
- **Risk Score:** {risk.score}/100 ({risk.level.value})
- **Confidence:** {risk.confidence.value} ({risk.confidence_value:.0%})

## Timeline
| Time (UTC) | Event | Actor |
|------------|-------|-------|
| | Detection | Automated/Manual |
| | Investigation Start | AIOps Agent |
| | Root Cause Identified | AIOps Agent |
| | Remediation Start | On-call |
| | Resolution Confirmed | On-call |

## Impact
- **Services Affected:** {inv.target_service}
- **User Impact:** [Describe user-facing impact]
- **Revenue Impact:** [If applicable]
- **Duration:** [Detection to resolution]

## Root Cause
{inv.root_cause}

### Contributing Factors
{chr(10).join(f"- {e}" for e in inv.evidence)}

## Resolution
**Action Taken:** {inv.suggested_action}
**Target:** {inv.target_service}
**Verification:** {'Automated sandbox passed' if risk.score >= 60 else 'Manual verification required'}

## Action Items
| # | Action | Owner | Due Date | Status |
|---|--------|-------|----------|--------|
| 1 | [Prevent recurrence - e.g., add circuit breaker] | | | |
| 2 | [Improve detection - e.g., lower alert threshold] | | | |
| 3 | [Update runbook] | | | |

## Lessons Learned
- What went well?
- What didn't go well?
- What can we improve?

## Appendices
- Investigation logs: [Link]
- Metrics dashboards: [Link]
- Related incidents: [Link]
"""


def create_incident_runbook(
    incident_id: str,
    title: str,
    investigation: InvestigationResult,
    risk_score: RiskScore,
    verification: SandboxVerification,
    output_path: Optional[str] = None,
) -> Runbook:
    runbook = generate_runbook(incident_id, title, investigation, risk_score, verification)

    if output_path:
        runbook.save(output_path)

    return runbook