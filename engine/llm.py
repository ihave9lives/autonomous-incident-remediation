from __future__ import annotations

import os
import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Protocol
from enum import Enum

logger = logging.getLogger(__name__)


class ToolResult:
    def __init__(self, success: bool, data: Any = None, error: str = ""):
        self.success = success
        self.data = data
        self.error = error

    def to_dict(self) -> Dict[str, Any]:
        return {"success": self.success, "data": self.data, "error": self.error}


class Tool(Protocol):
    name: str
    description: str
    parameters: Dict[str, Any]

    def execute(self, **kwargs) -> ToolResult:
        ...


@dataclass
class LLMMessage:
    role: str
    content: str
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_call_id: Optional[str] = None


@dataclass
class LLMResponse:
    content: str
    tool_calls: Optional[List[Dict[str, Any]]] = None
    usage: Optional[Dict[str, int]] = None


class LLMClient(ABC):
    @abstractmethod
    def chat(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[Tool]] = None,
        tool_choice: str = "auto",
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        ...

    @abstractmethod
    def get_model_name(self) -> str:
        ...


class OpenAICompatibleClient(LLMClient):
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout: int = 60,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                import httpx
                self._client = httpx.Client(
                    base_url=self.base_url,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    timeout=self.timeout,
                )
            except ImportError:
                raise RuntimeError("httpx not installed. Run: pip install httpx")
        return self._client

    def chat(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[Tool]] = None,
        tool_choice: str = "auto",
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        client = self._get_client()

        formatted_messages = []
        for m in messages:
            msg = {"role": m.role, "content": m.content}
            if m.tool_calls:
                msg["tool_calls"] = m.tool_calls
            if m.tool_call_id:
                msg["tool_call_id"] = m.tool_call_id
            formatted_messages.append(msg)

        payload = {
            "model": self.model,
            "messages": formatted_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in tools
            ]
            payload["tool_choice"] = tool_choice

        try:
            resp = client.post("/chat/completions", json=payload)
            resp.raise_for_status()
            data = resp.json()

            choice = data["choices"][0]
            message = choice["message"]

            tool_calls = None
            if message.get("tool_calls"):
                tool_calls = message["tool_calls"]

            return LLMResponse(
                content=message.get("content", ""),
                tool_calls=tool_calls,
                usage=data.get("usage"),
            )
        except Exception as e:
            logger.error(f"LLM API error: {e}")
            raise

    def get_model_name(self) -> str:
        return self.model

    def close(self):
        if self._client:
            self._client.close()


class ScriptedLLM(LLMClient):
    def __init__(self, scripts: Optional[Dict[str, str]] = None):
        self.scripts = scripts or {}
        self.call_count = 0
        self.tools_called: List[str] = []

    def _analyze_incident(self, incident_text: str) -> Dict:
        text = incident_text.lower()

        if "memory" in text and ("leak" in text or "oom" in text):
            return {
                "root_cause": "Memory leak in checkout-service causing OOM kills",
                "evidence": [
                    "Memory usage growing unbounded (>90%)",
                    "OOM killer triggered on checkout-service pods",
                    "Heap dump shows accumulating request objects"
                ],
                "confidence": 0.85,
                "suggested_action": "restart_service",
                "target": "checkout-service"
            }
        elif "deploy" in text or "regression" in text or "commit" in text:
            return {
                "root_cause": "Recent deployment introduced regression in payment integration",
                "evidence": [
                    "Error rate spike correlates with deploy abc123",
                    "Git commit abc123 modified payment client timeout logic",
                    "Rollback of abc123 restores normal operation"
                ],
                "confidence": 0.9,
                "suggested_action": "rollback_deployment",
                "target": "checkout-service"
            }
        elif "payment" in text and ("down" in text or "unavailable" in text):
            return {
                "root_cause": "Payment service completely unavailable and down",
                "evidence": [
                    "Payment service health checks failing",
                    "All checkout requests returning 502",
                    "No successful payment spans in traces",
                    "Service is down and unavailable"
                ],
                "confidence": 0.95,
                "suggested_action": "restart_service",
                "target": "payment-service"
            }
        elif "database" in text or "connection pool" in text:
            return {
                "root_cause": "Database connection pool exhaustion in checkout-service",
                "evidence": [
                    "Connection pool at 100% utilization",
                    "Threads blocked waiting for connections",
                    "Recent traffic spike exceeded pool size"
                ],
                "confidence": 0.88,
                "suggested_action": "scale_up",
                "target": "checkout-service"
            }
        else:
            return {
                "root_cause": "High latency in checkout-service due to payment-service timeout",
                "evidence": [
                    "EWMA detector triggered on http_latency_ms (z-score: 4.2)",
                    "Payment service calls timing out (>5s)",
                    "Recent commit abc123 increased timeout threshold"
                ],
                "confidence": 0.87,
                "suggested_action": "rollback_deployment",
                "target": "checkout-service"
            }

    def _get_next_tool(self, tool_names: List[str]) -> Optional[str]:
        tool_order = ["query_metrics", "extract_stack_traces", "analyze_traces", "check_recent_commits"]
        for tool in tool_order:
            if tool in tool_names and tool not in self.tools_called:
                return tool
        return None

    def chat(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[Tool]] = None,
        tool_choice: str = "auto",
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        self.call_count += 1
        last_user_msg = ""
        for m in reversed(messages):
            if m.role == "user":
                last_user_msg = m.content
                break

        # Reset tools_called if this is a new investigation (new user message without tool results)
        if not any(m.role == "tool" for m in messages):
            self.tools_called = []

        if any(kw in last_user_msg.lower() for kw in ["incident", "analyze", "investigate", "root cause", "high latency", "error", "timeout", "down", "unavailable", "memory", "leak", "oom", "deploy", "regression", "commit", "database", "connection pool"]):
            if tools:
                tool_names = [t.name for t in tools]
                next_tool = self._get_next_tool(tool_names)
                if next_tool:
                    self.tools_called.append(next_tool)
                    tool_args = {
                        "query_metrics": '{"service": "checkout-service", "metric": "http_latency_ms", "window": "5m"}',
                        "extract_stack_traces": '{"service": "checkout-service", "window": "5m"}',
                        "analyze_traces": '{"service": "checkout-service", "window": "5m"}',
                        "check_recent_commits": '{"repo_path": ".", "since": "1h"}',
                    }
                    return LLMResponse(
                        content="",
                        tool_calls=[{
                            "id": f"call_{self.call_count}",
                            "type": "function",
                            "function": {"name": next_tool, "arguments": tool_args.get(next_tool, "{}")}
                        }]
                    )

        analysis = self._analyze_incident(last_user_msg)
        return LLMResponse(content=json.dumps(analysis))

    def get_model_name(self) -> str:
        return "scripted-llm"


def create_llm_client() -> LLMClient:
    base_url = os.getenv("LLM_BASE_URL")
    api_key = os.getenv("LLM_API_KEY")
    model = os.getenv("LLM_MODEL", "gpt-4o-mini")

    if base_url and api_key:
        logger.info(f"Using OpenAI-compatible LLM: {model} at {base_url}")
        return OpenAICompatibleClient(base_url, api_key, model)
    else:
        logger.info("No LLM credentials found, using ScriptedLLM fallback")
        return ScriptedLLM()