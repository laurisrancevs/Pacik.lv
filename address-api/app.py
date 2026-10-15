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

    return {
        "columns": list(addresses[0].keys())
    }


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
        "first": transactions[0]
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


# ---------------------------------------------------------
# VALUATION
# ---------------------------------------------------------
@app.get("/transaction-columns")
def transaction_columns():
    if not transactions:
        raise HTTPException(
            status_code=503,
            detail="Darījumu dati nav ielādēti"
        )

    return {
        "column_count": len(transactions[0].keys()),
        "columns": list(transactions[0].keys())
    }
@app.get("/transaction-sample")
def transaction_sample():
    if not transactions:
        raise HTTPException(
            status_code=503,
            detail="Darījumu dati nav ielādēti"
        )

    return {
        "sample": transactions[:5]
    }
 @app.get("/building-sample")
 def building_sample():
     if not transactions:
         raise HTTPException(
             status_code=503,
             detail="Darījumu dati nav ielādēti"
         )

    results = []

    for row in transactions[:100]:
        results.append({
            "address": row.get("Adreses standartpieraksts_DTG", ""),
            "building_year": row.get(
                "Ekspluatācijas uzsākšanas gads(saraksts)_DTG_Z_E", ""
            ),
            "wall_material": row.get(
                "Ārsienu un karkasu materiāls(saraksts)_DTG_Z_E", ""
            ),
            "floors": row.get(
                "Virszemes stāvu skaits_DTG_Z_E", ""
            )
        })

    return {"results": results}
    @app.get("/building-info")
def building_info(
    q: str = Query(min_length=3)
):
    query = q.casefold().strip()

    results = []

    for row in transactions:
        address = row.get(
            "Adreses standartpieraksts_DTG",
            ""
        )

        if query not in address.casefold():
            continue

        results.append({
            "address": address,
            "building_year": row.get(
                "Ekspluatācijas uzsākšanas gads(saraksts)_DTG_Z_E",
                ""
            ),
            "wall_material": row.get(
                "Ārsienu un karkasu materiāls(saraksts)_DTG_Z_E",
                ""
            ),
            "floors": row.get(
                "Virszemes stāvu skaits_DTG_Z_E",
                ""
            )
        })

        if len(results) >= 20:
            break

    return {
        "query": q,
        "results": results
    }
@app.get("/valuation")
def valuation(
    q: str = Query(min_length=3),
    area: float = Query(gt=0),
    city: str = Query(min_length=2)
):
    if not transactions:
        raise HTTPException(
            status_code=503,
            detail="Darījumu dati nav ielādēti"
        )

    city_query = city.casefold().strip()

    # Atdalām ielu un mājas numuru.
    # Piemērs: "Brīvības iela 100"
    # street_query = "brīvības iela"
    # house_number = "100"
    query_parts = q.strip().rsplit(" ", 1)

    street_query = query_parts[0].casefold().strip()

    house_number = ""
    if len(query_parts) == 2:
        house_number = query_parts[1].casefold().strip()

    # -----------------------------------------------------
    # PALĪGFUNKCIJAS
    # -----------------------------------------------------

    def parse_number(value):
        if value is None:
            return None

        try:
            value = str(value).strip()

            if not value:
                return None

            return float(
                value
                .replace(" ", "")
                .replace(",", ".")
            )

        except (ValueError, TypeError):
            return None


    def make_comparable(row):
        address = (
            row.get("Adreses standartpieraksts_DTG", "")
            or ""
        )

        price = parse_number(
            row.get("Darījuma summa_DTG", "")
        )

        apartment_area = parse_number(
            row.get("Dzīvokļa platība_DTG", "")
        )

        if price is None or apartment_area is None:
            return None

        if price <= 0 or apartment_area <= 0:
            return None

        # Salīdzinām tikai līdzīga izmēra dzīvokļus:
        # +/- 20% no vērtējamā dzīvokļa platības
        if (
            apartment_area < area * 0.8
            or apartment_area > area * 1.2
        ):
            return None

        price_per_m2 = price / apartment_area

        # Aizsardzība pret acīmredzami nereālām vērtībām
        if price_per_m2 < 300 or price_per_m2 > 10000:
            return None

        return {
            "address": address,
            "price": price,
            "area": apartment_area,
            "price_per_m2": round(price_per_m2, 2),
            "date": row.get(
                "Darījuma datums_DTG",
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
        }


    def is_duplicate(item, items):
        return any(
            existing["address"] == item["address"]
            and existing["price"] == item["price"]
            and existing["area"] == item["area"]
            and existing["date"] == item["date"]
            for existing in items
        )


    # -----------------------------------------------------
    # 1. MEKLĒJAM KONKRĒTAJĀ MĀJĀ
    # -----------------------------------------------------

    building_comparables = []

    if house_number:

        target_address_start = (
            f"{street_query} {house_number}"
        )

        for row in transactions:

            address = (
                row.get(
                    "Adreses standartpieraksts_DTG",
                    ""
                )
                or ""
            )

            address_normalized = (
                address.casefold().strip()
            )

            if city_query not in address_normalized:
                continue

            # Adresei jāsākas ar konkrēto ielu + mājas numuru.
            # Tas samazina risku, ka "100" sakrīt ar "1000".
            if not address_normalized.startswith(
                target_address_start
            ):
                continue

            # Pēc mājas numura drīkst būt komats vai atstarpe,
            # bet ne nākamais cipars.
            remaining = address_normalized[
                len(target_address_start):
            ]

            if remaining:
                first_char = remaining[0]

                if first_char.isdigit():
                    continue

            item = make_comparable(row)

            if item is None:
                continue

            if not is_duplicate(
                item,
                building_comparables
            ):
                building_comparables.append(item)


    # -----------------------------------------------------
    # 2. JA MĀJĀ PAR MAZ DATU — MEKLĒJAM TAJĀ PAŠĀ IELĀ
    # -----------------------------------------------------

    street_comparables = []

    if len(building_comparables) < 5:

        for row in transactions:

            address = (
                row.get(
                    "Adreses standartpieraksts_DTG",
                    ""
                )
                or ""
            )

            address_normalized = (
                address.casefold().strip()
            )

            if street_query not in address_normalized:
                continue

            if city_query not in address_normalized:
                continue

            item = make_comparable(row)

            if item is None:
                continue

            # Neatkārtojam darījumus, kas jau atrasti
            # konkrētajā mājā
            if is_duplicate(
                item,
                building_comparables
            ):
                continue

            if is_duplicate(
                item,
                street_comparables
            ):
                continue

            street_comparables.append(item)


    # -----------------------------------------------------
    # APVIENOJAM SALĪDZINĀMOS
    # -----------------------------------------------------

    comparable = (
        building_comparables
        + street_comparables
    )

    if not comparable:
        raise HTTPException(
            status_code=404,
            detail="Nav atrasti piemēroti salīdzināmie darījumi"
        )


    # -----------------------------------------------------
    # IZMETAM CENU EKSTRĒMUS
    # -----------------------------------------------------

    prices_per_m2 = sorted(
        item["price_per_m2"]
        for item in comparable
    )

    median_index = len(prices_per_m2) // 2

    if len(prices_per_m2) % 2 == 0:
        median_price_per_m2 = (
            prices_per_m2[median_index - 1]
            + prices_per_m2[median_index]
        ) / 2
    else:
        median_price_per_m2 = (
            prices_per_m2[median_index]
        )

    # Atstājam darījumus +/- 35% robežās
    # no mediānas
    filtered_comparable = []

    for item in comparable:

        if (
            item["price_per_m2"]
            >= median_price_per_m2 * 0.65
            and item["price_per_m2"]
            <= median_price_per_m2 * 1.35
        ):
            filtered_comparable.append(item)

    # Ja filtrēšana atstāj pārāk maz datu,
    # izmantojam sākotnējo sarakstu
    if len(filtered_comparable) >= 3:
        comparable = filtered_comparable


    # -----------------------------------------------------
    # IEROBEŽOJAM SALĪDZINĀMO SKAITU
    # -----------------------------------------------------

    # Konkrētās mājas darījumiem dodam priekšroku.
    comparable = comparable[:20]


    # -----------------------------------------------------
    # APRĒĶINS
    # -----------------------------------------------------

    average_price_per_m2 = sum(
        item["price_per_m2"]
        for item in comparable
    ) / len(comparable)

    estimated_value = (
        average_price_per_m2 * area
    )

    # Aptuvenais vērtējuma diapazons
    estimated_min = estimated_value * 0.95
    estimated_max = estimated_value * 1.05


    # -----------------------------------------------------
    # STATISTIKA
    # -----------------------------------------------------

    building_count = sum(
        1
        for item in comparable
        if item in building_comparables
    )

    street_count = (
        len(comparable) - building_count
    )


    # -----------------------------------------------------
    # ATBILDE
    # -----------------------------------------------------

    return {
        "query": q,
        "city": city,
        "area": area,

        "comparable_count": len(comparable),

        "building_comparable_count":
            building_count,

        "street_comparable_count":
            street_count,

        "median_price_per_m2": round(
            median_price_per_m2,
            2
        ),

        "average_price_per_m2": round(
            average_price_per_m2,
            2
        ),

        "estimated_value": round(
            estimated_value
        ),

        "estimated_min": round(
            estimated_min
        ),

        "estimated_max": round(
            estimated_max
        ),

        "comparables": comparable[:10]
    }
