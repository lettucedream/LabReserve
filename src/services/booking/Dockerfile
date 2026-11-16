FROM python:3.14.10-slim@sha256:930e1abba7c4e8f96ed93e8012c35d174d7732752731bbd5e8e757d7ec6f3966
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY services/booking/requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt
RUN useradd --create-home --uid 10001 appuser
COPY shared/labreserve_messaging ./labreserve_messaging
COPY shared/labreserve_observability ./labreserve_observability
COPY shared/labreserve_auth ./labreserve_auth
COPY services/booking/app ./app
COPY services/booking/alembic.ini .
COPY services/booking/migrations ./migrations
USER appuser
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
