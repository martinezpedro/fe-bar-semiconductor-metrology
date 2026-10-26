"""Metrology Review — Databricks App (Streamlit).

Upload / submit SEM images, follow processing jobs, review model results,
approve or decline verdicts, and inspect the audit trail. Review state lives
in Lakebase; images in UC Volumes; results and analytics in Delta.
"""
import io
import json
import uuid
from datetime import datetime, timezone

import altair as alt
import pandas as pd
import streamlit as st

from lib import backend as be
from lib import workflow as wf
from lib import genie
from lib.ai import summarize

st.set_page_config(page_title="Metrology Review", page_icon="🔬", layout="wide")

SPEC = {"lsl": 54.0, "target": 60.0, "usl": 66.0}
# Color follows the entity (fixed order, never re-assigned by filters); review states use the status palette.
EXP_SCALE = alt.Scale(domain=["EXP-ETCH-A", "EXP-ETCH-B", "EXP-LITHO-C"], range=["#2a78d6", "#eb6834", "#1baf7a"])
TOOL_SCALE = alt.Scale(domain=["SEM-01", "SEM-02"], range=["#2a78d6", "#eb6834"])
STATE_COLOR = {"PENDING_REVIEW": "#fab219", "PENDING_APPROVAL": "#898781", "APPROVED_GOOD": "#0ca30c",
               "REJECTED_BAD": "#d03b3b", "NEEDS_REWORK": "#ec835a"}
MUTED = "#898781"
STATE_DOT = {"PENDING_REVIEW": "🟡", "PENDING_APPROVAL": "⚪", "APPROVED_GOOD": "🟢", "REJECTED_BAD": "🔴",
             "NEEDS_REWORK": "🟠"}


def spec_rules(values=(54.0, 66.0), labels=("LSL 54", "USL 66")):
    d = pd.DataFrame({"y": list(values), "label": list(labels)})
    rule = alt.Chart(d).mark_rule(strokeDash=[4, 4], color=MUTED, strokeWidth=1).encode(y="y:Q")
    text = alt.Chart(d).mark_text(align="left", dx=4, dy=-6, color=MUTED, fontSize=11).encode(
        y="y:Q", x=alt.value(0), text="label:N")
    return rule + text


# --------------------------------------------------------------------------- identity
def current_user() -> wf.User:
    if "user" not in st.session_state:
        h = st.context.headers
        email = h.get("X-Forwarded-Email") or h.get("X-Forwarded-Preferred-Username") or "local.dev@databricks.com"
        st.session_state.user = wf.get_or_register_user(email, h.get("X-Forwarded-Preferred-Username"))
        be.audit(email, "APP_ACCESS", "app", "fabs-review",
                 {"user_agent": h.get("User-Agent", "")[:200], "forwarded_for": h.get("X-Forwarded-For", "")})
    return st.session_state.user


def log_page(name):
    key = f"_viewed_{name}"
    if not st.session_state.get(key):
        be.audit(current_user().email, "PAGE_VIEW", "page", name)
        st.session_state[key] = True


def demo_mode():
    return st.session_state.get("demo_mode", False)


def state_badge(state):
    return f":{'orange' if state == 'PENDING_REVIEW' else 'blue' if state == 'PENDING_APPROVAL' else 'green' if state == 'APPROVED_GOOD' else 'red' if state == 'REJECTED_BAD' else 'violet'}-badge[{wf.STATE_LABEL.get(state, state)}]"


@st.cache_data(ttl=600, show_spinner=False)
def reason_codes(applies_to):
    df = be.pg_df("SELECT code, description FROM reason_codes WHERE applies_to IN (%s, 'any') ORDER BY code", (applies_to,))
    return dict(zip(df.code, df.description))


# --------------------------------------------------------------------------- pages
def page_overview():
    log_page("overview")
    st.title("Metrology overview")
    st.caption("Contact-hole layer CH1 · spec 60 ± 6 nm · synthetic POC data")

    q = be.pg_df("SELECT state, count(*) AS n FROM review_items GROUP BY state")
    counts = dict(zip(q.state, q.n)) if not q.empty else {}
    k = be.sql_cached(f"""
        SELECT count(*) AS images,
               round(avg(CASE WHEN disposition = 'FLAGGED' THEN 1 ELSE 0 END) * 100, 1) AS flagged_pct,
               round(avg(CASE WHEN cd_spec_status = 'FAIL' THEN 1 ELSE 0 END) * 100, 1) AS cd_fail_pct,
               max(processed_ts) AS last_processed
        FROM {be.FQ}.v_image_results""").iloc[0]
    c = st.columns(6)
    c[0].metric("Images processed", f"{int(k.images):,}")
    c[1].metric("Flagged by model", f"{k.flagged_pct}%")
    c[2].metric("CD out of spec", f"{k.cd_fail_pct}%")
    c[3].metric("Pending review", counts.get("PENDING_REVIEW", 0))
    c[4].metric("Pending approval", counts.get("PENDING_APPROVAL", 0))
    c[5].metric("Approved / rejected", f"{counts.get('APPROVED_GOOD', 0)} / {counts.get('REJECTED_BAD', 0)}")

    left, right = st.columns([3, 2])
    with left:
        st.subheader("Daily mean CD by experiment")
        t = be.sql_cached(f"""
            SELECT capture_date, experiment_id, sum(mean_cd_nm * images) / sum(images) AS mean_cd_nm
            FROM {be.FQ}.v_daily_cd_trend GROUP BY ALL ORDER BY capture_date""")
        if not t.empty:
            base = alt.Chart(t).mark_line(strokeWidth=2, point=alt.OverlayMarkDef(size=64)).encode(
                x=alt.X("capture_date:T", title=None),
                y=alt.Y("mean_cd_nm:Q", title="Mean CD (nm)", scale=alt.Scale(domain=[52, 68])),
                color=alt.Color("experiment_id:N", title="Experiment", scale=EXP_SCALE, legend=alt.Legend(orient="top")),
                tooltip=[alt.Tooltip("capture_date:T", title="Date"), alt.Tooltip("experiment_id", title="Experiment"),
                         alt.Tooltip("mean_cd_nm:Q", title="Mean CD (nm)", format=".2f")])
            st.altair_chart((base + spec_rules()).configure_axis(gridColor="#e1e0d9", domainColor="#c3c2b7"),
                            use_container_width=True)
    with right:
        st.subheader("Review queue")
        if counts:
            qd = pd.DataFrame({"state": [wf.STATE_LABEL[s] for s in counts], "n": list(counts.values()),
                               "color": [STATE_COLOR[s] for s in counts]})
            bars = alt.Chart(qd).mark_bar(cornerRadiusEnd=4, size=18).encode(
                y=alt.Y("state:N", title=None, sort="-x"), x=alt.X("n:Q", title="Images"),
                color=alt.Color("color:N", scale=None), tooltip=[alt.Tooltip("state", title="State"),
                                                                alt.Tooltip("n", title="Images")])
            labels = bars.mark_text(align="left", dx=4, color="#52514e").encode(text="n:Q", color=alt.value("#52514e"))
            st.altair_chart(bars + labels, use_container_width=True)
        st.subheader("Recent processing runs")
        runs = be.sql_cached(f"""SELECT ended_ts, mode, images_processed, flagged, seconds, model_version
                                 FROM {be.FQ}.processing_runs ORDER BY ended_ts DESC LIMIT 6""")
        st.dataframe(runs, hide_index=True, use_container_width=True)


def page_submit():
    log_page("submit")
    user = current_user()
    st.title("Submit images for processing")
    if not user.has("submitter"):
        st.warning("You need the **submitter** role to upload images. Ask an admin to grant it.")
        return

    src = st.radio("Image source", ["Upload files", "Generate synthetic SEM images"], horizontal=True)
    with st.form("submit", clear_on_submit=False):
        c = st.columns(4)
        experiment = c[0].selectbox("Experiment", ["EXP-ETCH-A", "EXP-ETCH-B", "EXP-LITHO-C"])
        lot = c[1].text_input("Lot", "L24299")
        wafer = c[2].text_input("Wafer", "W07")
        tool = c[3].selectbox("SEM tool", ["SEM-01", "SEM-02"])
        desc = st.text_input("Description", "Engineering split check")
        if src == "Upload files":
            files = st.file_uploader("JPEG / TIFF images", type=["jpg", "jpeg", "tif", "tiff"], accept_multiple_files=True)
            n_synth = 0
        else:
            files = []
            n_synth = st.slider("Number of images", 1, 12, 4)
        go = st.form_submit_button("Submit and start processing", type="primary")

    if not go:
        return
    if src == "Upload files" and not files:
        st.error("Choose at least one image.")
        return

    sid = f"SUB-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:4]}"
    payload = []
    if n_synth:
        from lib.synth import synth_images

        payload = synth_images(n_synth, experiment, tool)
    else:
        for f in files:
            ext = f.name.rsplit(".", 1)[-1].lower()
            payload.append((f"IMG-U-{uuid.uuid4().hex[:12]}", ext, f.getvalue(), f.name))

    be.pg_exec("INSERT INTO submissions (submission_id, submitted_by, description, experiment_id, lot_id, file_count) "
               "VALUES (%s, %s, %s, %s, %s, %s)", (sid, user.email, desc, experiment, lot, len(payload)))
    prog = st.progress(0.0, "Uploading to the landing Volume…")
    for i, (image_id, ext, data, original) in enumerate(payload):
        folder = f"{be.VOLUME_ROOT}/landing/uploads/{sid}"
        be.volume_upload(f"{folder}/{image_id}.{ext}", data)
        meta = {"image_id": image_id, "file_name": f"{image_id}.{ext}", "original_file_name": original,
                "experiment_id": experiment, "lot_id": lot, "wafer_id": wafer, "die_x": 0, "die_y": 0,
                "tool_id": tool, "layer": "CH1", "feature_type": "contact_hole_array", "pixel_size_nm": 2.0,
                "target_cd_nm": 60.0, "expected_holes": 64, "capture_ts": datetime.now(timezone.utc).isoformat(),
                "operator": user.email, "batch_id": sid, "submission_id": sid, "uploaded_by": user.email}
        be.volume_upload(f"{folder}/{image_id}.json", json.dumps(meta).encode())
        prog.progress((i + 1) / len(payload), f"Uploaded {i + 1}/{len(payload)}")
    be.audit(user.email, "UPLOAD", "submission", sid, {"files": len(payload), "experiment": experiment, "lot": lot})

    run_id = be.run_processing(submission_id=sid)
    be.pg_exec("UPDATE submissions SET job_run_id = %s, status = 'RUNNING', updated_at = now() WHERE submission_id = %s",
               (run_id, sid))
    be.audit(user.email, "JOB_SUBMIT", "job_run", str(run_id), {"submission_id": sid})
    st.success(f"Submission **{sid}** created with {len(payload)} image(s). Processing run {run_id} started — "
               "follow it on **Job status**.")


def page_jobs():
    log_page("jobs")
    user = current_user()
    st.title("Processing status")
    mine = st.toggle("Only my submissions", value=not user.has("admin"))
    df = be.pg_df(
        "SELECT submission_id, submitted_by, submitted_at, experiment_id, lot_id, file_count, job_run_id, status, status_detail "
        "FROM submissions " + ("WHERE submitted_by = %s " if mine else "") + "ORDER BY submitted_at DESC LIMIT 50",
        (user.email,) if mine else None)
    if df.empty:
        st.info("No submissions yet.")
        return
    # reconcile in-flight runs with the Jobs API
    for i, r in df[df.status.isin(["RUNNING", "SUBMITTED"]) & df.job_run_id.notna()].iterrows():
        s = be.run_state(int(r.job_run_id))
        if s["life_cycle"] in ("TERMINATED", "INTERNAL_ERROR", "SKIPPED") and s["result"] != "SUCCESS":
            be.pg_exec("UPDATE submissions SET status = 'FAILED', status_detail = %s, updated_at = now() "
                       "WHERE submission_id = %s AND status <> 'PROCESSED'", (f"run {s['result'] or s['life_cycle']}", r.submission_id))
            df.loc[i, "status"] = "FAILED"
        else:
            done = [k for k, v in s["tasks"].items() if v == "SUCCESS"]
            df.loc[i, "status_detail"] = f"{s['life_cycle'].lower()} · done: {', '.join(done) or '—'}"
    st.dataframe(df, hide_index=True, use_container_width=True,
                 column_config={"job_run_id": st.column_config.NumberColumn("Run", format="%d")})
    pick = st.selectbox("Run details", df.submission_id)
    r = df[df.submission_id == pick].iloc[0]
    if pd.notna(r.job_run_id):
        s = be.run_state(int(r.job_run_id))
        st.write(f"**{s['life_cycle']}** {s['result']} · [open run in Databricks]({s['url']})")
        st.dataframe(pd.DataFrame([{"task": k, "state": v} for k, v in s["tasks"].items()]), hide_index=True)
    if st.button("Refresh"):
        st.rerun()


def state_counts():
    q = be.pg_df("SELECT state, count(*) AS n FROM review_items GROUP BY state")
    return dict(zip(q.state, q.n)) if not q.empty else {}


def _review_list(states, key):
    counts = state_counts()
    st.caption("  ·  ".join(f"{STATE_DOT.get(s, '')} **{wf.STATE_LABEL[s]}** {counts.get(s, 0):,}" for s in wf.STATE_LABEL))
    ids = st.text_input("Image or submission ID", key=f"{key}_id", placeholder="Paste e.g. IMG-U-500dd0af3988 or "
                        "SUB-20261023-153839-5c84 (partial IDs work; separate several with spaces or commas)")
    terms = [t for t in ids.replace(",", " ").split() if t]
    f = st.columns([3, 2, 2, 2, 1])
    sel_states = f[0].multiselect("State", list(wf.STATE_LABEL), default=states, key=f"{key}_state",
                                  format_func=lambda s: f"{wf.STATE_LABEL[s]} ({counts.get(s, 0):,})")
    exp = f[1].multiselect("Experiment", ["EXP-ETCH-A", "EXP-ETCH-B", "EXP-LITHO-C"], key=f"{key}_exp")
    disp = f[2].multiselect("Model disposition", ["FLAGGED", "PASS"], default=["FLAGGED"] if key == "rev" else [], key=f"{key}_disp")
    lot = f[3].text_input("Lot contains", key=f"{key}_lot")
    limit = f[4].selectbox("Show", [50, 200, 1000], key=f"{key}_lim")
    where, params = ["state = ANY(%s)"], [sel_states or list(wf.STATE_LABEL)]
    if terms:
        pats = [f"%{t}%" for t in terms]
        where.append("(image_id ILIKE ANY(%s) OR submission_id ILIKE ANY(%s))"), params.extend([pats, pats])
    if exp:
        where.append("experiment_id = ANY(%s)"), params.append(exp)
    if disp and not terms:  # an explicit ID search should find the image whatever the model said
        where.append("disposition = ANY(%s)"), params.append(disp)
    if lot:
        where.append("lot_id ILIKE %s"), params.append(f"%{lot}%")
    df = be.pg_df(
        "SELECT image_id, state, priority, disposition, predicted_class, round(class_confidence::numeric, 2) AS conf, "
        "round(mean_cd_nm::numeric, 2) AS mean_cd_nm, cd_spec_status, experiment_id, lot_id, wafer_id, tool_id, capture_ts, "
        "reviewer_verdict, reviewed_by, submitted_by FROM review_items WHERE " + " AND ".join(where) +
        f" ORDER BY priority, capture_ts DESC LIMIT {int(limit)}", params)
    st.caption(f"{len(df)} item(s)" + (" matching the ID search (disposition filter ignored)" if terms else ""))
    if terms and df.empty:
        st.info("No match in this queue. The image may be in another state: check Approvals or the Audit trail.")
    ev = st.dataframe(df, hide_index=True, use_container_width=True, on_select="rerun", selection_mode="single-row",
                      key=f"{key}_table", height=260)
    rows = ev.selection.rows if ev and ev.selection else []
    # the selection is a row position from the previous render; the list may have shrunk since
    # (new filter, ID search, or the item just left this queue), so fall back to the first row
    if rows and rows[0] < len(df):
        return df.iloc[rows[0]].image_id
    return df.iloc[0].image_id if not df.empty else None


def _image_detail(image_id):
    item = wf.get_item(image_id)
    res = be.sql_df(f"SELECT * FROM {be.FQ}.v_image_results WHERE image_id = :id", {"id": image_id})
    r = res.iloc[0] if not res.empty else None
    st.markdown(f"### {image_id} {state_badge(item['state'])}")
    st.caption(f"{item['experiment_id']} · lot {item['lot_id']} · wafer {item['wafer_id']} · {item['tool_id']} · "
               f"captured {pd.to_datetime(item['capture_ts']):%Y-%m-%d %H:%M} · model {item['model_version']}")
    if genie.SPACE_ID and st.button(f"Ask Genie how lot {item['lot_id']} compares", key=f"g_{image_id}",
                                    icon="💬"):
        ask_genie_about(f"How does lot {item['lot_id']} compare with the other lots in {item['experiment_id']} on "
                        f"mean CD, CD fail rate and defect rate?")
    a, b, m = st.columns([2, 2, 2])
    if r is not None:
        a.image(be.volume_png(r.file_path), caption=f"Original ({r.file_ext.upper()})", use_container_width=True)
        b.image(be.volume_png(r.overlay_path), caption="Segmentation overlay (green = contacts, red = bridges)",
                use_container_width=True)
        with m:
            st.metric("Mean CD", f"{r.mean_cd_nm:.2f} nm" if pd.notna(r.mean_cd_nm) else "—",
                      f"{r.mean_cd_nm - SPEC['target']:+.2f} vs target" if pd.notna(r.mean_cd_nm) else None, delta_color="off")
            st.markdown(f"**Spec:** {r.cd_spec_status} &nbsp; **Class:** {r.predicted_class} ({r.class_confidence:.0%})")
            st.markdown(f"Contacts **{r.hole_count}/{r.expected_holes}** · missing **{r.missing_holes}** · "
                        f"bridges **{r.bridge_count}**")
            st.markdown(f"CD σ {r.std_cd_nm:.2f} nm · range {r.min_cd_nm:.1f}–{r.max_cd_nm:.1f} nm"
                        if pd.notna(r.std_cd_nm) else "")
            h = be.sql_df(f"SELECT diameter_nm FROM {be.FQ}.hole_measurements WHERE image_id = :id AND NOT is_bridge",
                          {"id": image_id})
            if not h.empty:
                st.altair_chart(alt.Chart(h).mark_bar(color="#2a78d6", cornerRadiusTopLeft=2, cornerRadiusTopRight=2).encode(
                    x=alt.X("diameter_nm:Q", bin=alt.Bin(step=0.5), title="Contact diameter (nm)"),
                    y=alt.Y("count()", title="Contacts"),
                    tooltip=[alt.Tooltip("diameter_nm:Q", bin=alt.Bin(step=0.5), title="Diameter (nm)"),
                             alt.Tooltip("count()", title="Contacts")]).properties(height=140), use_container_width=True)
    return item, r


def _history_and_ai(item, r, user):
    t1, t2 = st.tabs(["History", "AI review assistant"])
    with t1:
        hist = be.pg_df("SELECT action_ts, actor_email, acting_role, action, from_state, to_state, reason_code, comment, "
                        "sod_override FROM review_actions WHERE image_id = %s ORDER BY action_ts", (item["image_id"],))
        st.dataframe(hist, hide_index=True, use_container_width=True)
        with st.form(f"c_{item['image_id']}", clear_on_submit=True):
            txt = st.text_input("Add comment")
            if st.form_submit_button("Comment") and txt:
                try:
                    wf.add_comment(user, item["image_id"], txt)
                    st.rerun()
                except wf.WorkflowError as e:
                    st.error(str(e))
    with t2:
        prev = be.pg_df("SELECT created_at, created_by, model_endpoint, summary FROM ai_summaries WHERE image_id = %s "
                        "ORDER BY created_at DESC LIMIT 1", (item["image_id"],))
        if not prev.empty:
            p = prev.iloc[0]
            st.markdown(p.summary)
            st.caption(f"Generated {pd.to_datetime(p.created_at):%Y-%m-%d %H:%M} by {p.created_by} via {p.model_endpoint}. "
                       "Advisory only: the reviewer makes the call.")
        if r is not None and st.button("Generate summary" if prev.empty else "Regenerate", key=f"ai_{item['image_id']}"):
            with st.spinner(f"Asking {be.LLM_ENDPOINT} through the AI Gateway…"):
                try:
                    summarize(item, r, user)
                    st.rerun()
                except Exception as e:
                    st.error(f"AI summary failed: {e}")


def page_review():
    log_page("review")
    user = current_user()
    st.title("Review queue")
    image_id = _review_list(["PENDING_REVIEW", "NEEDS_REWORK"], "rev")
    if not image_id:
        st.success("Nothing waiting for review.")
        return
    st.divider()
    item, r = _image_detail(image_id)
    left, right = st.columns([3, 2])
    with right:
        st.markdown("#### Decision")
        if item["state"] == "NEEDS_REWORK":
            st.info("Marked for rework. Reprocess it with the current model to send it back to review.")
            if user.has("submitter") and st.button("Reprocess image", type="primary"):
                run_id = be.run_processing(image_ids=image_id)
                be.audit(user.email, "JOB_SUBMIT", "job_run", str(run_id), {"reprocess": image_id})
                st.success(f"Reprocessing run {run_id} started.")
        elif item["state"] != "PENDING_REVIEW":
            st.info(f"This image is **{wf.STATE_LABEL[item['state']]}**, so there is nothing to review here.")
        elif not user.has("reviewer"):
            st.warning("Reviewer role required to record a decision.")
        else:
            codes = reason_codes("review")
            with st.form(f"rev_{image_id}"):
                verdict = st.radio("Verdict", ["GOOD", "BAD", "NEEDS_REWORK"], horizontal=True,
                                   format_func={"GOOD": "✅ Good", "BAD": "❌ Bad", "NEEDS_REWORK": "🔁 Needs rework"}.get)
                rc = st.selectbox("Reason code", list(codes), format_func=lambda c: f"{c} — {codes[c]}")
                cm = st.text_area("Comment", height=80)
                if st.form_submit_button("Submit review", type="primary"):
                    try:
                        wf.review(user, image_id, verdict, rc, cm, demo_mode())
                        st.toast(f"{image_id}: {verdict}")
                        st.rerun()
                    except wf.WorkflowError as e:
                        st.error(str(e))
    with left:
        _history_and_ai(item, r, user)


def page_approvals():
    log_page("approvals")
    user = current_user()
    st.title("Approvals")
    image_id = _review_list(["PENDING_APPROVAL"], "apr")
    if not image_id:
        st.success("Nothing waiting for approval.")
        return
    st.divider()
    item, r = _image_detail(image_id)
    left, right = st.columns([3, 2])
    with right:
        st.markdown("#### Approval")
        last = be.pg_df("SELECT reason_code, comment FROM review_actions WHERE image_id = %s AND action LIKE 'REVIEW_%%' "
                        "ORDER BY action_ts DESC LIMIT 1", (image_id,))
        st.markdown(f"Reviewer **{item['reviewed_by']}** called it **{item['reviewer_verdict']}**"
                    + (f" ({last.iloc[0].reason_code}): _{last.iloc[0].comment or 'no comment'}_" if not last.empty else ""))
        if item["state"] != "PENDING_APPROVAL":
            st.info(f"This image is **{wf.STATE_LABEL[item['state']]}**, so there is nothing to approve here.")
        elif not user.has("approver"):
            st.warning("Approver role required.")
        else:
            codes = reason_codes("approval")
            with st.form(f"apr_{image_id}"):
                ok = st.radio("Decision", [True, False], horizontal=True,
                              format_func=lambda v: "Approve verdict" if v else "Decline (send back to review)")
                rc = st.selectbox("Reason code", list(codes), format_func=lambda c: f"{c} — {codes[c]}")
                cm = st.text_area("Comment", height=80)
                if st.form_submit_button("Record decision", type="primary"):
                    try:
                        wf.approve(user, image_id, ok, rc, cm, demo_mode())
                        st.toast(f"{image_id}: {'approved' if ok else 'declined'}")
                        st.rerun()
                    except wf.WorkflowError as e:
                        st.error(str(e))
    with left:
        _history_and_ai(item, r, user)


def page_analytics():
    log_page("analytics")
    st.title("Engineering analytics")
    c = st.columns([1, 1, 4])
    if be.DASHBOARD_URL:
        c[0].link_button("Open the AI/BI dashboard", be.DASHBOARD_URL)
    if genie.SPACE_ID:
        c[1].page_link(GENIE_PAGE, label="Ask Genie in plain English", icon="💬")
    t1, t2, t3, t4 = st.tabs(["CD trend & tool matching", "Lots", "Outliers", "Review quality"])
    with t1:
        t = be.sql_cached(f"SELECT * FROM {be.FQ}.v_daily_cd_trend ORDER BY capture_date")
        exp = st.selectbox("Experiment", sorted(t.experiment_id.unique()) if not t.empty else [])
        d = t[t.experiment_id == exp]
        st.caption("Line = daily mean CD per SEM tool; band = 5th–95th percentile of image means")
        band = alt.Chart(d).mark_area(opacity=0.15).encode(x="capture_date:T", y="p05_cd_nm:Q", y2="p95_cd_nm:Q",
                                                           color=alt.Color("tool_id:N", scale=TOOL_SCALE, legend=None))
        line = alt.Chart(d).mark_line(strokeWidth=2, point=alt.OverlayMarkDef(size=64)).encode(
            x=alt.X("capture_date:T", title=None), y=alt.Y("mean_cd_nm:Q", title="CD (nm)", scale=alt.Scale(domain=[50, 70])),
            color=alt.Color("tool_id:N", title="SEM tool", scale=TOOL_SCALE, legend=alt.Legend(orient="top")),
            tooltip=[alt.Tooltip("capture_date:T", title="Date"), alt.Tooltip("tool_id", title="Tool"),
                     alt.Tooltip("images", title="Images"), alt.Tooltip("mean_cd_nm:Q", title="Mean CD (nm)", format=".2f"),
                     alt.Tooltip("p05_cd_nm:Q", title="P05", format=".2f"), alt.Tooltip("p95_cd_nm:Q", title="P95", format=".2f")])
        rules = spec_rules((54.0, 60.0, 66.0), ("LSL 54", "Target 60", "USL 66"))
        st.altair_chart((band + line + rules).configure_axis(gridColor="#e1e0d9", domainColor="#c3c2b7"),
                        use_container_width=True)
        with st.expander("Table view"):
            st.dataframe(d, hide_index=True, use_container_width=True)
        st.markdown("**SEM tool matching** (defect-free images)")
        st.dataframe(be.sql_cached(f"SELECT * FROM {be.FQ}.v_tool_matching ORDER BY experiment_id"), hide_index=True)
    with t2:
        st.dataframe(be.sql_cached(f"SELECT * FROM {be.FQ}.v_lot_summary ORDER BY flagged_pct DESC"), hide_index=True,
                     use_container_width=True)
    with t3:
        st.dataframe(be.sql_cached(f"SELECT * FROM {be.FQ}.v_cd_outliers ORDER BY abs(z_score) DESC LIMIT 200"),
                     hide_index=True, use_container_width=True)
    with t4:
        agree = be.pg_df("""
            SELECT disposition AS model_disposition, reviewer_verdict, count(*) AS n
            FROM review_items WHERE reviewer_verdict IS NOT NULL GROUP BY 1, 2 ORDER BY 1, 2""")
        cyc = be.pg_df("""
            SELECT date_trunc('day', approved_at) AS day, count(*) AS approvals,
                   round(avg(extract(epoch FROM approved_at - created_at)) / 3600, 1) AS avg_hours_to_approval
            FROM review_items WHERE approved_at IS NOT NULL GROUP BY 1 ORDER BY 1""")
        c = st.columns(2)
        c[0].markdown("**Model disposition vs reviewer verdict**")
        c[0].dataframe(agree, hide_index=True, use_container_width=True)
        c[1].markdown("**Approval cycle time**")
        c[1].dataframe(cyc, hide_index=True, use_container_width=True)
        by = be.pg_df("SELECT actor_email, action, count(*) AS n FROM review_actions WHERE acting_role <> 'system' "
                      "GROUP BY 1, 2 ORDER BY 1, 2")
        st.markdown("**Actions by user**")
        st.dataframe(by, hide_index=True, use_container_width=True)


def page_audit():
    log_page("audit")
    user = current_user()
    st.title("Audit trail")
    if not (user.has("approver") or user.has("admin")):
        st.warning("Approver or admin role required.")
        return
    t1, t2 = st.tabs(["Review actions", "Application events"])
    with t1:
        q = st.text_input("Image or user contains")
        df = be.pg_df("SELECT action_ts, image_id, actor_email, acting_role, action, from_state, to_state, reason_code, "
                      "comment, sod_override FROM review_actions WHERE (%s = '' OR image_id ILIKE %s OR actor_email ILIKE %s) "
                      "ORDER BY action_ts DESC LIMIT 1000", (q, f"%{q}%", f"%{q}%"))
        st.dataframe(df, hide_index=True, use_container_width=True)
        st.download_button("Export CSV", df.to_csv(index=False), "review_actions.csv", "text/csv")
    with t2:
        types = be.pg_df("SELECT DISTINCT event_type FROM audit_events ORDER BY 1").event_type.tolist()
        sel = st.multiselect("Event type", types)
        df = be.pg_df("SELECT event_ts, actor_email, event_type, object_type, object_id, details::text AS details "
                      "FROM audit_events WHERE (cardinality(%s::text[]) = 0 OR event_type = ANY(%s)) "
                      "ORDER BY event_ts DESC LIMIT 1000", (sel, sel))
        st.dataframe(df, hide_index=True, use_container_width=True)
        st.download_button("Export CSV", df.to_csv(index=False), "audit_events.csv", "text/csv")


def page_admin():
    log_page("admin")
    user = current_user()
    st.title("Users & roles")
    if not user.has("admin"):
        st.warning("Admin role required.")
        return
    df = be.pg_df("SELECT email, display_name, roles, user_type, site, active, updated_at FROM app_users ORDER BY email")
    st.dataframe(df, hide_index=True, use_container_width=True)
    with st.form("role"):
        c = st.columns([3, 3, 2, 1])
        email = c[0].text_input("Email")
        roles = c[1].multiselect("Roles", ["viewer", "submitter", "reviewer", "approver", "admin"], default=["viewer"])
        utype = c[2].selectbox("User type", ["employee", "external"])
        active = c[3].checkbox("Active", True)
        if st.form_submit_button("Save") and email:
            if utype == "external" and set(roles) & {"reviewer", "approver", "admin"}:
                st.error("External users are limited to viewer / submitter.")
            else:
                be.pg_exec("INSERT INTO app_users (email, roles, user_type, active) VALUES (%s, %s, %s, %s) "
                           "ON CONFLICT (email) DO UPDATE SET roles = EXCLUDED.roles, user_type = EXCLUDED.user_type, "
                           "active = EXCLUDED.active, updated_at = now()", (email.strip().lower(), roles, utype, active))
                be.audit(user.email, "ROLE_CHANGE", "user", email, {"roles": roles, "user_type": utype, "active": active})
                st.rerun()


GENIE_SAMPLES = [
    "Which experiment is drifting toward the upper spec limit?",
    "Is there a CD offset between SEM-01 and SEM-02?",
    "Which lots have the highest defect rate?",
    "How many flagged images are still waiting for review?",
]


def ask_genie_about(question):
    st.session_state["genie_prefill"] = question
    st.switch_page(GENIE_PAGE)


def _genie_chart(df):
    # Draw a chart only when the shape makes one obvious; the table is always shown.
    if df is None or df.empty or len(df.columns) < 2:
        return None
    num = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    time_cols = [c for c in df.columns if any(k in c.lower() for k in ("date", "week", "day", "month"))]
    if time_cols and num:
        d = df.copy()
        d[time_cols[0]] = pd.to_datetime(d[time_cols[0]], errors="coerce")
        series = [c for c in df.columns if c not in num and c != time_cols[0]]
        enc = dict(x=alt.X(f"{time_cols[0]}:T", title=None), y=alt.Y(f"{num[0]}:Q", scale=alt.Scale(zero=False)))
        if series:
            enc["color"] = alt.Color(f"{series[0]}:N", legend=alt.Legend(orient="top"))
        return alt.Chart(d).mark_line(point=True).encode(**enc)
    cats = [c for c in df.columns if c not in num]
    if cats and num and len(df) <= 30:
        return alt.Chart(df).mark_bar(color="#2a78d6", cornerRadiusEnd=3).encode(
            y=alt.Y(f"{cats[0]}:N", sort="-x", title=None), x=alt.X(f"{num[0]}:Q"),
            tooltip=list(df.columns))
    return None


def _render_answer(ans, idx):
    if ans.text:
        st.markdown(ans.text)
    if ans.data is not None and not ans.data.empty:
        chart = _genie_chart(ans.data)
        if chart is not None:
            st.altair_chart(chart.properties(height=260), use_container_width=True)
        st.dataframe(ans.data, hide_index=True, use_container_width=True)
    if ans.sql:
        with st.expander("SQL Genie ran"):
            if ans.sql_description:
                st.caption(ans.sql_description)
            st.code(ans.sql, language="sql")
    if ans.error:
        st.warning(ans.error)
    if ans.suggestions:
        st.caption("Follow-up ideas")
        cols = st.columns(len(ans.suggestions))
        for i, q in enumerate(ans.suggestions):
            if cols[i].button(q, key=f"sug_{idx}_{i}"):
                st.session_state["genie_prefill"] = q
                st.rerun()


def page_genie():
    log_page("genie")
    user = current_user()
    st.title("Ask Genie")
    st.caption("Plain-English questions over the governed metrology views and the review queue, answered by the "
               "Metrology Process Analyst Genie space. Each answer shows the SQL it ran.")
    if not genie.SPACE_ID:
        st.error("No Genie space is bound to this app (GENIE_SPACE_ID).")
        return
    chat = st.session_state.setdefault("genie_chat", [])
    top = st.columns([4, 1])
    if top[1].button("New conversation", disabled=not chat):
        st.session_state["genie_chat"], st.session_state["genie_conv"] = [], None
        st.rerun()
    if not chat:
        st.markdown("**Try one of these**")
        cols = st.columns(len(GENIE_SAMPLES))
        for i, q in enumerate(GENIE_SAMPLES):
            if cols[i].button(q, key=f"sample_{i}", use_container_width=True):
                st.session_state["genie_prefill"] = q
                st.rerun()

    for i, (q, ans) in enumerate(chat):
        with st.chat_message("user"):
            st.markdown(q)
        with st.chat_message("assistant", avatar="💬"):
            _render_answer(ans, i)

    question = st.chat_input("Ask about CD trends, tool matching, lots, defects or the review queue")
    question = question or st.session_state.pop("genie_prefill", None)
    if question:
        with st.chat_message("user"):
            st.markdown(question)
        with st.chat_message("assistant", avatar="💬"):
            with st.spinner("Genie is working on it…"):
                try:
                    ans = genie.ask(question, user.email, st.session_state.get("genie_conv"))
                except Exception as e:
                    st.error(f"Genie request failed: {e}")
                    return
            st.session_state["genie_conv"] = ans.conversation_id
            chat.append((question, ans))
            _render_answer(ans, len(chat) - 1)


# --------------------------------------------------------------------------- shell
user = current_user()
with st.sidebar:
    st.markdown("### 🔬 Metrology Review")
    st.caption(f"Signed in as **{user.email}**  \n{', '.join(user.roles)} · {user.user_type}")
    if user.has("admin"):
        st.toggle("Demo mode: relax separation of duties", key="demo_mode",
                  help="Lets one admin play submitter, reviewer and approver. Every relaxed step is flagged "
                       "sod_override in the audit trail.")
        if st.button("Process new instrument files now"):
            rid = be.run_processing()
            be.audit(user.email, "JOB_SUBMIT", "job_run", str(rid), {"mode": "incremental"})
            st.success(f"Run {rid} started")

try:  # pending work shows in the navigation on every page
    _nav_counts = state_counts()
except Exception:
    _nav_counts = {}
GENIE_PAGE = st.Page(page_genie, title="Ask Genie", icon="💬", url_path="ask-genie")
pages = [
    st.Page(page_overview, title="Overview", icon="📊", default=True),
    st.Page(page_submit, title="Submit images", icon="📤"),
    st.Page(page_jobs, title="Job status", icon="⚙️"),
    st.Page(page_review, title=f"Review queue ({_nav_counts.get('PENDING_REVIEW', 0):,})", icon="🔍", url_path="page_review"),
    st.Page(page_approvals, title=f"Approvals ({_nav_counts.get('PENDING_APPROVAL', 0):,})", icon="✅", url_path="page_approvals"),
    st.Page(page_analytics, title="Analytics", icon="📈"),
    GENIE_PAGE,
    st.Page(page_audit, title="Audit trail", icon="🧾"),
    st.Page(page_admin, title="Users & roles", icon="👥"),
]
st.navigation(pages).run()
