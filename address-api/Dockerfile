FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY cadastre_indexer.py .
COPY index.html ./index.html
COPY ["Riga at Blue Hour_ Bridges and Spires.png", "./pacik-riga-hero.png"]

ENV PORT=8080
CMD ["sh", "-c", "exec uvicorn app:app --host 0.0.0.0 --port ${PORT}"]
