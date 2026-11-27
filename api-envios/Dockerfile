# Multietapa: las dependencias se instalan en un venv que se copia a la imagen final.
FROM python:3.12.16-slim AS build
WORKDIR /build
RUN python -m venv /opt/venv
COPY requirements.txt .
RUN /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

FROM python:3.12.16-slim
ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN useradd --system --uid 10001 --no-create-home envios
WORKDIR /app
COPY --from=build /opt/venv /opt/venv
COPY app ./app
COPY migrations ./migrations
COPY openapi.json .
USER 10001
EXPOSE 8003
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s \
  CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8003/health', timeout=2)"
CMD ["uvicorn", "--factory", "app.main:build_app", "--host", "0.0.0.0", "--port", "8003"]
