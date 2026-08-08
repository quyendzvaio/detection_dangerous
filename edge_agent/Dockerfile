FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg v4l-utils \
    && rm -rf /var/lib/apt/lists/*
COPY edge_agent/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY edge_agent /app/edge_agent
COPY customer_host /app/customer_host
COPY ai_engine/__init__.py /app/ai_engine/__init__.py
COPY ai_engine/quality_contract.py /app/ai_engine/quality_contract.py
CMD ["python", "-m", "edge_agent.main"]
