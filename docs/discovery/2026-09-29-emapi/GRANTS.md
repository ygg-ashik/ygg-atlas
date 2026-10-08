# ygg-atlas: consolidated read-only grant request

**Requested by:** ygg-atlas data platform (Data & AI architecture)
**Date:** 2026-09-29
**Target:** Aurora PostgreSQL 16 cluster `ecom-shared-read-optimized` (one writer, one reader)
**Databases:** `ygag_ecom_users_db`, `ygag_ecom_orders_db`, `ygag_emapi_stores_db`, `ygag_ecomweb_stores_db`
**Companion document:** REPORT.md. Feature ids (AF-xx) and hypothesis ids (Hxx) refer to it.

## 0. Summary for the DBA

**Current state** (verified 2026-09-29 with `has_table_privilege` as `<emapi_login_role>`):

| Database | SELECT today | Problem |
|---|---|---|
| users | 40 of 40 tables | Too broad: includes secrets, password hashes and raw PII |
| orders | 0 of 159 | Nothing readable |
| emapi | 0 of 84 | Nothing readable |
| ecomweb | 0 of 134 | Nothing readable |

**What we ask:**

1. **One dedicated group role** that holds all grants, plus a view-owner role (section 1).
2. **A keyed-hash (HMAC-SHA256) facility, identical in all four databases**, so identities can be joined across databases without raw email, phone or username ever leaving a database (section 2).
3. **Per-database grants**, delivered two ways:
   - column-level SELECT on non-PII columns, so atlas can run `TABLESAMPLE` on large tables;
   - views in schema `atlas_ro` that expose derived flags, keyed hashes and buckets in place of PII (sections 3–6).
4. **Index and extract asks** to protect the shared reader (section 7).
5. **A least-privilege clean-up of the users DB**, after the views exist (section 3.3).
6. **Generated DDL, not hand edits.** Appendix A turns sections 1–6 into one ready-to-run file per database, with every hash macro expanded, every object created as `atlas_view_owner`, and the ownership check appended.

**Principles:**

- Read-only.
- Grants are run on the **primary** so they replicate. Atlas connects **only to the reader endpoint**.
- The data that leaves a database is aggregate or pseudonymous.
- No secrets. No free text. No raw contact data. No card data.
- **Grant form follows the table's content, and only enumerated grants fail closed.**
  - **Tables with user-linked rows, free text, payloads or credentials** are exposed only through `atlas_ro` views or **enumerated column grants**. A column added later is not granted automatically, so these grants fail closed.
  - **Pure catalog, reference and config tables** (no user-linked rows, no free text written by customers, no secrets) get table-level grants, **named one by one**. This request never uses `GRANT ... ON ALL TABLES IN SCHEMA`. A table-level grant does expose columns added later, so these grants do **not** fail closed. The residual risk is covered by the monthly column-drift check V12 (section 9), which compares `pg_attribute` with the approved column list and alerts on any new column.
  - A new table is never granted until someone reviews it.

**Priority tiers.** If this cannot all land at once, apply the tiers in this order:

A feature or hypothesis that needs several tiers is listed under the **last** tier it needs, so it works once that tier lands. REPORT.md carries the full tier set per item (feature catalog "Tier" column, hypothesis catalog "Readiness" column).

| Tier | Contents | Features unlocked | Hypotheses unlocked |
|---|---|---|---|
| 0 | Sections 1–2 in all four DBs | Prerequisite for every row below | — |
| 1 | orders: `users_userprofile`, `order_order`, `order_line`, `order_orderlinequantitydetail`, plus the no-PII catalog, offer and checkout-config companions in §4.3 | AF-45, AF-46, AF-47, AF-53, AF-55, AF-64, AF-75; order-line half of AF-36 (`order_line.purchase_origin`) | H01, H08, H09, H12, H14, H23, H26, H27, H29, H30, H44, H50, H59, H64, H66, H71 |
| 2 | orders: personalisation, guests, payments, gift-creation log, baskets | AF-33, AF-36 (complete, with `basket_line.purchase_origin`), AF-48, AF-49, AF-50, AF-51, AF-59, AF-60, AF-69, AF-71, AF-74, AF-76, AF-93 | H13, H16, H19, H20, H21, H22, H31, H32, H41, H46, H47, H49, H54, H67, H68, H69, H70, H77 |
| 3 | emapi: catalog, offers, favourites, app user view | AF-17 (app side), AF-34, AF-35 (app side), AF-43, AF-52, AF-61, AF-65, AF-77 | H18, H25, H28, H42, H43, H52, H58, H62, H65 |
| 4 | ecomweb: merchandising, recently viewed, opt-ins | AF-17 (web side), AF-35 (web side), AF-54, AF-58, AF-66, AF-72, AF-73, AF-94, AF-95, AF-96 | H17, H24, H53, H60, H63 |
| 5 | Integration, risk and admin logs in orders, emapi and ecomweb | AF-62, AF-63, AF-67, AF-68, AF-70, AF-78 | H37 |

Items that need a source outside these four databases (AF-79–AF-87; the blocked-claim-attempt part of AF-97; H40, H45, H56, H73) are not covered by this request.

# 1. Roles and session safety (run once on the cluster)

**Roles:**

- `<emapi_login_role>` keeps its LOGIN and becomes a member of `atlas_reader`. Every grant below goes to `atlas_reader`, never to the login role directly.
- Views are owned by `atlas_view_owner` (NOLOGIN). Views run with their owner's privileges, so the owner reads the raw columns and the reader only ever sees the view output.

```sql
-- cluster-wide roles (run as rds_superuser / DB owner on the PRIMARY)
CREATE ROLE atlas_reader NOLOGIN;
CREATE ROLE atlas_view_owner NOLOGIN;
GRANT atlas_reader TO <emapi_login_role>;

-- session guards for the interactive atlas role
ALTER ROLE <emapi_login_role> SET default_transaction_read_only = on;
ALTER ROLE <emapi_login_role> SET statement_timeout = '20s';
ALTER ROLE <emapi_login_role> SET idle_in_transaction_session_timeout = '60s';
ALTER ROLE <emapi_login_role> SET lock_timeout = '2s';
ALTER ROLE <emapi_login_role> CONNECTION LIMIT 10;

-- separate role for the nightly governed extract (section 7): longer timeout, 2 connections, off-peak schedule
CREATE ROLE ygg_atlas_extract LOGIN PASSWORD '<from secrets manager>' IN ROLE atlas_reader;
ALTER ROLE ygg_atlas_extract SET default_transaction_read_only = on;
ALTER ROLE ygg_atlas_extract SET statement_timeout = '300s';
ALTER ROLE ygg_atlas_extract CONNECTION LIMIT 2;
```

**Network:** restrict both login roles in `pg_hba` or the security group to the atlas EC2 host, and to the reader endpoint.

**Who creates what (object ownership).** Every object in `atlas_ro` and `atlas_sec` must be **owned by `atlas_view_owner`**. Two things depend on it:

- the `ALTER DEFAULT PRIVILEGES FOR ROLE atlas_view_owner` below applies only to objects that `atlas_view_owner` itself creates;
- a view reads its source tables and the key table with its **owner's** rights.

If the DBA runs the DDL as `postgres`, the views and the key table are owned by `postgres`. The default privileges then never apply, `atlas_reader` gets nothing, and the key table sits outside the view owner's control. The DBA therefore:

1. creates the schemas with `AUTHORIZATION atlas_view_owner` (this needs the DBA's own CREATE right on the database);
2. grants `atlas_view_owner` read on the wrapped source tables (the view owner is NOLOGIN and owns none of them);
3. runs **every** `CREATE TABLE` / `VIEW` / `MATERIALIZED VIEW` / `FUNCTION` in sections 2–6 after `SET ROLE atlas_view_owner`, and `RESET ROLE` afterwards;
4. runs the ownership check at the end of this section.

The generator in Appendix A emits the DDL in exactly this order, per database.

```sql
-- once, on the cluster: let the DBA's login act as the view owner for the change window
GRANT atlas_view_owner TO <dba_login>;            -- REVOKE atlas_view_owner FROM <dba_login>; after the window
```

Then, **in each of the four databases**:

```sql
-- as the DBA
CREATE SCHEMA atlas_ro AUTHORIZATION atlas_view_owner;
GRANT USAGE ON SCHEMA atlas_ro TO atlas_reader;
ALTER DEFAULT PRIVILEGES FOR ROLE atlas_view_owner IN SCHEMA atlas_ro GRANT SELECT ON TABLES TO atlas_reader;
-- the view owner must be able to read the source tables it wraps (never granted to atlas_reader).
-- Appendix A emits one line per source table found in the view bodies:
-- GRANT SELECT ON <each source table named in sections 3-6> TO atlas_view_owner;

-- as the view owner: every CREATE in atlas_ro / atlas_sec
SET ROLE atlas_view_owner;
--   ... section 2 key table, sections 3-6 views and functions ...
RESET ROLE;
```

If an object was created under the wrong role, fix it in place rather than recreating it:

```sql
ALTER VIEW atlas_ro.<view> OWNER TO atlas_view_owner;            -- likewise ALTER MATERIALIZED VIEW / FUNCTION / TABLE
GRANT SELECT ON atlas_ro.<view> TO atlas_reader;                   -- default privileges do not apply retroactively
```

**Ownership check** (per database, after the DDL; Appendix A appends it to every file):

```sql
SELECT n.nspname, c.relname, c.relkind, pg_get_userbyid(c.relowner) AS owner,
       has_table_privilege('atlas_reader', c.oid, 'SELECT') AS reader_can_select
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname IN ('atlas_ro', 'atlas_sec') ORDER BY 1, 2;
-- expect: owner = atlas_view_owner on every row; reader_can_select = true on every atlas_ro row and false on atlas_sec.hk_key
SELECT p.proname, pg_get_userbyid(p.proowner) FROM pg_proc p WHERE p.pronamespace = 'atlas_ro'::regnamespace;   -- expect atlas_view_owner
SELECT has_schema_privilege('atlas_reader', 'atlas_sec', 'USAGE');                                                   -- expect false
SELECT has_table_privilege('atlas_view_owner', 'atlas_sec.hk_key', 'SELECT');                                       -- expect true
```

| Item | Justification |
|---|---|
| Group role `atlas_reader` | One place to audit and revoke. The login role inherits the grants and holds none directly. |
| `atlas_view_owner` | The PII-safe views need owner rights on the raw columns. The reader never gets them. |
| Timeouts, read-only default, connection cap | The single reader serves 40 databases, and the orders replica already carries an unidentified heavy reader (about 25.6 full youpay scans a day). |
| Separate extract role | Recurring funnels read nightly extracts instead of live scans (section 7). |

# 2. Keyed hashing, identical in all four databases

**Why.** Unkeyed `md5(email)`, `md5(phone)` or `md5(domain)` can be reversed with a dictionary. A salt written into a view definition is readable by anyone through `pg_get_viewdef`. The key therefore lives in a table that only `atlas_view_owner` can read. Views read it through a scalar subquery, so the view definition shows the table reference, never the key.

`pgcrypto` is not installed in the orders DB today: only `pg_stat_statements` and `plpgsql` are. It is supported on Aurora PostgreSQL 16.

```sql
-- in EACH database (users, orders, emapi, ecomweb)
CREATE SCHEMA IF NOT EXISTS atlas_crypto;
CREATE EXTENSION IF NOT EXISTS pgcrypto SCHEMA atlas_crypto;
GRANT USAGE ON SCHEMA atlas_crypto TO atlas_reader, atlas_view_owner;   -- hmac() is useless without the key

CREATE SCHEMA atlas_sec AUTHORIZATION atlas_view_owner;                  -- NO usage for atlas_reader
REVOKE ALL ON SCHEMA atlas_sec FROM PUBLIC;
GRANT USAGE ON SCHEMA atlas_sec TO atlas_view_owner;                     -- explicit, even though it owns the schema

SET ROLE atlas_view_owner;                                               -- the key table must be owned by the view owner
CREATE TABLE atlas_sec.hk_key (id int PRIMARY KEY DEFAULT 1 CHECK (id = 1), k bytea NOT NULL);
-- DBA inserts the SAME 32-byte key in all four DBs, fetched from AWS Secrets Manager (never in git, never in atlas config):
-- INSERT INTO atlas_sec.hk_key (k) VALUES (decode('<64 hex chars>', 'hex'));
RESET ROLE;

REVOKE ALL ON atlas_sec.hk_key FROM PUBLIC;
GRANT SELECT ON atlas_sec.hk_key TO atlas_view_owner;                    -- explicit: still works if ownership was set wrongly
-- never: any privilege on atlas_sec or atlas_sec.hk_key for atlas_reader, <emapi_login_role> or ygg_atlas_extract
```

**Hash expression.** The views inline this; `<norm(x)>` is replaced per column (template, not DDL):

```text
encode(atlas_crypto.hmac(convert_to(<norm(x)>, 'UTF8'), (SELECT k FROM atlas_sec.hk_key), 'sha256'), 'hex')
```

In sections 3–6 the DDL is written with two macros, `HK(<norm(x)>)` for the expression above and `PHONE(x)` for the phone rule below. **Nobody expands them by hand:** the generator in Appendix A expands both, emits one ready-to-run file per database, and refuses to write output if any macro is left or any unkeyed `md5(`/`sha` call appears in a view body.

**Normalisation.** Use exactly the same rule on every side, or matches silently fail:

| Kind | `<norm(x)>` |
|---|---|
| email / alternate email / claim email / recipient email | `lower(btrim(x))` |
| phone (account, OTP, blacklist `user_mobile_no`, recipient) | `PHONE(x)`: digits only, with a leading international `00` dropped, so `+971 5x…`, `009715x…` and `9715x…` give the same key. Expands to `nullif(CASE WHEN regexp_replace(x,'\D','','g') LIKE '00%' THEN substr(regexp_replace(x,'\D','','g'),3) ELSE regexp_replace(x,'\D','','g') END, '')`. A number stored in **national** format (`05x…`) keeps its national digits and does not match an international key; see the recipient phone note in section 4.2 |
| email domain | `lower(split_part(btrim(x), '@', 2))` (the **full** domain, e.g. `acme.com`) |
| email domain **label** (promo-blocked domain list) | `LABEL(x)` = `lower(split_part(ltrim(btrim(x), '@'), '.', 1))`, applied to the **same kind of value on both sides**: to `users_promotionaldomainblacklist.domain` (the 7 entries are uppercase labels with no TLD, e.g. `ACME`) and to the account's email domain `split_part(btrim(email), '@', 2)` (e.g. `acme.com` → `acme`). This is the first-label rule the discovery count used (5,544 live users, campaigns theme). A label key never equals a full-domain `email_domain_key`, so the two are never joined to each other |
| user key (UUID username or Cognito id) | `lower(btrim(x))` |
| local surrogate id (orders `guest_id` bigint → `users_guestuser.id`) | `x::text` (a bigint has no case or padding; never apply `lower`/`btrim` to a non-text column) |
| device signature (tokens) | `btrim(x)`, case preserved. It must equal the blacklist `user_device_id` rule below, or device matches fail silently |
| promo code; offer code (`plusoffer.code`, `order_line.offer_code`); gateway, order, invoice and loyalty references, including the customer-facing order `number` and basket/order `line_reference` (section 4) | `btrim(x)`, case preserved |
| tip payment reference (`user_tip_tip.reference_id` uuid, `user_tip_invoice.reference_id` varchar) | `lower(btrim(x::text))` on both tables, so a uuid and its text copy give the same key |
| black/white-list `value`, **by `type`** | `user_email` and `user_domain` → `lower(btrim(x))`; `user_mobile_no` → `PHONE(x)`; `user_device_id`, `user_ip` and `sms_country_code` → `btrim(x)` (case preserved, so a device key equals the token `device_key`); **any other type → no key (NULL)**. The same `CASE` is used in users `list_entry` (black and white) and orders `blacklist_entry`. Before creating the views, the DBA confirms the type set and the domain format with counts only: `SELECT type, count(*), count(*) FILTER (WHERE value LIKE '@%') FROM <blacklist table> GROUP BY 1;`. A new type is added to the `CASE` with its own rule; if domain values carry a leading `@`, the domain branch becomes `lower(ltrim(btrim(x), '@'))` |
| free-text field that holds a mix of kinds (e.g. activity-log `comment`) | Branch on the row type and use the matching rule above; never hash one kind with another kind's rule, or the key silently never matches |

`sms_country_code` keys keep their case (the codes are stored in mixed case, REPORT.md E6). Country grouping uses the separate `upper(value)` column `country_code`, never the key.

**Rules:**

- **Rotation:** replace the key in all four DBs in one change window, then re-run extracts. Atlas never stores the key.
- **Hashes are join keys only.** Atlas never displays a hash. Outputs are counts, rates or opaque ids.
- **Minimum cell sizes:** 10 on every breakdown, and 50 for organisation (email-domain) clusters.
- **Fallback if `pgcrypto` is refused:** `md5(encode((SELECT k FROM atlas_sec.hk_key),'hex') || '|' || <norm(x)>)`. It is weaker, but still keyed. Tell us if you use it, so the provenance chips can say so The Appendix A generator emits it with `--md5-fallback`; its unkeyed-hash check still rejects any other `md5` call.

# 3. ygag_ecom_users_db (readable today, needs narrowing)

## 3.1 Views requested

These views move every PII join inside the database. Atlas definitions then read only `atlas_ro.*`.

In the SQL below, `HK(...)` stands for the section 2 hash expression, written inline.

```sql
-- account dimension, no contact data
CREATE VIEW atlas_ro.user_profile WITH (security_barrier) AS
SELECT u.id AS user_id, HK(nullif(lower(btrim(u.username)),'')) AS user_key,
       u.date_joined, u.is_deleted, u.is_app_user, u.country_of_residence, u.trusted_user, u.is_staff,
       CASE WHEN u.gender IN ('male','female') THEN u.gender ELSE 'unknown' END AS gender,
       CASE WHEN u.birthdate ~ '^0000/\d{2}/\d{2}$' THEN substr(u.birthdate,6,2)::int END AS birthday_day,
       CASE WHEN u.birthdate ~ '^0000/\d{2}/\d{2}$' THEN substr(u.birthdate,9,2)::int END AS birthday_month,
       (u.birthdate = '0000/01/01') AS birthday_is_default,
       CASE WHEN u.phone_number LIKE '+966%' THEN 'SA' WHEN u.phone_number LIKE '+971%' THEN 'AE'
            WHEN u.phone_number ~ '^\+(974|965|973|968)' THEN 'GCC_OTHER' WHEN u.phone_number LIKE '+%' THEN 'OTHER' END AS phone_country_bucket,
       (coalesce(u.google_id,'') <> '') AS has_google_id, (coalesce(u.apple_id,'') <> '') AS has_apple_id,
       (coalesce(u.facebook_id,'') <> '') AS has_facebook_id,
       (cardinality(u.legacy_auth_code) > 0) AS has_legacy_code,
       CASE WHEN NOT u.is_deleted THEN HK(lower(split_part(btrim(u.email),'@',2))) END AS email_domain_key,  -- full domain; deleted rows hold ciphertext
       CASE WHEN NOT u.is_deleted
            THEN HK(nullif(lower(split_part(ltrim(btrim(split_part(btrim(u.email),'@',2)),'@'),'.',1)),'')) END AS email_domain_label_key,
            -- LABEL() rule of section 2: equals atlas_ro.promo_blocked_domain.domain_label_key, never email_domain_key
       CASE WHEN NOT u.is_deleted
            THEN coalesce(lower(split_part(ltrim(btrim(split_part(btrim(u.email),'@',2)),'@'),'.',1)) IN (
                   SELECT lower(split_part(ltrim(btrim(d.domain),'@'),'.',1))
                   FROM public.users_promotionaldomainblacklist d WHERE d.is_active), false) END AS is_promo_blocked_domain
            -- computed in-DB with the same LABEL() rule on both sides; no domain text leaves the DB (test V15)
FROM public.users_user u;

-- keyed identity keys for cross-DB and recipient matching (join side for orders G-1)
CREATE VIEW atlas_ro.identity_keys WITH (security_barrier) AS
SELECT u.id AS user_id, HK(nullif(lower(btrim(u.email)),'')) AS email_key, HK(PHONE(u.phone_number)) AS phone_key
FROM public.users_user u WHERE NOT u.is_deleted            -- deleted rows hold ciphertext, never hash it
UNION ALL
SELECT s.user_id, HK(nullif(lower(btrim(s.alternate_email)),'')), NULL FROM public.users_secondaryuseridentity s WHERE s.is_active AND NOT s.is_deleted;

-- gift claims without the claimed email: EMAIL activity types only, so the email normalisation is always the right one
CREATE VIEW atlas_ro.gift_claim WITH (security_barrier) AS
SELECT a.id, a.user_id, a."timestamp" AS claimed_at, a.activity,
       HK(nullif(lower(btrim(a.comment)),'')) AS claim_email_key,
       HK(nullif(lower(split_part(btrim(a.comment),'@',2)),'')) AS claim_domain_key
FROM public.users_useridentityactivitylog a
WHERE a.activity IN ('secondary_email_added_via_gift', 'secondary_email_added', 'secondary_email_removed');
-- updated_phone_number rows are excluded: their comment is not an email, and an email-normalised hash of it
-- would never match identity_keys.phone_key. comment is never exposed.

-- all identity events (including phone updates) with no comment-derived column at all
CREATE VIEW atlas_ro.identity_event WITH (security_barrier) AS
SELECT a.id, a.user_id, a."timestamp" AS event_at, a.activity, (a.actor_id IS NOT NULL) AS has_actor
FROM public.users_useridentityactivitylog a;

-- OTP requests with a hashed recipient
CREATE VIEW atlas_ro.otp_request WITH (security_barrier) AS
SELECT t.id, t.created_on, t.source, t.auth_type, t.language, t.email_delivery, t.sms_delivery, v.is_valid,
       HK(coalesce(lower(btrim(nullif(t.email,''))), PHONE(t.phone_number))) AS recipient_key,
       CASE WHEN coalesce(t.phone_number,'') = '' THEN 'email'
            WHEN t.phone_number LIKE '+966%' THEN 'SA' WHEN t.phone_number LIKE '+971%' THEN 'AE'
            WHEN t.phone_number ~ '^\+(974|965|973|968)' THEN 'GCC_OTHER' WHEN t.phone_number LIKE '+91%' THEN 'IN'
            WHEN t.phone_number LIKE '+1%' THEN 'US_CA' WHEN t.phone_number LIKE '+44%' THEN 'GB'
            WHEN t.phone_number LIKE '+7%' THEN 'RU_KZ' ELSE 'OTHER' END AS dest_bucket,
       (EXISTS (SELECT 1 FROM public.users_user u WHERE t.phone_number <> '' AND u.phone_number = t.phone_number)
        OR EXISTS (SELECT 1 FROM public.users_user u WHERE t.email <> '' AND lower(u.email) = lower(t.email))) AS recipient_registered_now
        -- needs: CREATE INDEX CONCURRENTLY ON public.users_user (lower(email)); on the primary (an unindexed lower(email) scan timed out at 20 s in profiling)
FROM public.notifications_twofactorauth t JOIN public.notifications_twofactorauthverification v ON v.reference_id_id = t.id;

-- tokens: derived geo/device only
CREATE VIEW atlas_ro.login_token WITH (security_barrier) AS
SELECT k.id, k.user_id, k.created_on, k.expires_at, k.user_platform,
       k.request_meta->>'COUNTRY' AS login_country,
       k.request_meta->'OS_TYPE'->>'name' AS os_family,
       (k.request_meta->>'IS_BOT')::boolean AS is_bot,
       HK(btrim(k.device_signature)) AS device_key
FROM public.users_cognitoissuedtokens k;                   -- jti, token_hash, raw request_meta excluded

-- black/white list entries without values or remarks
CREATE VIEW atlas_ro.list_entry WITH (security_barrier) AS
SELECT 'black' AS list, b.id, b.type, b.source, b.is_removed, b.is_guest, b.created_on, b.modified_on, b.created_by_id,
       CASE b.type WHEN 'user_email'       THEN HK(nullif(lower(btrim(b.value)),''))
                   WHEN 'user_domain'      THEN HK(nullif(lower(btrim(b.value)),''))
                   WHEN 'user_mobile_no'   THEN HK(PHONE(b.value))
                   WHEN 'user_device_id'   THEN HK(btrim(b.value))       -- case preserved: equals login_token.device_key
                   WHEN 'user_ip'          THEN HK(btrim(b.value))
                   WHEN 'sms_country_code' THEN HK(btrim(b.value))
                   END AS value_key,                                     -- any other type: NULL (section 2)
       CASE WHEN b.type = 'sms_country_code' THEN upper(b.value) END AS country_code,
       CASE WHEN coalesce(b.remarks,'') = '' THEN 'none' WHEN b.remarks ILIKE '%usercheck%' THEN 'rule_usercheck'
            WHEN b.remarks ILIKE '%dynamicemail%' OR b.remarks ILIKE '%dynamic email%' THEN 'rule_dyn_email'
            WHEN b.remarks ILIKE '%dynamicdomain%' OR b.remarks ILIKE '%dynamic domain%' THEN 'rule_dyn_domain'
            WHEN b.remarks ILIKE '%maximum login%' THEN 'rule_max_login' ELSE 'other' END AS remark_class,
       (b.reference_id ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$') AS ref_is_uuid,
       CASE WHEN b.reference_id ~* '^[0-9a-f-]{36}$' THEN HK(nullif(lower(btrim(b.reference_id)),'')) END AS ref_user_key
FROM public.core_blacklisteduserdetail b
UNION ALL
SELECT 'white', w.id, w.type, w.source, w.is_removed, NULL, w.created_on, w.modified_on, w.created_by_id,
       CASE w.type WHEN 'user_email'       THEN HK(nullif(lower(btrim(w.value)),''))
                   WHEN 'user_domain'      THEN HK(nullif(lower(btrim(w.value)),''))
                   WHEN 'user_mobile_no'   THEN HK(PHONE(w.value))
                   WHEN 'user_device_id'   THEN HK(btrim(w.value))
                   WHEN 'user_ip'          THEN HK(btrim(w.value))
                   WHEN 'sms_country_code' THEN HK(btrim(w.value))
                   END,                                                  -- same CASE as the black list, so V10 and conflicts match
       CASE WHEN w.type = 'sms_country_code' THEN upper(w.value) END, 'n/a', NULL, NULL
FROM public.core_whitelisteduserdetail w;

-- Kafka consumer events: shape and keys only, no payload values
CREATE VIEW atlas_ro.fraud_event_in WITH (security_barrier) AS
SELECT c.id, c.service_name, c.data->>'event_type' AS event_type, c.status, c.start_timestamp, c.completed_timestamp,
       (c.data->'data' ? 'reference_id') AS has_reference_id, (c.data->'data' ? 'mark_as_fraud') AS has_mark_as_fraud,
       (c.data->'data' ? 'guest_id') AS has_guest_id,
       EXISTS (SELECT 1 FROM public.users_user u WHERE u.username = c.data->'data'->>'guest_id') AS guest_id_is_username,
       (coalesce(c.error_data::text,'') NOT IN ('', '""', '{}', 'null')) AS has_error
FROM public.kafka_clients_blacklistuserconsumerdatalog c;
```

**Notes:**

- `HK(<norm(x)>)` and `PHONE(x)` are macros, not functions. **Do not expand them by hand:** run the Appendix A generator, which inlines the section 2 expression at every occurrence, writes one file per database and fails if any macro is left. Macros rather than a helper function are deliberate: a helper function would need EXECUTE for the reader, and the reader could then hash dictionary guesses. Inlined, the key is read with the view owner's rights only.
- The column paths `request_meta->'OS_TYPE'->>'name'` and `data->'data'` were used in profiling queries. Please confirm them against a few rows before creating the views.
- Soft-deleted rows hold encrypted email and phone (REPORT.md G6). The views never hash those rows.

**Justification:**

| View | Unlocks |
|---|---|
| `user_profile` | AF-02, AF-04, AF-10 (`is_promo_blocked_domain`), AF-11, AF-16, AF-19, AF-23, AF-91. Birthdays exposed as day and month only. The promo-blocked flag is computed in-DB with the section 2 label rule, so the suppression needs no key join at all. |
| `identity_keys` | The users side of the sender-to-recipient join (AF-45, AF-71), with no raw contact data |
| `gift_claim` | AF-02, AF-03, AF-08, AF-09, AF-14, AF-22, AF-88, AF-89, AF-90, AF-97. The claim email and domain become keys; org clusters become opaque ids. Email activity types only, so every key uses the email normalisation. |
| `identity_event` | The `identity_event` entity (REPORT.md section 7), phone-update counts, swap cycles for AF-97. No comment-derived column. |
| `otp_request` | AF-01, AF-03, AF-05, AF-25–AF-29; H51, H55, H74, H75, H77. The in-DB PII join moves out of atlas definitions. |
| `login_token` | AF-05, AF-18, AF-28, AF-40, AF-92. Device sharing via keyed hash. |
| `list_entry` | AF-06, AF-10, AF-13, AF-21; H74. Blacklist values and remarks never leave the DB. Value keys follow the per-type rule of section 2, so a device entry matches `login_token.device_key` and a mobile entry matches `identity_keys.phone_key`. |
| `fraud_event_in` | AF-07, including the 1,298 stuck events, split guest / registered |

## 3.2 Config and reference data: enumerated columns, not whole tables

The earlier draft kept ten tables readable as whole tables. A catalog review (`pg_attribute`, 2026-09-29) shows that three of them are not free of personal or sensitive data: `users_migratedtransactionlog` holds `user_reference` (the account UUID) and `legacy_auth_code`, `users_promotionaldomainblacklist.domain` names employers, and the template tables carry a `template_data` jsonb body. `core_captchaconfigurations` holds no key or secret column today (`id, created_on, modified_on, action, threshold, enabled, captcha_version, created_by_id, modified_by_id`), but it is still granted by column so that a key column added later stays closed. Every table in this section is therefore granted by column or through a view.

```sql
GRANT SELECT (id, created_on, modified_on, action, threshold, enabled, captcha_version) ON public.core_captchaconfigurations TO atlas_reader;
GRANT SELECT (id, created_on, modified_on, message_type, sms_communication, whatsapp_communication, email_communication)
  ON public.notifications_communicationchannelconfig TO atlas_reader;
GRANT SELECT (id, created_on, modified_on, channel, countries, country_codes) ON public.notifications_communicationcountries TO atlas_reader;
GRANT SELECT (id, created_on, modified_on, message_type, channel, country_code, direct_delivery, resend_delivery)
  ON public.notifications_communicationcountryconfigs TO atlas_reader;
GRANT SELECT (id, created_on, modified_on, email_type, template_code, is_active, language_id)
  ON public.notifications_emailtemplateconfiguration TO atlas_reader;               -- template_data excluded
GRANT SELECT (id, created_on, modified_on, whatsapp_type, template_code, language, category, is_active)
  ON public.notifications_whatsapptemplateconfiguration TO atlas_reader;            -- template_data excluded
GRANT SELECT (id, created_on, modified_on, name, code, code_three_letter, text_direction, is_default, is_active) ON public.core_language TO atlas_reader;
GRANT SELECT (id, app_label, model) ON public.django_content_type TO atlas_reader;

-- legacy state without the legacy auth code or the raw account UUID
CREATE VIEW atlas_ro.legacy_migration WITH (security_barrier) AS
SELECT m.id, HK(nullif(lower(btrim(m.user_reference)),'')) AS user_key, m.creation, m.request_status, m.created_on, m.modified_on
FROM public.users_migratedtransactionlog m;                                      -- legacy_auth_code excluded

-- promo-blocked domains as keys only (domain names identify employers)
-- entries are uppercase labels with no TLD (e.g. 'ACME'), so the key uses the section 2 LABEL() rule, not the full-domain rule
CREATE VIEW atlas_ro.promo_blocked_domain WITH (security_barrier) AS
SELECT d.id, HK(nullif(lower(split_part(ltrim(btrim(d.domain),'@'),'.',1)),'')) AS domain_label_key,
       d.is_active, d.created_on, d.modified_on
FROM public.users_promotionaldomainblacklist d;   -- joins user_profile.email_domain_label_key only
```

Also keep these column grants (written as SQL so that the Appendix A generator includes them):

```sql
GRANT SELECT (id, action_time, action_flag, content_type_id, object_id, user_id) ON public.django_admin_log TO atlas_reader;
GRANT SELECT (id, event_id, status, created_on, modified_on) ON public.kafka_clients_blacklistuserproducerlog TO atlas_reader;
GRANT SELECT (id, status, start_timestamp, completed_timestamp) ON public.kafka_clients_serviceinternalrefetchconsumerdatalog TO atlas_reader;
```

| Item | Unlocks |
|---|---|
| Channel, country and template column grants | OTP routing (AF-29), template coverage (AF-42) |
| `legacy_migration` | Legacy state dimension and shell rules (AF-04, AF-11, AF-12), H14, H59 |
| `promo_blocked_domain` | Suppression (AF-10) and its per-entry counts. It is matched to `user_profile.email_domain_label_key`, which uses the same label rule, **never** to `email_domain_key` (a full-domain key cannot equal a bare-label key, so that join would silently return 0 of the 5,544 users). AF-10 reads `user_profile.is_promo_blocked_domain` directly; test V15 checks both paths |

Site-configuration flags are exposed through a flags-only view:

```sql
CREATE VIEW atlas_ro.control_flags WITH (security_barrier) AS
SELECT (config->'disposable_usercheck'->>'disposable_usercheck_enabled')::text AS disposable_usercheck_enabled,
       (config->'disposable_email_manager'->>'disposable_email_manager_enabled')::text AS disposable_email_manager_enabled,
       (config->'dynamic_throttle_manager'->'dynamic_throttle_config'->>'enable_dynamic_throttle_manager') AS dynamic_throttle_enabled,
       (SELECT count(*) FROM jsonb_object_keys(config->'dynamic_throttle_manager'->'dynamic_throttle_config'->'enabled_countries')) AS geo_override_countries,
       (config->'secondary_identity'->>'secondary_identity_per_account') AS secondary_identity_per_account,
       modified_on
FROM public.core_siteconfiguration;   -- never automation_accounts; confirm key paths with the owning team
```

## 3.3 Least-privilege revoke (phase 2, after atlas has moved to the views)

The atlas role can read credentials today. It should never have been able to.

**Step 1: find where the privilege comes from.** A revoke on `<emapi_login_role>` does nothing if the privilege arrives through a group role, `pg_read_all_data`, ownership or `PUBLIC`. A catalog check on 2026-09-29 (STRUCTURAL) found:

- `relacl` on `users_user` and `core_remoteurlconfig` is `{postgres=arwdDxt/postgres, <emapi_login_role>=r/postgres}`: a **direct** table grant to the login role;
- `<emapi_login_role>` is a member of **no** role (`pg_auth_members` is empty for it), is not a superuser, and owns nothing (tables and database are owned by `postgres`);
- there are no default privileges (`pg_default_acl` is empty);
- schema `public` grants `USAGE` and `CREATE` to `PUBLIC` (`=UC/postgres`). This is not a read path, but please `REVOKE CREATE ON SCHEMA public FROM PUBLIC` while you are there.

The DBA should repeat the check on the primary just before the revoke, because the replica reflects the primary's catalog:

```sql
SELECT r.rolname FROM pg_auth_members m JOIN pg_roles r ON r.oid = m.roleid
 WHERE m.member = '<emapi_login_role>'::regrole;                                     -- expect no rows (atlas_reader after section 1)
SELECT c.relname, c.relacl FROM pg_class c
 WHERE c.relnamespace = 'public'::regnamespace AND c.relkind IN ('r','v','m','p')
   AND c.relacl::text LIKE '%<emapi_login_role>=%';                                 -- the direct grants to revoke
SELECT c.relname FROM pg_class c
 WHERE c.relnamespace = 'public'::regnamespace AND c.relkind IN ('r','p')
   AND (c.relacl IS NULL OR c.relacl::text ~ '(^|[{,])=r');                          -- anything readable by PUBLIC
```

**Step 2: revoke.**

```sql
-- run once atlas definitions read only atlas_ro.* (we will confirm the cut-over date)
REVOKE SELECT ON public.core_remoteurlconfig, public.users_passwordhistory, public.users_userauthlegacysignaturepreference,
  public.otp_totp_totpdevice, public.otp_static_staticdevice, public.otp_static_statictoken, public.two_factor_phonedevice,
  public.users_webauthncredentialmodel, public.django_session, public.auth_group, public.auth_group_permissions,
  public.auth_permission, public.users_user_groups, public.users_user_user_permissions, public.users_tokenrotatedusers
FROM <emapi_login_role>;
REVOKE SELECT ON public.users_user, public.users_secondaryuseridentity, public.users_useridentityactivitylog,
  public.users_cognitoissuedtokens, public.notifications_twofactorauth, public.notifications_twofactorauthverification,
  public.core_blacklisteduserdetail, public.core_whitelisteduserdetail, public.kafka_clients_blacklistuserconsumerdatalog,
  public.kafka_clients_blacklistuserproducerlog, public.kafka_clients_serviceinternalrefetchconsumerdatalog,
  public.core_siteconfiguration, public.django_admin_log, public.users_migratedtransactionlog,
  public.users_promotionaldomainblacklist, public.core_captchaconfigurations, public.notifications_communicationchannelconfig,
  public.notifications_communicationcountries, public.notifications_communicationcountryconfigs,
  public.notifications_emailtemplateconfiguration, public.notifications_whatsapptemplateconfiguration, public.core_language,
  public.django_content_type, public.django_migrations, public.django_site
FROM <emapi_login_role>;
-- the two statements name all 40 users-DB tables (15 + 25); atlas needs neither django_migrations nor django_site
-- then apply the section 3.2 column grants and views to atlas_reader
```

**Step 3: verify.** Re-run `has_table_privilege('<emapi_login_role>', '<table>', 'SELECT')` over all 40 tables (the Step 2 lists name each of them once; a count of 40 distinct names is the first check). The expected result is `false` for every table, with access only through `atlas_ro.*` and the section 3.2 column grants (`has_column_privilege` returns `true` for those columns only).

**Justification:** these tables hold `api_key` and `api_secret`, password hashes, TOTP keys, session data and raw email, phone and IP. None of them is needed once the section 3.1 views exist.

# 4. ygag_ecom_orders_db (tiers 1, 2 and 5)

**Column-grant lists** come from `pg_attribute` on 2026-09-29 and are complete for that date.

**Always excluded:**

- `order_order`: `user_email, guest_email, user_name, user_phone, owner, session_id, transaction_url, extra` (`user_gender` is exposed only as a bucket in the view). `guest_id` is exposed only as a keyed `guest_key` plus a `has_guest_id` flag (view `order_flags`).
- **Gateway, order, invoice and loyalty references** are never granted raw, in any table: `order_order.order_reference, payment_order_reference, transaction_id` and the customer-facing order `number`; `order_line.line_reference` and `basket_line.line_reference` (UNIQUE line references, listed as order reference keys in the cross-db profile); the tip payment references `user_tip_tip.reference_id` and `user_tip_invoice.reference_id`; youpay `transaction_id, payment_reference, order_reference, invoice_id, qitaf_request_id`; `kafka_giftcreationlog.order_id`; `personalization_detail.order_reference_id, cart_reference_id`. They are not personal data on their own, but each one links a row to records outside atlas's control: the YouPay gateway and settlement DB, finance exports and, for `qitaf_request_id`, STC Qitaf loyalty requests tied to a mobile number (orders-integrations and orders-customer-catalog profiles). Atlas needs them only as **join keys**, so each is exposed as a keyed hash (`btrim`, case preserved; section 2) under a `*_key` name, and `qitaf_request_id` only as a presence flag. The keys are computed the same way on both sides, so the youpay → order and gift-log → order joins still work.
- Basket: `user, user_email, user_name, user_phone, user_gender, note, extra`. `guest_id` only as `guest_key` (view `basket_guest`).
- Guest identity: raw `users_guestuser.id` and `users_mergeduser.guest_id` are not granted; every guest table exposes the same keyed `guest_key`, so guest joins still work.
- Recipient `phone_number` and `email_address`.
- `sender_name` and `personal_data_ref`.
- `partner_line_reference` and `partner_line_notes`.
- Card fields: `card_bin, card_last4, name_on_card`.
- youpay customer fields, `*_url`, and the jsonb columns `order_history, order_items, udf1, brand_*`.
- Gift log: `payload, failure, created_gift_details`.
- Blacklist: `value, reference_id`.
- `promo_code`, and the offer `code` (`offer_plusoffer.code`, `order_line.offer_code`): keyed only until the DBA confirms it is not a redeemable code (test V16).
- `django_admin_log.object_repr` and `change_message`.
- Credentials: `youpayclient_clientconfiguration`, `core_remoteurlconfig.api_key/api_secret/url`, `webhooks_webhookconfig.webhook_key/sender_ip`.

## 4.1 Tier 1: identity and orders

```sql
-- identity join (decisive test V2: user_key here = user_key in users atlas_ro.user_profile)
CREATE VIEW atlas_ro.user_profile WITH (security_barrier) AS
SELECT p.user_id, HK(nullif(lower(btrim(p.cognito_id)),'')) AS user_key, p.trusted_user, p.is_deleted, p.is_enabled,
       p.is_email_verified, p.is_phone_number_verified, p.country_of_residence, p.created_on
FROM public.users_userprofile p;
GRANT SELECT (id, date_joined, is_active, is_staff, is_superuser) ON public.users_customuser TO atlas_reader;

-- orders: column grant (49 non-PII columns) for TABLESAMPLE, plus a view with PII-presence flags, the keyed guest id and keyed references
GRANT SELECT (id, currency, total_incl_tax, total_excl_tax, shipping_incl_tax, shipping_excl_tax, shipping_method, shipping_code,
  status, date_placed, basket_id, billing_address_id, shipping_address_id, site_id, user_id, gateway_currency, is_visited,
  platform, region_id, total_base_amount, total_base_amount_in_gateway_currency, total_extra_charge, total_extra_charge_in_gateway_currency,
  total_incl_tax_in_gateway_currency, total_tax_amount, total_tax_in_gateway_currency, created_by_id, date_updated, modified_by_id,
  language_code, process_fee, process_fee_in_gateway_currency, quantity, vat_on_process_fee_in_gateway_currency,
  placed_country_id, total_incl_tax_before_payment, total_incl_tax_in_gateway_currency_before_payment,
  total_tax_amount_before_payment, total_tax_in_gateway_currency_before_payment, gift_create_event_triggered,
  conversion_rate_gateway_currency, conversion_rate_reporting_currency, total_incl_tax_before_payment_in_reporting_currency,
  total_extra_charge_before_payment, total_extra_charge_in_gateway_currency_before_pay, sold_date, shipping_tax_code,
  language_id, redemption_partner)
  ON public.order_order TO atlas_reader;   -- guest_id, number, order_reference, payment_order_reference, transaction_id NOT granted raw: see order_flags
CREATE VIEW atlas_ro.order_flags WITH (security_barrier) AS
SELECT o.id AS order_id,
       (o.user_email <> '') AS has_user_email, (o.guest_email <> '') AS has_guest_email, (o.user_phone <> '') AS has_user_phone,
       (o.session_id IS NOT NULL AND o.session_id <> '') AS has_session_id,
       CASE WHEN lower(o.user_gender) IN ('male','female') THEN lower(o.user_gender) ELSE 'unknown' END AS sender_gender,
       CASE WHEN jsonb_typeof(o.extra) = 'object' THEN ARRAY(SELECT jsonb_object_keys(o.extra) ORDER BY 1) END AS extra_keys,
       (o.guest_id IS NOT NULL) AS has_guest_id,
       HK(o.guest_id::text) AS guest_key,           -- bigint FK to users_guestuser.id: text cast, no lower/btrim (section 2)
       HK(btrim(o.order_reference)) AS order_ref_key,                  -- = youpay_derived.order_ref_key
       HK(btrim(o.payment_order_reference)) AS payment_order_ref_key,  -- = youpay_derived.payment_ref_key
       HK(btrim(o.transaction_id)) AS transaction_key,                 -- = youpay_derived.transaction_key
       HK(o.id::text) AS order_id_key, HK(btrim(o.number)) AS order_number_key   -- for test V4 against gift_issuance_event.order_id_key
FROM public.order_order o;

GRANT SELECT (id, partner_name, partner_sku, title, upc, quantity, line_price_incl_tax, line_price_excl_tax,
  line_price_before_discounts_incl_tax, line_price_before_discounts_excl_tax, unit_price_incl_tax, unit_price_excl_tax, status,
  order_id, partner_id, product_id, stockrecord_id, created_by_id, created_on, modified_by_id, modified_on,
  instant_activated_date, is_instant_activated, tax_code, is_offer_applied, purchase_origin, is_white_label)
  ON public.order_line TO atlas_reader;   -- line_reference and offer_code: keys only, below
CREATE VIEW atlas_ro.order_line_keys WITH (security_barrier) AS
SELECT l.id AS line_id, l.order_id,
       HK(btrim(l.line_reference)) AS line_ref_key,                     -- = basket_line_keys.line_ref_key if the reference carries over
       (coalesce(l.offer_code,'') <> '') AS has_offer_code,
       HK(btrim(nullif(l.offer_code,''))) AS offer_code_key             -- = plus_offer.offer_code_key (section 4.3, 5, 6)
FROM public.order_line l;

GRANT SELECT (id, created_on, modified_on, denomination_currency_id, line_id, created_by_id, denomination_in_cart_currency,
  denomination_in_denomination_currency, denomination_in_reporting_currency, extra_charge_in_cart_currency,
  extra_charge_in_denomination_currency, extra_charge_in_reporting_currency, is_buy_for_self, is_different_currency_denomination,
  modified_by_id, price_in_cart_currency, price_in_denomination_currency, price_in_reporting_currency, reporting_currency,
  tax_rate_in_cart_currency, tax_rate_in_denomination_currency, tax_rate_in_reporting_currency, conversion_rate,
  payment_gateway_charge, conversion_rate_cart_currency, delivery_method, extra_charge_in_denomination_currency_before_pay,
  price_in_denomination_currency_before_pay, tax_rate_in_denomination_currency_before_pay, brand_skin, processing_fee_rate,
  processing_fee_vat_in_cart_currency, processing_fee_vat_in_reporting_currency, processing_fee_vat_rate,
  processing_fee_in_cart_currency, processing_fee_in_reporting_currency)
  ON public.order_orderlinequantitydetail TO atlas_reader;
```

| Item | Unlocks | Why this form |
|---|---|---|
| `atlas_ro.user_profile` | Every cross-DB user join (test V2). Recipient to buyer (AF-45), leakage (AF-55). | `cognito_id` is exposed only as a keyed hash |
| `order_order` columns (49) + `order_flags` | Retention (AF-46), first purchase (AF-47), guest orders (AF-59, H19, H68), H01, H08, H12, H14, H29, H30 (H28 also needs tiers 2 and 3, so it is listed under tier 3) | The 9 PII columns, raw `guest_id`, the three gateway references and the customer-facing order `number` stay out (the number is what a customer quotes to support, so it is exposed only as `order_flags.order_number_key`); presence flags answer "is it populated?", and the references are keyed join keys. `guest_id` is a bigint FK to `users_guestuser.id` (orders-funnel profile), not a username; the UUID-in-`guest_id` defect (REPORT.md E3) is in the orders → users Kafka payload, which users `fraud_event_in` already exposes only as flags. It is still keyed here, so that no guest table exposes a raw guest identifier and every guest join uses one `guest_key`. |
| `order_line` columns + `order_line_keys` | Brand sales on `upc` (AF-53), offer redemption (`offer_code_key` joined to `plus_offer.offer_code_key`), surface attribution (AF-36) | Partner references stay excluded until their content is reviewed; `line_reference` and `offer_code` only as keys, so no order reference or possibly redeemable code leaves the DB |
| `order_orderlinequantitydetail` columns | Revenue in reporting currency, buy-for-self (H12), cross-currency (AF-75) | `sender_name` and `personal_data_ref` excluded |
| `users_customuser` columns | Staff/service accounts behind `created_by_id` | No email, username or password |

## 4.2 Tier 2: personalisation, guests, payments, gift issuance

```sql
-- occasion lines with keyed recipient (sender -> recipient edge; must match users atlas_ro.identity_keys)
GRANT SELECT (id, created_on, modified_on, delivery_time_zone, delivery_type, delivery_date, delivery_time, created_by_id, line_id,
  modified_by_id, greeting_code, occasion_code, is_reminder_added) ON public.order_orderlinepersonalisedetail TO atlas_reader;
CREATE VIEW atlas_ro.occasion_line WITH (security_barrier) AS
SELECT d.id, d.line_id, d.created_on, d.occasion_code, d.greeting_code, d.delivery_type, d.delivery_date, d.delivery_time,
       d.delivery_time_zone, d.is_reminder_added,
       (coalesce(d.email_address,'') <> '') AS has_recipient_email, (coalesce(d.phone_number,'') <> '') AS has_recipient_phone,
       HK(nullif(lower(btrim(nullif(d.email_address,''))),'')) AS recipient_email_key,
       HK(PHONE(d.phone_number)) AS recipient_phone_key,
       CASE WHEN coalesce(d.phone_number,'') = '' THEN NULL
            WHEN btrim(d.phone_number) LIKE '+%' OR regexp_replace(d.phone_number,'\D','','g') LIKE '00%' THEN 'international'
            WHEN regexp_replace(d.phone_number,'\D','','g') ~ '^0?5[0-9]{8}$' THEN 'national_mobile'
            WHEN regexp_replace(d.phone_number,'\D','','g') ~ '^(971|966|974|965|973|968)[0-9]{7,9}$' THEN 'international_no_plus'
            ELSE 'other' END AS recipient_phone_format,
       CASE WHEN btrim(d.phone_number) NOT LIKE '+%' AND regexp_replace(d.phone_number,'\D','','g') ~ '^0?5[0-9]{8}$'
            THEN HK('971' || right(regexp_replace(d.phone_number,'\D','','g'), 9)) END AS recipient_phone_key_if_ae,
       CASE WHEN btrim(d.phone_number) NOT LIKE '+%' AND regexp_replace(d.phone_number,'\D','','g') ~ '^0?5[0-9]{8}$'
            THEN HK('966' || right(regexp_replace(d.phone_number,'\D','','g'), 9)) END AS recipient_phone_key_if_sa
FROM public.order_orderlinepersonalisedetail d;

GRANT SELECT (id, created_on, modified_on, delivery_time_zone, delivery_type, delivery_date, delivery_time, created_by_id, line_id,
  modified_by_id, greeting_code, occasion_code, is_reminder_added) ON public.basket_basketpersonalisedetail TO atlas_reader;
CREATE VIEW atlas_ro.basket_occasion_line WITH (security_barrier) AS
SELECT d.id, d.line_id, d.created_on, d.occasion_code, d.greeting_code, d.delivery_type, d.delivery_date, d.delivery_time,
       d.delivery_time_zone, d.is_reminder_added,
       (coalesce(d.email_address,'') <> '') AS has_recipient_email, (coalesce(d.phone_number,'') <> '') AS has_recipient_phone,
       HK(nullif(lower(btrim(nullif(d.email_address,''))),'')) AS recipient_email_key,
       HK(PHONE(d.phone_number)) AS recipient_phone_key
FROM public.basket_basketpersonalisedetail d;   -- basket side: no national-format candidates (not used for recipient matching)

-- guests and merges (V8 guest-token test + guest funnel)
-- users_guestuser: no raw id, so a guest row joins only through the same keyed guest_key as order_flags / basket_guest
CREATE VIEW atlas_ro.guest_user WITH (security_barrier) AS
SELECT HK(g.id::text) AS guest_key, g.created_on, g.modified_on, g.platform, g.last_accessed, g.is_active
FROM public.users_guestuser g;
CREATE VIEW atlas_ro.guest_keys WITH (security_barrier) AS
SELECT HK(g.id::text) AS guest_key, HK(nullif(lower(btrim(g.username)),'')) AS guest_username_key, HK(btrim(g.session_id)) AS guest_session_key,
       HK(nullif(lower(btrim(g.email)),'')) AS guest_email_key
FROM public.users_guestuser g;
CREATE VIEW atlas_ro.guest_merge WITH (security_barrier) AS
SELECT m.id, m.created_on, m.modified_on, HK(m.guest_id::text) AS guest_key, m.user_id   -- guest_id bigint: text cast only
FROM public.users_mergeduser m;
GRANT SELECT (id, created_on, modified_on, guest_basket_id, user_basket_id) ON public.basket_mergedbasket TO atlas_reader;

-- payments: non-PII columns + derived response class; response_summary never raw
-- err_class maps free text to a CLOSED enum. It never returns any part of its input,
-- so cardholder or recipient names in a decline or error message cannot leak.
CREATE FUNCTION atlas_ro.err_class(t text) RETURNS text LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE
    WHEN t IS NULL OR btrim(t) = ''                                   THEN NULL
    WHEN t ~* '(insufficient|not enough|balance)'                     THEN 'insufficient_funds'
    WHEN t ~* '(3ds|3-d secure|authenticat|otp|challenge)'            THEN 'authentication_3ds'
    WHEN t ~* '(expired|expiry)'                                      THEN 'card_expired'
    WHEN t ~* '(invalid card|card number|cvv|cvc|luhn)'               THEN 'invalid_card'
    WHEN t ~* '(fraud|risk|blocked|blacklist|restricted)'             THEN 'risk_block'
    WHEN t ~* '(declin|do not honou?r|refused|rejected|not approved)' THEN 'declined'
    WHEN t ~* '(timeout|timed out|time-out)'                          THEN 'timeout'
    WHEN t ~* '(connection|network|unreachable|5\d\d|gateway)'      THEN 'network_or_gateway'
    WHEN t ~* '(duplicate|already exists|already processed)'          THEN 'duplicate'
    WHEN t ~* '(cancel)'                                              THEN 'cancelled'
    WHEN t ~* '(valid|required|missing|format|parse|schema)'          THEN 'validation'
    ELSE 'other' END $$;
GRANT EXECUTE ON FUNCTION atlas_ro.err_class(text) TO atlas_reader;
-- Before creating it, the DBA (not atlas) should run
--   SELECT atlas_ro.err_class(x), count(*) FROM <source column> GROUP BY 1
-- on a sample and tune the patterns so that 'other' stays small. The output set stays closed.

GRANT SELECT (id, created_on, modified_on, amount, base_amount,
  vat_amount, service_fee, processing_fee, paid_amount, gateway_charge, currency, cart_amount, cart_base_amount, "cart_VAT_amount",
  cart_service_fee, cart_currency, payment_gateway, payment_status, payment_method, payment_scheme, channel_code, platform, language,
  settlement_entity, approved, is_fraud, is_flagged, is_gcc_card, card_issuer_country, available_amount, payable_amount,
  redeemed_amount, point_program, loyalty_level, is_qitaf_enabled, point_collection_enabled, is_full_redemption,
  available_points, redeemed_points, earned_point)
  ON public.youpayclient_youpayclienttransactiondata TO atlas_reader;   -- the five gateway/loyalty references: keys only, below
CREATE VIEW atlas_ro.youpay_derived WITH (security_barrier) AS
SELECT y.id, atlas_ro.err_class(y.response_summary) AS response_class,
       (coalesce(y.verify_url,'') <> '') AS has_verify_url,                       -- 3DS proxy
       CASE WHEN jsonb_typeof(y.order_history) = 'array' THEN jsonb_array_length(y.order_history) END AS order_history_len,
       CASE WHEN jsonb_typeof(y.order_items) = 'array' THEN jsonb_array_length(y.order_items) END AS n_items,
       HK(btrim(y.order_reference)) AS order_ref_key,        -- joins order_flags.order_ref_key; dedup key for test V5
       HK(btrim(y.payment_reference)) AS payment_ref_key,    -- joins order_flags.payment_order_ref_key
       HK(btrim(y.transaction_id)) AS transaction_key,       -- joins order_flags.transaction_key
       HK(btrim(y.invoice_id)) AS invoice_key,               -- duplicate-invoice counts only
       (coalesce(y.qitaf_request_id,'') <> '') AS has_qitaf_request   -- presence only: Qitaf requests are tied to a mobile number
FROM public.youpayclient_youpayclienttransactiondata y;

GRANT SELECT (id, created_on, modified_on, payment_gateway, currency, is_fraud, is_flagged, payment_method, payment_scheme, is_gcc_card,
  processing_fee, card_issuer_country, paid_amount, created_by_id, modified_by_id, order_id, gateway_charge, payment_status,
  settlement_entity, exclude_instant_activation, point_collection_enabled, point_program)
  ON public.payment_paymentdetail TO atlas_reader;

-- gift issuance (PostgreSQL 16 IS JSON)
GRANT SELECT (id, created_on, modified_on, event_id, status) ON public.kafka_giftcreationlog TO atlas_reader;   -- order_id: key only
CREATE VIEW atlas_ro.gift_issuance_event WITH (security_barrier) AS
SELECT g.id, g.created_on, g.modified_on, g.event_id, g.status,
       HK(btrim(g.order_id::text)) AS order_id_key,    -- V4 decides which order_flags key it equals
       (g.error IS NOT NULL AND btrim(g.error) <> '') AS has_error, atlas_ro.err_class(g.error) AS error_class,
       (g.failure IS NOT NULL AND btrim(g.failure) <> '') AS has_failure, atlas_ro.err_class(g.failure) AS failure_class,
       CASE WHEN g.created_gift_details IS NOT NULL AND g.created_gift_details IS JSON ARRAY
            THEN jsonb_array_length(g.created_gift_details::jsonb) END AS gifts_created   -- count only, never content
FROM public.kafka_giftcreationlog g;

-- baskets (heavy: 3.05M rows, no date index) -> column grant for sampling + nightly materialized summary
GRANT SELECT (id, status, date_created, date_merged, date_submitted, owner_id, region_id, parent_id, platform, record_type,
  language_code, language_id) ON public.basket_basket TO atlas_reader;                -- guest_id NOT granted raw
CREATE VIEW atlas_ro.basket_guest WITH (security_barrier) AS
SELECT b.id AS basket_id, (b.guest_id IS NOT NULL) AS has_guest_id, HK(b.guest_id::text) AS guest_key
FROM public.basket_basket b;
GRANT SELECT (id, quantity, price_currency, price_excl_tax, price_incl_tax, date_created, basket_id, product_id,
  stockrecord_id, date_updated, parent_id, record_type, tax_code, purchase_origin, is_white_label) ON public.basket_line TO atlas_reader;
CREATE VIEW atlas_ro.basket_line_keys WITH (security_barrier) AS
SELECT l.id AS line_id, l.basket_id, HK(btrim(l.line_reference)) AS line_ref_key FROM public.basket_line l;   -- line_reference: key only
GRANT SELECT (id, created_on, modified_on, is_buy_for_self, denomination, denomination_currency_id, line_id, created_by_id,
  modified_by_id, delivery_method, brand_skin) ON public.basket_basketquantitydetail TO atlas_reader;
CREATE MATERIALIZED VIEW atlas_ro.basket_summary AS
SELECT b.id AS basket_id, date_trunc('week', b.date_created) AS created_week, b.platform, b.region_id,
       (b.guest_id IS NOT NULL) AS is_guest, b.status, count(l.id) AS n_lines, count(DISTINCT l.price_currency) AS n_currencies,
       CASE WHEN count(DISTINCT l.price_currency) = 1 THEN sum(l.price_incl_tax * l.quantity) END AS value_single_currency,
       min(l.price_currency) AS currency_if_single,
       EXISTS (SELECT 1 FROM public.order_order o WHERE o.basket_id = b.id) AS has_order
FROM public.basket_basket b LEFT JOIN public.basket_line l ON l.basket_id = b.id
GROUP BY b.id, b.date_created, b.platform, b.region_id, b.guest_id, b.status;
-- REFRESH MATERIALIZED VIEW atlas_ro.basket_summary; nightly, off-peak, on the primary
```

| Item | Unlocks | Why this form |
|---|---|---|
| `occasion_line` (+ basket twin) | Anniversary reminder (AF-50), occasion mix (AF-33), k-factor (AF-71), merchandising calendar (AF-96), H13, H16, H47, H49, H63, H67, H69 | The recipient is known only as a keyed hash that matches the users-side keys |

**Recipient phone format.** Users-side phones are stored in international form (`+971…`, `+966…`), so `identity_keys.phone_key` is an international key. A recipient phone typed in national form (`05x xxx xxxx`) cannot be canonicalised without knowing its country, and AE and SA mobiles share the `05` + 8-digit shape. The view therefore exposes, for national-format mobiles only, **two candidate keys** (`_if_ae` with prefix 971, `_if_sa` with 966) and a `recipient_phone_format` bucket:

- a recipient join matches `recipient_phone_key` first, then the candidate for the order's store country (`order_order.region_id`), and never both;
- phone matches on `other`-format numbers are not attempted;
- the expected loss is measured, not assumed: test V13 (section 9) reports the share of recipient phones by format and the match rate per format, and every recipient metric that uses phone matching (AF-45, AF-71, H13, H49, H67) carries that rate in its provenance chip. Email matching is unaffected. Tests V2 and V8 use user, guest, session and email keys only, so they carry no phone match loss.
| `guest_user`, `guest_keys`, `guest_merge`, `basket_guest`; `basket_mergedbasket` columns | Guest funnel (AF-59), H19, H68, V8 (the 902 stuck guest events) | Guest email, username, session **and the guest id itself** exposed only as keys; every guest view carries the same `guest_key` = HK(`guest_id::text`), so the order, basket, merge and guest rows still join |
| youpay columns + `youpay_derived`; paymentdetail columns | Payment declines (AF-48), fraud flags (H22, H28, H31, H32), points and Qitaf approval (H54), cross-currency declines (H70), H77, dedup test V5 | Decline text mapped to a closed class enum; no input text survives. No card or customer data. Gateway, invoice and order references only as keys; Qitaf request only as a flag. |
| `gift_issuance_event` | Gift issuance health (AF-51), order drill-down (AF-76), H41, test V4 | Gift codes and payloads never exposed; the gift count is derived; error text only as a closed class |
| Basket columns + `basket_line_keys` + `basket_summary` | Abandoned basket (AF-49), purchase funnel (AF-69), checkout health (AF-93), surface attribution (AF-36, `basket_line.purchase_origin`), denomination anchoring (AF-60), H20, H21 | Removes 1.6 GB live scans; the denominator is non-empty baskets |

## 4.3 Tier 1 companions: catalog, offers, checkout config (no PII)

These tables hold no user-linked rows and no customer-written text (catalog check on 2026-09-29), so they ship with tier 1. They are named one by one; per section 0 they do not fail closed on new columns, and check V12 covers that. `users_mergeduser` holds a guest id, so it is exposed only through the keyed `guest_merge` view; `basket_mergedbasket` holds local basket ids only and is granted by column (section 4.2).

```sql
GRANT SELECT ON public.catalogue_product, public.catalogue_store, public.catalogue_category, public.catalogue_productcategory,
  public.catalogue_productdenomination, public.catalogue_productdenominationrange, public.catalogue_producthandlingfee,
  public.partner_partner, public.offer_plusoffer_happy_cards, public.offer_productoffer,
  public.offer_productoffer_happy_cards, public.analytics_recommendedbrand, public.core_currency, public.core_basecurrency,
  -- DBA CHECK before running: confirm core_siteconfig, brands_retailers and company_company carry no contact or secret
  -- columns; if any do, grant those tables by column like core_siteconfiguration.
  public.core_currencyexchangerate, public.core_currencybasketlimit, public.core_language, public.core_siteconfig,
  public.core_unsupportedcountry, public.payment_paymentmethod, public.order_giftactivationconfig,
  public.order_giftactivationconfig_enabled_country, public.order_orderplacedcountry, public.address_country,
  public.address_countryvat, public.order_orderstatuschange, public.order_lineprice, public.django_content_type,
  public.django_migrations TO atlas_reader;
GRANT SELECT (id, created_on, modified_on, status, brand_id, created_by_id, modified_by_id, offer_id) ON public.offer_offerpromocode TO atlas_reader;
CREATE VIEW atlas_ro.offer_promocode_key WITH (security_barrier) AS
SELECT id, offer_id, status, HK(btrim(promo_code)) AS promo_code_key FROM public.offer_offerpromocode;

-- Plus offers: the offer code may be a code customers type at checkout (is_generic_promo_code), so it is keyed, not granted.
-- Enumerated columns from the catalog profile (orders-customer-catalog Q24); the DBA confirms the names with
--   SELECT attname FROM pg_attribute WHERE attrelid = 'public.offer_plusoffer'::regclass AND attnum > 0 AND NOT attisdropped;
-- A wrong name fails the generated transaction (fail closed). Content, terms and sponsor columns stay closed until reviewed.
CREATE VIEW atlas_ro.plus_offer WITH (security_barrier) AS
SELECT p.id, HK(btrim(p.code)) AS offer_code_key, p.name, p.start_date, p.end_date, p.is_active, p.brand_id, p.country_id,
       p.offer_mode, p.offer_type, p.offer_channel, p.funding_method, p.funded_by, p.reason_code,
       p.percentage, p.fixed_amount, p.has_min_max_restriction, p.minimum_amount, p.maximum_amount,
       p.is_budget_available, p.budget_type, p.budget_amount, p.budget_threshold, p.has_budget_exceeded,
       p.is_generic_promo_code, p.is_unique_promo_code, p.promo_code_end_date, p.promo_code_threshold,
       p.featured_order, p.brand_tile_order_number, p.offer_order_number
FROM public.offer_plusoffer p;   -- raw code never exposed until test V16 confirms it is not redeemable
```

**Justification:**

- These tables drive brand performance (AF-53, via `catalogue_product.upc`), checkout-gate diagnostics (AF-70), denomination anchoring (AF-60), the offer board (AF-61), FX drift (AF-75), the Happy Card loop (AF-65, `is_generic`), and the brand crosswalk (orders side, AF-52).
- `django_migrations` dates releases for H37.
- `offer_offerpromocode` exposes promo codes only as keys, so duplicates can be counted without revealing a redeemable code.
- `offer_plusoffer` moved out of the table-level list: `plus_offer` exposes the offer code only as `offer_code_key`, which equals `order_line_keys.offer_code_key` and the emapi and ecomweb `plus_offer.offer_code_key` (same `btrim` rule, same key), so the redemption join and the cross-store offer dimension still work. The table-level list is now 29 tables.

## 4.4 Tier 5: integration, risk and admin logs

```sql
GRANT SELECT (id, created_on, modified_on, type, created_by_id, modified_by_id, is_removed, source, is_guest)
  ON public.users_blacklisteduserdetail TO atlas_reader;
CREATE VIEW atlas_ro.blacklist_entry WITH (security_barrier) AS
SELECT b.id, b.type, b.source, b.is_removed, b.is_guest, b.created_on, b.modified_on,
       CASE b.type WHEN 'user_email'       THEN HK(nullif(lower(btrim(b.value)),''))
                   WHEN 'user_domain'      THEN HK(nullif(lower(btrim(b.value)),''))
                   WHEN 'user_mobile_no'   THEN HK(PHONE(b.value))
                   WHEN 'user_device_id'   THEN HK(btrim(b.value))       -- case preserved: equals users login_token.device_key
                   WHEN 'user_ip'          THEN HK(btrim(b.value))
                   WHEN 'sms_country_code' THEN HK(btrim(b.value))
                   END AS value_key,                                     -- identical CASE to users list_entry; other types: NULL
       CASE WHEN b.reference_id ~* '^[0-9a-f-]{36}$' THEN HK(nullif(lower(btrim(b.reference_id)),'')) END AS ref_user_key
FROM public.users_blacklisteduserdetail b;   -- the orders type set is NEEDS-GRANT: the DBA runs the section 2 type count first

GRANT SELECT (id, created_on, modified_on, event_id, status) ON public.kafka_legacyfraudsynclog, public.kafka_blacklistusergiftlog TO atlas_reader;
CREATE VIEW atlas_ro.kafka_eventlog WITH (security_barrier) AS
SELECT 'legacyfraud' AS src, id, created_on, modified_on, event_id, status,
       (error IS NOT NULL AND btrim(error) <> '') AS has_error, atlas_ro.err_class(error) AS error_class FROM public.kafka_legacyfraudsynclog
UNION ALL
SELECT 'blacklistgift', id, created_on, modified_on, event_id, status,
       (error IS NOT NULL AND btrim(error) <> ''), atlas_ro.err_class(error) FROM public.kafka_blacklistusergiftlog;

GRANT SELECT (id, status, start_timestamp, completed_timestamp) ON public.kafka_atworkkafkadatalog, public.kafka_plusofferkafkadatalog,
  public.kafka_solddateupdatekafkadatalog, public.kafka_blacklistuserkafkadatalog, public.kafka_productofferkafkadatalog,
  public.personalization_update_kafka_data_log TO atlas_reader;
CREATE VIEW atlas_ro.kafka_datalog WITH (security_barrier) AS
SELECT 'atwork' AS src, id, status, start_timestamp, completed_timestamp, (btrim(error_data) <> '') AS has_error, atlas_ro.err_class(error_data) AS error_class FROM public.kafka_atworkkafkadatalog
UNION ALL SELECT 'plusoffer', id, status, start_timestamp, completed_timestamp, (btrim(error_data) <> ''), atlas_ro.err_class(error_data) FROM public.kafka_plusofferkafkadatalog
UNION ALL SELECT 'solddate', id, status, start_timestamp, completed_timestamp, (btrim(error_data) <> ''), atlas_ro.err_class(error_data) FROM public.kafka_solddateupdatekafkadatalog
UNION ALL SELECT 'blacklistuser', id, status, start_timestamp, completed_timestamp, (btrim(error_data) <> ''), atlas_ro.err_class(error_data) FROM public.kafka_blacklistuserkafkadatalog
UNION ALL SELECT 'productoffer', id, status, start_timestamp, completed_timestamp, (btrim(error_data) <> ''), atlas_ro.err_class(error_data) FROM public.kafka_productofferkafkadatalog
UNION ALL SELECT 'personalization', id, status, start_timestamp, completed_timestamp, (btrim(error_data) <> ''), atlas_ro.err_class(error_data) FROM public.personalization_update_kafka_data_log;

GRANT SELECT (id, created_on, modified_on, status) ON public.users_cognitouserdatasynclog TO atlas_reader;
GRANT SELECT (id, action_time, object_id, action_flag, content_type_id, user_id) ON public.django_admin_log TO atlas_reader;
GRANT SELECT (id, created_on, modified_on, command, start_date, end_date, status, input_type, created_by_id) ON public.core_commandexecuter TO atlas_reader;
GRANT SELECT (id, received_at) ON public.webhooks_merchantwebhookmessage TO atlas_reader;
GRANT SELECT (id, created_by_id, created_on) ON public.personalization_detail TO atlas_reader;
CREATE VIEW atlas_ro.personalization_ref WITH (security_barrier) AS
SELECT p.id, HK(btrim(p.order_reference_id::text)) AS order_ref_key, HK(btrim(p.cart_reference_id::text)) AS cart_ref_key
FROM public.personalization_detail p;   -- order_ref_key = order_flags.order_ref_key if the column holds order_reference (confirm)
GRANT SELECT (id, created_on, modified_on, platform, status, amount, amount_in_aed, created_by_id, currency_id,
  modified_by_id, sender_id, language, send_tip_gift_event_triggered) ON public.user_tip_tip TO atlas_reader;          -- reference_id: key only
GRANT SELECT (id, created_on, modified_on, object_id, state, amount, service_charge, vat_amount, is_flagged_email_sent,
  payment_method, content_type_id, currency_id) ON public.user_tip_invoice TO atlas_reader;                            -- reference_id: key only
CREATE VIEW atlas_ro.tip_ref WITH (security_barrier) AS
SELECT 'tip' AS src, t.id, HK(nullif(lower(btrim(t.reference_id::text)),'')) AS reference_key FROM public.user_tip_tip t
UNION ALL
SELECT 'invoice', i.id, HK(nullif(lower(btrim(i.reference_id::text)),'')) FROM public.user_tip_invoice i;   -- same rule on both tables (section 2)
CREATE VIEW atlas_ro.google_review_state WITH (security_barrier) AS
SELECT HK(nullif(lower(btrim(r.user_reference::text)),'')) AS user_key, r.is_reviewed, r.reviewed_date, r.platform, r.created_on, r.modified_on
FROM public.reviews_googlereview r;
```

| Item | Unlocks |
|---|---|
| `blacklist_entry` | Two-blacklist reconciliation (AF-62, test V10), and the orders-side list in the leakage drill-down once tier 5 lands. AF-55 and H29 do **not** wait for it: they use the users-side blacklist (`list_entry`, section 3.1) with the tier 1 orders grant, which is why they are listed under tier 1 |
| `order_orderstatuschange` (in §4.3) | Order journey drill-down (AF-76); never a funnel denominator (0.98 rows per order) |
| `kafka_eventlog`, `kafka_datalog` | Kafka health grid (AF-63), fraud-propagation forensics (AF-78, test V6), H37 |
| `users_cognitouserdatasynclog` status | Identity-sync health |
| `django_admin_log` | "What changed?" for checkout config and merchandising (AF-67, AF-70) |
| `core_commandexecuter` | Dates admin-run jobs |
| `webhooks_merchantwebhookmessage` ids and times | Webhook volume (AF-68) |
| `personalization_detail` columns + `personalization_ref` | Personalisation coverage; references as keys only |
| `user_tip_*` columns + `tip_ref` | The P2P tip edge (`receiver_phone_number` excluded). The gateway payment references are exposed only as `reference_key`, following the section 4 reference rule (orders-customer-catalog profile safe-column list) |
| `google_review_state` | Post-purchase prompt state by user key (test V2 support) |

# 5. ygag_emapi_stores_db (tier 3, plus tier 5 logs)

```sql
-- (a) catalog, merchandising, reference and config tables: no user-linked rows, no customer text, no secrets.
--     Named one by one (never ON ALL TABLES); covered by the V12 column-drift check.
GRANT SELECT ON
  public.assets_image, public.assets_imagetag, public.brands_brand, public.brands_brand_categories,
  public.brands_brand_denomination, public.brands_brand_denomination_range, public.brands_brand_images,
  public.brands_brand_search_tag, public.brands_brand_search_tags, public.brands_category, public.brands_generic_brand_config,
  public.brands_generic_brand_item, public.brands_hasofferbrands, public.brands_occasion, public.brands_offer,
  public.brands_offer_happy_cards, public.brands_plusoffer_happy_cards, public.brands_productchannel,
  public.brands_retailers, public.brands_tag, public.brands_tag_brand, public.configurations_banner,
  public.configurations_bannerimage, public.configurations_banneritem, public.configurations_bannertype,
  public.configurations_carousel, public.configurations_carouselitem, public.configurations_color,
  public.configurations_homepageslider, public.configurations_homepageslider_platform_type,
  public.configurations_homepageslideritem, public.configurations_myshopcategory, public.configurations_myshopcategory_platforms,
  public.configurations_myshopcategorybrand, public.configurations_platform, public.configurations_shopcategory,
  public.configurations_shopcategorybrand, public.configurations_slidertype, public.core_basecurrency, public.core_city,
  public.core_community, public.core_country, public.core_country_languages, public.core_currency,
  public.core_currencyexchangerate, public.core_language, public.core_stateprovince, public.django_content_type,
  public.django_migrations, public.django_site, public.locations_store, public.locations_store_languages
  TO atlas_reader;

-- (a2) tables with user-linked rows or client identifiers: enumerated columns only (fail closed)
GRANT SELECT (id, created_on, modified_on, brand_id, user_id) ON public.brands_favouritebrand TO atlas_reader;
GRANT SELECT (id, created_on, modified_on, plus_offer_id, user_id) ON public.users_useravailedoffer TO atlas_reader;
GRANT SELECT (id, created_on, modified_on, password_last_changed, has_received_expiry_warning, user_id) ON public.users_usermetadata TO atlas_reader;
GRANT SELECT (id, created_on, modified_on, client_name, platform, version, expiry_date) ON public.mobile_app_client_config TO atlas_reader;   -- reference_id excluded
GRANT SELECT (id, app_platform, latest_version, required_version, optional, created_on, modified_on, os_version_check_enabled, required_os_version)
  ON public.emapi_generics_client_mobileappplatformversion TO atlas_reader;                                                                    -- reference_id excluded
GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO atlas_reader;   -- id ranges and growth without scans (sequences hold no row data)
-- Not granted at all: auth_*, dashboard_userdashboardmodule, jet_bookmark, jet_pinnedapplication (admin UI state),
-- webhooks_webhookconfig, OTP/2FA device tables, users_user_groups, users_user_user_permissions.

-- (b) app user mirror
CREATE VIEW atlas_ro.app_user WITH (security_barrier) AS
SELECT u.id, HK(nullif(lower(btrim(u.username)),'')) AS user_key, HK(nullif(lower(btrim(u.sub)),'')) AS sub_key, u.date_joined, u.last_login, u.modified_on,
       u.platform, u.app_version, u.language_code, u.country_of_residence, u.type, u.custom_profile_img, u.is_active, u.is_enabled,
       u.is_deleted, u.is_fraud, u.trusted_user, u.email_verified, u.phone_number_verified, u.is_native_user, u.is_app_user,
       u.new_password_policy, u.is_staff,
       (u.sub IS NOT NULL) AS has_sub, (coalesce(u.apple_id,'') <> '') AS has_apple_id, (coalesce(u.google_id,'') <> '') AS has_google_id,
       (coalesce(u.facebook_id,'') <> '') AS has_facebook_id, (cardinality(u.secondary_emails) > 0) AS has_secondary_emails,
       (cardinality(u.legacy_auth_code) > 0) AS has_legacy_auth_code,
       CASE WHEN u.user_agent ILIKE '%android%' THEN 'android' WHEN u.user_agent ~* '(iphone|ipad|ios)' THEN 'ios'
            WHEN u.user_agent IS NULL THEN NULL ELSE 'other' END AS os_family   -- UA truncated at 100 chars: lossy
FROM public.users_user u;

-- (c) Kafka logs: no payloads. The payload fingerprint is KEYED (section 2): an unkeyed md5 of a payload that
--     contains an email or phone could be confirmed by dictionary, which section 2 forbids.
CREATE VIEW atlas_ro.kafka_event WITH (security_barrier) AS
SELECT 'atwork' AS src, id, status, start_timestamp, completed_timestamp, (coalesce(error_data,'') <> '') AS has_error,
       HK(data::text) AS data_fingerprint, pg_column_size(data) AS data_bytes FROM public.kafka_atworkkafkadatalog
UNION ALL SELECT 'emapistores', id, status, start_timestamp, completed_timestamp, (coalesce(error_data,'') <> ''), HK(data::text), pg_column_size(data) FROM public.kafka_emapistoreskafkadatalog
UNION ALL SELECT 'plusoffer', id, status, start_timestamp, completed_timestamp, (coalesce(error_data,'') <> ''), HK(data::text), pg_column_size(data) FROM public.kafka_plusofferkafkadatalog
UNION ALL SELECT 'webstores', id, status, start_timestamp, completed_timestamp, (coalesce(error_data,'') <> ''), HK(data::text), pg_column_size(data) FROM public.kafka_webstoreskafkadatalog;
-- HK(data::text): no normalisation; the fingerprint is used only to count duplicate deliveries within one DB

-- (d)-(f) remaining sensitive tables
CREATE VIEW atlas_ro.webhook_message WITH (security_barrier) AS SELECT id, type, received_at, (error_message IS NOT NULL) AS has_error_message FROM public.webhooks_webhookmessage;
-- plus offers: offer code keyed (same rule and key as orders plus_offer); names from the emapi-stores profile, DBA confirms with pg_attribute
CREATE VIEW atlas_ro.plus_offer WITH (security_barrier) AS
SELECT p.id, HK(btrim(p.code)) AS offer_code_key, p.start_date, p.end_date, p.brand_id, p.country_id,
       p.offer_mode, p.offer_type, p.offer_channel, p.funding_method, p.funded_by, p.reason_code, p.percentage, p.fixed_amount,
       p.is_budget_available, p.budget_type, p.budget_amount, p.budget_threshold, p.has_budget_exceeded,
       p.has_usage_limit, p.usage_count,
       p.is_generic_promo_code, p.is_unique_promo_code, p.promo_code_end_date, p.promo_code_threshold,
       p.featured_order, p.brand_tile_order_number, p.offer_order_number
FROM public.brands_plusoffer p;   -- header, terms and how_it_works text columns stay closed
CREATE VIEW atlas_ro.offer_promocode_key WITH (security_barrier) AS
  SELECT id, offer_id, brand_id, status, created_on, modified_on, HK(btrim(promo_code)) AS promo_code_key, length(promo_code) AS promo_code_len
  FROM public.brands_offerpromocode;
CREATE VIEW atlas_ro.storelocation WITH (security_barrier) AS
  SELECT id, code, brand_id, community_id, created_on, modified_on FROM public.brands_storelocation;   -- contacts and addresses excluded
CREATE VIEW atlas_ro.email_template WITH (security_barrier) AS
  SELECT id, email_type, template_code, language_id, is_active, created_on, modified_on,
         (to_emails IS NOT NULL AND to_emails <> '') AS has_to_emails FROM public.notifications_emailtemplateconfiguration;
GRANT SELECT (id, action_time, action_flag, content_type_id, object_id, user_id) ON public.django_admin_log TO atlas_reader;
GRANT SELECT (id, user_id, created_on, modified_on) ON public.users_passwordhistory TO atlas_reader;
GRANT SELECT (expire_date) ON public.django_session TO atlas_reader;
CREATE VIEW atlas_ro.remote_url_host WITH (security_barrier) AS
  SELECT id, server, is_active, regexp_replace(split_part(split_part(url,'://',2),'/',1),'^.*@','') AS url_host, created_on, modified_on FROM public.remote_url_config_remoteurlconfig;  -- url_host: userinfo (user:pass@) stripped
```

| Item | Unlocks | Why this form |
|---|---|---|
| (a) 52 named catalog, merchandising, reference and config tables (`brands_plusoffer` moved to the keyed `plus_offer` view) | Catalog health (AF-17), offer coverage (AF-43), crosswalk (AF-52), availability (AF-66), placement (AF-54), Happy Card loop (AF-65), brand drill-down (AF-95), H24, H25, H60 | No user-linked rows, customer text or secrets (catalog review 2026-09-29). Table-level, so covered by V12. |
| (a2) `brands_favouritebrand`, `users_useravailedoffer`, `users_usermetadata`, app client and version config | Favourite × offer (AF-34), offer board (AF-61), forced upgrade (AF-77), browse-to-buy (AF-94), H18, H42, H52 | Enumerated columns (fail closed). Favourites and avails join to people only through `app_user.user_key`; client `reference_id` excluded. |
| Sequences | Id ranges and growth without scanning | 83 sequences, read-only |
| `app_user` | Forced upgrade (AF-77), signup-method recovery (H43), `is_fraud` split-brain (H58, test V9), tests V2 and V11 | Username and `sub` exposed only as keys. No email, phone, UA, IP or social ids. |
| `kafka_event` | Kafka health (AF-63), duplicate delivery | No `data` or `error_data`; the payload fingerprint is keyed |
| `plus_offer` | Offer board (AF-61), offer coverage (AF-43), favourite × offer (AF-34), placement by `featured_order` (AF-54), H18, H52 | Offer code only as `offer_code_key` (equal to the orders key); budget, usage and promo-code-mode flags kept |
| Promo code, store location, email template, admin log, password history, session, remote URL (d)–(f) | Promo inventory and duplicates, email trigger inventory, admin cadence, password-rotation funnel | Secrets, contacts and free text excluded |

# 6. ygag_ecomweb_stores_db (tier 4, plus tier 5 logs)

```sql
-- (a) catalog + CMS + reference tables: no user-linked rows, no customer text, no secrets.
--     Named one by one (never ON ALL TABLES); covered by the V12 column-drift check.
GRANT SELECT ON
  public.brands_brand, public.brands_brand_categories, public.brands_brand_search_tags, public.brands_brandcategory,
  public.brands_brandcommission, public.brands_brandcommissiondetail, public.brands_branddenomination,
  public.brands_branddenominationrange, public.brands_brandgenericconfig, public.brands_brandhandlingfee,
  public.brands_brandimagegallery, public.brands_brandoccasion, public.brands_brandoccasion_brands, public.brands_brandoffer,
  public.brands_brandoffer_happy_cards, public.brands_brandsearchtag, public.brands_brandslug, public.brands_categorygender,
  public.brands_defaultstorebrandforoffer, public.brands_genericbrandslist, public.brands_hasofferbrands, public.brands_occasion,
  public.brands_plusoffer_happy_cards, public.brands_productchannel, public.brands_tag,
  public.brands_tagbrand, public.company_company, public.configurations_announcement, public.configurations_announcement_country,
  public.configurations_announcement_platform_type, public.configurations_banner, public.configurations_banner_country,
  public.configurations_banner_platform_type, public.configurations_bannercategory, public.configurations_blog,
  public.configurations_brandpagepromotionbanner, public.configurations_brandskin, public.configurations_crosssellbrand,
  public.configurations_crosssellbrandconfig, public.configurations_customcategoryslider, public.configurations_downloadapp,
  public.configurations_downloadapptext, public.configurations_footer, public.configurations_footer_country,
  public.configurations_footer_payment_partners, public.configurations_footer_platform_type, public.configurations_footerstore,
  public.configurations_happycardwidget, public.configurations_happycardwidget_platform_type,
  public.configurations_happycardwidget_redeemable_brands, public.configurations_header,
  public.configurations_header_platform_type, public.configurations_headertype, public.configurations_homepageslider,
  public.configurations_homepageslider_platform_type, public.configurations_howtouse, public.configurations_howtousebanner,
  public.configurations_menuitem, public.configurations_paymentpartner, public.configurations_pdfsamples,
  public.configurations_pdfworkinfo, public.configurations_platformchoice, public.configurations_pressroom,
  public.configurations_searchtag, public.configurations_sliderbrand,
  public.configurations_testimonialvideo_country, public.configurations_themeconfig, public.configurations_themeconfig_country,
  public.configurations_upcomingoccasion, public.configurations_upcomingoccasion_country,
  public.configurations_whitelabelbrandconfigs, public.configurations_widgetorder, public.core_aigreetingsconfiguration,
  public.core_aigreetingsconfiguration_enabled_countries, public.core_aigreetingsconfiguration_enabled_languages,
  public.core_aigreetingsparameters, public.core_basecurrency, public.core_country, public.core_country_languages,
  public.core_currency, public.core_currencyexchangerate, public.core_language, public.core_siteconfiguration_platform_type,
  public.core_sitemeta, public.core_unsupportedcountry, public.django_content_type, public.django_migrations, public.django_site,
  public.locations_city, public.locations_community, public.locations_state, public.locations_store,
  public.locations_store_languages
  TO atlas_reader;

-- (a2) config tables with sensitive columns: enumerated columns only (fail closed)
GRANT SELECT (id, created_on, modified_on, action, threshold, enabled, captcha_version) ON public.core_captchaconfigurations TO atlas_reader;
GRANT SELECT (id, created_on, modified_on, name, is_active, chat_enabled, atwork_enabled, solution_hub_enabled)
  ON public.core_siteconfiguration TO atlas_reader;                               -- email, address, chat_key and logo excluded
GRANT SELECT (id, created_on, modified_on, tone, relation, occasion) ON public.core_aigreetingmessages TO atlas_reader;
  -- note (likely user-typed: names, relationships) and response_content (generated text that can echo the note) excluded
GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO atlas_reader;   -- sequences hold no row data

-- (a3) HELD for column review, not granted in this request: configurations_testimonial, configurations_testimonialapps,
--      configurations_testimonialorder, configurations_testimonialvideo. The testimonial block carries a curated
--      customer_name (cross-db profile, CMS map), and their full column lists were not captured in profiling.
--      Before any grant, the DBA lists the columns:
--        SELECT attrelid::regclass, attname, format_type(atttypid, atttypmod) FROM pg_attribute
--         WHERE attrelid IN ('public.configurations_testimonial'::regclass, 'public.configurations_testimonialapps'::regclass,
--                            'public.configurations_testimonialorder'::regclass, 'public.configurations_testimonialvideo'::regclass)
--           AND attnum > 0 AND NOT attisdropped;
--      and grants by enumerated column only, excluding customer_name and any name-bearing or free-text column
--      (the same treatment as configurations_testimonialreview). No REPORT.md feature or hypothesis depends on them.
--      configurations_testimonialvideo_country (testimonial-video id and country id only) stays in (a).
-- Not granted at all: auth_*, dashboard_userdashboardmodule, jet_bookmark, jet_pinnedapplication, users_customuser*,
-- users_passwordhistory, users_usermetadata, configurations_downloadapprequest, configurations_testimonialreview,
-- notifications_* (staff OTP and templates), webhooks_remoteurlconfig, webhooks_webhookconfig, OTP/2FA device tables.

-- Kafka logs (tier 5): no payloads, keyed fingerprint (same rule as emapi section 5(c))
CREATE VIEW atlas_ro.kafka_event WITH (security_barrier) AS
SELECT 'gift' AS src, id, status, start_timestamp, completed_timestamp, (coalesce(error_data,'') <> '') AS has_error,
       HK(data::text) AS data_fingerprint, pg_column_size(data) AS data_bytes FROM public.kafka_giftkafkadatalog
UNION ALL SELECT 'webstores', id, status, start_timestamp, completed_timestamp, (coalesce(error_data,'') <> ''), HK(data::text), pg_column_size(data) FROM public.kafka_webstoreskafkadatalog;

-- web user mirror
CREATE VIEW atlas_ro.web_user WITH (security_barrier) AS
SELECT c.id, HK(nullif(lower(btrim(c.username)),'')) AS user_key, c.date_joined, c.modified_on, c.platform, c.app_version, c.is_app_user,
       c.type, c.country_of_residence, c.language_code, c.is_deleted, c.is_enabled, c.trusted_user, c.email_verified,
       c.phone_number_verified, (cardinality(c.legacy_auth_code) > 0) AS has_legacy_auth_code
FROM public.users_cognitouser c;

-- recently viewed brands by user key
CREATE VIEW atlas_ro.recent_view WITH (security_barrier) AS
SELECT v.id, HK(nullif(lower(btrim(v.username)),'')) AS user_key, v.brand_id, v.store_id, v.created_on, v.modified_on
FROM public.configurations_lastviewedbrand v;

-- brand suggestions and newsletter opt-ins
-- brand_name is typed by the customer, so no text leaves the DB. A suggestion is matched in-DB to the catalog; atlas sees the
-- matched catalog brand id, or, for an unmatched suggestion, only a keyed hash (to count repeats of the same missing brand).
CREATE VIEW atlas_ro.feedback_suggestion WITH (security_barrier) AS
SELECT f.id, f.platform_id, f.created_on,
       (SELECT min(b.id) FROM public.brands_brand b
         WHERE lower(btrim(f.brand_name)) IN (lower(btrim(b.name)), lower(btrim(b.slug)))) AS matched_brand_id,
       CASE WHEN NOT EXISTS (SELECT 1 FROM public.brands_brand b
                              WHERE lower(btrim(f.brand_name)) IN (lower(btrim(b.name)), lower(btrim(b.slug))))
            THEN HK(nullif(lower(btrim(f.brand_name)),'')) END AS unmatched_suggestion_key,
       CASE WHEN jsonb_typeof(f.extra) = 'object' THEN ARRAY(SELECT jsonb_object_keys(f.extra) ORDER BY 1) END AS extra_keys
FROM public.configurations_productfeedbackbox f;
-- confirm the brands_brand name columns first (the catalog shows EN and AR names): match on the EN name, the AR name and the slug.
-- email_address and user_reference are never exposed. Unmatched keys are reported only as counts with a minimum cell of 10.
CREATE VIEW atlas_ro.email_subscription WITH (security_barrier) AS
SELECT s.id, s.platform_id, s.is_subscribed, s.created_on, s.modified_on, HK(nullif(lower(btrim(s.email_address)),'')) AS email_key,
       CASE WHEN jsonb_typeof(s.extra) = 'object' THEN ARRAY(SELECT jsonb_object_keys(s.extra) ORDER BY 1) END AS extra_keys
FROM public.configurations_emailsubscription s;

CREATE VIEW atlas_ro.storelocation WITH (security_barrier) AS SELECT id, brand_id, created_on, modified_on FROM public.brands_storelocation;
-- plus offers: offer code keyed (same rule and key as orders and emapi); names from the ecomweb-stores profile, DBA confirms
CREATE VIEW atlas_ro.plus_offer WITH (security_barrier) AS
SELECT p.id, HK(btrim(p.code)) AS offer_code_key, p.start_date, p.end_date, p.country_id,
       p.offer_mode, p.offer_type, p.offer_channel, p.reason_code,
       p.budget_type, p.budget_amount, p.budget_threshold, p.has_budget_exceeded,
       p.is_generic_promo_code, p.is_unique_promo_code, p.promo_code_end_date, p.promo_code_threshold
FROM public.brands_plusoffer p;
CREATE VIEW atlas_ro.offer_promocode_key WITH (security_barrier) AS
  SELECT id, offer_id, status, created_on, HK(btrim(promo_code)) AS promo_code_key FROM public.brands_offerpromocode;
GRANT SELECT (id, action_time, action_flag, content_type_id, object_id) ON public.django_admin_log TO atlas_reader;
GRANT SELECT (expire_date) ON public.django_session TO atlas_reader;
```

| Item | Unlocks | Why this form |
|---|---|---|
| (a) 93 named catalog, CMS and reference tables (the four testimonial tables are held for column review, (a3); `brands_plusoffer` moved to the keyed `plus_offer` view) | Placement effectiveness (AF-54), availability (AF-66), Arabic gap (AF-35), catalog health web side (AF-17), crosswalk (AF-52), browse-to-buy (AF-94), brand drill-down (AF-95), merchandising calendar (AF-96), H24, H25, H53, H60 | No user-linked rows, customer text or secrets (catalog review 2026-09-29). Table-level, so covered by V12. |
| (a2) `core_captchaconfigurations`, `core_siteconfiguration`, `core_aigreetingmessages` | Bot-friction config, feature flags, AI-greeting usage by tone, relation and occasion | Enumerated columns: no `chat_key`, contact email or address, and no greeting `note` or `response_content` |
| `kafka_event` | Kafka health (AF-63), including the gift topic that the earlier draft left out | No payloads; keyed fingerprint |
| `web_user` | Identity test V2, channel test V11, web-side signup platform | No email, phone, names, IP or UA |
| `recent_view` | Viewed-not-bought trigger (AF-58), H17, brand affinity (AF-72), browse-to-buy (AF-94) | Username exposed only as a key |
| `feedback_suggestion`, `email_subscription` | Supply-demand gap finder (AF-73), dead-end search (H53); a consent baseline for the web newsletter only (not a CRM consent record) and the attribution check in `extra` keys (D5) | No free text: a suggestion is a matched catalog brand id or a keyed count of an unmatched name. Emails exposed only as keys; `extra` as key names only |
| Promo codes, `plus_offer`, store locations, admin log, session expiry | Promo duplicates, web offer placement, merchandising "what changed" (AF-67) | Promo and offer codes only as keys; contacts excluded |

# 7. Index and extract asks (protecting the shared reader)

The cluster has **one reader shared by 40 databases**. The large orders tables have no usable time index.

| Ask | Where | Why |
|---|---|---|
| Nightly governed extract of the `atlas_ro` views (role `ygg_atlas_extract`, 02:00–05:00 Asia/Dubai) into the atlas store | orders (all tier 1–2 views), emapi and ecomweb catalog | Recurring funnels read the extract, never live 1–3 GB scans |
| `CREATE INDEX CONCURRENTLY ON youpayclient_youpayclienttransactiondata (order_reference)` and `(created_on)` | orders, primary | Without them, every youpay-to-order join is a 2 GB scan |
| `CREATE INDEX CONCURRENTLY ON kafka_giftcreationlog (order_id)` and `(created_on)` | orders, primary | About 3.26M rows (extrapolated estimate; 3.13M raw); only the primary key and `event_id` are indexed |
| `CREATE INDEX CONCURRENTLY ON basket_basket (date_created)` | orders, primary | 3.05M rows; no date or status index |
| `REFRESH MATERIALIZED VIEW atlas_ro.basket_summary` nightly | orders, primary | Replaces basket scans |
| Optional: `CREATE INDEX CONCURRENTLY ON configurations_lastviewedbrand (username)` | ecomweb, primary | Helps the storefront itself: every read is a full scan today |
| Optional: RDS Performance Insights access for the data platform | reader instance | Identify the unknown reader doing about 25.6 youpay full scans a day (AF-87) |

The indexes are suggestions for the table owners. If they are declined, the extract alone is enough.

# 8. Never grant (any database)

These are **never** granted, under any tier:

- password hashes;
- TOTP and static OTP secrets, WebAuthn keys;
- session keys and session data;
- `api_key` / `api_secret` / `encryption_key` in any `*remoteurlconfig*` or `youpayclient_clientconfiguration`;
- webhook keys and sender IPs;
- raw email, phone, name, IP, user agent and social ids;
- card BIN/last4 and `name_on_card`;
- customer fields on youpay;
- raw promo codes, and raw offer codes (`plusoffer.code`, `order_line.offer_code`) unless test V16 confirms they are not redeemable;
- gift codes, PINs and redemption links (`created_gift_details`, `partner_line_notes`, `partner_line_reference` until reviewed);
- raw gateway, order, invoice and loyalty references (`transaction_id`, `payment_reference`, `order_reference`, `payment_order_reference`, `invoice_id`, `qitaf_request_id`, gift-log `order_id`, the order `number`, basket and order `line_reference`, tip `reference_id`): keyed only;
- customer-typed free text in any form, including a normalised copy (`productfeedbackbox.brand_name`, AI-greeting `note`);
- raw Kafka `data`/`payload`/`error_data`;
- raw `response_summary` and `change_message`;
- raw decline, error or failure text in any form, including truncated or masked text (only the closed `err_class` enum);
- AI-greeting `note` and `response_content`; storefront `core_siteconfiguration.chat_key`, contact email and address;
- unkeyed hashes (md5 or sha) of any value that can contain personal data, payloads included;
- `object_repr`;
- the key table `atlas_sec.hk_key`.

# 9. Verification after grants (counts only, cheap)

| Test | What | Pass condition |
|---|---|---|
| V1 | Numeric-id overlap for 20 sampled users (users `id` against orders `customuser.id`, ecomweb and emapi `id`) | Expected to fail. It confirms that numeric ids must never be joined. |
| V2 | Share of orders `atlas_ro.user_profile.user_key`, ecomweb `web_user.user_key` and emapi `app_user.user_key` found in users `atlas_ro.user_profile.user_key` | 95% or more. Otherwise, investigate the username format (width 150 against 36). |
| V3 | Share of orders `catalogue_product.upc` found in emapi and ecomweb `brands_brand.code` | Report the match rate. It becomes the AF-52 crosswalk version. |
| V4 | `gift_issuance_event.order_id_key` against `order_flags.order_number_key` / `order_ref_key` / `order_id_key` / `payment_order_ref_key` | Identify the key (all keyed, section 4) |
| V5 | youpay `count(*)` against `count(DISTINCT order_ref_key)` in `youpay_derived` on a sample | Decides the dedup rule |
| V6 | Users producer `event_id` against orders `kafka_eventlog.event_id` | Propagation coverage |
| V8 | The 902 stuck guest tokens and emails against `guest_keys` (`guest_username_key`, `guest_session_key`, `guest_email_key`, hashed in-DB on the users side with the same section 2 rules) | Guest mapping |
| V9 | `is_deleted`, `trusted_user` and `is_fraud` agreement by `user_key` across the four DBs | Fraud-status split-brain check |
| V10 | Blacklist overlap by `type` on `value_key` (users `list_entry` against orders `blacklist_entry`) | Users-only / orders-only / both |
| V11 | Users who log in only on app against presence in emapi `app_user`; web-only users against ecomweb `web_user` | Confirms the channel mapping |
| V13 | Recipient phone format and match rate: share of `occasion_line` phones by `recipient_phone_format`, and the share of each format whose key (or the store-country candidate) is found in users `identity_keys.phone_key` | Reported, not pass/fail. It becomes the phone-match rate on the AF-45 / AF-71 provenance chip. A national-format share above 10% triggers an engineering ask to store recipient phones in E.164 |
| V14 | Blacklist key normalisation: per `type`, the number of users `list_entry` rows whose `value_key` is found on the matching side (`login_token.device_key` for `user_device_id`, `identity_keys.phone_key` for `user_mobile_no`, `identity_keys.email_key` for `user_email`), against the DBA's in-DB count of raw matches under the same rule (for example `btrim(value) = btrim(device_signature)`) | Equal counts per type. A gap means a case, trim or phone rule differs between the two sides |
| V15 | Promo-blocked domain normalisation: (a) live users with `user_profile.is_promo_blocked_domain`; (b) live users whose `email_domain_label_key` is in active `promo_blocked_domain.domain_label_key`; (c) the DBA's in-DB raw count under the same label rule (`lower(split_part(split_part(btrim(email),'@',2),'.',1)) IN (SELECT lower(btrim(domain)) FROM users_promotionaldomainblacklist WHERE is_active)`) | (a) = (b) = (c), and of the order of the 5,544 live users measured in discovery. (b) = 0 while (c) > 0 means a side is hashing the full domain instead of the label |
| V16 | Offer-code sensitivity (DBA or offers owner, no data to atlas): is `plusoffer.code` (orders, emapi, ecomweb) or `order_line.offer_code` ever typed or shown to customers as a redeemable code (for example when `is_generic_promo_code` is true)? The same question for the legacy offer `code` columns in the table-level lists (orders `offer_productoffer.code`, emapi `brands_offer.code`) | Answer recorded. If not redeemable, the raw `code` may be added to the `plus_offer` views by a later change; if redeemable, it stays keyed, and any legacy offer table whose `code` is redeemable moves from the table-level list to a keyed view before its tier runs |
| V12 | Monthly column drift: `pg_attribute` for every table granted at table level, against the approved column list in this document | Any new column raises an alert and is reviewed; a sensitive one moves its table to an enumerated grant |

# 10. Engineering asks (not grants, recorded for the owners)

1. **Add `deleted_at` (and `deleted_by`) to users `users_user`.** Keep an HMAC of the pre-deletion email and phone for abuse matching. Today soft delete encrypts both, and `modified_on` is not a deletion time.
2. **Fix the orders → users blacklist payload.** The stuck events are missing `mark_as_fraud` and `reference_id`. 396 events for 389 registered users are unapplied, and they are still arriving.
3. **Review the removed RU `sms_country_code` block** (removed 2025-10-16) in light of the live RU/+7 web farm (83 accounts since 2026-09-26). Also review the 13 countries where the whitelist overrides the blacklist.
4. **Record consumer errors.** `error_data` is empty on every stuck consumer row, which is why the failure was silent.

# Appendix A. DDL generator (expands the macros; no hand edits)

The DDL in sections 1–6 uses two macros, `HK(...)` and `PHONE(...)` (section 2). Expanding them by hand dozens of times invites exactly the silent-mismatch errors section 2 warns about, so this request ships a generator instead. It reads this document and writes one ready-to-run file per database:

| File | Contents | Run |
|---|---|---|
| `cluster.sql` | Roles, session guards, the temporary `GRANT atlas_view_owner TO <dba_login>` | Once, on the primary |
| `users.sql`, `orders.sql`, `emapi.sql`, `ecomweb.sql` | Section 1 schema prelude and section 2 key table, then that database's section; every macro expanded | Once per database, on the primary |
| `users_phase2_revoke.sql` | Section 3.3 checks and revoke | Only after the atlas cut-over date |

For each database file the generator:

1. expands every `HK(...)` and `PHONE(...)` outside comments and string literals, and **fails** if any macro is left or if a view body calls an unkeyed `md5`, `sha*` or `digest`;
2. orders the statements as section 1 requires: DBA prelude → `GRANT SELECT` on every source table found in a view body `TO atlas_view_owner` → `SET ROLE atlas_view_owner` → every `CREATE TABLE / VIEW / MATERIALIZED VIEW / FUNCTION` in `atlas_ro` or `atlas_sec` → `RESET ROLE` → column grants and grants on the new objects → an explicit `GRANT SELECT` per `atlas_ro` view `TO atlas_reader`;
3. wraps the run in one transaction and appends the section 1 ownership check.

The DBA inserts the key (as `atlas_view_owner`) after the file runs, then runs the ownership check and the section 9 tests. The generator was run against this revision of the document: it expanded every macro in all four files and passed both checks. The generated `users.sql` was then run end to end on a local PostgreSQL 14 with mock tables (every `atlas_ro` object and the key table came out owned by `atlas_view_owner`, readable by `atlas_reader` except the key table), and the changed orders views (`order_flags`, `occasion_line`, `youpay_derived`, `blacklist_entry`, `personalization_ref`) compiled on mock tables. On synthetic rows, a mixed-case blacklist device value matched the token `device_key`, a `00971…` blacklist mobile matched a `+971 …` account phone, and a national-format `050…` recipient matched through the `_if_ae` candidate. `gift_issuance_event` uses PostgreSQL 16 `IS JSON` and was not run locally.

```python
#!/usr/bin/env python3
"""Expand GRANTS.md into ready-to-run DDL, one file per database.

usage: python3 expand_grants.py GRANTS.md OUT_DIR [--md5-fallback]

- expands the HK(<norm>) and PHONE(<x>) macros everywhere outside comments and string literals;
- fails if a macro survives, or if a view body calls an unkeyed md5/sha/digest;
- emits, per database: DBA prelude -> GRANT SELECT on every wrapped source table TO atlas_view_owner ->
  SET ROLE atlas_view_owner -> every CREATE TABLE/VIEW/MATERIALIZED VIEW/FUNCTION in atlas_ro/atlas_sec -> RESET ROLE ->
  remaining grants -> an explicit GRANT SELECT per atlas_ro view -> the ownership check.
--md5-fallback: use the keyed md5 fallback of section 2 (only if pgcrypto is refused; tell the atlas team).
Writes cluster.sql, users.sql, users_phase2_revoke.sql, orders.sql, emapi.sql, ecomweb.sql.
"""
import os
import re
import sys

HK_TMPL = "encode(atlas_crypto.hmac(convert_to(({x}), 'UTF8'), (SELECT k FROM atlas_sec.hk_key), 'sha256'), 'hex')"
HK_FALLBACK = "md5(encode((SELECT k FROM atlas_sec.hk_key), 'hex') || '|' || ({x}))"   # keyed, weaker; section 2
PHONE_TMPL = ("nullif(CASE WHEN regexp_replace(({x}), '\\D', '', 'g') LIKE '00%' "
              "THEN substr(regexp_replace(({x}), '\\D', '', 'g'), 3) "
              "ELSE regexp_replace(({x}), '\\D', '', 'g') END, '')")
MACROS = {"HK": HK_TMPL, "PHONE": PHONE_TMPL}
DB_BY_SECTION = {3: "users", 4: "orders", 5: "emapi", 6: "ecomweb"}
DBS = ["users", "orders", "emapi", "ecomweb"]


def scan(text):
    """Yield (index, state) for every char; state is 'code', 'str', 'dollar', 'line', 'block'."""
    i, n, state, tag = 0, len(text), "code", None
    while i < n:
        c = text[i]
        if state == "code":
            if text.startswith("--", i):
                state = "line"
            elif text.startswith("/*", i):
                state = "block"
            elif c == "'":
                yield i, "str"; i += 1; state = "str"; continue
            else:
                m = re.match(r"\$[A-Za-z_]*\$", text[i:])
                if m:
                    tag = m.group(0)
                    for k in range(len(tag)):
                        yield i + k, "dollar"
                    i += len(tag); state = "dollar"; continue
        elif state == "str":
            yield i, "str"
            if c == "'":
                if text.startswith("''", i):
                    yield i + 1, "str"; i += 2; continue
                state = "code"
            i += 1; continue
        elif state == "dollar":
            if text.startswith(tag, i):
                for k in range(len(tag)):
                    yield i + k, "dollar"
                i += len(tag); state = "code"; continue
            yield i, "dollar"; i += 1; continue
        elif state == "line":
            yield i, "line"
            if c == "\n":
                state = "code"
            i += 1; continue
        elif state == "block":
            yield i, "block"
            if text.startswith("*/", i):
                yield i + 1, "block"; i += 2; state = "code"; continue
            i += 1; continue
        yield i, state
        i += 1


def states(text):
    st = ["code"] * len(text)
    for i, s in scan(text):
        st[i] = s
    return st


def expand(text):
    st = states(text)
    out, i = [], 0
    while i < len(text):
        m = re.compile(r"\b(HK|PHONE)\(").match(text, i) if st[i] == "code" and (i == 0 or not (text[i - 1].isalnum() or text[i - 1] == "_")) else None
        if not m:
            out.append(text[i]); i += 1; continue
        depth, j = 0, m.end() - 1
        while j < len(text):
            if st[j] == "code":
                if text[j] == "(":
                    depth += 1
                elif text[j] == ")":
                    depth -= 1
                    if depth == 0:
                        break
            j += 1
        if depth != 0:
            sys.exit(f"unbalanced {m.group(1)}( near: {text[i:i + 80]!r}")
        inner = expand(text[m.end():j])
        out.append(MACROS[m.group(1)].format(x=inner))
        i = j + 1
    return "".join(out)


def code_only(text):
    st = states(text)
    return "".join(ch if s in ("code", "str", "dollar") else " " for ch, s in zip(text, st))


def split_statements(text):
    st = states(text)
    stmts, start, i = [], 0, 0
    while i < len(text):
        if st[i] == "code" and text[i] == ";":
            end = text.find("\n", i)
            end = len(text) if end == -1 else end
            rest = text[i + 1:end]
            if rest.strip() and not rest.strip().startswith("--"):
                end = i + 1
            stmts.append(text[start:end + (1 if end < len(text) and text[end:end + 1] == "\n" else 0)])
            start = end + 1 if end < len(text) and text[end:end + 1] == "\n" else end
            i = start; continue
        i += 1
    tail = text[start:]
    if tail.strip():
        stmts.append(tail)  # trailing comments only
    return stmts


def blocks(md):
    sec, sub, cur, buf, out = None, None, None, [], []
    for line in md.splitlines():
        if cur is None:
            m = re.match(r"^# (\d+)\.", line) or re.match(r"^# Appendix", line)
            if m:
                sec = int(m.group(1)) if m.groups() else 99
                sub = None
            m2 = re.match(r"^## (\d+\.\d+)", line)
            if m2:
                sub = m2.group(1)
            if line.strip() == "```sql":
                cur, buf = (sec, sub), []
        elif line.strip() == "```":
            out.append((cur[0], cur[1], "\n".join(buf) + "\n"))
            cur = None
        else:
            buf.append(line)
    return out


def main(md_path, out_dir):
    md = open(md_path, encoding="utf-8").read()
    cluster, prelude, postlude, phase2 = [], [], [], []
    per_db = {d: [] for d in DBS}
    for sec, sub, body in blocks(md):
        if sec == 1:
            if "CREATE ROLE" in body or "GRANT atlas_view_owner TO" in body:
                cluster.append(body)
            elif "ALTER VIEW atlas_ro.<view>" in body:
                continue  # repair recipe, not part of the run
            elif "pg_get_userbyid" in body:
                postlude.append(body)
            else:
                prelude.append(body)
        elif sec == 2:
            prelude.append(body)
        elif sec == 3 and sub == "3.3":
            phase2.append(body)
        elif sec in DB_BY_SECTION:
            per_db[DB_BY_SECTION[sec]].append(body)
    os.makedirs(out_dir, exist_ok=True)
    write(os.path.join(out_dir, "cluster.sql"), "".join(cluster), check=False)
    write(os.path.join(out_dir, "users_phase2_revoke.sql"), "".join(phase2), check=False)
    for db in DBS:
        write(os.path.join(out_dir, f"{db}.sql"), assemble(db, "".join(prelude + per_db[db]), "".join(postlude)))


OWNER = re.compile(r"^\s*CREATE\s+(OR\s+REPLACE\s+)?(TABLE|VIEW|MATERIALIZED\s+VIEW|FUNCTION)\s+(atlas_ro|atlas_sec)\.(\w+)", re.I)
EARLY = re.compile(r"^\s*(CREATE\s+SCHEMA|CREATE\s+EXTENSION|ALTER\s+DEFAULT\s+PRIVILEGES|GRANT\s+USAGE\s+ON\s+SCHEMA|REVOKE\s+ALL\s+ON\s+SCHEMA)", re.I)
ROLESW = re.compile(r"^\s*(SET\s+ROLE|RESET\s+ROLE)\b", re.I)


def assemble(db, sql, postlude):
    sql = expand(sql)
    early, owner, late, views, sources = [], [], [], [], set()
    last = None
    for stmt in split_statements(sql):
        code = code_only(stmt).strip()
        if not code:
            (last if last is not None else early).append(stmt); continue
        if ROLESW.match(code):
            comments = "".join(l + "\n" for l in stmt.splitlines() if l.strip().startswith("--"))
            if comments:
                (last if last is not None else early).append(comments)
            continue
        m = OWNER.match(code)
        if m:
            owner.append(stmt); last = owner
            if "VIEW" in m.group(2).upper():
                views.append((m.group(2).upper().startswith("MATERIALIZED"), f"{m.group(3)}.{m.group(4)}"))
                sources.update(re.findall(r"\b(?:FROM|JOIN)\s+(public\.[a-z_0-9]+)", code, re.I))
        elif EARLY.match(code):
            early.append(stmt); last = early
        else:
            late.append(stmt); last = late
    grants = [f"GRANT SELECT ON {t} TO atlas_view_owner;\n" for t in sorted(sources)]
    reader = [f"GRANT SELECT ON {v} TO atlas_reader;   -- explicit; default privileges also cover it\n" for _, v in views]
    return (f"-- ygg-atlas grants for {db}: generated from GRANTS.md by expand_grants.py. Run on the PRIMARY as the DBA.\n"
            "\\set ON_ERROR_STOP on\nBEGIN;\n\n-- 1. DBA prelude\n" + "".join(early)
            + "\n-- 2. source tables the view owner reads (never granted to atlas_reader)\n" + "".join(grants)
            + "\n-- 3. every atlas_ro / atlas_sec object, created as its owner\nSET ROLE atlas_view_owner;\n" + "".join(owner)
            + "RESET ROLE;\n\n-- 4. column grants and grants on the new objects\n" + "".join(late)
            + "\n-- 5. explicit reader grants on every atlas_ro view\n" + "".join(reader)
            + "\nCOMMIT;\n-- insert the key now (as atlas_view_owner), then run the ownership check\n" + postlude)


def write(path, text, check=True):
    if check:
        code = code_only(text)
        left = re.findall(r"\b(HK|PHONE)\(", code)
        if left:
            sys.exit(f"{path}: {len(left)} unexpanded macro(s)")
        allowed = code.count("md5(encode((SELECT k FROM atlas_sec.hk_key)") if MACROS["HK"] == HK_FALLBACK else 0
        bad = re.findall(r"\b(md5|sha1|sha224|sha256|sha384|sha512|digest)\s*\(", code, re.I)
        bad = [b for b in bad if b.lower() != "md5"] + ["md5"] * max(0, sum(b.lower() == "md5" for b in bad) - allowed)
        if bad:
            sys.exit(f"{path}: unkeyed hash call(s): {sorted(set(bad))}")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"wrote {path}")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--md5-fallback"]
    if len(args) != 2:
        sys.exit(__doc__)
    if "--md5-fallback" in sys.argv:
        MACROS["HK"] = HK_FALLBACK
    main(args[0], args[1])
```
