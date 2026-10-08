# Theme: Risk, fraud & data integrity

Built 2026-09-29 (queries about 14:45–15:30 UTC) by the analytics strategist for ygg-atlas. Inputs were the seven critiqued profiles (`cross-db.md`, `users.md`, `orders-funnel.md`, `orders-customer-catalog.md`, `orders-integrations.md`, `ecomweb-stores.md`, `emapi-stores.md`) plus 29 new queries (R1–R29, appendix). Every query went through `atlasq.sh`: a READ ONLY transaction on the Aurora read replica, with PII-redacted output, returning aggregates only. Raw emails, phones, IPs, device ids and blacklist values were never selected. Where a PII column had to be matched, the join ran inside the database and only counts came back.

**Evidence labels.**
- **VALIDATED**: a data query was run. The source is an R-query below, or a profile appendix id (`C8`, `X30` and so on, from `users.md` / `cross-db.md`).
- **STRUCTURAL**: from the catalog or metadata only.
- **NEEDS-GRANT**: needs rows we cannot read. The exact table.columns are named.
- **[inferred]**: reasoning on top of a labelled fact.

**Access today.** `ygag_ecom_users_db`: all 40 tables are readable. `ygag_ecom_orders_db`, `ygag_ecomweb_stores_db` and `ygag_emapi_stores_db`: no data is readable. So every statement about payment fraud flags (`is_fraud`, `is_flagged`), the orders-side blacklist or order leakage is STRUCTURAL or NEEDS-GRANT.

---

## 0. Headline

1. **A live account-farming wave is running right now, and no current control has caught it** — VALIDATED (R26–R29).
   - Since **2026-09-26**, **83 accounts** have been created with residence `RU` and a `+7` phone. The baseline is about 0.3 such signups per day. The daily counts are 36, 17, 3 and 27 (Sep 29, still ongoing).
   - Every one of them logged in on **WEB**, and 81 did so from a **German** IP country.
   - Across all 83 there are only 5 browser builds and 2 OS types. 34 of the 36 Sep-26 accounts have 3 or more digits in the email local part, and the 26 Sep-29 accounts share a single non-freemail domain.
   - **None of them is blacklisted.** The `RU` sms-country-code block was **removed on 2025-10-16**.
   - atlas can find this with a metric we can ship today.
2. **The blacklist is a signup gate, not an account kill switch** — VALIDATED.
   - At signup it works:
     - 0 of the 59 addresses that the "dynamic email filter" blocked during signup in the last 31 days became accounts (R3).
     - 0 of the 2026 signups on a blacklisted domain joined after that domain was blacklisted (R8).
     - Countries that are only blacklisted for SMS received about 0 OTPs (R20).
   - After signup, blacklisting an existing account does not stop it logging in:
     - 903 live accounts carry an active email or mobile blacklist entry.
     - 12 of them received 18 new login tokens after being blacklisted (C8).
     - 8 accounts blocked by the **max-login-attempts** rule logged in again afterwards (R4).
3. **The two largest blacklist "spikes" were misread** — VALIDATED (R15–R17).
   - Aug 25 (797 rows) was not a spreadsheet upload. It was the automated *dynamic email filter* firing on a bot signup wave:
     - 797 freemail addresses on only 3 domains;
     - 70% have 3 or more digits in the local part, against 50% on other days;
     - all flagged `is_guest`, and only 1 matches an existing account.
   - The Jun 23–24 spike (381 rows) is the *dynamic domain filter*, spread over 317 distinct minutes.
   - Neither spike was analyst work. Neither means fraud grew.
4. **Several fields that look usable would corrupt metrics** — VALIDATED:
   - soft-delete replaces the email and phone with ciphertext, so no deleted account can ever match a blacklist value (R9–R11);
   - `modified_on` is not a deletion time (R23);
   - `email_verified` and `phone_number_verified` are constant;
   - `type`, `platform` and the social-id columns are dead (profile);
   - the whitelist silently overrides the blacklist for 13 countries (R18, R20).

---

## 1. Insights

### 1.1 A live RU/+7 web account farm, Sep 26–29 — VALIDATED

| Date (UTC) | Accounts (res RU, phone +7) | Email domains | Freemail | Local part with ≥3 digits | Distinct signup minutes | sign_up OTPs to +7 |
|---|---|---|---|---|---|---|
| Sep 1–25 (baseline) | 0–2 per day (11 in total) | — | — | — | — | 1–5 per day |
| **Sep 26** | **36** | 2 | 36 | **34** | 36 | **59** |
| **Sep 27** | 17 | 1 | 17 | 3 | 17 | 32 |
| Sep 28 | 3 | 1 | 2 | 0 | 2 | 6 |
| **Sep 29** (partial day) | **27** | **1 (non-freemail)** | 0 | 0 | 26 | **58** |

Sources: R27 and R28. Counts per day differ slightly between R27 (token-joined cohort) and R28 (all signups).

R29 checked the 83 accounts from Sep 26 onward:
- 83 of 83 have a WEB token, and 81 logged in from Germany;
- there are **5 distinct browser builds and 2 OS types** across all 83;
- 0 are blacklisted (email, mobile or domain);
- 0 have been deleted.

The residence/login pair `RU → Germany` has 82 tokens, 82 users and only 5 active days. All 82 are signup-day logins, all are web, the busiest day has 36, and **0 of these users ever logged in from Russia** (R26). Compare the travel-like pairs: `AE → India` has 57 of 197 users who also log in from home, over 61 days.

The pattern is one account per minute, one domain per day, on web, from datacenter or VPN egress. That fits scripted account creation [inferred]. The motive (promo, referral or card testing) needs orders data (H1).

**Why it got through.** The `RU` entry in `core_blacklisteduserdetail` (type `sms_country_code`) is `is_removed=true`, last modified 2025-10-16. The whitelist entry for RU was also removed, on 2025-11-27 (R28). Because RU is not blocked, SMS/WhatsApp OTPs flow freely to +7 numbers: 177 OTPs in 31 days, all delivered through SMS (R20).

### 1.2 The blacklist gates signup but does not revoke existing accounts — VALIDATED

At signup the gate works:

| Path | Evidence | Result |
|---|---|---|
| Email blocked by the **dynamic email filter** during signup | 59 recipients in the 31-day OTP window. For 55 of them the blacklist row was created *between* their first and last OTP; for 4 it was created later (R3). | **0 registered.** 152 codes were sent, 2.6 per recipient against 1.35 for clean recipients (R2). |
| Email domain on an active `user_domain` entry | 2026 signups on blacklisted domains: 487 users, **all joined before** the domain was blacklisted; 0 joined after (R8) | Domain gate is effective going forward |
| SMS country code, blacklist only | UA, LK, DZ, GH, ID, KE, BD, MX, NG, NP, SD, SY, VN: 1 OTP in 31 days in total (R20) | Geo gate is effective |

After signup it does not revoke:

| Population | Live accounts | Logged in after blacklist | Source |
|---|---|---|---|
| Active `user_email` / `user_mobile_no` entries matching a live account | **903** distinct users (752 matched on email, 553 on mobile) | **12 users, 18 tokens** (17 app, 1 WEB; 3 in Sep 2026) | C8 |
| of which the **max-login-attempts** rule (a lockout) | 267 mobile-row matches + 128 email-row matches | 5 + 3 users, 9 + 5 tokens after the entry | R4 |
| Active `user_device_id` entries | 166 rows | 10 tokens on a blacklisted device (9 users); **2 issued after** the device was blacklisted | R13 |
| Registered users named in an unapplied orders→users blacklist request (population B) | 389 users (still arriving, last 2026-09-28) | not applied at all | X30, X32 |

Reading [inferred]:
- The users service checks the blacklist when an identity is *created*. It does not disable accounts that already exist, and it does not block token issuance.
- A "maximum login attempts" entry is never lifted (`is_removed=false`), yet the account keeps logging in. So either the lockout is enforced somewhere else (Cognito), or the entry has no effect.
- Enforcement on existing accounts must therefore happen downstream, for example in orders `users_blacklisteduserdetail` (48,646 est rows [STRUCTURAL]). Whether it does is NEEDS-GRANT (H2).

### 1.3 Blacklist volume is mostly rules, and the spikes are attacks caught by rules, not imports — VALIDATED

Monthly adds by producer class (R15):

| Month | usercheck.com API | dynamic email filter | dynamic domain filter | max login attempts | other ecom_users (mostly analysts) | other services | Total | Largest single day |
|---|---|---|---|---|---|---|---|---|
| 2025-07 | 126 | 26 | 0 | 146 | 332 | 11 | 641 | 131 |
| 2025-11 | 83 | 4 | 0 | 2 | 163 | 31 | 283 | 166 |
| 2026-04 | 109 | 95 | 2 | 57 | 41 | 82 | 386 | 83 |
| 2026-05 | 99 | 92 | 1 | 81 | 22 | 111 | 406 | 64 |
| **2026-06** | 90 | 63 | **415** | 42 | 105 | 130 | 845 | 296 |
| **2026-08** | 113 | **1,088** | 2 | 117 | 42 | 83 | 1,445 | **801** |
| 2026-09 (to 29th) | 113 | 134 | 0 | 15 | 0 | 69 | 331 | 41 |

- **The usercheck.com disposable-email rule is steady at about 70–140 per month.** That is a stable baseline for a "disposable signup attempts" metric.
- **2026-08-25**: 797 rows (R16, R17):
  - all created by the single integration account, with the dynamic-email-filter remark;
  - spread over 38 minutes between 16:35 and 23:06 UTC;
  - all `is_guest`, all freemail, only 3 domains, 0 plus-addressing;
  - average local-part length 15.8 characters, against 13.0 on other days;
  - 70% of local parts have 3 or more digits, against 50% on other days;
  - 786 distinct local stems;
  - only **1** matches an existing account.

  This is the signature of a generated address list hitting signup and being auto-blocked [inferred]. `users.md` §7 called it "a spreadsheet upload". This theme revises that reading: the creator is the rule engine, not a person (X26, X27).
- **2026-06-23/24**: 381 `user_domain` rows from the dynamic domain filter, over 67 + 250 distinct minutes. This is again rule output, not a single bulk paste.
- **Analyst-entered adds** ("other ecom_users") are lumpy: 332 in Jul 2025 and 163 in Nov 2025. On 2025-11-17 there were 99 emails from one domain in 5 minutes, and 60 IPs in 7 minutes (R16). These are the genuine bulk imports.
- **Service-originated adds** (gifts, orders, legacy, groupgift, atwork) rose from 0–43 per month in 2025 to 65–130 per month in 2026. That is the only series that measures fraud *detected downstream*.

The OTP window starts Aug 29, so Aug 25 cannot be checked against OTP volume (users.md §10). This is exactly why daily snapshots are needed (§6).

### 1.4 Risk fingerprints that separate risky accounts from the base — VALIDATED (lift against blacklist status)

Base rate: 903 blacklisted live accounts out of 974,221 live accounts, or **0.093%**.

| Fingerprint (all derivable in the users DB) | Population | Blacklisted | Rate | Lift vs base | Source |
|---|---|---|---|---|---|
| App device shared by 2 or more accounts | 247 users (119 devices) | 5 | 2.0% | **about 22x** | R13 |
| SA/AE resident with any token from outside the GCC | 2,386 users | 8 | 0.34% | **about 13x** vs the 0.026% of home-only SA/AE users | R14 |
| SA/AE resident, home-country logins only | 46,725 | 12 | 0.026% | reference | R14 |

- Out-of-GCC SA/AE users are also more often on web (24.7% against 16.5%) and more often have a phone that does not match their residence (0.7% against 0.1%) (R14).
- Blacklisting is itself a biased label, because it is mostly rules applied at signup. These lifts show the features carry signal. They do not prove fraud (H3, H4).

### 1.5 Signup bursts are mostly campaigns, and the tell-tale of a farm is a narrow fingerprint, not volume — VALIDATED

- Since 2026-06-01 the hourly signup median is **29** and the p99 is **84**, over 2,893 hours (R5). The top hours are 2026-09-22 12–16 UTC (199, 163, 153, 141, 127), then Aug 20 14h (142) and Jun 24 06h (95).
- Burst-hour cohorts (hours at or above p99) compared with normal hours, for signups from 2026-07-13 to 09-27 (R6):

  | Measure | Burst hours | Normal hours |
  |---|---|---|
  | Users | 2,330 | 49,982 |
  | Deleted | 1.55% | 1.28% |
  | App | 87.8% | 82.1% |
  | Freemail | 70.0% | 78.0% |
  | SA residents | **73.1%** | 50.6% |
  | Phone/residence mismatch | 1.3% | 1.0% |

  The burst cohort is **an SA acquisition push, not a farm**. Deletion and mismatch rates are essentially baseline. Its lower return rate (1.9% against 3.5%) is confounded by the shorter observation window.
- A farm is **low-volume and narrow**. The RU wave peaked at 36 per day and never shows up as a burst hour. Across all 2026 signups, same-minute clusters on the same non-freemail domain are rare: 992 pairs, 85 clusters of 3–4, 4 clusters of 5–9, and none of 10 or more (R7). **An alert keyed on signup volume would have missed §1.1. An alert keyed on a (residence, login country, platform, phone prefix) cluster catches it.**

### 1.6 SMS geo-policy: whitelist overrides the blacklist, the RU gap, and US numbers that never verify — VALIDATED

- `sms_country_code` values are **ISO-2 country codes in mixed case**: 101 active blacklist rows, 13 of them lowercase, for example `ag`, `bb`, `gd` (R19).
- **15 active whitelist∩blacklist conflicts**, 13 of them on `sms_country_code`, for example DE, ES, BR, CN, JO, IQ, IL, ZA, TN (R18). Countries on both lists do receive OTPs (JO 53, IQ 38, IL 37, DE 28, ZA 25, BR 21, ES 18 in 31 days), so **the whitelist wins** (R20).
- **Removed blocks** for high-risk origins: RU (removed 2025-10-16), EG, PK, PH, MA, LB, OM, KW, GB (R19, R20). EG receives the most non-GCC OTPs (342 in 31 days, 292 signups since Aug 29).
- **US/CA (+1) numbers**: 267 numbers requested sign_up OTPs, and only **133 (49.8%)** became accounts. The rate is 96.5% for SA and AE, and 79.8% for GB (R1). The unverified numbers are spread over all 31 days (at most 9 per day) and 101 area codes (R22). Only 5 +1 numbers are Caribbean or Pacific (R21).

  This is **not** an SMS-pumping burst. It is most likely A2P SMS delivery failure to US carriers [inferred]: all of these codes go out over `whatsappsms`, and resend chains are 1.22 codes long.

  The consequence is friction, not fraud. It still belongs on the risk dashboard, because it is what separates "OTP cost with no signup" (pumping) from "OTP undelivered" (carrier).

### 1.7 Soft deletion pseudonymises identity, so blacklist matching and re-signup detection are blind to deleted accounts — VALIDATED

**What deletion does to the row.** On every soft-deleted account except one (22,107 of 22,108), `email` is replaced by a base64 string of 52–144 characters (R9, R10). It decodes to 19–98 **binary** bytes: NUL bytes appear in 3,268 rows, and '@' appears in only 14%, which is what random bytes would give (R11). `phone_number` is scrubbed as well (for example, 2,828 of 2,875 deleted 2026 accounts have no `+` prefix). Soft delete therefore **encrypts** the identifiers. It does not erase them. The lengths track the original email length [inferred: a length-preserving cipher, so reversible by whoever holds the key].

**Consequences:**
1. `core_blacklisteduserdetail` values can never match a deleted account. The "0 soft-deleted" in the blacklist overlap (B12) is an artefact of the scrub, not a finding.
2. After deletion the unique constraint no longer holds the address, so **a deleted email can register again** [inferred]. Deletion followed by re-signup (promo re-use) is invisible to value matching. The only readable link is the device: 5 deleted users have app device signatures, and 2 of them share a device with a live account (R12).
3. **For governance, the ciphertext is still PII.** The plugin must exclude it and must not treat it as a hash key.

**`modified_on` is not a deletion timestamp.** 5,254 of the 22,108 deleted accounts have `modified_on` less than 10 minutes after `date_joined` (R23), and 84% of *live* accounts also sit in that bucket. For accounts joined since 2025-06, 61% of deletions show `modified_on` within one day of joining. Either many accounts are deleted within hours of signup, or deletion does not always touch `modified_on`. The two cannot be told apart without a `deleted_at` column. `users.md` §5 ("soft deletions that month (modified_on)") should be read as an upper-bound proxy only.

### 1.8 Kafka fraud propagation fails silently for 1,298 requests, 396 of them for registered users — VALIDATED (from X30 and X32)

- 1,298 `ecom_order` blacklist requests are stuck `in_progress` with an empty `error_data`.
- 902 of them are true-guest events that stopped arriving on 2025-05-12.
- **396 are registered users (389 distinct)** whose username was placed in `guest_id`. These are still arriving: 58 in 2026, the last on 2026-09-28.
- None of the 1,298 carries `mark_as_fraud`, while all 2,895 completed events do.

These 389 users were reported by orders, never blacklisted in identity, and have no other entry for 367 of them (22 are listed another way, X32). This is the largest known enforcement leak, it is fixable by a payload contract change, and it is measurable today.

### 1.9 Payment-side fraud flags exist but are unreadable — STRUCTURAL

| Table (orders DB) | Relevant columns | Rows [est] | Notes |
|---|---|---|---|
| `youpayclient_youpayclienttransactiondata` | `is_fraud`, `is_flagged`, `approved`, `response_summary`, `card_issuer_country`, `is_gcc_card`, `platform`, `payment_gateway`, `payment_method` | 1,229,851 | One row per payment attempt (cardinality not verified). `card_issuer_country` is indexed. |
| `payment_paymentdetail` | `is_fraud`, `is_flagged`, `card_issuer_country`, `is_gcc_card`, `payment_status` | 761,949 | 0..1 per order (about 62% of orders) |
| `users_blacklisteduserdetail` | `type`, `source`, `is_removed`, `is_guest`, `created_on` (`value` is PII) | 48,646 | About 5.6x the identity master. At 157 MB of heap for 48.6k rows, it is heavily churned (X31). |
| `kafka_blacklistusergiftlog` / `kafka_blacklistuserkafkadatalog` / `kafka_legacyfraudsynclog` | `event_id`, `status`, `error` | 7,354 / 2,317 / 16,691 | The consumers of the users producer stream |
| emapi `users_user` | `is_fraud`, `trusted_user`, `is_deleted` | 992,399 | A per-account fraud flag that exists only in the app-store mirror |
| `core_unsupportedcountry`, `core_currencybasketlimit` | country block, basket caps | small | Checkout-side geo and amount controls |

YouPay card fields that would enable card-testing detection (`card_bin`, `card_last4`, `name_on_card`) are excluded by design. Derived flags (BIN country, a same-card-many-accounts count) must be computed in a view (§5).

### 1.10 Control configuration is readable and maps one-to-one to blacklist remark classes — VALIDATED

`core_siteconfiguration` (R24; keys and booleans only):
- `disposable_email_manager_enabled` = true, and `disposable_usercheck_enabled` = true. These produce the usercheck.com rule rows.
- `dynamic_throttle_config` holds `enabled_countries`, `ip_manager_config`, `email_manager_config`, `domain_manager_config` and `authentication_manager_config`, among others. These produce the dynamic email, dynamic domain and max-login rows.
- A voice-alert OTP fallback is enabled (`otp.limit` 22, `max.retries` 5).

**3 `automation_accounts`** (QA) hold 13 tokens (R25). They are small, but they must be excluded from login and risk metrics. Captcha scores are **not** logged anywhere readable. Only the config exists (users `core_captchaconfigurations`, threshold 0.5), plus 2.5M replica reads of ecomweb's captcha config [STRUCTURAL].

---

## 2. Hypotheses (testable, for ops/risk, growth and marketing)

| # | Hypothesis | Audience | Test (metric + comparison) | Data | Evidence |
|---|---|---|---|---|---|
| H1 | The Sep 26–29 RU/+7 web cohort (83 accounts) will place orders, redeem Plus offers or claim promo codes at **5x or more** the rate of same-week web signups, or will attempt payments with a high decline or `is_flagged` rate. That would make it promo or card-testing abuse, not dormant farming. | ops/risk, growth | Orders or offer redemptions per account within 7 days, and the youpay decline and `is_flagged` rate: cohort against a same-week WEB-signup control. If no orders, check `users_useravailedoffer` claims. | orders `order_order(user_id, date_placed, status)` via `users_userprofile.md5(cognito_id)`; youpay `(approved, is_fraud, is_flagged, card_issuer_country, created_on, md5(order_reference))`; emapi `users_useravailedoffer(user_id, created_on)` | NEEDS-GRANT (cohort itself VALIDATED, §1.1) |
| H2 | Of the 903 live blacklisted accounts, **at least 5%** placed an order after their blacklist date. That would show downstream checkout enforcement also leaks. | ops/risk | Share of the 903 with `date_placed > first_blacklist_created_on`. Split by source class (rule, analyst, service). | orders `order_order(user_id, date_placed)`, `users_userprofile(user_id, md5(cognito_id))`; orders `users_blacklisteduserdetail(type, md5(lower(value)), is_removed, created_on)` | NEEDS-GRANT |
| H3 | Accounts on a **shared app device** (2 or more accounts) have a payment `is_fraud`/`is_flagged` rate **at least 10x** that of single-device accounts. (Their blacklist lift is already 22x, §1.4.) | ops/risk | Flag rate per account, shared against single device; Fisher exact test. | users tokens (ready); youpay flags per user (grant) | NEEDS-GRANT (feature VALIDATED) |
| H4 | SA/AE residents whose **signup-day token comes from outside the GCC** have a higher first-order decline rate and chargeback or `is_fraud` rate than home-country signups. Travel mismatches that happen later do not. | ops/risk | Decline and fraud rate by segment {signup-day out-of-GCC, later out-of-GCC, home only}. | users tokens (ready); youpay (grant) | NEEDS-GRANT (segments VALIDATED: 725 AE and 690 SA signup-day out-of-GCC tokens, C6) |
| H5 | The 389 population-B users (orders reported them, identity never applied it) keep buying. The payload fix would stop a measurable volume of orders per month. | ops/risk, engineering | Orders by these users after their first stuck event, against the 18 of them that were blacklisted another way. | orders `order_order` by hashed username; users consumer log (ready) | NEEDS-GRANT |
| H6 | US/CA (+1) signups fail for **delivery** reasons, not pumping. Routing +1 to email or WhatsApp-only OTP would lift verification from 49.8% to at least 85%. | product, growth | A/B on the OTP channel for +1 numbers. Metric: the share of numbers with an accepted code, and signups per OTP. | users OTP tables (ready) + SMS engine delivery receipts (`ygag_smsengine_db`) | VALIDATED gap; experiment needed |
| H7 | Accounts deleted within 24 h of signup are disproportionately **re-created** (same device, or same payment card) and used for first-order promos. | ops/risk, growth | Among deleted accounts that have a device signature: the share whose device later appears on a new account, and the share of those new accounts with a promo order in the first 7 days, against a control. | users tokens (ready, n is small today: 5 deleted users with a device); orders `order_line(is_offer_applied, offer_code)` (grant); a proper `deleted_at` column (engineering) | STRUCTURAL + NEEDS-GRANT |
| H8 | **Max-login-attempts** entries signal credential stuffing. The 8 affected accounts that logged in afterwards (§1.2) have abnormal post-login behaviour: a new device, a new country, a phone change (`users_useridentityactivitylog updated_phone_number`) or a secondary-email change within 24 h. | ops/risk | Rate of identity changes within 24 h of the post-lockout token, against all accounts. | users (ready) | VALIDATED inputs; test runnable now (small n) |
| H9 | Moving the dynamic email filter **before** OTP dispatch saves about 1.6 OTPs per blocked attempt, about 95 per 31 days at the current rate. On bot days like Aug 25 (797 blocks) it would save about 1,300 OTPs a day. | product, finance | OTPs sent to recipients that were later blocked, per day, before and after the change. | users (ready); SMS cost per country (finance) | VALIDATED (R2, R3) |
| H10 | Re-enabling the RU sms-country-code block, or adding a (RU, web, DE-egress) rule, would have stopped **at least 90%** of the §1.1 cohort, at a cost of fewer than 1 legitimate RU signup per day (the baseline is 0.3 per day). | ops/risk | Replay the rule on the last 90 days of RU signups and count true and false positives. | users (ready) | VALIDATED inputs |
| H11 | The **whitelist-overrides-blacklist** conflicts (13 countries) are stale. Legitimate signup volume from those countries is at most 1 per day, so removing the conflicts barely affects growth. | ops/risk | Signups per day and completed-signup rate for the 13 conflict countries. | users (ready) | VALIDATED inputs |
| H12 | emapi `users_user.is_fraud` agrees with the users-DB blacklist on at least 95% of registered blacklisted usernames. If it does not, fraud status is split-brained and app-side offers can reach blocked users. | ops/risk | Agreement matrix on `md5(username)`. | emapi `users_user(md5(username), is_fraud, is_deleted)` | NEEDS-GRANT |
| H13 | **Marketing waste:** some share of each campaign's promo sends or redemptions goes to risk-segment accounts (farm cluster, shared device, blacklisted-live). Excluding them lowers cost per real acquisition by at least 2%. | marketing, growth | Cost per retained buyer with and without the exclusion segment, on campaign cohorts. | users (segment ready); campaign sends (MAIL/SMS engine) and orders (grant) | NEEDS-GRANT |

---

## 3. Atlas features

Readiness: **ready-now** means the users DB alone is enough; **needs-grant** means a blocked DB; **needs-new-source** means a DB not in scope (SMS engine, Cognito, youpay DB).

| id | Feature | Type | What it does | Backing (plugin → tables) | Readiness | Effort | Impact |
|---|---|---|---|---|---|---|---|
| RF1 | **Account-farm cluster alert** | alert_trigger | Each day, groups new signups by (residence, token login country, platform, phone-prefix country, email-domain class). It fires when a cluster has 15 or more accounts per day **and** more than 5x its 28-day baseline **and** no users who also log in from home. The alert carries cluster size, browser/OS diversity and blacklist coverage. It would have fired on 2026-09-26 (§1.1). | `ecom_users` → `users_user`, `users_cognitoissuedtokens` (COUNTRY, OS_TYPE, BROWSER, user_platform), `core_blacklisteduserdetail` | ready-now | M | 5 |
| RF2 | **Blacklist enforcement gap** | metric (snapshot) + record_drilldown | Live accounts with an active identity blacklist entry (903), accounts with tokens issued after the entry (12 / 18 tokens), and post-lockout logins, split by source class. The drill-down shows hashed user ids, source class, entry age and token count, never values. | `ecom_users` → `core_blacklisteduserdetail`, `users_user`, `users_cognitoissuedtokens` | ready-now | S | 5 |
| RF3 | **Blacklist volume by producer class** | metric (range) + breakdown | Adds and removals per day, split into rule class (usercheck, dynamic email, dynamic domain, max login), analyst, and service source. Net of un-blacklists (395) and legacy removals (350). A bulk flag marks 40 or more rows from one creator in one day. This stops "fraud wave" misreads (§1.3). | `ecom_users` → `core_blacklisteduserdetail` (via a remark-class view), `kafka_clients_blacklistuserproducerlog` | ready-now | S | 4 |
| RF4 | **Unapplied fraud requests** | metric (snapshot) + alert_trigger | Stuck `in_progress` consumer events (guest 902 / registered 396). Alerts on any new registered-population event. | `ecom_users` → `kafka_clients_blacklistuserconsumerdatalog` | ready-now | S | 4 |
| RF5 | **OTP geo-policy monitor** | breakdown + alert_trigger | OTPs, numbers, verification rate and registration rate by destination country, labelled blacklist-only / whitelist / both / unlisted. Alerts when an unlisted or removed-block country's daily OTPs exceed 5x baseline (RU on Sep 26: 59 against about 2). Also lists list conflicts and lowercase codes. | `ecom_users` → `notifications_twofactorauth(+verification)`, `core_blacklisteduserdetail`, `core_whitelisteduserdetail` | ready-now | M | 5 |
| RF6 | **Shared-device and delete/re-create clusters** | record_drilldown + segment | Devices shared by 2 or more accounts, with each account's blacklist status, deletion state and residence/login mismatch. Device ids are shown as keyed hashes only. | `ecom_users` → `users_cognitoissuedtokens(device_signature→HMAC)`, `users_user` | ready-now | M | 4 |
| RF7 | **Risk-exclusion segment for marketers** ("do not reward") | segment | The union of farm-cluster members (RF1), live blacklisted accounts, shared-device accounts and population-B users. It is exported as hashed usernames to the campaign tools, so promo budget does not go to farms. It pairs with RF10 once orders are granted. | `ecom_users` (ready); orders/campaign tools (later) | ready-now | S | 5 |
| RF8 | **Signup burst vs quality** | alert_trigger + breakdown | Hourly z-score alert on signups, *paired* with a cohort-quality card (deletion %, residence mix, freemail %, mismatch %, OTP resend %). Marketing sees a campaign; risk sees a farm. | `ecom_users` → `users_user`, tokens, OTP | ready-now | S | 3 |
| RF9 | **Fraud-agentic investigation** | agentic_analysis | Given an anomaly (an RF1/RF5 alert, or a question like "who is signing up from Germany with RU phones?"), the sandbox pulls the governed cohort extract, computes fingerprint diversity (browser/OS, domain entropy, digit-pattern share, signup-minute spacing), compares it with a matched control, checks list coverage, and drafts a proposed rule. Humans approve. Every number carries provenance. | `ecom_users` governed extracts (derived columns only) | ready-now | L | 5 |
| RF10 | **Payment fraud and flag rates** | metric (range) + breakdown | `is_fraud` / `is_flagged` / decline rate per attempt, by card-issuer country, GCC card, platform, gateway and payment method. Joined to identity risk segments (H3, H4). | `ecom_orders` → `youpayclient_youpayclienttransactiondata`, `payment_paymentdetail` | needs-grant | M | 5 |
| RF11 | **Blacklisted-user order leakage** | metric + record_drilldown | Orders placed after the blacklist date, by blacklist source class (H2, H5). | `ecom_users` + `ecom_orders` (`order_order`, `users_userprofile` hashed) | needs-grant | L | 5 |
| RF12 | **Two-blacklist reconciliation** | metric (snapshot) | users `core_blacklisteduserdetail` (8,760) against orders `users_blacklisteduserdetail` (48.6k est) on `md5(lower(value))` per type: users-only, orders-only, both, and `is_removed` disagreement (V10). Also emapi `is_fraud` agreement (H12). | `ecom_users` + `ecom_orders` + `emapi_stores` | needs-grant | M | 4 |
| RF13 | **Data-integrity monitor** | dashboard | Tracks the traps that would make metrics wrong: dead-field fill rates (`type`, `platform`, social ids, `whatsapp_delivery`, `email_verified`), the id-gap regime, OTP/token retention windows (earliest row date), snapshot drift, the 1,298 stuck-event count, soft-delete scrub consistency, and automation-account activity. Each metric definition declares which traps it depends on. | `ecom_users` (all), catalog stats for the others | ready-now | M | 4 |
| RF14 | **Risk & integrity dashboard** (ops) | dashboard | RF1–RF6 plus RF13 on one page, with provenance chips. Later adds RF10–RF12. | `ecom_users` → `ecom_orders` | ready-now (phase 1) | M | 4 |
| RF15 | **Soft-deletion metric (honest)** | metric (snapshot) | Deleted accounts by join cohort (22,108 in total). No "deletions per month" until a `deleted_at` column exists. The provenance says so. | `ecom_users` → `users_user` | ready-now | S | 2 |
| RF16 | **OTP risk funnel** (request → accepted → registered) | funnel | A per-country funnel that separates *pumping* (many numbers, few accepted, no registrations) from *delivery failure* (few accepted, normal chain length, spread over time) and from *filter blocks* (accepted, then blocked). US/CA gives 49.8% registered, against 96.5% for SA and AE. | `ecom_users` → OTP tables + `users_user` (in-DB join) | ready-now | M | 4 |

---

## 4. Plugin notes

### 4.1 `ecom_users` plugin: risk slice (readable now)

**Entities.**
- `account`: `users_user`, keyed by `username`. The internal id is used only for local joins.
- `login_token`: `users_cognitoissuedtokens`.
- `otp_request`: `notifications_twofactorauth` + `…verification`.
- `list_entry`: the blacklist and the whitelist.
- `fraud_event_in`: the consumer log.
- `fraud_event_out`: the producer log.
- `identity_change`: `users_useridentityactivitylog`.
- `control_config`: site config flags, captcha config.

**Allowlisted tables:**
- `users_user`
- `users_cognitoissuedtokens`
- `notifications_twofactorauth`, `notifications_twofactorauthverification`
- `core_blacklisteduserdetail`, `core_whitelisteduserdetail`, `users_promotionaldomainblacklist`
- `kafka_clients_blacklistuserconsumerdatalog`, `kafka_clients_blacklistuserproducerlog`
- `users_useridentityactivitylog`, `users_migratedtransactionlog`
- `django_admin_log` (action_flag, content type and time only)
- `core_siteconfiguration`, through a flags-only view

**Derived views** (the connector reads only these; raw PII never leaves the DB):

| View | Exposes | Replaces (excluded) |
|---|---|---|
| `atlas_ro.account_risk` | `username`, `date_joined`, `is_deleted`, `trusted_user`, `country_of_residence`, `is_app_user`, `phone_country` (ISO-2 derived from prefix), `email_domain_class` (freemail / apple_relay / edu_gov / corporate / blacklisted_domain), `email_local_digit_class` (0 / 1–2 / ≥3), `legacy_state`, `is_automation_account` | email, phone_number, name, birthdate (full), ip_address, social ids, password, and the **encrypted email/phone on deleted rows** |
| `atlas_ro.login_token` | `user_id`, `created_on`, `expires_at`, `user_platform`, `login_country`, `os_type`, `browser_family`, `is_bot`, `device_key` = HMAC(device_signature, rotating key) | jti, token_hash, device_signature, request_meta IP_ADDRESS / USER_AGENT / TOKEN_DERIVATIVES |
| `atlas_ro.otp_request` | `created_on`, `source`, `auth_type`, delivery flags, `dest_country` (from phone prefix), `recipient_key` = HMAC(lower(email) or phone), `is_valid`, `registered_now` (bool, computed in-DB) | email, phone_number, auth_code |
| `atlas_ro.list_entry` | `list` (black/white), `type`, `source`, `producer_class` (rule_usercheck / rule_dyn_email / rule_dyn_domain / rule_max_login / analyst / service), `is_removed`, `is_guest`, `created_on`, `modified_on`, `value_key` = HMAC(lower(trim(value))), `matches_live_account` (bool), `country_code` (for type sms_country_code only; not PII) | value, remarks (free text), reference_id (except a `ref_is_username` bool) |
| `atlas_ro.fraud_event_in` / `_out` | service, event_type, status, start/completed timestamps, payload key-set class, `mark_as_fraud`, `is_removed`, `population` (guest / registered / completed) | data / payload (contain emails and phones) |
| `atlas_ro.control_flags` | the booleans and numbers from §1.10 | automation account emails, secrets in `core_remoteurlconfig` |

**Rules the plugin must enforce:**
- **Minimum cell size of 10** on every breakdown and drill-down that is keyed by country, domain class or device cluster. The RU cohort (83) passes. A 2-account shared device is shown only as part of a count.
- HMAC keys must be identical across the users, orders, ecomweb and emapi plugins, so hashed joins work (§5). Use HMAC rather than a bare `md5`, because email and phone spaces are small enough to brute-force.
- Snapshot jobs: OTP tables (31-day retention) and WEB tokens (30-day life, purged) need a **daily aggregate snapshot** into atlas's own store, or trend metrics beyond 30 days are impossible.

### 4.2 `ecom_orders` plugin: risk slice (blocked)

- **Entities:** `payment_attempt` (youpay), `payment` (paymentdetail), `checkout_block_entry` (orders blacklist), `fraud_sync_event` (the three Kafka logs), and `guest_identity` (users_guestuser + mergeduser).
- **Views:**
  - youpay: flags, amounts, card_issuer_country, is_gcc_card, platform, gateway, method, `md5(order_reference)`, plus derived `card_key` = HMAC(card_bin‖last4) that is **only aggregated** (accounts per card, cards per account) and never exported per row;
  - `response_summary` normalised to an error class;
  - the blacklist with `value_key` (HMAC).
- **Exclude:** customer_email, customer_name, customer_ip_address, name_on_card, card_bin, card_last4, session_id, and the payload/error free text.

### 4.3 `emapi_stores` / `ecomweb_stores` plugins: risk slice (blocked)

- `users_user.is_fraud`, `trusted_user` and `is_deleted`, keyed by HMAC(username).
- emapi `users_useravailedoffer` for promo abuse (H1, H13).
- ecomweb `core_captchaconfigurations` is config only. No captcha outcomes exist in these DBs, so an outcome log is a new source.

---

## 5. Grants needed (theme subset, PII-safe)

| # | DB.table | Columns (as a view) | PII-safe alternative | Unblocks |
|---|---|---|---|---|
| RG1 | orders `youpayclient_youpayclienttransactiondata` | `created_on`, `approved`, `payment_status`, `is_fraud`, `is_flagged`, `is_gcc_card`, `card_issuer_country`, `platform`, `payment_gateway`, `payment_method`, `payment_scheme`, `currency`, `amount`, `md5(order_reference)`, `err_class(response_summary)` | No card or customer fields. Card reuse is exposed only as aggregates: `accounts_per_card_bucket` (1 / 2–3 / 4+) computed in-DB from HMAC(card_bin‖card_last4) | RF10, H1, H3, H4 |
| RG2 | orders `payment_paymentdetail` | `order_id`, `created_on`, `is_fraud`, `is_flagged`, `payment_status`, `is_gcc_card`, `card_issuer_country` | Excludes card_bin, card_last4, name_on_card, brand_calculations | RF10 |
| RG3 | orders `order_order` + `users_userprofile` | `order_order(id, user_id, guest_id, date_placed, status, platform, currency, total_incl_tax)`; `users_userprofile(user_id, HMAC(cognito_id), trusted_user, is_deleted)` | Excludes user_email, guest_email, user_phone, session_id | RF11, H1, H2, H5 |
| RG4 | orders `users_blacklisteduserdetail` | `type`, `source`, `is_removed`, `is_guest`, `created_on`, `modified_on`, `HMAC(lower(trim(value)))`, `ref_is_uuid` | Never `value` | RF12, H2 |
| RG5 | orders `kafka_blacklistusergiftlog`, `kafka_blacklistuserkafkadatalog`, `kafka_legacyfraudsynclog` | `event_id`, `status`, `created_on`, `modified_on`, `has_error`, `err_class` | No payload | RF12, fraud propagation SLA |
| RG6 | orders `core_unsupportedcountry`, `core_currencybasketlimit` | all (config) | none needed | geo and amount controls on the risk dashboard |
| RG7 | emapi `users_user` | `HMAC(username)`, `is_fraud`, `trusted_user`, `is_deleted`, `date_joined` | — | H12, RF12 |
| RG8 | emapi `users_useravailedoffer` | `user_id`→HMAC(username), `offer_id`, `created_on` | — | H1, H13 |
| RG9 | ecomweb `users_cognitouser` | `HMAC(username)`, `is_deleted`, `trusted_user` | — | RF12 |
| RG10 | new source: `ygag_smsengine_db` / `ygag_mailengine_aps_db` | delivery receipts: `created_on`, channel, `dest_country`, status, cost (if present), `HMAC(recipient)` | — | H6, RF16 pumping vs delivery |
| RG11 | engineering, users DB | add `deleted_at` (and `deleted_by`) to `users_user`, and keep an HMAC of the pre-deletion email and phone for abuse matching | a column change, not a grant | H7, RF15 |

**Minimum viable grant for this theme:** RG1, RG3 and RG4 (hashed). Together they answer "do blacklisted or farmed accounts buy, and are their payments flagged?"

---

## 6. Risks: data-quality traps that would make risk metrics wrong

1. **Blacklist rows are not fraud cases.** 83% of `ecom_users` rows are rule output (X27b), and the Aug 25 and Jun 24 spikes are rule firings on attack waves (§1.3). Count "fraud detected" only from service-sourced rows, or split by producer class. Net out un-blacklists (395) and legacy removals (350).
2. **`is_guest` is not a guest flag** (X13), and `guest_id` can hold a registered username (population B). Test "registered" as `reference_id` = `users_user.username`.
3. **Deleted accounts are invisible to value matching**, because their email and phone are encrypted (§1.7). Every "blacklisted accounts that are deleted = 0" style number is an artefact. The ciphertext is still PII: exclude it.
4. **`modified_on` is not a deletion date** (§1.7). Monthly deletion trends from it are unreliable.
5. **Case sensitivity.** `UNIQUE(type, value)` is case-sensitive: `user_email` has 3,775 rows but only 3,773 lower-trim hashes (X40), and `sms_country_code` mixes cases (R19). Always normalise with `lower(trim())` before matching or counting.
6. **The whitelist overrides the blacklist** for 13 countries (R18, R20). "Blocked countries" must be computed as blacklist minus whitelist.
7. **Retention windows.** OTP tables hold about 31 days. WEB tokens exist only from 2026-08-29, and app tokens from 2026-07-13. Anything earlier, such as the Aug 25 wave, cannot be reconstructed. Snapshot daily, and stamp the coverage start on every provenance chip.
8. **The id-sequence cutover in May 2025.** Signup counts and "accounts created per day" before and after it are not comparable (users.md §5). This matters for burst baselines.
9. **Dead or constant fields.** Signup-method risk features cannot be built from users-DB fields today:
   - `type` has been dead since Oct 2023;
   - `platform` has been `other` since 2024;
   - the social ids have been dead since Dec 2024;
   - `email_verified` and `phone_number_verified` are always true (996,155 / 996,156);
   - `whatsapp_delivery` is never true;
   - `last_login` is a frozen legacy timestamp;
   - `users_user.ip_address`, `device` and `app_version` are empty for current users.
10. **`is_valid` is not a wrong-code counter** (users.md §7). OTP brute-force attempts are not observable here. Only resends are.
11. **Producer `status=completed` means published, not delivered** (cross-db §3.2). Do not build a propagation SLA on it. Use the consumer logs on the orders side (RG5).
12. **Two blacklists and three fraud flags** (users list, orders list, `is_fraud` in emapi / paymentdetail / youpay) are not replicas. A single "fraud status" metric must name its source until RF12 shows they agree.
13. **Automation and staff accounts:** 3 QA automation accounts (13 tokens) and 42 `is_staff`. Exclude them from login, risk and fraud denominators.
14. **Live-replica drift.** Counts move by up to about 0.1% within an hour (users.md S1). Risk snapshot metrics must carry an as-of timestamp.
15. **Label bias.** Blacklist status is mostly set at signup by rules, so the lifts in §1.4 partly measure rule coverage, not fraud. Validate the fingerprints against payment outcomes (RF10) before any automated blocking.
16. **Small cells and re-identification.** Farm clusters, shared devices and rare countries produce tiny cells. Enforce the minimum cell size of 10 (§4.1). Corporate email domains identify employers, so expose only the domain *class*.

---

## Appendix: SQL provenance (queries run for this theme, 2026-09-29, `ygag_ecom_users_db`)

Date output uses `to_char(ts,'YYYY "m" MM "d" DD')`, because atlasq redacts ISO dates. All outputs are aggregates.

**R1: sign_up phone OTPs by destination prefix against registration**
```sql
with p as (select t.phone_number ph, case when t.phone_number like '+966%' then 'SA' when t.phone_number like '+971%' then 'AE' /* … QA KW BH OM IN EG GB US/CA PK PH ID NG … */ else 'other' end cc, v.is_valid
 from notifications_twofactorauth t join notifications_twofactorauthverification v on v.reference_id_id=t.id where t.source='sign_up' and coalesce(t.phone_number,'')<>''),
n as (select cc, ph, count(*) codes, bool_or(is_valid) anyv from p group by 1,2)
select n.cc, count(*) numbers, sum(codes), count(*) filter (where anyv), count(u.id) registered, count(*) filter (where codes>=5), round(avg(codes),2)
from n left join users_user u on u.phone_number=n.ph group by 1 order by 2 desc;
-- SA 14,128 / 13,633 reg; AE 8,545 / 8,244; US/CA 267 / 133 (any_valid 134); GB 352 / 281; other 661 / 520; PK 65 / 48; PH 24 / 18
```
**R2: sign_up email recipients by list class**
```sql
with bd as materialized (select lower(value) dom, bool_or(not is_removed) active from core_blacklisteduserdetail where type='user_domain' group by 1),
be as materialized (select lower(value) em from core_blacklisteduserdetail where type='user_email' and not is_removed),
e as (select lower(t.email) em, lower(split_part(t.email,'@',2)) dom, count(*) codes, bool_or(v.is_valid) anyv from notifications_twofactorauth t join notifications_twofactorauthverification v on v.reference_id_id=t.id where t.source='sign_up' and t.email like '%@%' group by 1,2)
select case when bd.dom is not null and bd.active then 'blacklisted_domain' when be.em is not null then 'blacklisted_email' else 'clean' end, count(*), sum(codes), count(*) filter (where anyv), count(u.id)
from e left join bd on bd.dom=e.dom left join be on be.em=e.em left join users_user u on lower(u.email)=e.em group by 1;
-- blacklisted_email 68 / 172 codes / 68 valid / 8 registered; clean 16,921 / 22,861 / 14,926 / 13,338; blacklisted_domain 1 / 1 / 0 / 0
```
**R3: blacklist entry timing against signup OTPs, by rule class**
```sql
with be as materialized (select lower(value) em, created_on bc, source, case when coalesce(remarks,'')='' then 'none' when remarks ilike '%usercheck%' then 'usercheck_api' when remarks ilike '%dynamicemail%' then 'dynamic_email_filter' when remarks ilike '%dynamicdomain%' then 'dynamic_domain_filter' when remarks ilike '%maximum login%' then 'max_login_attempts' else 'other' end cls from core_blacklisteduserdetail where type='user_email' and not is_removed),
e as (select lower(t.email) em, min(t.created_on) first_otp, max(t.created_on) last_otp, count(*) codes from notifications_twofactorauth t where t.source='sign_up' and t.email like '%@%' group by 1)
select be.cls, be.source, count(*), sum(codes), count(*) filter (where be.bc < e.first_otp), count(*) filter (where be.bc between e.first_otp and e.last_otp + interval '1 hour'), count(*) filter (where be.bc > e.last_otp + interval '1 hour'), count(u.id)
from e join be on be.em=e.em left join users_user u on lower(u.email)=e.em group by 1,2 order by 3 desc;
-- dynamic_email_filter/ecom_users 59 / 152 / 0 / 55 / 4 / 0 registered; ecom_legacy 5 (4 reg); ecom_gifts 2 (2); max_login_attempts 2 / 12 codes (2)
```
**R4: live blacklisted accounts by rule class; tokens after the entry**
```sql
with b as materialized (select id, type, lower(value) v, value rawv, created_on bc, is_removed, <cls CASE as R3> cls from core_blacklisteduserdetail where type in ('user_email','user_mobile_no')),
m as (select b.cls, b.type, b.bc, u.id uid, u.date_joined dj from b join users_user u on lower(u.email)=b.v where b.type='user_email' and not b.is_removed and not u.is_deleted
 union all select b.cls, b.type, b.bc, u.id, u.date_joined from b join users_user u on u.phone_number=b.rawv where b.type='user_mobile_no' and not b.is_removed and not u.is_deleted)
select m.cls, m.type, count(distinct m.uid), count(distinct m.uid) filter (where m.dj > m.bc), count(distinct t.user_id), count(distinct t.id) filter (where t.created_on>m.bc), count(distinct t.user_id) filter (where t.created_on>m.bc)
from m left join users_cognitoissuedtokens t on t.user_id=m.uid group by 1,2 order by 3 desc;
-- none/email 569 | 3 | 23 | 7 | 5; none/mobile 283 | 0 | 12 | 4 | 3; max_login/mobile 267 | 0 | 23 | 9 | 5; max_login/email 128 | 0 | 14 | 5 | 3; other/email 62 | 0 | 2 | 2 | 2; other/mobile 3 | 0 | 0 | 0 | 0
-- (rows overlap across classes; distinct users with post-blacklist tokens = 12 / 18 tokens per users.md C8)
```
**R5: top signup hours since 2026-06-01**
```sql
with h as (select date_trunc('hour',date_joined) hr, count(*) n from users_user where date_joined>='2026-06-01' group by 1),
s as (select percentile_cont(0.5) within group (order by n) med, percentile_cont(0.99) within group (order by n) p99, count(*) hours from h)
select to_char(h.hr,'YYYY "m" MM "d" DD HH24'), h.n, round(s.med), round(s.p99), s.hours from h, s order by h.n desc limit 15;
-- median 29, p99 84, 2,893 hours; top: Sep 22 13h 199, 12h 163, 14h 153; Aug 20 14h 142; Sep 22 16h 141 …
```
**R6: burst-hour cohort against normal hours (signups 2026-07-13 → 09-27)**
```sql
with h as (select date_trunc('hour',date_joined) hr, count(*) n from users_user where date_joined>='2026-07-13' group by 1),
u as (select u.id, u.is_deleted, u.is_app_user, u.country_of_residence res, lower(split_part(u.email,'@',2)) dom, u.phone_number, case when h.n>=84 then 'burst_hour' else 'normal_hour' end cls
 from users_user u join h on h.hr=date_trunc('hour',u.date_joined) where u.date_joined>='2026-07-13' and u.date_joined<'2026-09-28'),
t as (select user_id, bool_or(created_on - (select date_joined from users_user x where x.id=user_id) > interval '1 day') ret from users_cognitoissuedtokens group by 1)
select cls, count(*), avg(is_deleted), avg(is_app_user), avg(freemail), avg(res='SA'), avg(res='AE'), avg(phone/residence mismatch), avg(has token), avg(returned) from u left join t on t.user_id=u.id group by 1;
-- burst 2,330: del 1.55%, app 87.8, freemail 70.0, SA 73.1, AE 20.4, mismatch 1.3, token 95.8, returned 1.9
-- normal 49,982: del 1.28%, app 82.1, freemail 78.0, SA 50.6, AE 35.5, mismatch 1.0, token 71.4, returned 3.5
```
**R7: same-minute, same non-freemail-domain signup clusters (2026)**
```sql
with u as (select date_trunc('minute',date_joined) mi, lower(split_part(email,'@',2)) dom, is_deleted from users_user where date_joined>='2026-01-01'),
d as (select mi, dom, count(*) n, sum(is_deleted::int) del from u where dom not in ('gmail.com','hotmail.com','outlook.com','yahoo.com','icloud.com','live.com','hotmail.co.uk','yahoo.co.uk','me.com','outlook.sa') group by 1,2)
select case when n>=10 then '10+' when n>=5 then '5-9' when n>=3 then '3-4' when n=2 then '2' else '1' end, count(*), sum(n), sum(del) from d group by 1;
-- 1: 44,971 cells; 2: 992 (1,984 users); 3-4: 85 (258); 5-9: 4 (20); 10+: 0
```
**R8: 2026 signups by email-domain class; blacklisted-domain timing**
```sql
with bd as materialized (select lower(value) dom, min(created_on) bc from core_blacklisteduserdetail where type='user_domain' and not is_removed group by 1),
u as (select id, lower(split_part(email,'@',2)) dom, is_deleted, date_joined from users_user where date_joined>='2026-01-01')
select case when bd.dom is not null then case when u.date_joined>bd.bc then 'bl_domain_joined_after' else 'bl_domain_joined_before' end when u.dom in (<freemail list>) then 'freemail' when u.dom='privaterelay.appleid.com' then 'apple_relay' when u.dom like '%.edu%' or u.dom like '%.gov%' or u.dom like '%.ac.%' then 'edu_gov' when u.dom='' then 'no_email' else 'other_domain' end,
 count(*), sum(u.is_deleted::int), count(distinct u.dom) from u left join bd on bd.dom=u.dom group by 1;
-- freemail 161,718; apple_relay 21,523; other_domain 20,811 (4,572 domains); no_email 2,874 (all deleted); edu_gov 1,295; bl_domain_joined_before 487 (224 domains); joined_after 0
```
**R9: identifier scrub on deleted accounts, by join year**
```sql
select is_deleted, extract(year from date_joined)::int, count(*), count(*) filter (where email not like '%@%'), count(*) filter (where phone_number not like '+%'),
 min(length(email)) filter (where email not like '%@%'), max(length(email)) filter (where email not like '%@%') from users_user group by 1,2;
-- live: 0 emails without '@' in every year; deleted: every row without '@' except none (e.g. 2026 2,875 / 2,874; 2023 7,925 / 7,925); lengths 52–144
select is_deleted, count(*), count(*) filter (where coalesce(email,'')='') , count(*) filter (where email_verified), count(*) filter (where phone_number_verified),
 count(*) filter (where modified_on - date_joined < interval '1 day') from users_user group by 1;
-- live 974,221: 2 empty emails, 974,192 email_verified, 974,193 phone_verified; deleted 22,108: 1 empty, 22,103 / 22,103
```
**R10: character class of scrubbed emails**
```sql
select length(email), email ~ '^[0-9a-f]+$', email ~ '^[A-Za-z0-9+/=]+$', count(*) from users_user where is_deleted and email not like '%@%' group by 1,2,3 order by 4 desc;
-- all base64 alphabet, lengths multiple of 4 (64: 6,103; 68: 5,962; 72: 3,236; 84: 2,786; 60: 2,373 …)
```
**R11: byte-level shape of the decoded scrub (counts only)**
```sql
select count(*), count(*) filter (where position('\x40'::bytea in decode(email,'base64'))>0), count(*) filter (where position('\x00'::bytea in decode(email,'base64'))>0),
 min(length(decode(email,'base64'))), max(length(decode(email,'base64'))), count(distinct substr(decode(email,'base64'),1,4))
from users_user where is_deleted and email not like '%@%' and email ~ '^[A-Za-z0-9+/=]+$' and length(email)%4=0;
-- 22,107 | 3,188 with '@' byte | 3,268 with NUL | 19–98 bytes | 11,454 distinct 4-byte prefixes  → binary ciphertext, not text
-- (a first attempt with convert_from(..., 'LATIN1') failed on 0x00, which is itself evidence of binary content)
```
**R12: deleted users on shared devices**
```sql
with d as (select t.device_signature ds, u.is_deleted, u.id uid from users_cognitoissuedtokens t join users_user u on u.id=t.user_id where coalesce(t.device_signature,'')<>''),
g as (select ds, count(distinct uid) users, count(distinct uid) filter (where is_deleted) del_users from d group by 1 having count(distinct uid)>=2)
select count(*), sum(users), sum(del_users), count(*) filter (where del_users>0), (select count(distinct uid) from d where is_deleted) from g;
-- 119 shared devices | 248 users | 2 deleted | 2 devices | 5 deleted users with any device
```
**R13: device blacklist against tokens; shared-device users against the blacklist**
```sql
with bdev as materialized (select value v, created_on bc, is_removed from core_blacklisteduserdetail where type='user_device_id'),
t as (select id, user_id, device_signature ds, created_on from users_cognitoissuedtokens where coalesce(device_signature,'')<>''),
sh as (select ds from t group by 1 having count(distinct user_id)>=2),
bl_users as (select u.id from core_blacklisteduserdetail b join users_user u on lower(u.email)=lower(b.value) where b.type='user_email' and not b.is_removed union select u.id from core_blacklisteduserdetail b join users_user u on u.phone_number=b.value where b.type='user_mobile_no' and not b.is_removed)
select (select count(*) from bdev), (select count(*) from t join bdev on bdev.v=t.ds), (select count(distinct t.user_id) from t join bdev on bdev.v=t.ds),
 (select count(*) from t join bdev on bdev.v=t.ds and not bdev.is_removed and t.created_on>bdev.bc),
 (select count(distinct t.user_id) from t join sh using (ds)), (select count(distinct t.user_id) from t join sh using (ds) where t.user_id in (select id from bl_users)), (select count(*) from bl_users);
-- 166 | 10 tokens | 9 users | 2 after active device blacklist | 247 shared-device users | 5 blacklisted | 903
```
**R14: out-of-GCC login users against blacklist rate (SA/AE residents)**
```sql
with bl_users as materialized (<as R13>),
x as (select t.user_id, u.country_of_residence res, u.is_deleted, u.phone_number, bool_or(t.request_meta->>'COUNTRY' is not null and t.request_meta->>'COUNTRY' not in ('Saudi Arabia','United Arab Emirates','Qatar','Kuwait','Oman','Bahrain')) out_gcc, bool_or(t.user_platform='WEB') web
 from users_cognitoissuedtokens t join users_user u on u.id=t.user_id where u.country_of_residence in ('SA','AE') group by 1,2,3,4)
select out_gcc, count(*), count(*) filter (where user_id in (select id from bl_users)), avg(is_deleted), avg(phone mismatch), avg(web) from x group by 1;
-- home-only 46,725 | 12 | 0.01% | 0.1% | 16.5% ; out-of-GCC 2,386 | 8 | 0.00% | 0.7% | 24.7%
```
**R15: monthly blacklist adds by producer class (since 2025-06)**
```sql
select to_char(date_trunc('month',created_on),'YYYY "m" MM'), count(*) filter (where remarks ilike '%usercheck%'), count(*) filter (where remarks ilike '%dynamicemail%'), count(*) filter (where remarks ilike '%dynamicdomain%'), count(*) filter (where remarks ilike '%maximum login%'),
 count(*) filter (where source='ecom_users' and not (coalesce(remarks,'') ilike any (array['%usercheck%','%dynamicemail%','%dynamicdomain%','%maximum login%']))), count(*) filter (where source<>'ecom_users'), count(*), max(dc)
from (select *, count(*) over (partition by date_trunc('day',created_on)) dc from core_blacklisteduserdetail) b where created_on>='2025-06-01' group by date_trunc('month',created_on) order by 1;
-- see §1.3 table (2025-06 … 2026-09)
```
**R16: bulk blacklist days (60 or more rows per day, class and type)**
```sql
select to_char(date_trunc('day',b.created_on),'YYYY "m" MM "d" DD'), <cls CASE>, b.type, count(*), count(distinct date_trunc('minute',b.created_on)), count(distinct b.created_by_id), count(*) filter (where b.is_guest), count(u.id),
 count(distinct lower(split_part(b.value,'@',2))) filter (where b.type='user_email'), to_char(min(b.created_on),'HH24:MI'), to_char(max(b.created_on),'HH24:MI')
from core_blacklisteduserdetail b left join users_user u on b.type='user_email' and lower(u.email)=lower(b.value) where b.created_on>='2025-07-01' group by 1,2,3 having count(*)>=60 order by 4 desc;
-- 2026-08-25 dyn_email user_email 797 | 38 min | 1 creator | 797 guest | 1 matches user | 3 domains | 16:35–23:06
-- 2026-06-24 dyn_domain 287 | 250 min; 2026-06-23 dyn_domain 94 | 67 min; 2025-07-22 other email 124 (47 match users); 2025-07-23 other email 100;
-- 2025-11-17 other email 99 in 5 min (1 domain); 2025-11-17 other user_ip 60 in 7 min
```
**R17: address shape of dynamic-email-filter entries (Aug 25 against other days)**
```sql
with b as (select lower(value) v, created_on from core_blacklisteduserdetail where type='user_email' and remarks ilike '%dynamicemail%')
select case when created_on >= '2026-08-25' and created_on < '2026-08-26' then 'aug25' else 'other_days' end, <freemail class>, count(*), count(*) filter (where split_part(v,'@',1) like '%+%'),
 round(avg(length(split_part(v,'@',1))),1), count(*) filter (where split_part(v,'@',1) ~ '[0-9]{3,}'), count(distinct split_part(v,'@',2)), count(distinct regexp_replace(split_part(v,'@',1),'[0-9]','','g'))
from b group by 1,2;
-- aug25 freemail 797 | 0 plus | 15.8 | 561 (70%) | 3 domains | 786 stems ; other freemail 809 | 1 | 13.0 | 402 (50%) | 6 ; other non-freemail 130 | 0 | 11.5 | 32 | 61
```
**R18: whitelist/blacklist conflicts**
```sql
select (select count(*) from core_whitelisteduserdetail w join core_blacklisteduserdetail b on b.type=w.type and lower(b.value)=lower(w.value) where not w.is_removed and not b.is_removed),
 (select count(*) from core_whitelisteduserdetail w join core_blacklisteduserdetail b on b.type=w.type and lower(b.value)=lower(w.value)),
 (select count(*) from users_user u where u.trusted_user and not u.is_deleted and exists (select 1 from core_blacklisteduserdetail b where b.type='user_email' and not b.is_removed and lower(b.value)=lower(u.email))),
 (select count(*) from core_blacklisteduserdetail where type='sms_country_code' and not is_removed), (select count(*) from core_whitelisteduserdetail where type='sms_country_code' and not is_removed),
 (select count(*) from core_whitelisteduserdetail w join core_blacklisteduserdetail b on b.type=w.type and b.value=w.value where w.type='sms_country_code' and not w.is_removed and not b.is_removed);
-- 15 active conflicts | 61 any | 0 trusted∧blacklisted | 101 active bl codes | 62 active wl codes | 13 sms_cc conflicts
```
**R19: sms_country_code list values** (ISO-2 country codes; not PII)
```sql
select 'bl', value, is_removed from core_blacklisteduserdetail where type='sms_country_code' union all select 'wl', value, is_removed from core_whitelisteduserdetail where type='sms_country_code' order by 1,2;
-- ISO-2, mixed case (ag, aw, ba, bb, bm, bz, cg, gd, gf, gp, gt, gy, ht, kg, md, pe …); removed on bl: AU, EG, FR, GB, GI, IE, IT, KR, KW, LB, MA, MY, OM, PH, PK, RU
-- output truncated at 150 rows (whitelist tail not shown; conflicts measured by R18/R20)
```
**R20: OTPs to listed countries (calling-code prefix map)**
```sql
with m(iso,pfx) as (values ('BR','+55'),('ES','+34'),('DE','+49'),('NG','+234'),('ID','+62'),('CN','+86'),('VN','+84'),('BD','+880'),('KE','+254'),('ZA','+27'),('UA','+380'),('MX','+52'),('IL','+972'),('JO','+962'),('IQ','+964'),('GH','+233'),('MA','+212'),('PK','+92'),('EG','+20'),('PH','+63'),('LK','+94'),('NP','+977'),('SD','+249'),('SY','+963'),('TN','+216'),('DZ','+213'),('LB','+961'),('RU','+7')),
bl as (select upper(value) iso, bool_or(not is_removed) bl_active from core_blacklisteduserdetail where type='sms_country_code' group by 1),
wl as (select upper(value) iso, bool_or(not is_removed) wl_active from core_whitelisteduserdetail where type='sms_country_code' group by 1)
select m.iso, bl_active, wl_active, count(t.id), count(t.id) filter (where t.sms_delivery), count(distinct t.phone_number), (select count(*) from users_user u where not u.is_deleted and u.date_joined>='2026-08-29' and u.phone_number like m.pfx||'%')
from m left join bl using (iso) left join wl using (iso) left join notifications_twofactorauth t on t.phone_number like m.pfx||'%' group by 1,2,3,m.pfx order by 4 desc;
-- unlisted/removed: EG 342 OTPs (292 signups), RU 177 (94), PK 76, PH 34, LB 24; bl+wl (whitelist wins): JO 53, IQ 38, IL 37, DE 28, ZA 25, BR 21, ES 18, CN 10, TN 10;
-- bl only: UA 1, LK/DZ/GH/ID/KE/BD/MX/NG/NP/SD/SY/VN 0
```
**R21: +1 sign_up numbers, Caribbean/Pacific against US/CA**
```sql
with n as (select t.phone_number ph, count(*) codes, bool_or(v.is_valid) anyv from notifications_twofactorauth t join notifications_twofactorauthverification v on v.reference_id_id=t.id where t.source='sign_up' and t.phone_number like '+1%' group by 1)
select case when substr(ph,3,3) in ('268','246','441','473','876','809','829','849','868','242','284','345','758','767','784','869','664','649','721','340','787','939','671','670','684','658') then 'nanp_caribbean_pacific' else 'us_ca' end,
 count(*), sum(codes), count(*) filter (where anyv), count(u.id), count(*) filter (where codes>=3), round(avg(codes),2) from n left join users_user u on u.phone_number=n.ph group by 1;
-- caribbean/pacific 5 / 6 / 5 / 5 ; us_ca 262 / 320 / 129 / 128 / 8 / 1.22
```
**R22: US/CA unverified numbers: day and area-code spread**
```sql
with n as (select t.phone_number ph, t.auth_type, bool_or(v.is_valid) anyv, min(t.created_on) f from notifications_twofactorauth t join notifications_twofactorauthverification v on v.reference_id_id=t.id where t.source='sign_up' and t.phone_number like '+1%' group by 1,2)
select auth_type, anyv, count(*), count(distinct date_trunc('day',f)), max(c), count(distinct substr(ph,1,5)), count(distinct substr(ph,1,8))
from (select *, count(*) over (partition by anyv, auth_type, date_trunc('day',f)) c from n) x group by 1,2;
-- whatsappsms unverified 133 numbers / 31 days / max 9 per day / 101 area codes; verified 132 / 27 / 12 / 96
```
**R23: age at last modification, deleted against live**
```sql
select case when date_joined>='2025-06-01' then 'joined_since_2025_06' else 'joined_before' end, case when modified_on-date_joined<interval '10 minutes' then 'a <10m' when modified_on-date_joined<interval '1 hour' then 'b 10m-1h' when modified_on-date_joined<interval '1 day' then 'c 1h-1d' when modified_on-date_joined<interval '30 days' then 'd 1-30d' else 'e >30d' end,
 count(*) filter (where is_deleted), count(*) filter (where not is_deleted), count(*) filter (where is_deleted and modified_by_id is not null and modified_by_id<>id) from users_user group by 1,2;
-- before: deleted 3,821 / 2,432 / 1,931 / 2,933 / 5,347; live 480,255 / 5,978 / 5,709 / 8,541 / 111,761
-- since 2025-06: deleted 1,433 / 966 / 1,013 / 1,383 / 849; live 329,127 / 7,683 / 7,292 / 8,005 / 9,879; deleted by another actor: 21 in total
```
**R24: fraud-control config (keys and scalar flags only)**
```sql
select k, k2, jsonb_typeof(config->k->k2) from core_siteconfiguration, jsonb_object_keys(config) k, lateral jsonb_object_keys(case when jsonb_typeof(config->k)='object' then config->k else '{}' end) k2
where k in ('disposable_usercheck','dynamic_throttle_manager','disposable_email_manager','automation_accounts','update_phone_number','voice_alert_config');
select config->'disposable_email_manager'->>'disposable_email_manager_enabled', config->'disposable_usercheck'->>'disposable_usercheck_enabled', config->'voice_alert_config'->>'otp.limit', config->'voice_alert_config'->>'max.retries',
 (select string_agg(k||':'||jsonb_typeof(config->'dynamic_throttle_manager'->'dynamic_throttle_config'->k), ', ') from jsonb_object_keys(config->'dynamic_throttle_manager'->'dynamic_throttle_config') k),
 (select count(*) from jsonb_object_keys(config->'automation_accounts')) from core_siteconfiguration;
-- true | true | 22 | 5 | enabled_countries, ip_manager_config, email_manager_config, domain_manager_config, authentication_manager_config, adaptive_… | 3 automation accounts (keys redacted)
```
**R25: automation-account footprint**
```sql
with a as (select lower(k) e from core_siteconfiguration, jsonb_object_keys(config->'automation_accounts') k)
select count(*), count(u.id), (select count(*) from users_cognitoissuedtokens t join users_user u2 on u2.id=t.user_id where lower(u2.email) in (select e from a)),
 (select count(*) from notifications_twofactorauth t where lower(t.email) in (select e from a)), (select count(*) from core_blacklisteduserdetail b where b.type='user_email' and lower(b.value) in (select e from a))
from a left join users_user u on lower(u.email)=a.e;
-- 3 | 3 | 13 tokens | 0 OTPs | 0 blacklisted
```
**R26: top residence/login mismatch pairs: spread and home logins**
(The first version, with a correlated subquery, hit the 20 s timeout. It was rewritten with materialized CTEs and run once.)
```sql
with x as materialized (select u.country_of_residence res, t.request_meta->>'COUNTRY' c, t.user_id, t.created_on, t.user_platform p, (t.created_on-u.date_joined<=interval '1 day') is_new from users_cognitoissuedtokens t join users_user u on u.id=t.user_id),
pair as (select res, c, user_id from x where (res,c) in (('SA','Spain'),('AE','Brazil'),('RU','Germany'),('SA','United States'),('AE','India'),('AE','Romania')) group by 1,2,3),
home as (select distinct user_id from x where c = case res when 'SA' then 'Saudi Arabia' when 'AE' then 'United Arab Emirates' when 'RU' then 'Russia' end),
agg as (select res, c, count(*) toks, count(distinct user_id) users, count(distinct date_trunc('day',created_on)) days, count(*) filter (where is_new) new_tok, count(*) filter (where p='WEB') web from x where (res,c) in (select res,c from pair) group by 1,2),
dmax as (select res, c, max(n) mx from (select res, c, date_trunc('day',created_on) d, count(*) n from x where (res,c) in (select res,c from pair) group by 1,2,3) q group by 1,2)
select agg.*, dmax.mx, (select count(*) from pair p join home h using (user_id) where p.res=agg.res and p.c=agg.c) from agg join dmax using (res,c) order by toks desc;
-- SA→US 211/200/57 days/125 new/34 web/max 31/20 also home; AE→India 204/197/61/77/32/8/57; SA→Spain 189/183/55/145/12/12/13;
-- AE→Brazil 91/90/44/53/25/5/7; RU→Germany 82/82/5/82/82/36/0; AE→Romania 53/49/37/28/22/4/2
```
**R27: RU→Germany cohort by signup day**
```sql
with r as materialized (select distinct t.user_id from users_cognitoissuedtokens t join users_user u on u.id=t.user_id where u.country_of_residence='RU' and t.request_meta->>'COUNTRY'='Germany')
select to_char(date_trunc('day',u.date_joined),'YYYY "m" MM "d" DD'), count(*), count(distinct lower(split_part(u.email,'@',2))), count(*) filter (where <freemail>), count(*) filter (where u.phone_number like '+7%'),
 count(*) filter (where u.is_deleted), count(*) filter (where u.is_app_user), count(*) filter (where split_part(u.email,'@',1) ~ '[0-9]{3,}'), count(distinct date_trunc('minute',u.date_joined))
from r join users_user u on u.id=r.user_id group by date_trunc('day',u.date_joined) order by 1;
-- Sep 01 1; Sep 26 36 (2 domains, 36 freemail, 36 +7, 34 digit-local, 36 minutes); Sep 27 17 (1 domain); Sep 28 2; Sep 29 26 (1 non-freemail domain); 0 deleted, 0 app users
```
**R28: RU list-entry history; daily +7 OTPs and signups since Aug 29**
```sql
select 'ru_bl_entry', to_char(created_on,F), to_char(modified_on,F), is_removed::text, null from core_blacklisteduserdetail where type='sms_country_code' and upper(value)='RU'
union all select 'ru_wl_entry', … from core_whitelisteduserdetail where type='sms_country_code' and upper(value)='RU'
union all select 'otp_+7_day', to_char(date_trunc('day',created_on),F), source, auth_type, count(*) from notifications_twofactorauth where phone_number like '+7%' group by 2,3,4
union all select 'signups_+7_day', to_char(date_trunc('day',date_joined),F), country_of_residence, null, count(*) from users_user where phone_number like '+7%' and date_joined>='2026-08-29' group by 2,3;
-- RU bl: created 2023-05-14, modified 2025-10-16, is_removed=true; RU wl: created 2023-05-31, modified 2025-11-27, removed
-- +7 sign_up OTPs: 1–5 per day to Sep 25, then Sep 26 59, Sep 27 32, Sep 28 6, Sep 29 58; +7 signups (RU): Sep 26 36, 27 17, 28 3, 29 27 (baseline 0–2 per day)
```
**R29: RU wave accounts: list status, channel, fingerprint diversity**
```sql
with r as materialized (select id, email, phone_number, date_joined from users_user where phone_number like '+7%' and country_of_residence='RU' and date_joined>='2026-09-26')
select count(*), count(*) filter (where exists (select 1 from core_blacklisteduserdetail b where not b.is_removed and ((b.type='user_email' and lower(b.value)=lower(r.email)) or (b.type='user_mobile_no' and b.value=r.phone_number) or (b.type='user_domain' and lower(b.value)=lower(split_part(r.email,'@',2)))))),
 count(*) filter (where exists (select 1 from users_cognitoissuedtokens t where t.user_id=r.id)), count(*) filter (where exists (… and t.user_platform='WEB')), count(*) filter (where exists (… and t.request_meta->>'COUNTRY'='Germany')),
 (select count(distinct t.request_meta->>'BROWSER') from users_cognitoissuedtokens t where t.user_id in (select id from r)), (select count(distinct t.request_meta->>'OS_TYPE') from users_cognitoissuedtokens t where t.user_id in (select id from r)), count(distinct extract(hour from date_joined))
from r;
-- 83 accounts | 0 blacklisted | 83 with token | 83 WEB | 81 DE egress | 5 browser builds | 2 OS types | 14 distinct signup hours
```

**Figures reused from profiles** (SQL in their appendices): users.md B12, C5, C6, C6b, C7, C8, S1, B5, B7, §10 dead fields; cross-db.md X13, X26, X27, X27b, X28, X30, X31, X32, X35, X40; orders-funnel.md, orders-customer-catalog.md and orders-integrations.md (fraud columns, catalog only).
