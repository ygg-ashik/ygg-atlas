# Theme: Errors & system behavior

Built 2026-09-29 (13:20–13:45 UTC) by the analytics-strategy pass for ygg-atlas, from the seven critiqued profiles (`users.md`, `cross-db.md`, `orders-integrations.md`, `emapi-stores.md`, `ecomweb-stores.md`, `orders-funnel.md`, `orders-customer-catalog.md`) plus **31 new queries (N1–N31)** on `ygag_ecom_users_db`, the only readable DB. All new SQL is in the appendix. Nothing was run against orders, ecomweb or emapi data. No privilege workaround was attempted.

**Labels.** **VALIDATED** means a data query was run (new N-query, or a profile appendix id such as X30/C8). **STRUCTURAL** means it is inferred from catalog, stats or size only. **NEEDS-GRANT** means a hypothesis that needs rows we cannot read; the table.columns are named. `[inferred]` marks reasoning on top of a fact.

**Tooling note.** atlasq redacts ISO dates, so dates below come from `to_char`. "Dubai" means `Asia/Dubai` local date/hour; everything else is UTC.

---

## 0. Headline

1. **One gift-claim OTP incident is visible end-to-end in the readable data, and it would have been caught by a simple z-score alert.** On 2026-09-22 (Dubai), `2fa_account_verification` chains rose from about 87/day to **535**, and **74.8% of them never got an accepted code**. The baseline is about 22%. Most of these chains went to one corporate (non-freemail) email domain: from 15:00 Dubai, **575 recipients on it had 76.6% of gift-claim chains fail, and 809 had 69.7% of sign-up chains fail**, against 20.4% / 11.5% for everyone else. Token issuance hit z = 6.0 at 17:00 Dubai the same day. [VALIDATED, N16–N20]
2. **`2fa_account_verification` is the gift-recipient claim flow, not a login 2FA.** Only 41 of its 3,182 recipients are a registered user's primary email. 2,284 are now secondary identities and **1,857 were added via gift** (N14). This is the worst OTP flow: 23.5% of chains need a resend and 34% never complete [profile users §7]. **Every failed chain is a gift that did not reach an account.**
3. **The fraud-propagation Kafka path from gifts, orders and group gift into the identity service went silent for about 9 months, and no alert fired.** All three producers stopped on **2025-05-12**. Gifts resumed 2026-02-12 and orders 2026-02-22; group gift never resumed. **0 blacklist rows arrived from ecom_gifts from Jun 2025 to Jan 2026** (N29, N30). The legacy stream also had a gap (2025-08-19 → 2025-10-09), and September 2025 has no consumer rows at all. Separately, 1,298 orders-side messages are stuck `in_progress` with an empty `error_data` [X30].
4. **Delivery friction is country- and channel-specific, and it costs signups.** WhatsApp/SMS sign-up chains end in a registration within 1 h **94.3%** of the time; email chains **73.4%** (N11, N12). A second code costs about 30 points of completion on email (78.1% → 47.9%). **+1 (US/CA) numbers: 53.5% of chains never get an accepted code**; GB 20.8%; SA/AE 3.3% (N25).
5. **Config edits and blacklist surges happen on the same days.** Site-configuration edits in Django admin (the dynamic-throttle rule engine lives in `core_siteconfiguration`) fall on 64 of 486 days. Those days carry **50% of the rule-generated blacklist rows and 92% of the analyst-entered rows**. **All 7 days with ≥50 rule rows are config-change days** (N10). "What changed?" can be answered for the identity service today.

---

## 1. Insights

### 1.1 OTP delivery and resend chains

| # | Insight | Evidence | Label |
|---|---|---|---|
| I1 | **Each extra sign-up email code roughly halves the chance of registering.** Sign-up email chains (codes to the same address at most 10 min apart) followed by a registration within 1 h: 1 code **78.1%** (12,424 / 15,899), 2 codes **47.9%** (811 / 1,694), 3–4 codes **36.0%** (230 / 639), 5+ **37.0%** (88 / 238). Overall 13,553 / 18,470 = **73.4%**; 13.9% of chains need ≥2 codes. | N11 | VALIDATED |
| I2 | **Phone (WhatsApp+SMS) sign-up works much better than email.** 26,457 chains, **94.3%** registered within 1 h, only 3.0% need ≥2 codes. By country, 1-code chains: SA 96.7%, AE 96.5%, non-SA/AE 87.3%. 2-code chains: SA 69.4%, AE 75.4%, others **37.9%**. | N12 | VALIDATED |
| I3 | **SMS to +1 is broken, and several non-GCC routes are weak.** Share of sign-up phone chains with no accepted code (registered within 1 h): **US/CA 53.5% (46.5%)**, PK 24.6% (73.8%), "other" 23.1% (75.1%), GB 20.8% (78.9%), EG 10.8%, IN 8.4%; SA 3.3% (95.9%), AE 3.3% (96.0%), QA 4.0%, OM 2.6%. The +1 figure fits carrier A2P filtering of unregistered senders [inferred]. | N25 | VALIDATED |
| I4 | **`2fa_account_verification` = verifying a secondary (gift-claim) email.** Of 3,182 recipients in 31 days, 41 are primary user emails, 2,284 are now `users_secondaryuseridentity.alternate_email`, and 1,857 were `secondary_email_added_via_gift` since 2026-08-29 (490 self-added). A chain followed within 30 min by a secondary-email add: 1 code **71.8%**, 2 codes 53.8%, 3–4 codes 50.0%, 5+ **29.9%**. Overall 2,386 of 3,569 (66.9%), of which 1,877 are gift adds. | N14, N15 | VALIDATED |
| I5 | **Sign-in OTP → login token is a clean, measurable funnel.** Of 10,778 sign-in chains to a known user, **86.8%** get a login token within 15 min of the last code: 1 code 87.2%, 2 codes 82.5%, 3+ 77.6%. | N13 | VALIDATED |
| I6 | **The 2026-09-22/23 OTP spike was a corporate-domain delivery incident on top of a broad acquisition push.** Gift-claim chains per Dubai day: 23-day baseline about 87/day with 22.1% failing (N16 arithmetic). **Sep 22: 535 chains, 400 failed (74.8%)**; Sep 23: 374 chains, 58.3%; back to 24% by Sep 24. The spike came with only 95 and 125 gift adds on those days, so most of the extra chains produced no claim. **85.1% of Sep 22 gift-claim OTPs went to one non-freemail domain** (321 recipients), which has only 473 registered users in total, 380 of them signed up since Sep 15. The domain was neither blacklisted nor whitelisted. Across flows, that domain's chains fail 77.6% (sign-in), 76.6% (gift claim) and 69.7% (sign-up), against 10.7% / 20.4% / 11.5% for the rest. Recipients resent at up to 202 OTPs/hour. The pattern fits a corporate mail gateway delaying or quarantining OTP email during a bulk corporate gift drop [inferred]. It accounts for only 4–5% of that week's tokens (94 / 2,159 on Sep 22), so the Sep 22–25 signup surge was broader. | N16–N21 | VALIDATED (cause [inferred]) |
| I7 | **Login-token issuance has a stable hourly baseline, so anomalies stand out.** From 2026-08-30: 734 hours, median 51 tokens/h, mean 52.8, sd 30.9, p99 144, max 237. All 8 hours above p99 fall on Sep 22–24 (z up to 6.0 at Sep 22 17:00 Dubai). | N20 | VALIDATED |
| I8 | **`is_valid` is not a failure counter; "chain with no accepted code" is the failure signal.** Resends at a median of 77–129 s, inside the 5-min validity, point to delivery latency, not expiry. | users §7 (B2, B5, C9) | VALIDATED [profile] |
| I9 | **OTP history is a rolling 31-day window** (oldest row 2026-08-29 20:05 at 13:24 UTC today). Any OTP trend beyond 31 days needs atlas to snapshot it daily. | N4 | VALIDATED |
| I10 | **Blacklists gate signup at OTP time, and the rule engine can block after OTP acceptance.** 0 sign-up OTPs in 31 days went to an email or domain that was already actively blacklisted. **69 recipients were blacklisted after their OTP**: they averaged 2.51 codes and 98.6% had an accepted code, yet only **11.6% registered**. Clean recipients: 88.2% accepted, 78.8% registered. | N31 | VALIDATED |

### 1.2 Kafka integration logs: failure, retry, silence

| # | Insight | Evidence | Label |
|---|---|---|---|
| I11 | **The inbound fraud path went silent for about 9 months with no error recorded.** Consumer events from `ecom_gift`, `ecom_order` and `ecomgroupgift` all end on **2025-05-12**. The only events in Jun 2025–Jan 2026 are legacy ones, and Sep 2025 has none at all. Gifts resume 2026-02-12, orders 2026-02-22; group gift never does. The legacy stream is absent 2025-08-19 → 2025-10-09. In `core_blacklisteduserdetail`, `ecom_gifts` rows go 14 (May 2025) → **0 every month Jun 2025–Jan 2026** → 13 (Feb 2026). **So for about 8.5 months, fraud flagged in gifts or orders never reached the identity service.** The stop date is the same month as the users-id-sequence cutover (May 2025) and the last "population A" guest event (2025-05-12). A platform release in May 2025 probably changed both [inferred]. | N28, N29, N30; users §5 | VALIDATED (cause [inferred]) |
| I12 | **1,298 blacklist requests from orders are silently unapplied.** 902 are true guests (2024-04-15 → 2025-05-12, ended). **396 are registered users (389 distinct) and are still arriving: 5–10 per month through 2026, 58 in 2026, the last on 2026-09-28.** The probable cause is a payload without `mark_as_fraud` / `reference_id` (0 / 1,298, against 2,895 / 2,895 on completed events). `error_data` is empty on all 5,113 rows, and completed latency is 35–80 ms. | X15, X30, X32, N28 | VALIDATED |
| I13 | **The producer's `status=completed` means "published", not "delivered".** 14,150 of 14,150 are completed, with 0 s between created and modified. Delivery health must come from the consumer side of each service. Users → legacy publish lag, measured against the blacklist row's `created_on`: median 0.07 s, but **344 of 6,612 adds (5.2%) were published more than 1 h later** (p95 2.7 h). Part of that tail is re-activation of old rows (created_on is the first insert), so this is an upper bound. | X15b, N22 | VALIDATED |
| I14 | **Orders-side and emapi-side Kafka logs are larger and unreadable.** Orders `kafka_giftcreationlog` has about 3.13M rows, about 2.54 per order, unexplained (retries, per-unit events or duplicates). emapi has 4 consumer logs of about 2.87M rows in total with **no topic, offset or attempt column**, so retry detection needs payload hashing. Neither DB indexes status or time on these logs. | orders-integrations, emapi-stores | STRUCTURAL |
| I15 | **Consumer volume has "event storms" that follow admin bulk imports.** The users producer's legacy-sync volume was 1,417 in Aug 2026, against 110–650 in other months, the same month as the 797-row bulk email import on Aug 25. | N28; users C6b | VALIDATED |

### 1.3 Blacklist / whitelist sync and config-change history

| # | Insight | Evidence | Label |
|---|---|---|---|
| I16 | **Blacklist surges line up with admin config edits.** Since 2025-06-01, `siteconfiguration` was edited on 64 of 486 days (13%). On those days: 2,215 rule-account rows (34.6/day, against 5.3/day on other days) and 613 human rows (9.58/day, against 0.13). **All 7 days with ≥50 rule rows and all 7 days with ≥20 human rows are config-change days.** The dates match the rule-class starts in cross-db X27 (edits on 2025-07-22/24 and 2025-10-08/09) and the bulk-import days (2026-06-23/24, 08-11, 08-13, 08-25). | N6, N10 | VALIDATED |
| I17 | **The rule engine is a config document, and its thresholds are readable.** `core_siteconfiguration.config.dynamic_throttle_manager` has `enable_dynamic_throttle_manager=true` and adaptive attempts/delay both `false`. Managers: auth (`max.auth.throttles.for.account.blacklist=3`, ttl 3600), email (`max.email.throttles.for.email.blacklist=3`, `max.distinct.unverified.phone.count.per.email=3`), domain (5, 86,400 s), ip (5, ip ttl 54,000 s). There are geo-specific overrides for **23 countries, which include KW and OM but not SA or AE**. Also `disposable_usercheck_enabled=true`, `disposable_email_manager_enabled=true`, `voice_alert_config` (enabled, max.retries 5, otp.limit 22), `webauthn_enabled=false`, and a `drm_dashboard_state` with `global_lockdown` null (off). **These are the dials that explain the rule-generated blacklist rows** (usercheck 2,176, dynamic email 1,736, max login 551, dynamic domain 439, X27). | N7–N9 | VALIDATED |
| I18 | **The whitelist and blacklist contradict each other for 15 SMS countries.** 96 `sms_country_code` whitelist rows (62 active); 52 of them also appear in the blacklist, and **15 are active in both**, 3 of which were blacklisted after being whitelisted. None is a GCC country. The values are ISO-2 codes with mixed case (16 of 117 blacklist values are lower-case), and `UNIQUE(type,value)` is case-sensitive. | N23, N24 | VALIDATED |
| I19 | **Config changes are rare and have one editor.** Last-modified ages at 13:24 UTC: siteconfiguration 8.3 days (Sep 21), whitelist 15 days, SMS country configs (14 added Jun 2026) 116 days, remote URLs 110 days (8 edits by 3 staff in Mar 2026), captcha 140 days (9 edits in May 2026), channel config 2025-01-22. Almost every model has **one** editing account per month. An "admin change → metric shift" annotation layer is cheap. | N4, N5 | VALIDATED |
| I20 | **Blacklisting does not block login for existing accounts.** 903 live users match an active email or mobile blacklist entry; 12 of them got 18 tokens after being blacklisted. | users C8 | VALIDATED [profile] |
| I21 | **Two blacklists that disagree by design.** Users has 8,760 rows; orders `users_blacklisteduserdetail` has about 48.6k, is UNIQUE on (type, value) and is 157 MB of heap. "Is X blacklisted?" gets different answers in different DBs. | cross-db §1.3c | STRUCTURAL |

### 1.4 Data freshness, replica reads, app-version gates, webhooks

| # | Insight | Evidence | Label |
|---|---|---|---|
| I22 | **Replica lag is under a minute, and the users replica is almost idle.** At 13:24 UTC, max `date_joined`, OTP and token timestamps were all 0 min old. The replica restarted 2026-08-25 00:22 UTC (35.54 days ago; same date as the orders profile window). Since then the users DB has had **5,395 commits, 1,228 rollbacks and 341 temp files**, 1 session at query time. Its biggest reader is the `(username, is_enabled)` index (347,741 scans), consistent with atlas's own username joins. Production readers do not use this replica [inferred], so atlas extracts here are cheap and isolated. | N1–N4 | VALIDATED (counters) / STRUCTURAL (reading) |
| I23 | **The orders replica has one heavy unknown reader.** youpay table: about 25.6 full-size seq scans/day and about 616k PK-fetched rows/day, about 11.8% of all DB tuples returned. There is also a once-a-day pass touching 20 DBs (36 `xact_commit` each). `pg_stat_statements` cannot identify the reader because of heavy eviction (dealloc 664k). | orders-integrations | STRUCTURAL |
| I24 | **The ecomweb storefront reads config from the DB on every request** (platformchoice 73.2M seq scans; siteconfiguration 9.95M) **and polls empty feature tables** (upcomingoccasion 89k, announcement 52k scans). Webhook and Kafka logs there are purged to 0 heap rows (the PK index implies about 500–600k webhook messages at peak). | ecomweb-stores | STRUCTURAL |
| I25 | **Force-upgrade exposure cannot be measured from identity data.** `users_user.app_version` is 100% NULL, and token user-agents are webview/browser strings with no app version (Safari/Chrome/SamsungBrowser tokens only, N26). **OS versions in tokens are frozen by UA reduction**: 95.9% of Android tokens say "Android 10" and 96.8% of iOS tokens say "iOS 18", while browser builds are Safari 26.x (N27). The OS-gate side (`required_os_version`) cannot be evaluated from UA data. emapi has two gates: `emapi_generics_client_mobileappplatformversion` (16 rows, several per platform, no UNIQUE) and an **empty** `mobile_app_client_config`. The user side is `emapi.users_user.app_version` (NEEDS-GRANT). | N26, N27, users §10, emapi-stores | VALIDATED (users side) / STRUCTURAL (emapi) |
| I26 | **Webhook history is purged in every DB.** Orders `webhooks_merchantwebhookmessage` about 5.2k rows, emapi 1,629 rows (8.15 MB PK on a 1.06 MB heap), ecomweb 0 rows. Only a rolling window can back a webhook error rate. | profiles | STRUCTURAL |
| I27 | **Token issuance is mostly first logins,** so a token spike means a signup spike. 67% of Sep 2026 tokens went to users who joined less than a day earlier. Web tokens are visible only from 2026-08-29 (30-day life, purged). | users C4 | VALIDATED [profile] |

---

## 2. Hypotheses (testable, with test design)

| id | Statement | Audience | Test | Data | Evidence |
|---|---|---|---|---|---|
| H1 | Sign-up users who need ≥2 email OTP codes are ≥30% less likely to place a first order within 7 days than 1-code users, even after they register. | growth, product | Cohort registered users by the code count of their sign-up chain (N11 logic). Compare 7-day first-order rate; control for country and channel. | users OTP (31-day window, so snapshot daily) + orders `order_order(user/profile id, date_placed, status)` via `users_userprofile.cognito_id` = username | NEEDS-GRANT (G9, G1) |
| H2 | Switching sign-up OTP from email to WhatsApp/SMS as the default (with email fallback) lifts 1-h registration from about 73% to over 90% for email-first sign-ups. | product, growth | A/B on channel default. Primary metric: 1-h registration rate per chain (N11/N12 logic). Guardrail: OTP cost per registration. | users `notifications_twofactorauth` (+ snapshot) | VALIDATED baseline (N11, N12); experiment needed |
| H3 | +1 (US/CA) SMS OTPs fail because of carrier A2P filtering. Routing +1 to WhatsApp or voice (`voice_alert_config` exists, max.retries 5) raises accepted-code chains from 46% to over 85%. | ops, product | Route +1 to WhatsApp/voice for 2 weeks. Compare no-accept rate (N25) before and after. | users OTP + `notifications_communicationcountryconfigs` change date | VALIDATED baseline (N25) |
| H4 | Gift recipients whose claim OTP chain fails never claim the gift. That is about 1,183 unclaimed claim attempts per 31 days, and a share of those gifts expire unredeemed. | marketers, growth | For failed claim chains, count later successful adds for the same email (any time) and, once granted, gift redemption status. | users OTP + activity log (readable); gifts `gifts_gift` status/expiry | VALIDATED (claim side N15) / NEEDS-GRANT (redemption side) |
| H5 | Corporate recipient domains (non-freemail) have 3–5x the gift-claim OTP failure rate of freemail domains, and a "corporate mail allowlist / SMS fallback" nudge before a B2B drop halves it. | ops, B2B/@Work, marketers | Classify recipient domain as freemail or corporate (CASE list, no raw domain). Compare chain failure by class over 31 days, then pre/post for the next B2B drop. | users OTP (readable); @Work order timing (atwork DBs, not in scope) | VALIDATED for one domain (N19); general claim needs a 31-day class split |
| H6 | The 2025-05-12 Kafka stop and the May 2025 id-sequence cutover come from one release. Accounts flagged fraudulent in gifts/orders in Jun 2025–Jan 2026 went on to place orders or claim gifts that would otherwise have been blocked. | ops/risk | (a) `django_migrations.applied` in gifts/orders around 2025-05-12. (b) orders-side `kafka_blacklistusergiftlog` / `users_blacklisteduserdetail` rows created in the gap, compared with users core rows (N30 = 0). (c) orders placed by those identities after flagging. | orders `users_blacklisteduserdetail(type, source, created_on, md5(value))`, `kafka_blacklistusergiftlog(event_id, status, created_on)`, `django_migrations` | NEEDS-GRANT (G6, G7) |
| H7 | The 389 registered users whose orders blacklist request was never applied place orders at a higher rate after the request than matched non-flagged users, i.e. real leakage. | risk | Using the username, count orders after each user's `start_timestamp` and compare with a propensity-matched control. | users consumer log (readable) + orders `order_order` via cognito_id | NEEDS-GRANT (G1, G9) |
| H8 | Site-config edits to the dynamic throttle manager cause step changes in sign-up completion within 24 h (a stricter email or domain filter means fewer registrations). | ops/risk, growth | Event study: for each siteconfig change day (N6), sign-up chain completion (N11) in the 24 h before and after, and rule-row counts. Needs the change payload diff, keys only. | users `django_admin_log` (readable); daily OTP snapshots (only 31 days kept) | STRUCTURAL now; VALIDATED co-occurrence (N10) |
| H9 | Blacklisted-after-OTP recipients (rule engine firing between OTP and account creation) include real customers. Those who retry within 7 days through another channel (phone) convert at a measurable rate: the rule's false-positive signal. | risk, growth | Among the 69/31-day "blacklisted_after_otp" recipients (N31), look for a later phone-based sign-up or a support whitelist add. | users OTP, blacklist, whitelist (readable) | VALIDATED baseline (N31) |
| H10 | Users on app versions below `required_version` show a drop in token issuance and purchases in the 7 days after a forced-upgrade bump (upgrade wall churn). | product | Event study on `emapi_generics_client_mobileappplatformversion.modified_on` bumps, comparing app tokens/day (users) and orders by platform. | emapi `mobileappplatformversion` (config), `users_user.app_version, platform` (hashed id) | NEEDS-GRANT (G4 + blanket a) |
| H11 | `kafka_giftcreationlog` carries 2.54 events per order because of retries. Orders with more than 1 creation event have slower gift delivery and more support contacts. | ops | Bounded PK window: events per `order_id` by status; `modified_on − created_on` retry span. | orders `atlas_ro.kafka_giftcreationlog` view | NEEDS-GRANT (G7/G9) |
| H12 | The 15 SMS countries that are both whitelisted and blacklisted produce inconsistent OTP outcomes: sends succeed for some users and fail for others depending on the check order. | ops | Per conflicting country (ISO-2 mapped to dial prefix), 31-day phone OTP send and accept rates compared with non-conflicting non-GCC countries. | users OTP + lists (readable) | VALIDATED conflict (N23); test not yet run |

---

## 3. Atlas features

Ranked by impact. **Readiness:** ready-now = readable users DB; needs-grant = blocked DB; needs-new-source = outside Postgres or needs atlas snapshots.

| id | Feature | Type | Backing (plugin → tables) | Readiness | Effort | Impact |
|---|---|---|---|---|---|---|
| F1 | **OTP chain completion** by flow × channel × recipient country × day (`otp_chain_completion_rate`, `otp_resend_chain_share`, `otp_chains_no_accept`) | metric (range) + breakdown | `ecom_users` → `notifications_twofactorauth`, `…verification` (derived view `otp_chain`) | ready-now (31-day window; add daily snapshot) | M | 5 |
| F2 | **OTP incident alert**: z-score on hourly chains and failure share per flow, with auto drill-down to the dominant recipient-domain class, country prefix and channel | alert_trigger + agentic_analysis | same + `users_cognitoissuedtokens` | ready-now | M | 5 |
| F3 | **Gift-claim funnel**: claim OTP chain → accepted → secondary email added via gift (→ redeemed, once granted) | funnel | `users_useridentityactivitylog`, `users_secondaryuseridentity`, OTP tables; later gifts DB | ready-now (first 3 steps) | M | 5 |
| F4 | **Signup verification funnel**: OTP chain → accepted → account created within 1 h, split by channel and code count | funnel | OTP tables + `users_user.date_joined` (in-DB email/phone join, aggregated) | ready-now | M | 5 |
| F5 | **Integration silence detector**: per (service_name, event_type), hours since the last event against the typical inter-arrival time, plus stuck `in_progress` count and age | alert_trigger + metric (snapshot) | `kafka_clients_blacklistuserconsumerdatalog`, `…producerlog`, `…serviceinternalrefetchconsumerdatalog` | ready-now | S | 5 |
| F6 | **Unapplied blacklist requests** (guest vs registered), with record drill-down to hashed username and whether blacklisted elsewhere | metric (snapshot) + record_drilldown | consumer log + `core_blacklisteduserdetail` | ready-now | S | 4 |
| F7 | **"What changed?" annotation layer**: admin config changes (model, action, day, actor count) overlaid on any metric chart, plus a config-diff agent that names which throttle keys changed | dashboard + agentic_analysis | `django_admin_log`, `django_content_type`, `core_siteconfiguration` (keys/values of non-PII flags only); orders/ecomweb/emapi admin logs once granted | ready-now (users) / needs-grant (others) | M | 4 |
| F8 | **Blacklist ops board**: adds by source × creator class (rule vs analyst) × rule class, net of un-blacklists, bulk-import detector (≥40 rows/day, few minutes, single remark) | dashboard + metric | `core_blacklisteduserdetail`, producer log (regex-parsed view), `django_admin_log` | ready-now | M | 4 |
| F9 | **Trust-list consistency check**: whitelist ∩ blacklist conflicts, case-variant duplicates, rows active in one list and removed in the other | alert_trigger | `core_whitelisteduserdetail`, `core_blacklisteduserdetail` | ready-now | S | 3 |
| F10 | **Blocked-but-active monitor**: live accounts matching an active email or mobile blacklist entry that got a token after blacklisting (12 users / 18 tokens today) | alert_trigger + record_drilldown | `users_user`, blacklist, `users_cognitoissuedtokens` | ready-now | S | 4 |
| F11 | **Source freshness & replica health panel**: per governed table max(ts) age, OTP retention window, replica uptime, commits and temp files; provenance chips show freshness | dashboard + metric (snapshot) | all readable tables + `pg_stat_database`; catalog stats elsewhere | ready-now | S | 4 |
| F12 | **Token issuance anomaly**: hourly tokens against baseline, split new (joined ≤1 d) vs returning, platform, out-of-GCC share, shared-device bursts | alert_trigger + breakdown | `users_cognitoissuedtokens` + `users_user` | ready-now | S | 3 |
| F13 | **Delivery-route scorecard** by dial-prefix country: send volume, no-accept %, 1-h registration %; flags routes worse than 2x the GCC baseline (US/CA, PK, GB today) | breakdown + segment | OTP tables + `notifications_communicationcountryconfigs` | ready-now | S | 4 |
| F14 | **"Lost at the door" segment**: recipients with a failed sign-up or claim chain and no account or add within 24 h, as hashed email for a re-engagement channel (SMS, WhatsApp) | segment | OTP + users + activity log | ready-now (hash-only export needs a policy decision) | M | 4 |
| F15 | **Gift-creation pipeline health**: events per order, failure/error class mix, retry span, stuck events | metric + alert_trigger | orders `atlas_ro.kafka_giftcreationlog` | needs-grant | M | 5 |
| F16 | **Cross-service Kafka health grid** (orders atwork/plusoffer/solddate/blacklist/legacyfraud; emapi atwork/emapistores/plusoffer): throughput, `has_error`, latency p95, stuck, duplicate `data_md5` | dashboard | orders `atlas_ro.kafka_datalog`, `atlas_ro.kafka_eventlog`; emapi `atlas_kafka_*` views | needs-grant | M | 4 |
| F17 | **Force-upgrade exposure**: users per platform below `required_version` / `latest_version`, with a version-bump event study | metric (snapshot) + agentic_analysis | emapi `users_user.app_version/platform` (view), `emapi_generics_client_mobileappplatformversion`, `mobile_app_client_config` | needs-grant | M | 3 |
| F18 | **Webhook error rate** (rolling retention window only) | metric | orders `atlas_ro.webhook_message`; emapi `atlas_webhookmessage` | needs-grant | S | 2 |
| F19 | **Two-blacklist reconciliation**: hashed overlap per type between users (8,760) and orders (about 48.6k) lists | agentic_analysis | users blacklist + orders `users_blacklisteduserdetail` (md5 view) | needs-grant | M | 3 |
| F20 | **Fraud-propagation gap forensics** (the 9-month silence): orders-side events and blacklist adds during the gap, and orders placed by those identities | agentic_analysis | orders G6/G7 + order_order | needs-grant | L | 4 |
| F21 | **Replica reader attribution**: who does the 25.6/day youpay full reads and the daily cross-DB pass | agentic_analysis | RDS Performance Insights / `pg_stat_activity` sampling | needs-new-source | M | 2 |
| F22 | **OTP history snapshot** (daily roll-up of F1/F3/F4 so trends outlive the 31-day purge) | metric (range) | atlas-owned table fed from users OTP | needs-new-source (atlas job) | S | 5 |

The features most likely to impress a marketer are **F3 (gift-claim funnel)**, **F2 (OTP incident alert, with its "one corporate domain" drill-down)**, **F4 (each resend costs about 30 points of signups)** and **F14 (re-engage the lost-at-the-door segment)**.

---

## 4. Plugin notes

**Plugin `ecom_users` (identity; ready now).** Entities: `user` (key `username`), `otp_request`, `otp_chain` (derived), `login_token`, `identity_event`, `trust_list_entry`, `integration_event` (consumer/producer/refetch), `admin_change`, `config_flag`.
- **Allowlisted tables:** users_user (non-PII columns only), notifications_twofactorauth, notifications_twofactorauthverification, users_cognitoissuedtokens (excluding jti, token_hash, device_signature, IP and UA in request_meta), users_useridentityactivitylog (without `comment`), users_secondaryuseridentity (flags and timestamps), core_blacklisteduserdetail, core_whitelisteduserdetail (without `value`), kafka_clients_* (derived columns only), django_admin_log (without object_repr and change_message), django_content_type, core_siteconfiguration (whitelisted keys only), notifications_communication*configs, core_captchaconfigurations.
- **PII exclusions:** email, phone_number, alternate_email, activity `comment` (it holds the email), blacklist `value` and `remarks` (templated class only), Kafka `data`/`payload` values, request_meta IP_ADDRESS/USER_AGENT/TOKEN_DERIVATIVES, `core_siteconfiguration.config.automation_accounts` (keys are emails), core_remoteurlconfig api_key/api_secret/url, auth_code, device_signature.
- **Derived views** (connector SQL; joins on PII stay inside the DB and only aggregates leave):
  - `otp_chain(flow, channel, recipient_country (dial-prefix bucket), recipient_domain_class (freemail/corporate/blacklisted), started_at, codes, any_accepted, outcome ∈ {registered_1h, token_15m, secondary_added_30m, none})`. Chain = same recipient + flow, gap ≤10 min. This is the backbone of F1–F4, F13, F14.
  - `trust_list_entry(type, source, creator_class ∈ {rule, analyst}, rule_class, is_removed, created_on, value_md5, reference_is_username)`.
  - `integration_event(stream, service_name, event_type, status, payload_shape, started_at, completed_at, latency_s, has_reference, has_mark_as_fraud, population ∈ {guest_token, registered_uuid, n/a})`.
  - `producer_message(kind ∈ {blacklist_event, legacy_sync}, flag, fraud_type, created_on)`, regex-parsed from the Python-repr payload.
  - `config_flag(key_path, value)` over an allowlist of boolean/number leaves of `dynamic_throttle_manager`, `disposable_*`, `voice_alert_config`, `drm_dashboard_state.features`, `webauthn`, `update_phone_number`.
  - `freshness(table, max_ts, age_min)`.
- **Metric kinds:** chain metrics are *range* over `started_at`; stuck counts, blocked-but-active and trust-list conflicts are *snapshot*; breakdown top-N by country prefix, domain class or flow.
- **Freshness contract:** OTP is kept 31 days and web tokens 30 days; atlas must snapshot `otp_chain` daily (F22) or refuse questions older than 31 days honestly.

**Plugins `ecom_orders_integrations`, `emapi_stores`, `ecomweb_stores` (blocked).** Ship them with a manifest and only the catalog-level `freshness` / `replica_stats` entities now, labelled STRUCTURAL. Their Kafka, webhook and admin-log entities should consume only the `atlas_ro.*` views proposed in the profiles (has_error, err_class, data_md5, no payloads). Normalize both Kafka log families to the `integration_event` shape: (event_id, payload, status(200), error, created_on) and (data, status(20), error_data, start/completed). Retry detection in emapi needs `data_md5`; in orders it needs `event_id` uniqueness plus `order_id` fan-out.

---

## 5. Grants needed (PII-safe)

| DB.table | Columns | PII-safe form |
|---|---|---|
| orders `kafka_giftcreationlog` | id, created_on, modified_on, event_id, status, order_id; has_error, error_class, has_failure, failure_class, gifts_created | `atlas_ro.kafka_giftcreationlog` view; never payload or created_gift_details |
| orders `kafka_blacklistusergiftlog`, `kafka_legacyfraudsynclog` | id, created_on, modified_on, event_id, status, has_error, error_class | `atlas_ro.kafka_eventlog` view |
| orders `kafka_atworkkafkadatalog`, `kafka_plusofferkafkadatalog`, `kafka_solddateupdatekafkadatalog`, `kafka_blacklistuserkafkadatalog`, `kafka_productofferkafkadatalog`, `personalization_update_kafka_data_log` | id, status, start_timestamp, completed_timestamp, has_error, error_class | `atlas_ro.kafka_datalog` view; no `data` |
| orders `users_blacklisteduserdetail` | type, source, is_removed, is_guest, created_on, modified_on, md5(lower(trim(value))), reference_is_uuid | view; no raw value |
| orders `users_cognitouserdatasynclog` | id, created_on, modified_on, status, has_error (error jsonb keys only) | view; no payload |
| orders / ecomweb / emapi `django_admin_log` (+ `django_content_type`) | id, action_time, action_flag, content_type_id, object_id, user_id (count only); change_message field names | `atlas_ro.admin_change_keys` view |
| orders `core_commandexecuter` | id, created_on, command, start_date, end_date, status, input_type | column grant |
| orders `webhooks_merchantwebhookmessage`; emapi `webhooks_webhookmessage` | id, received_at, type, has_error, message_keys | view; no ip, message or error_message values |
| emapi `kafka_*kafkadatalog` (4) | id, status, start_timestamp, completed_timestamp, has_error, data_md5, data_bytes | `atlas_kafka_*` views |
| emapi `users_user` | id, platform, app_version, date_joined, last_login, is_fraud, is_deleted, md5(username) | `atlas_users_user` view |
| emapi `emapi_generics_client_mobileappplatformversion`, `mobile_app_client_config` | all columns (config, no PII) | plain grant |
| orders / ecomweb / emapi `django_migrations` | app, name, applied | plain grant (dates releases, tests H6) |
| orders `order_order` + `users_userprofile` | id, date_placed, status, user_id; md5(cognito_id) | view (for H1, H7) |
| ecom_gifts `gifts_gift` | order_id, status, created_on, redeemed/expired flags | view (for H4) |
| RDS Performance Insights on the replica | top SQL by DB | console access (for F21) |

---

## 6. Risks and data-quality traps

1. **`is_valid=false` is not a failed verification.** Count chains, not rows. Sign-up and sign-in chains can hold several `true` codes (21.6% / 39% of multi-code chains) [users C9].
2. **OTP and web tokens are purged at 31 / 30 days.** Month-over-month OTP metrics are impossible without an atlas snapshot. Token counts before 2026-08-29 exclude web.
3. **Producer `status=completed` means published.** It must never be shown as delivery success.
4. **`error_data` is empty even on stuck rows.** Error-rate metrics built on `error_data <> ''` read 0% during real outages. Use stuck / in_progress age and silence (inter-arrival) instead.
5. **Silence looks like health.** A throughput metric with no expected-rate baseline would have shown "0 errors" through the whole 2025-05 → 2026-02 gap. Alerts need a per-stream expected-activity model.
6. **`is_guest` and "has guest_id" are not guest flags.** 396 registered users arrive in `guest_id`. Test `reference/guest_id = users_user.username` instead.
7. **Blacklist volume mixes rule-engine output, analyst entries and bulk imports.** Split them, and net out 395 un-blacklists and 350 legacy removals. Bulk-import days (Jun 23–24, Aug 11/13/25 2026) are config-change days.
8. **Case-sensitive uniqueness** on trust lists: `sms_country_code` has mixed-case ISO-2 values; emails have 2 case/space variants [X40]. Normalize with `upper/lower(trim())`.
9. **Frozen user-agents.** "Android 10" and "iOS 18" dominate because of UA reduction. OS-gate exposure and OS-version breakdowns from token UAs are wrong. `users_user.app_version` is 100% NULL.
10. **May 2025 discontinuities:** the id-sequence cutover and the Kafka producer stop both fall in May 2025. Any trend spanning May 2025 (signups, fraud inflow) needs a regime marker.
11. **Replica stats windows differ**: the table/database counters cover 35.5 days since the 2026-08-25 restart; orders pg_stat_statements covers 95.5 days with heavy eviction. Never divide one by the other. Blocked-DB `reltuples` have unknown age.
12. **Purged logs understate volume**: webhooks (all DBs) and ecomweb Kafka logs. Rates only cover the retained window, and absolute counts are meaningless.
13. **Config-diff history is not stored.** `core_siteconfiguration` keeps only the current value, and the admin log has action counts but not values. Atlas must snapshot whitelisted flags daily to reconstruct "what changed".
14. **In-DB PII joins** (OTP email/phone ↔ users) must run inside the connector and return aggregates only. The recipient domain must be returned as a class, never as the domain string: corporate domains can identify an employer.
15. **Push campaigns and incidents overlap.** Sep 22–25 combined a broad acquisition push with a single-domain delivery failure. An alert that only watches totals would misattribute it; drill-down by domain class and country prefix is required.

---

## Appendix: SQL provenance (new queries, `ygag_ecom_users_db`, 2026-09-29)

All run via `atlasq.sh ygag_ecom_users_db <rows>`. Date formatting through `to_char` (atlasq redacts ISO dates).

**N1 replica table read counters**
```sql
select relname, seq_scan, seq_tup_read, idx_scan, idx_tup_fetch from pg_stat_user_tables where coalesce(seq_scan,0)+coalesce(idx_scan,0)>0 order by coalesce(seq_tup_read,0)+coalesce(idx_tup_fetch,0) desc limit 40;
-- users_user seq 162 / idx 440,050; notifications_twofactorauth seq 869; core_blacklisteduserdetail seq 2,427 ...
```
**N2 replica uptime and DB counters**
```sql
select to_char(pg_postmaster_start_time() at time zone 'utc','YYYY "m" MM "d" DD HH24:MI'), round(extract(epoch from now()-pg_postmaster_start_time())/86400,2), d.xact_commit, d.xact_rollback, d.tup_returned, d.tup_fetched, d.conflicts, d.deadlocks, d.temp_files, to_char(d.stats_reset,'YYYY "m" MM "d" DD'), (select count(*) from pg_stat_activity where datname=current_database()) from pg_stat_database d where datname=current_database();
-- 2026-08-25 00:22 | 35.54 | 5,395 | 1,228 | 286,046,738 | 3,586,542 | 0 | 0 | 341 | null | 1
```
**N3 index usage**
```sql
select relname, indexrelname, idx_scan, idx_tup_read from pg_stat_user_indexes where idx_scan>0 order by idx_scan desc limit 25;
-- users_user (username,is_enabled) 347,741; users_user pkey 83,966; secondaryuseridentity user_id idx 59,598 ...
```
**N4 freshness snapshot (13:24 UTC)**
```sql
with f as (select 'users_user.date_joined' t, max(date_joined) mx, min(date_joined) mn from users_user
 union all select 'otp.created_on', max(created_on), min(created_on) from notifications_twofactorauth
 union all select 'tokens.created_on', max(created_on), min(created_on) from users_cognitoissuedtokens
 /* … blacklist, whitelist, kafka consumer/producer/refetch, activity log, admin log, siteconfig, captcha, remoteurl, comm configs … */)
select t, to_char(mx at time zone 'utc','YYYY "m" MM "d" DD HH24:MI'), round(extract(epoch from now()-mx)/60), to_char(mn at time zone 'utc','YYYY "m" MM "d" DD HH24:MI') from f;
-- users/otp/tokens 0 min; OTP min 2026-08-29 20:05; consumer 200 min; producer 35; siteconfig 2026-09-21 07:04; whitelist 09-14; captcha 2026-05-12; channel cfg 2025-01-22
```
**N5 admin changes by model × month (excluding user and blacklist)**
```sql
select ct.model, to_char(date_trunc('month',l.action_time),'YYYY "m" MM'), l.action_flag, count(*), count(distinct l.user_id)
from django_admin_log l join django_content_type ct on ct.id=l.content_type_id where ct.model not in ('user','blacklisteduserdetail') group by 1,2,3 order by 1,2,3;
```
**N6 siteconfiguration change days since 2025-06**
```sql
select to_char(date_trunc('day',l.action_time),'YYYY "m" MM "d" DD'), count(*), count(distinct l.user_id) from django_admin_log l join django_content_type ct on ct.id=l.content_type_id
where ct.model='siteconfiguration' and l.action_time >= '2025-06-01' group by 1 order by 1;   -- 64 days
```
**N7 site config key names (names only; automation_accounts keys are redacted emails and not used)**
```sql
select k, jsonb_typeof(config->k), case when jsonb_typeof(config->k)='object' then (select string_agg(k2, ',' order by k2) from jsonb_object_keys(config->k) k2) end from core_siteconfiguration, jsonb_object_keys(config) k;
```
**N8 / N9 throttle-manager structure, thresholds, flags (boolean/number leaves only)**
```sql
with c as (select config->'dynamic_throttle_manager'->'dynamic_throttle_config' t from core_siteconfiguration)
select k, jsonb_typeof(t->k), case when jsonb_typeof(t->k)='object' then (select string_agg(k2||'='||case when jsonb_typeof(t->k->k2) in ('boolean','number') then (t->k->k2)::text else jsonb_typeof(t->k->k2) end, ' | ' order by k2) from jsonb_object_keys(t->k) k2) end from c, jsonb_object_keys(t) k;
with c as (...) select 'enabled_countries_n', (select count(*) from jsonb_object_keys(t->'enabled_countries'))::text from c
 union all select 'gcc_in_enabled', (select string_agg(x, ',') from jsonb_object_keys(t->'enabled_countries') x where x in ('AE','SA','QA','KW','BH','OM')) from c
 union all select 'flags', (t->'enable_adaptive_attempts_limit')::text||'/'||(t->'enable_adaptive_throttle_delay')::text||'/'||(t->'enable_dynamic_throttle_manager')::text from c /* + per-manager key=value */;
-- 23 countries (KW, OM only GCC); flags false/false/true; auth max 3; email max 3; domain 5; ip 5
select k, (config->k)::text from core_siteconfiguration, jsonb_object_keys(config) k where k in ('disposable_usercheck','disposable_email_manager','update_phone_number','webauthn_authentication','secondary_identity');
```
**N10 blacklist writes on config-change days vs other days**
```sql
with svc as (select distinct created_by_id id from core_blacklisteduserdetail where source<>'ecom_users'),
days as (select generate_series('2025-06-01'::date, current_date, '1 day')::date d),
cfg as (select distinct (l.action_time at time zone 'utc')::date d from django_admin_log l join django_content_type ct on ct.id=l.content_type_id where ct.model='siteconfiguration'),
bl as (select (created_on at time zone 'utc')::date d, count(*) filter (where created_by_id in (select id from svc)) rule_rows, count(*) filter (where created_by_id not in (select id from svc)) human_rows
 from core_blacklisteduserdetail where source='ecom_users' and created_on>='2025-06-01' group by 1),
j as (select days.d, (c.d is not null) cfg_day, coalesce(b.rule_rows,0) r, coalesce(b.human_rows,0) h from days left join cfg c on c.d=days.d left join bl b on b.d=days.d)
select cfg_day, count(*), sum(r), round(avg(r),1), percentile_cont(0.5) within group (order by r), sum(h), round(avg(h),2), count(*) filter (where h>=20), count(*) filter (where r>=50) from j group by 1;
-- false: 422 days, 2,255 rule (5.3/d), 53 human, 0 / 0 ; true: 64 days, 2,215 rule (34.6/d), 613 human (9.58/d), 7 / 7
```
**N11 sign-up email chain length → registration within 1 h**
```sql
with r as (select lower(t.email) e, t.created_on, t.id, v.is_valid,
  case when t.created_on - lag(t.created_on) over (partition by lower(t.email) order by t.created_on, t.id) <= interval '10 minutes' then 0 else 1 end newc
 from notifications_twofactorauth t join notifications_twofactorauthverification v on v.reference_id_id=t.id where t.source='sign_up' and t.auth_type='email' and coalesce(t.email,'')<>''),
c as (select *, sum(newc) over (partition by e order by created_on, id rows unbounded preceding) cid from r),
ch as (select e, cid, count(*) codes, bool_or(is_valid) any_valid, min(created_on) st, max(created_on) en from c group by 1,2),
u as (select lower(email) e, min(date_joined) dj from users_user where email is not null group by 1)
select case when codes=1 then '1' when codes=2 then '2' when codes<=4 then '3-4' else '5+' end, count(*), count(*) filter (where any_valid), count(u.e),
 count(*) filter (where u.dj between ch.st - interval '5 minutes' and ch.en + interval '1 hour'), round(100.0*count(*) filter (where u.dj between ch.st - interval '5 minutes' and ch.en + interval '1 hour')/count(*),1)
from ch left join u on u.e=ch.e group by 1 order by 1;
-- 1: 15,899 / 12,424 (78.1%); 2: 1,694 / 811 (47.9%); 3-4: 639 / 230 (36.0%); 5+: 238 / 88 (37.0%)
```
**N12 sign-up phone chain length → registration by SA/AE/other** (same chain logic on `phone_number`, `auth_type in ('whatsappsms','whatsapp')`, joined to `users_user.phone_number`; `group by rollup(cc, bucket)`)
```sql
-- total 26,457 chains, 24,948 registered within 1h (94.3%); SA 1-code 96.7%, AE 96.5%, other 87.3%; 2-code SA 69.4%, AE 75.4%, other 37.9%
```
**N13 sign-in and gift-claim chains → token within 15 min** (chain on `source, lower(email)`; `exists (select 1 from users_cognitoissuedtokens k where k.user_id=u.uid and k.created_on between ch.st and ch.en + interval '15 minutes')`)
```sql
-- sign_in: 10,913 chains, 10,778 known users, 9,353 tokens (86.8%); 1 code 87.2%, 2 82.5%, 3+ 77.6%; 2fa_account_verification: 3,569 chains, only 50 known primary users
```
**N14 gift-claim OTP recipients vs secondary identities**
```sql
with o as (select distinct lower(email) e from notifications_twofactorauth where source='2fa_account_verification' and coalesce(email,'')<>''),
s as (select distinct lower(alternate_email) e from users_secondaryuseridentity)
select (select count(*) from o), (select count(*) from o join s using (e)),
 (select count(*) from o where e in (select lower(email) from users_user)),
 (select count(*) from o join (select distinct lower(comment) e from users_useridentityactivitylog where activity='secondary_email_added_via_gift' and "timestamp">='2026-08-29') g using (e)),
 (select count(*) from o join (select distinct lower(comment) e from users_useridentityactivitylog where activity='secondary_email_added' and "timestamp">='2026-08-29') g using (e));
-- 3,182 | 2,284 | 41 | 1,857 | 490
```
**N15 gift-claim chain length → secondary email added within 30 min** (chains as N11 on source `2fa_account_verification`; materialized activity CTE joined on `lower(comment)=e and ts between st and en+30min`)
```sql
-- 1: 2,734 → 1,962 (71.8%); 2: 522 → 281 (53.8%); 3-4: 246 → 123 (50.0%); 5+: 67 → 20 (29.9%); total 3,569 → 2,386 (66.9%), 1,877 via gift
```
**N16 daily gift-claim chains, failures, gift adds (Dubai dates)**
```sql
-- ch as in N15; d: (st at time zone 'Asia/Dubai')::date, count(*), count(*) filter (where codes>=2), count(*) filter (where not any_valid); joined to daily secondary_email_added_via_gift
-- Aug 30–Sep 21: 2,004 chains / 443 failed (22.1%), 87.1/day; Sep 22: 535 / 400 (74.8%), 95 gift adds; Sep 23: 374 / 218 (58.3%); Sep 24: 178 / 43 (24.2%)
```
**N17 spike-day recipient profile**
```sql
-- per Dubai day since Sep 19: otps, distinct recipients, distinct domains, max(domain count)/count (top_dom_share), blacklisted-domain / blacklisted-email hits, now-secondary count, max OTPs per hour
-- Sep 22: 960 OTPs, 427 recipients, 49 domains, top share 85.1%, max 202/hour
```
**N18 dominant domain class per day** (CASE freemail list → 'freemail' / 'non_freemail'; domain string never returned)
```sql
-- Sep 22–24 top domain non_freemail (817 / 442 / 120 OTPs), not blacklisted or whitelisted, 473 registered users on it
```
**N19 spike domain vs rest since Sep 15, by flow** (chains per `source, lower(email)`; `is_top` = domain equals the Sep 22 top domain)
```sql
-- 2fa: top 787 chains / 575 recips / 76.6% fail vs rest 20.4%; sign_up: top 1,317 / 809 / 69.7% vs 11.5%; sign_in: top 49 / 77.6% vs 10.7%; first seen 09-22 15h Dubai; 380 signups on domain since Sep 15
```
**N20 hourly token baseline and outliers**
```sql
with h as (select date_trunc('hour',created_on) hr, count(*) n, count(distinct user_id) u, count(*) filter (where user_platform='WEB') web from users_cognitoissuedtokens where created_on>='2026-08-30' group by 1),
s as (select percentile_cont(0.5) within group (order by n) med, percentile_cont(0.99) within group (order by n) p99, avg(n) mu, stddev(n) sd from h)
select ... from h, s where n > s.p99;
-- 734 h, median 51, mean 52.8, sd 30.9, p99 144, max 237; outliers: Sep 22 16–20h (183–237, z 4.2–6.0), Sep 23 14–15h, Sep 24 14h
```
**N21 daily tokens and share on the spike domain** — Sep 22: 2,159 tokens, 94 on the domain; Sep 24: 2,372 / 113.

**N22 users → legacy publish lag**
```sql
with p as materialized (select created_on pc, substring(payload from $$'fraud_type': '([a-z_]+)'$$) ft, substring(payload from $$'fraud_value': '([^']*)'$$) fv, substring(payload from $$'is_removed': (True|False)$$) rm from kafka_clients_blacklistuserproducerlog where payload like '%fraud_type%'),
m as (select pc, rm, fv, case ft when 'domain' then 'user_domain' when 'email_address' then 'user_email' when 'phone' then 'user_mobile_no' when 'ip_address' then 'user_ip' end ct from p),
j as (select extract(epoch from m.pc - b.created_on) lag_s from m join core_blacklisteduserdetail b on b.type=m.ct and b.value=m.fv where m.rm='False')
select count(*), percentile_cont(0.5) within group (order by lag_s), percentile_cont(0.95) within group (order by lag_s), count(*) filter (where lag_s > 60), count(*) filter (where lag_s > 3600) from j;
-- 6,612 | 0.065 s | 9,766 s | 410 | 344
```
**N23 whitelist ∩ blacklist**
```sql
select w.type, count(*), count(*) filter (where not w.is_removed), count(b.id), count(b.id) filter (where not w.is_removed and not b.is_removed), count(b.id) filter (where not w.is_removed and not b.is_removed and b.created_on > w.created_on)
from core_whitelisteduserdetail w left join core_blacklisteduserdetail b on b.type=w.type and lower(b.value)=lower(w.value) group by 1;
-- sms_country_code 96 / 62 / 52 / 15 / 3; user_domain 12/12/6/0; user_email 11/10/3/0
```
**N24 SMS country list case mix**
```sql
select 'bl', count(*), count(*) filter (where value ~ '^[a-z]{2}$'), count(*) filter (where value ~ '^[A-Z]{2}$'), count(*) filter (where not is_removed), count(distinct upper(value)) from core_blacklisteduserdetail where type='sms_country_code'
union all select 'wl', ... from core_whitelisteduserdetail where type='sms_country_code';
-- bl 117 (16 lower, 101 upper, 101 active); wl 96 (0 lower, 62 active); 0 GCC among conflicts
```
**N25 sign-up phone chains by dial-prefix country** (N12 chain logic over all sign_up phone OTPs, CASE on prefix)
```sql
-- SA 14,271 chains: 2.7% multi, 3.3% no-accept, 95.9% reg; AE 8,615: 3.3% / 96.0%; US/CA 288: 8.7% multi, 53.5% no-accept, 46.5% reg; GB 356: 20.8% / 78.9%; PK 65: 24.6% / 73.8%; other 654: 23.1% / 75.1%; EG 333: 10.8%; IN 345: 8.4%
```
**N26 product tokens in app user-agents** [sample 20%]
```sql
select user_platform, m[1], count(*) from users_cognitoissuedtokens tablesample system (20), regexp_matches(coalesce(request_meta->>'USER_AGENT',''), '([A-Za-z][A-Za-z_.-]{1,30})/[0-9]', 'g') m where user_platform like 'app%' group by 1,2 order by 3 desc limit 30;
-- only Mozilla/AppleWebKit/Safari/Chrome/SamsungBrowser/... — no app product/version token
```
**N27 OS name and major version on app tokens**
```sql
select user_platform, request_meta->'PLATFORM'->>'name', split_part(request_meta->'PLATFORM'->>'version','.',1), count(*), count(distinct user_id)
from users_cognitoissuedtokens where user_platform like 'app%' group by 1,2,3 having count(*)>=150 order by 1,4 desc;
-- Android 10: 16,119; Android 16: 168; 12: 165; iOS 18: 31,147; 17: 489; 16: 267; Mac OS X 10: 155
```
**N28 monthly consumer / producer / refetch throughput since 2025-09**
```sql
-- consumer by month: completed, in_progress, per service_name; producer: legacy_sync vs blacklist events; refetch: count and not-completed
-- ecom_gift/order 0 in Oct 2025–Jan 2026; stuck 5–10 per month Feb–Sep 2026; producer legacy_sync Aug 2026 1,417; refetch 0 failures
```
**N29 consumer monthly volume before 2026 and gap edges**
```sql
select service_name, to_char(max(start_timestamp) filter (where start_timestamp<'2025-10-01'),'YYYY "m" MM "d" DD'), to_char(min(start_timestamp) filter (where start_timestamp>='2025-09-01'),'YYYY "m" MM "d" DD') from kafka_clients_blacklistuserconsumerdatalog group by 1;
-- ecom_gift 2025-05-12 → 2026-02-12; ecom_order 2025-05-12 → 2026-02-22; ecomgroupgift 2025-05-12 → never; legacy 2025-08-19 → 2025-10-09; atwork first 2026-03-10
```
**N30 blacklist rows by source per month, Mar 2025 – Mar 2026**
```sql
select to_char(date_trunc('month',created_on),'YYYY "m" MM'), count(*) filter (where source='ecom_gifts'), count(*) filter (where source='ecom_orders'), count(*) filter (where source='ecom_groupgift'), count(*) filter (where source='ecom_legacy'), count(*) filter (where source='ecom_users')
from core_blacklisteduserdetail where created_on>='2025-03-01' and created_on<'2026-04-01' group by 1 order by 1;
-- ecom_gifts: 19, 41, 14, then 0 Jun 2025–Jan 2026, 13 Feb 2026, 58 Mar 2026
```
**N31 sign-up OTP outcome for blacklisted recipients**
```sql
with bd as (select lower(value) dom, min(created_on) bc from core_blacklisteduserdetail where type='user_domain' and not is_removed group by 1),
be as (select lower(value) e, min(created_on) bc from core_blacklisteduserdetail where type='user_email' and not is_removed group by 1),
o as (select lower(t.email) e, split_part(lower(t.email),'@',2) dom, min(t.created_on) st, bool_or(v.is_valid) ok, count(*) codes from notifications_twofactorauth t join notifications_twofactorauthverification v on v.reference_id_id=t.id where t.source='sign_up' and t.auth_type='email' and coalesce(t.email,'')<>'' group by 1,2),
u as (select distinct lower(email) e from users_user where email is not null)
select case when be.e is not null and be.bc < o.st then 'email_blacklisted_before' when bd.dom is not null and bd.bc < o.st then 'domain_blacklisted_before' when be.e is not null or bd.dom is not null then 'blacklisted_after_otp' else 'clean' end,
 count(*), round(avg(codes),2), round(100.0*count(*) filter (where ok)/count(*),1), round(100.0*count(u.e)/count(*),1)
from o left join bd on bd.dom=o.dom left join be on be.e=o.e left join u on u.e=o.e group by 1;
-- clean 16,919 / 1.35 / 88.2% / 78.8%; blacklisted_after_otp 69 / 2.51 / 98.6% / 11.6%; 0 rows blacklisted before
```
Figures reused from profiles (their SQL is in the source appendices): users B2, B5, C4, C6b, C8, C9 (users.md); X15, X15b, X27, X30, X32, X35, X40 (cross-db.md); Q17–Q28 (orders-integrations.md); A6b, A11, A14 (ecomweb-stores.md); Q20–Q31 (emapi-stores.md).
