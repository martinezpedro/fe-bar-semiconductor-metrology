"""Create the Lakebase schema, seed users/roles, and grant the app service principal.

Idempotent; safe to rerun after the app is (re)created.
"""
import argparse
import os
import sys

here = os.path.dirname(os.path.abspath(globals().get("__file__") or sys.argv[0]))
sys.path.insert(0, os.path.join(here, "..", "common"))

import lakebase

ap = argparse.ArgumentParser()
ap.add_argument("--lakebase_endpoint", required=True)
ap.add_argument("--lakebase_host", required=True)
ap.add_argument("--admin_email", required=True)
ap.add_argument("--app_sp_client_id", default="")
args, _ = ap.parse_known_args()

ddl = open(os.path.join(here, "..", "lakebase", "schema.sql")).read()

# Demo personas. Real deployments map SSO groups to roles instead.
USERS = [
    (args.admin_email, "Pedro Martinez", ["admin", "submitter", "reviewer", "approver"], "employee", "HQ"),
    ("metrology.engineer@semiconductor-customer-demo.com", "Metrology Engineer", ["submitter", "reviewer"], "employee", "Fab A"),
    ("process.engineer@semiconductor-customer-demo.com", "Process Engineer", ["reviewer"], "employee", "Fab B"),
    ("eng.manager@semiconductor-customer-demo.com", "Engineering Manager", ["approver"], "employee", "HQ"),
    ("vendor.analyst@partner-demo.com", "Vendor Analyst", ["viewer"], "external", "Remote"),
]

with lakebase.connect(args.lakebase_endpoint, args.lakebase_host) as conn, conn.cursor() as cur:
    cur.execute(ddl)
    for email, name, roles, utype, site in USERS:
        cur.execute(
            "INSERT INTO fabs.app_users (email, display_name, roles, user_type, site) VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (email) DO NOTHING",
            (email, name, roles, utype, site),
        )
    if args.app_sp_client_id:
        sp = args.app_sp_client_id
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (sp,))
        if cur.fetchone():
            for stmt in (
                'GRANT USAGE ON SCHEMA fabs TO "{sp}"',
                'GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA fabs TO "{sp}"',
                'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA fabs TO "{sp}"',
                'ALTER DEFAULT PRIVILEGES IN SCHEMA fabs GRANT SELECT, INSERT, UPDATE ON TABLES TO "{sp}"',
                'ALTER DEFAULT PRIVILEGES IN SCHEMA fabs GRANT USAGE, SELECT ON SEQUENCES TO "{sp}"',
            ):
                cur.execute(stmt.format(sp=sp))
            print(f"granted app role {sp}")
        else:
            print(f"WARNING: Postgres role {sp} not found yet; deploy the app with its postgres resource, then rerun")
    conn.commit()
    cur.execute("SELECT count(*) FROM fabs.app_users")
    print("app_users:", cur.fetchone()[0])
print("lakebase ready")
