from __future__ import annotations

import logging
import subprocess
import tempfile
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class VerificationStatus(Enum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"


@dataclass
class VerificationResult:
    check: str
    status: VerificationStatus
    details: str
    command: str = ""
    output: str = ""


@dataclass
class SandboxVerification:
    overall_status: VerificationStatus
    results: List[VerificationResult]
    rollback_command: str = ""
    git_revert_patch: str = ""
    safe_to_proceed: bool = False


def verify_kubectl_rollback(
    deployment: str,
    namespace: str = "default",
    dry_run: bool = True,
) -> VerificationResult:
    cmd = ["kubectl", "rollout", "undo", f"deployment/{deployment}", "-n", namespace]
    if dry_run:
        cmd.append("--dry-run=client")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        success = result.returncode == 0

        return VerificationResult(
            check=f"kubectl_rollback_{deployment}",
            status=VerificationStatus.PASSED if success else VerificationStatus.FAILED,
            details=f"Rollback {'dry-run' if dry_run else 'execution'} {'succeeded' if success else 'failed'}",
            command=" ".join(cmd),
            output=result.stdout + result.stderr,
        )
    except subprocess.TimeoutExpired:
        return VerificationResult(
            check=f"kubectl_rollback_{deployment}",
            status=VerificationStatus.ERROR,
            details="kubectl command timed out",
            command=" ".join(cmd),
        )
    except FileNotFoundError:
        return VerificationResult(
            check=f"kubectl_rollback_{deployment}",
            status=VerificationStatus.SKIPPED,
            details="kubectl not available in environment",
            command=" ".join(cmd),
        )
    except Exception as e:
        return VerificationResult(
            check=f"kubectl_rollback_{deployment}",
            status=VerificationStatus.ERROR,
            details=f"Unexpected error: {e}",
            command=" ".join(cmd),
        )


def verify_git_revert(
    commit_hash: str,
    repo_path: str = ".",
    dry_run: bool = True,
) -> VerificationResult:
    try:
        show_cmd = ["git", "-C", repo_path, "show", commit_hash, "--format=", "--patch"]
        show_result = subprocess.run(show_cmd, capture_output=True, text=True, timeout=10)

        if show_result.returncode != 0:
            return VerificationResult(
                check=f"git_revert_{commit_hash[:8]}",
                status=VerificationStatus.FAILED,
                details=f"Could not retrieve commit {commit_hash}",
                command=" ".join(show_cmd),
                output=show_result.stderr,
            )

        patch_content = show_result.stdout

        with tempfile.NamedTemporaryFile(mode="w", suffix=".patch", delete=False) as f:
            f.write(patch_content)
            patch_file = f.name

        try:
            check_cmd = ["git", "-C", repo_path, "apply", "--check"]
            if dry_run:
                check_cmd.append("--dry-run")
            check_cmd.append(patch_file)

            check_result = subprocess.run(check_cmd, capture_output=True, text=True, timeout=10)
            success = check_result.returncode == 0

            return VerificationResult(
                check=f"git_revert_{commit_hash[:8]}",
                status=VerificationStatus.PASSED if success else VerificationStatus.FAILED,
                details=f"Git revert patch {'validates' if success else 'fails validation'}",
                command=" ".join(check_cmd),
                output=check_result.stdout + check_result.stderr,
            )
        finally:
            try:
                os.unlink(patch_file)
            except OSError:
                pass

    except subprocess.TimeoutExpired:
        return VerificationResult(
            check=f"git_revert_{commit_hash[:8]}",
            status=VerificationStatus.ERROR,
            details="Git command timed out",
            command="git apply --check",
        )
    except FileNotFoundError:
        return VerificationResult(
            check=f"git_revert_{commit_hash[:8]}",
            status=VerificationStatus.SKIPPED,
            details="git not available in environment",
            command="git apply --check",
        )
    except Exception as e:
        return VerificationResult(
            check=f"git_revert_{commit_hash[:8]}",
            status=VerificationStatus.ERROR,
            details=f"Unexpected error: {e}",
            command="git apply --check",
        )


def verify_helm_rollback(
    release: str,
    namespace: str = "default",
    revision: int = 0,
    dry_run: bool = True,
) -> VerificationResult:
    cmd = ["helm", "rollback", release]
    if revision > 0:
        cmd.append(str(revision))
    if dry_run:
        cmd.append("--dry-run")
    cmd.extend(["-n", namespace])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        success = result.returncode == 0

        return VerificationResult(
            check=f"helm_rollback_{release}",
            status=VerificationStatus.PASSED if success else VerificationStatus.FAILED,
            details=f"Helm rollback {'dry-run' if dry_run else 'execution'} {'succeeded' if success else 'failed'}",
            command=" ".join(cmd),
            output=result.stdout + result.stderr,
        )
    except FileNotFoundError:
        return VerificationResult(
            check=f"helm_rollback_{release}",
            status=VerificationStatus.SKIPPED,
            details="helm not available in environment",
            command=" ".join(cmd),
        )
    except Exception as e:
        return VerificationResult(
            check=f"helm_rollback_{release}",
            status=VerificationStatus.ERROR,
            details=f"Unexpected error: {e}",
            command=" ".join(cmd),
        )


def verify_canary_analysis(
    service: str,
    namespace: str = "default",
) -> VerificationResult:
    cmd = ["kubectl", "get", "deployment", service, "-n", namespace, "-o", "jsonpath={.spec.replicas}"]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        replicas = int(result.stdout.strip()) if result.stdout.strip().isdigit() else 0

        if replicas >= 3:
            status = VerificationStatus.PASSED
            details = f"Service has {replicas} replicas, suitable for canary"
        elif replicas > 0:
            status = VerificationStatus.PASSED
            details = f"Service has {replicas} replicas, minimal for canary"
        else:
            status = VerificationStatus.FAILED
            details = f"Service has {replicas} replicas, cannot canary"

        return VerificationResult(
            check=f"canary_analysis_{service}",
            status=status,
            details=details,
            command=" ".join(cmd),
            output=result.stdout,
        )
    except Exception as e:
        return VerificationResult(
            check=f"canary_analysis_{service}",
            status=VerificationStatus.ERROR,
            details=f"Error checking replicas: {e}",
            command=" ".join(cmd),
        )


def run_full_verification(
    investigation_target: str,
    suggested_action: str,
    commit_hash: Optional[str] = None,
    namespace: str = "default",
    repo_path: str = ".",
) -> SandboxVerification:
    results = []

    if suggested_action in ("rollback_deployment", "restart_service"):
        results.append(verify_kubectl_rollback(investigation_target, namespace, dry_run=True))

    if suggested_action == "rollback_deployment" and commit_hash:
        results.append(verify_git_revert(commit_hash, repo_path, dry_run=True))

    if suggested_action == "rollback_deployment":
        results.append(verify_helm_rollback(investigation_target, namespace, dry_run=True))

    results.append(verify_canary_analysis(investigation_target, namespace))

    failed = [r for r in results if r.status == VerificationStatus.FAILED]
    errors = [r for r in results if r.status == VerificationStatus.ERROR]
    passed = [r for r in results if r.status == VerificationStatus.PASSED]

    if errors:
        overall = VerificationStatus.ERROR
    elif failed:
        overall = VerificationStatus.FAILED
    elif passed:
        overall = VerificationStatus.PASSED
    else:
        overall = VerificationStatus.SKIPPED

    rollback_cmd = ""
    if suggested_action == "rollback_deployment":
        rollback_cmd = f"kubectl rollout undo deployment/{investigation_target} -n {namespace}"

    git_patch = ""
    if commit_hash:
        try:
            result = subprocess.run(
                ["git", "-C", repo_path, "show", commit_hash, "--format=", "--patch"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                git_patch = result.stdout
        except Exception:
            pass

    safe = overall == VerificationStatus.PASSED

    logger.info(f"Sandbox verification: {overall.value}, {len(passed)} passed, {len(failed)} failed, {len(errors)} errors")

    return SandboxVerification(
        overall_status=overall,
        results=results,
        rollback_command=rollback_cmd,
        git_revert_patch=git_patch,
        safe_to_proceed=safe,
    )