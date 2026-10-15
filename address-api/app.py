

import csv
import io
import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Query, HTTPException
from google.cloud import storage
from fastapi.middleware.cors import CORSMiddleware
BUCKET = "pacik-lv-address-data"
FILE = "aw_eka.csv"
TRANSACTIONS_FILE = "transactions/TG.csv"
addresses = []
transactions = []
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global addresses, transactions

    try:
        client = storage.Client()

        blob = client.bucket(BUCKET).blob(FILE)
        raw = blob.download_as_bytes()

        decoded = raw.decode("utf-8-sig")
        reader = csv.DictReader(
            io.StringIO(decoded),
            delimiter=";"
        )

        if not reader.fieldnames:
            raise ValueError("CSV failā nav atrastas kolonnas")

        logger.info("CSV kolonnas: %s", reader.fieldnames)

        addresses = list(reader)
        logger.info(
            "Ielādēti %s adrešu ieraksti",
            len(addresses)
        )

        transactions_blob = client.bucket(BUCKET).blob(
            TRANSACTIONS_FILE
        )
        transactions_raw = transactions_blob.download_as_bytes()

        transactions_decoded = transactions_raw.decode("utf-8-sig")
        transactions_reader = csv.DictReader(
            io.StringIO(transactions_decoded),
            delimiter=";"
        )

        transactions = list(transactions_reader)

        logger.info(
            "Ielādēti %s darījumu ieraksti",
            len(transactions)
        )

    except Exception:
        logger.exception(
            "Neizdevās ielādēt adrešu un darījumu datus"
        )
        addresses = []
        transactions = []

    yield


app = FastAPI(
    title="PACIK.LV Address API",
    lifespan=lifespan
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
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
        "columns": list(addresses[0].keys()) if addresses else [],
        "transaction_records": len(transactions),
"transaction_columns": list(transactions[0].keys()) if transactions else []
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
@app.get("/sample")
def sample():
    if not addresses:
        raise HTTPException(status_code=503, detail="Adrešu dati nav ielādēti")

    return addresses[0]
