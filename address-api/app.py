
from fastapi import FastAPI, Query

app = FastAPI(title="PACIK.LV Address API")


@app.get("/")
def home():
    return {"status": "ok", "service": "PACIK.LV Address API"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/search")
def search_address(q: str = Query(min_length=3)):
    return {
        "query": q,
        "results": [],
        "message": "Adreses datu avots vēl nav pieslēgts"
    }
