#!/bin/zsh
# Finish a fresh build once the setup job (seed + train) is running: wait for it, run processing,
# deploy the app, apply UC column comments, point the Genie space at the data, benchmark it,
# and collect the execution evidence.   usage: scripts/rebuild_after_setup.sh <setup_run_id>
set -u
cd "${0:A:h}/.."
P=fe-vm-azure
state() { databricks jobs get-run $1 -p $P -o json 2>/dev/null | python3 -c "import json,sys;s=json.load(sys.stdin)['state'];print(s.get('result_state') or s.get('life_cycle_state'))"; }
wait_run() { while true; do s=$(state $1); case "$s" in SUCCESS) echo "run $1 SUCCESS"; return 0;; FAILED|CANCELED|TIMEDOUT|INTERNAL_ERROR|SKIPPED) echo "run $1 $s"; return 1;; esac; sleep 60; done; }

echo "STEP setup: waiting for run $1"; wait_run $1 || exit 1
JID=$(databricks bundle summary -o json | python3 -c "import json,sys;print(json.load(sys.stdin)['resources']['jobs']['fabs_processing']['id'])")
databricks bundle run fabs_processing --no-wait >/dev/null 2>&1
RID=$(databricks jobs list-runs --job-id $JID --limit 1 -p $P -o json | python3 -c "import json,sys;d=json.load(sys.stdin);d=d[0] if isinstance(d,list) else d['runs'][0];print(d['run_id'])")
echo "STEP processing: run $RID"; wait_run $RID || exit 1
echo "STEP app: deploying"; databricks bundle run fabs_review 2>&1 | tail -3
echo "STEP genie: column comments"
python3 -I - <<'PY'
import re, sys; sys.path.insert(0, "genie")
from sql_run import run
sql = re.sub(r"--[^\n]*", "", open("genie/column_comments.sql").read())
n = 0
for s in [x.strip().rstrip(";") for x in sql.split(";\n") if x.strip()]:
    if s.startswith("USE"): continue
    run(s.replace("ON COLUMN fabs_", "ON COLUMN ws_azure_classic_eastus_pedro.fabs_", 1)); n += 1
print("comments applied", n)
PY
python3 -I genie/build_space.py --update
EID=$(databricks genie genie-create-eval-run $(cat genie/space_id.txt) -p $P -o json | python3 -c "import json,sys;print(json.load(sys.stdin)['eval_run_id'])")
echo "STEP genie: benchmark run $EID"
while ! databricks genie genie-get-eval-run $(cat genie/space_id.txt) $EID -p $P -o json | grep -q '"eval_run_status": "\(DONE\|FAILED\|CANCELLED\)"'; do sleep 20; done
python3 -I genie/eval_report.py $EID
echo "STEP evidence"; python3 -I evidence/collect_evidence.py
echo "ALL DONE"
