import os
import random
import time
import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.resources import Resource, SERVICE_NAME
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor

service_name = os.getenv("OTEL_SERVICE_NAME", "payment-service")
otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")

resource = Resource.create({SERVICE_NAME: service_name})
provider = TracerProvider(resource=resource)
provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)))
trace.set_tracer_provider(provider)

LoggingInstrumentor().instrument(set_logging_format=True)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

tracer = trace.get_tracer(__name__)

fault_mode: Optional[str] = None
fault_latency_ms: int = 0
fault_error_rate: float = 0.0


class ChargeRequest(BaseModel):
    amount: float
    user_id: str


class ChargeResponse(BaseModel):
    payment_id: str
    status: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(title="Payment Service", lifespan=lifespan)
FastAPIInstrumentor.instrument_app(app)


def maybe_inject_fault():
    global fault_mode, fault_latency_ms, fault_error_rate
    if fault_mode == "latency" and fault_latency_ms > 0:
        time.sleep(fault_latency_ms / 1000.0)
    if fault_mode == "error" and fault_error_rate > 0:
        if random.random() < fault_error_rate:
            raise HTTPException(status_code=500, detail="Injected fault: simulated payment gateway error")


@app.post("/charge", response_model=ChargeResponse)
async def charge(request: ChargeRequest):
    with tracer.start_as_current_span("charge") as span:
        span.set_attribute("user_id", request.user_id)
        span.set_attribute("amount", request.amount)

        maybe_inject_fault()

        logger.info(f"Processing payment for user {request.user_id}, amount: {request.amount}")

        with tracer.start_as_current_span("payment-gateway-call") as pg_span:
            pg_span.set_attribute("gateway", "stripe-mock")
            time.sleep(random.uniform(0.01, 0.05))
            pg_span.set_attribute("gateway_response_time_ms", random.randint(10, 50))

        payment_id = f"pay_{int(time.time() * 1000)}_{random.randint(1000, 9999)}"
        span.set_attribute("payment_id", payment_id)

        logger.info(f"Payment completed: payment_id={payment_id}")

        return ChargeResponse(payment_id=payment_id, status="authorized")


@app.get("/health")
async def health():
    return {"status": "healthy", "service": service_name}


@app.post("/faults/{mode}")
async def set_fault(mode: str, latency_ms: int = 0, error_rate: float = 0.0):
    global fault_mode, fault_latency_ms, fault_error_rate
    valid_modes = ["none", "latency", "error", "both"]
    if mode not in valid_modes:
        raise HTTPException(status_code=400, detail=f"Invalid mode. Must be one of: {valid_modes}")

    fault_mode = mode if mode != "none" else None
    fault_latency_ms = latency_ms if mode in ("latency", "both") else 0
    fault_error_rate = error_rate if mode in ("error", "both") else 0.0

    logger.warning(f"Fault injection set: mode={mode}, latency_ms={fault_latency_ms}, error_rate={fault_error_rate}")
    return {"mode": mode, "latency_ms": fault_latency_ms, "error_rate": fault_error_rate}


@app.get("/faults")
async def get_fault():
    return {
        "mode": fault_mode or "none",
        "latency_ms": fault_latency_ms,
        "error_rate": fault_error_rate,
    }