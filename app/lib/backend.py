"""Data access for the review app: Lakebase (operational state), SQL warehouse
(Delta results), Volumes (images), Jobs (processing) and the AI Gateway (LLM).

All calls run as the app service principal; the end user's identity comes from
the Databricks Apps SSO headers and is recorded on every action.
"""
import io
import os
import time
from contextlib import contextmanager

import pandas as pd
import psycopg
import streamlit as st
from databricks import sql as dbsql
from databricks.sdk import WorkspaceClient
from databricks.sdk.core import Config
from PIL import Image
from psycopg.rows import dict_row

CATALOG = os.getenv("CATALOG", "ws_azure_classic_eastus_pedro")
SCHEMA = os.getenv("SCHEMA", "fabs_metrology")
FQ = f"{CATALOG}.{SCHEMA}"
VOLUME_ROOT = f"/Volumes/{CATALOG}/{SCHEMA}"
WAREHOUSE_ID = os.getenv("DATABRICKS_WAREHOUSE_ID", "")
JOB_ID = os.getenv("PROCESSING_JOB_ID", "")
LLM_ENDPOINT = os.getenv("LLM_ENDPOINT", "databricks-claude-sonnet-5-5")
LAKEBASE_ENDPOINT = os.getenv("LAKEBASE_ENDPOINT", "")
DASHBOARD_URL = os.getenv("DASHBOARD_URL", "")


@st.cache_resource
def ws() -> WorkspaceClient:
    return WorkspaceClient()


# --------------------------------------------------------------------------- Lakebase
@st.cache_resource
def _token_cache():
    return {"token": None, "at": 0.0}


def _pg_password():
    c = _token_cache()
    if not c["token"] or time.time() - c["at"] > 30 * 60:  # OAuth tokens last ~1h
        c["token"] = ws().api_client.do("POST", "/api/2.0/postgres/credentials", body={"endpoint": LAKEBASE_ENDPOINT})["token"]
        c["at"] = time.time()
    return c["token"]


@contextmanager
def pg():
    conn = psycopg.connect(
        host=os.environ["PGHOST"],
        port=int(os.getenv("PGPORT", "5432")),
        dbname=os.getenv("PGDATABASE", "databricks_postgres"),
        user=os.getenv("PGUSER") or ws().config.client_id,
        password=_pg_password(),
        sslmode=os.getenv("PGSSLMODE", "require"),
        options="-c search_path=fabs",
        row_factory=dict_row,
    )
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def pg_df(query, params=None) -> pd.DataFrame:
    with pg() as conn, conn.cursor() as cur:
        cur.execute(query, params or ())
        rows = cur.fetchall()
        return pd.DataFrame(rows, columns=[d.name for d in cur.description] if cur.description else None)


def pg_exec(query, params=None):
    with pg() as conn, conn.cursor() as cur:
        cur.execute(query, params or ())
        return cur.fetchone() if cur.description else None


def audit(actor, event_type, object_type=None, object_id=None, details=None):
    from psycopg.types.json import Json

    pg_exec(
        "INSERT INTO audit_events (actor_email, event_type, object_type, object_id, details) VALUES (%s, %s, %s, %s, %s)",
        (actor, event_type, object_type, object_id, Json(details or {})),
    )


# --------------------------------------------------------------------------- SQL warehouse (Delta)
@st.cache_resource
def _sql_conn():
    cfg = Config()
    return dbsql.connect(
        server_hostname=cfg.host.replace("https://", ""),
        http_path=f"/sql/1.0/warehouses/{WAREHOUSE_ID}",
        credentials_provider=lambda: cfg.authenticate,
    )


def sql_df(query, params=None) -> pd.DataFrame:
    try:
        with _sql_conn().cursor() as cur:
            cur.execute(query, params or {})
            return cur.fetchall_arrow().to_pandas()
    except Exception:
        _sql_conn.clear()  # stale session -> reconnect once
        with _sql_conn().cursor() as cur:
            cur.execute(query, params or {})
            return cur.fetchall_arrow().to_pandas()


@st.cache_data(ttl=120, show_spinner=False)
def sql_cached(query, params_tuple=()):
    return sql_df(query, dict(params_tuple))


# --------------------------------------------------------------------------- Volumes
@st.cache_data(ttl=3600, show_spinner=False, max_entries=256)
def volume_png(path: str) -> bytes:
    """Download an image from a Volume and return display-ready PNG bytes (handles 16-bit TIFF)."""
    raw = ws().files.download(path).contents.read()
    im = Image.open(io.BytesIO(raw))
    if im.mode in ("I;16", "I;16B", "I"):
        import numpy as np

        arr = np.asarray(im).astype("float32")
        arr = (arr / max(arr.max(), 1) * 255).astype("uint8")
        im = Image.fromarray(arr)
    buf = io.BytesIO()
    im.convert("RGB" if im.mode not in ("L", "RGB") else im.mode).save(buf, format="PNG")
    return buf.getvalue()


def volume_upload(path: str, data: bytes):
    ws().files.upload(path, io.BytesIO(data), overwrite=True)


# --------------------------------------------------------------------------- Jobs
def run_processing(submission_id="", image_ids=""):
    run = ws().jobs.run_now(job_id=int(JOB_ID), job_parameters={"submission_id": submission_id, "image_ids": image_ids,
                                                                     "reprocess_all": "false"})
    return run.run_id


def run_state(run_id):
    r = ws().jobs.get_run(run_id)
    life = r.state.life_cycle_state.value if r.state and r.state.life_cycle_state else "UNKNOWN"
    result = r.state.result_state.value if r.state and r.state.result_state else ""
    tasks = {t.task_key: (t.state.result_state.value if t.state and t.state.result_state else
                          t.state.life_cycle_state.value if t.state and t.state.life_cycle_state else "") for t in r.tasks or []}
    return {"life_cycle": life, "result": result, "url": r.run_page_url, "tasks": tasks,
            "start": r.start_time, "end": r.end_time}


# --------------------------------------------------------------------------- AI Gateway
@st.cache_resource
def llm_client():
    return ws().serving_endpoints.get_open_ai_client()
