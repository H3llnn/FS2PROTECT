FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/app/data
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --create-home subgate
COPY --chown=subgate:subgate . .
RUN mkdir -p /app/data && chown subgate:subgate /app/data
USER subgate
CMD ["python", "main.py"]
