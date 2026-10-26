"""Run SQL on the fe-vm warehouse through the Databricks CLI and return rows (helper for genie/ scripts)."""
import json, subprocess, sys

WAREHOUSE = "d508a88f62d6950a"
PROFILE = "fe-vm-azure"


def run(sql):
    body = json.dumps({"warehouse_id": WAREHOUSE, "statement": sql, "wait_timeout": "50s",
                       "disposition": "INLINE", "format": "JSON_ARRAY"})
    out = subprocess.run(["databricks", "api", "post", "/api/2.0/sql/statements", "--json", body,
                          "-p", PROFILE, "-o", "json"], capture_output=True, text=True)
    if out.returncode:
        raise RuntimeError(out.stderr)
    r = json.loads(out.stdout)
    st = r["status"]["state"]
    if st != "SUCCEEDED":
        raise RuntimeError(f"{st}: {r['status'].get('error', {}).get('message')}")
    cols = [c["name"] for c in r.get("manifest", {}).get("schema", {}).get("columns", [])]
    return cols, r.get("result", {}).get("data_array", []) or []


if __name__ == "__main__":
    cols, rows = run(sys.stdin.read())
    print(" | ".join(cols))
    for row in rows:
        print(" | ".join("" if v is None else str(v) for v in row))
