# Lakebase operational store

The app's live state lives in Lakebase Postgres (project `fabs-metrology`, schema `fabs`). The change data feed replicates it to Delta in `fabs_review`; these queries read that replica.

Collected 2026-10-20 15:49 UTC from workspace fe-vm (Azure, adb-7405605954880111) by `evidence/collect_evidence.py`.

Lakebase project:

```json
{
  "name": "projects/fabs-metrology",
  "uid": "63337e7b-4c0f-46c4-b973-a28990dc27b4",
  "create_time": "2026-10-20T03:12:50Z",
  "update_time": "2026-10-20T15:44:46Z",
  "status": {
    "display_name": "Fabs Metrology Review",
    "pg_version": 17,
    "history_retention_duration": "604800s",
    "default_endpoint_settings": {
      "autoscaling_limit_min_cu": 0.5,
      "autoscaling_limit_max_cu": 2.0,
      "suspend_timeout_duration": "3600s"
    },
    "branch_logical_size_limit_bytes": 35184372088832,
    "synthetic_storage_size_bytes": 0,
    "compute_last_active_time": "2026-10-20T15:44:46Z",
    "owner": "pedro.martinez@databricks.com",
    "enable_pg_native_login": false,
    "default_branch": "projects/fabs-metrology/branches/production",
    "project_id": "fabs-metrology"
  },
  "project_id": "fabs-metrology"
}
```

### Replicated tables

```sql
SELECT table_name, table_type FROM ws_azure_classic_eastus_pedro.information_schema.tables
WHERE table_schema = 'fabs_review' ORDER BY 1
```

| table_name | table_type |
|---|---|
| lb_ai_summaries_history | MANAGED |
| lb_app_users_history | MANAGED |
| lb_audit_events_history | MANAGED |
| lb_reason_codes_history | MANAGED |
| lb_review_actions_history | MANAGED |
| lb_review_items_history | MANAGED |
| lb_submissions_history | MANAGED |
| v_audit_events | VIEW |
| v_review_actions | VIEW |
| v_review_items_current | VIEW |

_10 rows_

### Review queue by state, disposition and priority

```sql
SELECT state, disposition, priority, COUNT(*) AS items FROM ws_azure_classic_eastus_pedro.fabs_review.v_review_items_current
GROUP BY ALL ORDER BY ALL
```

| state | disposition | priority | items |
|---|---|---|---|
| PENDING_REVIEW | FLAGGED | 1 | 394 |
| PENDING_REVIEW | PASS | 2 | 1106 |

_2 rows_

### Review actions (append-only)

```sql
SELECT action, acting_role, COUNT(*) AS actions FROM ws_azure_classic_eastus_pedro.fabs_review.v_review_actions GROUP BY ALL ORDER BY ALL
```

| action | acting_role | actions |
|---|---|---|
| PUBLISHED | system | 1500 |
| REPROCESSED | system | 220 |

_2 rows_

### Audit events by type

```sql
SELECT event_type, COUNT(*) AS events, MIN(event_ts) AS first_event, MAX(event_ts) AS last_event
FROM ws_azure_classic_eastus_pedro.fabs_review.v_audit_events GROUP BY ALL ORDER BY events DESC
```

| event_type | events | first_event | last_event |
|---|---|---|---|
| PIPELINE_PUBLISH | 2 | 2026-10-20T14:23:04.154Z | 2026-10-20T15:44:36.502Z |

_1 rows_
