import csv
import io
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from google.cloud import storage


# --------------------------------------------------
# CONFIG
# --------------------------------------------------

BUCKET = "pacik-lv-address-data"
FILE = "aw_eka.csv"
TRANSACTIONS_FILE = "transactions/TG.csv"

addresses = []
transactions = []

logger = logging.getLogger(__name__)


# --------------------------------------------------
# LOAD DATA
# --------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    global addresses, transactions

    try:
        client = storage.Client()

        # -------------------------
        # ADDRESS DATA
        # -------------------------

        address_blob = client.bucket(BUCKET).blob(FILE)
        address_raw = address_blob.download_as_bytes()

        address_decoded = address_raw.decode("utf-8-sig")

        address_reader = csv.DictReader(
            io.StringIO(address_decoded),
            delimiter=";"
        )

        if not address_reader.fieldnames:
            raise ValueError(
                "Adrešu CSV failā nav atrastas kolonnas"
            )

        addresses = list(address_reader)

        logger.info(
            "Ielādēti %s adrešu ieraksti",
            len(addresses)
        )

        # -------------------------
        # TRANSACTION DATA
        # -------------------------

        transactions_blob = client.bucket(BUCKET).blob(
            TRANSACTIONS_FILE
        )

        transactions_raw = transactions_blob.download_as_bytes()

        transactions_decoded = transactions_raw.decode("utf-16")

        transactions_reader = csv.DictReader(
            io.StringIO(transactions_decoded),
            delimiter=","
        )

        if not transactions_reader.fieldnames:
            raise ValueError(
                "Darījumu CSV failā nav atrastas kolonnas"
            )

        transactions = [
            row
            for row in transactions_reader
            if row
        ]

        logger.info(
            "Ielādēti %s darījumu ieraksti",
            len(transactions)
        )

    except Exception:
        logger.exception(
            "Neizdevās ielādēt adrešu vai darījumu datus"
        )

        addresses = []
        transactions = []

    yield


# --------------------------------------------------
# FASTAPI
# --------------------------------------------------

app = FastAPI(
    title="PACIK.LV Address API",
    lifespan=lifespan
)


# --------------------------------------------------
# CORS
# --------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------
# HOME
# --------------------------------------------------

@app.get("/")
def home():
    return {
        "status": "ok",
        "service": "PACIK.LV Address API",
        "loaded_records": len(addresses),
        "transaction_records": len(transactions)
    }


# --------------------------------------------------
# HEALTH
# --------------------------------------------------

@app.get("/health")
def health():
    return {
        "status": "ok",
        "loaded_records": len(addresses),
        "columns": (
            list(addresses[0].keys())
            if addresses
            else []
        ),
        "transaction_records": len(transactions),
        "transaction_columns": (
            list(transactions[0].keys())
            if transactions
            else []
        )
    }


# --------------------------------------------------
# ADDRESS SEARCH
# --------------------------------------------------

@app.get("/search")
def search_address(
    q: str = Query(min_length=3)
):
    if not addresses:
        raise HTTPException(
            status_code=503,
            detail="Adrešu dati nav ielādēti"
        )

    query = q.casefold().strip()

    results = []

    for row in addresses:

        address = row.get("STD", "") or ""

        if query in address.casefold():

            results.append({
                "address": address,
                "object_code": row.get("KODS", "")
            })

            if len(results) >= 10:
                break

    return {
        "query": q,
        "results": results
    }


# --------------------------------------------------
# ADDRESS SAMPLE
# --------------------------------------------------

@app.get("/sample")
def sample():
    if not addresses:
        raise HTTPException(
            status_code=503,
            detail="Adrešu dati nav ielādēti"
        )

    return addresses[0]


# --------------------------------------------------
# TRANSACTION SAMPLE
# --------------------------------------------------

@app.get("/transaction-sample")
def transaction_sample():
    if not transactions:
        raise HTTPException(
            status_code=503,
            detail="Darījumu dati nav ielādēti"
        )

    return {
        "count": len(transactions),
        "first": transactions[0],
        "second": (
            transactions[1]
            if len(transactions) > 1
            else None
        )
    }


# --------------------------------------------------
# TRANSACTION SEARCH
# --------------------------------------------------

@app.get("/transactions/search")
def search_transactions(
    q: str = Query(min_length=3)
):
    if not transactions:
        raise HTTPException(
            status_code=503,
            detail="Darījumu dati nav ielādēti"
        )

    query = q.casefold().strip()

    results = []

    for row in transactions:

        address = (
            row.get(
                "Adreses standartpieraksts_DTG",
                ""
            )
            or ""
        )

        if query in address.casefold():

            results.append({
                "address": address,
                "date": row.get(
                    "Darījuma datums_DTG",
                    ""
                ),
                "price": row.get(
                    "Darījuma summa_DTG",
                    ""
                ),
                "apartment_area": row.get(
                    "Dzīvokļa platība_DTG",
                    ""
                ),
                "total_area": row.get(
                    "Telpu grupas kopplatība_DTG",
                    ""
                ),
                "rooms": row.get(
                    "Dzīvojamo telpu skaits_DTG",
                    ""
                ),
                "floor": row.get(
                    "Zemākais stāvs_DTG",
                    ""
                ),
                "building_year": row.get(
                    "Ekspluatācijas uzsākšanas gads(saraksts)_DTG_Z_E",
                    ""
                )
            })

            if len(results) >= 20:
                break

    return {
        "query": q,
        "count": len(results),
        "results": results
    }
@app.get("/valuation")
def valuation(
    q: str = Query(min_length=3),
    area: float = Query(gt=0),
    city: str = Query(min_length=2)
):
    query = q.casefold().strip()
    comparable = []

    for row in transactions:
        address = row.get("Adreses standartpieraksts_DTG", "")

        if query not in address.casefold():
            continue
                

        if city.casefold() not in address.casefold():
            continue
    

        try:
            price = float(
                row.get("Darījuma summa_DTG", "")
                .replace(" ", "")
                .replace(",", ".")
            )

            apartment_area = float(
                row.get("Dzīvokļa platība_DTG", "")
                .replace(" ", "")
                .replace(",", ".")
            )

            if price <= 0 or apartment_area <= 0:
                continue

            price_per_m2 = price / apartment_area

            comparable.append({
                "address": address,
                "price": price,
                "area": apartment_area,
                "price_per_m2": round(price_per_m2, 2)
            })

        except (ValueError, TypeError):
            continue

    if not comparable:
        raise HTTPException(
            status_code=404,
            detail="Nav atrasti piemēroti salīdzināmie darījumi"
        )

    average_price_per_m2 = sum(
        item["price_per_m2"] for item in comparable
    ) / len(comparable)

    estimated_value = average_price_per_m2 * area

    return {
        "query": q,
        "area": area,
        "comparable_count": len(comparable),
        "average_price_per_m2": round(average_price_per_m2, 2),
        "estimated_value": round(estimated_value),
        "comparables": comparable[:10]
    }
