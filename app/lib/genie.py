"""Natural-language questions through the Genie space (Conversation API).

The app sends the engineer's question to the "Metrology Process Analyst" Genie space, waits for
the answer, and returns Genie's text, the SQL it ran and the result rows. The space is bound to
the app as a resource (CAN_RUN), so calls run as the app service principal over the same governed
UC views the rest of the app reads. Every question is written to the Lakebase audit trail.
"""
import os
import time
from dataclasses import dataclass, field

import pandas as pd

from . import backend as be

SPACE_ID = os.getenv("GENIE_SPACE_ID", "")
_DONE = {"COMPLETED", "FAILED", "CANCELLED", "QUERY_RESULT_EXPIRED"}


@dataclass
class Answer:
    conversation_id: str
    message_id: str
    status: str
    text: str = ""
    sql: str = ""
    sql_description: str = ""
    data: pd.DataFrame | None = None
    suggestions: list[str] = field(default_factory=list)
    error: str = ""


def _api(method, path, body=None):
    return be.ws().api_client.do(method, f"/api/2.0/genie/spaces/{SPACE_ID}{path}", body=body)


def _wait(conversation_id, message_id, timeout_s=120):
    # Genie answers in a few seconds to ~1 min; poll with backoff.
    deadline, delay = time.time() + timeout_s, 1.0
    while True:
        msg = _api("GET", f"/conversations/{conversation_id}/messages/{message_id}")
        if msg.get("status") in _DONE or time.time() > deadline:
            return msg
        time.sleep(delay)
        delay = min(delay * 1.5, 5.0)


def _result(conversation_id, message_id, attachment_id):
    r = _api("GET", f"/conversations/{conversation_id}/messages/{message_id}/attachments/{attachment_id}/query-result")
    sr = r.get("statement_response", r)
    cols = [c["name"] for c in sr.get("manifest", {}).get("schema", {}).get("columns", [])]
    rows = sr.get("result", {}).get("data_array") or []
    df = pd.DataFrame(rows, columns=cols)
    for c in df.columns:  # the API returns strings; restore numbers so tables sort and charts work
        conv = pd.to_numeric(df[c], errors="coerce")
        if conv.notna().sum() == df[c].notna().sum():
            df[c] = conv
    return df


def ask(question, user_email, conversation_id=None) -> Answer:
    if conversation_id:
        m = _api("POST", f"/conversations/{conversation_id}/messages", {"content": question})
        conversation_id, message_id = m["conversation_id"], m.get("message_id") or m["id"]
    else:
        m = _api("POST", "/start-conversation", {"content": question})
        conversation_id, message_id = m["conversation_id"], m["message_id"]

    msg = _wait(conversation_id, message_id)
    ans = Answer(conversation_id, message_id, msg.get("status", "UNKNOWN"))
    for a in msg.get("attachments") or []:
        if "text" in a:
            ans.text = a["text"].get("content", "")
        if "query" in a:
            ans.sql = a["query"].get("query", "")
            ans.sql_description = a["query"].get("description", "")
            try:
                ans.data = _result(conversation_id, message_id, a["attachment_id"])
            except Exception as e:  # answer text is still useful without the table
                ans.error = f"Could not fetch the result table: {e}"
        if "suggested_questions" in a:
            ans.suggestions = a["suggested_questions"].get("questions", [])[:3]
    if ans.status != "COMPLETED" and not ans.error:
        ans.error = (msg.get("error") or {}).get("error") or f"Genie returned status {ans.status}"

    be.audit(user_email, "GENIE_QUESTION", "genie_conversation", conversation_id,
             {"space_id": SPACE_ID, "message_id": message_id, "question": question, "status": ans.status,
              "sql": ans.sql, "rows": None if ans.data is None else len(ans.data)})
    return ans
