import json
import logging
import os
import re
import sqlite3
import tempfile
import zipfile
from xml.etree import ElementTree as ET

from google.cloud import storage

BUCKET = os.getenv("PACIK_BUCKET", "pacik-lv-address-data")
SOURCES = {
    "premise_group": "cadastre/premisegroup.zip",
    "valuation": "cadastre/valuation.zip",
    "parcel": "cadastre/parcel.zip",
    "encumbrance": "cadastre/encumbrance.zip",
}
OUTPUT_OBJECT = "cadastre/cadastre.db"
LOCAL_DB = "/tmp/cadastre.db"
DIGITS = re.compile(r"^\d{10,20}$")
log = logging.getLogger("pacik-cadastre-index")


def local_name(tag):
    return tag.rsplit("}", 1)[-1]


def flatten_leaves(element):
    out = {}
    for node in element.iter():
        if len(node) != 0:
            continue
        value = (node.text or "").strip()
        if not value:
            continue
        key = local_name(node.tag)
        if key in out:
            if isinstance(out[key], list):
                if value not in out[key]:
                    out[key].append(value)
            elif out[key] != value:
                out[key] = [out[key], value]
        else:
            out[key] = value
    return out


def identifiers(fields):
    cadastral = set()
    varis = set()
    for key, raw in fields.items():
        values = raw if isinstance(raw, list) else [raw]
        kl = key.casefold()
        for value in values:
            text = str(value).strip()
            compact = text.replace("-", "").replace(" ", "")
            if "varis" in kl and compact:
                varis.add(compact)
            if ("cadastre" in kl or "kadastr" in kl) and DIGITS.match(compact):
                cadastral.add(compact)
    return cadastral, varis


def init_db():
    con = sqlite3.connect(LOCAL_DB)
    con.executescript("""
    PRAGMA journal_mode=WAL;
    PRAGMA synchronous=NORMAL;
    CREATE TABLE IF NOT EXISTS records (
      id INTEGER PRIMARY KEY,
      dataset TEXT NOT NULL,
      cadastral_id TEXT,
      varis_code TEXT,
      record_type TEXT,
      data_json TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_records_cadastral ON records(cadastral_id);
    CREATE INDEX IF NOT EXISTS idx_records_varis ON records(varis_code);
    CREATE INDEX IF NOT EXISTS idx_records_dataset ON records(dataset);
    CREATE TABLE IF NOT EXISTS metadata (
      key TEXT PRIMARY KEY,
      value TEXT NOT NULL
    );
    """)
    return con


def index_xml(con, dataset, stream):
    count = 0
    # End-event streaming keeps memory bounded even for very large VZD XML files.
    for event, elem in ET.iterparse(stream, events=("end",)):
        fields = flatten_leaves(elem)
        if len(fields) < 2:
            elem.clear()
            continue
        cadastral, varis = identifiers(fields)
        if not cadastral and not varis:
            elem.clear()
            continue
        record_type = local_name(elem.tag)
        payload = json.dumps(fields, ensure_ascii=False, separators=(",", ":"))
        cad_values = sorted(cadastral) or [None]
        varis_values = sorted(varis) or [None]
        # One canonical row per detected identifier pair. Duplicates are harmless
        # and preserve source evidence instead of guessing relationships.
        for cad in cad_values:
            for vc in varis_values:
                con.execute(
                    "INSERT INTO records(dataset,cadastral_id,varis_code,record_type,data_json) VALUES(?,?,?,?,?)",
                    (dataset, cad, vc, record_type, payload),
                )
                count += 1
        if count % 5000 == 0:
            con.commit()
        elem.clear()
    con.commit()
    return count


def build():
    logging.basicConfig(level=logging.INFO)
    client = storage.Client()
    bucket = client.bucket(BUCKET)
    if os.path.exists(LOCAL_DB):
        os.remove(LOCAL_DB)
    con = init_db()
    totals = {}

    with tempfile.TemporaryDirectory(prefix="pacik-cadastre-") as td:
        for dataset, object_name in SOURCES.items():
            blob = bucket.blob(object_name)
            if not blob.exists(client):
                raise FileNotFoundError(f"Missing gs://{BUCKET}/{object_name}")
            local_zip = os.path.join(td, os.path.basename(object_name))
            log.info("Downloading %s", object_name)
            blob.download_to_filename(local_zip)
            total = 0
            with zipfile.ZipFile(local_zip) as zf:
                xml_names = [n for n in zf.namelist() if n.lower().endswith(".xml")]
                log.info("%s: %s XML files", dataset, len(xml_names))
                for name in xml_names:
                    with zf.open(name) as source:
                        total += index_xml(con, dataset, source)
            totals[dataset] = total
            con.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES(?,?)",
                        (f"records_{dataset}", str(total)))
            con.commit()

    con.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES('schema_version','1')")
    con.commit()
    con.execute("VACUUM")
    con.close()

    out = bucket.blob(OUTPUT_OBJECT)
    out.upload_from_filename(LOCAL_DB, content_type="application/x-sqlite3")
    log.info("Uploaded gs://%s/%s: %s", BUCKET, OUTPUT_OBJECT, totals)
    return totals


if __name__ == "__main__":
    print(json.dumps(build(), ensure_ascii=False))
