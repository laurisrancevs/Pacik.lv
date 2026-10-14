
from fastapi import FastAPI, Query

app = FastAPI(title="PACIK.LV Address API")


@app.get("/")
def home():
    return {"status": "ok", "service": "PACIK.LV Address API"}


@app.get("/health")
def health():
    return {"status": "ok"}
