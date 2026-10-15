FROM python:3.10-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt requirements-analysis.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt -r requirements-analysis.txt
COPY app ./app
COPY scripts ./scripts
COPY load_tests ./load_tests
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]
