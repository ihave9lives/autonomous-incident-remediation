# Autonomous Incident Remediation Agent (AIOps & SRE)

A production-grade autonomous incident remediation system that detects anomalies, performs root cause analysis, assesses risk, and generates verified remediation runbooks.

## Architecture Overview

```
┌─────────────────┐     ┌──────────────────┐     ┌────────────────────┐
│  Demo Services  │────▶│  OTel Collector  │────▶│    ClickHouse      │
│ (FastAPI + OTel)│     │  (Traces/Metrics)│     │  (Telemetry Store) │
└─────────────────┘     └──────────────────┘     └────────────────────┘
                                                       │
                                                       ▼
┌─────────────────┐     ┌──────────────────┐     ┌────────────────────┐
│  Runbook Gen    │◀────│  Risk Scorer &   │◀────│  Agentic Engine    │
│  (Markdown)     │     │  Sandbox Verify  │     │  (LLM + Tools)     │
└─────────────────┘     └──────────────────┘     └────────────────────┘
                                                       ▲
                                                       │
                                              ┌──────────────────┐
                                              │ Anomaly Daemon   │
                                              │ (Go: EWMA +      │
                                              │  Entropy)        │
                                              └──────────────────┘
```

## Components

### 1. Telemetry & Demo Microservices (`otel/`, `demo-app/`, `docker-compose.yml`)
- **OpenTelemetry Collector**: Exports traces, metrics, logs to ClickHouse
- **checkout-service**: FastAPI service with OTel instrumentation, calls payment-service
- **payment-service**: FastAPI service with OTel instrumentation
- **Fault Injection**: `/faults/{mode}` endpoint for latency spikes, HTTP 500s, or both

### 2. Go Anomaly Trigger Daemon (`anomaly-daemon/`)
- **EWMA Detector**: Exponentially Weighted Moving Average for threshold shift detection
- **Shannon Entropy Detector**: Log level distribution entropy for burst detection
- **Stdlib-only**: No external dependencies
- **Unit Tests**: Comprehensive test coverage in `detector_test.go`

### 3. Python Agentic Root-Cause Engine (`engine/`)
- **Pluggable LLM Client**: OpenAI-compatible APIs (`LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`)
- **ScriptedLLM Fallback**: Deterministic offline mode for testing/CI
- **Tool-Calling Orchestrator**: 5 built-in tools
  - `query_metrics` - Time-series metrics from ClickHouse (or in-memory)
  - `extract_stack_traces` - Error stack traces from logs
  - `analyze_traces` - Distributed trace span analysis
  - `check_recent_commits` - Git history for regression detection
  - `get_service_topology` - Service dependency mapping

### 4. Verification Sandbox & Risk Scoring (`engine/risk.py`, `engine/verifier.py`, `engine/runbook.py`)
- **Deterministic Risk Score (0-100)**: Weighted evidence correlation
- **Confidence Rating**: Very High / High / Medium / Low / Very Low
- **Sandbox Verifier**: Dry-runs `kubectl rollout undo --dry-run=client`, validates `git apply --check`
- **Markdown Runbooks**: Complete incident documentation with timeline, evidence, remediation steps, post-mortem template

### 5. Deterministic Eval Harness & CI (`eval/`, `.github/workflows/ci.yml`)
- **Golden Scenarios**: 5 predefined incidents with expected outcomes
- **GitHub Actions**: Runs `go test`, `pytest`, eval suite, linting, Docker builds

## Quick Start

### Prerequisites
- Docker & Docker Compose
- Go 1.22+
- Python 3.12+
- (Optional) kubectl, helm for verification

### Run the Demo Stack

```bash
# Start all services
docker compose up -d

# Verify services
curl http://localhost:8001/health  # checkout-service
curl http://localhost:8002/health  # payment-service

# Inject faults
curl -X POST http://localhost:8001/faults/latency -H "Content-Type: application/json" -d '{"latency_ms": 500}'
curl -X POST http://localhost:8001/faults/error -H "Content-Type: application/json" -d '{"error_rate": 0.3}'

# View metrics
curl http://localhost:8888/metrics  # OTel collector Prometheus endpoint
```

### Run the Anomaly Daemon

```bash
cd anomaly-daemon
go mod download
go run main.go -config=config.json
```

### Run the Agentic Engine

```bash
cd engine
pip install -r requirements.txt

# Offline mode (no API keys needed)
python -m engine.cli "Checkout service high latency and 5xx errors"

# With LLM (set environment variables)
export LLM_BASE_URL=https://api.openai.com/v1
export LLM_API_KEY=your-key
export LLM_MODEL=gpt-4o-mini
python -m engine.cli "Payment service timeout cascade"
```

### Run Tests

```bash
# Go tests
cd anomaly-daemon && go test -v ./...

# Python tests
cd engine && python -m pytest -v

# Evaluation harness
cd eval && python run_eval.py
```

## Configuration

### Anomaly Daemon Config (`anomaly-daemon/config.json`)
```json
{
  "ewma": {
    "alpha": 0.3,
    "threshold": 3.0,
    "window_size": 100,
    "min_samples": 10
  },
  "entropy": {
    "window_size": 50,
    "threshold": 2.5,
    "min_samples": 20
  },
  "metrics": { "endpoint": "", "interval": 10 },
  "logs": { "endpoint": "", "interval": 10 },
  "alert_endpoint": "http://localhost:8080/alerts"
}
```

### Engine Environment Variables
| Variable | Description | Default |
|----------|-------------|---------|
| `LLM_BASE_URL` | OpenAI-compatible API base URL | (uses ScriptedLLM) |
| `LLM_API_KEY` | API key | (uses ScriptedLLM) |
| `LLM_MODEL` | Model name | `gpt-4o-mini` |

## API Reference

### Fault Injection Endpoint
```
POST /faults/{mode}
```
Modes: `none`, `latency`, `error`, `both`

Body (for latency/error/both):
```json
{"latency_ms": 500, "error_rate": 0.1}
```

### Health Checks
```
GET /health
```

## Evaluation Scenarios

| Scenario | Description | Expected Action |
|----------|-------------|-----------------|
| `payment_timeout_cascade` | Payment timeouts causing checkout latency | `rollback_deployment` |
| `memory_leak_checkout` | Memory growth leading to OOM kills | `restart_service` |
| `deployment_regression` | Error spike after new deploy | `rollback_deployment` |
| `payment_service_down` | Payment service unavailable | `restart_service` |
| `database_connection_pool_exhaustion` | DB pool exhausted | `scale_up` |

## CI/CD Pipeline

The GitHub Actions workflow (`.github/workflows/ci.yml`) runs on every push/PR:

1. **Go Tests** - Anomaly daemon unit tests
2. **Python Tests** - Engine unit tests
3. **Evaluation Harness** - Golden scenario validation
4. **Linting** - Ruff (Python), go vet/fmt (Go)
5. **Docker Build** - Service image builds
6. **Integration Test** - Full stack smoke test (main branch only)

## Runbook Output

The agent generates comprehensive Markdown runbooks including:
- Incident metadata and risk assessment
- Root cause analysis with evidence
- Investigation step log
- Sandbox verification results
- Remediation commands (ready to execute)
- Post-mortem template

Example:
```bash
python -m engine.cli "Checkout 5xx spike" --output runbook.md
cat runbook.md
```

## Extending the System

### Add Custom Tools
```python
from engine.tools import Tool, ToolResult

class MyCustomTool(Tool):
    name = "my_tool"
    description = "Does something useful"
    parameters = {"type": "object", "properties": {...}}

    def execute(self, **kwargs) -> ToolResult:
        return ToolResult(True, data={"result": "..."})

# Register in orchestrator
orchestrator = AgentOrchestrator(tools=[MyCustomTool()] + get_all_tools())
```

### Add Custom Detectors (Go)
```go
type CustomDetector struct {
    // ...
}

func (d *CustomDetector) Update(value float64) (bool, float64) {
    // Your detection logic
    return isAnomaly, score
}
```

## License

MIT License - see LICENSE file for details.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Run tests: `go test ./... && pytest && python eval/run_eval.py`
4. Submit a PR