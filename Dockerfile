FROM mcr.microsoft.com/playwright/python:v1.48.0-jammy

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# 👇 ESSA LINHA FALTAVA
RUN playwright install --with-deps chromium

COPY . .

CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}
