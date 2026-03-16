FROM python:3.13-slim

WORKDIR /app

# Deps de sistema para pdfplumber (poppler)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpoppler-dev \
    && rm -rf /var/lib/apt/lists/*

# Deps Python — copia pyproject.toml primeiro para cache de layer
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Código da aplicação
COPY app/ app/
COPY doc_analizer/ doc_analizer/
COPY run.py .

# Diretórios de dados (serão sobrescritos pelo volume)
RUN mkdir -p data/db data/uploads data/gosati data/examples data/conferencias

EXPOSE 8008

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8008", "--proxy-headers", "--forwarded-allow-ips", "*"]
