import csv
import io
import logging
import sqlite3
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from google.cloud import storage


# --------------------------------------------------
# CONFIG
# --------------------------------------------------

BUCKET = "pacik-lv-address-data"
FILE = "aw_eka.csv"
BUILDINGS_DB_FILE = "buildings.db"
BUILDINGS_DB_PATH = "/tmp/buildings.db"
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
        bucket = client.bucket(BUCKET)

        # BUILDINGS DATABASE
        buildings_blob = bucket.blob(BUILDINGS_DB_FILE)
        buildings_blob.download_to_filename(BUILDINGS_DB_PATH)

        logger.info("Buildings DB lejupielādēta")

        # ADDRESS DATA
        address_blob = bucket.blob(FILE)
        address_raw = address_blob.download_as_bytes()
        address_decoded = address_raw.decode("utf-8-sig")

        address_reader = csv.DictReader(
            io.StringIO(address_decoded),
            delimiter=","
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

        # TRANSACTION DATA
        transactions_blob = bucket.blob(
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
def get_building_by_varis_code(varis_code: str):
    con = sqlite3.connect(BUILDINGS_DB_PATH)
    con.row_factory = sqlite3.Row

    try:
        row = con.execute(
            "SELECT * FROM buildings WHERE varis_code = ?",
            (varis_code,)
        ).fetchone()

        if row is None:
            return None

        return dict(row)
    finally:
        con.close()


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
# TRANSACTION COLUMNS
# --------------------------------------------------

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
                    "(B) Ekspluatācijas uzsākšanas gads(saraksts)_DTG_Z_E",
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


# --------------------------------------------------
# BUILDING SAMPLE
# --------------------------------------------------

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
            "address": row.get(
                "Adreses standartpieraksts_DTG",
                ""
            ),
            "building_year": row.get(
                "(B) Ekspluatācijas uzsākšanas gads(saraksts)_DTG_Z_E",
                ""
            ),
            "wall_material": row.get(
                "(B) Ārsienu un karkasu materiāls(saraksts)_DTG_Z_E",
                ""
            ),
            "floors": row.get(
                "(B) Virszemes stāvu skaits_DTG_Z_E",
                ""
            )
        })

    return {
        "results": results
    }


# --------------------------------------------------
# BUILDING INFO
# --------------------------------------------------

@app.get("/building-info")
def building_info(
    q: str = Query(min_length=3)
):
    if not transactions:
        raise HTTPException(
            status_code=503,
            detail="Darījumu dati nav ielādēti"
        )

    query = q.casefold().strip().rstrip(",")
    results = []

    for row in transactions:
        address = (
            row.get(
                "Adreses standartpieraksts_DTG",
                ""
            )
            or ""
        )

        address_normalized = address.casefold().strip()

        # Adresei jāsākas precīzi ar meklēto ielu + mājas numuru.
        if not address_normalized.startswith(query):
            continue

        # Neļaujam "100" sakrist ar "100A", "100B", "1000" utt.
        remaining = address_normalized[len(query):]

        if remaining:
            first_char = remaining[0]

            # Pēc precīza mājas numura sagaidām komatu.
            # Piemēram: "Brīvības iela 100, Rīga..."
            if first_char != ",":
                continue

        results.append({
            "address": address,
            "building_year": row.get(
                "(B) Ekspluatācijas uzsākšanas gads(saraksts)_DTG_Z_E",
                ""
            ),
            "wall_material": row.get(
                "(B) Ārsienu un karkasu materiāls(saraksts)_DTG_Z_E",
                ""
            ),
            "floors": row.get(
                "(B) Virszemes stāvu skaits_DTG_Z_E",
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

# --------------------------------------------------
# VALUATION
# --------------------------------------------------

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
    # Atrodam ēku pēc ievadītās adreses
    target_building = None
    target_varis_code = ""

    query_address = q.casefold().strip()

    for address_row in addresses:
        std_address = (address_row.get("STD", "") or "").casefold().strip()

        if std_address.startswith(query_address + ","):
            target_varis_code = (address_row.get("KODS", "") or "").strip()
            break

    if target_varis_code:
        target_building = get_building_by_varis_code(target_varis_code)
    city_query = city.casefold().strip()

    query_parts = q.strip().rsplit(" ", 1)

    street_query = query_parts[0].casefold().strip()

    house_number = ""

    if len(query_parts) == 2:
        house_number = query_parts[1].casefold().strip()

    # --------------------------------------------------
    # PALĪGFUNKCIJAS
    # --------------------------------------------------

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
            row.get(
                "Adreses standartpieraksts_DTG",
                ""
            )
            or ""
        )

        price = parse_number(
            row.get(
                "Darījuma summa_DTG",
                ""
            )
        )

        apartment_area = parse_number(
            row.get(
                "Dzīvokļa platība_DTG",
                ""
            )
        )

        if price is None or apartment_area is None:
            return None

        if price <= 0 or apartment_area <= 0:
            return None

        if (
            apartment_area < area * 0.8
            or apartment_area > area * 1.2
        ):
            return None

        price_per_m2 = price / apartment_area

        if price_per_m2 < 300 or price_per_m2 > 10000:
            return None

        return {
            "address": address,
            "price": price,
            "area": apartment_area,
            "price_per_m2": round(
                price_per_m2,
                2
            ),
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
                "(B) Ekspluatācijas uzsākšanas gads(saraksts)_DTG_Z_E",
                ""
            ),
            "building_material": row.get(
                "(B) Ārsienu un karkasu materiāls(saraksts)_DTG_Z_E",
                ""
            )
        }

    def normalize_material(value):
        """Map VZD and transaction material labels to broad comparable groups."""
        material = (value or "").casefold().strip()

        if not material:
            return ""

        if "vieglbeton" in material:
            return "lightweight_concrete"
        if "dzelzsbeton" in material or "beton" in material:
            return "concrete"
        if "ķieģe" in material or "mūr" in material or "akmens" in material:
            return "masonry"
        if "koka" in material or material == "koks":
            return "wood"

        return material

    def is_duplicate(item, items):
        return any(
            existing["address"] == item["address"]
            and existing["price"] == item["price"]
            and existing["area"] == item["area"]
            and existing["date"] == item["date"]
            for existing in items
        )

    # --------------------------------------------------
    # 1. MEKLĒJAM KONKRĒTAJĀ MĀJĀ
    # --------------------------------------------------

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

            if not address_normalized.startswith(
                target_address_start
            ):
                continue

            remaining = address_normalized[
                len(target_address_start):
            ]

            if remaining and not (
                remaining.startswith(",")
                or remaining.startswith(" -")
            ):
                continue

            item = make_comparable(row)

            if item is None:
                continue

            if not is_duplicate(
                item,
                building_comparables
            ):
                building_comparables.append(item)

    # --------------------------------------------------
    # 2. JA MĀJĀ PAR MAZ DATU, MEKLĒJAM TAJĀ PAŠĀ IELĀ
    # --------------------------------------------------

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
                            # Ja zinām vērtējamās ēkas parametrus,
            # atlasām līdzīga vecuma un materiāla ēkas
            if target_building:
                target_year = parse_number(
                    target_building.get("exploit_year")
                )
                comparable_year = parse_number(
                    item.get("building_year")
                )

                if target_year and comparable_year:
                    if abs(target_year - comparable_year) > 20:
                        continue

                target_material = normalize_material(
                    target_building.get("material", "")
                )
                comparable_material = normalize_material(
                    item.get("building_material", "")
                )

                # VZD and transaction datasets describe the same material
                # differently (for example "mūra" vs "ķieģeļu mūris").
                # Compare normalized groups instead of raw text.
                if target_material and comparable_material:
                    if target_material != comparable_material:
                        continue

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

    # --------------------------------------------------
    # SAKĀRTOJAM PĒC LĪDZĪBAS
    # --------------------------------------------------
    # Darījumi konkrētajā mājā vienmēr paliek ar augstāko prioritāti.
    # Citu tās pašas ielas māju darījumus kārtojam pēc ēkas vecuma
    # un dzīvokļa platības līdzības, nevis CSV faila nejaušās secības.

    target_year = None
    if target_building:
        target_year = parse_number(
            target_building.get("exploit_year")
        )

    def similarity_score(item, same_building=False):
        comparable_year = parse_number(
            item.get("building_year")
        )

        area_difference = abs(item["area"] - area) / area
        area_score = max(0.0, 1.0 - area_difference / 0.20)

        if target_year is not None and comparable_year is not None:
            year_difference = abs(target_year - comparable_year)
            year_score = max(0.0, 1.0 - year_difference / 20.0)
        else:
            year_score = 0.25

        # Area is the strongest apartment-level signal in the data we have.
        # Building age adds context; an exact-building transaction gets a
        # substantial bonus because location/building quality match exactly.
        score = (
            area_score * 0.60
            + year_score * 0.40
            + (1.0 if same_building else 0.0)
        )

        return round(score, 4)

    for item in building_comparables:
        item["similarity_score"] = similarity_score(
            item,
            same_building=True
        )

    for item in street_comparables:
        item["similarity_score"] = similarity_score(item)

    building_comparables.sort(
        key=lambda item: item["similarity_score"],
        reverse=True
    )
    street_comparables.sort(
        key=lambda item: item["similarity_score"],
        reverse=True
    )

    # --------------------------------------------------
    # APVIENOJAM SALĪDZINĀMOS
    # --------------------------------------------------

    comparable = (
        building_comparables
        + street_comparables
    )

    if not comparable:
        raise HTTPException(
            status_code=404,
            detail="Nav atrasti piemēroti salīdzināmie darījumi"
        )

    # --------------------------------------------------
    # IZMETAM CENU EKSTRĒMUS
    # --------------------------------------------------

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

    filtered_comparable = []

    for item in comparable:
        if (
            item["price_per_m2"]
            >= median_price_per_m2 * 0.65
            and item["price_per_m2"]
            <= median_price_per_m2 * 1.35
        ):
            filtered_comparable.append(item)

    if len(filtered_comparable) >= 3:
        comparable = filtered_comparable

    # --------------------------------------------------
    # IEROBEŽOJAM SALĪDZINĀMO SKAITU
    # --------------------------------------------------

    comparable = comparable[:20]

    # --------------------------------------------------
    # APRĒĶINS
    # --------------------------------------------------

    # Weighted estimate: the most similar transactions influence the
    # valuation more than weaker comparables. Keep a small minimum weight so
    # valid filtered transactions still contribute without dominating.
    weights = [
        max(item.get("similarity_score", 0.0), 0.10)
        for item in comparable
    ]
    total_weight = sum(weights)

    average_price_per_m2 = sum(
        item["price_per_m2"] * weight
        for item, weight in zip(comparable, weights)
    ) / total_weight

    estimated_value = (
        average_price_per_m2 * area
    )

    estimated_min = estimated_value * 0.95
    estimated_max = estimated_value * 1.05

    # --------------------------------------------------
    # STATISTIKA
    # --------------------------------------------------

    building_count = sum(
        1
        for item in comparable
        if item in building_comparables
    )

    street_count = (
        len(comparable) - building_count
    )

    # --------------------------------------------------
    # ATBILDE
    # --------------------------------------------------

    return {
        "query": q,
        "city": city,
        "area": area,
        "target_building": target_building,
        "target_varis_code": target_varis_code or None,
        "selection_method": "weighted_similarity_v1",
        "comparable_count": len(comparable),
        "building_comparable_count": building_count,
        "street_comparable_count": street_count,
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
@app.get("/building-by-code")
def building_by_code(
    varis_code: str = Query(min_length=1)
):
    building = get_building_by_varis_code(varis_code)

    if building is None:
        raise HTTPException(
            status_code=404,
            detail="Ēka nav atrasta"
        )

    return building
@app.get("/building-by-address")
def building_by_address(
    q: str = Query(min_length=3)
):
    if not addresses:
        raise HTTPException(
            status_code=503,
            detail="Adrešu dati nav ielādēti"
        )

    query = q.casefold().strip().rstrip(",")

    # Atrodam precīzu adresi
    for row in addresses:
        address = (row.get("STD", "") or "").strip()
        address_normalized = address.casefold()

        # Noņemam pasta indeksu salīdzināšanai
        address_without_postcode = address_normalized
        if ", lv-" in address_without_postcode:
            address_without_postcode = address_without_postcode.split(", lv-")[0]

        if (
            address_normalized == query
            or address_without_postcode == query
        ):
            varis_code = (row.get("KODS", "") or "").strip()

            building = get_building_by_varis_code(varis_code)

            if building is None:
                raise HTTPException(
                    status_code=404,
                    detail="Ēkas dati nav atrasti"
                )

            return {
                "address": address,
                "object_code": varis_code,
                "building": building
            }

    raise HTTPException(
        status_code=404,
        detail="Adrese nav atrasta"
    )
@app.get("/building-db-columns")
def building_db_columns():
    con = sqlite3.connect(BUILDINGS_DB_PATH)

    try:
        columns = con.execute(
            "PRAGMA table_info(buildings)"
        ).fetchall()

        sample = con.execute(
            "SELECT * FROM buildings LIMIT 5"
        ).fetchall()

        column_names = [column[1] for column in columns]

        return {
            "columns": column_names,
            "sample": [
                dict(zip(column_names, row))
                for row in sample
            ]
        }

    finally:
        con.close()
@app.get("/building-material-stats")
def building_material_stats():
    con = sqlite3.connect(BUILDINGS_DB_PATH)

    try:
        total = con.execute(
            "SELECT COUNT(*) FROM buildings"
        ).fetchone()[0]

        with_material = con.execute(
            """
            SELECT COUNT(*)
            FROM buildings
            WHERE material IS NOT NULL
              AND TRIM(material) != ''
            """
        ).fetchone()[0]

        samples = con.execute(
            """
            SELECT
                varis_code,
                cadastre_nr,
                building_name,
                exploit_year,
                material
            FROM buildings
            WHERE material IS NOT NULL
              AND TRIM(material) != ''
            LIMIT 20
            """
        ).fetchall()

        return {
            "total_buildings": total,
            "buildings_with_material": with_material,
            "buildings_without_material": total - with_material,
            "material_percent": round(
                with_material / total * 100, 2
            ) if total else 0,
            "samples": [
                {
                    "varis_code": row[0],
                    "cadastre_nr": row[1],
                    "building_name": row[2],
                    "exploit_year": row[3],
                    "material": row[4]
                }
                for row in samples
            ]
        }

    finally:
        con.close()

