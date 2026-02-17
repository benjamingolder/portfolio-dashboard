FROM python:3.12-slim AS builder

WORKDIR /build
COPY proto/client.proto proto/
RUN pip install --no-cache-dir grpcio-tools protobuf==5.29.0 && \
    mkdir -p app/parser && \
    python -m grpc_tools.protoc --python_out=app/parser --proto_path=proto proto/client.proto

FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/
COPY --from=builder /build/app/parser/client_pb2.py app/parser/

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import httpx; httpx.get('http://localhost:8000/api/sync/status').raise_for_status()"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
