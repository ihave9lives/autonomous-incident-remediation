import pytest
from engine.llm import ScriptedLLM, LLMMessage
from engine.tools import get_all_tools, MetricQueryTool, ExtractStackTracesTool
from engine.orchestrator import AgentOrchestrator, run_investigation
from engine.risk import calculate_risk_score, RiskLevel, ConfidenceLevel
from engine.verifier import run_full_verification, VerificationStatus
from engine.runbook import create_incident_runbook


class TestScriptedLLM:
    def test_scripted_llm_returns_tool_calls(self):
        llm = ScriptedLLM()
        messages = [LLMMessage(role="user", content="Analyze incident: checkout service high latency")]
        tools = get_all_tools()

        response = llm.chat(messages, tools=tools)

        assert response.tool_calls is not None
        assert len(response.tool_calls) > 0
        assert response.tool_calls[0]["function"]["name"] == "query_metrics"

    def test_scripted_llm_returns_final_answer(self):
        llm = ScriptedLLM()
        messages = [
            LLMMessage(role="user", content="Analyze incident and provide root cause"),
            LLMMessage(role="assistant", content="", tool_calls=[{"id": "1", "type": "function", "function": {"name": "query_metrics", "arguments": "{}"}}]),
            LLMMessage(role="tool", content='{"success": true, "data": {}}', tool_call_id="1"),
            LLMMessage(role="assistant", content="", tool_calls=[{"id": "2", "type": "function", "function": {"name": "extract_stack_traces", "arguments": "{}"}}]),
            LLMMessage(role="tool", content='{"success": true, "data": {}}', tool_call_id="2"),
            LLMMessage(role="assistant", content="", tool_calls=[{"id": "3", "type": "function", "function": {"name": "analyze_traces", "arguments": "{}"}}]),
            LLMMessage(role="tool", content='{"success": true, "data": {}}', tool_call_id="3"),
            LLMMessage(role="assistant", content="", tool_calls=[{"id": "4", "type": "function", "function": {"name": "check_recent_commits", "arguments": "{}"}}]),
            LLMMessage(role="tool", content='{"success": true, "data": {}}', tool_call_id="4"),
        ]

        response = llm.chat(messages, tools=[])

        assert response.content != ""
        import json
        parsed = json.loads(response.content)
        assert "root_cause" in parsed


class TestTools:
    def test_query_metrics_tool(self):
        tool = MetricQueryTool()
        result = tool.execute(service="checkout-service", metric="http_latency_ms", window="5m")

        assert result.success
        assert result.data["service"] == "checkout-service"
        assert result.data["metric"] == "http_latency_ms"
        assert "values" in result.data
        assert len(result.data["values"]) > 0

    def test_extract_stack_traces_tool(self):
        tool = ExtractStackTracesTool()
        result = tool.execute(service="checkout-service", window="5m")

        assert result.success
        assert result.data["service"] == "checkout-service"
        assert "traces" in result.data
        assert len(result.data["traces"]) > 0

    def test_all_tools_exist(self):
        tools = get_all_tools()
        tool_names = [t.name for t in tools]
        assert "query_metrics" in tool_names
        assert "extract_stack_traces" in tool_names
        assert "analyze_traces" in tool_names
        assert "check_recent_commits" in tool_names
        assert "get_service_topology" in tool_names


class TestOrchestrator:
    def test_run_investigation(self):
        result = run_investigation("Checkout service high latency and errors")

        assert result.root_cause != ""
        assert isinstance(result.evidence, list)
        assert 0 <= result.confidence <= 1
        assert result.suggested_action in ["rollback_deployment", "scale_up", "restart_service", "investigate_manually"]
        assert result.target_service != ""


class TestRiskScoring:
    def test_calculate_risk_score(self):
        from engine.orchestrator import InvestigationResult, InvestigationStep
        from engine.tools import ToolResult

        investigation = InvestigationResult(
            root_cause="Payment service timeout causing checkout latency",
            evidence=["EWMA z-score 4.2", "Stack trace shows timeout", "Recent commit increased timeout"],
            confidence=0.85,
            suggested_action="rollback_deployment",
            target_service="checkout-service",
            steps=[
                InvestigationStep(tool="query_metrics", args={}, result=ToolResult(True, data={}), reasoning="test"),
                InvestigationStep(tool="extract_stack_traces", args={}, result=ToolResult(True, data={}), reasoning="test"),
            ],
        )

        risk = calculate_risk_score(investigation)

        assert 0 <= risk.score <= 100
        assert risk.level in list(RiskLevel)
        assert risk.confidence in list(ConfidenceLevel)
        assert risk.recommendation != ""


class TestVerifier:
    def test_run_full_verification(self):
        verification = run_full_verification(
            investigation_target="checkout-service",
            suggested_action="rollback_deployment",
        )

        assert verification.overall_status in list(VerificationStatus)
        assert isinstance(verification.results, list)
        assert len(verification.results) > 0


class TestRunbook:
    def test_create_incident_runbook(self):
        from engine.orchestrator import InvestigationResult, InvestigationStep
        from engine.tools import ToolResult
        from engine.risk import RiskScore, RiskLevel, ConfidenceLevel
        from engine.verifier import SandboxVerification, VerificationResult

        investigation = InvestigationResult(
            root_cause="Test root cause",
            evidence=["Evidence 1", "Evidence 2"],
            confidence=0.8,
            suggested_action="rollback_deployment",
            target_service="checkout-service",
            steps=[],
        )

        risk = RiskScore(
            score=75,
            level=RiskLevel.HIGH,
            confidence=ConfidenceLevel.HIGH,
            confidence_value=0.8,
            breakdown={"metrics_correlation": 0.2},
            evidence_summary=["Test"],
            recommendation="Rollback deployment",
        )

        verification = SandboxVerification(
            overall_status=VerificationStatus.PASSED,
            results=[
                VerificationResult(check="test", status=VerificationStatus.PASSED, details="ok", command="test", output=""),
            ],
            rollback_command="kubectl rollout undo deployment/checkout-service",
            safe_to_proceed=True,
        )

        runbook = create_incident_runbook(
            incident_id="TEST-001",
            title="Test Incident",
            investigation=investigation,
            risk_score=risk,
            verification=verification,
        )

        assert runbook.incident_id == "TEST-001"
        assert "Test root cause" in runbook.to_markdown()
        assert "Rollback deployment" in runbook.to_markdown()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])