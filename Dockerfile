# syntax=docker/dockerfile:1
# Full BurdaSaxla (API + admin + UI) in one container.
# docker build -t burdasaxla . && docker run -p 8000:8000 -e BURDASAXLA_ADMIN_TOKEN=change-me burdasaxla
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/proxy_ca; fi; \
    npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 BURDASAXLA_DB=/data/burdasaxla.sqlite3
WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    pip install --no-cache-dir -r requirements.txt
COPY backend/ ./
COPY --from=web /web/dist /app/frontend/dist
RUN mkdir -p /data && useradd -r -u 10001 app \
    && chmod -R a+rX /app/backend/app /app/backend/data \
    && chown -R app /data
USER app
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
