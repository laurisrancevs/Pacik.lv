import gc
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
    # VZD schemas use names such as PremiseGroupCadastreNr and
    # PremiseGroupVARIScode (and analogous names in the other datasets).
    # Match the schema semantics instead of the English word "cadastre".
    for key, raw in fields.items():
        values = raw if isinstance(raw, list) else [raw]
        kl = key.casefold()
        for value in values:
            text = str(value).strip()
            compact = text.replace("-", "").replace(" ", "")
            if "varis" in kl and compact.isdigit():
                varis.add(compact)
            if ("cadastre" in kl or "cadastr" in kl or "kadastr" in kl) and compact.isdigit():
                cadastral.add(compact)
    return cadastral, varis

def init_db():
    con = sqlite3.connect(LOCAL_DB)
    con.executescript("""
    PRAGMA journal_mode=WAL;
    PRAGMA synchronous=NORMAL;
    PRAGMA cache_size=-8192;
    PRAGMA mmap_size=0;
    PRAGMA temp_store=FILE;
    CREATE TABLE IF NOT EXISTS records (
      id INTEGER PRIMARY KEY,
      dataset TEXT NOT NULL,
      cadastral_id TEXT,
      varis_code TEXT,
      record_type TEXT,
      data_json TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS metadata (
      key TEXT PRIMARY KEY,
      value TEXT NOT NULL
    );
    """)
    return con


def index_xml(con, dataset, stream):
    """Incrementally parse XML and discard completed sibling subtrees.

    VZD files can contain millions of nodes. A streaming parser alone does
    not free the root's accumulated children; remove completed siblings
    throughout the tree, including inside large record containers.
    """
    count = 0
    record_tags = {
        "PremiseGroupItemData", "ParcelItemData",
        "EncumbranceItemData", "ValuationItemData",
    }
    stack = []
    record_depth = None
    for event, elem in ET.iterparse(stream, events=("start", "end")):
        if event == "start":
            stack.append(elem)
            if record_depth is None and local_name(elem.tag) in record_tags:
                record_depth = len(stack)
            continue

        is_record_end = record_depth is not None and len(stack) == record_depth
        if is_record_end:
            fields = flatten_leaves(elem)
            cadastral, varis = identifiers(fields)
            if cadastral or varis:
                payload = json.dumps(fields, ensure_ascii=False, separators=(",", ":"))
                con.execute(
                    "INSERT INTO records(dataset,cadastral_id,varis_code,record_type,data_json) VALUES(?,?,?,?,?)",
                    (
                        dataset,
                        min(cadastral) if cadastral else None,
                        min(varis) if varis else None,
                        local_name(elem.tag),
                        payload,
                    ),
                )
                count += 1
                if count % 2000 == 0:
                    con.commit()
                    log.info("%s: indexed %d records", dataset, count)
            record_depth = None

        # Never discard descendants of a record before flatten_leaves()
        # has extracted them. Once a record ends, discard it immediately.
        if record_depth is None:
            elem.clear()
            if len(stack) > 1:
                parent = stack[-2]
                # The finished element is the last appended child. Remove
                # it so even very large wrapper elements stay bounded.
                if len(parent) and parent[-1] is elem:
                    parent.remove(elem)
        stack.pop()
    con.commit()
    gc.collect()
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
                for file_number, name in enumerate(xml_names, 1):
                    log.info("%s: parsing XML %d/%d: %s", dataset, file_number, len(xml_names), name)
                    with zf.open(name) as source:
                        total += index_xml(con, dataset, source)
                    log.info("%s: finished XML %d/%d; %d records", dataset, file_number, len(xml_names), total)
            totals[dataset] = total
            con.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES(?,?)",
                        (f"records_{dataset}", str(total)))
            con.commit()

    if any(count == 0 for count in totals.values()):
        raise RuntimeError(f"One or more VZD datasets produced no records: {totals}; index not uploaded")
    log.info("Creating lookup indexes after bulk import")
    con.execute("CREATE INDEX IF NOT EXISTS idx_records_cadastral ON records(cadastral_id)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_records_varis ON records(varis_code)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_records_dataset ON records(dataset)")
    con.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES('schema_version','1')")
    con.commit()
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    con.execute("PRAGMA journal_mode=DELETE")
    con.execute("VACUUM")
    con.close()

    out = bucket.blob(OUTPUT_OBJECT)
    out.upload_from_filename(LOCAL_DB, content_type="application/x-sqlite3")
    log.info("Uploaded gs://%s/%s: %s", BUCKET, OUTPUT_OBJECT, totals)
    return totals


if __name__ == "__main__":
    print(json.dumps(build(), ensure_ascii=False))
