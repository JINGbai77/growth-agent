FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md requirements.lock ./
COPY growth_agent ./growth_agent
RUN pip install --no-cache-dir -r requirements.lock && pip install --no-cache-dir --no-deps .
RUN useradd --create-home appuser && mkdir /app/var && chown appuser:appuser /app/var
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/ready')"
CMD ["uvicorn", "growth_agent.api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
