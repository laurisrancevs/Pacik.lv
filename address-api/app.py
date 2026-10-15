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
            "Darījumu CSV kolonnas: %s",
            transactions_reader.fieldnames
)
        logger.info(
            "Ielādēti %s darījumu ieraksti",
            len(transactions)
        )
