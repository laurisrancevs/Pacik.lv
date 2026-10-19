import csv
import io
import logging
import sqlite3
from datetime import datetime, date
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
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
address_coordinates = {}
address_coordinates_without_postcode = {}

logger = logging.getLogger(__name__)


# --------------------------------------------------
# LOAD DATA
# --------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    global addresses, transactions, address_coordinates, address_coordinates_without_postcode

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

        # Build coordinate indexes once at startup. Valuation requests must not
        # rebuild or linearly scan all ~611k addresses for every comparable.
        address_coordinates = {}
        address_coordinates_without_postcode = {}

        for row in addresses:
            std = (row.get("STD", "") or "").casefold().strip()
            if not std:
                continue

            try:
                x_raw = str(row.get("KOORD_X", "") or "").strip().replace(" ", "").replace(",", ".")
                y_raw = str(row.get("KOORD_Y", "") or "").strip().replace(" ", "").replace(",", ".")
                if not x_raw or not y_raw:
                    continue
                coords = (float(x_raw), float(y_raw))
            except (ValueError, TypeError):
                continue

            address_coordinates[std] = coords
            address_coordinates_without_postcode[std.split(", lv-")[0]] = coords

        logger.info(
            "Izveidots koordinātu indekss %s adresēm",
            len(address_coordinates)
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
        address_coordinates = {}
        address_coordinates_without_postcode = {}

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


@app.get("/pacik-riga-hero.png", include_in_schema=False)
def pacik_riga_hero():
    return FileResponse("/app/pacik-riga-hero.png", media_type="image/png")

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


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def home():
    try:
        with open("/app/index.html", "r", encoding="utf-8") as page:
            return HTMLResponse(content=page.read(), status_code=200)
    except Exception:
        logger.exception("PACIK frontend index.html could not be served")
        raise HTTPException(status_code=503, detail="PACIK.LV frontend is temporarily unavailable")

@app.get("/api")
def api_status():
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
    city: str = Query(min_length=2),
    property_type: str = Query(default="Dzīvoklis")
):
    if not transactions:
        raise HTTPException(
            status_code=503,
            detail="Darījumu dati nav ielādēti"
        )

    # Pašreizējais modelis ir trenēts/veidots no dzīvokļu darījumu laukiem.
    # Neļaujam māju, zemes vai komercīpašumu ievadi kļūdaini novērtēt kā dzīvokli.
    if property_type.casefold().strip() not in {"dzīvoklis", "dzivoklis", "apartment"}:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "unsupported_property_type",
                "message": "Automātiskais modelis šobrīd droši atbalsta dzīvokļus."
            }
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

    # Safety guard: an address code can sometimes resolve to a non-residential
    # building (for example a school) even though the user is valuing an
    # apartment. Never return a confident apartment valuation from such a
    # mismatch.
    if target_building:
        building_name = (
            target_building.get("building_name", "") or ""
        ).casefold()
        use_kind = (
            target_building.get("use_kind", "") or ""
        ).casefold()

        residential_markers = (
            "dzīvojam",
            "dzīvok",
        )
        is_residential = any(
            marker in building_name or marker in use_kind
            for marker in residential_markers
        )

        if not is_residential:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "building_type_mismatch",
                    "message": (
                        "Adrese ir atrasta, bet VZD piesaistītā ēka nav "
                        "dzīvojamā ēka. Automātisks dzīvokļa vērtējums "
                        "netiek veikts, lai nerādītu maldinošu cenu."
                    ),
                    "target_varis_code": target_varis_code,
                    "building_name": target_building.get("building_name"),
                    "use_kind": target_building.get("use_kind"),
                },
            )

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

    def make_comparable(row, area_tolerance=0.20):
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
            apartment_area < area * (1.0 - area_tolerance)
            or apartment_area > area * (1.0 + area_tolerance)
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


    def parse_transaction_date(value):
        """Parse known TG transaction date formats without guessing ambiguous dates."""
        raw = (value or "").strip()
        if not raw:
            return None

        for fmt in ("%Y-%m-%d", "%Y.%m.%d", "%d.%m.%Y", "%d/%m/%Y"):
            try:
                return datetime.strptime(raw[:10], fmt).date()
            except ValueError:
                pass
        return None

    def recency_weight(item):
        """Give recent registered sales more influence while retaining older evidence."""
        transaction_date = parse_transaction_date(item.get("date"))
        if transaction_date is None:
            return 0.70

        age_days = max(0, (date.today() - transaction_date).days)
        age_months = age_days / 30.4375

        if age_months <= 6:
            return 1.00
        if age_months <= 12:
            return 0.90
        if age_months <= 24:
            return 0.75
        if age_months <= 36:
            return 0.60
        return 0.45

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
    # 2. PAKĀPENISKA SALĪDZINĀMO ATLASE TAJĀ PAŠĀ IELĀ
    # --------------------------------------------------

    # Hierarhija:
    #   A) tā pati ēka;
    #   B) tā pati iela, tas pats materiāls, ēkas vecums ±5 gadi;
    #   C) ja datu vēl par maz, tā pati iela, tas pats materiāls,
    #      ēkas vecums ±20 gadi.
    #
    # Plašāku apkaimes līmeni nepievienojam, kamēr datos nav drošas
    # apkaimes/ģeogrāfiskās sasaistes. Tas ir apzināti konservatīvi.

    for item in building_comparables:
        item["selection_tier"] = "same_building"

    street_comparables = []

    def collect_street_comparables(max_year_difference):
        for row in transactions:
            address = (
                row.get(
                    "Adreses standartpieraksts_DTG",
                    ""
                )
                or ""
            )
            address_normalized = address.casefold().strip()

            # Require the actual street name at the beginning of the address,
            # rather than accepting an arbitrary substring match.
            if not address_normalized.startswith(street_query + " "):
                continue

            if city_query not in address_normalized:
                continue

            item = make_comparable(row)
            if item is None:
                continue

            if target_building:
                target_year_local = parse_number(
                    target_building.get("exploit_year")
                )
                comparable_year = parse_number(
                    item.get("building_year")
                )

                if target_year_local and comparable_year:
                    if abs(target_year_local - comparable_year) > max_year_difference:
                        continue

                target_material = normalize_material(
                    target_building.get("material", "")
                )
                comparable_material = normalize_material(
                    item.get("building_material", "")
                )

                if target_material and comparable_material:
                    if target_material != comparable_material:
                        continue

            if is_duplicate(item, building_comparables):
                continue
            if is_duplicate(item, street_comparables):
                continue

            item["selection_tier"] = (
                "same_street_strict"
                if max_year_difference <= 5
                else "same_street_relaxed"
            )
            street_comparables.append(item)

    if len(building_comparables) < 5:
        collect_street_comparables(5)

    if len(building_comparables) + len(street_comparables) < 5:
        collect_street_comparables(20)

    # --------------------------------------------------
    # 3. ĢEOGRĀFISKĀ TUVUMA SAGATAVOŠANA
    # --------------------------------------------------

    # Coordinate indexes are built once during application startup.
    # Lookup is O(1) instead of rebuilding/scanning ~611k addresses per request.
    target_coordinates = None

    for address_row in addresses:
        std = (address_row.get("STD", "") or "").casefold().strip()
        if std.startswith(query_address + ","):
            target_coordinates = address_coordinates.get(std)
            break

    def distance_to_target(address):
        if target_coordinates is None:
            return None

        normalized = (address or "").casefold().strip()
        coords = address_coordinates.get(normalized)

        if coords is None:
            coords = address_coordinates_without_postcode.get(
                normalized.split(", lv-")[0]
            )

        if coords is None:
            return None

        dx = coords[0] - target_coordinates[0]
        dy = coords[1] - target_coordinates[1]
        return round((dx * dx + dy * dy) ** 0.5)

    # --------------------------------------------------
    # 4. TUVUMĀ ESOŠU LĪDZĪGU ĒKU DARĪJUMI
    # --------------------------------------------------

    nearby_comparables = []

    def collect_nearby_comparables(max_distance_m, max_year_difference=10, require_material=True, tier_name=None, area_tolerance=0.20):
        """Pakāpeniski paplašina ģeogrāfisko loku, saglabājot ēkas līdzību."""
        if target_coordinates is None:
            return

        for row in transactions:
            address = row.get("Adreses standartpieraksts_DTG", "") or ""
            address_normalized = address.casefold().strip()

            if city_query not in address_normalized:
                continue

            item = make_comparable(row, area_tolerance=area_tolerance)
            if item is None:
                continue

            distance_m = distance_to_target(address)
            if distance_m is None or distance_m > max_distance_m:
                continue

            if is_duplicate(item, building_comparables):
                continue
            if is_duplicate(item, street_comparables):
                continue
            if is_duplicate(item, nearby_comparables):
                continue

            if target_building:
                target_year_local = parse_number(target_building.get("exploit_year"))
                comparable_year = parse_number(item.get("building_year"))
                if target_year_local and comparable_year:
                    if abs(target_year_local - comparable_year) > max_year_difference:
                        continue

                if require_material:
                    target_material = normalize_material(target_building.get("material", ""))
                    comparable_material = normalize_material(item.get("building_material", ""))
                    if target_material and comparable_material and target_material != comparable_material:
                        continue

            item["distance_m"] = distance_m
            item["selection_tier"] = tier_name or f"nearby_{max_distance_m}m"
            nearby_comparables.append(item)

    def evidence_count():
        return len(building_comparables) + len(street_comparables) + len(nearby_comparables)

    # A) ļoti līdzīgas ēkas 500 m rādiusā
    if evidence_count() < 5:
        collect_nearby_comparables(500, 10, True, "nearby_500m_strict", 0.20)

    # B) ļoti līdzīgas ēkas 1 km rādiusā
    if evidence_count() < 5:
        collect_nearby_comparables(1000, 15, True, "nearby_1000m_strict", 0.25)

    # C) plašāks apkaimes loks: līdz 2 km, līdzīgs vecums un materiāls
    if evidence_count() < 5:
        collect_nearby_comparables(2000, 25, True, "nearby_2000m_similar", 0.35)

    # D) pēdējais drošais fallback: līdz 3 km, līdzīga vecuma dzīvojamās ēkas.
    # Materiāls drīkst atšķirties, bet šiem darījumiem būs zemāks svars.
    if evidence_count() < 3:
        collect_nearby_comparables(3000, 35, False, "nearby_3000m_fallback", 0.45)

    # E) Sparse-data fallback for unusual/large apartments:
    # widen to 5 km and ±50% area, but keep only valid apartment transactions.
    # These receive a strong tier penalty and therefore cannot dominate stronger evidence.
    if evidence_count() < 3:
        collect_nearby_comparables(5000, 50, False, "nearby_5000m_sparse", 0.50)

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

    for item in nearby_comparables:
        base_score = similarity_score(item)
        distance_m = item.get("distance_m") or 3000
        distance_score = max(0.0, 1.0 - distance_m / 3000.0)

        tier_penalty = {
            "nearby_500m_strict": 1.00,
            "nearby_1000m_strict": 0.92,
            "nearby_2000m_similar": 0.82,
            "nearby_3000m_fallback": 0.68,
            "nearby_5000m_sparse": 0.52,
        }.get(item.get("selection_tier"), 0.75)

        item["similarity_score"] = round(
            (base_score * 0.82 + distance_score * 0.18) * tier_penalty,
            4
        )

    building_comparables.sort(
        key=lambda item: item["similarity_score"],
        reverse=True
    )
    street_comparables.sort(
        key=lambda item: item["similarity_score"],
        reverse=True
    )
    nearby_comparables.sort(
        key=lambda item: item["similarity_score"],
        reverse=True
    )

    # --------------------------------------------------
    # APVIENOJAM SALĪDZINĀMOS
    # --------------------------------------------------

    comparable = (
        building_comparables
        + street_comparables
        + nearby_comparables
    )

    if len(comparable) < 3:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "insufficient_comparables",
                "message": "Drošam automātiskam vērtējumam nav vismaz 3 piemērotu salīdzināmo darījumu.",
                "comparable_count": len(comparable)
            }
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
    for item in comparable:
        item["recency_weight"] = recency_weight(item)

    weights = [
        max(item.get("similarity_score", 0.0), 0.10)
        * item.get("recency_weight", 0.70)
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

    # --------------------------------------------------
    # STATISTIKA + UZTICAMĪBA
    # --------------------------------------------------

    building_count = sum(
        1
        for item in comparable
        if item in building_comparables
    )

    nearby_count = sum(
        1
        for item in comparable
        if item in nearby_comparables
    )

    street_count = (
        len(comparable) - building_count - nearby_count
    )

    comparable_count = len(comparable)
    broad_fallback_count = sum(
        1 for item in comparable
        if item.get("selection_tier") in {"nearby_2000m_similar", "nearby_3000m_fallback", "nearby_5000m_sparse"}
    )
    average_similarity = (
        sum(item.get("similarity_score", 0.0) for item in comparable)
        / comparable_count
    )

    # Confidence reflects the evidence behind the estimate, not a guarantee
    # of the final sale price. Exact-building transactions are especially
    # valuable because location and building quality match directly.
    confidence_points = 0

    if comparable_count >= 10:
        confidence_points += 2
    elif comparable_count >= 5:
        confidence_points += 1

    if building_count >= 3:
        confidence_points += 2
    elif building_count >= 1:
        confidence_points += 1

    if average_similarity >= 1.20:
        confidence_points += 2
    elif average_similarity >= 0.70:
        confidence_points += 1

    if broad_fallback_count > 0:
        confidence_points = min(confidence_points, 4)

    if confidence_points >= 5:
        confidence = "high"
        confidence_label = "Augsta"
        range_percent = 0.05
    elif confidence_points >= 3:
        confidence = "medium"
        confidence_label = "Vidēja"
        range_percent = 0.08
    else:
        confidence = "low"
        confidence_label = "Zema"
        range_percent = 0.12

    estimated_min = estimated_value * (1.0 - range_percent)
    estimated_max = estimated_value * (1.0 + range_percent)

    # --------------------------------------------------
    # ATBILDE
    # --------------------------------------------------

    return {
        "query": q,
        "city": city,
        "area": area,
        "target_building": target_building,
        "target_varis_code": target_varis_code or None,
        "selection_method": "hierarchical_geo_recency_v7_sparse_safe",
        "comparable_count": comparable_count,
        "building_comparable_count": building_count,
        "street_comparable_count": street_count,
        "nearby_comparable_count": nearby_count,
        "target_coordinates": (
            {
                "x": target_coordinates[0],
                "y": target_coordinates[1],
            }
            if target_coordinates else None
        ),
        "selection_tier_counts": {
            "same_building": sum(
                1 for item in comparable
                if item.get("selection_tier") == "same_building"
            ),
            "same_street_strict": sum(
                1 for item in comparable
                if item.get("selection_tier") == "same_street_strict"
            ),
            "same_street_relaxed": sum(
                1 for item in comparable
                if item.get("selection_tier") == "same_street_relaxed"
            ),
            "nearby_500m": sum(
                1 for item in comparable
                if item.get("selection_tier") == "nearby_500m"
            ),
            "nearby_1000m": sum(
                1 for item in comparable
                if item.get("selection_tier") == "nearby_1000m"
            ),
        },
        "confidence": confidence,
        "confidence_label": confidence_label,
        "confidence_points": confidence_points,
        "average_similarity_score": round(average_similarity, 4),
        "recency_weighting": {
            "0_6_months": 1.00,
            "6_12_months": 0.90,
            "12_24_months": 0.75,
            "24_36_months": 0.60,
            "over_36_months": 0.45,
            "unknown_date": 0.70,
        },
        "range_percent": round(range_percent * 100),
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
@app.get("/address-coordinate-debug")
def address_coordinate_debug(
    q: str = Query(min_length=3)
):
    """Inspect coordinate fields available for one exact address."""
    if not addresses:
        raise HTTPException(status_code=503, detail="Adrešu dati nav ielādēti")

    query = q.casefold().strip().rstrip(",")

    for row in addresses:
        address = (row.get("STD", "") or "").strip()
        normalized = address.casefold()
        without_postcode = normalized.split(", lv-")[0]

        if normalized == query or without_postcode == query:
            coordinate_fields = {
                key: value
                for key, value in row.items()
                if value and (
                    "koord" in key.casefold()
                    or key.casefold() in {"x", "y", "lat", "lon", "lng"}
                    or "latitude" in key.casefold()
                    or "longitude" in key.casefold()
                )
            }
            return {
                "address": address,
                "object_code": row.get("KODS", ""),
                "coordinate_fields": coordinate_fields,
                "available_columns": list(row.keys()),
            }

    raise HTTPException(status_code=404, detail="Adrese nav atrasta")


@app.get("/address-debug")
def address_debug(
    q: str = Query(min_length=3)
):
    """Diagnostic endpoint for address -> VZD building linkage."""
    if not addresses:
        raise HTTPException(
            status_code=503,
            detail="Adrešu dati nav ielādēti"
        )

    query = q.casefold().strip().rstrip(",")
    matches = []

    for row in addresses:
        address = (row.get("STD", "") or "").strip()
        normalized = address.casefold()

        without_postcode = normalized
        if ", lv-" in without_postcode:
            without_postcode = without_postcode.split(", lv-")[0]

        if normalized == query or without_postcode == query:
            varis_code = (row.get("KODS", "") or "").strip()
            matches.append({
                "address": address,
                "object_code": varis_code,
                "address_type": row.get("TIPS_CD", ""),
                "parent_code": row.get("VKUR_CD", ""),
                "parent_type": row.get("VKUR_TIPS", ""),
                "name": row.get("NOSAUKUMS", ""),
                "attributes": row.get("ATRIB", ""),
                "building": (
                    get_building_by_varis_code(varis_code)
                    if varis_code else None
                ),
            })

    return {
        "query": q,
        "match_count": len(matches),
        "matches": matches,
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

