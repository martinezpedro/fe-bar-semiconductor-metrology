"""Review / approval state machine with role and separation-of-duties checks.

Every transition is a single Lakebase transaction: guarded UPDATE of
review_items (optimistic on the current state) + append to review_actions.
"""
from dataclasses import dataclass

from . import backend as be

STATES = ["PENDING_REVIEW", "PENDING_APPROVAL", "APPROVED_GOOD", "REJECTED_BAD", "NEEDS_REWORK"]
STATE_LABEL = {
    "PENDING_REVIEW": "Pending review",
    "PENDING_APPROVAL": "Pending approval",
    "APPROVED_GOOD": "Approved / Good",
    "REJECTED_BAD": "Rejected / Bad",
    "NEEDS_REWORK": "Needs rework",
}


@dataclass
class User:
    email: str
    display_name: str
    roles: list
    user_type: str

    def has(self, role):
        return role in self.roles or "admin" in self.roles


class WorkflowError(Exception):
    pass


def _sod(user, item, field, demo_mode, what):
    """Return True if an SoD override was needed (demo mode), raise if not allowed."""
    if item.get(field) and item[field] == user.email:
        if demo_mode and user.has("admin"):
            return True
        raise WorkflowError(f"Separation of duties: you {what} this item, so another user must do this step.")
    return False


def review(user, image_id, verdict, reason_code, comment, demo_mode=False):
    """verdict: GOOD | BAD | NEEDS_REWORK"""
    if not user.has("reviewer"):
        raise WorkflowError("Reviewer role required.")
    if user.user_type == "external":
        raise WorkflowError("External users cannot record review decisions.")
    item = get_item(image_id)
    if item["state"] != "PENDING_REVIEW":
        raise WorkflowError(f"Item is {STATE_LABEL[item['state']]}, not pending review.")
    override = _sod(user, item, "submitted_by", demo_mode, "submitted")
    to_state = "NEEDS_REWORK" if verdict == "NEEDS_REWORK" else "PENDING_APPROVAL"
    action = {"GOOD": "REVIEW_GOOD", "BAD": "REVIEW_BAD", "NEEDS_REWORK": "NEEDS_REWORK"}[verdict]
    _transition(user, image_id, "PENDING_REVIEW", to_state, action, "reviewer", reason_code, comment, override,
                extra_set="reviewer_verdict = %s, reviewed_by = %s, reviewed_at = now()",
                extra_params=(verdict if verdict != "NEEDS_REWORK" else None, user.email))


def approve(user, image_id, approve_verdict, reason_code, comment, demo_mode=False):
    """approve_verdict True -> APPROVED_GOOD / REJECTED_BAD per reviewer verdict; False -> back to review."""
    if not user.has("approver"):
        raise WorkflowError("Approver role required.")
    if user.user_type == "external":
        raise WorkflowError("External users cannot approve.")
    item = get_item(image_id)
    if item["state"] != "PENDING_APPROVAL":
        raise WorkflowError(f"Item is {STATE_LABEL[item['state']]}, not pending approval.")
    override = _sod(user, item, "reviewed_by", demo_mode, "reviewed")
    override = _sod(user, item, "submitted_by", demo_mode, "submitted") or override
    if approve_verdict:
        to_state = "APPROVED_GOOD" if item["reviewer_verdict"] == "GOOD" else "REJECTED_BAD"
        _transition(user, image_id, "PENDING_APPROVAL", to_state, "APPROVE", "approver", reason_code, comment, override,
                    extra_set="approved_by = %s, approved_at = now()", extra_params=(user.email,))
    else:
        _transition(user, image_id, "PENDING_APPROVAL", "PENDING_REVIEW", "DECLINE", "approver", reason_code, comment,
                    override, extra_set="reviewer_verdict = NULL, reviewed_by = NULL, reviewed_at = NULL")


def add_comment(user, image_id, comment):
    if user.user_type == "external" and not user.has("reviewer"):
        raise WorkflowError("External viewers cannot comment.")
    item = get_item(image_id)
    be.pg_exec(
        "INSERT INTO review_actions (image_id, actor_email, acting_role, action, from_state, to_state, comment) "
        "VALUES (%s, %s, %s, 'COMMENT', %s, %s, %s)",
        (image_id, user.email, ",".join(user.roles), item["state"], item["state"], comment),
    )


def _transition(user, image_id, from_state, to_state, action, role, reason_code, comment, override,
                extra_set="", extra_params=()):
    with be.pg() as conn, conn.cursor() as cur:
        cur.execute(
            f"UPDATE review_items SET state = %s, updated_at = now(){', ' + extra_set if extra_set else ''} "
            "WHERE image_id = %s AND state = %s",
            (to_state, *extra_params, image_id, from_state),
        )
        if cur.rowcount != 1:
            raise WorkflowError("Item changed while you were looking at it. Refresh and try again.")
        cur.execute(
            "INSERT INTO review_actions (image_id, actor_email, acting_role, action, from_state, to_state, "
            "reason_code, comment, sod_override) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (image_id, user.email, role, action, from_state, to_state, reason_code or None, comment or None, override),
        )


def get_item(image_id):
    df = be.pg_df("SELECT * FROM review_items WHERE image_id = %s", (image_id,))
    if df.empty:
        raise WorkflowError(f"Unknown image {image_id}")
    return df.iloc[0].to_dict()


def get_or_register_user(email, display_name=None):
    df = be.pg_df("SELECT email, display_name, roles, user_type FROM app_users WHERE email = %s AND active", (email,))
    if df.empty:
        # first visit: least privilege. Non-corporate domains are external.
        corp = email.endswith(("@semiconductor-customer.com", "@databricks.com"))
        be.pg_exec(
            "INSERT INTO app_users (email, display_name, roles, user_type) VALUES (%s, %s, ARRAY['viewer'], %s) "
            "ON CONFLICT (email) DO NOTHING",
            (email, display_name or email.split("@")[0], "employee" if corp else "external"),
        )
        be.audit(email, "USER_REGISTERED", "user", email, {"roles": ["viewer"]})
        df = be.pg_df("SELECT email, display_name, roles, user_type FROM app_users WHERE email = %s", (email,))
    r = df.iloc[0]
    return User(r.email, r.display_name, list(r.roles), r.user_type)
