from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .llm import LLMClient, LLMMessage, LLMResponse, create_llm_client
from .tools import Tool, ToolResult, get_all_tools

logger = logging.getLogger(__name__)


@dataclass
class InvestigationStep:
    tool: str
    args: Dict[str, Any]
    result: ToolResult
    reasoning: str = ""


@dataclass
class InvestigationResult:
    root_cause: str
    evidence: List[str]
    confidence: float
    suggested_action: str
    target_service: str
    steps: List[InvestigationStep] = field(default_factory=list)
    raw_llm_output: str = ""


class AgentOrchestrator:
    def __init__(self, llm: Optional[LLMClient] = None, tools: Optional[List[Tool]] = None, max_iterations: int = 5):
        self.llm = llm or create_llm_client()
        self.tools = {t.name: t for t in (tools or get_all_tools())}
        self.max_iterations = max_iterations
        self.tool_schemas = [self._tool_to_schema(t) for t in self.tools.values()]

    def _tool_to_schema(self, tool: Tool) -> Dict[str, Any]:
        return {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        }

    def investigate(self, incident_description: str, context: Optional[Dict[str, Any]] = None) -> InvestigationResult:
        system_prompt = self._build_system_prompt()
        messages = [
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(role="user", content=self._build_user_prompt(incident_description, context)),
        ]

        steps: List[InvestigationStep] = []

        for iteration in range(self.max_iterations):
            logger.info(f"Investigation iteration {iteration + 1}/{self.max_iterations}")

            response = self.llm.chat(
                messages=messages,
                tools=list(self.tools.values()),
                tool_choice="auto",
            )

            if response.tool_calls:
                for tool_call in response.tool_calls:
                    func = tool_call["function"]
                    tool_name = func["name"]
                    args = json.loads(func["arguments"])

                    tool = self.tools.get(tool_name)
                    if not tool:
                        logger.warning(f"Unknown tool: {tool_name}")
                        continue

                    logger.info(f"Calling tool: {tool_name} with args: {args}")
                    result = tool.execute(**args)

                    step = InvestigationStep(
                        tool=tool_name,
                        args=args,
                        result=result,
                        reasoning=f"Iteration {iteration + 1}: Called {tool_name}",
                    )
                    steps.append(step)

                    messages.append(LLMMessage(
                        role="assistant",
                        content=response.content or "",
                        tool_calls=[tool_call],
                    ))
                    messages.append(LLMMessage(
                        role="tool",
                        content=json.dumps(result.to_dict()),
                        tool_call_id=tool_call["id"],
                    ))

                continue

            if response.content:
                try:
                    parsed = json.loads(response.content)
                    return InvestigationResult(
                        root_cause=parsed.get("root_cause", "Unknown"),
                        evidence=parsed.get("evidence", []),
                        confidence=float(parsed.get("confidence", 0.5)),
                        suggested_action=parsed.get("suggested_action", "investigate_manually"),
                        target_service=parsed.get("target", "unknown"),
                        steps=steps,
                        raw_llm_output=response.content,
                    )
                except json.JSONDecodeError:
                    logger.warning("LLM response not valid JSON, treating as final answer")
                    return InvestigationResult(
                        root_cause=response.content[:200],
                        evidence=[],
                        confidence=0.5,
                        suggested_action="investigate_manually",
                        target_service="unknown",
                        steps=steps,
                        raw_llm_output=response.content,
                    )

        return InvestigationResult(
            root_cause="Max iterations reached without conclusion",
            evidence=[],
            confidence=0.1,
            suggested_action="investigate_manually",
            target_service="unknown",
            steps=steps,
            raw_llm_output="",
        )

    def _build_system_prompt(self) -> str:
        tool_descs = "\n".join([
            f"- {t.name}: {t.description}"
            for t in self.tools.values()
        ])
        return f"""You are an expert SRE incident investigator. Your job is to analyze incidents and determine root cause.

Available tools:
{tool_descs}

Investigation process:
1. Start by querying metrics for the affected service
2. Extract stack traces from logs to find error patterns
3. Analyze distributed traces for latency and error propagation
4. Check recent Git commits for potential regressions
5. Synthesize findings into a root cause analysis

You must call tools to gather evidence. Do not guess - use the tools.
When you have enough evidence, respond with a JSON object containing:
{{
  "root_cause": "Clear description of the root cause",
  "evidence": ["Evidence point 1", "Evidence point 2", ...],
  "confidence": 0.0-1.0,
  "suggested_action": "rollback_deployment|scale_up|restart_service|investigate_manually|...",
  "target": "service-name"
}}"""

    def _build_user_prompt(self, incident: str, context: Optional[Dict[str, Any]]) -> str:
        ctx_str = json.dumps(context, indent=2) if context else "{}"
        return f"""Incident: {incident}

Context: {ctx_str}

Begin investigation. Use the available tools to gather evidence and determine root cause."""


def run_investigation(incident: str, context: Optional[Dict[str, Any]] = None) -> InvestigationResult:
    orchestrator = AgentOrchestrator()
    return orchestrator.investigate(incident, context)