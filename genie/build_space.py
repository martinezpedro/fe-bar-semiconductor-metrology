"""Build the Genie serialized_space payload from space_content.py and create or update the space.

    python3 build_space.py            # write genie/space.json only
    python3 build_space.py --create   # create the space in fe-vm (records its id in space_id.txt)
    python3 build_space.py --update   # push changes to the existing space
"""
import json, os, subprocess, sys, uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import space_content as c
from sql_run import PROFILE, WAREHOUSE

HERE = os.path.dirname(os.path.abspath(__file__))
_n = [0]


def nid():
    # Genie wants 32-hex ids, and lists sorted by id; a counter suffix keeps creation order.
    _n[0] += 1
    return uuid.uuid4().hex[:24] + f"{_n[0]:08x}"


def lines(text):
    return [l + "\n" for l in text.split("\n")[:-1]] + [text.split("\n")[-1]]


def by_id(items):
    return sorted(items, key=lambda x: x["id"])


def build():
    tables = []
    for ident in sorted(c.TABLES):
        name = ident.rsplit(".", 1)[1]
        cfgs = [{"column_name": col, "enable_entity_matching": True, "enable_format_assistance": True}
                for col in c.ENTITY_COLUMNS.get(name, [])]
        cfgs += [{"column_name": col, "exclude": True} for col in c.HIDDEN_COLUMNS.get(name, [])]
        t = {"identifier": ident}
        if cfgs:
            t["column_configs"] = sorted(cfgs, key=lambda x: x["column_name"])
        tables.append(t)

    snippets = {kind: by_id([{"id": nid(), "display_name": disp, "sql": [sql], "instruction": [desc]} for alias, disp, sql, desc in rows])
                for kind, rows in c.SNIPPETS.items()}

    return {
        "version": 2,
        "config": {"sample_questions": by_id([{"id": nid(), "question": [q]} for q in c.SAMPLE_QUESTIONS])},
        "data_sources": {"tables": tables},
        "instructions": {
            "text_instructions": [{"id": nid(), "content": lines(c.TEXT_INSTRUCTIONS)}],
            "example_question_sqls": by_id([{"id": nid(), "question": [q], "sql": lines(sql)} for q, sql in c.EXAMPLES]),
            "join_specs": by_id([{"id": nid(), "left": {"identifier": l},
                                  "right": {"identifier": r},
                                  "sql": [cond, f"--rt=FROM_RELATIONSHIP_TYPE_{rt}--"], "comment": [cm]}
                                 for l, r, cond, cm, rt in c.JOINS]),
            "sql_snippets": snippets,
        },
        "benchmarks": {"questions": by_id([{"id": nid(), "question": [q],
                                            "answer": [{"format": "SQL", "content": lines(sql)}]}
                                           for q, sql in c.BENCHMARKS])},
    }


def cli(*args):
    out = subprocess.run(["databricks", *args, "-p", PROFILE, "-o", "json"], capture_output=True, text=True)
    if out.returncode:
        sys.exit(out.stderr)
    return json.loads(out.stdout)


if __name__ == "__main__":
    space = build()
    with open(os.path.join(HERE, "space.json"), "w") as f:
        json.dump(space, f, indent=2)
    body = {"warehouse_id": WAREHOUSE, "title": c.TITLE, "description": c.DESCRIPTION,
            "serialized_space": json.dumps(space)}
    id_file = os.path.join(HERE, "space_id.txt")
    if "--create" in sys.argv:
        body["parent_path"] = "/Workspace/Users/pedro.martinez@databricks.com"
        r = cli("api", "post", "/api/2.0/genie/spaces", "--json", json.dumps(body))
        open(id_file, "w").write(r["space_id"] + "\n")
        print("created", r["space_id"])
    elif "--update" in sys.argv:
        sid = open(id_file).read().strip()
        r = cli("api", "patch", f"/api/2.0/genie/spaces/{sid}", "--json", json.dumps(body))
        print("updated", r["space_id"])
    else:
        print("wrote space.json")
