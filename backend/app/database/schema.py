"""Table and index definitions for the SQLite store."""

from __future__ import annotations

TABLES = """
CREATE TABLE IF NOT EXISTS customer_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    summary TEXT NOT NULL,
    entities_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    tenant_id TEXT NOT NULL DEFAULT 'tenant-demo'
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    model TEXT,
    request_json TEXT NOT NULL,
    decision_json TEXT NOT NULL,
    guardrail_json TEXT NOT NULL,
    actor TEXT,
    created_at TEXT NOT NULL,
    tenant_id TEXT NOT NULL DEFAULT 'tenant-demo'
);

CREATE TABLE IF NOT EXISTS support_ticket (
    case_id TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    customer_json TEXT NOT NULL,
    channel TEXT NOT NULL,
    subject TEXT,
    message TEXT NOT NULL,
    received_at TEXT NOT NULL,
    minutes_ago INTEGER NOT NULL,
    truth_intent TEXT NOT NULL,
    truth_urgency TEXT NOT NULL,
    triage_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    tenant_id TEXT NOT NULL DEFAULT 'tenant-demo',
    last_message_at TEXT,
    PRIMARY KEY (tenant_id, case_id)
);

CREATE TABLE IF NOT EXISTS app_setting (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS case_lifecycle (
    case_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    state TEXT NOT NULL,
    external_thread_id TEXT,
    provider TEXT,
    assigned_to TEXT,
    resolved_at TEXT,
    reopened_count INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, case_id)
);

CREATE TABLE IF NOT EXISTS support_message (
    id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    channel TEXT NOT NULL,
    direction TEXT NOT NULL,
    provider TEXT NOT NULL,
    provider_message_id TEXT,
    external_thread_id TEXT,
    contact TEXT,
    subject TEXT,
    body TEXT NOT NULL,
    delivery_status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    rfc_message_id TEXT
);

CREATE TABLE IF NOT EXISTS webhook_event (
    event_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    processed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS delivery_job (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL,
    job_type TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 5,
    run_after TEXT NOT NULL,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS human_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    actor TEXT NOT NULL,
    predicted_json TEXT NOT NULL,
    corrected_json TEXT NOT NULL,
    response_accepted INTEGER,
    response_edited INTEGER NOT NULL DEFAULT 0,
    reason TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS api_principal (
    token_hash TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    display_name TEXT NOT NULL,
    role TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS case_sequence (
    name TEXT PRIMARY KEY,
    next_value INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS knowledge_policy (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    source_url TEXT,
    version TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS case_note (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    actor TEXT NOT NULL,
    body TEXT NOT NULL,
    mentions_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS proof_run (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL,
    report_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS team_member (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL,
    name TEXT NOT NULL,
    role TEXT NOT NULL,
    teams_json TEXT NOT NULL,
    capacity INTEGER NOT NULL,
    availability TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (tenant_id, name)
);

CREATE TABLE IF NOT EXISTS usage_counter (
    key TEXT PRIMARY KEY,
    count INTEGER NOT NULL
);
"""


INDEXES = """
CREATE INDEX IF NOT EXISTS idx_memory_customer ON customer_memory(customer_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_case ON audit_log(tenant_id, case_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_tenant_time ON audit_log(tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ticket_recent ON support_ticket(tenant_id, last_message_at DESC);
CREATE INDEX IF NOT EXISTS idx_lifecycle_tenant_state
ON case_lifecycle(tenant_id, state, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_message_case ON support_message(tenant_id, case_id, created_at ASC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_message_provider_id
ON support_message(provider, provider_message_id)
WHERE provider_message_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_message_rfc_id ON support_message(tenant_id, rfc_message_id)
WHERE rfc_message_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_job_ready ON delivery_job(status, run_after, id);
CREATE INDEX IF NOT EXISTS idx_feedback_case ON human_feedback(case_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_policy_tenant_active
ON knowledge_policy(tenant_id, active, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_case_note_case
ON case_note(tenant_id, case_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_proof_run_tenant
ON proof_run(tenant_id, created_at DESC);
"""
