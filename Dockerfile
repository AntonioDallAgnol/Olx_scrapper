# Stage 1: Build the Application
FROM python:3.10-slim AS build

WORKDIR /usr/src/app

# Dependências para compilar bibliotecas C (necessário para curl_cffi)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Criação do virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copia e instala as dependências
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Stage 2: Final Runtime Image
FROM python:3.10-slim

WORKDIR /usr/src/app

# Copia o virtual environment compilado
COPY --from=build /opt/venv /opt/venv

# Copia o código da aplicação
COPY . .

ENV PATH="/opt/venv/bin:$PATH"
# Garante que os prints apareçam imediatamente nos logs do Fly
ENV PYTHONUNBUFFERED=1

# Usuário sem privilégios de root
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /usr/src/app
USER appuser

# Executa o script do bot
CMD ["python", "monitor_olx.py"]
