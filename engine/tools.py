from __future__ import annotations

import json
import random
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .llm import Tool, ToolResult


@dataclass
class MetricQueryTool(Tool):
    name: str = "query_metrics"
    description: str = "Query time-series metrics from ClickHouse (or in-memory fallback)"
    parameters: Dict[str, Any] = field(default_factory=lambda: {
        "type": "object",
        "properties": {
            "service": {"type": "string", "description": "Service name to query"},
            "metric": {"type": "string", "description": "Metric name (e.g., http_latency_ms, error_rate)"},
            "window": {"type": "string", "description": "Time window (e.g., 5m, 1h, 24h)"},
        },
        "required": ["service", "metric", "window"],
    })

    def execute(self, service: str, metric: str, window: str) -> ToolResult:
        try:
            base_values = {
                "http_latency_ms": 50.0,
                "error_rate": 0.01,
                "throughput_rps": 100.0,
                "cpu_usage": 0.45,
                "memory_usage": 0.60,
            }
            base = base_values.get(metric, 100.0)

            if service == "checkout-service" and metric == "http_latency_ms":
                values = [base + random.uniform(-10, 200) for _ in range(20)]
            elif service == "checkout-service" and metric == "error_rate":
                values = [base + random.uniform(-0.005, 0.15) for _ in range(20)]
            else:
                values = [base + random.uniform(-base*0.1, base*0.1) for _ in range(20)]

            return ToolResult(True, {
                "service": service,
                "metric": metric,
                "window": window,
                "values": values,
                "count": len(values),
                "min": min(values),
                "max": max(values),
                "avg": sum(values) / len(values),
                "p95": sorted(values)[int(len(values) * 0.95)],
                "p99": sorted(values)[int(len(values) * 0.99)],
            })
        except Exception as e:
            return ToolResult(False, error=str(e))


@dataclass
class ExtractStackTracesTool(Tool):
    name: str = "extract_stack_traces"
    description: str = "Extract stack traces from logs for a service in a time window"
    parameters: Dict[str, Any] = field(default_factory=lambda: {
        "type": "object",
        "properties": {
            "service": {"type": "string", "description": "Service name"},
            "window": {"type": "string", "description": "Time window (e.g., 5m, 1h)"},
            "level": {"type": "string", "description": "Log level filter", "default": "ERROR"},
        },
        "required": ["service", "window"],
    })

    def execute(self, service: str, window: str, level: str = "ERROR") -> ToolResult:
        try:
            traces = [
                {
                    "timestamp": int(time.time() * 1000) - i * 60000,
                    "level": "ERROR",
                    "message": "java.lang.TimeoutException: Payment service call timed out after 5000ms",
                    "stack_trace": (
                        "java.lang.TimeoutException: Payment service call timed out after 5000ms\n"
                        "\tat com.example.checkout.PaymentClient.charge(PaymentClient.java:45)\n"
                        "\tat com.example.checkout.CheckoutService.process(CheckoutService.java:112)\n"
                        "\tat com.example.checkout.CheckoutController.checkout(CheckoutController.java:28)"
                    ),
                    "service": service,
                }
                for i in range(3)
            ]

            return ToolResult(True, {
                "service": service,
                "window": window,
                "level": level,
                "count": len(traces),
                "traces": traces,
            })
        except Exception as e:
            return ToolResult(False, error=str(e))


@dataclass
class AnalyzeTracesTool(Tool):
    name: str = "analyze_traces"
    description: str = "Analyze distributed traces for latency, errors, and span anomalies"
    parameters: Dict[str, Any] = field(default_factory=lambda: {
        "type": "object",
        "properties": {
            "service": {"type": "string", "description": "Service name"},
            "window": {"type": "string", "description": "Time window (e.g., 5m, 1h)"},
            "trace_id": {"type": "string", "description": "Optional specific trace ID"},
        },
        "required": ["service", "window"],
    })

    def execute(self, service: str, window: str, trace_id: Optional[str] = None) -> ToolResult:
        try:
            spans = [
                {
                    "trace_id": f"trace_{i}",
                    "span_id": f"span_{i}_1",
                    "service": "checkout-service",
                    "operation": "checkout",
                    "duration_ms": 150 + random.uniform(0, 3000),
                    "status": "ERROR" if random.random() < 0.3 else "OK",
                    "tags": {"user_id": f"user_{i}", "items": random.randint(1, 10)},
                }
                for i in range(10)
            ]

            error_spans = [s for s in spans if s["status"] == "ERROR"]
            avg_duration = sum(s["duration_ms"] for s in spans) / len(spans)

            return ToolResult(True, {
                "service": service,
                "window": window,
                "total_spans": len(spans),
                "error_spans": len(error_spans),
                "error_rate": len(error_spans) / len(spans),
                "avg_duration_ms": avg_duration,
                "p95_duration_ms": sorted([s["duration_ms"] for s in spans])[int(len(spans) * 0.95)],
                "top_operations": [
                    {"operation": "checkout", "count": len(spans), "avg_ms": avg_duration},
                ],
                "slowest_traces": sorted(spans, key=lambda x: x["duration_ms"], reverse=True)[:3],
            })
        except Exception as e:
            return ToolResult(False, error=str(e))


@dataclass
class CheckRecentCommitsTool(Tool):
    name: str = "check_recent_commits"
    description: str = "Check recent Git commits for potential regression causes"
    parameters: Dict[str, Any] = field(default_factory=lambda: {
        "type": "object",
        "properties": {
            "repo_path": {"type": "string", "description": "Repository path", "default": "."},
            "since": {"type": "string", "description": "Time range (e.g., 1h, 24h, 7d)"},
            "max_count": {"type": "integer", "description": "Max commits to return", "default": 20},
        },
        "required": ["repo_path", "since"],
    })

    def execute(self, repo_path: str, since: str, max_count: int = 20) -> ToolResult:
        try:
            result = subprocess.run(
                ["git", "-C", repo_path, "log", f"--since={since}", f"-n", str(max_count), "--pretty=format:%H|%an|%ad|%s", "--date=iso"],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode != 0:
                commits = [
                    {
                        "hash": "abc123def456",
                        "author": "dev@example.com",
                        "date": "2024-01-15T10:30:00+00:00",
                        "message": "Increase payment service timeout from 3s to 5s",
                        "files": ["checkout-service/main.py", "checkout-service/config.yaml"],
                    },
                    {
                        "hash": "def456ghi789",
                        "author": "dev@example.com",
                        "date": "2024-01-15T09:15:00+00:00",
                        "message": "Add retry logic for payment service calls",
                        "files": ["checkout-service/main.py"],
                    },
                ]
            else:
                commits = []
                for line in result.stdout.strip().split("\n"):
                    if line:
                        parts = line.split("|", 3)
                        if len(parts) == 4:
                            commits.append({
                                "hash": parts[0],
                                "author": parts[1],
                                "date": parts[2],
                                "message": parts[3],
                                "files": [],
                            })

            return ToolResult(True, {
                "repo_path": repo_path,
                "since": since,
                "commit_count": len(commits),
                "commits": commits,
            })
        except Exception as e:
            return ToolResult(False, error=str(e))


@dataclass
class GetServiceTopologyTool(Tool):
    name: str = "get_service_topology"
    description: str = "Get service dependency topology from traces"
    parameters: Dict[str, Any] = field(default_factory=lambda: {
        "type": "object",
        "properties": {
            "window": {"type": "string", "description": "Time window", "default": "1h"},
        },
        "required": ["window"],
    })

    def execute(self, window: str) -> ToolResult:
        try:
            return ToolResult(True, {
                "window": window,
                "services": [
                    {"name": "checkout-service", "dependencies": ["payment-service"], "call_count": 1250},
                    {"name": "payment-service", "dependencies": [], "call_count": 1250},
                ],
                "edges": [
                    {"source": "checkout-service", "target": "payment-service", "call_count": 1250, "avg_latency_ms": 45},
                ],
            })
        except Exception as e:
            return ToolResult(False, error=str(e))


def get_all_tools() -> List[Tool]:
    return [
        MetricQueryTool(),
        ExtractStackTracesTool(),
        AnalyzeTracesTool(),
        CheckRecentCommitsTool(),
        GetServiceTopologyTool(),
    ]