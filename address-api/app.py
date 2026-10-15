

import csv
import io
import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Query, HTTPException
from google.cloud import storage

BUCKET = "pacik-lv-address-data"
FILE = "aw_eka.csv"

addresses = []
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global addresses
    try:
        client = storage.Client()
        blob = client.bucket(BUCKET).blob(FILE)
        raw = blob.download_as_bytes()

        decoded = raw.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(decoded), delimiter=";")

        if not reader.fieldnames:
            raise ValueError("CSV failā nav atrastas kolonnas")

        logger.info("CSV kolonnas: %s", reader.fieldnames)

        addresses = list(reader)
        logger.info("Ielādēti %s adrešu ieraksti", len(addresses))
    except Exception:
        logger.exception("Neizdevās ielādēt adrešu datus")
        addresses = []

    yield


app = FastAPI(
    title="PACIK.LV Address API",
    lifespan=lifespan
)


@app.get("/")
def home():
    return {
        "status": "ok",
        "service": "PACIK.LV Address API",
        "loaded_records": len(addresses)
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "loaded_records": len(addresses),
        "columns": list(addresses[0].keys()) if addresses else []
    }


@app.get("/search")
def search_address(q: str = Query(min_length=3)):
    if not addresses:
        raise HTTPException(
            status_code=503,
            detail="Adrešu dati nav ielādēti"
        )

    query = q.casefold().strip()
    results = []

        for row in addresses:
        address = row.get("STD", "")

        if query in address.casefold():
            results.append({
                "address": address,
                "object_code": row.get("KODS", "")
            })

            if len(results) >= 10:
                break

    return {"query": q, "results": results}
