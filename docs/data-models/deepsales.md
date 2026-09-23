# DeepSales Database — Complete Data Model

**Source:** `DEEPSALES_DB_URL_LIVE` in `backend/.env` (Postgres, RDS `bizdata-rag-sandbox`, db `deepsales`)
**Captured:** 2026-09-23 from the live catalog (43 tables). Regenerate with the introspection
script when the upstream project migrates its schema (`alembic_version` tells you if it changed).
**⚠ Credential note:** the current URL uses the `postgres` superuser with INSERT rights.
ygg-atlas policy requires a read-only role — ask the DeepSales owner for `GRANT SELECT`-only
credentials and swap the URL. Until then the connector's SELECT-only enforcement is the only guard.

DeepSales is YouGotAGift's B2B corporate-portfolio management platform (the atwork_agent_fe
project). It tracks corporates (business clients), their revenue/health/sentiment over time,
CSM tasks, sales leads, and finance top-ups.

## Domain overview (what to build metrics on)

**Dimensions**
- `corporate` (~6.3k) — master client dimension: `corporate_code` (unique key), name, region,
  currency, tier, csm, product, ICP segment/industry, `registered_on`.
- `account_profiles` (~7.7k) — denormalized analytics hub, one row per account
  (`account_code` = corporate_code): health v1/v2 score+status, `revenue_ytd`,
  `revenue_ytd_change`, `avg_order_value`, `ytd_orders`, `active_rate`, `last_order_at`,
  `target_ytd_achievement`, `analyzed_at` (freshness; NULL = never analyzed),
  `product` ('atwork'|'yourewards'), `type` ('atwork'|'yourewards'|'yougotagift').
- `csm` (~7) — customer success managers; `team` ∈ unknown|direct|platform. PII: name, email.
- `poc` (~3k) — client contacts. PII: name, email, phone, designation.
- `company_group` / `company_group_member` — ops-defined parent/subsidiary grouping.
- `product` — product line dimension.

**Facts / time series**
- `corporate_revenue_monthly` (~15.7k) — per corporate per month: `revenue_aed`
  (AED-normalized), `transaction_count`, `revenue_by_currency` JSON, `last_order_at`.
  UNIQUE (corporate_id, month). The reliable revenue time series.
- `corporate_metrics_daily` (~3.9k) — daily financial snapshot per corporate:
  revenue_ytd/90d/prior, AOV, ytd_orders, tier, rfm_segment, wallet_balance.
  UNIQUE (corporate_code, captured_on).
- `corporate_sentiment_daily` — daily support/sentiment: feedback/email negatives,
  intercom tickets & escalations, `weighted_negative_score`, `sentiment_bucket`,
  `escalation_flag`. UNIQUE (corporate_code, captured_on).
- `analysis_snapshots` (~4.4k) — append-only LLM analysis history with cached
  health/revenue metrics; dedup by (corporate_code, content_hash).
- `tasks` (~8.8k) + `task_events`/`task_comments`/`task_notifications` — CSM work items:
  status ∈ pending|in_progress|blocked|completed|cancelled, priority, assignee, due_date,
  source (manual|email_action|topup_invoice|suggestion|insight), category, reason.
- `leads` (~32, growing) + `lead_activities` — sales pipeline: stage ∈
  new|contacted|qualified|won|lost, channel, firmographic scoring
  (industry/size/seniority → total_score, recommended_team direct|platform), value+currency,
  matched/converted corporate codes.
- `topup_invoices` (~868) / `topup_transactions` (~246) — finance events: amount+currency,
  status active|revoked, ops review flags (`needs_review`, `review_reason`).
- `page_sessions` (~8.4k) — DeepSales UI clickstream (durations per page/entity).
- `revenue_target` (~36.8k) — per-account revenue targets.

**Key semantics**
- Health v2: 0–100; band Green ≥ 40, Yellow ≥ 22, Red < 22. At-risk =
  `health_v2_status='Red'` OR `sentiment.escalation_flag=true`.
- Portfolio KPIs are computed over `account_profiles` WHERE `analyzed_at IS NOT NULL`.
- Money is AED-normalized in `corporate_revenue_monthly.revenue_aed`; profile revenue fields
  are YTD (calendar year). All timestamps are timestamptz UTC.
- Freshness markers: `account_profiles.last_synced_at` / `analyzed_at`,
  `corporate_metrics_daily.captured_on`, `corporate_revenue_monthly.computed_at`.
- PII columns (mask/never expose): poc.*, csm.name/email, all *_email/*_name actor fields on
  tasks/leads/comments/notifications, lead contact fields, topup_transactions.sender_email,
  chat_sessions.user_email.

## Full schema (from live catalog)

### account_profiles  (~7,704 rows)
PK: account_code
- account_code: character varying NOT NULL
- account_name: character varying
- health_status: character varying
- health_score: integer
- csm_name: character varying
- tier: character varying
- account_status: character varying
- raw_data: json
- last_synced_at: timestamp with time zone NOT NULL
- type: character varying
- product: character varying
- health_v2_score: integer
- health_v2_status: character varying
- revenue_ytd: numeric
- revenue_ytd_change: numeric
- avg_order_value: numeric
- ytd_orders: integer
- ytd_order_days: integer
- active_rate: numeric
- last_contact_at: timestamp with time zone
- last_order_at: timestamp with time zone
- target_ytd_achievement: numeric
- icp_size_tier: character varying
- analyzed_at: timestamp with time zone

### alembic_version  (~1 rows)
PK: version_num
- version_num: character varying NOT NULL

### analysis_snapshots  (~4,386 rows)
PK: id
UNIQUE: corporate_code, content_hash
- id: integer NOT NULL
- corporate_code: character varying NOT NULL
- analyzed_at: timestamp with time zone
- health_v2_score: integer
- health_v2_status: character varying
- revenue_ytd: numeric
- revenue_ytd_change: numeric
- avg_order_value: numeric
- ytd_orders: integer
- narrative: jsonb
- content_hash: character varying NOT NULL
- created_at: timestamp with time zone NOT NULL
- source_fingerprint: character varying
- pre_band: character varying
- tier: character varying
- rfm_segment: character varying
- analysis_version: character varying

### app_settings  (~0 rows)
PK: key
- key: character varying NOT NULL
- value: json NOT NULL
- updated_by_email: character varying NOT NULL
- updated_at: timestamp with time zone NOT NULL

### chat_messages  (~101 rows)
PK: id
FK: session_id -> chat_sessions.id
- id: uuid NOT NULL
- session_id: uuid NOT NULL
- role: character varying NOT NULL
- content: text NOT NULL
- tool_calls: json
- guardrail_flags: json
- model: character varying
- token_usage: json
- created_at: timestamp with time zone NOT NULL
- feedback_rating: character varying
- feedback_category: character varying
- feedback_comment: text

### chat_query_requests  (~0 rows)
PK: id
- id: uuid NOT NULL
- entry_key: character varying NOT NULL
- params: jsonb
- status: character varying NOT NULL
- result: jsonb
- error: text
- requested_by: character varying
- session_id: uuid
- created_at: timestamp with time zone NOT NULL
- started_at: timestamp with time zone
- finished_at: timestamp with time zone

### chat_sessions  (~10 rows)
PK: id
- id: uuid NOT NULL
- user_uid: character varying NOT NULL
- user_email: character varying NOT NULL
- title: character varying NOT NULL
- corporate_code: character varying
- created_at: timestamp with time zone NOT NULL
- updated_at: timestamp with time zone NOT NULL

### company_group  (~165 rows)
PK: id
- id: integer NOT NULL
- name: character varying NOT NULL
- name_key: character varying NOT NULL
- source: character varying NOT NULL
- created_at: timestamp with time zone NOT NULL
- updated_at: timestamp with time zone NOT NULL

### company_group_member  (~485 rows)
PK: company_group_id, corporate_id
FK: company_group_id -> company_group.id; corporate_id -> corporate.id
- company_group_id: integer NOT NULL
- corporate_id: integer NOT NULL
- relation: character varying
- source: character varying NOT NULL
- source_ref: character varying
- created_at: timestamp with time zone NOT NULL

### corporate  (~6,343 rows)
PK: id
FK: csm_id -> csm.id; product_id -> product.id
- id: integer NOT NULL
- corporate_code: character varying NOT NULL
- corporate_name: character varying NOT NULL
- region: character varying
- currency: character varying
- tier: character varying
- csm_name: character varying
- payment_terms: text
- account_management_type: character varying
- subscriptions: boolean NOT NULL
- product_id: integer
- icp_segment: character varying
- icp_usecase: character varying
- icp_industry: character varying
- icp_synced_at: timestamp with time zone
- email_domains: json
- csm_id: integer
- registered_on: timestamp with time zone
- first_order_analysis_at: timestamp with time zone

### corporate_metrics_daily  (~3,907 rows)
PK: id
UNIQUE: corporate_code, captured_on
- id: integer NOT NULL
- corporate_code: character varying NOT NULL
- captured_on: date NOT NULL
- captured_at: timestamp with time zone NOT NULL
- revenue_ytd: numeric
- revenue_ytd_change: numeric
- revenue_ytd_prior: numeric
- avg_order_value: numeric
- ytd_orders: integer
- wallet_balance: numeric
- tier: character varying
- rfm_segment: character varying
- pre_band: character varying
- source_fingerprint: character varying
- created_at: timestamp with time zone NOT NULL
- last_order_date: date
- vol_bucket: integer
- rev_90d: numeric
- rev_prior_90d: numeric
- ratio_bucket: integer
- sentiment_fingerprint: character varying
- sentiment_last_item_at: timestamp with time zone

### corporate_poc_link  (~3,132 rows)
PK: corporate_id, poc_id
FK: corporate_id -> corporate.id; poc_id -> poc.id
- corporate_id: integer NOT NULL
- poc_id: integer NOT NULL

### corporate_revenue_monthly  (~15,703 rows)
PK: id
FK: corporate_id -> corporate.id
UNIQUE: corporate_id, month
- id: integer NOT NULL
- corporate_id: integer NOT NULL
- month: date NOT NULL
- transaction_count: integer NOT NULL
- revenue_aed: numeric NOT NULL
- revenue_by_currency: json
- computed_at: timestamp with time zone NOT NULL
- last_order_at: timestamp with time zone

### corporate_sentiment_daily  (~0 rows)
PK: id
UNIQUE: corporate_code, captured_on
- id: integer NOT NULL
- corporate_code: character varying NOT NULL
- business_unit: character varying NOT NULL
- captured_on: date NOT NULL
- fb_neg_unresolved: integer NOT NULL
- fb_neg_resolved_decaying: integer NOT NULL
- fb_pos_90d: integer NOT NULL
- fb_neu_90d: integer NOT NULL
- email_neg_90d: integer NOT NULL
- email_pos_90d: integer NOT NULL
- email_responded_neg: integer NOT NULL
- weighted_negative_score: double precision NOT NULL
- sentiment_bucket: integer NOT NULL
- escalation_flag: boolean NOT NULL
- sentiment_fingerprint: character varying NOT NULL
- last_item_at: timestamp with time zone
- digest: jsonb
- captured_at: timestamp with time zone NOT NULL
- intercom_tickets_90d: integer NOT NULL
- intercom_open: integer NOT NULL
- intercom_open_escalations: integer NOT NULL
- intercom_last_at: timestamp with time zone

### csm  (~7 rows)
PK: id
- id: integer NOT NULL
- name: character varying NOT NULL
- email: character varying
- firebase_uid: character varying
- is_active: boolean NOT NULL
- created_at: timestamp with time zone NOT NULL
- is_human: boolean NOT NULL
- team: character varying NOT NULL
- is_primary: boolean NOT NULL

### delta_dispatch_inflight  (~0 rows)
PK: corporate_code
- corporate_code: character varying NOT NULL
- business_unit: character varying NOT NULL
- intended_source_fingerprint: character varying NOT NULL
- intended_vol_bucket: integer
- intended_ratio_bucket: integer
- last_order_date: date
- rev_90d: numeric
- rev_prior_90d: numeric
- dispatched_at: timestamp with time zone NOT NULL
- retry_count: integer NOT NULL
- intended_sentiment_fingerprint: character varying
- intended_sentiment_last_item_at: timestamp with time zone

### email_logs  (~167 rows)
PK: id
- id: uuid NOT NULL
- template_id: uuid
- template_key: character varying NOT NULL
- source_ref: character varying
- to_recipients: json NOT NULL
- cc_recipients: json NOT NULL
- context: json NOT NULL
- rendered_subject: character varying NOT NULL
- status: character varying NOT NULL
- error: character varying
- retry_of: uuid
- triggered_by: character varying
- sent_at: timestamp with time zone NOT NULL

### email_recipient_groups  (~0 rows)
PK: id
UNIQUE: group_key, email
- id: uuid NOT NULL
- group_key: character varying NOT NULL
- email: character varying NOT NULL
- created_at: timestamp with time zone NOT NULL
- created_by: character varying

### email_templates  (~0 rows)
PK: id
- id: uuid NOT NULL
- key: character varying NOT NULL
- name: character varying NOT NULL
- description: character varying
- subject: character varying NOT NULL
- html_body: character varying NOT NULL
- enabled: boolean NOT NULL
- created_at: timestamp with time zone NOT NULL
- updated_at: timestamp with time zone NOT NULL
- updated_by: character varying

### event_sources  (~11 rows)
PK: id
UNIQUE: key_hash; source_name
- id: uuid NOT NULL
- source_name: character varying NOT NULL
- key_prefix: character varying
- key_hash: character varying
- hmac_secret: character varying
- is_active: boolean NOT NULL
- created_at: timestamp with time zone NOT NULL
- last_used_at: timestamp with time zone
- auth_method: character varying NOT NULL
- basic_auth_username: character varying
- basic_auth_password_hash: character varying

### group_permission_link  (~43 rows)
PK: group_id, permission_id
FK: group_id -> rbac_group.id; permission_id -> permission.id
- group_id: integer NOT NULL
- permission_id: integer NOT NULL

### ingested_events  (~2,190 rows)
PK: id
FK: source_id -> event_sources.id
- id: uuid NOT NULL
- source_id: uuid NOT NULL
- source_name: character varying NOT NULL
- event_type: character varying NOT NULL
- entity_id: character varying NOT NULL
- entity_type: character varying NOT NULL
- version: character varying NOT NULL
- metadata: json
- idempotency_key: character varying
- occurred_at: timestamp with time zone NOT NULL
- received_at: timestamp with time zone NOT NULL
- raw_payload: jsonb

### lead_activities  (~63 rows)
PK: id
FK: lead_id -> leads.id
- id: uuid NOT NULL
- lead_id: uuid NOT NULL
- type: character varying NOT NULL
- actor_email: character varying
- actor_name: character varying
- from_stage: character varying
- to_stage: character varying
- body: character varying
- created_at: timestamp with time zone NOT NULL

### leads  (~32 rows)
PK: id
FK: source_id -> event_sources.id
- id: uuid NOT NULL
- external_ref: character varying
- source: character varying NOT NULL
- source_id: uuid
- source_name: character varying
- channel: character varying
- contact_name: character varying NOT NULL
- company_name: character varying
- contact_email: character varying
- contact_phone: character varying
- email_domain: character varying
- stage: character varying NOT NULL
- value: numeric
- currency: character varying NOT NULL
- owner_email: character varying
- owner_name: character varying
- matched_corporate_code: character varying
- converted_corporate_code: character varying
- notes: character varying
- created_by_email: character varying
- created_by_name: character varying
- raw_payload: json
- metadata: json
- created_at: timestamp with time zone NOT NULL
- updated_at: timestamp with time zone NOT NULL
- last_activity_at: timestamp with time zone NOT NULL
- stage_changed_at: timestamp with time zone NOT NULL
- invalid_at: timestamp with time zone
- invalid_reason: character varying
- industry: character varying
- industry_qualifies: boolean
- company_size_band: character varying
- size_qualifies: boolean
- seniority_tier: character varying
- seniority_qualifies: boolean
- score_industry: integer
- score_size: integer
- score_seniority: integer
- total_score: integer
- recommended_team: character varying
- score_status: character varying NOT NULL
- needs_review_reason: character varying
- enrichment_source: character varying
- enrichment_confidence: double precision
- enrichment_evidence_url: character varying
- scored_at: timestamp with time zone
- notified_at: timestamp with time zone

### page_sessions  (~8,400 rows)
PK: session_id
- session_id: character varying NOT NULL
- user_id: character varying NOT NULL
- device_id: character varying NOT NULL
- login_session_id: character varying
- page_path: character varying NOT NULL
- page_raw_path: character varying NOT NULL
- page_entity_id: character varying
- page_entity_type: character varying
- total_duration_s: integer NOT NULL
- active_duration_s: integer NOT NULL
- idle_duration_s: integer NOT NULL
- started_at: timestamp with time zone NOT NULL
- last_flushed_at: timestamp with time zone NOT NULL
- is_final: boolean NOT NULL

### permission  (~0 rows)
PK: id
- id: integer NOT NULL
- name: character varying NOT NULL
- description: character varying

### poc  (~3,037 rows)
PK: id
- id: integer NOT NULL
- name: character varying NOT NULL
- email: character varying NOT NULL
- phone: character varying
- designation: character varying

### product  (~0 rows)
PK: id
UNIQUE: code
- id: integer NOT NULL
- name: character varying NOT NULL
- code: character varying NOT NULL
- created_at: timestamp with time zone

### rbac_group  (~4 rows)
PK: id
- id: integer NOT NULL
- name: character varying NOT NULL
- description: character varying
- analytics_tag: character varying
- analytics_display_order: integer
- created_at: timestamp with time zone NOT NULL

### revenue_target  (~36,840 rows)
PK: id
FK: corporate_id -> corporate.id
- id: integer NOT NULL
- corporate_id: integer NOT NULL
- year: integer NOT NULL
- month: integer NOT NULL
- target_amount: double precision
- currency: character varying

### scheduler_runs  (~8,391 rows)
PK: id
- id: uuid NOT NULL
- job_type: character varying NOT NULL
- status: character varying NOT NULL
- trigger: character varying NOT NULL
- started_at: timestamp with time zone NOT NULL
- finished_at: timestamp with time zone
- items_created: integer NOT NULL
- items_failed: integer NOT NULL
- summary: json
- error: character varying
- instance: character varying

### suggested_actions  (~308 rows)
PK: id
FK: task_id -> tasks.id
- id: uuid NOT NULL
- feedback_id: character varying NOT NULL
- account_id: character varying NOT NULL
- corporate_code: character varying NOT NULL
- title: character varying NOT NULL
- description: character varying
- priority: character varying NOT NULL
- suggested_due_date: date
- urgency: integer NOT NULL
- sentiment: character varying NOT NULL
- category: character varying
- status: character varying NOT NULL
- task_id: uuid
- classifier_version: character varying NOT NULL
- schema_version: integer NOT NULL
- extra: json
- submitter_email: character varying NOT NULL
- submitter_name: character varying
- created_at: timestamp with time zone NOT NULL
- updated_at: timestamp with time zone NOT NULL
- dismissed_at: timestamp with time zone
- converted_at: timestamp with time zone

### task_comments  (~212 rows)
PK: id
FK: parent_id -> task_comments.id; task_id -> tasks.id
- id: uuid NOT NULL
- task_id: uuid NOT NULL
- parent_id: uuid
- author_email: text NOT NULL
- author_name: text
- text: text NOT NULL
- created_at: timestamp with time zone NOT NULL
- outcome: character varying

### task_events  (~9,712 rows)
PK: id
FK: task_id -> tasks.id
- id: uuid NOT NULL
- task_id: uuid NOT NULL
- event_type: character varying NOT NULL
- old_value: character varying
- new_value: character varying
- actor_email: character varying NOT NULL
- actor_name: character varying
- created_at: timestamp with time zone NOT NULL

### task_notifications  (~490 rows)
PK: id
FK: task_id -> tasks.id
- id: uuid NOT NULL
- recipient_email: character varying NOT NULL
- task_id: uuid NOT NULL
- task_title: character varying NOT NULL
- account_id: character varying NOT NULL
- notification_type: character varying NOT NULL
- actor_email: character varying NOT NULL
- actor_name: character varying
- read: boolean NOT NULL
- created_at: timestamp with time zone NOT NULL

### tasks  (~8,793 rows)
PK: id
FK: source_run_id -> scheduler_runs.id
- id: uuid NOT NULL
- account_id: text NOT NULL
- corporate_code: text NOT NULL
- title: text NOT NULL
- description: text
- assignee_email: text NOT NULL
- assignee_name: text
- created_by_email: text NOT NULL
- created_by_name: text
- status: text NOT NULL
- priority: text NOT NULL
- due_date: date
- comment_count: integer NOT NULL
- created_at: timestamp with time zone NOT NULL
- updated_at: timestamp with time zone NOT NULL
- source: character varying NOT NULL
- source_ref: character varying
- source_metadata: json
- type: character varying NOT NULL
- category: character varying
- source_run_id: uuid
- reason: character varying

### topup_amount_edits  (~0 rows)
PK: id
FK: transaction_id -> topup_transactions.id
- id: uuid NOT NULL
- transaction_id: uuid NOT NULL
- old_amount: numeric
- new_amount: numeric NOT NULL
- note: text NOT NULL
- edited_by: character varying NOT NULL
- edited_at: timestamp with time zone NOT NULL

### topup_authorized_senders  (~0 rows)
PK: id
- id: uuid NOT NULL
- email: character varying NOT NULL
- active: boolean NOT NULL
- created_by_email: character varying NOT NULL
- created_at: timestamp with time zone NOT NULL
- disabled_at: timestamp with time zone
- disabled_by_email: character varying

### topup_invoice_uploads  (~47 rows)
PK: id
FK: transaction_id -> topup_transactions.id
- id: uuid NOT NULL
- transaction_id: uuid NOT NULL
- task_id: uuid
- s3_key: character varying NOT NULL
- filename: character varying NOT NULL
- content_type: character varying NOT NULL
- size_bytes: integer NOT NULL
- uploaded_by: character varying NOT NULL
- uploaded_by_name: character varying
- uploaded_at: timestamp with time zone NOT NULL
- superseded_at: timestamp with time zone
- created_at: timestamp with time zone NOT NULL
- kind: character varying NOT NULL

### topup_invoices  (~868 rows)
PK: id
FK: source_id -> event_sources.id
UNIQUE: reference_id
- id: uuid NOT NULL
- account_code: character varying NOT NULL
- reference_id: character varying NOT NULL
- ygg_record_id: integer
- amount: numeric
- currency: character varying
- top_up_date: timestamp with time zone
- document_url: character varying
- status: character varying NOT NULL
- revoked_at: timestamp with time zone
- source_id: uuid NOT NULL
- raw_payload: json
- created_at: timestamp with time zone NOT NULL
- updated_at: timestamp with time zone NOT NULL
- invoice_reference_number: character varying
- document_s3_key: character varying

### topup_transactions  (~246 rows)
PK: id
FK: task_id -> tasks.id
- id: uuid NOT NULL
- email_fingerprint: character varying NOT NULL
- sender_email: character varying NOT NULL
- corporate_id_raw: character varying
- account_code: character varying
- corporate_name: character varying
- amount: numeric
- currency: character varying
- email_date: timestamp with time zone
- source_email_id: integer
- gmail_message_id: character varying
- thread_id: character varying
- topup_completed: boolean NOT NULL
- topup_completed_at: timestamp with time zone
- topup_completed_by: character varying
- invoice_required: boolean
- needs_review: boolean NOT NULL
- review_reason: character varying
- task_id: uuid
- created_at: timestamp with time zone NOT NULL
- updated_at: timestamp with time zone NOT NULL
- item_fingerprint: character varying
- line_items: json

### user_devices  (~37 rows)
PK: device_id
- device_id: character varying NOT NULL
- user_id: character varying NOT NULL
- user_agent: text
- first_seen_at: timestamp with time zone NOT NULL
- last_seen_at: timestamp with time zone NOT NULL

### user_group_link  (~31 rows)
PK: user_uid, group_id
FK: group_id -> rbac_group.id
- user_uid: character varying NOT NULL
- group_id: integer NOT NULL

