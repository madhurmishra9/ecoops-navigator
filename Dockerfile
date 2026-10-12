FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080
WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY app ./app
RUN pip install --no-cache-dir ".[app,api]" \
    && useradd --create-home appuser
USER appuser

EXPOSE 8080
CMD ["sh", "-c", "streamlit run app/streamlit_app.py --server.port=${PORT} --server.address=0.0.0.0 --server.headless=true"]
