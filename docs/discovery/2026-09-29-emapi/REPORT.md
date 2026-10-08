# Executive summary

**What this report covers.** We looked at the four YouGotAGift ecommerce databases that sit behind the consumer web and app: identity (`ygag_ecom_users_db`), orders (`ygag_ecom_orders_db`), the web storefront (`ygag_ecomweb_stores_db`) and the app/EMAPI stores service (`ygag_emapi_stores_db`). The goal is to decide which of them become atlas source plugins, in what order, and which atlas features to switch on first. Everything was read on 2026-09-29 through the atlas read replica. Every claim carries an evidence label: VALIDATED, STRUCTURAL or NEEDS-GRANT (defined in section 2). Causal readings on top of a measurement are marked **[inferred]**.

**The access reality.** A `has_table_privilege` check on 2026-09-29 gave this picture:

| Database | Tables | Readable today | What we could do |
|---|---|---|---|
| `ygag_ecom_users_db` (identity) | 40 | **40** | Run data queries. About 150 aggregate data queries were run. |
| `ygag_ecom_orders_db` (baskets, orders, payments, gift events) | 159 | **0** | Read the catalog and metadata only |
| `ygag_ecomweb_stores_db` (web storefront) | 134 | **0** | Read the catalog and metadata only |
| `ygag_emapi_stores_db` (app stores, master catalog) | 84 | **0** | Read the catalog and metadata only |

Consequences:

- Every number about baskets, orders, payments, brands and offers is STRUCTURAL: it comes from the schema, planner estimates or replica counters.
- Nothing about purchase behaviour is VALIDATED yet.
- No attempt was made to work around privileges.

## Immediate escalations (live incidents found during discovery)

These are not atlas features. They are live problems in production systems, and each needs a named owner this week. Owners are proposed by role and must be confirmed by the engineering and risk leads. Evidence is VALIDATED on the users DB unless marked otherwise.

| # | Incident | Severity | Evidence | Proposed owner | Proposed deadline |
|---|---|---|---|---|---|
| E1 | **Active RU/+7 account farm.** 83 web accounts since 2026-09-26 (36, 17, 3 and 27 a day, against a baseline of about 0.3), 81 of them logging in from German IPs on 5 browser builds, none blacklisted. The RU SMS block was removed on 2025-10-16. | Sev 1 (active) | G1, VALIDATED | Risk and fraud operations lead, with identity service engineering | Triage and a containment rule (H33) by 2026-10-01 |
| E2 | **903 blacklisted accounts can still log in.** 12 of them were issued 18 tokens after being blacklisted, and 8 accounts with a max-login-attempts entry logged in again. The blacklist gates signup only. | Sev 1 (control failure) | G2, VALIDATED | Identity service engineering lead | Decision on revoking tokens for blacklisted accounts by 2026-10-06 |
| E3 | **Orders → users fraud requests are silently dropped.** 1,298 consumer rows are stuck `in_progress`. 396 of them are for 389 registered users, and the last arrived on 2026-09-28. The probable cause is a payload missing `mark_as_fraud` / `reference_id` [inferred]. `error_data` is empty on every row. | Sev 2 (still arriving) | E3, VALIDATED | Orders service engineering lead (producer), with identity service engineering (consumer) | Payload fix and replay of the 396 by 2026-10-13 |
| E4 | **The group-gift fraud feed never resumed** after the 2025-05-12 stop. The gifts and orders feeds were silent for about 9 months, and no alert fired. | Sev 2 | E2, VALIDATED | Platform / integration engineering lead | Root cause and an alert by 2026-10-13 |
| E5 | **The atlas role can read secrets and raw PII in the users DB** (`api_key`/`api_secret`, password hashes, TOTP keys). The grant sits directly on the role. | Sev 2 (our own exposure) | VALIDATED grant state (`has_table_privilege`, cross-db X1); GRANTS.md §3.3 | DBA, with the ygg-atlas data platform lead | Views in place and revoke run by 2026-10-20 |
| E6 | **About half of US/CA numbers cannot sign up by phone.** Only 133 of 267 +1 numbers (49.8%) became accounts in 31 days, so about half never register. 13 SMS countries are on both the whitelist and the blacklist, and the whitelist wins. | Sev 3 (friction, not fraud) | B2, E6, VALIDATED | Messaging / SMS operations | Carrier and route review by 2026-10-20 |

## What we found

1. **Gifts bring in customers, and nobody measures it.** 26,737 accounts were created no more than a day before their owner's first gift claim, 23,994 of them within an hour. That is **3.2–6.3% of all monthly signups** since Aug 2024, and it is a lower bound (VALIDATED). These users look low-risk: 0.02% match an active blacklist entry, against **up to 0.76%** of organic signups. The 0.76% is an upper bound, because it sums email, domain and mobile matches, which can overlap. Among accounts that survived day 1, 0.39% against 0.76% are later deleted. But they come back less: among app users who joined 2026-07-15 to 2026-08-31, 2.2% of gift-acquired signups (26 of 1,208) got a new token more than 7 days after signup, against 3.3% of other app signups in the same cohort (744 of 22,371; G11, VALIDATED). All gift-acquired users in that cohort are app users, so this is an app-only comparison, not all gift-acquired against all organic users. Calling gifting an acquisition *channel* is [inferred]: the data shows timing, not cause.
2. **Verification friction is the largest measurable leak** (VALIDATED).
   - Needing a resend at signup (2+ codes) drops registration from **82.7% to 56.8%** (exactly one resend: 59.4%; 3+ codes: 52.6%). This is per recipient over 31 days, the canonical metric definition (see B1).
   - Phone signups from countries with no SMS routing config never get an accepted code **23.3%** of the time, against 2.7% for SA/AE. For US/CA, only **49.8%** of numbers became accounts, so about half never register.
   - The gift-recipient claim step verifies only 66% of chains, and **46% in Arabic** against 74% in English.
3. **Several risk controls leak today** (VALIDATED). See the escalation table above: the live farm (E1), blacklisted accounts that still log in (E2), dropped fraud requests (E3) and the 9-month fraud-feed silence (E4).
4. **Ready-made campaign audiences exist today.**
   - About 26.8k birthdays of live non-shell users fall in the next 30 days, or 31.0k if migration shells are included (VALIDATED). This is the live base, not active users: only 47.0% of recent token holders have a usable birthday (D2). D1 sets the shell rule for each audience.
   - A seasonal occasion calendar can be seeded from signup and claim spikes. For example, SA signups ran 8.5x their trailing 28-day mean on 2025-03-26 (3,628 signups; VALIDATED, campaigns T10). That this was the pre-Eid effect is [inferred] from the date: it fell in the last days of Ramadan 1446, four days before Eid al-Fitr on 2025-03-30.
   - Corporate gifting shows up in claim bursts: burst domains burst again in the same season **40%** of the time, against 3.9% for other active domains (VALIDATED, n = 20 domain-seasons).
5. **The commerce side is rich but locked** (STRUCTURAL). All volumes below are planner estimates extrapolated to 2026-09-29 by page growth (orders-funnel Q20), so every ratio uses one basis:
   - 3.05M baskets, 1.23M orders and 1.47M order lines;
   - 3.26M gift-creation events, which is **2.64 per order** and not yet explained (the raw, un-extrapolated ratio is 3.13M / 1.23M = 2.54);
   - two payment tables, not two records per order: youpay has 1,238,225 rows (100.3% of the order count) with no uniqueness on `order_reference`, so its per-order cardinality is unknown, and `payment_paymentdetail` has 769,659 rows (0..1 per order, about 62% of orders; see B6);
   - occasion and reminder fields on about 513k order lines;
   - a 6,610-listing master catalog.

   Every purchase-based trigger needs a grant.
6. **None of the four databases holds referral, UTM/campaign attribution or message-delivery data, and none holds a general marketing-consent store** (VALIDATED for the users DB, STRUCTURAL for the others). The only consent-like data is a small ecomweb newsletter opt-in table, `configurations_emailsubscription` (`is_subscribed` by platform; 32 KB, never analysed, so its row count is unknown; STRUCTURAL). It is not a consent record that CRM triggers could rely on. The gift loop is the only referral proxy.

## Top 10 recommended features

All ten can be built now on the users DB. Each costs about one sprint or less. Section 6 has the full scored catalog, with a "Blocked by" column.

Nine of them score 5.00 on their own. The tenth, the S-effort domain classifier AF-88, scores 3.00 but **inherits 5.00** because AF-08 and AF-09 cannot be built without it: a prerequisite always ranks with, and just before, its highest-ranked dependent (section 6). Among equal scores, the **rank tie-break** is applied in this order: (1) dependency, so a feature that unblocks others ranks first; (2) exposure to a live incident; (3) audience reach; (4) time to value. The corporate season re-book list AF-09 ranks 11th, one place below the top 10; it is S effort on top of AF-08 and AF-88 and ships in the same sprint. Three M-effort features also reach 5.00 because P1 experiments need them (section 6, "Hypothesis prerequisites"): the OTP incident alert AF-26 (H55), the rescue queue AF-27 (H51, H07) and the signup verification funnel AF-25 (H61, H02). They rank 12–14, after the rows that score 5.00 on their own, and ship in Wave 1 of the roadmap.

| Rank | Feature | Why now | Tie-break reason · blocked by |
|---|---|---|---|
| 1 | AF-01 OTP and login-token daily snapshot job | OTP data is purged after 31 days and web tokens after 30. Every trend dies without the snapshot. | Unblocks AF-03, AF-05, AF-25–AF-29 and every trend |
| 2 | AF-10 Suppression and risk-exclusion ("do not reward") segment | Keeps promo budget away from farms and blacklisted accounts | Gates every campaign trigger (AF-04, AF-05, AF-27); live incidents E1, E2 |
| 3 | AF-06 Blacklist enforcement-gap monitor | 903 blacklisted accounts are still live | Live incident E2 |
| 4 | AF-07 Integration silence and stuck-request detector | Would have caught the 9-month fraud-feed silence | Live incidents E3, E4 |
| 5 | AF-03 Gift-claim verification funnel, by language | Only 46% of Arabic claim chains get through; about 1,183 failed claim chains per 31 days; 857 of 3,182 claim-OTP recipient emails (26.9%) never became an identity | Direct fix target (H03, H51); AF-01 for trends |
| 6 | AF-02 Gift-acquired signups metric | An acquisition source nobody reports: 3–6% of signups a month | Leadership reach; has no blockers (it is itself a blocker of AF-15, AF-16, AF-31, AF-45 and AF-90) |
| 7 | AF-05 Failed sign-in win-back trigger | 44.7% of users whose email sign-in failed have no login token within 7 days, against 5.6% after success. Fires about 15 times a day. | Needs AF-01 and AF-10 |
| 8 | AF-04 Birthday audience segment | About 26.8k birthdays of live non-shell users in the next 30 days (the live base, not active users) | Largest reach; needs AF-10 and AF-11's `legacy_state` dimension (built with it, for the shell exclusion); a marketing send also needs a consent decision (AF-79) |
| 9 | AF-88 Data-driven claim-domain classifier | Consumer-or-org class for every claim domain, computed in-DB; names never leave the DB | Prerequisite of AF-08, AF-09, AF-89, AF-90 and H50; inherits their 5.00 |
| 10 | AF-08 Corporate gifting burst alert | About 9 firings a year, each worth a B2B follow-up | Needs AF-88 |

**Recommended plugin order**

1. **`ecom_users` now**: identity, OTP, gifting-claim, risk and lifecycle definitions.
2. **`ecom_orders` after grant tiers 1–2**: orders, identity join, occasions, payments and gift issuance. This plugin unlocks the most value.
3. **`emapi_stores`**: master catalog, offers, favourites and the app user mirror.
4. **`ecomweb_stores`**: web merchandising and recently-viewed brands.

The single most valuable grant is the orders identity-and-order tier, which lets atlas join a user's identity to their orders: `users_userprofile` (keyed hash of `cognito_id`) plus `order_order`, `order_line` and `order_orderlinequantitydetail`. **GRANTS.md** has the consolidated, DBA-ready request. Section 8 maps every feature and hypothesis to the grant tier that unlocks it.

# Scope and method

## What was analysed

The four databases above sit on one Aurora PostgreSQL 16 cluster. That cluster has one writer and **one reader shared by 40 databases**. Measured replica lag was 8–26 ms (STRUCTURAL).

The work ran in two layers:

- **Seven database profiles**: users, the orders funnel, orders customer/catalog, orders integrations, ecomweb stores, emapi stores, and a cross-database map.
- **Seven theme analyses** built on the profiles: user lifecycle, purchase friction, gifting and referral network, campaigns and triggers, errors and system behaviour, catalog and brand intelligence, and risk, fraud and data integrity.

## How queries were run (read-replica safety)

- Every query went through `atlasq.sh`. It opens an SSH session to the atlas EC2 host, then runs a **READ ONLY transaction on the Aurora read replica** as role `<emapi_login_role>`. Output passes through a PII redactor.
- The redactor also masks ISO dates. Dates were therefore produced with `to_char`, and any output that came back masked was discarded, not guessed.
- Output was **aggregate-only**. No email, phone, IP, device id, blacklist value, domain name or free text was selected.
- Where a PII column had to be matched, for example linking an OTP recipient to an account, the join ran **inside the database** and only counts came back.
- Queries were bounded by the 31-day OTP window or sampled. One query hit the 20-second timeout and was rewritten, not retried as-is.
- Blocked databases were queried only through catalog views: `pg_class`, `pg_attribute`, `pg_constraint`, `pg_index` and `pg_stat_*`.
- About 150 data queries ran on the users DB, identified in the inputs as U, T, G, N, R, X, S, A, B and C series.
- **No privilege workaround was attempted.**

## Critique loops

Every profile went through two to four rounds of adversarial critic review, and every theme through at least one:

| Document | Final revision |
|---|---|
| users | v3 |
| cross-db | rev 3 |
| orders-funnel | v4 |
| orders-customer-catalog | rev 5 |
| emapi-stores | rev 4 |

Each round re-ran queries and corrected claims. Corrections carried into this report include:

- `2fa_account_verification` is the **gift-recipient claim** step, not login 2FA.
- `is_valid=false` on an OTP means the code was superseded or unused. It is not a wrong-code count.
- The Aug 2026 blacklist spike was the rule engine firing on a bot wave, not a spreadsheet import.
- `last_login` is a frozen legacy timestamp, not a dead column.
- The "59.5% basket abandonment" figure is wrong, because at least about 40% of baskets are empty.
- The deletion gap for gift-acquired users is 2.0x once corrected for survivorship, not 3.7x.

## Evidence labels

| Label | Meaning | Where it can apply today |
|---|---|---|
| **VALIDATED** | Backed by a data query that was actually run, or by a profile's SQL appendix | Users DB only |
| **STRUCTURAL** | Inferred from schema or metadata only: column types, constraints, `reltuples` estimates, physical size, replica read counters. May include reasoning on top of those facts. | Everything about orders, ecomweb and emapi |
| **NEEDS-GRANT** | A hypothesis that needs data we cannot read today. The exact table and columns are named. | Consolidated in GRANTS.md |

Two further conventions:

- **[inferred]** marks reasoning on top of a labelled fact. It is never a measurement.
- The users DB is live, so figures drift by about 0.1% within a day. Each figure is as of 2026-09-29, with query times in the source files.

# Data landscape

## ygag_ecom_users_db: identity microservice (readable)

**Purpose.** The Django identity and auth service. It holds:

- the consumer account master;
- alternate emails;
- OTP requests and verifications;
- issued Cognito-style login tokens;
- a cross-service blacklist and whitelist fed by Kafka;
- operations configuration: captcha, OTP routing, templates and the throttle rule engine.

It holds no orders, payments, gifts or campaigns.

**Key entities and volumes** (VALIDATED, exact)

| Entity | Table | Rows | Notes |
|---|---|---|---|
| Account | `users_user` | 996,283 (974,175 live, 22,108 soft-deleted) | Key `username` (UUID). About 23k signups a month. |
| Alternate identity | `users_secondaryuseridentity` | 76,175 (72,637 live) | At most 1 live alternate email per user |
| Identity events | `users_useridentityactivitylog` | 83,910 | 59,595 `secondary_email_added_via_gift` since 2024-08-05 |
| Login tokens | `users_cognitoissuedtokens` | 59,964 | App from 2026-07-13, web from 2026-08-29. Life is 548 days (app) and 30 days (web). |
| OTP requests and verifications | `notifications_twofactorauth` (+ `...verification`) | 68,465 each | Rolling **31-day** retention |
| Blacklist / whitelist | `core_blacklisteduserdetail` / `core_whitelisteduserdetail` | 8,760 / 119 | 81% of blacklist rows come from ecom_users, and 83% of those are rule-generated |
| Kafka consumer / producer logs | `kafka_clients_*` | 5,113 / 14,150 | 1,298 consumer rows stuck `in_progress` |
| Legacy migration log | `users_migratedtransactionlog` | 171,232 | Gives the legacy dimension: linked 57,754, shell 110,937, native 827,585 |

**Lifecycle states** (VALIDATED)

- **Account:** `is_deleted` is the real state flag; `is_active`/`is_enabled` are almost constant.
- **Legacy state:**

  | State | Accounts |
  |---|---|
  | linked | 57,754 |
  | shell | 110,937 |
  | native | 827,585 |

- **Identity activity** has four kinds: added via gift, self-added, removed, phone updated.
- **OTP flows:** sign_up, sign_in, `2fa_account_verification` (the gift-claim step) and two change-phone flows.
- **Blacklist types:** email, domain, mobile, ip, device and sms_country_code.

**Data quality traps** (VALIDATED)

- **Dead fields:**
  - `type` since Oct 2023;
  - social-login ids since Dec 2024;
  - `platform` since 2024 (always "other");
  - `app_version` (100% NULL);
  - `whatsapp_delivery` (never true);
  - `email_verified` and `phone_number_verified` (constant).
- **Regime cutovers:**
  - `is_app_user` was redefined in Aug 2024;
  - the id-sequence gap closed in May 2025, so signup counts are not comparable across that month;
  - gender became mandatory in May 2025;
  - birthday capture doubled in Nov 2025.
- **`birthdate`** is `0000/DD/MM`, a birthday with no year, on 369k users. `0000/01/01` (9,940 rows) is a default value.
- **Soft delete** encrypts email and phone, and `modified_on` is not a deletion date.
- **Security finding (VALIDATED grant state):** the atlas role can read **all 40 tables**. That includes credential and secret columns (`core_remoteurlconfig.api_key/api_secret`, password hashes, TOTP keys) and raw PII. GRANTS.md section 3 proposes least-privilege views and a phased revoke.

## ygag_ecom_orders_db: transactions (metadata only)

**Purpose.** The Django-Oscar consumer ecommerce app:

- baskets, orders and line money (multi-currency);
- personalisation: occasion, greeting, schedule, reminder, recipient;
- two payment tables (youpay and `payment_paymentdetail`);
- the Kafka gift-creation log;
- guest checkout;
- its own blacklist;
- a gift-card catalog modelled as `catalogue_product`;
- Plus-Offer campaigns;
- config tables that gate checkout.

**Key entities and volumes** (STRUCTURAL). Every count is a planner estimate extrapolated to 2026-09-29 by page growth (orders-funnel Q20), so all ratios use one basis. Where the raw estimate differs, it is shown in brackets.

| Entity | Table | Rows (est.) | Notes |
|---|---|---|---|
| Basket | `basket_basket` / `basket_line` | 3,046,354 / 1,824,296 | 0.60 lines per basket, so at least about 40% of baskets are empty. No date or status index; 0 reads on the replica. |
| Order | `order_order` / `order_line` | 1,233,955 / 1,473,029 | 63 columns. PII is denormalised on the order row. |
| Line money | `order_orderlinequantitydetail` | 1,480,661 [1,474,250] | 1:1 with lines. Use the reporting-currency columns for revenue. |
| Personalisation | `order_orderlinepersonalisedetail` | 513,374 [496,737] | `occasion_code`, `delivery_date`, `is_reminder_added`, recipient email/phone |
| Payment | `youpayclient_youpayclienttransactiondata` / `payment_paymentdetail` | 1,238,225 / 769,659 | youpay has **no uniqueness** on `order_reference`, so its per-order cardinality is unknown. paymentdetail is 0..1 per order and covers about 62% of orders. |
| Gift issuance | `kafka_giftcreationlog` | 3,256,033 [3,134,464] | 2.64 events per order (2.54 on raw estimates), unexplained. No index on `order_id`. |
| Status log | `order_orderstatuschange` | 1,209,722 | 0.98 rows per order, so probably incomplete |
| Guests | `users_guestuser` / `users_mergeduser` / `basket_mergedbasket` | 82,502 (no growth) / at most ~3.7k / at most ~1.2k | Includes `last_accessed` and `platform` |
| Blacklist | `users_blacklisteduserdetail` | 48,646 (no growth) | About 5.6x the identity blacklist. Not a replica of it. |
| Catalog / offers | `catalogue_product` / `offer_plusoffer` | 3,442 / 378 | Redemption join: `order_line.offer_code` = `plusoffer.code` |

**Lifecycle states.** All status columns are free varchar with no enums or checks. Value sets are NEEDS-GRANT: `order_order.status`, `order_line.status`, `basket_basket.status`, youpay `approved/payment_status/response_summary`, and `kafka_giftcreationlog.status`.

**Data quality** (STRUCTURAL)

- 30 of the 50 funnel tables are empty (0-byte heap), including all Oscar voucher, discount, address and shipping-event tables.
- Fee rates are stored as varchar.
- FX keeps only current rates (437 pairs).
- The replica serves one heavy reader nobody can identify: about 25.6 full-size youpay scans a day.
- `order_line.upc` is NOT NULL but `product_id` is nullable. Brand joins must use `upc`.
- **No referral, UTM or refund columns exist.**

## ygag_ecomweb_stores_db: web storefront (metadata only)

**Purpose.** The web storefront backend:

- a brand catalog of 3,243 listings, with denominations, tags, occasions and generic cards;
- Plus-Offer definitions;
- a 54-table CMS;
- reference data;
- a Cognito user mirror (`users_cognitouser`, about 980k rows);
- `configurations_lastviewedbrand` (about 59.9k rows), its only per-user behaviour table.

**Volumes and behaviour** (STRUCTURAL; replica counters over a 35.5-day window)

- `brands_brand` primary key: 8.52B index scans.
- Tag landing lookups: 28.1M. Brand-slug lookups: 1.47M. Search-keyword lookups: about 36k. So **discovery runs through tags and categories, not search**.
- `configurations_upcomingoccasion` and `announcement` are empty tables that are still polled 89k and 52k times.
- Webhook and Kafka logs are purged to 0 rows.

**Data quality** (STRUCTURAL)

- `users_cognitouser` has no `last_login` and no `date_joined` index.
- `lastviewedbrand` has no `username` index and no uniqueness on (user, brand), so every read is a full scan.
- Visibility flags are nullable. Treat NULL as unknown, never as false.
- `configurations_sliderbrand.brand_id` points at `brands_tagbrand`, not at brands.

## ygag_emapi_stores_db: app stores service (metadata only)

**Purpose.** The EMAPI stores service. It holds:

- the **master catalog**: 6,610 brand listings across 12 channel-visibility flags, with denominations, generic cards and redemption-friction flags;
- app merchandising;
- Plus Offers, promo codes and per-user avails (`users_useravailedoffer`, 6,487 rows);
- favourites (`brands_favouritebrand`, 19,821 rows);
- a consumer mirror (`users_user`, 992,399 rows) with `last_login`, `app_version`, `is_fraud`;
- four Kafka ingest logs (about 2.87M rows);
- forced-upgrade configuration.

**Data quality** (STRUCTURAL)

- **Missing uniqueness** means duplicates are possible in `brands_hasofferbrands`, `users_useravailedoffer`, `brands_offerpromocode.promo_code`, `brands_generic_brand_item` and `emapi_generics_client_mobileappplatformversion`.
- **Sync-churn bloat:** `hasofferbrands` estimates swing about 20%.
- **Kafka logs** have no topic, offset or attempt columns.
- **The replica sees almost no app traffic** (408 commits), so read counters cannot stand in for app browsing.

## Cross-database identity map

**The canonical user key is the UUID `users_user.username`, not any numeric id.**

- Every service that talks to identity (gifts, orders, group gift, legacy) identifies registered users by that UUID (VALIDATED).
- The numeric ids come from four independent generators and must never be joined across databases (STRUCTURAL).

| Database | User table | Rows | Link to canonical key | Status |
|---|---|---|---|---|
| users | `users_user` | 996,283 | `username` (UUID) | VALIDATED |
| orders | `users_customuser` + 1:1 `users_userprofile` | 996,517 extrap. [991,558] / 978,022 est | `userprofile.cognito_id` (UNIQUE NOT NULL) | Hypothesis, test V2 (NEEDS-GRANT) |
| ecomweb | `users_cognitouser` | 980,177 est | `username` (varchar 150, UNIQUE) | Hypothesis, test V2 (NEEDS-GRANT) |
| emapi | `users_user` | 992,399 est | `username` (varchar 150, UNIQUE) | Hypothesis, test V2 (NEEDS-GRANT) |

Other keys and rules:

- **Legacy crosswalk:** `legacy_auth_code[]` covers 57,757 users and also exists in the ecomweb and emapi mirrors (hypothesis V7).
- **Brand key:** orders `order_line.upc` → `catalogue_product.upc`, which is believed to equal `brands_brand.code` in the stores DBs (hypothesis V3).
- **Offer key:** `plusoffer.code`, identical in all three commerce DBs (STRUCTURAL). Atlas reads it only as the keyed `offer_code_key` (GRANTS.md §4.3, test V16), because the code may be one customers type at checkout.
- **Guests** have no cross-DB identity. `users_mergeduser` and `basket_mergedbasket` are the only guest-to-registered links.
- **`is_guest` on blacklist rows is not a reliable guest flag**, and the orders → users Kafka blacklist payload puts registered usernames into its `guest_id` field (VALIDATED). This is the payload field, not the `order_order.guest_id` column, which is a bigint FK to `users_guestuser.id` (STRUCTURAL).

## End-to-end user journey

| # | Step | Where the data lives | Readiness |
|---|---|---|---|
| 1 | Signup | users `users_user` | VALIDATED, ready now |
| 2 | Verify (OTP) | users OTP tables (31-day retention) | VALIDATED, ready now (needs a snapshot) |
| 3 | Login | users `users_cognitoissuedtokens` | VALIDATED, but only since Jul/Aug 2026 |
| 4 | Browse (web) | ecomweb `configurations_lastviewedbrand`, replica counters | NEEDS-GRANT; not a clickstream |
| 4b | Browse (app) | emapi `brands_favouritebrand` | NEEDS-GRANT; favourites only |
| 5 | Brand choice | emapi, ecomweb `brands_brand`; orders `catalogue_product` | NEEDS-GRANT; crosswalk unverified |
| 6 | Basket | orders `basket_*` | NEEDS-GRANT; needs an extract |
| 7 | Order | orders `order_order`, `order_line`, personalisation | NEEDS-GRANT |
| 8 | Payment | orders youpay and `payment_paymentdetail` | NEEDS-GRANT; dedup first |
| 9 | Gift creation | orders `kafka_giftcreationlog` | NEEDS-GRANT |
| 10 | Delivery / notify | **No data** in the four DBs (mailengine, smsengine) | Needs a new source |
| 11 | Recipient claim | users `secondary_email_added_via_gift` | VALIDATED; lower bound |
| 12 | Redemption / sold | orders `sold_date` (partial); gifts DB | Needs grant or a new source |
| 13 | Offers | orders `offer_code`; emapi avails; plus-offers ledger | NEEDS-GRANT / new source |
| 14 | Post-purchase | orders `reviews_googlereview` (prompt state per user) | NEEDS-GRANT |

**Journey steps with no data in any of the four DBs:**

- page views, search and clickstream;
- acquisition and attribution (UTM, campaign, install source);
- referral programme;
- message send and delivery, including OTP delivery receipts;
- a general marketing-consent store (only the small ecomweb newsletter opt-in table exists, STRUCTURAL);
- gift issuance state, recipient open and redemption;
- refunds and chargebacks;
- loyalty ledger;
- wallet;
- group gift;
- @Work B2B orders.

# Insights by theme

The strongest findings from each theme, deduplicated.

## A. User lifecycle and acquisition

| # | Insight | Label |
|---|---|---|
| A1 | **Many gift recipients sign up just to claim.** 26,737 users signed up no more than 1 day before their first gift claim (23,994 within 1 h). That is 3.2–6.3% of monthly signups since Aug 2024. Among users who joined after the log started and later claimed, 69% claimed within a day of signup. This is a lower bound: the event only covers claims into a non-primary email, and the log starts 2024-08-05. Reading this as an acquisition channel (the gift caused the signup) is [inferred]. | VALIDATED |
| A2 | **Gift-acquired users are clean but not sticky.** Blacklist match is 0.02% against **up to 0.76%** for organic signups (an upper bound: email, domain and mobile matches are summed and can overlap; U20), and shared devices 0 against 0.54%. Among accounts that survived day 1, deletion is 0.39% against 0.76% (2.0x; the raw 3.7x is survivorship-biased). Return after 7 days, measured only for **app** users in one cohort (joined 2026-07-15 to 2026-08-31, not deleted): 2.2% of gift-acquired app signups (26 / 1,208) against 3.3% of other app signups (744 / 22,371) got a token more than 7 days after signup (G11; pooled z = 2.24). It is not an all-users comparison. | VALIDATED |
| A3 | **Returning activity is almost invisible.** About 10.5k returning users a month, roughly 1.1% of the live base, get a new token. This is a floor, not MAU: app tokens live 548 days and web tokens 30. 67% of tokens are first logins right after signup. App and web rates are not comparable. | VALIDATED |
| A4 | **Legacy "shell" accounts are a win-back pool, not junk.** 110,937 shells were created by the 2023 migration. They reactivate at 0.93% in 30 days, the same rate as native 2023 users, and 1,557 already hold new-platform tokens. | VALIDATED |
| A5 | **Every lifecycle trend crosses signup-flow cutovers.** `is_app_user` was redefined in Aug 2024. In May 2025 the id-sequence gap closed and gender became mandatory. In Nov 2025 birthday capture doubled (22% → 42% → 53%). `type` has been dead since Oct 2023 and social ids since Dec 2024. Unannotated trends across these dates are wrong. | VALIDATED |
| A6 | **SA overtook AE.** SA's share of signups rose from 43.3% (2024) to 49.3% (2025) to 50.3% (2026 YTD), while AE's fell from 43.7% to 37.1%. AE peaks on Friday and SA on Thursday. SA acts in the evening (46.5% of signups between 16:00 and 23:00 local); AE is flat through the day. Farmed residence cohorts (AM 2,439 on 13 days in 2024; CH 2,890 in 2025; MX 818) must be flagged. | VALIDATED |
| A7 | **Deletion is mostly signup regret.** Of the 5,644 accounts created since Jun 2025 that were later deleted, 42.5% were deleted within 1 h of signup and 60.4% within a day. `modified_on` is only an upper-bound proxy for deletion time; there is no `deleted_at`. | VALIDATED (with caveat) |
| A8 | **No acquisition, UTM or referral data exists** in any of the four DBs. | VALIDATED (users) / STRUCTURAL (others) |
| A9 | **Guest checkout identities could feed a guest-to-account funnel.** There are 82.5k–88.7k of them, with `last_accessed` and `platform`. | STRUCTURAL |

## B. Purchase flows and friction

| # | Insight | Label |
|---|---|---|
| B1 | **The first resend is the cliff.** Canonical definition (metric `signup_registration_by_code_count`, golden H02): **per email recipient over 31 days, 82.7% register after 1 code and 56.8% after 2 or more** (11,812 / 14,284 against 1,540 / 2,712; T18). The chain-level view (10-minute chain rule, U3) gives 80.7% and 56.7% for email and 95.8% and 63.5% for phone; it is reported as a secondary breakdown, never mixed with the canonical figure. Other windows give 78–83% falling to 48–59%. 13.9% of email chains need a resend, against 2.2–2.7% of SA/AE phone chains. | VALIDATED |
| B2 | **Unconfigured SMS countries fail.** Phone signups from countries with no routing config never get an accepted code 23.3% of the time, against 2.7% for SA/AE (8.6x). US/CA: only 133 of 267 numbers (49.8%) became accounts, so about 50.2% never register; at chain level, 53.5% of +1 chains get no accepted code (N25). That the cause is carrier A2P filtering is [inferred]. | VALIDATED |
| B3 | **1,756 email recipients per 31 days had a code accepted but never registered.** They are a separate "finish your account" audience. | VALIDATED |
| B4 | **The readable data has no checkout OTP.** Purchase-time friction is card 3DS (youpay `verify_url`) and brand-level mobile verification. | STRUCTURAL |
| B5 | **The structural funnel is 3.05M baskets → 1.23M orders**, but at least about 40% of baskets are empty. "59.5% abandonment" must not be published. | STRUCTURAL |
| B6 | **Payment and issuance metrics are traps until deduplicated.** youpay has 100.3% of the order count with no uniqueness; paymentdetail covers 62%; there are 2.64 gift events per order (extrapolated basis; 2.54 on raw estimates); the status log has 0.98 rows per order. | STRUCTURAL |
| B7 | **Checkout friction is encoded as config, so causes are enumerable.** Currency caps (8), denomination ranges (11,376), fee rules (939), unsupported countries, 20 payment methods, promo limits and a 48.6k blacklist, all dateable through `django_admin_log`. | STRUCTURAL |
| B8 | **Personalisation is common.** 31–35% of basket and order lines carry a personalise row (occasion, schedule, reminder). | STRUCTURAL |

## C. Gifting network and referrals

| # | Insight | Label |
|---|---|---|
| C1 | **The gift-claim event is the only readable network edge.** 59,595 events for 59,496 users. Gift-created emails are 81% of live alternate identities. There is a one-alternate-email-per-account cap. | VALIDATED |
| C2 | **Within the claim event, 72–74% of emails are work emails, but this does not describe all gifts.** 76% of signups have a freemail primary, and gifts sent to a primary email leave no event. | VALIDATED (event only) |
| C3 | **Corporate gifting is mostly re-engagement.** Large org domains have a 31.4% new-user share against 44.0% for freemail. The largest burst day had 9.7% new users. | VALIDATED |
| C4 | **Bursts are single-company and occasion-timed.** On 2026-03-09, 730 claims came in and 84.8% were from one domain (27.8% of March). Burst domains burst again in the same season 40% of the time, against 3.9% for other active domains (n = 20 domain-seasons). | VALIDATED |
| C5 | **Claims do not re-engage existing users.** 1.23% against 1.10%, pooled z = −0.37, n = 894, on a weak login proxy. | VALIDATED |
| C6 | **Recipients are 1.57x more likely to claim in their birth month**, and 2.6x within ±3 days of the birthday. | VALIDATED |
| C7 | **Gift-acquired share of signups by country:** QA 8.2%, AE 5.9%, SA 3.65%. | VALIDATED |
| C8 | **A small identity-collision queue exists.** 164 claims bound an email that is another account's primary; 31 emails are shared across 2–3 users; 24 users bound 2 or more distinct emails, one of them 19. | VALIDATED |
| C9 | **The recipient has no user id in orders.** The sender-to-recipient edge (k-factor) needs a keyed hash of `order_orderlinepersonalisedetail.email_address`, matched to users-side hashes. | STRUCTURAL / NEEDS-GRANT |

## D. Campaigns, triggers and personalisation

| # | Insight | Label |
|---|---|---|
| D1 | **Three lifecycle triggers are computable today.** Birthdays: 26,833 in the next 30 days excluding shells (T3), 31,004 including them (U5; the two queries also differ slightly in window). OTP rescue: 3,644 of 16,996 email recipients (21.4%) never ended with an account. Gift-acquired recipients: about 0.9–1.9k new accounts a month (893 in Sep 2026; 1,851 at the Dec 2024 peak; gifting G4), the per-month trigger volume behind H09. The 26,737 total is cumulative since 2024-08-05 and is not a monthly audience. | VALIDATED |
| D2 | **Birthday coverage.** 303,223 of 868,696 live non-shell users (34.9%) have a usable birthday. The share is 47.0% among recent token holders. Needs a local-date rule, 29 Feb handling (144 users) and exclusion of 50 impossible dates. | VALIDATED |
| D3 | **An occasion calendar can be seeded now.** Measured: SA 2025-03-26 signups 8.5x and gift claims 9.7x; AE spikes 42–62% female against a 26.8% baseline; Saudi National Day 2025 lifted SA signups only about 1.5x, while Sep 22–24 2026 ran 2.6–3.4x. Inferred: 2025-03-26 is a pre-Eid effect, and the 2026 tripling is a campaign on top of the occasion rather than a calendar effect [inferred]. Occasion labels come from dates, not from send logs. | VALIDATED (ratios); causes [inferred] |
| D4 | **Mother's Day 2026 showed no signup lift and no female shift.** Those campaigns must target senders (NEEDS-GRANT on orders). | VALIDATED |
| D5 | **No general marketing-consent store exists.** The only opt-in table is the small ecomweb newsletter table `configurations_emailsubscription` (`is_subscribed` by platform; row count unknown). It is a consent baseline for the web newsletter only. | VALIDATED (users) / STRUCTURAL |
| D6 | **Suppression is computable.** 5,544 live users on promo-blocked domains, 3,316 on blacklisted domains, 903 blacklisted by email or mobile. | VALIDATED |
| D7 | **Trigger overlap is 3.8%** (2,039 of 54,243 eligible users). A frequency cap and priority order are needed. | VALIDATED |
| D8 | **The identity service sends only transactional templates**, and `password_expiry_warning` has no Arabic version. | VALIDATED |
| D9 | **Plus Offers are the only live promo mechanism.** They exist in three copies with three different "usage" numbers. Oscar vouchers are physically empty. | STRUCTURAL |

**Shell-account rule by audience.** A migration "shell" is an account the 2023 migration created for a legacy customer who never used it on the legacy side (110,937 in total, 105,501 live). Shells are not junk: 1,557 already hold new-platform tokens, and they reactivate at 0.93% in 30 days, the same rate as native 2023 users (A4, VALIDATED). Each audience therefore states its rule explicitly:

| Audience or metric | Shells | Count basis | Why |
|---|---|---|---|
| Birthday audience (AF-04) | **Excluded** by default | 26,833 in the next 30 days | The owner has never used the account, so a "treat yourself" send reads as unsolicited |
| Welcome-back segment (AF-11) | **Only** shells and linked legacy accounts | 105,501 live shells; about 4.2k of them have a birthday in the next 30 days (31,004 − 26,833; the two queries differ slightly in window) | Win-back pool; the birthday is a hook inside this message, not a second send |
| Suppression segment (AF-10) | Evaluated like any account | All live accounts | Risk rules apply regardless of legacy state |
| Signup metrics (AF-02, AF-25, AF-31) | Excluded | Native signups | Shells were created by a batch migration, not by a signup |
| Login and retention floors (AF-18, AF-56) | Reported as a separate `legacy_state` band | All live accounts | Shell reactivation is a win-back outcome, not organic retention |
| Risk and deletion comparisons (AF-16, AF-19) | Excluded from denominators | Native signups | Shells never had a signup day |

## E. Errors and system behaviour

| # | Insight | Label |
|---|---|---|
| E1 | **A gift-claim OTP incident on 2026-09-22 was visible end to end.** Chains rose from about 87 a day to 535, and 74.8% failed. 85.1% of them went to one corporate domain. Tokens peaked at z = 6.0. A simple z-score alert would have fired within hours. | VALIDATED |
| E2 | **The fraud feed from gifts, orders and group gift into identity went silent for about 9 months, and no alert fired.** It stopped 2025-05-12. Gifts resumed 2026-02-12 and orders 2026-02-22; group gift never did. There were 0 ecom_gifts blacklist rows from Jun 2025 to Jan 2026. | VALIDATED |
| E3 | **1,298 orders → users blacklist requests are silently unapplied.** 396 of them are for 389 registered users and are still arriving (last 2026-09-28). The probable cause is a payload missing `mark_as_fraud`/`reference_id`. `error_data` is empty on every row. | VALIDATED |
| E4 | **Producer `status=completed` means published, not delivered.** 5.2% of blacklist adds were published more than 1 h late (an upper bound). | VALIDATED |
| E5 | **Config edits and blacklist surges coincide.** Site-config edits fell on 64 of 486 days, and those days carry 50% of rule-generated and 92% of analyst blacklist rows. All 7 days with 50 or more rule rows are config-change days. | VALIDATED |
| E6 | **The whitelist overrides the blacklist for 13 SMS countries.** 15 entries are active on both lists, and the country codes are stored in mixed case. | VALIDATED |
| E7 | **Force-upgrade exposure cannot be measured from identity data.** `app_version` is 100% NULL, and user-agent OS versions are frozen ("Android 10", "iOS 18"). The emapi mirror is the only path. | VALIDATED / STRUCTURAL |
| E8 | **Replica load.** The orders reader carries an unidentified reader doing about 25.6 youpay full scans a day. The ecomweb storefront reads config on every request and polls empty tables. The users replica is almost idle, so atlas reads there are cheap. | STRUCTURAL |

## F. Catalog and brand intelligence

| # | Insight | Label |
|---|---|---|
| F1 | **There are three catalog copies.** emapi is the master (6,610 listings); ecomweb has 3,243 and orders 3,442. A listing belongs to one store, so a brand sold in AE and SA is two rows. No brand-to-country M2M exists. | STRUCTURAL |
| F2 | **Order lines key brands on `upc`** (NOT NULL); `product_id` is nullable. The `upc` to `code` crosswalk is unverified. | STRUCTURAL |
| F3 | **Web discovery runs through tags and categories.** Tag lookups outnumber search-keyword lookups about 780x (28.1M against 36k). Tag, shop-category and offer positions are the main merchandising levers. | STRUCTURAL |
| F4 | **Price structure:** about 6.5–7 fixed denominations and about 3.5 open ranges per listing, with a pre-selected default. Anchoring on the default is measurable once granted. | STRUCTURAL |
| F5 | **Generic Happy Cards hide a large catalog.** 533,305 items over 3,381 configs, with no uniqueness. | STRUCTURAL |
| F6 | **Browse signals are thin.** Recently-viewed (59.9k rows, capped) and favourites (19.8k). No clickstream exists in Postgres. | STRUCTURAL |
| F7 | **Demand facts.** 39.1% of Saudi OTP recipients use Arabic, against 0.4% in the UAE. Gift claims peak in December and March. Birthdays run 27–33k a month. | VALIDATED |
| F8 | **Unused surfaces.** Cross-sell (`crosssellbrand`) and "upcoming occasion" slots exist but are empty, so atlas-computed affinity could fill them. | STRUCTURAL |

## G. Risk, fraud and data integrity

| # | Insight | Label |
|---|---|---|
| G1 | **A live account farm.** Since 2026-09-26, 83 RU/+7 web accounts (36, 17, 3 and 27 per day, against a baseline of about 0.3 a day). 81 of them log in from German IPs, with only 5 browser builds between them. None is blacklisted. The RU SMS block was removed on 2025-10-16. | VALIDATED |
| G2 | **The blacklist gates signup but does not revoke existing accounts.** 0 of 59 blocked signup addresses became accounts. But 903 blacklisted accounts are live, 12 got 18 tokens after blacklisting, and 8 accounts with a max-login-attempts entry logged in again. | VALIDATED |
| G3 | **The two largest blacklist spikes were rules, not imports.** Aug 25 (797 rows) and Jun 23–24 (381 rows) were the rule engine firing on bot waves. They do not mean fraud grew. | VALIDATED |
| G4 | **Risk fingerprints separate risky accounts.** Shared app devices show about 22x blacklist lift; SA/AE residents with tokens from outside the GCC about 13x. Blacklist status is a biased label (mostly set by rules at signup). | VALIDATED |
| G5 | **Farms are narrow, not voluminous.** Measured: the burst-hour cohort (2,330 signups) is 73.1% SA with baseline deletion (1.55%) and mismatch rates, while the RU farm peaked at 36 a day and never formed a burst hour; same-minute domain clusters of 10 or more do not occur in 2026. Inferred: the bursts are acquisition campaigns, not farms, so a volume alert misses farms and a cluster-fingerprint alert catches them [inferred]. | VALIDATED (measures); causes [inferred] |
| G6 | **Soft delete encrypts email and phone.** Blacklist matching and re-signup detection are blind to deleted accounts. | VALIDATED |
| G7 | **Two blacklists and three fraud flags do not agree.** The users list has 8,760 rows, the orders list about 48.6k. `is_fraud` exists in emapi, paymentdetail and youpay. | STRUCTURAL |
| G8 | **Exclude non-customer accounts.** 3 QA automation accounts (13 tokens) and 42 staff accounts must be kept out of risk and login denominators. | VALIDATED |

# Hypothesis catalog

Readiness values:

- **ready-now:** the test runs on the users DB alone. It may need an app change or a send channel.
- **needs-grant, tier N:** needs rows from orders, emapi or ecomweb; the tiers are those of GRANTS.md (section 8 has the full map).
- **needs-new-source:** needs a database outside the four.

Each row also carries its evidence label: what is VALIDATED today, and what is NEEDS-GRANT.

**Priority** (proposed; to be confirmed by the owners):

- **P1:** high expected value **and** runnable this quarter (ready-now, or tier 1 only). A live-incident tie (E1–E6) makes a runnable hypothesis P1 only when its test contains or sizes that incident (H29, H30, H33); a clean-up test next to an incident stays P2 (H05, H72). A hypothesis that needs tier 2 or later is never P1.
- **P2:** high value, but needs tier 2 or later, a consent decision, or a larger build; or runnable (ready-now or tier 1) with a medium expected value.
- **P3:** small n, diagnostic, or needs a new source.
- **Prerequisites:** a hypothesis whose test needs a feature first is scheduled after that feature, and the feature inherits the hypothesis's urgency in the feature ranking. The needed features are listed per hypothesis in the "Hypothesis prerequisites" table of the feature catalog, and the inherited score is computed there by one formula.

**Owner** is a proposed role, not a named person. Expected value is an order-of-magnitude estimate built on the VALIDATED baselines; it is not a forecast.

| id | Priority | Hypothesis | Owner (proposed) | Expected value | Test | Data needed | Readiness · evidence |
|---|---|---|---|---|---|---|---|
| H01 | P1 | Signups needing 2+ codes are at least 20–30% less likely to order within 7 days | Growth PM | Puts a money value on OTP friction for about 1.5k multi-code signups per 31 days (1,540 of the 2,712 multi-code email recipients registered; T18) | Chain length (from the snapshot) → first `date_placed`, controlling for country and channel | users OTP; orders `order_order(user_id, date_placed, status)`, `atlas_ro.user_profile(user_id, user_key)` | needs-grant, tier 1 · NEEDS-GRANT (registration gap VALIDATED) |
| H02 | P1 | Offering a phone OTP after the first email resend lifts multi-code registration by at least 10 pp (57% → 67%+) | Identity product manager | +10 pp on about 2,700 multi-code recipients a month, about 270 more registrations a month | 50/50 on recipient hash; about 2,700 multi-code recipients a month gives an MDE of about 5.3 pp | users OTP | ready-now · baseline VALIDATED (82.7% / 56.8%, T18) |
| H03 | P1 | A fixed Arabic email template lifts Arabic claim-OTP acceptance from 46.0% to the English level of 73.8% | CRM lead, with the identity PM | Base: about 987 Arabic `2fa_account_verification` chains per 31 days, 454 accepted (46.0%). At 73.8% that is about 274 extra accepted chains per 31 days, about 220 of them gift claims (about 81% of the flow is gift-related, U14b). An upper bound on claims, because a user can retry in a new chain (user-lifecycle H2, I12) | A/B on the template; guardrail is resend share | users OTP | ready-now · baseline VALIDATED |
| H04 | P2 | WhatsApp as the claim-OTP channel raises recipient claim rate from about 74% toward about 97% | Identity product manager | Up to +23 pp on about 3.2k claim recipients per 31 days; needs a WhatsApp template | A/B on claim channel; claims within 1 h per recipient | users OTP + activity log | ready-now · baseline VALIDATED; lift is a hypothesis |
| H05 | P2 | Direct routes for US/CA and UK (WhatsApp or voice) cut never-accepted rates to 10% or less | Messaging / SMS operations | At most about 130 lost US/CA phone signups a month | Diff-in-diff by prefix, 4 weeks before and after | users OTP; `ygag_smsengine_db` delivery receipts for the mechanism | ready-now · baseline VALIDATED; mechanism needs a new source (smsengine) |
| H06 | P1 | A failed sign-in predicts dormancy (44.7% have no token in 7 days, against 5.6% after success); a same-day fallback nudge halves it | CRM lead | About 450 failed sign-ins a month with no token in 7 days; halving it recovers about 200 users a month | Randomise the nudge among failed, no-token users | users OTP + tokens | ready-now · baseline VALIDATED (U22) |
| H07 | P1 | A "finish your account" link within 1 h registers 20%+ of accepted-but-unregistered recipients (1,756 per 31 days) | Growth PM | 20% of 1,756 per 31 days, about 350 more accounts a month | 80/20 holdout; registered within 72 h | users; send via mailengine | ready-now · baseline VALIDATED (T18) |
| H08 | P1 | Gift-acquired users place a first order within 90 days at 0.8x or less of organic signups, but repeat at 1.2x or more once they buy | Marketing analytics lead | Decides whether recipient onboarding deserves budget (3–6% of signups) | Cohorts by acquisition class (joiners since 2024-08-05, day-1 survivors) | users + orders `order_order`, `atlas_ro.user_profile.user_key` | needs-grant, tier 1 · NEEDS-GRANT (cohort VALIDATED) |
| H09 | P2 | A post-claim onboarding push ("send one back") raises 30-day first purchase by 20%+ relative | Growth / CRM lead | +20% relative first purchase on about 1–2k gift-acquired signups a month | Holdout RCT; login is only a guardrail (it needs about 20k per arm) | users + orders | needs-grant, tier 1 · NEEDS-GRANT (login gap VALIDATED) |
| H10 | P3 | A same-day follow-up to existing-user claimers doubles 30-day return (1.2% → 2.5%+) | CRM lead | Small: 1.2% → 2.5% return on about 900 users per arm | Holdout RCT randomised by claim day; about 900 per arm over about 2 months | users tokens (weak proxy) | ready-now · baseline VALIDATED (weak login proxy) |
| H11 | P1 | Pre-season outreach raises the corporate burst-again rate from 40% to 55%+ | B2B / @Work sales lead | About 9 bursts a year; +15 pp re-burst is one or two extra corporate drops a season | Randomise the season burst list, pooled across seasons | users claims; @Work DBs for revenue | ready-now · backtest VALIDATED; revenue NEEDS-GRANT (also needs a new @Work source) |
| H12 | P2 | A birthday-week "treat yourself" offer lifts 14-day self-purchase by 2 pp+ against a 10% holdout | CRM lead | Up to about 540 self-purchases a month (2 pp of 26.8k); blocked on consent (AF-79) | 90/10 on `hash(username)`; local-date send | users birthdate; orders `is_buy_for_self`, `order_order` | needs-grant, tier 1 · NEEDS-GRANT (audience VALIDATED) |
| H13 | P2 | A "birthday in 7 days" nudge to past senders raises gifts to that recipient by 15%+ | CRM lead | Occasion-timed repeat gifting; the 1.57x birthday-month lift is the premise | RCT on sender-recipient pairs | orders personalise recipient HMAC + users hashes | needs-grant, tier 2 · NEEDS-GRANT (1.57x lift VALIDATED) |
| H14 | P2 | A shell-account win-back gets more than 3% login and more than 1% purchase in 30 days (baseline 0.93% login) | Marketing lead | 1% purchase on 105,501 live shells is about 1,000 orders | Holdout on shell accounts | users + orders | needs-grant, tier 1 · NEEDS-GRANT (0.93% baseline VALIDATED) |
| H15 | P3 | Local send windows (SA 16:00–22:00, AE 10:00–18:00) lift 24-h action by 15%+ relative against a fixed 10:00 send | Marketing operations | Modest relative lift on existing sends | 50/50 send-time test per country | users; mailengine for opens | ready-now · send-time profile VALIDATED; opens need a new source (mailengine) |
| H16 | P2 | Senders who set `is_reminder_added` reorder within ±14 days of the anniversary at 2–3x the rate of others | CRM lead | Anniversary reorders on about 513k personalised lines | Occasion-line cohorts, then order 350–380 days later | orders `order_orderlinepersonalisedetail`, `order_line`, `order_order` | needs-grant, tier 2 · NEEDS-GRANT |
| H17 | P2 | "Viewed brand, no order in 72 h" plus a reminder converts 1.5x+ against holdout | CRM lead | The only browse-abandon trigger in the estate | Segment and randomised reminder | ecomweb `lastviewedbrand` (user key); orders lines | needs-grant, tiers 1 + 4 · NEEDS-GRANT (ecomweb `lastviewedbrand`) |
| H18 | P3 | Favouriters buy a brand 3–4x more when it enters a Plus Offer | Offers manager | Targets about 19.8k favourites rows | Event study around `start_date` | emapi `brands_favouritebrand`, `brands_plusoffer`; orders `offer_code`, `upc` | needs-grant, tiers 1 + 3 · NEEDS-GRANT |
| H19 | P2 | A checkout signup nudge converts 10%+ of returning guests who never signed up | Growth PM | 10% of 82.5k guests is about 8k accounts | A/B on the nudge; guest `last_accessed` bands | orders `atlas_ro.guest_user`, `atlas_ro.guest_merge`, `atlas_ro.order_flags.guest_key` | needs-grant, tier 2 · NEEDS-GRANT |
| H20 | P2 | Baskets within 10% of the currency cap convert at half the rate; baskets over it never convert | Checkout PM | Enumerates one checkout-gate cause of lost orders | Basket value per currency against the cap → `order_order.basket_id` | orders basket tables, `core_currencybasketlimit` | needs-grant, tier 2 · NEEDS-GRANT |
| H21 | P2 | 50%+ of lines use the default denomination; raising the default one step lifts line value by 10%+ with under 3% conversion loss | Merchandising lead | +10% line value if the default anchors choice | Share at default, then A/B the default on 10 brands | orders denominations + basket quantity detail | needs-grant, tier 2 · NEEDS-GRANT |
| H22 | P2 | Non-GCC cards decline 2–3x more; 30%+ of declines are rescued by a retry within 30 min | Payments operations | Retry rescue of up to 30% of declines | youpay approval by card origin, after dedup | orders youpay view (`response_class`) | needs-grant, tier 2 · NEEDS-GRANT |
| H23 | P3 | A price change between checkout and payment raises payment-step abandonment | Checkout PM, with finance | Diagnostic for payment-step abandonment | Share with `total_incl_tax <> total_incl_tax_before_payment`, then approval | orders `order_order` money columns | needs-grant, tier 1 · NEEDS-GRANT |
| H24 | P2 | Brands in the top 12 tag positions earn 2x+ the order lines of the same brands at position 25+ | Merchandising lead | Prices the tag positions that drive web discovery (28.1M tag lookups in 35.5 days) | Panel regression, then randomised re-rank | ecomweb `brands_tagbrand`, admin log; orders lines; brand crosswalk | needs-grant, tiers 1 + 3 + 4 · NEEDS-GRANT (lookup counts STRUCTURAL) |
| H25 | P2 | SA brands without Arabic recipient instructions convert 20%+ worse; the gap is under 5% in AE | Content lead | SA is half of signups and 39.1% Arabic; a 20% gap there is material | Compare, then backfill 30 brands with diff-in-diff | emapi/ecomweb `brands_brand` has-Arabic flags; orders lines | needs-grant, tiers 1 + 3 · NEEDS-GRANT (39.1% Arabic premise VALIDATED) |
| H26 | P3 | A brand's first Plus-Offer week lifts its lines by 25%+ with no loss to its category | Offers manager, with finance | Offer ROI for finance | Diff-in-diff on brand-days | orders `offer_plusoffer`, `order_line` | needs-grant, tier 1 · NEEDS-GRANT |
| H27 | P3 | Stable brand co-purchase pairs (5x+ lift) exist and can fill the empty cross-sell slot | Product (recommendations) | Fills the empty cross-sell slot | Lift/Jaccard matrix, stability by quarter, then an A/B rail | orders lines + user key extract | needs-grant, tier 1 · NEEDS-GRANT |
| H28 | P2 | The RU/+7 farm cohort orders, redeems offers or fails payments at 5x+ same-week web signups | Risk and fraud operations | Sizes the farm's commercial damage (E1) | Cohort against a control | orders `order_order`, youpay flags; emapi `users_useravailedoffer` | needs-grant, tiers 1 + 2 + 3 · NEEDS-GRANT (cohort VALIDATED) |
| H29 | P1 | 5%+ of the 903 blacklisted live accounts ordered after their blacklist date | Risk and fraud operations | Tests whether the E2 gap leaks into orders | Orders after the first blacklist `created_on`, by source class | orders `order_order`, `atlas_ro.user_profile.user_key` | needs-grant, tier 1 · NEEDS-GRANT (903 accounts VALIDATED) |
| H30 | P1 | The 389 users with unapplied orders fraud requests keep buying | Risk and fraud operations, with orders engineering | Tests whether the E3 defect lets flagged users keep buying | Orders after the first stuck event | orders `order_order` by user key | needs-grant, tier 1 · NEEDS-GRANT (389 users VALIDATED) |
| H31 | P2 | Accounts on a shared device have a payment fraud or flag rate 10x+ that of single-device accounts | Risk and fraud operations | A cheap device rule if the lift holds | Fisher exact test | users tokens; orders youpay flags | needs-grant, tier 2 · NEEDS-GRANT (22x blacklist lift VALIDATED) |
| H32 | P3 | Signup-day out-of-GCC tokens predict first-order decline and fraud; later travel does not | Risk and fraud operations | Refines geo risk rules | Segments against decline and fraud rate | users tokens; orders youpay | needs-grant, tier 2 · NEEDS-GRANT |
| H33 | P1 | Re-enabling the RU block, or a (RU, web, DE-egress) rule, stops 90%+ of the farm at under 1 legitimate signup a day | Risk and fraud operations lead | Contains the live farm (E1) at under 1 legitimate signup a day | Replay the rule on 90 days of RU signups | users | ready-now · VALIDATED cohort; rule replay pending |
| H34 | P2 | Running the dynamic email filter before OTP dispatch saves about 95 OTPs per 31 days, and about 1,300 a day on bot days | Identity engineering | About 95 OTPs per 31 days, about 1,300 a day on bot days | OTPs sent to later-blocked recipients, before and after | users | ready-now · VALIDATED counts |
| H35 | P3 | Accounts that log in after a max-login lockout show credential-stuffing behaviour (new device, country or phone change within 24 h) | Risk and fraud operations | Small n; a credential-stuffing check | Identity-change rate against all accounts | users | ready-now · VALIDATED (small n) |
| H36 | P2 | Throttle-config edits cause step changes in signup completion within 24 h | Identity engineering, with growth | Makes config changes a first-class cause in "why did signups move?" | Event study on site-config change days | users admin log + OTP snapshots | ready-now · STRUCTURAL now; VALIDATED co-occurrence (N10) |
| H37 | P3 | The May 2025 Kafka stop and the id cutover came from one release, and identities flagged in the gap went on to order | Platform engineering, with risk | Forensics for the 9-month silence (E4) | `django_migrations` dates; orders-side logs in the gap | orders `django_migrations`, Kafka logs, `users_blacklisteduserdetail` | needs-grant, tiers 1 + 5 · NEEDS-GRANT |
| H38 | P1 | Corporate domains have 3–5x the claim-OTP failure of freemail; an allowlist or SMS fallback before B2B drops halves it | Identity operations, with B2B | Prevents repeats of the Sep 22 claim-OTP incident | Domain-class split over 31 days, then pre/post | users OTP | ready-now · VALIDATED for one domain |
| H39 | P3 | On peak days OTP degradation costs about 23 signups per point of excess resend share | Identity operations | n = 1 peak so far | Regress daily excess unregistered on resend share over the next 3 peaks | users (snapshot) | ready-now · VALIDATED (n = 1) |
| H40 | P3 | A cap of 2 messages a week lowers unsubscribes with no loss of 30-day outcomes | Marketing lead | Fatigue control once sends are visible | Capped against uncapped among multi-trigger users | trigger views; mailengine; orders | needs-new-source · NEEDS-GRANT (mailengine) |
| H41 | P2 | The 2.64 gift events per order (extrapolated basis) are retries, and orders with extra events have slower delivery | Orders engineering | Explains the 2.64 events per order and "paid but no gift" | Events per `order_id` by status; retry span | orders `kafka_giftcreationlog` view | needs-grant, tier 2 · NEEDS-GRANT (ratio STRUCTURAL) |
| H42 | P3 | Users below `required_version` show a login gap or churn after a forced-upgrade bump | Mobile product manager | Forced-upgrade churn | Event study on version bumps | emapi `users_user` view, version config | needs-grant, tier 3 · NEEDS-GRANT |
| H43 | P3 | Phone-only signup verification is a 90%+ proxy for social-IdP signup | Growth analytics | Restores a dead signup-method dimension | Compare with emapi social-id flags | emapi `users_user` view (`has_*_id`) | needs-grant, tier 3 · NEEDS-GRANT |
| H44 | P2 | Web-first users who adopt the app have 2x+ the 90-day orders of web-only users | Product lead | Justifies app-adoption pushes | Token platform split → orders | users + orders `order_order.platform` | needs-grant, tier 1 · NEEDS-GRANT (3.8% web-to-app VALIDATED) |
| H45 | P3 | Recipient onboarding pays back more in QA/AE (8.2% / 5.9% gift-acquired) than in SA (3.65%) | Growth leadership | Country budget allocation | Shares by country against ad CAC | users; ads spend | needs-new-source · NEEDS-GRANT (ads spend; shares VALIDATED) |
| H46 | P3 | Happy Card (generic) gifts convert recipients to buyers better than single-brand cards | Merchandising lead | Product mix for recipient conversion | Recipient 60-day purchase by `is_generic` | orders lines, `catalogue_product.is_generic`, recipient HMAC | needs-grant, tiers 1 + 2 · NEEDS-GRANT |
| H47 | P3 | Corporate gifts delivered 09:00–11:00 local are claimed within 1 h more often | B2B product | Delivery-time default for corporate drops | Claim latency by `delivery_time` bucket | orders personalise + users claims | needs-grant, tier 2 · NEEDS-GRANT |
| H48 | P2 | Signups deleted within 1 h over-index on risk flags (shared device, blacklisted domain, out-of-GCC token) | Risk and fraud operations | A cheap early-risk rule | Flag rates, 1-h-deleted against retained | users | ready-now · VALIDATED inputs; test pending |
| H49 | P2 | **Reciprocity loop / k-factor.** At least 8% of gift recipients send a gift within 60 days, and at least 25% of those send back to the original sender. Corporate (burst) recipients reciprocate less than person-to-person recipients. | Growth leadership | The only honest referral metric in reach (AF-71). P2, not P1, because it needs tier 2 (the P1 rule allows ready-now or tier 1 only) | Rolling 60-day cohorts: k = new senders among recipients ÷ senders, split P2P against corporate | orders `order_orderlinepersonalisedetail` (recipient email/phone as keyed hash), `order_line.order_id`, `order_order(user_id, date_placed, status)` + `atlas_ro.order_flags.guest_key`; users `atlas_ro.identity_keys` | needs-grant, tiers 1 + 2 · NEEDS-GRANT |
| H50 | P2 | **Corporate recipients are a latent B2C audience.** Recipients who claim on an org domain but hold a freemail primary (about 36.3k claims) buy for themselves less often than freemail recipients, but respond more to occasion-timed offers. | Growth, with B2B marketing | About 36.3k reachable recipients with no B2C relationship today | 90-day first-order rate, org against freemail recipients, stratified new/existing; then an A/B occasion offer in the org segment | users claims (G9 segment; domain class from AF-88); orders `order_order`, `atlas_ro.user_profile.user_key` | needs-grant, tier 1 · STRUCTURAL + NEEDS-GRANT (gifting H2; the G9 segment is ready, the domain class is a heuristic from AF-88) |
| H51 | P1 | **A failed claim OTP means an unclaimed gift.** Recipients whose claim chain fails rarely add the email later; that is about 1,183 failed claim chains per 31 days, and a share of those gifts expire unredeemed. | CRM lead, with the identity PM | Directly sizes the AF-03 / AF-27 rescue: up to about 1,183 claims per 31 days | For failed claim chains, count later successful adds for the same recipient hash; later, gift redemption status | users OTP + activity log (readable); gifts `gifts_gift` status and expiry (new source) | ready-now (claim side) · VALIDATED claim side (N15); redemption side needs a new source |
| H52 | P2 | **Plus-offer avails convert to an order with that `offer_code` less than 50% of the time**, and the gap sits in unique-promo-code offers that ran out of codes. | Offers manager | Finds offers that lose buyers after the claim | Claim-to-redeem funnel per offer, split by `is_unique_promo_code`, codes left against `promo_code_threshold` | emapi `users_useravailedoffer`, `brands_offerpromocode` (keyed); orders `order_line.offer_code` | needs-grant, tiers 1 + 3 · NEEDS-GRANT |
| H53 | P3 | **Dead-end search keywords.** At least 5% of active search keywords in a store map to 0 active, launched brands in that store, and they overlap with feedback-box suggestions. | Merchandising, with BD | Search is small (about 36k lookups in 35.5 days), so value is modest | Anti-join keyword → brand → store, ranked by keyword read frequency | ecomweb `brands_brandsearchtag`, `brands_brand_search_tags`, `brands_brand(store_id, is_active, is_launched, is_obsolete)`, `atlas_ro.feedback_suggestion(matched_brand_id, unmatched_suggestion_key, platform_id)` (no suggestion text leaves the DB) | needs-grant, tier 4 · NEEDS-GRANT |
| H54 | P2 | **Partial points redemption (Qitaf and other programmes) is approved less often** than card-only payment. | Loyalty / payments PM | A payment-mix fix with a loyalty partner | youpay approval by redemption mode × `point_program` | orders youpay `redeemed_amount`, `is_full_redemption`, `point_program`, `is_qitaf_enabled`, `approved` | needs-grant, tier 2 · NEEDS-GRANT |
| H55 | P1 | **Claim-OTP storm days lose at least 20% of that day's claims**, and the lost recipients rarely come back. Sep 22 ran 10.6 OTPs per claim against 1.5–2.3 on normal days. | Identity operations, with CRM | Turns the AF-26 incident alert into lost claims | Alert on OTPs per claim above 3; compare 7-day claim rate of failed recipients on storm against normal days | users OTP + activity log | ready-now · signal VALIDATED (T12, T13) |
| H56 | P3 | **The one-alternate-email cap loses claims.** About 13.9k users already hold a self-added alternate email and cannot bind a gifted work email; raising the cap to 2 increases claims per recipient. | Identity product manager | Up to 13.9k blocked recipients, but visible swap behaviour is small (24 users) | Claim-attempt success by "already has an alternate email", before and after a cap change | claim attempts in `ygag_ecom_gotagift_db` / `ygag_ecom_gifts_db` | needs-new-source · NEEDS-GRANT; cap count VALIDATED |
| H57 | P3 | **Identity collisions indicate interception or duplicate accounts.** Claims that bind another account's primary email (164) or a shared email (31) have a higher later blacklist rate. | Risk and fraud operations | Small n; a monitor more than a test | Blacklist hit rate within 180 days: collision cohort against all claimers | users DB | ready-now · cohort VALIDATED (small n) |
| H58 | P2 | **Fraud status is split-brained.** emapi `users_user.is_fraud` agrees with the users-DB blacklist on less than 95% of blacklisted registered users, so app-side offers can reach blocked users. | Risk and fraud operations, with identity engineering | Closes an offer-abuse path next to E2 | Agreement matrix on `user_key` (test V9) | emapi `atlas_ro.app_user(user_key, is_fraud, is_deleted)`; users `atlas_ro.list_entry` | needs-grant, tier 3 · NEEDS-GRANT (users side VALIDATED) |
| H59 | P2 | **Legacy linked customers respond to "your account moved".** The 57,754 linked accounts (tenure back to 2012) have a higher first-order rate on the new platform after the message than native dormant users. | Marketing lead | About 58k known customers with no new-platform relationship | Cohort by `legacy_state` × tenure, with a holdout on the message | users legacy dimension (readable); orders `order_order` by `user_key` | needs-grant, tier 1 · NEEDS-GRANT (cohort VALIDATED) |
| H60 | P2 | **Broken listings convert at zero.** At least 50 listings are active but not launched, obsolete but visible, or visible with no active denominations or ranges, and they draw views with no orders. | Merchandising operations | Cheap fixes once AF-17 lists them | Catalog-health snapshot joined with `lastviewedbrand` and `order_line` | ecomweb/emapi `brands_brand` flags, `brands_branddenomination(is_active)`, ranges; `configurations_lastviewedbrand`; orders `order_line` | needs-grant, tiers 1 + 3 + 4 · NEEDS-GRANT |
| H61 | P1 | **Phone-first signup OTP.** Making WhatsApp/SMS the default signup OTP channel, with email as the fallback, lifts 1-h registration for email-first signups from about 73% to over 90% (errors H2). This is the full-population version of H02, which only treats recipients after a first resend. | Identity product manager, with growth | Base (N11, N12, per chain over 31 days): email signup chains register within 1 h 73.4% of the time (13,553 of 18,470), phone chains 94.3% (24,948 of 26,457). Moving the 18,470 email chains to 90% is up to about 3,070 more registrations per 31 days; that is an upper bound, because phone users self-select [inferred]. About 7x the chain reach of H02 (2,571 multi-code email chains) | A/B on the channel default; primary metric 1-h registration per chain (N11/N12 logic); guardrail OTP cost per registration. Run H02 as the post-resend arm inside the same split, not as a separate test | users `notifications_twofactorauth` (+ AF-01 snapshot) | ready-now (the default needs an app change) · VALIDATED baseline (N11, N12); experiment needed |
| H62 | P2 | **Brand mobile-verification friction.** Brands with `require_mobile_verification` and no `allow_any_country_mobile_verification` convert worse for non-local buyers and cause more claim friction for recipients (purchase H12). The only brand-level checkout-friction test; B4 names the mechanism. | Merchandising lead, with the checkout PM | Enumerates a brand-level gate; value is the conversion gap on the flagged brands | Conversion by brand flag × `placed_country_id`, flagged against unflagged brands in the same store | orders `catalogue_product(id, require_mobile_verification)`, `order_order.placed_country_id`, basket and order lines; emapi `brands_brand(code, allow_any_country_mobile_verification)` | needs-grant, tiers 1 + 2 + 3 · NEEDS-GRANT |
| H63 | P2 | **Early occasion re-rank.** Re-ranking occasion tags and denominations 3 weeks before Ramadan and December (the claim peaks) captures more of the peak than re-ranking 1 week before (catalog H11). Gives AF-96 a testable hypothesis and a holdout. | Merchandising lead | The two largest claim peaks of the year (F7, D3); the lift is the share of peak-window lines moved earlier | Staggered-timing test by store: SA re-ranks early and AE late, then swap next season; outcome is peak-window order lines and gift claims | users activity log (ready); ecomweb `brands_tagbrand`, `brands_occasion`, `django_admin_log`; orders `order_orderlinepersonalisedetail.occasion_code`, `order_line` | needs-grant, tiers 1 + 2 + 4 · STRUCTURAL (seasonality VALIDATED) |
| H64 | P2 | **Diaspora buyers.** Non-GCC residents (IN, EG, GB, US; 11.3k live signups in the last 12 months, VALIDATED) buy into AE and SA stores at a higher average value and with a different brand mix (grocery and retail rather than entertainment) than GCC residents (catalog H12). | Growth lead (diaspora campaigns) | Sizes a diaspora campaign segment of about 11.3k signups a year | AOV and brand-mix breakdown by buyer residence × `order_order.region_id` | users `country_of_residence` (ready); orders `order_order(user_id, region_id)`, `atlas_ro.user_profile.user_key`, `order_line.upc` | needs-grant, tier 1 · NEEDS-GRANT (11.3k signups VALIDATED) |
| H65 | P3 | **Generic-card breadth sells.** Generic (multi-brand) cards with 100 or more active redeemable brands sell 30%+ more per listing than those with under 30, within the same classification (catalog H8). | Merchandising lead, with product | Guides Happy Card assortment; cross-sectional, so diagnostic | Distinct active redeemable brands per config (deduplicated on (config, brand)) against orders per generic listing | emapi `brands_generic_brand_item(generic_config_id, brand_id, is_active)`, `brands_generic_brand_config`; orders `order_line.upc` | needs-grant, tiers 1 + 3 · NEEDS-GRANT |
| H66 | P2 | **Surface value against loyalty.** Order lines whose `purchase_origin` is an offer or slider surface have a higher average line value but lower repeat purchase than lines from tag or category browsing (catalog H9). | Growth PM, with product | Prices each merchandising surface on value and repeat; builds on AF-36 | Lines, AOV and 60-day repeat by `purchase_origin` | orders `order_line(purchase_origin, upc, created_on)`, `order_orderlinequantitydetail` reporting-currency amounts, `order_order.user_id` | needs-grant, tier 1 · NEEDS-GRANT |
| H67 | P3 | **Occasion code drives virality.** Lines with `occasion_code` = birthday or Eid have a higher recipient → sender conversion than lines with no occasion, and senders with `is_reminder_added` repeat to the same recipient the next year at 30%+ (gifting H9). | CRM lead, with product | Refines the k-factor (H49) by occasion; overlaps H16 on the reminder half | Recipient → sender conversion and next-year same-recipient repeat, by `occasion_code` and `is_reminder_added` | orders `atlas_ro.occasion_line` (recipient keys), `order_line`, `order_order`; users `atlas_ro.identity_keys` | needs-grant, tiers 1 + 2 · NEEDS-GRANT |
| H68 | P3 | **Merged guests are the best seed and the best repeaters.** Guest checkouts later merged to a registered account (`users_mergeduser`) repeat at 2x the rate of never-merged guests (purchase H10) and produce more recipient signups per sending order (gifting H10); guests whose basket did not merge show cart-loss friction. | Growth PM | Merges are small (at most about 3.7k rows), so a diagnostic that sizes the guest-to-account prize (AF-59) | Repeat rate and recipient signups per order, merged against unmerged guest senders; basket merge gap | orders `atlas_ro.guest_merge`, `atlas_ro.guest_user`, `atlas_ro.order_flags.guest_key`, `basket_mergedbasket`, `order_order`; recipient join via `atlas_ro.occasion_line` | needs-grant, tiers 1 + 2 · NEEDS-GRANT |
| H69 | P3 | **Scheduled-gift lead time.** Scheduled (future-dated) personalised gifts are placed 3 days or more before occasions and cluster before Ramadan and Eid (purchase H7). The reminder half of the source hypothesis is H16. | CRM lead | Sets send timing for occasion campaigns | Lead-time distribution `delivery_date − date_placed` by `occasion_code` × month | orders `order_orderlinepersonalisedetail(line_id, delivery_date, delivery_type, occasion_code)`, `order_line`, `order_order(date_placed)` | needs-grant, tiers 1 + 2 · NEEDS-GRANT |
| H70 | P3 | **Cross-currency friction.** Cross-currency lines (`is_different_currency_denomination`) have lower basket → order conversion and higher decline rates than same-currency lines (purchase H11). | Checkout PM, with finance | Diagnostic for cross-border GCC gifting; feeds AF-75 | Conversion and approval by the flag and currency pair | orders `order_orderlinequantitydetail(is_different_currency_denomination, denomination_currency_id, reporting_currency)`, basket equivalents, youpay columns | needs-grant, tiers 1 + 2 · NEEDS-GRANT |
| H71 | P3 | **Delete-then-recreate promo abuse.** Accounts deleted within 24 h of signup are disproportionately re-created (same device, or same card) and used for first-order promos (risk H7). | Risk and fraud operations | Small n today (5 deleted users with a device signature); a monitor more than a test until `deleted_at` exists | Share of deleted accounts whose device later appears on a new account, and the share of those with a promo order in 7 days, against a control | users tokens (ready); orders `order_line(is_offer_applied, offer_code)`; a `deleted_at` column (GRANTS.md §10 engineering ask 1) | needs-grant, tier 1 (+ engineering ask) · STRUCTURAL + NEEDS-GRANT |
| H72 | P2 | **Trust-list conflicts are stale and inconsistent.** The whitelist-overrides-blacklist conflicts (13 countries, 15 entries active on both lists) carry at most 1 legitimate signup a day, so removing them barely affects growth (risk H11), and they produce inconsistent OTP outcomes by check order (errors H12). | Risk and fraud operations, with messaging / SMS operations | Settles the E6 list clean-up (GRANTS.md §10 engineering ask 3) with a measured cost | Per conflict country (ISO-2 mapped to dial prefix): signups a day, completed-signup rate, and 31-day phone OTP send and accept rates against non-conflicting non-GCC countries | users OTP + lists | ready-now · VALIDATED inputs (risk H11); VALIDATED conflict (N23), test not yet run (errors H12) |
| H73 | P3 | **Marketing waste on risky accounts.** Some share of each campaign's promo sends or redemptions reaches risk-segment accounts (farm cluster, shared device, blacklisted-live); excluding them lowers cost per real acquisition by 2%+ (risk H13). | Marketing lead, with risk | Puts a money value on AF-10 | Cost per retained buyer with and without the AF-10 exclusion, on campaign cohorts | users (segment ready); campaign sends (mailengine, smsengine); orders `order_order` | needs-new-source (+ tier 1) · NEEDS-GRANT |
| H74 | P3 | **Rule-engine false positives among real customers.** Recipients blacklisted by the rule engine between their sign-up OTP and account creation include real customers; those who retry within 7 days through another channel (phone), or get a support whitelist add, show the rule's false-positive rate (errors H9). | Risk and fraud operations, with growth | Small n: 69 email sign-up recipients per 31 days were blacklisted after their OTP; 98.6% had an accepted code but only 11.6% registered, against 78.8% of clean recipients (N31). Calibrates the rule engine rather than recovering volume | Among the blacklisted-after-OTP recipients (N31 logic, 31 days), the share with a later phone sign-up within 7 days or a whitelist add, matched in-DB on keys; compare with clean recipients who needed a resend | users OTP, blacklist, whitelist (`atlas_ro.otp_request`, `atlas_ro.list_entry`) | ready-now · VALIDATED baseline (N31); test not yet run |
| H75 | P2 | **Email fallback for non-GCC phone signups.** Non-GCC phone signups that need a resend register only 32.5% of the time, and an email code offered after the first failed phone code lifts completion above 70% (purchase H4). The reverse of H61 (phone-first for email signups); H05 treats the same countries with direct routes instead. | Identity product manager, with growth | Base (T9, per recipient, whatsappsms sign_up, 1–26 Sep 2026): 49 of 151 non-GCC recipients with 2+ codes registered (32.5%), against 76.8–84.1% in SA, AE and other GCC. At 70%, about 57 more registrations per 26 days (0.70 × 151 − 49 = 56.7; about 68 per 31 days) | A/B on the email fallback after the first failed phone code; metric registered / recipients by geo × codes (T9 logic). Can run as an arm of the H61 split | users `notifications_twofactorauth` (+ AF-01 snapshot) | ready-now (the fallback needs an app change) · VALIDATED baseline (T9) |
| H76 | P3 | **Send day by country weekend.** AE sends on Friday and SA sends on Thursday beat a single GCC send day (user-lifecycle H10). | Marketing operations | Modest. U9 (Dubai time, Oct 2025–Sep 2026): AE signups peak on Friday (17,997), while Friday is SA's second-weakest day (17,552); a single GCC send day misses one of the two weekends | Geo-split send-day test (AE Friday, SA Thursday, against one common day); outcome daily signups by country. Run as the weekday factor of the H15 send-time test (weekday × hour); scorecard AF-20 | users (readable); a send channel | ready-now · VALIDATED baseline (U9) |
| H77 | P2 | **Failed 2FA/claim resend chains lose logged-in customers.** 34.0% of `2fa_account_verification` resend chains never end with an accepted code; these are logged-in customers lost at gift claim or checkout, and rescuing a chain within 10 minutes recovers orders (campaigns H11). H51 measures later claims by the same recipient and H03 the Arabic template; H77 measures the chain owner's order attempts. | Identity product manager, with CRM | Base (users profile B5, 31 days): 1,208 of 3,555 resend chains (34.0%) never accepted. The order value lost is what the test measures | Join the chain-failure day to order attempts (orders, youpay) for the same user key, against users whose chain succeeded; then a within-10-minute rescue through the AF-27 claim queue | users OTP (ready); orders `order_order`, `atlas_ro.user_profile.user_key`, `atlas_ro.youpay_derived` | needs-grant, tiers 1 + 2 · failure rate VALIDATED (B5); order impact NEEDS-GRANT |

**By priority:** P1 (14): H01, H02, H03, H06, H07, H08, H11, H29, H30, H33, H38, H51, H55, H61; P2 (35): H04, H05, H09, H12, H13, H14, H16, H17, H19, H20, H21, H22, H24, H25, H28, H31, H34, H36, H41, H44, H48, H49, H50, H52, H54, H58, H59, H60, H62, H63, H64, H66, H72, H75, H77; P3 (28): H10, H15, H18, H23, H26, H27, H32, H35, H37, H39, H40, H42, H43, H45, H46, H47, H53, H56, H57, H65, H67, H68, H69, H70, H71, H73, H74, H76.

H61–H73 were added from the theme catalogs in critique round 2, and H74–H77 in round 3 (errors H9, purchase H4, user-lifecycle H10, campaigns H11). The appendix "Considered and deferred" maps **every** theme hypothesis to its Hxx id, so a merge or an omission can be checked.

# Feature catalog

**How to read the columns**

- **Type:** metric, funnel, segment, alert_trigger, breakdown, dashboard, record_drilldown or agentic_analysis.
- **Readiness:**
  - **RN** = ready-now (users DB);
  - **NG** = needs-grant;
  - **NS** = needs-new-source.
- **Effort:** S, M or L.
- **Impact:** 1–5.

**Priority** = impact × readiness weight (RN 1.0, NG 0.6, NS 0.3) ÷ effort weight (S 1, M 2, L 3).

**Evidence.** Figures in the Value column are VALIDATED for RN rows (users DB queries) and STRUCTURAL for NG and NS rows, unless the cell says otherwise. Any outcome an NG feature would measure is NEEDS-GRANT until its tier lands.

Features are deduplicated across all seven themes. Effort and impact are the architect's judgment, built on the theme ratings.

**Rank.** Rows are ranked by effective priority, then by an explicit tie-break.

- **Inheritance rule (one rule, applied to every row).** A prerequisite's effective priority is the highest of (a) its own score, (b) the effective priority of every feature that lists it under "Blocked by", and (c) the urgency of every hypothesis that needs it (table below). No feature is ever scheduled before something it needs; a validation over the "Blocked by" column finds no row ranked above one of its blockers, except AF-04 over AF-11, where only AF-11's `legacy_state` dimension is needed and it ships with AF-04 (next bullet).
  - **Feature → feature:** the prerequisite ranks immediately before its highest-ranked dependent. AF-88 (base 3.00) takes 5.00 from AF-08 and AF-09; AF-19 (base 3.00) takes 4.00 from AF-16; AF-52 (base 1.50) takes 2.40 from AF-54 and AF-58, which inherit it from H24 and H17. Where only part of a feature is needed, that part is built with its dependent and the rest keeps its own rank: AF-04's shell exclusion needs AF-11's `legacy_state` dimension, which ships with AF-04 in Wave 1, while the AF-11 welcome-back segment stays at 4.00.
  - **Hypothesis → feature:** a feature that a hypothesis's test needs is scored as if it had the hypothesis's urgency as impact (P1 = 5, P2 = 4) at S effort, with its **own** readiness weight: inherited score = urgency × readiness weight. A ready-now prerequisite of a P1 hypothesis therefore inherits 5.00, and a needs-grant one 3.00 (5 × 0.6). A ready-now prerequisite of a P2 hypothesis inherits 4.00, and a needs-grant one 2.40 (4 × 0.6). P3 hypotheses pass on nothing. Seventeen rows inherit this way: AF-25, AF-26, AF-27 (5.00); AF-18 (4.00); AF-45, AF-55, AF-64 (3.00); and AF-48, AF-50, AF-51, AF-54, AF-58, AF-59, AF-60, AF-61, AF-71, AF-96 (2.40). A hypothesis "needs" a feature when its test design names that feature's segment, funnel, metric or breakdown as the population, the treatment trigger or the outcome; a hypothesis whose test is a one-off query on granted views needs none, and the table below says so for every P1 and P2 hypothesis.
  - The Priority cell shows both numbers whenever a row inherits.
- **Blocked by** lists the features that must ship first. "(trend)" means the feature works on the 31-day OTP or 30-day web-token window without it and needs it only for history. An *activation gate* (AF-79 consent) blocks sending, not building, and is marked "sends:"; it is escalated as a decision rather than re-ranked (see its row). Every NG feature that joins users to another database also waits for test V2 (GRANTS.md §9).
- **Tie-break** for equal effective scores (fourteen at 5.00, eight at 4.00, fifteen at 2.40): rows that hold the score on their own rank first, using (1) dependency, so a feature that unblocks others ranks first (AF-01 unblocks every OTP and token trend; AF-10 gates every campaign trigger; AF-88 unblocks the corporate features); (2) exposure to a live incident (E1–E6); (3) audience reach; (4) time to value. Rows that inherit the score from a hypothesis follow them, in the order their hypotheses run in the roadmap (so AF-26 for H55, then AF-27 for H51, then AF-25 for H61 and H02; at 4.00, AF-18 for H44; at 2.40, AF-71 for H49, then the tier 2 prerequisites in hypothesis order, AF-50 (H16), AF-59 (H19), AF-60 (H21), AF-48 (H22, H54) and AF-51 (H41), then tier 3, AF-61 (H52), then tier 4, AF-52 immediately before its first dependent AF-58 (H17), then AF-54 (H24) and AF-96 (H63)).
- **Tier** is the GRANTS.md tier set that must land before an NG feature works (section 8).

**Hypothesis prerequisites.** The features each P1 and P2 hypothesis's test needs, and what they inherit. The last rows list the P1 and P2 hypotheses that need no feature, with the reason, so the table covers every P1 and P2 row of the hypothesis catalog.

| Hypothesis | Priority | Needs | Inherited score | Effect on the ranking |
|---|---|---|---|---|
| H55 claim-OTP storm loss | P1 | AF-26 (the OTPs-per-claim alert is the test's trigger) | 5.00 | AF-26 2.50 → 5.00, rank 12 |
| H51 failed claim = unclaimed gift | P1 | AF-27 (claim part: the failed-claim-chain segment) | 5.00 | AF-27 2.50 → 5.00, rank 13 |
| H07 "finish your account" link | P1 | AF-27 (signup part: accepted-but-unregistered recipients) | 5.00 | as above |
| H61 phone-first signup OTP; H02 phone OTP after resend | P1 | AF-01, AF-25 (the canonical `signup_registration_by_code_count` funnel is the primary metric) | 5.00 | AF-25 2.50 → 5.00, rank 14 |
| H03 Arabic claim template; H38 corporate claim fallback | P1 | AF-03; H38 also AF-88 | 5.00 | none (already 5.00) |
| H06 failed sign-in nudge | P1 | AF-01, AF-05 | 5.00 | none |
| H11 corporate pre-season outreach | P1 | AF-09 | 5.00 | none |
| H01 resend → purchase | P1 | AF-01, AF-64 | 5.00 / 3.00 (NG) | AF-64 1.20 → 3.00, rank 32 |
| H08 gift-acquired first order | P1 | AF-02, AF-45 | 5.00 / 3.00 (NG) | AF-45 1.50 → 3.00, rank 33 |
| H29 blacklisted accounts ordering; H30 unapplied fraud requests | P1 | AF-06 (H29), AF-07 (H30), AF-55 | 5.00 / 3.00 (NG) | AF-55 1.50 → 3.00, rank 34 |
| H49 k-factor | P2 | AF-71 | 2.40 (NG) | AF-71 1.00 → 2.40, rank 46 |
| H44 web-first app adopters | P2 | AF-01, AF-18 (the web-first → app cohort is AF-18's definition; web tokens purge after 30 days) | 4.00 (RN) | AF-18 3.00 → 4.00, rank 22 |
| H16 reminder senders reorder | P2 | AF-50 (the occasion-line cohort with `is_reminder_added` is AF-50's segment) | 2.40 (NG) | AF-50 1.50 → 2.40, rank 47 |
| H19 checkout signup nudge for returning guests | P2 | AF-59 (returning-guest `last_accessed` bands and guest-to-account conversion) | 2.40 (NG) | AF-59 1.20 → 2.40, rank 48 |
| H21 default denomination anchoring | P2 | AF-60 (share at default is AF-60's breakdown) | 2.40 (NG) | AF-60 1.20 → 2.40, rank 49 |
| H22 non-GCC declines and retry rescue; H54 partial points redemption | P2 | AF-48 (approval by card origin, retry rescue and redemption mode on the deduplicated youpay view) | 2.40 (NG) | AF-48 1.50 → 2.40, rank 50 |
| H41 gift events per order | P2 | AF-51 (events per order, retry span and failure class) | 2.40 (NG) | AF-51 1.50 → 2.40, rank 51 |
| H52 claim-to-redeem funnel | P2 | AF-61 (avails → orders with the offer code, codes left against threshold) | 2.40 (NG) | AF-61 1.20 → 2.40, rank 52 |
| H17 viewed-not-bought reminder | P2 | AF-58 (the segment is the test population), hence AF-52 | 2.40 (NG) | AF-58 1.20 → 2.40, rank 54; AF-52 1.50 → 2.40, rank 53 |
| H24 tag position | P2 | AF-54 (sales by tag position is the panel's outcome), hence AF-52 | 2.40 (NG) | AF-54 1.50 → 2.40, rank 55 |
| H63 early occasion re-rank | P2 | AF-96 (the playbook drives the staggered re-rank) | 2.40 (NG) | AF-96 1.20 → 2.40, rank 56 |
| H04, H05, H13, H25, H36, H48, H59, H60 | P2 | AF-03; AF-01; AF-71 and AF-04; AF-35; AF-01; AF-19; AF-11; AF-17 | 4.00 / 2.40 | none (each already at or above it) |
| H09, H12, H14, H50, H66, H75, H77 | P2 | AF-15 and AF-45; AF-04; AF-11; AF-88; AF-36; AF-01; AF-27 | 4.00 / 2.40 | none (each already at or above it) |
| H10, H56, H76 | P3 | AF-14, AF-97, AF-20 | none (P3) | none |
| H33 RU rule replay | P1 | none: a rule replay on raw users data | — | — |
| H20, H28, H31, H34, H58, H62, H64, H72 | P2 | none. H20 is one query on `basket_summary` against `core_currencybasketlimit`; H28, H31 and H64 are cohort comparisons on granted views; H34 is a before/after count; H58 is test V9; H62 is a brand-flag comparison on order lines; H72 runs on the 13 known conflict countries straight from `list_entry` and OTP (AF-21 alerts on conflicts but is not the test) | — | — |

AF-88 to AF-96 were added in an earlier revision from the theme catalogs (gifting F3, F16, F20; campaigns F22; errors F12; purchase F18; catalog F11, F17, F20). AF-97 (gifting F17, alt-email cap friction) was added in this revision. The stuck-claim segment (purchase F5, errors F14) is merged into AF-27. The appendix carries the complete theme-feature crosswalk (all 146 theme features).

| Rank | id | Name | Type | Audience | Value | Plugin / tables | Ready | Eff | Imp | Tier | Blocked by | Priority |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | AF-01 | OTP and token daily snapshot job | metric (snapshot) | All | Keeps OTP and web-token history beyond the 31- and 30-day purge. Prerequisite for every trend. | ecom_users: OTP tables, tokens → atlas store | RN | S | 5 | — | — | 5.00 |
| 2 | AF-10 | Suppression and risk-exclusion segment | segment | Marketing, risk | Keeps promo budget from farms, blacklisted and promo-blocked accounts (5,544 live users on promo-blocked domains, matched on the first label of the email domain) | ecom_users: blacklist, promo domains (`user_profile.is_promo_blocked_domain`, label rule; GRANTS.md §2, test V15), tokens | RN | S | 5 | — | — | 5.00 |
| 3 | AF-06 | Blacklist enforcement-gap monitor | metric + drilldown | Ops/risk | 903 blacklisted live accounts; 12 users / 18 tokens after blacklisting | ecom_users: blacklist, `users_user`, tokens | RN | S | 5 | — | — | 5.00 |
| 4 | AF-07 | Integration silence and stuck-request detector | alert_trigger | Ops, engineering | Would have caught the 9-month fraud-feed silence; tracks 396 registered stuck events | ecom_users: `kafka_clients_*` | RN | S | 5 | — | — | 5.00 |
| 5 | AF-03 | Gift-claim verification funnel (by language, code count) | funnel | Product, CRM | 46% Arabic against 74% English. 857 of 3,182 claim-OTP recipient emails (26.9%) never became an identity (U14a). | ecom_users: OTP, activity log, secondary identity | RN | S | 5 | — | AF-01 (trend) | 5.00 |
| 6 | AF-02 | Gift-acquired signups (+ share, by country) | metric | Marketing, leadership | Unreported channel: 3–6% of signups, lower-bound chip, `valid_from` 2024-08-05 | ecom_users: `users_user`, activity log | RN | S | 5 | — | — | 5.00 |
| 7 | AF-05 | Failed sign-in win-back trigger | alert_trigger | CRM, product | Failed email sign-in with no login token within 7 days: 344 of 770 matched users whose email sign-in chain failed (44.7% of those users, against 350 of 6,302 users, 5.6%, whose chain succeeded; about 23 days of chains; U22), about 15 a day or 450 a month. The trigger fires within 24 h. | ecom_users: OTP, tokens | RN | S | 5 | — | AF-01, AF-10 | 5.00 |
| 8 | AF-04 | Birthday audience (next 7/30 days, local-date rule) | segment | CRM | About 26.8k birthdays of live non-shell users in the next 30 days (the live base, not active users: only 47.0% of recent token holders have a usable birthday, D2); excludes shells (they go to AF-11, see the shell rule in D), the 01/01 default and impossible dates | ecom_users: `users_user`, migration log | RN | S | 5 | — | AF-10, AF-11 `legacy_state` dimension (built with it); sends: AF-79 | 5.00 |
| 9 | AF-88 | Data-driven claim-domain classifier | segment (derived dimension) | Data, B2B | Classifies each claim domain in-DB as consumer or org (≥1,000 primary-email holders and ≥10× ratio = consumer), with the hand list as override and a sensitivity band on org share (74.4% / 72.4% / 61.8% floor). Names never leave the DB. Prerequisite for AF-08, AF-09, AF-89, AF-90 and H50. | ecom_users: activity log, `users_user.email` domain part (in-DB only) | RN | S | 3 | — | — | 3.00 → **5.00** (inherited from AF-08, AF-09) |
| 10 | AF-08 | Corporate gifting burst alert | alert_trigger | B2B, CRM | About 9 firings a year, carrying opaque org ids only. S effort on top of AF-88. | ecom_users: activity log (claim domain key), AF-88 classifier | RN | S | 5 | — | AF-88 | 5.00 |
| 11 | AF-09 | Corporate season re-book list | segment | B2B sales | 40% of burst domains burst again the same season, against 3.9%. S effort on top of AF-08 and AF-88. | ecom_users: burst rollup, AF-88 classifier | RN | S | 5 | — | AF-08, AF-88 | 5.00 |
| 12 | AF-26 | OTP incident alert with drill-down | alert_trigger + agentic | Ops | Would have flagged Sep 22 within hours, pointing at the corporate domain class | ecom_users: OTP, tokens | RN | M | 5 | — | AF-01 (trend) | 2.50 → **5.00** (inherited from P1 H55) |
| 13 | AF-27 | Signup and gift-claim OTP rescue queue ("lost at the door") | segment + alert | Growth, CRM | Signup: 3,644 email recipients per 31 days with no account. Gift claim: about 1,183 failed claim chains per 31 days with no email added within 30 min (the stuck-claim segment, merged from purchase F5 and errors F14). Counts in atlas; any export needs a policy. | ecom_users: OTP, activity log, `users_user` | RN | M | 5 | — | AF-01 (trend), AF-10 | 2.50 → **5.00** (inherited from P1 H51, H07) |
| 14 | AF-25 | Signup verification funnel (channel × prefix × codes × language) | funnel | Growth, product | The resend cliff: 82.7% → 56.8% per email recipient (canonical), 32 points per phone chain; unconfigured countries | ecom_users: OTP, `users_user` | RN | M | 5 | — | AF-01 (trend) | 2.50 → **5.00** (inherited from P1 H02, H61) |
| 15 | AF-12 | Regime/cutover annotation registry | dashboard | All | Auto-annotates the 2023–2026 cutovers; stops wrong trend conclusions | registry metadata | RN | S | 4 | — | — | 4.00 |
| 16 | AF-13 | Blacklist volume by producer class | metric | Ops/risk | Separates rule, analyst and service rows; stops "fraud wave" misreads | ecom_users: blacklist, producer log | RN | S | 4 | — | — | 4.00 |
| 17 | AF-19 | Early-deletion (signup regret) metric | metric | Growth, risk | 42.5% of deletions happen within 1 h; provides the survived-day-1 denominator | ecom_users | RN | S | 3 | — | — | 3.00 → **4.00** (inherited from AF-16) |
| 18 | AF-16 | Gift-acquired quality overlay | breakdown | Marketing, risk | Blacklist, device and deletion rates, survivor-adjusted | ecom_users | RN | S | 4 | — | AF-02, AF-19 | 4.00 |
| 19 | AF-11 | Legacy state dimension + shell welcome-back segment | segment | Marketing | 105,501 live shells (0.93% reactivate in 30 days); 1,557 already back; carries the shell birthday hook | ecom_users: migration log | RN | S | 4 | — | AF-10 | 4.00 (its `legacy_state` dimension is built at rank 8 with AF-04, which needs it) |
| 20 | AF-15 | Dormant gift recipients segment | segment | CRM | The "claim and leave" audience for H09 | ecom_users | RN | S | 4 | — | AF-02 | 4.00 |
| 21 | AF-14 | Gift-claim re-engagement scorecard | metric | CRM | Baseline: 1.23% against 1.10%, no lift. Scores H10. | ecom_users: activity log, tokens | RN | S | 4 | — | — | 4.00 |
| 22 | AF-18 | Web-to-app migration metric | metric | Product | 3.8% of web signups later log in on the app | ecom_users: tokens | RN | S | 3 | — | — | 3.00 → **4.00** (inherited from P2 H44) |
| 23 | AF-17 | Catalog health snapshot | metric (snapshot) + alert | Ops, merchandising | Listings that are active but not launched, have no denominations or lack Arabic instructions | emapi / ecomweb `brands_brand` + children | NG | S | 5 | 3 (+4 for web) | — | 3.00 |
| 24 | AF-24 | Signup/token burst alert with a cohort-quality card | alert_trigger | Growth, risk | Tells a campaign apart from a farm | ecom_users | RN | S | 3 | — | — | 3.00 |
| 25 | AF-92 | Token issuance anomaly alert | alert_trigger + breakdown | Ops, risk | Hourly tokens against baseline, split new against returning, platform, out-of-GCC share and shared-device bursts (the Sep 22 peak reached z = 6.0) | ecom_users: tokens, `users_user` | RN | S | 3 | — | — | 3.00 |
| 26 | AF-21 | Trust-list consistency check | alert_trigger | Ops/risk | 15 whitelist and blacklist conflicts; case variants | ecom_users: white and black lists | RN | S | 3 | — | — | 3.00 |
| 27 | AF-22 | Identity-collision queue | alert_trigger | Risk | 164 cross-primary claims; 31 shared emails | ecom_users | RN | S | 3 | — | — | 3.00 |
| 28 | AF-23 | Market demand × language map with farmed-cohort flags | breakdown | Growth, merchandising | SA 39.1% Arabic; flags the AM/CH/MX farmed cohorts | ecom_users | RN | S | 3 | — | — | 3.00 |
| 29 | AF-20 | Send-time and weekday profile | breakdown | Marketing | AE Friday against SA Thursday; SA evening, AE daytime | ecom_users | RN | S | 3 | — | — | 3.00 |
| 30 | AF-91 | Gender × occasion segment | breakdown + segment | Marketing | Female share of claimers and signups by country on occasion days against baseline (AE spikes 42–62% female against 26.8%), for cohorts since Jul 2025 where gender is fully captured. Sender side later. | ecom_users: `users_user.gender`, activity log; later orders `occasion_code` | RN | S | 3 | — | — | 3.00 |
| 31 | AF-97 | Alt-email cap friction | metric (snapshot) | Product, identity | Share of claimers already holding a live alternate email (about 13.9k users hold a self-added one and cannot bind a gifted email under the one-per-account cap); remove → via-gift swap cycles per week (24 users bound 2+ distinct emails). Blocked claim attempts come later from the gotagift source. Scored on its ready-now part. Scorecard for H56 (gifting F17) | ecom_users: `atlas_ro.gift_claim`, `atlas_ro.identity_event`, secondary identity; later `ygag_ecom_gotagift_db` | RN | S | 3 | — (blocked attempts: new source) | — | 3.00 |
| 32 | AF-64 | OTP resend → purchase impact analysis | agentic_analysis | Product | Turns friction into money (H01) | OTP snapshot + orders | NG | M | 4 | 1 | AF-01 | 1.20 → **3.00** (inherited from P1 H01) |
| 33 | AF-45 | Recipient → buyer loop (gift-driven referral proxy) | funnel | Marketing, leadership | "Gifts pay for their own acquisition" | ecom_users + orders `order_order`, `atlas_ro.user_profile.user_key` | NG | M | 5 | 1 | AF-02 | 1.50 → **3.00** (inherited from P1 H08) |
| 34 | AF-55 | Blacklisted-user order leakage | metric + drilldown | Risk | Tests whether checkout enforcement leaks | ecom_users + orders | NG | M | 5 | 1 | AF-06, AF-07 (H30 cohort) | 1.50 → **3.00** (inherited from P1 H29, H30) |
| 35 | AF-28 | Account-farm cluster alert | alert_trigger | Ops/risk | Would have fired on 2026-09-26 | ecom_users: `users_user`, tokens, blacklist | RN | M | 5 | — | AF-01 (trend) | 2.50 |
| 36 | AF-29 | OTP geo-policy and delivery-route scorecard | breakdown + alert | Ops, product | US/CA: only 49.8% of numbers register (53.5% of chains get no accepted code); RU block gap; whitelist overrides | ecom_users: OTP, lists, routing config | RN | M | 5 | — | AF-01 (trend) | 2.50 |
| 37 | AF-89 | Corporate gifting radar | breakdown | B2B, CRM | Claims by domain class and org-size bucket; top org clusters as opaque ids with k ≥ 50; burst-day count | ecom_users: activity log (via AF-88) | RN | M | 5 | — | AF-88 | 2.50 |
| 38 | AF-30 | Occasion impact analyst (seed `occasions.yaml`) | agentic_analysis | Marketing | Country diff-in-diff; Ramadan and December calendar | ecom_users (+ orders `occasion_code` later) | RN | M | 5 | — | — | 2.50 |
| 39 | AF-31 | "Why did signups move?" analysis | agentic_analysis | Leadership, growth | Breaks the change into country × gift × channel × resend × cutover | ecom_users (sandbox) | RN | M | 5 | — | AF-02, AF-12, AF-25 | 2.50 |
| 40 | AF-32 | Growth and lifecycle dashboard v1 | dashboard | Growth, CRM | One page with provenance chips; v2 adds orders | ecom_users | RN | M | 5 | — | — | 2.50 |
| 41 | AF-90 | Gifting network dashboard v1 | dashboard | Growth, leadership | Claims (lower-bound chip), gift-acquired share, org against freemail share with the AF-88 band, burst calendar and re-book list, birthday lift, returning-login gap, country shares. v2 adds k-factor (AF-71) and the recipient funnel. | ecom_users (AF-02, AF-03, AF-08, AF-09, AF-88, AF-89) | RN | M | 5 | — | AF-02, AF-03, AF-08, AF-09, AF-88, AF-89 | 2.50 |
| 42 | AF-33 | Occasion and personalisation mix | breakdown | Marketing | Occasion, scheduled against instant, reminder, lead time | orders personalise, quantity detail | NG | S | 4 | 2 | — | 2.40 |
| 43 | AF-34 | Favourite-brand × Plus-offer match | segment | Offers, CRM | Users whose favourite brand just got an offer | emapi favourites, `plusoffer` | NG | S | 4 | 3 | AF-10 | 2.40 |
| 44 | AF-35 | Arabic content gap alert | alert_trigger | Content | SA listings missing Arabic recipient instructions | emapi/ecomweb `brands_brand`; users language share | NG | S | 4 | 3 or 4 | — | 2.40 |
| 45 | AF-36 | Surface attribution by `purchase_origin` | breakdown | Growth, product | The first per-surface attribution in scope | orders `basket_line`, `order_line` | NG | S | 4 | 1 (order lines) + 2 (basket lines) | — | 2.40 |
| 46 | AF-71 | k-factor and gifting graph | metric + drilldown | Growth, leadership | Recipient → sender, reciprocal edges | orders personalise HMAC + users hashes | NG | L | 5 | 1 + 2 | — | 1.00 → **2.40** (inherited from P2 H49) |
| 47 | AF-50 | Occasion anniversary reminder | segment | CRM | A trigger the customer consented to (`is_reminder_added`) | orders personalise, `order_line`, `order_order` | NG | M | 5 | 1 + 2 | AF-10 | 1.50 → **2.40** (inherited from P2 H16) |
| 48 | AF-59 | Guest checkout and guest-to-account funnel | funnel | Growth | Merge rate, cart carry-over, returning guests | orders guest and merge tables | NG | M | 4 | 2 | — | 1.20 → **2.40** (inherited from P2 H19) |
| 49 | AF-60 | Denomination mix and default anchoring | breakdown | Merchandising | Which defaults sell | orders denominations, basket quantity detail | NG | M | 4 | 2 | — | 1.20 → **2.40** (inherited from P2 H21) |
| 50 | AF-48 | Payment decline and fraud-flag breakdown | breakdown | Ops, finance | Approval by gateway, method, card origin; retry rescue | orders youpay view, paymentdetail | NG | M | 5 | 2 | — | 1.50 → **2.40** (inherited from P2 H22, H54) |
| 51 | AF-51 | Gift issuance health alert | alert_trigger | Ops | Catches "paid but no gift" | orders `order_order`, gift log view | NG | M | 5 | 1 + 2 | — | 1.50 → **2.40** (inherited from P2 H41) |
| 52 | AF-61 | Plus-offer effectiveness board | dashboard | Offers | Avails → orders → GMV; budget and code inventory | orders offers, lines; emapi avails | NG | M | 4 | 1 + 3 | — | 1.20 → **2.40** (inherited from P2 H52) |
| 53 | AF-52 | Brand crosswalk (`upc` ↔ `code`) | metric (snapshot) | Data | Prerequisite for every brand metric | orders `catalogue_product`; emapi/ecomweb `brands_brand` | NG | M | 5 | 1 + 3 (+4) | — | 1.50 → **2.40** (inherited from AF-54, AF-58) |
| 54 | AF-58 | Viewed-not-bought / browse-abandon trigger | alert_trigger | CRM | The only browse signal in the estate | ecomweb `lastviewedbrand`; orders | NG | M | 4 | 1 + 4 | AF-10, AF-52 | 1.20 → **2.40** (inherited from P2 H17) |
| 55 | AF-54 | Merchandising placement effectiveness | breakdown | Merchandising | Sales by tag, shop-category and offer position | ecomweb/emapi merchandising + orders lines | NG | M | 5 | 1 + 3 + 4 | AF-52 | 1.50 → **2.40** (inherited from P2 H24) |
| 56 | AF-96 | Merchandising calendar playbook | dashboard | Merchandising | Seasonality (AF-30) + birthdays (AF-04) + `occasion_code` + current tag and slider layout: what to re-rank this week | ecom_users (ready) + ecomweb merchandising + orders personalise | NG | M | 4 | 2 + 4 | AF-04, AF-30 | 1.20 → **2.40** (inherited from P2 H63) |
| 57 | AF-37 | "What changed?" admin-config annotation (users v1) | dashboard + agentic | Ops | Config edits carry 50% of rule rows; overlays any chart | ecom_users `django_admin_log`, site config flags | RN | M | 4 | — | — | 2.00 |
| 58 | AF-38 | Trigger frequency governor + holdout assignment | segment + metric | Marketing | 3.8% overlap; intent-to-treat holdouts, audit-logged | derived trigger views | RN | M | 4 | — | — | 2.00 |
| 59 | AF-39 | Source freshness and data-integrity monitor | dashboard | Data, ops | Dead-field fill rates, retention windows, stuck counts, drift | ecom_users + catalog stats | RN | M | 4 | — | — | 2.00 |
| 60 | AF-40 | Shared-device and delete/re-create cluster drill-down | record_drilldown | Risk | 22x blacklist lift on shared devices; keyed device hash | ecom_users: tokens view | RN | M | 4 | — | — | 2.00 |
| 61 | AF-41 | Risk and integrity dashboard v1 | dashboard | Ops/risk | AF-06/07/13/21/28/29 on one page | ecom_users | RN | M | 4 | — | AF-06, AF-07, AF-13, AF-21, AF-28, AF-29 | 2.00 |
| 62 | AF-42 | Template coverage checker | metric (snapshot) | CRM | Flags the missing Arabic `password_expiry_warning` | ecom_users templates | RN | S | 2 | — | — | 2.00 |
| 63 | AF-43 | Offer coverage, badge integrity and generic-card breadth | metric (snapshot) | Offers | Duplicate badges; Happy Card breadth | emapi/orders offer tables | NG | S | 3 | 3 | — | 1.80 |
| 64 | AF-44 | Fraud investigation agent | agentic_analysis | Risk | Fingerprint diversity against a control; drafts a rule for human approval | ecom_users governed extracts | RN | L | 5 | — | — | 1.67 |
| 65 | AF-46 | True retention, dormancy and repeat purchase | breakdown | Marketing | Replaces the login floor with purchase recency | orders `order_order` | NG | M | 5 | 1 | — | 1.50 |
| 66 | AF-47 | First-purchase nudge audience | segment | Growth | Signed up N days ago, no order | ecom_users + orders | NG | M | 5 | 1 | AF-10 | 1.50 |
| 67 | AF-49 | Abandoned-basket trigger (non-empty only) | alert_trigger | CRM | Classic trigger, correct denominator | orders basket summary view | NG | M | 5 | 2 | AF-10 | 1.50 |
| 68 | AF-53 | Brand performance top-N | metric | Merchandising | Lines, units, GMV per brand per store | orders lines, quantity detail, catalog | NG | M | 5 | 1 | — | 1.50 |
| 69 | AF-56 | Cohort retention grid (login proxy, app/web split) | breakdown | Growth | First honest retention view (a floor) | ecom_users tokens | RN | M | 3 | — | AF-01 (trend) | 1.50 |
| 70 | AF-57 | Identity and audience-membership drill-down | record_drilldown | CS, CRM | "Why is this user in this audience", no PII | ecom_users | RN | M | 3 | — | — | 1.50 |
| 71 | AF-62 | Two-blacklist and fraud-flag reconciliation | agentic_analysis | Risk | Hashed overlap: users 8,760 against orders about 48.6k | ecom_users + orders + emapi | NG | M | 4 | 3 + 5 | — | 1.20 |
| 72 | AF-63 | Cross-service Kafka health grid | dashboard | Engineering | Throughput, errors, latency, duplicates | orders/emapi Kafka views | NG | M | 4 | 5 | — | 1.20 |
| 73 | AF-65 | Happy Card / offer viral loop | breakdown | Merchandising | Generic against single-brand recipient conversion | orders, emapi | NG | M | 4 | 1 + 2 + 3 | — | 1.20 |
| 74 | AF-66 | Brand availability matrix | dashboard | Merchandising | "Sold in AE but not SA" gaps | emapi/ecomweb `brands_brand`, stores | NG | M | 4 | 3 + 4 | — | 1.20 |
| 75 | AF-67 | Merchandising "what changed" log | alert_trigger | Merchandising | Brand sales move → prior admin edits | ecomweb/emapi admin logs; orders | NG | M | 4 | 1 + 5 | AF-52 | 1.20 |
| 76 | AF-68 | Webhook error rate (retained window) | metric | Engineering | Small, but cheap | orders/emapi webhook views | NG | S | 2 | 5 | — | 1.20 |
| 77 | AF-93 | Checkout health dashboard | dashboard | Growth, product, ops | One page: signup and claim funnels now; payment approval, abandoned baskets and gate config once granted; provenance and freshness on every tile. Partly ready now; scored as NG because its core tiles need tier 2. | ecom_users + orders views | NG | M | 4 | 1 + 2 | AF-03, AF-25, AF-48, AF-49 | 1.20 |
| 78 | AF-95 | Brand record drill-down | record_drilldown | Merchandising, CS | One brand: listings per store, channel flags, denominations, tags and positions, offers, favourites and views, 90-day sales, recent admin changes | all three commerce plugins | NG | M | 4 | 1 + 3 + 4 | AF-52 | 1.20 |
| 79 | AF-69 | Purchase funnel (non-empty basket → order → approved payment → gift) | funnel | Product, leadership | The core "where do we lose buyers" view | orders views + extract | NG | L | 5 | 1 + 2 | — | 1.00 |
| 80 | AF-70 | Checkout-gate diagnostics agent | agentic_analysis | Product, ops | "Why did conversion drop Tuesday?" answered with the config change | orders config + basket/order + admin log | NG | L | 5 | 1 + 2 + 5 | — | 1.00 |
| 81 | AF-72 | Brand affinity and cross-sell recommender | agentic_analysis | Product | Fills the empty cross-sell slot | orders lines + browse | NG | L | 5 | 1 + 4 | AF-52 | 1.00 |
| 82 | AF-73 | Supply-demand gap finder | agentic_analysis | Merchandising, BD | Missing brands, denominations and stores | catalog + orders + users | NG | L | 5 | 1 + 3 + 4 | AF-52 | 1.00 |
| 83 | AF-74 | Holdout-governed campaign readout | agentic + dashboard | Marketing | Incrementality with MDE and guard metrics | triggers + orders | NG | L | 5 | 1 + 2 (+ mailengine) | AF-38 | 1.00 |
| 84 | AF-75 | Cross-currency and price-drift breakdown | breakdown | Finance | Needs a daily FX snapshot | orders money columns, FX | NG | M | 3 | 1 | — | 0.90 |
| 85 | AF-76 | Order journey drill-down | record_drilldown | Ops, CS | "What happened to order X" without DB access | orders views | NG | M | 3 | 1 + 2 | — | 0.90 |
| 86 | AF-77 | App version, forced upgrade and signup-method recovery | breakdown | Product | Restores dead dimensions | emapi `users_user` view, version config | NG | M | 3 | 3 | — | 0.90 |
| 87 | AF-78 | Fraud-propagation gap forensics | agentic_analysis | Risk | What leaked during the 9-month silence | orders Kafka logs, blacklist, orders | NG | L | 4 | 1 + 5 | — | 0.80 |
| 88 | AF-94 | Browse-to-buy funnel per brand | funnel | Merchandising | Recently viewed / favourite → basket line → order line → gift claim, per brand and store; guest against registered | ecomweb `lastviewedbrand`, emapi `favouritebrand`; orders basket and order lines; users activity log | NG | L | 4 | 1 + 2 + 3 + 4 | AF-52 | 0.80 |
| 89 | AF-79 | Consent and channel preference | segment | Marketing, legal | Legal gate on every marketing send. Activation gate, not a build prerequisite: AF-04 (rank 8) and every other marketing trigger can be built without it but cannot send, so the consent-location decision is filed now at AF-04's urgency (roadmap, In parallel); the build score stays 0.75 until the source exists | consent store (location unknown) | NS | M | 5 | new source | — | 0.75 |
| 90 | AF-80 | Acquisition attribution (UTM, campaign, install) | breakdown | Marketing | The attribution gap in all four DBs; the GA4 plugin is scaffolded in the repo | GA4 (`backend/app/sources/ga4`), app analytics | NS | M | 5 | new source | — | 0.75 |
| 91 | AF-81 | Plus-offers redemption ledger | metric | Offers, finance | Reconciles three usage numbers | `ygag_plusoffers_db` | NS | M | 4 | new source | — | 0.60 |
| 92 | AF-82 | Message delivery and engagement (including OTP delivery receipts) | metric + breakdown | CRM, ops | Explains resends; open and click | `ygag_mailengine_aps_db`, `ygag_smsengine_db` | NS | L | 5 | new source | — | 0.50 |
| 93 | AF-83 | Full gift lifecycle (issued → claimed → redeemed / expired) | funnel | Product, leadership | Full claim population, not the lower bound | `ygag_ecom_gifts_db`, `ygag_ecom_gotagift_db` | NS | L | 5 | new source | — | 0.50 |
| 94 | AF-84 | Payment gateway truth, refunds and chargebacks | metric | Finance | Revenue net of refunds | `ygag_youpay_db` | NS | L | 4 | new source | — | 0.40 |
| 95 | AF-85 | Referral programme metrics | metric | Growth | No referral ledger exists; needs a product build | new referral ledger | NS | L | 4 | new source | — | 0.40 |
| 96 | AF-86 | Group gift and @Work B2B | breakdown | B2B | Real company dimension, not domain inference | `ygag_groupgift_aps_db`, `ygag_atwork_*` | NS | L | 3 | new source | — | 0.30 |
| 97 | AF-87 | Replica reader attribution | agentic_analysis | Engineering | Who does the 25.6 youpay full scans a day | RDS Performance Insights | NS | M | 2 | new source | — | 0.30 |

**Deliberately not proposed:**

- raw "baskets vs orders" abandonment;
- funnels built on the status-change log;
- token counts labelled MAU or DAU;
- any "gifts received" metric built on the claim event without the lower-bound chip.

# Plugin recommendations

## Order and rationale

| Order | Plugin | Database | When | Why |
|---|---|---|---|---|
| 1 | `ecom_users` | `ygag_ecom_users_db` | **Now** | Readable. Backs 46 of the 97 features: identity, OTP, gifting claims, lifecycle and risk. |
| 2 | `ecom_orders` | `ygag_ecom_orders_db` | After GRANTS tiers 1–2 | Highest value: purchase outcome for every hypothesis, occasions, payments, gift issuance, recipient hashes |
| 3 | `emapi_stores` | `ygag_emapi_stores_db` | After GRANTS tier 3 | Master catalog (6,610), offers and avails, favourites, app user mirror (`is_fraud`, `app_version`, `last_login`) |
| 4 | `ecomweb_stores` | `ygag_ecomweb_stores_db` | After GRANTS tier 4 | Web merchandising positions, recently-viewed brands, feedback box, email opt-ins |

The catalog theme suggested a single `catalog` plugin over emapi and ecomweb. The plugin contract has one connector per plugin, so we recommend two plugins that share a `brand_key` from the AF-52 crosswalk. Each plugin must declare `allowed_tables`. On blocked DBs, only `atlas_ro.*` views and column-granted tables go on that list.

## ecom_users (build now)

**Entities**

- `user`, keyed `user_key`:
  - dimensions: signup month, country, `is_app_user` (valid from Aug 2024), gender, birthday month/day, `legacy_state`, `is_deleted`, `trusted_user`;
  - derived: gift-acquired class, first-token platform, phone country.
- `identity_event` (from the activity log; comment excluded).
- `gift_claim`: claim time, minutes since signup, claim domain class, opaque org id with k ≥ 50, collision flags.
- `otp_chain`: derived with a 10-minute chain rule. Flow, channel, destination-country bucket, language, codes, accepted, outcome.
- `login_token`: platform, derived login country, OS family, keyed device hash, lifetime.
- `list_entry`: producer class, value key.
- `integration_event`.
- `admin_change`.

**First metric definitions**

| Kind | Definitions |
|---|---|
| Range metrics | `signups`, `signups_gift_acquired` (with share), `gift_claims` (lower-bound chip), `otp_chains_no_accept`, `otp_resend_chain_share`, `returning_login_users` ("floor, not MAU"; split app/web), `early_deletions`, `blacklist_adds` (by producer class) |
| Snapshot metrics | `birthday_audience_next_30d`, `live_users_by_legacy_state`, `blacklisted_live_accounts`, `unapplied_fraud_requests` (guest / registered), `trust_list_conflicts` |
| Funnels | `signup_verification` (requested → accepted → registered ≤1 h → first token) and `gift_claim_verification` (claim OTP → accepted → email attached ≤30 min) |
| Top-N breakdowns | country, language, destination prefix, platform, claim domain class |

**Allowlisted tables.** Migrate to `atlas_ro` views (GRANTS.md section 3). Until they exist, the YAML definitions must use raw columns only inside CTEs and never in the select list, and a definition lint enforces this. Tables:

- `users_user`
- `users_useridentityactivitylog`
- `users_secondaryuseridentity`
- `users_cognitoissuedtokens`
- `notifications_twofactorauth` (+ `...verification`)
- `users_migratedtransactionlog` (`legacy_auth_code` excluded; `user_reference` only inside CTEs)
- `core_blacklisteduserdetail`, `core_whitelisteduserdetail`, `users_promotionaldomainblacklist`
- `kafka_clients_blacklistuserconsumerdatalog`, `kafka_clients_blacklistuserproducerlog`
- `django_admin_log` (action columns only), `django_content_type`
- `core_siteconfiguration` (flags only)
- `notifications_communication*` configs and template configs (enumerated columns; template `template_data` excluded)

**PII exclusions.** Never selected:

- email, phone_number, alternate_email;
- activity `comment` (it holds the recipient email);
- names, ip_address, location, picture, raw social ids, password and legacy auth codes;
- jti, token_hash, raw `device_signature`, and `request_meta` IP_ADDRESS / USER_AGENT / TOKEN_DERIVATIVES;
- blacklist `value` and `remarks`;
- Kafka `data` and `payload`;
- `core_remoteurlconfig` secrets;
- `automation_accounts` emails;
- the encrypted email/phone on deleted rows;
- all admin, session and 2FA tables.

**Guardrails declared in the definitions**

- A `valid_from` on every signup trend, with warnings across Aug 2024 and May 2025.
- Gift metrics valid from 2024-08-05.
- The survived-day-1 denominator for any segment deletion comparison.
- Login metrics always split app/web.
- `2fa_account_verification` relabelled as "gift-claim / alternate-email verification".
- Business days in Asia/Dubai, storage in UTC.
- A minimum cell size of 10, and k ≥ 50 for org clusters.
- Promo-blocked domains are matched on the **first label** of the email domain (the list holds uppercase labels with no TLD), never on the full domain; AF-10 reads the in-DB `is_promo_blocked_domain` flag.

**Evals.** Before merge, add the goldens proposed in the gifting theme:

- claims in March 2026 = 2,626 (Asia/Dubai month);
- `signup_registration_by_code_count` for email = 82.7% (1 code) / 56.8% (2+ codes), per recipient over the pinned 31-day window (T18); the chain-level 80.7% / 56.7% is a separate breakdown with its own golden;
- the Sep 2026 gift-acquired share = 3.74%;
- live users on promo-blocked domains = 5,544 (label rule; a full-domain match returning 0 fails the golden);
- a "k-factor" question gets an honest failure;
- a "referrals last month" question gets an honest failure;
- a "gifts received" question does not answer with the claim count as if it were all gifts.

## ecom_orders (after grant)

**Entities**

- `order` (with user key and guest flag)
- `order_line`, with brand keyed on `upc` and 1:1 line money in reporting currency
- `occasion_line` (personalise, with recipient HMAC and `has_*` flags)
- `basket_summary` (non-empty baskets only, by default)
- `payment` (youpay deduplicated to the latest row per keyed `order_ref_key`; test V5 confirms the rule)
- `payment_attempt`
- `gift_issuance` (events per order, failure flags)
- `guest` and `guest_merge`
- `checkout_gate_config`
- `offer` (`plus_offer.offer_code_key`, the keyed `plusoffer.code`; joined to `order_line_keys.offer_code_key`)
- `checkout_block_entry` (value HMAC)

**First definitions**

- `orders`, `gmv_reporting_currency`, `first_orders`, `repeat_purchase_rate`, `days_since_last_order` bands
- `gift_acquired_first_order_rate` (cross-plugin; see below)
- `occasion_mix`, `reminder_lines`
- `payment_approval_rate` (deduplicated)
- `paid_orders_without_gift_event`

**Allowlist.** The GRANTS.md tier 1–2 tables and views.

**PII exclusions**

- All `order_order` `user_*` columns, `guest_email`, `owner`, `session_id`, `transaction_url`, `extra`.
- Recipient email and phone.
- `sender_name`, `personal_data_ref`.
- Card BIN/last4, `name_on_card`, customer fields, URLs and jsonb histories.
- Raw `guest_id` and guest-user ids (exposed only as the keyed `guest_key`).
- `created_gift_details`, `payload`, `failure`.
- `partner_line_notes` and `partner_line_reference`.
- Promo code values, and raw offer codes (`plusoffer.code`, `order_line.offer_code`), until GRANTS.md test V16 confirms they are not redeemable.
- Blacklist `value`.
- Raw gateway, order, invoice and loyalty references (`order_reference`, `payment_order_reference`, `transaction_id`, the customer-facing order `number`, basket and order `line_reference`, youpay `payment_reference`, `invoice_id`, `qitaf_request_id`, gift-log `order_id`, tip `reference_id`): keyed `*_key` columns only; Qitaf requests only as a presence flag.

**Allowlist entries (names exactly as in GRANTS.md §4).** Entities above are atlas names; the plugin's `allowed_tables` uses these source names:

| Kind | Names |
|---|---|
| `atlas_ro` views | `user_profile`, `order_flags`, `order_line_keys`, `occasion_line`, `basket_occasion_line`, `guest_user`, `guest_keys`, `guest_merge`, `basket_guest`, `basket_line_keys`, `youpay_derived` (with `response_class` and the keyed references), `gift_issuance_event`, `basket_summary` (materialized), `offer_promocode_key`, `plus_offer`; tier 5: `blacklist_entry`, `kafka_eventlog`, `kafka_datalog`, `personalization_ref`, `tip_ref`, `google_review_state` |
| Column-granted tables | `order_order`, `order_line`, `order_orderlinequantitydetail`, `users_customuser`, `order_orderlinepersonalisedetail`, `basket_basketpersonalisedetail`, `basket_mergedbasket`, `youpayclient_youpayclienttransactiondata`, `payment_paymentdetail`, `kafka_giftcreationlog`, `basket_basket`, `basket_line`, `basket_basketquantitydetail`, `offer_offerpromocode`; tier 5 logs as listed in GRANTS.md §4.4 |
| Table-level (no PII) | The 29 catalog, offer and checkout-config tables of GRANTS.md §4.3 (`offer_plusoffer` is read through the keyed `plus_offer` view) |

Entity → source: `order` = `order_order` + `order_flags`; `order_line` = `order_line` + `order_orderlinequantitydetail`; `occasion_line` = `occasion_line`; `payment` and `payment_attempt` = youpay columns + `youpay_derived` (+ `payment_paymentdetail`); `gift_issuance` = `gift_issuance_event`; `guest` / `guest_merge` = `guest_user`, `guest_keys`, `guest_merge`, `basket_guest`; `checkout_block_entry` = `blacklist_entry`.

**Recurring funnels run on a nightly extract**, because basket, youpay and the gift log are unindexed and the reader is shared by 40 databases.

**Cross-plugin joins** go only through `user_key`, which is HMAC(username) = HMAC(cognito_id). They run in the sandbox over governed extracts, after test V2 passes.

## emapi_stores (after grant)

**Entities**

- `brand_listing` and `brand` (via `brand_key`)
- `denomination` and `range`
- `category`, `tag`, `search_keyword`
- `generic_card` (deduplicated on the natural pair)
- `shop_category` and `merch_slot`
- `plus_offer` (offer code keyed only), `promo_code` (keyed HMAC only), `offer_avail`
- `favourite_brand`
- `app_user` (user key, `platform`, `app_version`, `last_login`, `is_fraud`, `has_*_id` flags)
- `app_version_gate`
- `kafka_event` (`has_error`, keyed `data_fingerprint`)

**First definitions**

- Catalog health (AF-17)
- Offer coverage and generic breadth (AF-43)
- Favourite × offer segment (AF-34)
- Forced-upgrade exposure (AF-77)

**PII exclusions:** user email, phone, names, user agent, IP, social ids, `sub`, legacy codes; `storelocation` contacts; `promo_code`; raw `brands_plusoffer.code`; Kafka `data`; webhook payloads; `remote_url_config` secrets; `to_emails`.

## ecomweb_stores (after grant)

**Entities**

- The web `brand_listing` with its nullable visibility flags
- Web merchandising: `tagbrand` positions, sliders, promo banners
- `recent_view` (`lastviewedbrand` by user key, deduplicated on the pair)
- `feedback_suggestion` (the matched catalog brand id; an unmatched suggestion only as a keyed count, never as text)
- `email_subscription` (newsletter opt-in by platform; a consent baseline for that newsletter only, not a CRM consent record)
- `web_user` (user key and flags only)
- `admin_change`

**First definitions:** the viewed-not-bought segment (AF-58), placement effectiveness (AF-54, with orders), the Arabic content gap (AF-35) and the brand availability matrix (AF-66).

**PII exclusions:** consumer email, phone, names, IP, user agent; `lastviewedbrand.username` raw; subscription and feedback emails; `remoteurlconfig` credentials; sessions; OTP devices.

**Load rule:** read from a daily extract, never from the storefront's hot path (8.5B brand primary-key lookups in 35.5 days).

# Access, risks and next databases

## Access and grant request summary

The full, DBA-ready request is in **GRANTS.md**. It covers:

- a dedicated read-only group role;
- a keyed-hash (HMAC) infrastructure that is identical in all four databases;
- per-database column grants and `atlas_ro` views;
- index and extract asks;
- a least-privilege clean-up of the users DB.

The tiers, with every feature and hypothesis they unlock. A feature or hypothesis that needs several tiers is listed under the **last** tier it needs, so it works once that tier lands (the full tier set is in the feature catalog's Tier column and the hypothesis catalog's Readiness column). The no-PII catalog, offer and checkout-config tables of orders (GRANTS.md §4.3) ship with tier 1.

| Tier | Contents | Features unlocked | Hypotheses unlocked |
|---|---|---|---|
| 0 | Role, schemas, HMAC key (all four DBs) | Safe cross-DB joins; prerequisite for every row below | — |
| 1 | orders identity + orders: `users_userprofile`, `order_order`, `order_line`, `order_orderlinequantitydetail`, plus the §4.3 catalog/config companions | AF-45, AF-46, AF-47, AF-53, AF-55, AF-64, AF-75; order-line half of AF-36 | H01, H08, H09, H12, H14, H23, H26, H27, H29, H30, H44, H50, H59, H64, H66, H71 |
| 2 | orders personalisation, guests, payments, gift-creation log, baskets | AF-33, AF-36 (complete), AF-48, AF-49, AF-50, AF-51, AF-59, AF-60, AF-69, AF-71, AF-74 (sends also need mailengine), AF-76, AF-93 | H13, H16, H19, H20, H21, H22, H31, H32, H41, H46, H47, H49, H54, H67, H68, H69, H70, H77 |
| 3 | emapi catalog, offers, favourites, app user view | AF-17 (app side), AF-34, AF-35 (app side), AF-43, AF-52 (orders + emapi), AF-61, AF-65, AF-77 | H18, H25, H28, H42, H43, H52, H58, H62, H65 |
| 4 | ecomweb merchandising, recently viewed, opt-ins | AF-17 (web side), AF-35 (web side), AF-54, AF-58, AF-66, AF-72, AF-73, AF-94, AF-95, AF-96 | H17, H24, H53, H60, H63 |
| 5 | Integration, risk and admin logs (orders, emapi, ecomweb) | AF-62, AF-63, AF-67, AF-68, AF-70, AF-78 | H37 |
| new source | Outside the four DBs | AF-79–AF-87; the blocked-claim-attempt part of AF-97 | H40, H45, H56, H73; the mechanism of H05, the opens of H15, the redemption side of H51 |

## Risks and data-quality traps

1. **Lower-bound and selection-biased gift signals.** The claim event misses gifts sent to primary emails, to guests and by phone, and it over-represents work email. Every gift chip must say "lower bound" or "share of claim events".
2. **Retention windows.** OTP is kept 31 days and web tokens 30. App tokens start 2026-07-13 and web tokens 2026-08-29. Without the AF-01 snapshot, trends are impossible.
3. **Tokens are not activity.** App tokens last 548 days and web tokens 30, and 67% of tokens are first logins. Never label them MAU or DAU, and never compare app with web.
4. **Regime cutovers:** Oct 2023, Aug 2024, Dec 2024, May 2025 and Nov 2025. Signup counts are not comparable across May 2025.
5. **`is_valid` is not success.** Count chains, not true rows.
6. **Basket denominator:** at least about 40% of baskets are empty.
7. **youpay fan-out:** there is no uniqueness on `order_reference`.
8. **Gift events are not gifts:** 2.64 per order on the extrapolated basis (2.54 on raw estimates). Say which basis a ratio uses.
9. **Brand keys:** `upc`, not `product_id`. One listing per store. Three catalog copies.
10. **Two blacklists and three fraud flags.** Always name the source. Blacklist rows are mostly rule output, not fraud cases.
11. **`is_guest` and the Kafka payload `guest_id` are not guest flags.** (The `order_order.guest_id` FK is; GRANTS.md exposes it only as a keyed `guest_key`.)
12. **Deleted accounts are encrypted,** and `modified_on` is not a deletion time. Ask engineering for a `deleted_at` column.
13. **Hashing.** An unkeyed md5 of an email, phone or domain can be reversed by dictionary. Use the keyed HMAC in GRANTS.md, with one normalisation function per kind on every side: blacklist values are normalised by type (a device value keeps its case so it matches the token device key), and phones drop a leading `00`. Recipient phones typed in national format (`05…`) match only through the store-country candidate key, and the match rate is measured (GRANTS.md test V13). The orders DB has no `pgcrypto` today.
14. **Reader contention.** One reader serves 40 databases, and basket, youpay and the gift log are unindexed. Use extracts, sampled queries and statement timeouts.
15. **Small cells and re-identification.** Corporate domains identify employers. Expose domain class and opaque ids only, with a minimum cell of 10 and k ≥ 50 for org clusters.
16. **Security today.** The atlas role can read users-DB secrets and raw PII. Least privilege is overdue (GRANTS.md section 3).
17. **Live incidents found during discovery** are escalated with severity, a proposed owner and a deadline in the executive summary (E1–E6). They are listed here only so that the risk list is complete.

## Adjacent databases worth analysing next (names only)

- `ygag_ecom_gifts_db`
- `ygag_ecom_gotagift_db`
- `ygag_mailengine_aps_db`
- `ygag_smsengine_db`
- `ygag_youpay_db`
- `ygag_checkout_db`
- `ygag_plusoffers_db`
- `ygag_groupgift_aps_db`
- `ygag_atwork_aps_v2_db`
- `ygag_ecom_wallet_restored_db`
- `ygag_mycredits_db`
- `ygag_rewards_db`
- `ygag_greetings_hub_db`
- `ygag_giftshop_db`
- `ygag_hub_db`
- `ygag_emapi_generics_db`

Non-database sources: AWS Cognito, GA4, and Firebase/app analytics.

# Recommended roadmap

## Now: ready on the users DB (weeks 0–6)

All 46 ready-now features are scheduled below **in catalog rank order** (section 6), so no feature waits on something scheduled later. Wave boundaries follow the effective scores; a feature never moves ahead of its rank except as the part of a prerequisite that ships with its dependent (AF-11's `legacy_state` dimension with AF-04).

1. **Foundations:**
   - the `ecom_users` plugin skeleton with the allowlist and a PII lint;
   - the AF-01 snapshot job (rank 1);
   - goldens for every new metric.
2. **Wave 1: ranks 2–14 (5.00), in rank order:**
   - suppression / risk-exclusion segment (AF-10);
   - blacklist enforcement-gap monitor (AF-06);
   - integration silence detector (AF-07);
   - gift-claim funnel (AF-03);
   - gift-acquired signups (AF-02);
   - failed sign-in win-back trigger (AF-05);
   - AF-11's `legacy_state` dimension, then the birthday audience (AF-04), with sends held until the consent decision;
   - domain classifier (AF-88), then the corporate burst alert (AF-08) and re-book list (AF-09);
   - OTP incident alert (AF-26), rescue queue for signup and gift claim (AF-27) and signup verification funnel (AF-25): M effort, pulled into Wave 1 because the P1 experiments H55, H51, H07, H61 and H02 need them.
3. **Wave 2: ranks 15–22 (4.00):** cutover registry (AF-12), blacklist volume by producer class (AF-13), early-deletion metric (AF-19), then the gift-acquired quality overlay (AF-16), the shell welcome-back segment (rest of AF-11), dormant gift recipients (AF-15), the gift-claim re-engagement scorecard (AF-14, which scores H10) and web-to-app migration (AF-18, inherited 4.00 because the P2 hypothesis H44 uses its cohort; built now so its tokens are snapshotted before tier 1 lands).
4. **Wave 3: ready-now ranks 24–31 (3.00):** signup/token burst alert (AF-24), token anomaly alert (AF-92), trust-list consistency check (AF-21), identity-collision queue (AF-22), market demand × language map (AF-23), send-time and weekday profile (AF-20, the scorecard for H15 and H76), gender × occasion segment (AF-91) and alt-email cap friction (AF-97). The 3.00 rows in between (AF-17 at rank 23; AF-64, AF-45 and AF-55 at ranks 32–34) need grants and are scheduled in "After grants".
5. **Wave 4: ranks 35–41 (2.50):** farm cluster alert (AF-28), geo-policy scorecard (AF-29), corporate gifting radar (AF-89), occasion analyst (AF-30), "why did signups move?" (AF-31), growth dashboard (AF-32) and gifting network dashboard (AF-90).
6. **Wave 5: the remaining ready-now rows (2.00 and below), in rank order:** "what changed?" annotation (AF-37), frequency governor with holdouts (AF-38), freshness and integrity monitor (AF-39), shared-device drill-down (AF-40), risk dashboard (AF-41, after all six of its blockers: AF-06, AF-07, AF-13, AF-21, AF-28, AF-29), template coverage checker (AF-42), fraud investigation agent (AF-44), cohort retention grid (AF-56) and audience-membership drill-down (AF-57).
7. **Experiments and analyses that need no grant, in order.** Each has a proposed owner (a role, to be confirmed) and a first milestone. The order follows priority, then live-incident exposure, then expected value.

   | Order | id | Priority | Proposed owner | First milestone |
   |---|---|---|---|---|
   | 1 | H33 RU farm rule replay | P1 | Risk and fraud operations lead | Replay on 90 days of RU signups, with a go / no-go on the rule, by 2026-10-01 (E1) |
   | 2 | H38 corporate claim-OTP allowlist / SMS fallback | P1 | Identity operations, with B2B | Domain-class split over 31 days; fallback agreed before the next B2B drop |
   | 3 | H55 claim-OTP storm loss | P1 | Identity operations, with CRM | Storm-day threshold wired into AF-26 (Wave 1, rank 12) |
   | 4 | H51 failed claim = unclaimed gift | P1 | CRM lead, with the identity PM | Later-add rate for failed claim chains, on the AF-27 claim segment (Wave 1, rank 13) |
   | 5 | H03 Arabic claim template | P1 | CRM lead, with the identity PM | Template fix and A/B live |
   | 6 | H61 phone-first signup OTP (email as fallback) | P1 | Identity product manager, with growth | Channel-default A/B live, read on the AF-25 funnel (Wave 1, rank 14); largest ready-now upside (up to about 3,070 registrations per 31 days) |
   | 7 | H02 phone OTP after the first email resend | P1 | Identity product manager | Runs as the post-resend arm inside the H61 split |
   | 8 | H07 "finish your account" link | P1 | Growth PM | 80/20 holdout via mailengine, on the AF-27 signup segment |
   | 9 | H06 failed sign-in fallback nudge | P1 | CRM lead | Randomised nudge; needs AF-01 and AF-05 |
   | 10 | H11 corporate pre-season outreach | P1 | B2B / @Work sales lead | Season list from AF-09 randomised |
   | 11 | H34 dynamic email filter before OTP | P2 | Identity engineering | Before/after count of OTPs to later-blocked recipients |
   | 12 | H48 1-hour deletions and risk flags | P2 | Risk and fraud operations | Flag-rate comparison |
   | 13 | H36 throttle-config event study | P2 | Identity engineering, with growth | Event study on config change days |
   | 14 | H04 WhatsApp claim channel | P2 | Identity product manager | A/B once a WhatsApp template is approved |
   | 15 | H05 US/CA direct routes | P2 | Messaging / SMS operations | Diff-in-diff by prefix (E6) |
   | 16 | H72 stale and inconsistent trust-list conflicts | P2 | Risk and fraud operations, with messaging / SMS operations | Per-country signup and OTP accept rates for the 13 conflict countries (E6 clean-up) |
   | 17 | H75 email fallback for non-GCC phone signups | P2 | Identity product manager, with growth | Fallback arm inside the H61 split; T9 baseline 32.5% (49 / 151) |
   | 18 | H15 local send windows, with H76 send day as its weekday factor | P3 | Marketing operations | One weekday × hour send test per country; scorecard AF-20 (Wave 3) |
   | 19 | H10 same-day follow-up to existing-user claimers | P3 | CRM lead | Holdout RCT by claim day; scorecard AF-14 (Wave 2) |
   | 20 | H74 rule-engine false positives after OTP | P3 | Risk and fraud operations, with growth | Later phone sign-up and whitelist-add rate for the 69 blacklisted-after-OTP recipients per 31 days |
   | 21 | H35, H39, H57 small-n monitors | P3 | Risk / identity operations | Run as monitors, not experiments |

8. **In parallel:** file GRANTS.md tiers 0–2 with the DBA (with the Appendix A generated DDL), and track the escalations E1–E6 with their owners from the executive summary. Raise the consent-store location decision (AF-79) now, at the urgency of its first dependent, the birthday audience (AF-04, rank 8): AF-04 can be built without it, but cannot send.

## After grants

1. **Tier 1–2 lands.** Run tests V1, V2, V4, V5, V8 and V13. Build the `ecom_orders` plugin with the nightly extract. Ship in catalog rank order; tier 1 rows start when tier 1 lands, tier 2 rows when tier 2 lands:
   - resend → purchase analysis (AF-64), recipient → buyer loop (AF-45) and order leakage (AF-55): the P1 prerequisites (inherited 3.00, ranks 32–34);
   - occasion mix (AF-33), surface attribution (AF-36) and k-factor (AF-71, inherited 2.40 from H49);
   - the P2 prerequisites (inherited 2.40, ranks 47–51): anniversary reminder (AF-50, H16), guest funnel (AF-59, H19), denomination anchoring (AF-60, H21), payment declines (AF-48, H22 and H54) and gift issuance health (AF-51, H41);
   - retention and repeat (AF-46), first-purchase nudge (AF-47), abandoned basket (AF-49);
   - brand performance (AF-53), which ships with the tier 1 §4.3 catalog companions (`catalogue_product.upc`) and does not wait for the cross-store crosswalk;
   - checkout health dashboard (AF-93, after its blockers AF-48 and AF-49);
   - then the purchase funnel (AF-69), campaign readout (AF-74, which also needs mailengine), FX drift (AF-75) and order drill-down (AF-76).

   Test the tier 1 P1 hypotheses first: H01, H08, H29 and H30. Next, as soon as tier 2 lands, H49 (k-factor, P2), because AF-71 and the v2 gifting dashboard measure the same loop, then H77 (failed 2FA chains and orders). Then the remaining tier 1–2 hypotheses in the section 8 order.
2. **Tier 3–4 lands.** Run test V3 (brand crosswalk, AF-52), then `emapi_stores` and `ecomweb_stores`, in rank order:
   - catalog health (AF-17);
   - favourite × offer (AF-34);
   - Arabic gap (AF-35);
   - the P2 prerequisites (inherited 2.40, ranks 52–56): Plus-offer board (AF-61, H52), brand crosswalk (AF-52, which AF-58 and AF-54 need), viewed-not-bought (AF-58, H17), placement effectiveness (AF-54, H24) and merchandising calendar (AF-96, H63);
   - offer coverage and generic breadth (AF-43);
   - Happy Card loop (AF-65) and brand availability matrix (AF-66);
   - brand drill-down (AF-95);
   - affinity and supply-demand agents (AF-72, AF-73);
   - forced-upgrade breakdown (AF-77) and browse-to-buy funnel (AF-94).

   Test H58 (fraud split-brain, V9) and H52 (on AF-61) as soon as tier 3 lands, then H17, H24 and H63 on their prerequisites once tier 4 lands.
3. **Tier 5 lands.** Blacklist reconciliation (AF-62, with test V10), Kafka health grid (AF-63), the "what changed" merchandising log (AF-67), webhook error rate (AF-68), checkout-gate diagnostics (AF-70) and gap forensics (AF-78).

## After new sources

1. **Messaging:** `ygag_mailengine_aps_db` and `ygag_smsengine_db`. OTP delivery receipts explain the resend and Arabic gaps. Send, open and click enable campaign readouts (AF-74, AF-82).
2. **Gifts:** `ygag_ecom_gifts_db` and `ygag_ecom_gotagift_db`. The full claim and redemption population (AF-83) replaces the lower bound.
3. **Attribution:** configure the existing GA4 plugin and app analytics (AF-80).
4. **Consent store (AF-79):** the legal gate on every marketing trigger. Its location still has to be found.
5. **Later:** `ygag_youpay_db` (AF-84), `ygag_plusoffers_db` (AF-81), group gift and @Work (AF-86). A referral programme ledger (AF-85) needs a product decision first; no such data exists anywhere today.

# Appendix: Considered and deferred

**Hypotheses: complete crosswalk.** Every hypothesis in the seven theme catalogs is listed here with the report id that carries it, so a merge or an omission can be checked line by line. 96 theme hypotheses map onto H01–H77; none is deferred or dropped. "Merged" means two theme items share a treatment, population and metric, or one is a sub-test of the other; the reason is given where it is not obvious. The evidence label on each Hxx row is the source theme's label.

| Theme | Theme id → report id |
|---|---|
| user-lifecycle (15) | H1 → H01 · H2 → H03 · H3a → H08 · H3b → H08 (repeat half) · H3c → H06 · H4 → H43 · H5 → H12 (merged: same birthday-week audience and self-purchase outcome; H12 uses a holdout instead of a random-time arm) · H6 → H16 · H7 → H14 · H8 → H44 · H9 → H48 · **H10 → H76** (added in round 3; the weekday factor of the H15 send test) · H11 → H17 · H11b → H19 · H12 → H42 |
| purchase-friction (15) | H1 → H01 (merged with user-lifecycle H1 and errors H1: same resend → first-order test) · H2 → H04 · H3 → H08 (merged: first-order rate of gift-acquired signups) · **H4 → H75** (added in round 3; not H05, which tests direct routes) · H5 → H20 · H6 → H21 (merged: default-denomination anchoring; the out-of-range custom-amount half is part of the H21 share breakdown) · H7 → H69 (lead time) + H16 (reminder repeat) · H8 → H22 · H9 → H54 · H10 → H68 · H11 → H70 · H12 → H62 · H13 → H55 · H14 → H29 · H15 → H23 |
| gifting-referral-network (13) | H1 → H09 (the login gap is its VALIDATED baseline) · H2 → H50 · H3 → H11 · H4 → H13 · H5 → H49 · H6 → H56 · H7 → H10 (merged: same treatment, population and metric) · H8 → H47 · H9 → H67 · H10 → H68 (merged with purchase H10: same merged-guest cohort, two outcomes) · H11 → H46 · H12 → H45 · H13 → H57 |
| campaigns-triggers (14) | H1 → H02 · H2 → H05 · H3 → H12 · H4 → H09 · H5 → H16 · H6 → H39 · H7 → H18 · H8 → H52 · H9 → H07 · H10 → H59 · **H11 → H77** (added in round 3; H51 and H03 cover the claim and template sides, not the order impact) · H12 → H49 (merged: new accounts per purchasing sender is the recipient → account edge of the k-factor) · H13 → H15 · H14 → H40 |
| catalog-brand-intelligence (14) | H1 → H24 · H2 → H25 · H3 → H17 (merged: repeat viewers are a stratum of the viewed-not-bought reminder test) · H4 → H18 · H5 → H21 · H6 → H12 (merged: birthday-month self-purchase) · H7 → H53 · H8 → H65 · H9 → H66 · H10 → H26 · H11 → H63 · H12 → H64 · H13 → H60 · H14 → H27 |
| errors-system-behavior (12) | H1 → H01 · H2 → H61 · H3 → H05 (merged: +1 routing to WhatsApp or voice) · H4 → H51 · H5 → H38 · H6 → H37 · H7 → H30 · H8 → H36 · **H9 → H74** (added in round 3) · H10 → H42 · H11 → H41 · H12 → H72 (merged with risk H11) |
| risk-fraud-integrity (13) | H1 → H28 · H2 → H29 · H3 → H31 · H4 → H32 · H5 → H30 · H6 → H05 (merged: US/CA delivery routes) · H7 → H71 · H8 → H35 · H9 → H34 · H10 → H33 · H11 → H72 (merged with errors H12) · H12 → H58 · H13 → H73 |

**Round-3 additions and the merges that were not recorded before**

| Source item | Outcome | Where it now lives | Reason |
|---|---|---|---|
| errors H9 (blacklisted after OTP: rule-engine false positives) | Added | H74 (P3) | VALIDATED baseline N31; small n (69 per 31 days) makes it a calibration, not a growth lever |
| purchase H4 (email fallback for non-GCC phone signups) | Added | H75 (P2) | VALIDATED baseline T9 (32.5%, 49 / 151); a different treatment from H05 (direct routes) |
| user-lifecycle H10 (AE-Friday / SA-Thursday send day) | Added | H76 (P3), run as the weekday factor of H15 | H15 tests send hours, not weekdays; the earlier revision had it only as feature AF-20, which is now its scorecard |
| campaigns H11 (failed 2FA/claim resend chains and orders) | Added | H77 (P2) | Failure rate VALIDATED (users profile B5, 1,208 of 3,555); the order impact needs tiers 1 + 2 |

**Round-2 additions and merges** (unchanged, kept for the record)

| Source item | Outcome | Where it now lives | Reason |
|---|---|---|---|
| errors H2 (phone-first signup OTP) | Added | H61 (P1) | Largest ready-now upside; H02 becomes its post-resend arm |
| purchase H12 (brand mobile-verification gate) | Added | H62 (P2) | The only brand-level checkout-friction test |
| catalog H11 (early occasion re-rank) | Added | H63 (P2) | Gives AF-96 a testable hypothesis and a holdout |
| catalog H12 (diaspora buyers) | Added | H64 (P2) | |
| catalog H8 (generic-card breadth vs sales) | Added | H65 (P3) | Cross-sectional, so diagnostic |
| catalog H9 (`purchase_origin` surface vs line value) | Added | H66 (P2) | |
| gifting H7 (burst-day onboarding) | Merged | H10 | Same treatment, population and metric (same-day follow-up to existing-user claimers, 30-day return 1.2% → 2.5%+, about 900 per arm) |
| gifting H9 (`occasion_code` virality) | Added | H67 (P3) | Its reminder-repeat half overlaps H16 |
| gifting H10 (merged guest senders as seed) | Merged with purchase H10 | H68 (P3) | Same cohort (merged against unmerged guests), two outcomes |
| purchase H10 (merged guests repeat 2x) | Merged with gifting H10 | H68 (P3) | As above |
| purchase H7 (scheduled-gift lead time) | Split | Lead time: H69 (P3); reminder repeat: H16 | The reminder half was already H16 |
| purchase H11 (cross-currency conversion) | Added | H70 (P3) | Feeds AF-75 |
| risk H7 (delete-then-recreate) | Added | H71 (P3) | n = 5 today; waits on the `deleted_at` engineering ask |
| risk H11 (stale whitelist overrides) | Merged with errors H12 | H72 (P2) | Same 13 conflict countries, same ready-now data |
| errors H12 (whitelist/blacklist OTP inconsistency) | Merged with risk H11 | H72 (P2) | As above |
| risk H13 (marketing waste on risky accounts) | Added | H73 (P3) | Needs campaign sends (new source) |
| gifting F17 (alt-email cap friction) | Added | AF-97 (rank 31, 3.00) | Scorecard for H56 |

**Features: complete crosswalk.** Every feature in the seven theme catalogs (146 rows) is listed with the report feature that carries it, so a merge or an omission can be checked line by line, the same way as the hypotheses above. The theme's impact rating is in brackets; every impact 4–5 item maps to a scored AF row. "Merged" items share a population and output with the AF row (reason given where not obvious); "part of" means the theme item is one tile, split or phase of that AF row. No theme feature is deferred or dropped. The only theme feature that is not an AF row is gifting F1, which is a base metric of the `ecom_users` plugin itself (section 7).

| Theme | Theme id [impact] → report id |
|---|---|
| user-lifecycle (26) | F1 [5] → AF-02 · F2 [5] → AF-25 · F3 [5] → AF-03 · F4 [4] → AF-26 (merged: resend-share alert per flow) · F5 [5] → AF-04 · F6 [3] → AF-56 · F7 [4] → AF-11 · F8 [3] → AF-18 · F9 [3] → AF-19 · F10 [3] → AF-20 · F11 [4] → AF-12 · F12 [3] → AF-57 · F13 [5] → AF-31 · F14 [5] → AF-45 · F15 [5] → AF-50 · F16 [5] → AF-46 · F17 [4] → AF-59 · F18 [3] → AF-77 · F19 [4] → AF-64 · F20 [5] → AF-32 · F21 [4] → AF-82 · F22 [5] → AF-80 · F23 [5] → AF-05 · F24 [4] → AF-16 · F25 [4] → AF-58 (its brand-affinity segments are AF-72) · F26 [3] → AF-59 (merged: returning guests by `last_accessed` band are a stage of the guest funnel) |
| purchase-friction (18) | F1 [5] → AF-03 · F2 [5] → AF-02 · F3 [4] → AF-26 · F4 [4] → AF-25 · F5 [4] → AF-27 (merged: claim half of the rescue queue) · F6 [4] → AF-01 · F7 [5] → AF-69 · F8 [5] → AF-48 · F9 [5] → AF-70 · F10 [4] → AF-60 · F11 [5] → AF-46 (merged: repeat purchase and time to second order are its cohort grid) · F12 [5] → AF-45 · F13 [3] → AF-59 · F14 [4] → AF-51 · F15 [3] → AF-76 · F16 [3] → AF-75 · F17 [4] → AF-33 · F18 [4] → AF-93 |
| gifting-referral-network (22) | F1 [3] → `gift_claims` plugin metric (section 7; surfaced as the claims tile of AF-90) · F2 [5] → AF-02 · F3 [5] → AF-89 · F4 [5] → AF-08 · F5 [4] → AF-15 · F6 [4] → AF-04 (merged: the "has claimed a gift before" split is a breakdown of the birthday audience) · F7 [5] → AF-30 (merged: claim series are one input of the occasion analyst) · F8 [5] → AF-45 (merged: the recipient → buyer → sender funnel; the sender stage is AF-71) · F9 [5] → AF-71 · F10 [4] → AF-71 (part of: its drill-down) · F11 [3] → AF-07 (silence alert per source) + AF-13 (adds by source) · F12 [3] → AF-22 · F13 [3] → AF-59 · F14 [4] → AF-65 · F15 [4] → AF-33 · F16 [5] → AF-90 · F17 [3] → AF-97 · F18 [4] → AF-85 (with AF-80 for UTM/invite attribution) · F19 [4] → AF-14 · F20 [3] → AF-88 · F21 [5] → AF-09 · F22 [2] → AF-16 (merged: survivor-adjusted deletion is one of its rates) |
| campaigns-triggers (22) | F1 [5] → AF-04 · F2 [5] → AF-27 · F3 [4] → AF-25 (merged: same funnel per recipient) · F4 [5] → AF-02 (ready part) + AF-45 (order part) · F5 [5] → AF-30 · F6 [3] → AF-11 · F7 [4] → AF-10 (part of: its per-audience suppression counts) · F8 [5] → AF-74 · F9 [5] → AF-47 · F10 [5] → AF-49 · F11 [5] → AF-50 · F12 [4] → AF-61 · F13 [4] → AF-34 · F14 [4] → AF-46 (merged: its dormancy bands include last order > 180 days, with last-order occasion and brand as dimensions) · F15 [5] → AF-82 · F16 [2] → AF-42 · F17 [3] → AF-33 · F18 [3] → AF-57 · F19 [5] → AF-02 (ready part) + AF-71 (graph part) · F20 [3] → AF-20 · F21 [4] → AF-38 · F22 [3] → AF-91 |
| catalog-brand-intelligence (20) | F1 [4] → AF-30 (merged: the seasonality calendar is the analyst's seeded `occasions.yaml` and its YoY view) · F2 [4] → AF-04 · F3 [3] → AF-23 · F4 [5] → AF-17 · F5 [4] → AF-66 · F6 [5] → AF-53 · F7 [5] → AF-73 · F8 [5] → AF-72 · F9 [5] → AF-54 · F10 [4] → AF-67 · F11 [4] → AF-94 · F12 [5] → AF-58 · F13 [4] → AF-60 · F14 [4] → AF-35 · F15 [3] → AF-43 · F16 [3] → AF-43 (merged: generic-card breadth) · F17 [4] → AF-95 · F18 [5] → AF-52 · F19 [4] → AF-36 · F20 [4] → AF-96 |
| errors-system-behavior (22) | F1 [5] → AF-25 (signup flow) + AF-03 (claim flow), both fed by the AF-01 snapshot (merged: chain completion by flow is the first step of each funnel) · F2 [5] → AF-26 · F3 [5] → AF-03 · F4 [5] → AF-25 · F5 [5] → AF-07 · F6 [4] → AF-07 (merged: the stuck-request half, guest against registered) · F7 [4] → AF-37 · F8 [4] → AF-13 · F9 [3] → AF-21 · F10 [4] → AF-06 · F11 [4] → AF-39 · F12 [3] → AF-92 · F13 [4] → AF-29 · F14 [4] → AF-27 · F15 [5] → AF-51 (merged: events per order, error class and retry span are its checks) · F16 [4] → AF-63 · F17 [3] → AF-77 · F18 [2] → AF-68 · F19 [3] → AF-62 · F20 [4] → AF-78 · F21 [2] → AF-87 · F22 [5] → AF-01 |
| risk-fraud-integrity (16) | RF1 [5] → AF-28 · RF2 [5] → AF-06 · RF3 [4] → AF-13 · RF4 [4] → AF-07 · RF5 [5] → AF-29 · RF6 [4] → AF-40 · RF7 [5] → AF-10 · RF8 [3] → AF-24 · RF9 [5] → AF-44 · RF10 [5] → AF-48 (merged: `is_fraud` / `is_flagged` rates per attempt are columns of the same deduplicated youpay breakdown) · RF11 [5] → AF-55 · RF12 [4] → AF-62 · RF13 [4] → AF-39 · RF14 [4] → AF-41 · RF15 [2] → AF-19 (merged: deletions by join cohort, with the no-`deleted_at` caveat) · RF16 [4] → AF-29 (merged: pumping against delivery failure is its per-country split) |

**Considered and deferred.** No theme feature or theme hypothesis is deferred in this revision. Two review items were considered and handled without a new catalog row:

| Item | Decision | Reason |
|---|---|---|
| A separate `is_promo_blocked_domain` feature | Not a new row; built into AF-10 and GRANTS.md `user_profile` | It is an input of the suppression segment, not a feature on its own; test V15 and a golden cover it |
| Raw `plusoffer.code` as the offer dimension | Deferred to GRANTS.md test V16 | The code may be redeemable, so atlas uses the keyed `offer_code_key` until the owner confirms otherwise; no feature loses function, because every offer join works on the key |
