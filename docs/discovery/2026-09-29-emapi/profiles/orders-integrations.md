# Profile: orders-integrations (ygag_ecom_orders_db)

Profiled 2026-09-29 through `atlasq.sh` (atlas EC2 over SSH, READ ONLY transaction, Aurora read replica, role `<emapi_login_role>`).

## BLOCKER: no row-level access

`<emapi_login_role>` has **zero SELECT grants on any of the 159 base tables in `public`** of `ygag_ecom_orders_db` (exact, Q6/Q11). Of the 161 relations in `public`, only 2 are readable, and both are views: `pg_stat_statements` and `pg_stat_statements_info` (Q11). Their query text is hidden from this role. **`pg_stat_statements` is cluster-wide**, not per database. The earlier cluster totals (4,980 statements, 419,972,814 calls, Q12) are therefore mostly other databases' workload. Grouping by `dbid` → `pg_database` (exact at query time, Q17):

| Database | Tracked stmts | Calls | Rows | Visible text |
|---|---|---|---|---|
| ygag_ecomweb_stores_db | 4,683 | 384,638,644 | 593,405,124 | 4 |
| rdsadmin | 67 | 33,583,134 | 10,464,837 | 0 |
| **ygag_ecom_orders_db** | **20** | **1,858,925** | **3,459,861** | 4 |
| ygag_ecom_users_db | 4 | 536 | 0 | 4 |
| ygag_emapi_stores_db | 4 | 196 | 0 | 4 |
| ygag_plusoffers_db | 3 | 6 | 0 | 0 |

The orders DB accounts for under 0.5% of tracked calls. Its 4 visible-text statements are our own profiling queries; the 16 visible statements are spread 4 per DB across 4 DBs. The DB can be read from `dbid` and calls/rows are visible even though the text is redacted.

**The orders-DB statement set is DRIFTING (STRUCTURAL, re-measured 2026-09-29, Q18/Q27).** Two snapshots on the same day disagree:

| Snapshot | Stmts | Calls | Rows | Largest rows/call |
|---|---|---|---|---|
| First pass (Q17/Q18) | 20 | 1,858,925 | 3,459,861 | 19 calls / 36,575 rows = 1,925 (80 ms mean) |
| Re-query (Q27) | 20 (19 returned by the per-call listing) | 1,860,334 | 3,426,135 | 483 calls / 16,053 rows = 33.2 (2.7 ms mean) |

Total rows went *down* while calls went up. So statements are being evicted and replaced between snapshots: the 1,925-rows/call statement has gone (the round-3 critic's count of 18 statements was a third, intermediate state). The stable part is the high-volume small statements: 225,147 calls / 2,249,929 rows (10.0 rows/call), 114,968 / 962,013 (8.4), 19,810 / 195,722 (9.9), and a 1,496,479-call statement returning 0 rows (a keep-alive or existence probe). `pg_stat_statements_info.dealloc` rose from 663,052 to 664,237 during the day (Q26), and the pgss window is **95.5 days** (`now() - pg_stat_statements_info.stats_reset`, Q26). That is much longer than the 35.53-day table-stat window, so pgss and `pg_stat_user_tables` counters cannot be divided into each other. The turnover is further evidence that pgss cannot identify the youpay extractor: whatever statement did those scans is either being evicted or was never tracked long enough.

The first data query failed with `InsufficientPrivilegeError: permission denied for table kafka_giftcreationlog`. `has_table_privilege(...,'SELECT')` returns false for every table and `has_column_privilege` returns 0 columns (Q5, Q6). `pg_stats` also returns no rows, because it filters by column privilege. `pg_sequences.last_value` is NULL for the same reason.

**Evidence labels used in this profile.** **VALIDATED** = backed by a data query that was run. **No claim in this profile is VALIDATED**, because no table in this DB is readable. Exact catalog facts (for example "0 of 159 tables granted", byte sizes, constraint definitions, scan counters) are marked "exact" but are still STRUCTURAL: they describe the schema and workload, not the business data. **STRUCTURAL** = inferred from schema, metadata or stats. **NEEDS-GRANT** = a hypothesis that needs table data we cannot read; the table and columns are named.

So this profile is **metadata only**. It is built from the catalog: `pg_class`, `pg_attribute`, `pg_constraint`, `pg_indexes`, `pg_stat_user_tables`/`pg_stat_user_indexes`, `pg_stat_database` and sizes. **Items 3 to 6 of the brief could not be measured**: status distributions, min/max timestamps, monthly trends and failure rates. They are listed as work to do once access is granted. I made no attempt to get around the permission. Every number below is either an **estimate** (`reltuples`, catalog statistic) or **exact** (a catalog fact such as bytes or a constraint definition).

Required action: see the **Grant request** below (all grant needs consolidated there). The counterpart databases `ygag_youpay_db` (54 base tables) and `ygag_ecom_gifts_db` (110 base tables) are just as blocked: 0 readable tables and 0 readable views in each (exact, Q13). They belong in the same request.

### Grant request (column allowlist + PII-safe views; secrets and free text excluded)

Everything in this section is BLOCKED — needs grant. Design rule: **free-text error columns are never granted raw.** `kafka_giftcreationlog.error` / `.failure`, `kafka_*datalog.error_data`, `kafka_legacyfraudsynclog.error`, `kafka_blacklistusergiftlog.error` and youpay `response_summary` commonly embed payload fragments (emails, names, gift codes, card or order refs). They are exposed only through `atlas_ro.*` views that return a `has_error` flag and a normalized error class (digits, emails, uuids and long hex/token strings replaced, then truncated to 60 chars). The same applies to `django_admin_log.change_message` (keys only) and `core_remoteurlconfig.url` (host only).

```sql
-- ygag_ecom_orders_db — run by the DB owner; schema atlas_ro owned by an admin role, SELECT granted to <emapi_login_role>
CREATE SCHEMA IF NOT EXISTS atlas_ro;

-- shared normalizer: strips PII-bearing fragments, keeps the error "shape"
CREATE FUNCTION atlas_ro.err_class(t text) RETURNS text LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE WHEN t IS NULL OR btrim(t) = '' THEN NULL ELSE left(
    regexp_replace(regexp_replace(regexp_replace(regexp_replace(t,
      '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', '<email>', 'g'),
      '[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}', '<uuid>', 'g'),
      '[A-Za-z0-9]{16,}', '<tok>', 'g'),
      '[0-9]+', '<n>', 'g'), 60) END $$;

-- datalog family: no `data` (jsonb payload), no raw error_data. Non-text columns granted raw so TABLESAMPLE works:
GRANT SELECT (id, status, start_timestamp, completed_timestamp)
  ON kafka_atworkkafkadatalog, kafka_plusofferkafkadatalog, kafka_solddateupdatekafkadatalog,
     kafka_blacklistuserkafkadatalog, kafka_productofferkafkadatalog, kafka_plusofferconfigdatalog TO <emapi_login_role>;
CREATE VIEW atlas_ro.kafka_datalog AS
  SELECT 'atwork' src, id, status, start_timestamp, completed_timestamp,
         (btrim(error_data) <> '') has_error, atlas_ro.err_class(error_data) error_class
  FROM kafka_atworkkafkadatalog
  UNION ALL SELECT 'plusoffer', id, status, start_timestamp, completed_timestamp, (btrim(error_data)<>''), atlas_ro.err_class(error_data) FROM kafka_plusofferkafkadatalog
  UNION ALL SELECT 'solddate',  id, status, start_timestamp, completed_timestamp, (btrim(error_data)<>''), atlas_ro.err_class(error_data) FROM kafka_solddateupdatekafkadatalog
  UNION ALL SELECT 'blacklistuser', id, status, start_timestamp, completed_timestamp, (btrim(error_data)<>''), atlas_ro.err_class(error_data) FROM kafka_blacklistuserkafkadatalog
  UNION ALL SELECT 'productoffer', id, status, start_timestamp, completed_timestamp, (btrim(error_data)<>''), atlas_ro.err_class(error_data) FROM kafka_productofferkafkadatalog
  UNION ALL SELECT 'plusofferconfig', id, status, start_timestamp, completed_timestamp, (btrim(error_data)<>''), atlas_ro.err_class(error_data) FROM kafka_plusofferconfigdatalog;
-- (optional, separate) key-name view of `data`: SELECT src, id, jsonb_object_keys(data) — names only, never values

-- gift creation: no payload, no created_gift_details values, no raw error/failure.
GRANT SELECT (id, created_on, modified_on, event_id, status, order_id) ON kafka_giftcreationlog TO <emapi_login_role>;  -- for TABLESAMPLE (P2)
CREATE VIEW atlas_ro.kafka_giftcreationlog AS
  SELECT id, created_on, modified_on, event_id, status, order_id,
         (error   IS NOT NULL AND btrim(error)   <> '') has_error,   atlas_ro.err_class(error)   error_class,
         (failure IS NOT NULL AND btrim(failure) <> '') has_failure, atlas_ro.err_class(failure) failure_class,
         CASE WHEN created_gift_details IS NULL OR btrim(created_gift_details) = '' THEN 'empty'
              WHEN left(ltrim(created_gift_details),1) = '[' THEN 'array' ELSE 'other' END gift_details_shape,
         CASE WHEN left(ltrim(created_gift_details),1) = '[' AND created_gift_details::text IS JSON ARRAY  -- PG16 IS JSON; older: safe-parse function
              THEN jsonb_array_length(created_gift_details::jsonb) END gifts_created
  FROM kafka_giftcreationlog;

GRANT SELECT (id, created_on, modified_on, event_id, status) ON kafka_legacyfraudsynclog, kafka_blacklistusergiftlog TO <emapi_login_role>;
CREATE VIEW atlas_ro.kafka_eventlog AS   -- legacy fraud + blacklist gift; modified_on = retry span, event_id = idempotency
  SELECT 'legacyfraud' src, id, created_on, modified_on, event_id, status,
         (error IS NOT NULL AND btrim(error)<>'') has_error, atlas_ro.err_class(error) error_class FROM kafka_legacyfraudsynclog
  UNION ALL SELECT 'blacklistgift', id, created_on, modified_on, event_id, status,
         (error IS NOT NULL AND btrim(error)<>''), atlas_ro.err_class(error) FROM kafka_blacklistusergiftlog;

-- youpay: plain column grant for non-PII columns; response_summary only via the view
GRANT SELECT (id, created_on, modified_on, transaction_id, payment_reference, order_reference, invoice_id,
  amount, base_amount, vat_amount, service_fee, processing_fee, paid_amount, gateway_charge, currency,
  cart_amount, cart_base_amount, "cart_VAT_amount", cart_service_fee, cart_currency,
  payment_gateway, payment_status, payment_method, payment_scheme, channel_code, platform, language,
  settlement_entity, approved, is_fraud, is_flagged, is_gcc_card, card_issuer_country,
  available_amount, payable_amount, redeemed_amount, point_program, loyalty_level, is_qitaf_enabled,
  point_collection_enabled, is_full_redemption, qitaf_request_id,
  available_points, redeemed_points, earned_point)
  ON youpayclient_youpayclienttransactiondata TO <emapi_login_role>;
CREATE VIEW atlas_ro.youpay_derived AS
  SELECT id, atlas_ro.err_class(response_summary) response_class,
         jsonb_typeof(order_items) items_type,
         CASE WHEN jsonb_typeof(order_items)='array'   THEN jsonb_array_length(order_items)   END n_items,
         CASE WHEN jsonb_typeof(order_history)='array' THEN jsonb_array_length(order_history) END n_history,
         CASE WHEN jsonb_typeof(udf1)='object' THEN ARRAY(SELECT jsonb_object_keys(udf1)) END udf1_keys,
         CASE WHEN jsonb_typeof(brand_details)='object' THEN (SELECT count(*) FROM jsonb_object_keys(brand_details)) END n_brand_keys,
         split_part(split_part(success_url,'://',2),'/',1) success_host   -- host only, no path/query
  FROM youpayclient_youpayclienttransactiondata;
  -- EXCLUDED (never granted raw): customer_email, customer_name, name_on_card, customer_ip_address, card_bin, card_last4,
  --   points_collected_mobile_number, points_redeemed_mobile_number, session_id, response_summary,
  --   success_url, failure_url, cancel_url, verify_url, order_items, order_history, brand_details, brand_calculations, udf1

-- webhooks
GRANT SELECT (id, received_at) ON webhooks_merchantwebhookmessage TO <emapi_login_role>;
CREATE VIEW atlas_ro.webhook_message AS
  SELECT m.id, m.received_at, (m.error_message IS NOT NULL) has_error,
         CASE WHEN jsonb_typeof(m.message)='object'       THEN ARRAY(SELECT jsonb_object_keys(m.message)) END message_keys,
         CASE WHEN jsonb_typeof(m.error_message)='object' THEN ARRAY(SELECT jsonb_object_keys(m.error_message)) END error_keys,
         (m.ip_address = c.sender_ip) from_configured_sender     -- boolean only; neither IP is exposed
  FROM webhooks_merchantwebhookmessage m CROSS JOIN LATERAL
       (SELECT sender_ip FROM webhooks_webhookconfig WHERE is_active ORDER BY id LIMIT 1) c;
GRANT SELECT (id, name, is_active) ON webhooks_webhookconfig TO <emapi_login_role>;

-- reference / config
GRANT SELECT ON core_currency, core_basecurrency, core_currencyexchangerate, core_currencybasketlimit,
  core_language, core_siteconfig, core_unsupportedcountry, django_content_type TO <emapi_login_role>;
GRANT SELECT (id, created_on, modified_on, server, is_active) ON core_remoteurlconfig TO <emapi_login_role>;
CREATE VIEW atlas_ro.remote_url_host AS    -- host only; never api_key / api_secret / full url
  SELECT id, server, is_active, split_part(split_part(url,'://',2),'/',1) url_host FROM core_remoteurlconfig;
GRANT SELECT (id, created_on, modified_on, command, start_date, end_date, status, input_type, created_by_id)
  ON core_commandexecuter TO <emapi_login_role>;   -- created_by_id: opaque user id, counted only (distinct operators)

-- back-office audit
GRANT SELECT (id, action_time, action_flag, content_type_id, object_id) ON django_admin_log TO <emapi_login_role>;
  -- object_id is the edited row's PK (text) → joins admin edits to order_order.id etc.; object_repr stays excluded
CREATE VIEW atlas_ro.admin_change_keys AS  -- Django stores change_message as JSON: [{"changed":{"fields":[...]}}]
  SELECT l.id, l.content_type_id, l.action_flag, e.key action_kind,
         CASE WHEN jsonb_typeof(e.value->'fields')='array' THEN ARRAY(SELECT jsonb_array_elements_text(e.value->'fields')) END field_names
  FROM django_admin_log l
  CROSS JOIN LATERAL jsonb_array_elements(CASE WHEN l.change_message LIKE '[%' THEN l.change_message::jsonb ELSE '[]' END) el
  CROSS JOIN LATERAL jsonb_each(CASE WHEN jsonb_typeof(el)='object' THEN el ELSE '{}' END) e;   -- field names only, no values/names

-- sessions and 2FA (no secrets)
GRANT SELECT (expire_date) ON django_session TO <emapi_login_role>;  -- never session_key / session_data
CREATE VIEW atlas_ro.totp_device_health AS   -- no key, no name, no user_id
  SELECT id, confirmed, drift, throttling_failure_count,
         CASE WHEN last_t = 0 THEN 'never' ELSE width_bucket(extract(epoch FROM now())/step - last_t, 0, 86400*90/30, 6)::text END last_use_bucket
  FROM otp_totp_totpdevice;

GRANT USAGE ON SCHEMA atlas_ro TO <emapi_login_role>;
GRANT SELECT ON ALL TABLES IN SCHEMA atlas_ro TO <emapi_login_role>;
-- Secondary aid only: GRANT pg_read_all_stats TO <emapi_login_role>;  (reveals pg_stat_statements text; see note below)
-- NEVER: youpayclient_clientconfiguration (api_key/api_secret/encryption_key), core_remoteurlconfig.api_key/api_secret/url,
--        otp_totp_totpdevice.key, otp_static_*.token, two_factor_*, django_session.session_key/session_data, auth_*,
--        webhooks_webhookconfig.webhook_key/sender_ip, webhooks_merchantwebhookmessage.ip_address/message/error_message,
--        django_admin_log.object_repr/change_message (raw), any raw free-text error column listed above
-- Counterparts: ygag_youpay_db (payments_youpaytransactiondata, services_paymentrequestdata, gateway tables)
--               ygag_ecom_gifts_db (orders_order, gifts_gift, gifts_gift_meta_data): same allowlist + err_class view pattern.
```

Notes on the views (STRUCTURAL; none has been created or tested, since we have no DDL rights):
- `IS JSON ARRAY` needs PostgreSQL 16. On an older engine, the owner should add a `safe_jsonb(text)` function that returns NULL on parse errors.
- `totp_device_health.last_use_bucket` converts `last_t` (a TOTP time-step counter) into steps since last use. A step is usually 30 s, so each of the 6 buckets is about 15 days, and the top bucket is "over 90 days". Exact bucket edges should be set by the owner.
- `webhook_message.from_configured_sender` assumes a single active config row (reltuples 1). If more than one exists, the view compares with the lowest-id active row.

**Finding the consumer behind the youpay large scans.** `pg_read_all_stats` alone is unlikely to find it (STRUCTURAL). None of the orders DB's tracked statements fits the youpay seq-scan pattern of about 1.14M rows per scan. The largest per call was 1,925 rows in the first snapshot and 33.2 in the re-query (Q18/Q27), and the set turns over within a day. With dealloc at 664,237 and rising, those statements have probably been evicted by the stores DB's 4,683 statements. Better tools, in order:
1. RDS Performance Insights on the replica instance (top SQL by DB and by wait; no grant needed from us).
2. Periodic `pg_stat_activity` sampling on the replica by an admin role (`datname`, `usename`, `application_name`, `client_addr` bucket, `query` prefix).
3. `log_min_duration_statement` (for example 5s) on the replica's parameter group, for a bounded window.

## Access pattern on the replica (catalog stats, measured; all STRUCTURAL)

**Counter window.** `pg_stat_database.stats_reset` is NULL, but the window is known: `pg_postmaster_start_time()` and `pg_stat_bgwriter.stats_reset` are 2 seconds apart and both were **35.53 days** before the re-query (Q26). This matches the 35.49 days the round-3 critic measured a few hours earlier. So `pg_stat_user_tables`/`pg_stat_user_indexes` counters cover about 35.5 days since the replica instance last restarted. They are not lifetime figures. (The pgss window is different: 95.5 days, Q26.) Per-day rates below divide by 35.53 (Q19b, re-query; counters moved by one seq scan since the first pass):

| Table | seq_scan | seq scans/day | seq_tup_read | rows / seq scan | seq rows/day | idx_scan | idx scans/day | idx_tup_fetch | rows / idx scan | idx rows/day | reltuples |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **youpayclient_youpayclienttransactiondata** | 910 | **25.6** | 1,041,912,866 | **1,144,959** | 29.3M | 129,122 | **3,634** | 21,904,581 | **169.6** | **616,500** | 1,229,851 |
| order_order (context, other unit) | 2,179 | 61.3 | 2,614,412,342 | 1,199,822 | 73.6M | 454,327 | 12,787 | 24,609,584 | 54.2 | 692,631 | 1,232,173 |
| order_orderstatuschange (context) | 835 | 23.5 | 989,407,358 | 1,184,919 | 27.8M | 1,670 | 47 | 835 | 0.5 | 24 | 1,157,239 |
| order_line / order_orderlinequantitydetail / users_customuser / users_userprofile / payment_paymentdetail (context) | 36 each | **1.0** | 27M–52M each | 0.75M–1.45M | 0.76M–1.47M | — | — | — | — | — | 0.76M–1.47M |

What this shows (all STRUCTURAL):
- **youpay seq scans are consistent with mostly full-table reads.** The average of 1,144,959 rows per scan is 93% of reltuples (1,229,851). The average could hide a mix: many full scans plus some partial scans that stop early at a `LIMIT`, or a table that grew during the window. So "every scan reads the whole table" is not proven; "mostly full-table reads" is what the evidence supports. The per-scan average is also a rough live-row proxy that does not depend on the stale `reltuples`. It is not a strict lower bound, because partial scans would pull it down.
- **About 25.6 youpay full-table-size reads per day** (about 29.3M tuples/day). That is roughly one per hour, which fits an hourly job or a frequently re-run report rather than the once-a-day extract below.
- **All youpay index traffic goes to the PK.** `youpayclienttransactiondata_pkey` has idx_scan 129,122. All 7 other indexes have **idx_scan = 0**: both `card_issuer_country` indexes, both `qitaf_request_id` indexes and the three boolean flag indexes (Q20, unchanged on re-query). The flag and country indexes serve no reader on this replica; they may be used on the primary.
- **The PK traffic is not incremental polling.** It averages 3,634 scans/day at about 170 rows per scan, which is **about 616,500 rows/day, or about 50% of the table's estimated rows every day**. An incremental extractor or CDC poller would fetch only new rows, a small share of that. The volume fits one of these:
  1. a repeated full read of the table done page by page by PK (`WHERE id > :last ORDER BY id LIMIT ~170`) about every two days; this is one hypothesis only;
  2. bulk keyed lookups (`WHERE id IN (...)` or `id = ANY(...)`) driven by another process, for example a join from order_order or a report;
  3. a mix of both.
  `idx_tup_read` (22,200,008) is close to `idx_tup_fetch` (21,904,581), so most index entries read lead to a visible heap row. That rules out neither option.
- **youpay seq reads are about 11.8% of the whole DB's `tup_returned`**: 1,041,912,866 of 8,795,539,868 (Q21/Q28). One integration table in scope is a leading read load on this replica.
- **The "36 seq scans" tables fit a once-a-day full reader.** Several business tables have exactly 36 seq scans of about 1M rows each. 36 matches the 35.53-day window rounded up, so this is one scan per table per day. Supporting evidence from `pg_stat_database` (Q28): **20 databases on this cluster have exactly 36 `xact_commit`** (and postgres has 38, ygag_checkout_db 39) (for example ygag_atwork_aps_v2_db, ygag_hub_db, ygag_rewards_db, ygag_giftshop_db). They carry 1,104–1,878 `tup_returned` each, which is catalog-only work. So something connects to every database once a day. In the orders DB, the same daily job or a related one also reads these five business tables in full. That fits a daily dump or snapshot export; which tool does it is unverified. youpay (25.6/day) and order_order (61.3/day) are scanned far more often, so there is a second, more frequent reader.
- **No kafka_*, webhooks_* or django_* table appears** among the tables with any scan on this replica (Q19b). Their readers, if any, use the primary.

## Summary

All of this summary is STRUCTURAL (catalog names, types, sizes and `reltuples` estimates of unknown age).

This group of tables is the **integration and system layer** of the ecommerce orders service, a Django/Oscar app. It has four parts.

- **Kafka event consumers/producers logs (9 tables, about 5.1M rows estimated).** Gift creation (`kafka_giftcreationlog`, about 3.13M) is the core entity. It is keyed by `event_id uuid` and `order_id varchar`, with `status`, `error` and `failure` columns. The other logs cover @Work (corporate) sync (about 1.70M), Plus-offer sync (about 202K, 1.5GB of TOAST jsonb), product-offer sync, sold-date updates, blacklisted-user sync, blacklisted-user gift log and legacy fraud sync.
- **YouPay client transactions (`youpayclient_youpayclienttransactiondata`, about 1.23M, 2.1GB).** This is the payment-gateway handoff record: amounts, VAT/fees, gateway, payment_status, approved, is_fraud/is_flagged, card BIN/scheme/issuer country, loyalty points (Qitaf and others) and redemption. It is the main source for purchase-friction and payment-failure metrics. **Hypothesis only:** its reltuples (1,229,851) is close to `order_order` (1,232,173), but that is not evidence of 1:1. `order_reference` is nullable. Retries could add rows while abandoned orders have none, and the two could cancel out. Test this once granted with P6 (count(DISTINCT order_reference) vs count(*) on a sample).
- **Merchant webhooks (`webhooks_merchantwebhookmessage`, about 5.2K).** Inbound webhook payloads with `error_message jsonb`.
- **Django/admin/2FA/config.** Sessions (about 285K), admin audit log (about 2.6K), OTP/TOTP devices (28 TOTP) and reference data: currencies (23), FX rates (437), basket limits, languages (2), remote URL config and site config.

There are no timestamp indexes on any kafka, youpay or webhook table (exact, Q4b). youpay has 8 indexes (Q4b):
- the PK;
- 3 boolean flag indexes: `is_full_redemption`, `is_qitaf_enabled` and `point_collection_enabled`;
- 2 btree indexes on `card_issuer_country` (plain and `varchar_pattern_ops` `_like`);
- 2 btree indexes on `qitaf_request_id` (plain and `_like`).

On this replica **only the PK index has ever been scanned**. The other 7 have idx_scan = 0 (Q20). Whether the planner would use the flag and country indexes for our queries is an assumption and has not been observed.

`kafka_giftcreationlog` has only the PK and `event_id` UNIQUE. **There is no index on `order_id`.** Once access is granted, time-windowed queries must use `id` ranges (PK index) or TABLESAMPLE.

## Entities & Tables

All rows are STRUCTURAL. Volumes are `pg_class.reltuples` (estimate). Bytes = `pg_total_relation_size` (exact at query time).

| Table | Est. rows | Total bytes | Purpose | Key columns / timestamps |
|---|---|---|---|---|
| kafka_giftcreationlog | 3,134,464 | 3.12 GB (TOAST 131 MB) | Log of gift-creation events per order (Kafka → gift service) | event_id uuid UNIQUE, order_id varchar(255) NOT NULL, status varchar(200), error varchar(255), failure text, created_gift_details text, payload text; created_on/modified_on |
| kafka_atworkkafkadatalog | 1,700,549 | 554 MB | @Work (corporate/B2B) Kafka data sync log | data jsonb, status varchar(20), error_data text, start_timestamp, completed_timestamp (nullable) |
| kafka_plusofferkafkadatalog | 201,682 | 1.55 GB (TOAST 1.53 GB) | Plus-offer (loyalty/cashback offer) Kafka sync log; very large jsonb payloads | same shape as atwork |
| kafka_solddateupdatekafkadatalog | 34,582 | 10 MB | Gift "sold date" update events | same shape as atwork |
| kafka_legacyfraudsynclog | 16,691 | 4 MB | Fraud flags synced from legacy platform | event_id uuid UNIQUE, payload, status, error; created_on |
| kafka_blacklistusergiftlog | 7,354 | 2 MB | Gift actions for blacklisted users | event_id uuid UNIQUE, payload, status, error; created_on |
| kafka_blacklistuserkafkadatalog | 2,317 | 1.3 MB | Blacklisted-user sync events | same shape as atwork |
| kafka_productofferkafkadatalog | 767 | 2.8 MB | Product-offer (promotion) sync events | same shape as atwork |
| kafka_plusofferconfigdatalog | 0 | 16 KB | Plus-offer config sync; **empty / dead** | same shape as atwork |
| youpayclient_youpayclienttransactiondata | 1,229,851 | 2.08 GB (TOAST 73 MB) | Payment session / transaction handed to YouPay gateway | transaction_id, payment_reference, order_reference, invoice_id, session_id, amount/base/vat/service_fee/processing_fee/paid/gateway_charge, currency, cart_* mirror, payment_gateway, payment_status, payment_method, payment_scheme, channel_code, platform, approved, is_fraud, is_flagged, is_gcc_card, card_bin, card_last4, card_issuer_country, response_summary, points (available/redeemed/earned, point_program, loyalty_level, qitaf_*), is_full_redemption, order_items/order_history/brand_details/brand_calculations/udf1 jsonb; created_on/modified_on |
| youpayclient_clientconfiguration | 2 | 88 KB | YouPay API client credentials (**secrets**) | client_name, api_key UNIQUE, api_secret, encryption_key |
| webhooks_merchantwebhookmessage | 5,241 | 19.5 MB | Inbound merchant webhook payloads | ip_address inet, message jsonb, error_message jsonb, received_at |
| webhooks_webhookconfig | 1 | 128 KB | Webhook sender config | name, webhook_key UNIQUE, sender_ip, is_active |
| django_session | 284,567 | 152 MB | Server-side sessions (admin/storefront) | session_key PK, session_data, expire_date (indexed) |
| django_admin_log | 2,608 | 552 KB | Back-office admin change audit | action_time, action_flag (1 add/2 change/3 delete in Django), content_type_id, object_id, user_id |
| django_content_type / auth_permission / auth_group(_permissions) | 150 / 550 / 6 / n.a. | small | Django RBAC | — |
| django_site / django_flatpage(_sites) / django_migrations | 1 / 0 / 0 / n.a. | small | Site registry; flatpages **empty** | — |
| otp_totp_totpdevice | 28 | 72 KB | Admin TOTP 2FA devices | confirmed, key (**secret**), drift, last_t, throttling_failure_count/timestamp, user_id |
| otp_static_staticdevice / otp_static_statictoken | 1 / 10 | small | Backup codes | token (**secret**) |
| two_factor_phonedevice | 0 | 16 KB | SMS/call 2FA; **empty** | number (PII), method |
| core_currency / core_basecurrency / core_currencyexchangerate / core_currencybasketlimit | 23 / 19 / 437 / 8 | small | Currency reference, FX buy/sell rates, max basket per currency | code UNIQUE, buy_rate, sell_rate, limit_amount |
| core_language / core_siteconfig / core_unsupportedcountry / core_remoteurlconfig / core_commandexecuter | 2 / 1 / n.a. / 9 / n.a. | small | Config: languages, guest checkout flag (`is_guest_enabled`), blocked countries, remote service URLs (+api_key/api_secret **secrets**), admin-triggered management commands (status, input_type) | — |
| jet_bookmark / jet_pinnedapplication | 0 / 0 | 16 KB | Django-Jet admin UI; **empty** | — |

`n.a.` = reltuples is -1 (never analyzed); the size is small.

**Business entity grouping**
- *Gift fulfilment pipeline*: kafka_giftcreationlog, kafka_solddateupdatekafkadatalog
- *Payments / checkout*: youpayclient_youpayclienttransactiondata, youpayclient_clientconfiguration, core_currencybasketlimit, core_currencyexchangerate
- *Offers / loyalty sync*: kafka_plusofferkafkadatalog, kafka_plusofferconfigdatalog, kafka_productofferkafkadatalog
- *Corporate (@Work) sync*: kafka_atworkkafkadatalog
- *Risk / fraud*: kafka_legacyfraudsynclog, kafka_blacklistuserkafkadatalog, kafka_blacklistusergiftlog, youpay is_fraud/is_flagged
- *Merchant integrations*: webhooks_*
- *Back-office security & audit*: django_admin_log, django_session, otp_*, two_factor_*, auth_*
- *Reference config*: core_*, django_site, django_content_type

## Relations

Declared FKs (Q3, exact catalog facts; STRUCTURAL as business relations):
- All `core_*`, `webhooks_webhookconfig`: created_by_id / modified_by_id → users_customuser(id)
- core_basecurrency.currency_id, core_currencybasketlimit.currency_id, core_currencyexchangerate.foreign_currency_id → core_currency(id); core_currencyexchangerate.base_currency_id → core_basecurrency(id)
- django_admin_log.user_id → users_customuser; .content_type_id → django_content_type
- otp_totp_totpdevice / otp_static_staticdevice / two_factor_phonedevice / jet_* .user_id → users_customuser; otp_static_statictoken.device_id → otp_static_staticdevice
- auth_permission.content_type_id → django_content_type; auth_group_permissions → auth_group, auth_permission

Inbound FKs from business tables (Q9, exact): core_currency ← catalogue_product, catalogue_productdenomination(+range), catalogue_producthandlingfee, catalogue_store, basket_basketquantitydetail, order_orderlinequantitydetail, offer_productoffer (budget/fixed_amount/min_max currency), address_country, user_tip_*; core_language ← basket_basket, order_order, users_userprofile, notifications_emailtemplateconfiguration; django_site ← order_order; django_content_type ← catalogue_productattributevalue, user_tip_invoice.

**No declared FKs** on kafka_* or youpayclient_youpayclienttransactiondata. Logical keys (STRUCTURAL: inferred from names and types; match rates are NEEDS-GRANT via P11/P11b):
- kafka_giftcreationlog.order_id varchar(255) → order_order.number varchar(128) or order_order.id bigint (the varchar type suggests `number`). **Join warning:** `order_id` has no index, so any per-order lookup or join is a full scan of a 3.12 GB table. Always bound the kafka side first, by `id` range or `TABLESAMPLE SYSTEM(1)`, then join to order_order, which is indexed on id/number.
- webhooks_merchantwebhookmessage has **no FK and no config id column** pointing to webhooks_webhookconfig, and there is exactly 1 config row (reltuples 1). The likely topology is a single merchant sender, with authentication by webhook_key/sender_ip at ingest time. Messages cannot be attributed to a sender in the DB, and `received_at`, the only timestamp, has no index.
- youpayclient_youpayclienttransactiondata.order_reference varchar(200) → order_order.order_reference varchar(128); payment_reference → order_order.payment_order_reference varchar(21); transaction_id varchar(100) → order_order.transaction_id varchar(256).
  **Index asymmetry (Q22, exact):** order_order has UNIQUE indexes on `number` (`order_order_number_key`) and `order_reference` (`order_order_order_reference_key`), and a plain btree on `transaction_id`. There is **no index on `payment_order_reference`**. The youpay side has no index on any of these reference columns. So a reconciliation join must be **bounded on the youpay side** (PK id range), then probe `order_order.order_reference` (UNIQUE) or `order_order.transaction_id`. Never drive it by `payment_order_reference`.
- kafka_*.event_id uuid → Kafka message id (idempotency key; UNIQUE on 3 tables)
- *_kafkadatalog.data jsonb → contains entity ids (offer/brand/user/company); structure unknown without read access

## Lifecycle States

**BLOCKED — needs grant:** the status/flag columns listed below (column-level grants and `atlas_ro` views in the Grant request). Candidate state columns (STRUCTURAL) to profile once access exists:
- kafka_giftcreationlog.status varchar(200) + error + failure (gift creation success/failed/retry)
- kafka_*datalog.status varchar(20) + error_data + completed_timestamp NULL (= in-flight or stuck)
- kafka_legacyfraudsynclog / kafka_blacklistusergiftlog .status
- youpayclient_youpayclienttransactiondata.payment_status, approved, is_fraud, is_flagged, is_full_redemption, payment_gateway, payment_method, payment_scheme, channel_code, platform, response_summary
- core_commandexecuter.status varchar(15) NOT NULL, input_type varchar(15) NOT NULL, command varchar(256), start_date/end_date date, argument1 varchar(100). This is an **ops/backfill audit trail**: admin-triggered management-command reruns over date ranges. It shows when and how often the pipeline needed manual repair.
- django_admin_log.action_flag (Django: 1=add, 2=change, 3=delete)
- two_factor_phonedevice.method (sms/call), otp devices.confirmed

## Time Coverage & Trends

**BLOCKED — needs grant:** `kafka_giftcreationlog.created_on/modified_on`, `kafka_*datalog.start_timestamp/completed_timestamp`, `youpayclient_youpayclienttransactiondata.created_on/modified_on`, `webhooks_merchantwebhookmessage.received_at`, `django_admin_log.action_time`, `django_session.expire_date` (plus `id` on each for PK-range bucketing). Timestamp columns: created_on/modified_on (gift/fraud/blacklist-gift logs, youpay, core_*), start_timestamp/completed_timestamp (*datalog), received_at (webhooks), action_time (admin log), expire_date (sessions, indexed). None of the large tables has a timestamp index. Monthly trends will need `id`-range bucketing (PK) or `TABLESAMPLE SYSTEM (1)`.

**reltuples staleness caveat:** for all 159 public tables, `last_analyze`, `last_autoanalyze`, `last_vacuum` and `last_autovacuum` are NULL, and `n_mod_since_analyze` is 0 (Q14). So the age of every reltuples estimate in this profile is unknown. The estimates could be days or months old, and could differ from the real counts by an unknown amount. Read them as order-of-magnitude figures only. (The equivalent tables in ygag_ecom_gifts_db have reltuples -1 and have never been analyzed.)

`pg_stat_user_tables` on the replica shows no vacuum/analyze timestamps and zero n_tup_ins, because write-side stats are not kept on a replica. `youpayclient_youpayclienttransactiondata` is the only in-scope table with read activity on this replica: seq_scan 910, idx_scan 129,122 over a 35.53-day window (Q19b, Q26). The scan-ratio analysis is in **Access pattern on the replica** above. In short (STRUCTURAL): about 25.6 seq scans/day consistent with mostly full-table reads of about 1.14M rows each, plus about 3,634 PK index scans/day of about 170 rows each (about 616K rows/day, about half the table). Performance Insights or `pg_stat_activity` sampling on the replica would identify the reader; `pg_stat_statements` probably no longer holds it (dealloc 664,237 and rising, statement set turning over within a day).

**Row-count proxy with no grant (STRUCTURAL):** 1,144,959 average rows per youpay seq scan against reltuples 1,229,851. It is a rough proxy, not a bound: growth during the window pulls it below the current count, and any partial (LIMIT-terminated) scans pull it lower still. Exact count is NEEDS-GRANT (`youpayclient_youpayclienttransactiondata.id`).

## Behavior Signals (captured, not quantified)

**BLOCKED — needs grant.** Every signal below is STRUCTURAL (the column exists and has this type) and every rate or distribution is NEEDS-GRANT. The columns each one needs are in the Grant request and the matching P-query.

- **Gift creation per order**: kafka_giftcreationlog has about 3.13M rows against about 1.23M order_order rows (both estimates of unknown age). The raw ratio of about 2.5 **cannot be interpreted yet**, for three reasons:
  1. `event_id` is UNIQUE, so a retry (if retries happen) is a new row, not an update.
  2. The ratio depends on the status mix: success versus failed rows.
  3. It depends on what `order_id` holds: number, id or an external reference.

  Resolve with P1 and P2.
- **Payment attempts / checkout sessions**: youpay rows (about 1.23M) with method/scheme/gateway/platform/`language` varchar(15)/channel_code. Also card issuer country (btree-indexed, but the index is unused on the replica) and is_gcc_card.
- **Payment economics** (youpay, numeric(12,4)): `gateway_charge`, `processing_fee`, `settlement_entity` varchar(100) and `paid_amount`. Together they give cost-of-payment and margin per gateway or settlement entity (P7).
- **Loyalty behavior**: `loyalty_level` int, `point_program` varchar(200), and the flags `is_qitaf_enabled` and `point_collection_enabled` (btree-indexed, but idx_scan 0 on the replica, Q20; P8 counts them one flag per statement). Point economics columns (Q23, exact types): `available_points` numeric(20,4), `redeemed_points` numeric(12,4), `earned_point` numeric(12,4); money-side `available_amount`, `payable_amount`, `redeemed_amount` numeric(12,4). Together with `is_full_redemption` they give:
  - earned vs redeemed points per program and loyalty level (point liability build-up vs burn; P8b);
  - redemption depth `redeemed_points / available_points` (how much of the balance a customer uses);
  - partial vs full redemption. A partial redemption leaves a gap that must be paid by card, which is friction.
- **Basket shape and repeat-buyer depth (jsonb structure, PII-safe; P12)**: `jsonb_array_length(order_items)` gives basket size and the multi-item share. `jsonb_array_length(order_history)` (or its key count if it is an object) gives repeat-buyer depth. The key sets of `brand_details` / `brand_calculations` show multi-brand carts. The key set of `udf1` tests whether it carries campaign/UTM fields. Only lengths, key names and counts are read, never values.
- **Repeat-buyer / attribution carriers (jsonb)**: `order_history` may carry prior-purchase context, a repeat-buyer signal. `udf1` is a possible campaign/UTM carrier. The redirect URLs (`success_url`, `failure_url`, `cancel_url`, `verify_url`, all varchar(500) NOT NULL) likely encode the storefront or channel. Expose these only through derived views, such as a host or path-prefix bucket or a list of jsonb keys, never as raw values (see PII).
- **Gifts per creation event**: `kafka_giftcreationlog.created_gift_details` (text) likely lists the gifts made by each event. A derived count per row (JSON array length if it parses, no values) would settle the "about 2.5 events per order" question better than status alone (P15).
- **Merchant webhook event types and error classes**: key names of `webhooks_merchantwebhookmessage.message` / `error_message` (jsonb), counted (P12).
- **Ops interventions**: core_commandexecuter (admin reruns and backfills by command and date range).
- **Offer/campaign propagation**: plus-offer and product-offer sync logs.
- **Corporate (@Work) activity**: atwork sync log, about 1.70M.
- **Sessions**: django_session, about 285K rows (expire-based). The expired share is cheap to measure through the `expire_date` btree (P14) and tests the "clearsessions not running" hypothesis.
- **Back-office actions**: django_admin_log, about 2.6K; admin 2FA devices, 28 TOTP. Grouping by `content_type_id` → `django_content_type.model` × `action_flag` (P10) shows **which** entities are manually added, changed or deleted in the back office (order or voucher repairs, offer edits). `content_type_id` has a btree index (Q24).
- Not in this unit: views, baskets, referrals, notifications (other units/tables).

## Friction & Errors (candidates, rates not measurable)

**BLOCKED — needs grant.** Candidates are STRUCTURAL. Rates are NEEDS-GRANT, and error reasons are available only as normalized `error_class` / `response_class` from the `atlas_ro` views, never as raw free text.

- Gift creation failures: kafka_giftcreationlog.status / error / failure
- Kafka sync failures and stuck events: *datalog.status, error_data, completed_timestamp IS NULL
- Payment friction: youpay approved=false, payment_status non-success, response_summary (gateway decline reason), is_fraud / is_flagged
- Blacklist and fraud blocks: kafka_blacklistusergiftlog, kafka_legacyfraudsynclog, kafka_blacklistuserkafkadatalog
- Webhook errors: webhooks_merchantwebhookmessage.error_message IS NOT NULL (via `atlas_ro.webhook_message.has_error`)
- Webhook sender drift: share of messages not from the configured `sender_ip` (`from_configured_sender`, P16f)
- FX staleness and spread: `core_currencyexchangerate` rate age and sell/buy spread per pair (P16c); presentment vs cart currency mismatch × approval (P16d)
- Time-of-week decline pattern: youpay hour-of-week × approval (P16e)
- 2FA friction and dormancy: otp_*.throttling_failure_count, TOTP last-use recency buckets (P16a)
- Guest checkout / country block config: core_siteconfig.is_guest_enabled, core_unsupportedcountry
- Manual repair frequency: core_commandexecuter rows per command and status (failed reruns), distinct operators and date-window length (P16g); django_admin_log changes by model and by changed field name (P10, P16b), and admin edits joined to orders via `object_id` (P10)
- **Near-limit basket friction** (P13a): youpay `amount` / `cart_amount` against `core_currencybasketlimit.limit_amount` numeric(15,6) (UNIQUE per `currency_id`, `is_active`), by currency: the share of sessions within 10% of the cap, and approval rate near the cap vs elsewhere.
- **Cross-border and blocked-country declines** (P13b): approval rate by `card_issuer_country`, flagged where the country is in `core_unsupportedcountry` (country_code varchar(2) UNIQUE, is_active); and `card_issuer_country` ≠ the currency's home country.
- **GCC card × gateway** (P13c): approval rate by `is_gcc_card` × `payment_gateway`, to show where non-GCC cards fail.

### Latency / SLA signals (measurable once granted)

| Metric | Formula | Meaning | Query |
|---|---|---|---|
| Kafka consumer processing latency | `completed_timestamp - start_timestamp` (per *datalog) | Time from consumer start to completion; p50/p95 per table and status | P3 |
| Stuck / in-flight events | `completed_timestamp IS NULL AND start_timestamp < now() - interval '1 hour'` | Consumer stalls | P3 |
| Gift-creation latency / retry span | kafka_giftcreationlog `modified_on - created_on` | Time from event log to the final status update; a long span means retries | P2 |
| Checkout / payment-session duration | youpay `modified_on - created_on` by payment_status and gateway | Purchase-friction signal: slow sessions or abandoned sessions (never updated) | P5 |
| Webhook error rate | share with `error_message IS NOT NULL` by month (id buckets) | Merchant integration health | P9 |

## Cross-DB Keys (types only; ranges not measurable; STRUCTURAL)

| Column | Type | Likely shared with |
|---|---|---|
| kafka_giftcreationlog.order_id | varchar(255) | order number used by gift service / legacy YGG DBs |
| kafka_*.event_id | uuid | Kafka producer services (message id) |
| youpay.transaction_id / payment_reference / order_reference / invoice_id / session_id | varchar | YouPay gateway DB, finance/settlement |
| youpay.qitaf_request_id | varchar(100), indexed | STC Qitaf loyalty |
| youpay.settlement_entity, payment_gateway | varchar | finance |
| youpay.brand_details / brand_calculations / order_items (jsonb) | jsonb | brand ids/codes (catalogue, brand service) |
| *datalog.data (jsonb) | jsonb | @Work company/user ids, offer ids |
| users_customuser.id (via created_by_id, user_id FKs) | bigint | orders-db user id; cognito/central identity mapping lives elsewhere |
| core_currency.code | varchar(3) | ISO currency across all DBs |
| core_unsupportedcountry.country_code, youpay.card_issuer_country | varchar(2)/(4) | ISO country |

**Counterpart databases** (catalog only; 0 grants in both, Q13):

| This DB | Counterpart | Candidate key (types, Q15/Q16) | Notes |
|---|---|---|---|
| youpay.order_reference varchar(200) / payment_reference / invoice_id / transaction_id / qitaf_request_id | **ygag_youpay_db**: payments_youpaytransactiondata (about 2.08M est, 7.2 GB), payments_archivedyoupaytransactiondata, services_paymentrequestdata (about 2.16M, 5.2 GB), integrations_youpaytopaymentgatewaysdata (about 4.45M), payments_clientnotification (about 6.64M), plus per-gateway tables (checkoutpgclient, adcbpgclient, tabbypgclient, networkpg, paypal, tpay, amazonpg, happycredits) | payments_youpaytransactiondata.order_reference / payment_reference / invoice_id varchar(120), transaction_id uuid, qitaf_request_id varchar(100) | Gateway-side truth for payment status and the per-gateway response. The YouPay DB holds about 1.7 times more transaction rows than the orders-side client table (estimates), which is consistent with YouPay serving other clients too. |
| kafka_giftcreationlog.order_id varchar(255) | **ygag_ecom_gifts_db**: orders_order (500 MB), gifts_gift (12.6 GB), gifts_gift_meta_data (1.9 GB), ecom_reports_giftderivate (1.6 GB) | orders_order.order_id varchar(50), gifts_gift_meta_data.order_id varchar(50), gifts_gift_ordered_gifts.order_id varchar(22) | Consumer side of gift creation. Its reltuples are -1 (never analyzed), so it has no row estimates. |

## PII (column names only)

- youpayclient_youpayclienttransactiondata: customer_email, customer_name, name_on_card, customer_ip_address, card_bin, card_last4, points_collected_mobile_number, points_redeemed_mobile_number, session_id, order_history/order_items/udf1/brand_details/brand_calculations (jsonb, may embed PII); **success_url, failure_url, cancel_url, verify_url** (varchar(500) NOT NULL). These URLs are likely to carry tokens, signatures or session references in the query string, so treat them as secret-bearing. Expose only a derived host or path bucket.
- webhooks_merchantwebhookmessage: ip_address, message (jsonb)
- webhooks_webhookconfig: sender_ip, webhook_key (secret)
- two_factor_phonedevice: number, key (secret)
- otp_totp_totpdevice.key, otp_static_statictoken.token (secrets)
- youpayclient_clientconfiguration: api_key, api_secret, encryption_key (**secrets, exclude from any grant**)
- core_remoteurlconfig: api_key, api_secret (**secrets, exclude**)
- django_session.session_data (serialized session; may contain user ids and tokens)
- kafka_*: payload text, data jsonb, created_gift_details text (likely recipient names/emails/phones, gift codes)
- django_admin_log.object_repr / change_message (may contain names/emails)

## Data Quality

All items are STRUCTURAL unless marked NEEDS-GRANT.

- Empty or dead tables (reltuples 0): kafka_plusofferconfigdatalog, django_flatpage, django_flatpage_sites, jet_bookmark, jet_pinnedapplication, two_factor_phonedevice.
- Never analyzed (reltuples -1): auth_group_permissions, core_commandexecuter, core_unsupportedcountry, django_migrations.
- Two log shapes for the same concept, "Kafka event log": the (event_id, payload, status(200), error(255), created_on) family versus the (data jsonb, status(20), error_data, start/completed_timestamp) family. Metrics need to normalize them.
- kafka_plusofferkafkadatalog stores about 1.53GB of TOAST for about 202K rows, roughly 7.5KB per row of jsonb. Payloads are heavy, so avoid `data` in scans.
- Money fields are duplicated in youpay (amount vs cart_amount, vat_amount vs cart_VAT_amount, service_fee vs cart_service_fee, currency vs cart_currency). The canonical field has to be decided.
- No FK integrity on order_id / order_reference, so orphans are possible. NEEDS-GRANT: `kafka_giftcreationlog.order_id`, `youpayclient_youpayclienttransactiondata.order_reference/transaction_id` (P11, P11b).
- `error_data text NOT NULL` on datalogs means an empty string probably stands for "no error".
- reltuples ages are unknown: the replica shows no analyze/vacuum timestamps for any table (Q14).
- The youpay index set suggests the app looks up rows by qitaf_request_id and card_issuer_country, but not by order_reference or payment_reference. Those columns have no index, so reconciliation joins on them must be bounded. On the replica none of the non-PK youpay indexes has been used (idx_scan 0, Q20).
- **Dropped column in youpay (Q23, exact):** attnum 62 is `........pg.dropped.62........`, between `points_collected_mobile_number` (61) and `points_redeemed_mobile_number` (63). This is the only dropped column across all 38 in-scope tables (Q25). It is schema-history evidence of a loyalty-related column that was added and then removed; plausibly an earlier mobile-number or points field that was renamed or replaced (hypothesis). Historical rows may have carried data in a field that no longer exists, so older loyalty metrics may not be comparable with newer ones.
- webhooks_merchantwebhookmessage cannot be attributed to a sender: there is no FK to webhookconfig.
- django_session holds about 285K rows, which suggests expired sessions are not being cleared (clearsessions). NEEDS-GRANT: `django_session.expire_date` (P14, cheap via its index).

## Open Questions

1. Can SELECT be granted to `<emapi_login_role>`, table- and column-level, on the non-secret integration tables? Every distribution, trend and rate in this unit is blocked on that.
2. Does kafka_giftcreationlog.order_id hold order_order.number, order_order.id or an external order ref?
3. What are the payment_status values and the approved semantics in youpay (attempt vs final)? Is there one row per attempt or per order?
4. What is the status vocabulary of the kafka logs? Is there retry, and are retries new rows or updates?
5. Which service reads youpay on the replica (about 25.6 seq scans/day averaging about 1.14M rows, plus about 3,634 PK scans/day of about 170 rows, about 616K rows/day)? Is it the same reader that seq-scans order_order about 61 times/day? And which job does the once-a-day pass that touches every DB (36 xact_commit in 20 DBs)? Answer with Performance Insights or `pg_stat_activity` sampling, not `pg_stat_statements`.
6. Is kafka_plusofferconfigdatalog deprecated?
7. What does *datalog.data look like (which ids for @Work company/user, plus-offer)?
8. Do the youpay redirect URLs carry tokens or signatures? This decides whether a derived-host view is enough.
9. Is youpay (orders DB) a mirror of ygag_youpay_db.payments_youpaytransactiondata, or a separate client-side record? Which one is canonical for the payment status?
10. Can grants on ygag_youpay_db and ygag_ecom_gifts_db be requested in the same ticket?

## Appendix: SQL provenance

Q1 volumes (estimate reltuples, exact bytes):
```sql
SELECT c.relname, c.reltuples::bigint est, pg_total_relation_size(c.oid) bytes, s.n_live_tup, s.last_autoanalyze::date
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace LEFT JOIN pg_stat_user_tables s ON s.relid=c.oid
WHERE n.nspname='public' AND c.relkind='r' AND c.relname ~ '^(kafka_|youpayclient_|webhooks_|django_|core_|auth_|otp_|two_|jet_)' ORDER BY 1;
```
Q2 columns (information_schema.columns returned 0 rows due to privileges; pg_attribute used):
```sql
SELECT c.relname t, a.attname c, format_type(a.atttypid,a.atttypmod) ty, a.attnotnull nn
FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname='public' AND c.relkind='r' AND a.attnum>0 AND NOT a.attisdropped
AND c.relname ~ '^(kafka_|youpayclient_|webhooks_|core_|otp_|two_|django_admin)' ORDER BY c.relname, a.attnum;
```
Q3 constraints:
```sql
SELECT conrelid::regclass t, contype, pg_get_constraintdef(oid) def FROM pg_constraint
WHERE connamespace='public'::regnamespace AND contype IN ('p','f','u')
AND conrelid::regclass::text ~ '^(kafka_|youpayclient_|webhooks_|django_|core_|auth_|otp_|two_|jet_)' ORDER BY 1,2;
```
Q4 indexes:
```sql
SELECT tablename, indexdef FROM pg_indexes WHERE schemaname='public'
AND tablename ~ '^(kafka_|youpayclient_|webhooks_|django_session|django_admin)' ORDER BY 1;
```
Q5 first data query (failed: permission denied for table kafka_giftcreationlog):
```sql
SELECT (SELECT min(id) FROM kafka_giftcreationlog), ... ;
```
Q6 privileges (exact: 0 of 159 tables granted):
```sql
SELECT c.relname, has_table_privilege(c.oid,'SELECT') FROM pg_class c ... ;
SELECT count(*) FILTER (WHERE has_table_privilege(c.oid,'SELECT')) granted, count(*) total
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relkind='r';
```
Q7 activity stats / TOAST:
```sql
SELECT s.relname, s.seq_scan, s.idx_scan, s.n_tup_ins, s.n_dead_tup, s.last_autovacuum::date, c.relpages,
 pg_relation_size(c.oid) heap, pg_total_relation_size(c.reltoastrelid) toast
FROM pg_stat_user_tables s JOIN pg_class c ON c.oid=s.relid
WHERE s.relname ~ '^(kafka_|youpayclient_|webhooks_|django_session|django_admin)' ORDER BY 1;
```
Q8 sequences (last_value NULL, no privilege):
```sql
SELECT sequencename, last_value FROM pg_sequences WHERE schemaname='public' AND sequencename ~ '^(kafka_|youpayclient_|webhooks_|django_admin)';
```
Q9 inbound FKs:
```sql
SELECT conrelid::regclass src, confrelid::regclass tgt, pg_get_constraintdef(oid) FROM pg_constraint
WHERE contype='f' AND connamespace='public'::regnamespace
AND confrelid::regclass::text ~ '^(kafka_|youpayclient_|webhooks_|core_|django_content_type|django_site)'
AND conrelid::regclass::text !~ '^(kafka_|youpayclient_|webhooks_|core_|django_|auth_)';
```
Q10 cross-key types and order volume (estimate):
```sql
SELECT c.relname, a.attname, format_type(a.atttypid,a.atttypmod) FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
WHERE c.relname IN ('order_order','users_customuser') AND a.attname ~ '(^id$|number|reference|uuid|sub|cognito|user_id|external|legacy)';
SELECT reltuples::bigint FROM pg_class WHERE oid='order_order'::regclass;  -- 1,232,173
```

Q4b index list, corrected (exact: youpay has 8 indexes; giftcreationlog has only PK + event_id; no timestamp or order_id indexes):
```sql
SELECT tablename, indexname, indexdef FROM pg_indexes WHERE schemaname='public'
AND tablename IN ('youpayclient_youpayclienttransactiondata','kafka_giftcreationlog','webhooks_merchantwebhookmessage',
                  'kafka_atworkkafkadatalog','kafka_plusofferkafkadatalog') ORDER BY 1,2;
```
Q11 readable relations by kind (exact: r 159/0 readable; v 2/2 readable = pg_stat_statements, pg_stat_statements_info):
```sql
SELECT c.relkind, count(*) total, count(*) FILTER (WHERE has_table_privilege(c.oid,'SELECT')) readable,
 string_agg(c.relname, ',') FILTER (WHERE has_table_privilege(c.oid,'SELECT')) readable_names
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname='public' AND c.relkind IN ('r','v','m','p','f') GROUP BY 1;
```
Q12 pg_stat_statements visibility. **CLUSTER-WIDE, all databases**, superseded by Q17 for per-DB figures (exact at first query time: 4,980 stmts, 16 with visible text, 419,972,814 calls, dealloc 662,912; stats_reset got redacted by the output filter):
```sql
SELECT count(*) stmts, count(*) FILTER (WHERE query NOT LIKE '<insufficient%') visible_text, sum(calls)::bigint total_calls,
 (SELECT stats_reset::date FROM pg_stat_statements_info) reset, (SELECT dealloc FROM pg_stat_statements_info) dealloc
FROM pg_stat_statements;
```
Q13 counterpart DB grants (exact: ygag_youpay_db 54 tables / 0 readable / 0 views; ygag_ecom_gifts_db 110 / 0 / 0), run in each DB:
```sql
SELECT current_database(), count(*) FILTER (WHERE c.relkind='r') base_tables,
 count(*) FILTER (WHERE c.relkind='r' AND has_table_privilege(c.oid,'SELECT')) readable_tables,
 count(*) FILTER (WHERE c.relkind='v' AND has_table_privilege(c.oid,'SELECT')) readable_views
FROM pg_class c WHERE c.relnamespace='public'::regnamespace;
```
Q14 analyze staleness (exact: 159 tables, 0 with any analyze/vacuum timestamp, n_mod_since_analyze sum 0):
```sql
SELECT count(*) tables, count(last_analyze) la, count(last_autoanalyze) laa, count(last_vacuum) lv, count(last_autovacuum) lav,
 sum(n_mod_since_analyze) mods FROM pg_stat_user_tables WHERE schemaname='public';
```
Q15 youpay/webhook/commandexecuter columns (exact catalog):
```sql
SELECT c.relname t, a.attname c, format_type(a.atttypid,a.atttypmod) ty, a.attnotnull nn
FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
WHERE c.relnamespace='public'::regnamespace AND a.attnum>0 AND NOT a.attisdropped
AND (c.relname IN ('core_commandexecuter','webhooks_merchantwebhookmessage','webhooks_webhookconfig','kafka_giftcreationlog','kafka_atworkkafkadatalog')
 OR (c.relname='youpayclient_youpayclienttransactiondata' AND a.attname ~ '(url|gateway_charge|processing_fee|settlement|language|loyalty|point_collection|qitaf_enabled|amount|order_history|udf|order_reference|payment_status|approved|response)'))
ORDER BY 1, a.attnum;
```
Q16 counterpart key columns and sizes (types exact; reltuples estimates; bytes exact at query time):
```sql
-- ygag_youpay_db
SELECT relname, reltuples::bigint est FROM pg_class WHERE relnamespace='public'::regnamespace AND relkind='r' ORDER BY reltuples DESC LIMIT 12;
SELECT c.relname, a.attname, format_type(a.atttypid,a.atttypmod) FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
WHERE c.relnamespace='public'::regnamespace AND c.relkind='r' AND a.attnum>0 AND NOT a.attisdropped
AND a.attname ~ '(order_reference|payment_reference|transaction_id|invoice_id|qitaf_request_id)';
SELECT relname, pg_total_relation_size(oid) FROM pg_class WHERE relnamespace='public'::regnamespace
AND relname IN ('payments_youpaytransactiondata','payments_archivedyoupaytransactiondata','services_paymentrequestdata');
-- ygag_ecom_gifts_db
SELECT c.relname, c.reltuples::bigint, a.attname, format_type(a.atttypid,a.atttypmod) FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
WHERE c.relnamespace='public'::regnamespace AND c.relkind='r' AND a.attnum>0 AND NOT a.attisdropped
AND a.attname ~ '(^order_id$|order_number|order_reference|event_id)';
SELECT relname, reltuples::bigint, pg_total_relation_size(oid) FROM pg_class WHERE relnamespace='public'::regnamespace
AND relname IN ('orders_order','gifts_gift_meta_data','ecom_reports_giftderivate','gifts_gift','gifts_gifteventlog','orders_order_item');
```

Q17 pg_stat_statements split per database via `dbid` (exact at query time; orders DB 20 stmts / 1,858,925 calls / 3,459,861 rows; stores DB 4,683 / 384,638,644):
```sql
SELECT d.datname, count(*) stmts, sum(s.calls)::bigint calls, sum(s.rows)::bigint rows_,
       count(*) FILTER (WHERE s.query NOT LIKE '<insufficient%') visible
FROM pg_stat_statements s LEFT JOIN pg_database d ON d.oid=s.dbid GROUP BY 1 ORDER BY 3 DESC;
SELECT dealloc FROM pg_stat_statements_info;   -- 663,052
```
Q18 orders-DB statements by rows (text hidden; calls/rows exact; max 1,925 rows/call, none near 1.14M rows/call):
```sql
SELECT s.calls, s.rows, round(s.rows::numeric/NULLIF(s.calls,0),1) rpc, round(s.mean_exec_time::numeric,1) mean_ms
FROM pg_stat_statements s WHERE s.dbid=(SELECT oid FROM pg_database WHERE datname=current_database())
ORDER BY s.rows DESC LIMIT 25;
```
Q19 table scan ratios, first pass (exact counters at that time; youpay 909 / 1,040,679,102 = 1,144,861 rows per seq scan; 129,122 / 21,904,581 = 169.6 rows per idx scan). Superseded by Q19b for the table figures:
```sql
SELECT relname, seq_scan, seq_tup_read, round(seq_tup_read::numeric/NULLIF(seq_scan,0)) rows_per_seq,
       idx_scan, idx_tup_fetch, round(idx_tup_fetch::numeric/NULLIF(idx_scan,0),1) rows_per_idx
FROM pg_stat_user_tables WHERE schemaname='public' AND (seq_scan>0 OR idx_scan>0)
ORDER BY seq_tup_read DESC NULLS LAST LIMIT 40;
```
Q20 youpay index usage (exact: only the PK has idx_scan>0 = 129,122; 7 indexes at 0):
```sql
SELECT indexrelname, idx_scan, idx_tup_read, idx_tup_fetch FROM pg_stat_user_indexes
WHERE relname='youpayclient_youpayclienttransactiondata' ORDER BY 1;
```
Q21 DB-wide tuples returned (exact: tup_returned 8,789,692,325; youpay seq reads = 11.8%; stats_reset NULL):
```sql
SELECT datname, tup_returned, tup_fetched, xact_commit, stats_reset IS NULL no_reset
FROM pg_stat_database WHERE datname=current_database();
```
Q22 order_order indexes (exact: UNIQUE on number and order_reference; btree on transaction_id; none on payment_order_reference):
```sql
SELECT indexname, indexdef FROM pg_indexes WHERE tablename='order_order' ORDER BY 1;
```
Q23 youpay full attribute list incl. dropped (exact: 65 attnums, attnum 62 dropped; point columns and types):
```sql
SELECT a.attnum, a.attname, a.attisdropped, format_type(a.atttypid,a.atttypmod) ty FROM pg_attribute a
WHERE a.attrelid='youpayclient_youpayclienttransactiondata'::regclass AND a.attnum>0 ORDER BY 1;
```
Q24 friction/admin/session columns and indexes (exact catalog):
```sql
SELECT c.relname, a.attname, format_type(a.atttypid,a.atttypmod) ty, a.attnotnull nn FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
WHERE c.relnamespace='public'::regnamespace AND a.attnum>0 AND NOT a.attisdropped AND (
 c.relname IN ('core_currencybasketlimit','core_unsupportedcountry','django_admin_log','django_session','webhooks_merchantwebhookmessage')
 OR (c.relname='order_order' AND a.attname IN ('transaction_id','payment_order_reference','order_reference','number'))
 OR (c.relname='kafka_giftcreationlog' AND a.attname IN ('created_gift_details','payload')))
ORDER BY 1, a.attnum;
SELECT tablename, indexdef FROM pg_indexes
WHERE tablename IN ('django_session','django_admin_log','core_currencybasketlimit','core_unsupportedcountry') ORDER BY 1;
SELECT c.relname, string_agg(a.attname, ',' ORDER BY a.attnum) cols FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
WHERE c.relnamespace='public'::regnamespace AND a.attnum>0 AND NOT a.attisdropped AND c.relname ~ '^kafka_' GROUP BY 1 ORDER BY 1;
```
Q25 dropped columns across the unit (exact: 1, youpayclient_youpayclienttransactiondata.62):
```sql
SELECT count(*) FILTER (WHERE a.attisdropped) dropped,
       string_agg(c.relname||'.'||a.attnum, ', ') FILTER (WHERE a.attisdropped) which
FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
WHERE c.relnamespace='public'::regnamespace AND c.relkind='r' AND a.attnum>0
AND c.relname ~ '^(kafka_|youpayclient_|webhooks_|django_|core_|auth_|otp_|two_|jet_)';
```

Q19b table scan ratios with per-day rates, re-query 2026-09-29 (exact counters at query time; window 35.53 days from Q26; youpay 910 seq scans = 25.6/day, 1,041,912,866 tuples, 1,144,959 per scan; 129,122 idx scans = 3,634/day, 21,904,581 fetched = 616,500/day, 169.6 per scan; order_order 2,179 = 61.3/day; the 36-scan tables = 1.0/day; no kafka_/webhooks_/django_ table in the result):
```sql
WITH w AS (SELECT extract(epoch FROM now()-pg_postmaster_start_time())/86400.0 d)
SELECT relname, seq_scan, seq_tup_read, round(seq_tup_read::numeric/NULLIF(seq_scan,0)) rows_per_seq,
 round((seq_scan/w.d)::numeric,1) seq_per_day, round((seq_tup_read/w.d)::numeric) seq_rows_per_day,
 idx_scan, idx_tup_fetch, round(idx_tup_fetch::numeric/NULLIF(idx_scan,0),1) rows_per_idx,
 round((idx_scan/w.d)::numeric,1) idx_per_day, round((idx_tup_fetch/w.d)::numeric) idx_rows_per_day,
 (SELECT reltuples::bigint FROM pg_class c WHERE c.oid=s.relid) reltuples
FROM pg_stat_user_tables s, w WHERE schemaname='public' AND (seq_scan>0 OR idx_scan>0)
ORDER BY seq_tup_read DESC NULLS LAST LIMIT 40;
```
Q20 was re-run with the same SQL (unchanged: PK 129,122 idx_scan, idx_tup_read 22,200,008, idx_tup_fetch 21,904,581; the 7 other indexes 0).

Q26 stats windows (exact at query time: postmaster start and pg_stat_bgwriter.stats_reset both 35.53 days ago, 2 s apart; pgss stats_reset 95.5 days ago; dealloc 664,237):
```sql
SELECT now() AS at_, pg_postmaster_start_time() AS pm_start,
 round(extract(epoch FROM now()-pg_postmaster_start_time())/86400.0,2) AS uptime_days,
 (SELECT stats_reset FROM pg_stat_bgwriter) AS bgw_reset,
 round(extract(epoch FROM now()-(SELECT stats_reset FROM pg_stat_bgwriter))/86400.0,2) AS bgw_days,
 round(extract(epoch FROM now()-(SELECT stats_reset FROM pg_stat_statements_info))/86400.0,2) AS pgss_days,
 (SELECT dealloc FROM pg_stat_statements_info) AS dealloc;
```
Q27 orders-DB pgss re-snapshot (exact at query time: 20 stmts, 1,860,334 calls, 3,426,135 rows, max 33.2 rows/call; the per-call listing returned 19 rows; the Q18 1,925-rows/call statement is gone):
```sql
SELECT count(*) stmts, sum(calls)::bigint calls, sum(rows)::bigint rows_, max(round(rows::numeric/NULLIF(calls,0),1)) max_rpc
FROM pg_stat_statements WHERE dbid=(SELECT oid FROM pg_database WHERE datname=current_database());
SELECT s.calls, s.rows, round(s.rows::numeric/NULLIF(s.calls,0),1) rpc, round(s.mean_exec_time::numeric,1) mean_ms
FROM pg_stat_statements s WHERE s.dbid=(SELECT oid FROM pg_database WHERE datname=current_database())
ORDER BY rpc DESC NULLS LAST LIMIT 25;
```
Q28 per-database transactions (exact at query time: 20 DBs at exactly 36 xact_commit with 1,104–1,878 tup_returned; postgres 38; ygag_checkout_db 39; orders DB xact_commit 10,430,804, tup_returned 8,795,539,868; stats_reset NULL everywhere):
```sql
SELECT datname, xact_commit, xact_rollback, tup_returned, stats_reset IS NULL no_reset FROM pg_stat_database ORDER BY 1;
```
Q29 columns for the new views and P16 (exact catalog: core_remoteurlconfig server varchar(15)/url varchar(200)/is_active; django_admin_log.object_id text, change_message text; otp_totp_totpdevice step/last_t; core_currencyexchangerate buy_rate/sell_rate numeric(15,6); core_commandexecuter created_by_id; webhooks sender_ip/ip_address inet):
```sql
SELECT c.relname, a.attname, format_type(a.atttypid,a.atttypmod) ty, a.attnotnull nn FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
WHERE c.relnamespace='public'::regnamespace AND a.attnum>0 AND NOT a.attisdropped AND c.relname IN
('core_remoteurlconfig','django_admin_log','otp_totp_totpdevice','core_currencyexchangerate','core_commandexecuter','webhooks_webhookconfig','webhooks_merchantwebhookmessage')
ORDER BY 1, a.attnum;
```

## Appendix: prepared query pack (run once SELECT is granted; all cheap and PII-safe)

These have NOT been run (no grant yet); every result they would produce is NEEDS-GRANT until then. Each one touches only allowlisted columns or the `atlas_ro.*` views from the grant request. Raw jsonb, free-text error columns and secrets stay ungranted: every error/reason breakdown reads `error_class` / `response_class`, never the raw text. A view over a large table still scans that table, so `TABLESAMPLE` cannot be applied to a view; view queries are bounded by `id` ranges on the PK instead. Each stays under a 20s budget: large tables use `TABLESAMPLE SYSTEM(1)` or PK ranges. Run `EXPLAIN` first on anything that has no WHERE clause against youpay or giftcreationlog.

P0 coverage: min/max timestamp via the PK, with no full scan (repeat for each large table):
```sql
SELECT (SELECT created_on FROM kafka_giftcreationlog ORDER BY id ASC  LIMIT 1) first_on,
       (SELECT created_on FROM kafka_giftcreationlog ORDER BY id DESC LIMIT 1) last_on,
       (SELECT min(id) FROM kafka_giftcreationlog) min_id, (SELECT max(id) FROM kafka_giftcreationlog) max_id;
SELECT (SELECT start_timestamp FROM kafka_atworkkafkadatalog ORDER BY id LIMIT 1), (SELECT start_timestamp FROM kafka_atworkkafkadatalog ORDER BY id DESC LIMIT 1);
SELECT (SELECT created_on FROM youpayclient_youpayclienttransactiondata ORDER BY id LIMIT 1), (SELECT created_on FROM youpayclient_youpayclienttransactiondata ORDER BY id DESC LIMIT 1);
SELECT (SELECT received_at FROM webhooks_merchantwebhookmessage ORDER BY id LIMIT 1), (SELECT received_at FROM webhooks_merchantwebhookmessage ORDER BY id DESC LIMIT 1);
```
P1 gift-creation status and error mix (latest ~50K events by PK, via the view; error text only as `error_class`):
```sql
-- :max_id from P0; window of the latest ~50K events (PK range scan)
SELECT status, has_error, has_failure, count(*) n
FROM atlas_ro.kafka_giftcreationlog WHERE id > :max_id - 50000 GROUP BY 1,2,3 ORDER BY 4 DESC;
SELECT error_class, failure_class, count(*) n
FROM atlas_ro.kafka_giftcreationlog WHERE id > :max_id - 50000 AND (has_error OR has_failure)
GROUP BY 1,2 ORDER BY 3 DESC LIMIT 20;
```
P2 gift-creation retry span and order_id format (sample):
```sql
SELECT status, percentile_cont(ARRAY[0.5,0.95]) WITHIN GROUP (ORDER BY extract(epoch FROM modified_on-created_on)) span_s, count(*)
FROM kafka_giftcreationlog TABLESAMPLE SYSTEM (1) GROUP BY 1;
SELECT CASE WHEN order_id ~ '^[0-9]+$' THEN 'numeric' WHEN order_id ~ '^[A-Z0-9-]+$' THEN 'alnum_upper' ELSE 'other' END fmt,
       length(order_id) len, count(*) FROM kafka_giftcreationlog TABLESAMPLE SYSTEM (1) GROUP BY 1,2 ORDER BY 3 DESC LIMIT 10;
SELECT count(*) sample_rows, count(DISTINCT order_id) distinct_orders FROM kafka_giftcreationlog TABLESAMPLE SYSTEM (1);  -- the per-order ratio is biased low in a sample; use a PK id-range window instead:
SELECT count(*), count(DISTINCT order_id) FROM atlas_ro.kafka_giftcreationlog WHERE id BETWEEN :max_id-50000 AND :max_id;
```
P3 datalog status, stuck share, error share and p50/p95 latency (via `atlas_ro.kafka_datalog`; small sources in full, atwork bounded to its latest ~50K ids; `src` is a constant per UNION branch, so the planner prunes the filter per table):
```sql
SELECT src, status, count(*) n,
       avg((completed_timestamp IS NULL)::int) in_flight_share,
       avg((completed_timestamp IS NULL AND start_timestamp < now() - interval '1 hour')::int) stuck_share,
       percentile_cont(ARRAY[0.5,0.95]) WITHIN GROUP (ORDER BY extract(epoch FROM completed_timestamp-start_timestamp)) lat_s,
       avg(has_error::int) err_share
FROM atlas_ro.kafka_datalog WHERE src <> 'atwork' OR id > :atwork_max_id - 50000 GROUP BY 1,2 ORDER BY 1,3 DESC;
SELECT src, error_class, count(*) FROM atlas_ro.kafka_datalog WHERE has_error AND (src <> 'atwork' OR id > :atwork_max_id - 50000)
GROUP BY 1,2 ORDER BY 3 DESC LIMIT 30;
-- plusoffer is 1.5 GB of TOAST: the view never reads `data`, so its jsonb is not detoasted.
```
P4 fraud/blacklist logs (small, full scan OK):
```sql
SELECT src, status, has_error, count(*) FROM atlas_ro.kafka_eventlog GROUP BY 1,2,3 ORDER BY 1,4 DESC;
SELECT src, error_class, count(*) FROM atlas_ro.kafka_eventlog WHERE has_error GROUP BY 1,2 ORDER BY 3 DESC LIMIT 20;
```
P5 youpay payment outcome matrix and session duration (1% sample):
```sql
SELECT payment_status, approved, payment_gateway, count(*)*100 est,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM modified_on-created_on)) p50_session_s,
       percentile_cont(0.95) WITHIN GROUP (ORDER BY extract(epoch FROM modified_on-created_on)) p95_session_s
FROM youpayclient_youpayclienttransactiondata TABLESAMPLE SYSTEM (1) GROUP BY 1,2,3 ORDER BY 4 DESC LIMIT 60;
SELECT d.response_class reason, count(*) n
FROM atlas_ro.youpay_derived d JOIN youpayclient_youpayclienttransactiondata y ON y.id = d.id
WHERE d.id > :max_id - 50000 AND NOT y.approved GROUP BY 1 ORDER BY 2 DESC LIMIT 25;
SELECT payment_method, payment_scheme, platform, channel_code, language, is_gcc_card, avg(approved::int) approval_rate, count(*)*100 est
FROM youpayclient_youpayclienttransactiondata TABLESAMPLE SYSTEM (1) GROUP BY 1,2,3,4,5,6 ORDER BY 8 DESC LIMIT 60;
SELECT avg(is_fraud::int) fraud, avg(is_flagged::int) flagged FROM youpayclient_youpayclienttransactiondata TABLESAMPLE SYSTEM (1);
```
P6 youpay-to-order cardinality hypothesis test (sample and id window):
```sql
SELECT count(*) rows_, count(order_reference) with_ref, count(DISTINCT order_reference) distinct_ref
FROM youpayclient_youpayclienttransactiondata WHERE id BETWEEN :max_id-50000 AND :max_id;
```
P7 payment economics per gateway (sample):
```sql
SELECT payment_gateway, settlement_entity, currency, count(*)*100 est, sum(amount)*100 est_amount,
       sum(gateway_charge)*100 est_gw_charge, sum(processing_fee)*100 est_proc_fee,
       sum(gateway_charge)/NULLIF(sum(paid_amount),0) gw_cost_ratio
FROM youpayclient_youpayclienttransactiondata TABLESAMPLE SYSTEM (1) WHERE approved GROUP BY 1,2,3 ORDER BY 4 DESC LIMIT 40;
```
P8 loyalty flags and redemption mix. A single SELECT with three FILTERs and no WHERE **cannot** use the three boolean indexes: it would seq-scan the 2.08 GB table. So each flag gets its own statement, and each one is run with `EXPLAIN` first. If the plan is not an index/bitmap scan, fall back to the TABLESAMPLE form:
```sql
EXPLAIN SELECT count(*) FROM youpayclient_youpayclienttransactiondata WHERE is_qitaf_enabled;          -- confirm index/bitmap plan first
SELECT count(*) FROM youpayclient_youpayclienttransactiondata WHERE is_qitaf_enabled;
SELECT count(*) FROM youpayclient_youpayclienttransactiondata WHERE point_collection_enabled;
SELECT count(*) FROM youpayclient_youpayclienttransactiondata WHERE is_full_redemption;
-- fallback (estimate): all three shares from one 1% sample
SELECT avg(is_qitaf_enabled::int) qitaf, avg(point_collection_enabled::int) collect, avg(is_full_redemption::int) full_redeem, count(*) n
FROM youpayclient_youpayclienttransactiondata TABLESAMPLE SYSTEM (1);
SELECT point_program, loyalty_level, is_full_redemption, count(*)*100 est, avg(redeemed_amount/NULLIF(amount,0)) redeem_share,
       avg((payable_amount>0 AND redeemed_amount>0)::int) partial_share
FROM youpayclient_youpayclienttransactiondata TABLESAMPLE SYSTEM (1) GROUP BY 1,2,3 ORDER BY 4 DESC LIMIT 40;
-- card issuer country: 1.23M rows, sample rather than GROUP BY over the whole table (the index is unused on the replica)
SELECT card_issuer_country, count(*)*100 est, avg(approved::int) approval_rate
FROM youpayclient_youpayclienttransactiondata TABLESAMPLE SYSTEM (1) GROUP BY 1 ORDER BY 2 DESC LIMIT 30;
```
P8b point economics: earned vs redeemed per program (1% sample, estimate):
```sql
SELECT point_program, loyalty_level, count(*)*100 est_sessions,
       sum(earned_point)*100 est_earned, sum(redeemed_points)*100 est_redeemed,
       sum(redeemed_points)/NULLIF(sum(earned_point),0) burn_to_earn,
       avg(redeemed_points/NULLIF(available_points,0)) FILTER (WHERE redeemed_points>0) avg_balance_used,
       avg((earned_point>0)::int) earn_share, avg((redeemed_points>0)::int) redeem_share
FROM youpayclient_youpayclienttransactiondata TABLESAMPLE SYSTEM (1) WHERE approved GROUP BY 1,2 ORDER BY 3 DESC LIMIT 40;
```
P9 monthly buckets via id ranges (webhooks and youpay; exact for small tables):
```sql
SELECT date_trunc('month', received_at) m, count(*), avg((error_message IS NOT NULL)::int) err_rate
FROM webhooks_merchantwebhookmessage GROUP BY 1 ORDER BY 1;          -- 5.2K rows, full scan OK
SELECT width_bucket(id, :min_id, :max_id, 40) b, min(created_on), max(created_on), count(*)*100 est, avg(approved::int)
FROM youpayclient_youpayclienttransactiondata TABLESAMPLE SYSTEM (1) GROUP BY 1 ORDER BY 1;
```
P10 ops interventions and admin audit (small):
```sql
SELECT command, status, input_type, count(*), min(created_on), max(created_on) FROM core_commandexecuter GROUP BY 1,2,3 ORDER BY 4 DESC;
SELECT date_trunc('month', action_time) m, action_flag, count(*) FROM django_admin_log GROUP BY 1,2 ORDER BY 1;
-- which entities get manual back-office edits (2.6K rows; content_type_id indexed)
SELECT ct.app_label, ct.model, l.action_flag, count(*) n, min(l.action_time)::date first_, max(l.action_time)::date last_
FROM django_admin_log l LEFT JOIN django_content_type ct ON ct.id = l.content_type_id
GROUP BY 1,2,3 ORDER BY 4 DESC LIMIT 60;
-- admin edits joined to orders via the object_id grant (object_id is text; CASE guards the cast)
SELECT l.action_flag, count(*) n, count(o.id) matched_orders, min(l.action_time)::date, max(l.action_time)::date
FROM django_admin_log l
JOIN django_content_type ct ON ct.id = l.content_type_id AND ct.app_label = 'order' AND ct.model = 'order'
LEFT JOIN order_order o ON o.id = CASE WHEN l.object_id ~ '^[0-9]{1,18}$' THEN l.object_id::bigint END
GROUP BY 1 ORDER BY 2 DESC;
```
P11 bounded giftcreationlog-to-order join, testing all three candidate `order_id` formats in one window (never unbounded; order_id is unindexed; every order_order probe is on a UNIQUE index):
```sql
WITH g AS (SELECT order_id FROM atlas_ro.kafka_giftcreationlog WHERE id BETWEEN :max_id-20000 AND :max_id)
SELECT count(*) g_rows,
       count(*) FILTER (WHERE EXISTS (SELECT 1 FROM order_order o WHERE o.number = g.order_id))           matched_number,
       count(*) FILTER (WHERE CASE WHEN g.order_id ~ '^[0-9]{1,18}$'
                                   THEN EXISTS (SELECT 1 FROM order_order o WHERE o.id = g.order_id::bigint)
                              END)                                                                     matched_id,
       -- CASE, not AND: Postgres does not guarantee AND evaluation order, so `order_id::bigint` could run on a
       -- non-numeric value and abort the query. CASE guarantees the cast only runs on numeric strings.
       -- (o.id::text = order_id would avoid the cast but could not use the PK.)
       count(*) FILTER (WHERE EXISTS (SELECT 1 FROM order_order o WHERE o.order_reference = g.order_id))  matched_order_reference
FROM g;
```
P11b youpay-to-order reconciliation (bounded on the youpay side; probes UNIQUE `order_order.order_reference` and indexed `transaction_id`; never drives by the unindexed `payment_order_reference`):
```sql
WITH y AS (SELECT order_reference, transaction_id, approved FROM youpayclient_youpayclienttransactiondata
           WHERE id BETWEEN :max_id-20000 AND :max_id)
SELECT approved, count(*) y_rows,
       count(*) FILTER (WHERE EXISTS (SELECT 1 FROM order_order o WHERE o.order_reference = y.order_reference)) matched_ref,
       count(*) FILTER (WHERE EXISTS (SELECT 1 FROM order_order o WHERE o.transaction_id = y.transaction_id))   matched_txn
FROM y GROUP BY 1;
```
P12 PII-safe jsonb structure (from `atlas_ro.youpay_derived` / `atlas_ro.webhook_message`: lengths, key names and counts only, never values):
```sql
-- youpay basket size / repeat depth (latest ~50K sessions by PK)
SELECT d.items_type, least(d.n_items,10) n_items, least(d.n_history,20) n_history, count(*) n, avg(y.approved::int) approval_rate
FROM atlas_ro.youpay_derived d JOIN youpayclient_youpayclienttransactiondata y ON y.id = d.id
WHERE d.id > :max_id - 50000 GROUP BY 1,2,3 ORDER BY 4 DESC LIMIT 80;
-- udf1 key names (campaign/UTM carrier test) and brand-key count (multi-brand carts)
SELECT k udf1_key, count(*) n FROM atlas_ro.youpay_derived, unnest(udf1_keys) k WHERE id > :max_id - 50000 GROUP BY 1 ORDER BY 2 DESC LIMIT 50;
SELECT least(n_brand_keys,10) n_brand_keys, count(*) FROM atlas_ro.youpay_derived WHERE id > :max_id - 50000 GROUP BY 1 ORDER BY 1;
-- redirect host mix (storefront / channel), host only
SELECT success_host, count(*) FROM atlas_ro.youpay_derived WHERE id > :max_id - 50000 GROUP BY 1 ORDER BY 2 DESC LIMIT 20;
-- webhook event types / error classes (5.2K rows, full scan OK)
SELECT 'message' col, k, count(*) FROM atlas_ro.webhook_message, unnest(message_keys) k GROUP BY 1,2
UNION ALL
SELECT 'error_message', k, count(*) FROM atlas_ro.webhook_message, unnest(error_keys) k GROUP BY 1,2
ORDER BY 3 DESC LIMIT 100;
```
P13 cross-table friction:
```sql
-- (a) near-limit baskets per currency (1% sample; core_currencybasketlimit has 8 rows)
SELECT y.currency, bl.limit_amount, count(*)*100 est,
       avg((y.amount >= 0.9*bl.limit_amount)::int) near_limit_share,
       avg(y.approved::int) FILTER (WHERE y.amount >= 0.9*bl.limit_amount) approval_near_limit,
       avg(y.approved::int) FILTER (WHERE y.amount <  0.9*bl.limit_amount) approval_elsewhere
FROM youpayclient_youpayclienttransactiondata y TABLESAMPLE SYSTEM (1)
JOIN core_currency c ON c.code = y.currency
JOIN core_currencybasketlimit bl ON bl.currency_id = c.id AND bl.is_active
GROUP BY 1,2 ORDER BY 3 DESC;
-- (b) approval by issuer country, flagged if unsupported (1% sample)
SELECT y.card_issuer_country, (u.id IS NOT NULL) unsupported, y.is_gcc_card, count(*)*100 est, avg(y.approved::int) approval_rate
FROM youpayclient_youpayclienttransactiondata y TABLESAMPLE SYSTEM (1)
LEFT JOIN core_unsupportedcountry u ON u.country_code = y.card_issuer_country AND u.is_active
GROUP BY 1,2,3 ORDER BY 4 DESC LIMIT 60;
-- (c) GCC card x gateway x approved (1% sample)
SELECT payment_gateway, is_gcc_card, approved, count(*)*100 est
FROM youpayclient_youpayclienttransactiondata TABLESAMPLE SYSTEM (1) GROUP BY 1,2,3 ORDER BY 1,2,3;
```
P14 django_session expired share (uses the `expire_date` btree; needs only the expire_date column grant):
```sql
SELECT count(*) FILTER (WHERE expire_date <  now()) expired,
       count(*) FILTER (WHERE expire_date >= now()) live,
       min(expire_date)::date oldest_expiry
FROM django_session;
```
P15 gifts per creation event (PII-safe count via `atlas_ro.kafka_giftcreationlog.gifts_created`; no values):
```sql
SELECT status, gift_details_shape, least(gifts_created,20) gifts_in_event, count(*) n
FROM atlas_ro.kafka_giftcreationlog WHERE id > :max_id - 50000 GROUP BY 1,2,3 ORDER BY 4 DESC LIMIT 60;
```

P16 remaining signals (all small tables or bounded; views where the raw column is ungranted):
```sql
-- (a) admin 2FA recency: how many TOTP devices were used recently vs dormant (28 rows)
SELECT confirmed, last_use_bucket, count(*), sum(throttling_failure_count) throttle_failures
FROM atlas_ro.totp_device_health GROUP BY 1,2 ORDER BY 1,2;
-- (b) which fields back-office staff change, per model (field NAMES only, from change_message JSON)
SELECT ct.app_label, ct.model, k.action_kind, f field_name, count(*) n
FROM atlas_ro.admin_change_keys k JOIN django_content_type ct ON ct.id = k.content_type_id, unnest(k.field_names) f
GROUP BY 1,2,3,4 ORDER BY 5 DESC LIMIT 60;
-- (c) FX rate age and buy/sell spread per currency pair (437 rows)
SELECT bc.id base_id, fc.code foreign_code, count(*) n_rates,
       max(r.modified_on) last_update, now() - max(r.modified_on) age,
       avg((r.sell_rate - r.buy_rate) / NULLIF(r.buy_rate,0)) avg_spread,
       (array_agg((r.sell_rate - r.buy_rate) / NULLIF(r.buy_rate,0) ORDER BY r.modified_on DESC))[1] latest_spread
FROM core_currencyexchangerate r JOIN core_currency fc ON fc.id = r.foreign_currency_id
JOIN core_basecurrency bc ON bc.id = r.base_currency_id GROUP BY 1,2 ORDER BY age DESC;
-- (d) presentment vs cart currency mismatch x approval (1% sample, estimate)
SELECT (currency IS DISTINCT FROM cart_currency) fx_mismatch, currency, cart_currency,
       count(*)*100 est, avg(approved::int) approval_rate
FROM youpayclient_youpayclienttransactiondata TABLESAMPLE SYSTEM (1) GROUP BY 1,2,3 ORDER BY 4 DESC LIMIT 40;
-- (e) youpay hour-of-week x approval (1% sample; created_on is timestamptz, reported in Asia/Dubai local time)
SELECT extract(isodow FROM created_on AT TIME ZONE 'Asia/Dubai')::int dow,
       extract(hour   FROM created_on AT TIME ZONE 'Asia/Dubai')::int hr,
       count(*)*100 est, avg(approved::int) approval_rate
FROM youpayclient_youpayclienttransactiondata TABLESAMPLE SYSTEM (1) GROUP BY 1,2 ORDER BY 1,2;
-- (f) webhook sender consistency: share of messages whose ip_address = configured sender_ip (boolean only)
SELECT from_configured_sender, count(*), avg(has_error::int) err_rate FROM atlas_ro.webhook_message GROUP BY 1;
-- (g) ops reruns: distinct operators, date-window length per command
SELECT command, status, input_type, count(*) runs, count(DISTINCT created_by_id) operators,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY (end_date - start_date)) p50_window_days,
       max(end_date - start_date) max_window_days, min(created_on)::date first_, max(created_on)::date last_
FROM core_commandexecuter GROUP BY 1,2,3 ORDER BY 4 DESC;
-- (h) remote service topology (host only)
SELECT server, is_active, url_host FROM atlas_ro.remote_url_host ORDER BY 1;
```
