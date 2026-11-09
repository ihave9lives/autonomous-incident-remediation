FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir \
    fastapi==0.111.0 \
    uvicorn[standard]==0.30.5 \
    opentelemetry-api==1.26.0 \
    opentelemetry-sdk==1.26.0 \
    opentelemetry-instrumentation-fastapi==0.46b0 \
    opentelemetry-exporter-otlp==1.26.0 \
    opentelemetry-instrumentation-logging==0.46b0

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]