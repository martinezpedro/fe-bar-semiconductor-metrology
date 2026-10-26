"""LLM review assistant via the Databricks AI Gateway (OpenAI-compatible API).

Uses the OpenAI SDK against a Databricks serving endpoint, the same pattern the
team would use with Portkey/LangChain, but governed (usage tracking, rate
limits, guardrails) by the gateway inside the workspace. Every summary and its
token usage is stored in Lakebase for traceability.
"""
import json

import pandas as pd

from . import backend as be

SYSTEM = (
    "You are a metrology review assistant for a memory-process engineering team. You get model and "
    "measurement results for one SEM image of a contact-hole array (layer CH1, spec 60 nm, LSL 54, USL 66) "
    "and context for its lot. Write a concise review note for the human reviewer: 3-5 bullets covering "
    "spec status, defect evidence, model confidence, and anything unusual versus the lot or tool. "
    "Then a line 'Suggested reason code: <CODE>' using one of: OK_IN_SPEC, CD_HIGH, CD_LOW, MISSING_CONTACT, "
    "BRIDGE, PARTICLE, IMAGE_QUALITY, MODEL_MISS. Be factual and do not invent data. The reviewer decides."
)


def _fmt(v, nd=2):
    return "n/a" if v is None or (isinstance(v, float) and pd.isna(v)) else (f"{v:.{nd}f}" if isinstance(v, float) else str(v))


def _answer_text(content):
    # Reasoning models return a list of blocks (reasoning + text), sometimes JSON-encoded as a string;
    # keep only the text the reviewer reads.
    if isinstance(content, str):
        if not content.lstrip().startswith("[{"):
            return content
        try:
            content = json.loads(content, strict=False)
        except ValueError:
            return content
    parts = []
    for b in content or []:
        b = b if isinstance(b, dict) else getattr(b, "model_dump", lambda: {})()
        if b.get("type") == "text" and b.get("text"):
            parts.append(b["text"])
    return "\n\n".join(parts).strip()


def summarize(item, r, user):
    lot = be.sql_df(f"SELECT * FROM {be.FQ}.v_lot_summary WHERE experiment_id = :e AND lot_id = :l",
                    {"e": item["experiment_id"], "l": item["lot_id"]})
    tool = be.sql_df(f"SELECT * FROM {be.FQ}.v_tool_matching WHERE experiment_id = :e", {"e": item["experiment_id"]})
    probs = ", ".join(f"{c}={_fmt(float(r[f'p_{c}']))}" for c in ["none", "missing_contact", "bridge", "particle"]
                      if f"p_{c}" in r) if hasattr(r, "index") else ""
    facts = f"""Image {item['image_id']} | experiment {item['experiment_id']} | lot {item['lot_id']} | wafer {item['wafer_id']} | tool {item['tool_id']}
Model: predicted_class={r.predicted_class} (confidence {_fmt(r.class_confidence)}); class probabilities: {probs or 'n/a'}
Disposition: {r.disposition}
Contacts: {r.hole_count}/{r.expected_holes} detected, missing={r.missing_holes}, bridges={r.bridge_count}
CD: mean={_fmt(r.mean_cd_nm)} nm, sigma={_fmt(r.std_cd_nm)} nm, min={_fmt(r.min_cd_nm)}, max={_fmt(r.max_cd_nm)}, spec_status={r.cd_spec_status}
Lot context: {lot.to_dict('records')[0] if not lot.empty else 'n/a'}
Tool matching for this experiment: {tool.to_dict('records')[0] if not tool.empty else 'n/a'}"""

    resp = be.llm_client().chat.completions.create(
        model=be.LLM_ENDPOINT,
        messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": facts}],
        max_tokens=1500,  # includes the model's reasoning tokens
    )
    text = _answer_text(resp.choices[0].message.content)
    if not text:
        raise RuntimeError("The model returned no answer text")
    usage = resp.usage
    be.pg_exec(
        "INSERT INTO ai_summaries (image_id, model_endpoint, summary, prompt_tokens, completion_tokens, created_by) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (item["image_id"], be.LLM_ENDPOINT, text, getattr(usage, "prompt_tokens", None),
         getattr(usage, "completion_tokens", None), user.email),
    )
    be.audit(user.email, "AI_SUMMARY", "image", item["image_id"],
             {"endpoint": be.LLM_ENDPOINT, "prompt_tokens": getattr(usage, "prompt_tokens", None),
              "completion_tokens": getattr(usage, "completion_tokens", None)})
    return text
