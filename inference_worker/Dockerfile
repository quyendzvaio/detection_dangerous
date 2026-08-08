FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app
COPY inference_worker/requirements.txt /app/inference_worker/requirements.txt
RUN pip install --no-cache-dir -r /app/inference_worker/requirements.txt

COPY ai_engine /app/ai_engine
COPY inference_worker /app/inference_worker
COPY run_inference_worker.sh /app/run_inference_worker.sh
COPY weights/fall_model/inference_config.json /app/weights/fall_model/inference_config.json

ENTRYPOINT ["python", "-m", "inference_worker.main"]
