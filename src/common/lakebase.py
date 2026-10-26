"""Lakebase Autoscaling connection helper (OAuth token auth, no stored passwords)."""
import os

import psycopg
from databricks.sdk import WorkspaceClient


def connect(endpoint: str, host: str, database: str = "databricks_postgres", user: str = None, w: WorkspaceClient = None):
    """Open a psycopg connection to a Lakebase endpoint as the current Databricks identity.

    endpoint: projects/<project>/branches/<branch>/endpoints/<endpoint>
    """
    w = w or WorkspaceClient()
    token = w.api_client.do("POST", "/api/2.0/postgres/credentials", body={"endpoint": endpoint})["token"]
    user = user or w.current_user.me().user_name
    return psycopg.connect(
        host=host,
        port=5432,
        dbname=database,
        user=user,
        password=token,
        sslmode="require",
        autocommit=False,
        options="-c search_path=fabs",
    )


def from_env(w: WorkspaceClient = None):
    return connect(
        endpoint=os.environ["LAKEBASE_ENDPOINT"],
        host=os.environ["LAKEBASE_HOST"],
        database=os.environ.get("LAKEBASE_DATABASE", "databricks_postgres"),
        w=w,
    )
