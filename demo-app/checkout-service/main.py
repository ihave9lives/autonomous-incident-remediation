import os
import random
import time
import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
import httpx

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.resources import Resource, SERVICE_NAME
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor

service_name = os.getenv("OTEL_SERVICE_NAME", "checkout-service")
otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
payment_service_url = os.getenv("PAYMENT_SERVICE_URL", "http://localhost:8000")

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


class CheckoutRequest(BaseModel):
    user_id: str
    items: list[dict]
    total_amount: float


class CheckoutResponse(BaseModel):
    order_id: str
    status: str
    payment_id: Optional[str] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    HTTPXClientInstrumentor().instrument()
    yield


app = FastAPI(title="Checkout Service", lifespan=lifespan)
FastAPIInstrumentor.instrument_app(app)


def maybe_inject_fault():
    global fault_mode, fault_latency_ms, fault_error_rate
    if fault_mode == "latency" and fault_latency_ms > 0:
        time.sleep(fault_latency_ms / 1000.0)
    if fault_mode == "error" and fault_error_rate > 0:
        if random.random() < fault_error_rate:
            raise HTTPException(status_code=500, detail="Injected fault: simulated internal error")


@app.post("/checkout", response_model=CheckoutResponse)
async def checkout(request: CheckoutRequest, http_request: Request):
    with tracer.start_as_current_span("checkout") as span:
        span.set_attribute("user_id", request.user_id)
        span.set_attribute("item_count", len(request.items))
        span.set_attribute("total_amount", request.total_amount)

        maybe_inject_fault()

        logger.info(f"Processing checkout for user {request.user_id}, items: {len(request.items)}")

        with tracer.start_as_current_span("call-payment-service") as pay_span:
            pay_span.set_attribute("service", "payment-service")
            maybe_inject_fault()

            async with httpx.AsyncClient(timeout=10.0) as client:
                try:
                    resp = await client.post(
                        f"{payment_service_url}/charge",
                        json={"amount": request.total_amount, "user_id": request.user_id},
                    )
                    resp.raise_for_status()
                    payment_data = resp.json()
                    payment_id = payment_data.get("payment_id")
                    pay_span.set_attribute("payment_id", payment_id or "unknown")
                except httpx.HTTPStatusError as e:
                    pay_span.record_exception(e)
                    span.set_attribute("error", "payment_service_failed")
                    raise HTTPException(status_code=502, detail="Payment service unavailable")
                except Exception as e:
                    pay_span.record_exception(e)
                    span.set_attribute("error", "payment_service_error")
                    raise HTTPException(status_code=500, detail="Payment service error")

        order_id = f"ord_{int(time.time() * 1000)}_{random.randint(1000, 9999)}"
        span.set_attribute("order_id", order_id)

        logger.info(f"Checkout completed: order_id={order_id}, payment_id={payment_id}")

        return CheckoutResponse(order_id=order_id, status="completed", payment_id=payment_id)


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