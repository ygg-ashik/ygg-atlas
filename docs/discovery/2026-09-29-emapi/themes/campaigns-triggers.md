# Theme: Campaigns, triggers & personalization

Written 2026-09-29 by the analytics-strategy pass for ygg-atlas. Inputs: the seven unit profiles in `../profiles/` (cross-db and users read in full; emapi-stores, orders-funnel read for the theme; orders-customer-catalog, orders-integrations, ecomweb-stores searched for theme terms). New queries T1–T15 (appendix) were run through `atlasq.sh`: data queries against `ygag_ecom_users_db` only, catalog-only queries against orders / ecomweb / emapi. No privilege workaround was attempted.

**Evidence labels.** **VALIDATED** = a data query was run (T-numbers here, or a profile's appendix, cited as [profile X]). **STRUCTURAL** = schema, catalog stats or sizes only. **NEEDS-GRANT** = needs rows we cannot read; the table.columns are named. **[inferred]** = my reasoning on top of labelled facts, never a measurement.

**As-of.** users-DB figures are live and drift by about 0.1% during the day. The T-queries ran 2026-09-29, roughly 13:30–14:15 UTC; the revision queries T16–T27 ran later the same day. OTP tables hold a rolling 31 days (2026-08-29 → 2026-09-29).

**Revision note (critic pass 1).** Fixed: (1) the phone OTP "non-GCC" bucket actually contained other GCC countries and India; it is re-split in T16/T17, and the real unconfigured-country failure rate is 23.3%, not 13.6%. (2) H1's "3x" premise is refuted by a per-recipient recomputation (T18): multi-code recipients register 56.8% vs 82.7%. (3) T6 double-counted recipients who got codes in two languages; T18 groups by recipient only. (4) The grants table named a non-existent `order_order` column; it now uses catalog-verified names (T25). Added: a referral proxy (I10, F19), an occasion calendar from readable data (I4, T20–T22), send-time windows (I11, T23), trigger overlap and frequency capping (I12, T24), a gender × occasion segment (I4), and a birthday local-date rule (I1, T26). Labels are made consistent: every figure that comes from a data query is VALIDATED.

---

## 0. The short version

1. **Atlas can already power three lifecycle triggers from the identity DB, and all three are big.** (a) **Birthday**: 303,223 live, non-shell users have a usable day and month of birth. 26,833 of them have a birthday in the next 30 days, about 890 a day. (b) **OTP-failure / abandoned-signup rescue**: in 31 days, 3,644 of 16,996 email-signup recipients (21.4%) never ended up with an account. 1,888 never got a code accepted and 1,756 had a code accepted but still did not register. On phone, recipients in countries with no routing config fail 23.3% of the time, against 2.7% in SA/AE; US/Canada numbers fail 49.8%. (c) **Gift-recipient conversion**: 26,737 accounts (45% of all gift-claim users) were created no more than a day before the user's first gift claim. Gifting is an acquisition channel, and it is the only referral signal the data has. [VALIDATED T3, T4, T8, T16–T18]
2. **Every trigger that needs a purchase is blocked**: first-purchase nudge, abandoned basket, dormant reactivation, occasion anniversary reminder, offer redemption. These need orders / emapi rows (NEEDS-GRANT). Everything about sends, deliveries, opens and consent needs sources atlas does not have yet: `ygag_mailengine_aps_db`, `ygag_smsengine_db`, and a consent store. **None of the four DBs has a marketing-consent column** (T1, T12) [STRUCTURAL].
3. **The occasion calendar is the strongest campaign lever we can see, and it can be built from readable data today.** Across 23 months, readable signup and gift-claim spikes (≥1.8–2x a trailing 28-day mean) fall into three families: **Ramadan / pre-Eid in SA** (2025-03-26 SA signups 8.5x, gift claims 9.7x; 2026-03-08 claims 7.7x), **AE spikes that are strongly female** (gift claims 42–60% female on spike days, against a 26.8% AE baseline), and the **Sep 22–24 2026 SA push** (3.4x / 2.6x / 3.0x). Saudi National Day 2025 lifted SA signups only about 1.5x, so the 2026 tripling is not a plain calendar effect; it looks like a campaign on top of the day. [VALIDATED T10, T20–T22; occasion names are inferred from dates] Atlas should treat occasions as a first-class dimension, and measure them with country-vs-country difference-in-differences, because there are no send logs to attribute from.

---

## 1. Insights

### I1. Birthday is a real, growing trigger field, but shell accounts and a default value must be removed first [VALIDATED T3, T4; profile C1]
- `users_user.birthdate` is `0000/DD/MM`: a day and month with no year. Of **974,197 live users**, **105,501 are migration "shell" accounts** that have never logged in, and **48,920 of those still carry a birthdate**. Once shell accounts and the `0000/01/01` default are excluded, **303,223 of the 868,696 live non-shell users (34.9%)** have a usable birthday. [T3]
- **Next 30 days (Sep 30 → Oct 29): 26,833 birthdays**, about 890 a day. SA 138,100 and AE 129,159 usable birthdays in total. [T3]
- **Capture more than doubled in Nov 2025.** About 21–23% of signups gave a birthday in Jul–Oct 2025 (for example Oct 4,665 / 21,925). The share was 40% in Nov 2025, 51% in Dec, and has held at about 48–50% through 2026 (Sep: 11,608 / 23,903). The signup form changed. The `0000/01/01` default grew with it, to 400–800 a month. [T4]
- Among the 54,812 users who logged in on the new platform since Jul 2026 (token holders), **47.0% (25,768)** have a usable birthday. The recently active base is better covered than the whole base. [T3]
- Gender is recorded for about 100% of signups since Jul 2025 (T4). Across the whole base, 223k users have no gender [profile]. So gender is only usable as a segment for recent cohorts (see I4 for the gender × occasion segment).
- **Birthdays need a local-date rule** [VALIDATED T26]. The field is day and month only, so the send day must be computed in the user's own timezone. 35,973 of 303,341 usable birthdays (11.9%) belong to users outside SA/AE: QA 8,726, KW 4,591, IN 3,307, EG 2,902, AM 2,426, GB 2,326, OM 2,265, BH 2,129, then PH, MX, US. Rules for the `v_birthday` view [the rules are design, not data]:
  - Map `country_of_residence` to an IANA zone (SA/QA/KW/BH `Asia/Riyadh` +3; AE/OM `Asia/Dubai` +4; IN +5:30; GB, EG, US and MX have DST). A job that selects "birthday = today" in UTC is correct for the GCC only if it runs after 21:00 UTC the day before (00:00 Riyadh). For negative-offset countries (US, MX), a UTC-date job fires a day early.
  - **144 users have a 29 Feb birthday**. 2027 is not a leap year, so send on 28 Feb.
  - **50 users have an impossible date** (30/31 Feb, 31 Apr/Jun/Sep/Nov). T3 counted them as usable; exclude them in the view. (T26's 303,341 differs from T3's 303,223 because T26 does not range-check day and month and ran later. The 118-row gap is the missing range check plus live drift.)
  - The send window is local 09:00–22:00 (I11). Null `country_of_residence` falls back to the phone prefix, then to `Asia/Dubai`.

### I2. Signup OTP loses about 1 in 5 email recipients and 1 in 4 phone recipients in unconfigured countries, and a resend is the tell [VALIDATED T16–T18; profile B5]
Per recipient, 31 days, `source='sign_up'`, checked against whether the email or phone is now registered (in-DB join, counts only). Email is grouped by recipient only, with the language of the first code (T18 replaces T6, which split recipients by language and double-counted about 1%).

| Channel / segment | Recipients | Never accepted, not registered | Accepted, not registered | Registered |
|---|---|---|---|---|
| Email | 16,996 | **1,888 (11.1%)** | **1,756 (10.3%)** | 13,352 (78.6%) |
| Phone, SA +966 | 14,137 | 380 (2.7%) | 116 | 13,641 |
| Phone, AE +971 | 8,547 | 231 (2.7%) | 70 | 8,246 |
| Phone, other GCC (+965/+974/+973/+968) | 1,467 | 56 (3.8%) | 13 | 1,398 |
| Phone, India +91 | 341 | 26 (7.6%) | 9 | 306 |
| Phone, all other countries (no routing config) | 1,694 | **395 (23.3%)** | 10 | 1,289 |

- **A resend predicts failure, but less strongly than the first draft said.** Email recipients who needed 1 code registered 82.7% of the time (11,812 / 14,284). Recipients who needed 2 or more registered 56.8% (1,540 / 2,712): 2 codes 59.4%, 3 or more 52.6%. So multi-code recipients are **1.46x less likely to register**, and **2.5x more likely not to** (43.2% vs 17.3%). Among never-accepted, unregistered recipients, 37.2% had 2 or more codes, against 11.3% of accepted and registered ones. Those are shares within each outcome, not registration rates. [T18]
- **1,756 email recipients got a code accepted but never registered.** They dropped out after OTP, at the profile or password step. This is a different rescue audience ("finish your account"), not "your code didn't arrive". [T18; the step is inferred]
- **The phone failure is concentrated in countries with no routing config at all.** `notifications_communicationcountryconfigs` has entries (for `signin` only) for 7 countries: AE, IN, SA, KW, QA, BH, OM (T2). Every one of those countries fails signup OTP at 2.7–7.6%. The countries with no config fail at 23.3%, which is **8.6x the SA/AE rate**. Within them [T17]: **US/Canada 133 / 267 (49.8%)**, RU/KZ 31 / 125 (24.8%), UK 71 / 352 (20.2%), PK 16 / 65 (24.6%), AU 11 / 57 (19.3%), EG 34 / 325 (10.5%). Numbers written with a trunk zero after the country code (for example +44 0…, +20 0…) are 1–3 of the failures per country, so number formatting is not the cause.
- Cause [inferred]: the config list may simply mark the countries where the business already has working provider routes, so it probably flags where delivery works rather than causing it. India is configured and still fails 2.8x the SA/AE rate. The signup flow itself has no per-country config. Delivery receipts by prefix (smsengine) are needed to confirm the cause.
- Language: 20.2% of email recipients got an Arabic first code (3,427 / 16,996). Arabic is over-represented among never-accepted failures (454 / 1,888 = 24.0%) against registered recipients (2,731 / 13,352 = 20.5%). On phone, 39.2% of registered SA recipients used Arabic OTP (5,355 / 13,645), against 0.4% in AE (T7). [T18, T7]
- Daily cost at peaks: see H6 (T19).

### I3. Gifting is an acquisition loop. Recipient-acquired users show a weaker return signal, but tokens cannot tell us whether they disengage [VALIDATED T8, T9]
- `secondary_email_added_via_gift` (the recipient claims a gift into an account) covers **59,496 users**. For **26,737 (44.9%)** of them, the account was created no more than 1 day before the first claim, and for 23,994 (40.3%) no more than 1 hour before. By year: 2024 40.5%, 2025 46.5%, 2026 46.1%. [T8]
- These gift-driven signups are about **4.5% of all 2025 signups** (12,778 / 281,274) and about **3.9% in 2026 to date** (8,170 / 208,609; the denominator is from profile C2, so this is approximate). [T8 + profile]
- In the app cohort that signed up Jul 15 → Aug 28 2026, **gift-driven signups came back (a new token issued more than 1 day after signup) 2.6% of the time (30 / 1,146), against 4.4% for other app signups (921 / 20,938)**. All 1,146 gift-driven signups are `is_app_user`. [T9] Caveat: a returning token is a weak signal for app users, whose tokens live 548 days. The *relative* gap is the signal, not the level.
- Reading: recipients are acquired at the moment they claim. Fewer of them log in again from a new session, but a 548-day app token means most users never need a new token (I7), so this does **not** show that they leave. It shows only that the relative return signal is weaker. Whether they engage or buy needs orders (NEEDS-GRANT, H4). The "you received a gift, now send one" nudge is the obvious first-purchase trigger.

### I4. Occasion spikes are visible, geo-specific, and a historical calendar can be seeded now [VALIDATED T10, T20–T22; profile B6]
- **Sep 2026.** SA signups on Sep 22 / 23 / 24 were 1,171 / 961 / 1,159, against a Sep 15–21 average of 443 (2.2–2.6x). AE was 352 / 414 / 345 against 258 (about 1.4x). Gift-claim signups were 89 / 72 / 67 against 29 (about 2.6x). [T10]
- **Saudi National Day is not enough to explain it.** On Saudi National Day 2025 (Tue Sep 23), SA non-migrated signups were 479, against 246–392 on Sep 16–22 (about 1.5x), and the day does not reach the 1.8x spike threshold [T21]. The 2026 tripling therefore looks like a campaign on top of the occasion [inferred]. That makes it a clean diff-in-diff case: SA 2026 vs SA 2025 on the same day, with AE as the second control.
- **Historical spike calendar** (non-migrated signups, or gift-claim rows, at least 1.8x (signups) or 2x (claims) the trailing 28-day mean, Nov 2024 → Sep 2026) [T20, T22]. The occasion column is my reading of the date, not data:

| Date | Country | Signups (× base) | Gift claims (× base) | Female share of claims (gender known) | Likely occasion [inferred] |
|---|---|---|---|---|---|
| 2024-12-12 / 13 | AE | 1,012 (2.4x) / 1,335 (3.0x) | 231 / 527 AE (base 65–72) | 62% / 60% | Not UAE National Day (Dec 2). Probably a bulk or corporate gifting drop |
| 2025-02-17 | SA | — | 140 SA (base 24) | 9% | Pre-Ramadan / Founding Day week (Feb 22) |
| **2025-03-26 / 27** | SA | **3,628 (8.5x)** / 2,300 (4.3x) | **774** / 326 SA (base 34–60) | 4% / 5% | Last days of Ramadan 1446, before Eid al-Fitr (Mar 30) |
| 2025-06-23 → 26 | AE | 779 (2.0x), 898 (2.1x) | 119 → 248 AE (base 33–44) | 29–49% | Mid-year corporate rewards [inferred] |
| 2025-11-11 / 12 | SA | 759 (2.4x) / 603 (1.8x) | — | — | 11.11 sale |
| 2025-12-04 / 05 | AE | 688 (2.1x) / 663 (2.0x) | 141 / 240 AE (base 32–36) | 42% / 49% | Just after UAE National Day holiday (Dec 2–3) |
| **2026-03-08 / 09** | SA | 1,289 (2.7x) / 1,222 (2.4x) | **409** / 362 SA (base 19–32) | 7% / 6% | Mid-Ramadan 1447 |
| 2026-03-18 | AE | 756 (3.2x) | 160 AE (base 26) | 28% | Before Eid al-Fitr (~Mar 20) and Mother's Day (Mar 21) |
| 2026-04-09 | SA | 1,137 (2.5x) | 144 SA (base 24) | 12% | Unknown. Needs the campaign calendar |
| 2026-06-01 / 02 | AE | — | 144 / 72 AE (base 25–30) | 19% / 12% | Unknown (Eid al-Adha was ~May 27) |
| 2026-07-01 → 03 | AE | — | 85–153 AE (base 39–44) | 35–43% | Mid-year corporate rewards [inferred] |
| 2026-08-20 | SA | — | 126 SA (base 18) | 11% | Unknown |
| **2026-09-22 → 24** | SA | 1,171 (3.4x), 961 (2.6x), 1,159 (3.0x) | 43 SA on Sep 23 (base 22) | 14% (all countries) | Saudi National Day plus an acquisition push |

Smaller spikes left out of the table (1.8–2.8x, one country, one day): SA 2025-07-21, 2026-09-15/16; AE 2024-11-22, 2024-12-09, 2025-08-12, 2025-10-24, 2026-06-26; claims 2025-05-08, 2025-09-03/09, 2025-11-19, 2026-04-07, 2026-05-11 [T20, T22].

- **Gender × occasion segment** [VALIDATED T22, T27]. Since Jul 2025 the baseline female share is: AE gift claims 26.8% (3,807 / 14,187 with gender known), SA gift claims 9.7% (976 / 10,070), AE signups 23.3%, SA signups 9.0%. **AE gift-claim spikes run at 42–62% female, about twice the AE baseline.** SA Ramadan spikes run at 4–7% female, below the SA baseline. So AE spike-day recipients are a distinct, female-heavy audience, which fits corporate or women-targeted gifting [inferred]. **Mother's Day (21 Mar 2026) shows no signup lift and no female shift** (SA 402, AE 238; 13.5% female, against 9–18% that week) [T21]. A Mother's Day campaign therefore has to target *senders* (purchasers, NEEDS-GRANT on orders `order_order.user_gender` and `order_orderlinepersonalisedetail.occasion_code`), not new signups.
- The profile's OTP resend spike (Sep 22–23: sign_up resends at 25.6% and 20.0%, against a 7–12% baseline) falls in the same window. The peak campaign days are also the worst OTP days, so a campaign loses more signups exactly when it matters (quantified in H6). [profile B6, T19]
- Occasion data exists in the catalog but not as a calendar. ecomweb `brands_occasion` has 55 rows, `brands_brandoccasion` 21 and `brands_brandoccasion_brands` 142. **`configurations_upcomingoccasion` (occasion_date, per country) is physically empty (0 heap bytes)** (T13). Orders line personalisation carries `occasion_code`, `greeting_code`, `delivery_date` and `is_reminder_added` on 496,737 order lines (est.) (T12). [STRUCTURAL] The table above is therefore the seed for F5 until those are granted.

### I5. The identity service sends only transactional messages. Lifecycle marketing lives elsewhere [VALIDATED T2]
- Email templates (7 rows): `twofactor_emails` EN/AR, `sec_identity_added` EN/AR, `sec_identity_removed` EN/AR, and **`password_expiry_warning` in EN only, with no Arabic template**. WhatsApp: one `account_verification` template (authentication category), EN and AR. Template codes are 8-character ids (`ME…` for email, `WAT…` for WhatsApp), which points to an external mail-engine / WhatsApp template registry [inferred]. None of these is a marketing or lifecycle message. [T2]
- Orders and ecomweb each hold 6 email-template rows and emapi holds 1 heap page of them (T13, profiles) [STRUCTURAL]. Which lifecycle emails exist is NEEDS-GRANT (`email_type`, `language_id`, `is_active`).
- There are no send, delivery, open or click tables in any of the four DBs. `whatsapp_delivery` is never true [profile]. The send-side truth is `ygag_mailengine_aps_db` / `ygag_smsengine_db` (by name only).

### I6. There is no consent model in reach, so the audience cannot yet be filtered to "may be marketed to" [VALIDATED T1 for users; STRUCTURAL T12/T13 for the others]
- `ygag_ecom_users_db` has **no column** matching marketing / consent / subscribe / newsletter / opt-in / DND (T1).
- The only opt-in table anywhere is ecomweb `configurations_emailsubscription` (32 kB heap, never analyzed: at most a few hundred rows) [STRUCTURAL T13].
- Suppression is partly computable today [VALIDATED T11, profile C8]:
  - **5,544 live users** have an email on one of the 7 `users_promotionaldomainblacklist` entries. The entries are uppercase labels with no TLD, created 2026-04, and I matched them as the first label of the email domain. That covers 10 distinct full domains, and 455 of the users joined in 2026.
  - **3,316 live users** are on an actively blacklisted domain. This is an exact count (the profile's 5% sample estimated about 2.7k).
  - **903 live users** are blacklisted by email or mobile.

### I7. "Dormant" cannot be defined from login data. Only legacy-tenure and shell cohorts can [VALIDATED T5, T14]
- Only about 1.4–2.2% of every pre-July cohort received a login token in the 2.5 months of token history: linked legacy 1,220 / 56,234; native pre-2025 4,731 / 330,710; native 2025–Jul 2026 7,785 / 428,480 [T5]. App tokens live 548 days, and 98% of new signups get a token within an hour (T14). So "no new token" mostly means "still logged in", not "dormant".
- Dormancy must be defined on **last purchase** (orders, NEEDS-GRANT). The one dormancy signal that is ready now is the **legacy lapsed cohort**: 56,234 live *linked* legacy customers with a frozen legacy `last_login` (99.95% before 2024) and a pre-migration tenure back to 2012 [profile X34].
- **1,557 shell accounts** (created by the migration and never used on the legacy side) **now hold new-platform tokens** [T5]. Legacy customers are coming back into accounts that were created for them. That is a "welcome back" trigger.

### I8. Offers and promo codes: one live mechanism, three copies, three different "usage" numbers [STRUCTURAL; cross-db §2.3, emapi, orders-funnel]
- Oscar vouchers and discounts are physically empty. The live mechanism is **Plus Offers**: 378 `plusoffer` rows, replicated in orders, ecomweb and emapi (56–57 of 59 columns shared). There are 41 / 40 / 72 promo codes in the three DBs. Redemption shows up in `order_line.is_offer_applied` + `offer_code` = `plusoffer.code`.
- There are three "usage" views: `order_line.offer_code` (orders), `brands_plusoffer.usage_count` (emapi only), and `users_useravailedoffer` (emapi, 6,487 est.; no amount, order or UNIQUE(user, offer); `plus_offer_id` nullable). A fourth, the `ygag_plusoffers_db` ledger, is 0/49 readable.
- `brands_offerpromocode` has **no UNIQUE on promo_code and no user_id / redeemed_at**, so a code cannot be traced to a user in emapi.
- `brands_hasofferbrands` (the "brand has an offer" badge table) is rebuilt by a sync job. Its reltuples moved 49,787 → 40,079 with pages unchanged, so it is not a stable history.
- Offers are on the hot path: 13.2M index scans on orders `offer_plusoffer`, and 1.7M brand-keyed lookups on ecomweb `brands_plusoffer` [profile]. Customers see offers constantly. Whether offers convert is NEEDS-GRANT.

### I9. Personalisation is widely used, and it is the richest trigger seed [STRUCTURAL; orders profiles]
- About 31–35% of basket and order lines carry a personalise detail: 553,383 basket and 496,737 order rows (est.) with `delivery_type`, `delivery_date` / `delivery_time` / `delivery_time_zone` (local wall-clock), `greeting_code`, `occasion_code` and **`is_reminder_added`** (T12).
- `is_reminder_added` is the customer's own opt-in to be reminded of this occasion. With `occasion_code` and `delivery_date`, it gives a consented **"same occasion, next year"** trigger (NEEDS-GRANT).
- `personalization_detail` (94,394 est.) covers only about 19% of personalised order lines, a newer service or partial rollout. Its update log runs at about 1.37 updates per detail, which suggests post-purchase edits. Do not use it as the personalisation denominator.
- Browse and interest signals: emapi `brands_favouritebrand` (19,821 est., UNIQUE(user, brand)) and ecomweb `configurations_lastviewedbrand` (59,921 est., keyed by username, not unique per brand). There is no clickstream or search log in any DB.

### I10. Referrals: there is no referral data, but the gift-claim chain is a de facto referral graph [VALIDATED T8, T24b; STRUCTURAL T25]
- **Nothing in reach records a referral.** users has no referral / invite / UTM / affiliate / campaign column (T1, T25). In orders, the only sender→recipient table, `communication_notification(sender_id, recipient_id)`, is Oscar's built-in notification table and is **physically empty (0 bytes)** (T25). `user_tip_tip(sender_id, receiver_phone_number)` is a small (344 kB heap) person-to-person tipping table.
- **The users DB sees the recipient but not the sender.** Every one of the 59,596 `secondary_email_added_via_gift` rows has `actor_id = user_id` (the recipient acted for themself) [VALIDATED T24b]. Only `comment` holds anything about the gift, and it holds the recipient email (PII, never selected).
- **So the proxy referral metric is "gift-acquired signup"**: an account created no more than 1 day before its first gift claim. It is ready now: 26,737 users in total, 8,170 in 2026 (T8). It measures "gifting brought in a new customer". It cannot say *who* referred them.
- **Attributing the referral to a sender** needs orders: `order_orderlinepersonalisedetail.email_address / phone_number` (the recipient contact on the gift line), linked through `order_line.order_id` to `order_order.user_id` (the sender). Exposed only as `md5(lower(trim(email_address)))` and `md5(phone_number)`, and matched to the same hash of `users_user.email` / `phone_number` inside atlas, it gives sender → recipient-signup edges without raw PII [NEEDS-GRANT]. With it, atlas can compute a viral coefficient (gift-acquired signups per purchasing sender per month), top referring senders by count (pseudonymous), and second-generation gifting (recipient becomes a sender).
- **A true referral programme would need a new source**: a referral code or invite link per user, a `referred_by` key written at signup, and a reward ledger. None exists in the four DBs.

### I11. Send-time windows: SA is an evening market, AE a daytime one [VALIDATED T23]
Local time (SA = UTC+3, AE = UTC+4), 13 weeks Jun 29 → Sep 27 2026 for signups and gift claims, 31 days for phone OTP requests:

| Series | Local 00–08 | 09–15 | 16–23 | Peak hour |
|---|---|---|---|---|
| SA signups (31,690) | 20.4% | 33.0% | **46.5%** | 16h (still 1,241 at 00h) |
| AE signups (23,201) | 12.7% | 43.5% | 43.7% | 15h (flat 11–18h) |
| SA gift claims (2,051) | 13.3% | 40.9% | **45.9%** | 16h |
| AE gift claims (2,999) | 12.2% | **49.5%** | 38.2% | 15h |
| Phone OTP requests | SA peaks 16h (1,061), AE is flat 11–19h (526–605) | | | |

- Day of week (signups, same 13 weeks, local date): SA is highest Tue–Thu (5,214–5,775) and lowest Sat (3,324). AE is flatter (2,678 Sun → 3,844 Fri). Caveat: the Sep 22–24 push (Tue–Thu) inflates SA mid-week.
- Implications [inferred]: SA triggers (birthday, gift nudges) send in 16:00–22:00 local and are still acceptable up to midnight. AE triggers send 10:00–18:00, and AE gift-recipient nudges belong in working hours, which fits the corporate-gifting reading in I4. OTP rescue sends go out within the hour, not batched, because the OTP peak and the signup peak coincide.
- This is when people *act*, not when they open. Open-time optimisation needs mailengine open events (F15).

### I12. Trigger overlap is small but real, so atlas needs a frequency cap and a priority order [VALIDATED T24]
For the next 30 days (birthday) and the last 30 days (gift claim, new signup), with welcome-back = a migrated (linked or shell) account that holds a new-platform token:
- 54,243 live users qualify for at least one of: birthday in the next 30 days (26,835), gift claim in the last 30 days (1,850), welcome-back (2,777), new signup in the last 30 days (24,859).
- **2,039 (3.8%) qualify for two or more**: gift claim + new signup 1,004 (by construction, these are the gift-acquired signups); birthday + new signup 911; birthday + gift claim + new signup 39; birthday + welcome-back 34; gift claim + welcome-back 32; birthday + gift claim 19.
- OTP-rescue audiences are unregistered, so they cannot overlap with these user triggers. They can overlap with each other (a recipient who fails on email, then on phone), so dedupe on the recipient hash.
- **Proposed governance** [design, not data]: a registry-level `trigger_priority` (for example OTP rescue > finish-your-account > gift-recipient nudge > birthday > welcome-back > first-purchase > occasion broadcast), a per-user cap (for example at most 2 lifecycle messages per rolling 7 days, and at most 1 per day), and a suppression window after any purchase once orders are granted. Atlas resolves every audience against the cap before export, logs which trigger won in the audit log, and reports "suppressed by cap" as a guard metric. Holdout assignment (§4) happens **before** the cap, so a capped user stays in their bucket and intent-to-treat is preserved.

---

## 2. Trigger computability matrix

| Trigger | Can atlas compute it today? | Backing data | What is missing |
|---|---|---|---|
| **Birthday (self-gift / "treat yourself")** | **Yes: audience, daily volume, geo, language proxy** | users `users_user.birthdate`, `date_joined`, `country_of_residence`, `is_deleted`; shell exclusion via `users_migratedtransactionlog` | consent (new source); purchase outcome (orders grant); send/open (mailengine) |
| **OTP-failure rescue** (never accepted) | **Yes: daily audience by channel, country prefix, language, resend count** | users `notifications_twofactorauth(+verification)`, `users_user.email/phone_number` (in-DB match only) | delivery receipts (smsengine / mailengine); 31-day retention means atlas must snapshot daily |
| **Finish-your-account** (accepted, not registered) | **Yes** | same as above | whether the step failed technically: no signup-step log |
| **Gift-recipient → first gift** | **Partly: audience yes, conversion no** | users `users_useridentityactivitylog` (`secondary_email_added_via_gift`), `users_user.date_joined` | orders: did the recipient buy (`order_order.user_id` via `users_userprofile.cognito_id`) |
| **Welcome-back (legacy / shell reactivating)** | **Yes: segment** | users migration log, `legacy_auth_code`, `users_cognitoissuedtokens` | purchase history (orders) |
| **First-purchase nudge** (signed up, no order in N days) | **No** | users signup + orders | NEEDS-GRANT orders `order_order(user_id, guest_id, date_placed, status)`, `users_userprofile(user_id, md5(cognito_id))` |
| **Abandoned basket** | **No** | orders `basket_basket`, `basket_line` | NEEDS-GRANT (status, date_created, owner/guest, line value); guest contact is PII, so a hashed flag only |
| **Dormant reactivation** | **No** (tokens cannot define dormancy, I7) | orders last `date_placed` per user | NEEDS-GRANT orders |
| **Occasion "remind me next year"** | **No** | orders `order_orderlinepersonalisedetail.occasion_code, delivery_date, is_reminder_added` | NEEDS-GRANT (non-PII columns only) |
| **Favourite brand got an offer** | **No** | emapi `brands_favouritebrand` × `brands_plusoffer` / `brands_plusoffer_happy_cards` | NEEDS-GRANT emapi (non-PII) + `md5(username)` on emapi users |
| **Browse abandonment (viewed, didn't buy)** | **No** | ecomweb `configurations_lastviewedbrand` × orders | NEEDS-GRANT ecomweb (`md5(username)`) + orders |
| **Offer claimed, not used** | **No** | emapi `users_useravailedoffer` × orders `order_line.offer_code` | NEEDS-GRANT both |
| **Promo code running out / expiring** (ops alert) | **No** | `plusoffer.promo_code_threshold, promo_code_end_date, is_unique_promo_code`, `offerpromocode.status` | NEEDS-GRANT (non-PII; `md5(promo_code)`) |
| **Marketing suppression** (fraud, promo-blocked domains) | **Yes** | users `core_blacklisteduserdetail`, `users_promotionaldomainblacklist` | orders `users_blacklisteduserdetail` (48.6k est.), which is a different list |
| **Send / open / click / DLR metrics** | **No** | — | **new sources**: `ygag_mailengine_aps_db`, `ygag_smsengine_db` |
| **Consent / channel preference** | **No** | — | **new source** (none of the 4 DBs; possibly mailengine or a CRM) |
| **Referral: gift-acquired signup** (proxy) | **Yes: count, trend, cohort** | users activity log + `users_user.date_joined` (I10) | the sender: orders personalise recipient hash → `order_order.user_id` (NEEDS-GRANT) |
| **Referral programme** (invite code, referred_by, reward) | **No** | — | **new source**: no referral table or column exists in any DB (I10) |
| **Send-time window per country** | **Yes: action-time histograms** | users `date_joined`, activity log, OTP `created_on` (I11) | open/click times (mailengine) |
| **Frequency cap / cross-trigger priority** | **Yes, for user triggers computable today** | derived from the trigger views above (I12) | purchase-based suppression (orders); actual sends (mailengine) |

---

## 3. Hypotheses (testable, for marketers / growth / product / ops)

| # | Hypothesis | Audience | Test design | Data | Evidence level |
|---|---|---|---|---|---|
| H1 | Email signup recipients who need 2 or more codes register at 56.8% against 82.7% for single-code recipients (T18). Offering a phone (WhatsApp/SMS) OTP after the first email resend raises the multi-code registration rate by at least 10 pp (to ≥ 67%), closing about 40% of the 25.9 pp gap. | product, growth | Metric: registration within 24 h, per recipient, by code count (1 / 2 / 3+) and channel, from the daily OTP snapshot. Experiment: 50/50 split on `hash(recipient)` among recipients who request a second email code. MDE: about 2,700 multi-code recipients a month split 50/50 detects about a 5.3 pp lift (80% power, α 0.05, base 57%), so one month is enough for 10 pp. | users OTP tables + `users_user` (ready); the split flag needs an app change | Gap VALIDATED (T18); the lift is untested |
| H2 | Phone signups from countries with no routing config fail OTP at 23.3% against 2.7% in SA/AE (8.6x) and 3.8% in other GCC (T16). The failure is delivery, not user error: adding routing configs (with a direct provider route) for US/Canada and the UK, which hold 619 of the 1,694 unconfigured recipients and 204 of their 395 failures, cuts their never-accepted rate to at most 10% within 4 weeks. | ops, product | Diff-in-diff by country prefix: US/CA + UK (treated) vs the other unconfigured countries (control), 4 weeks before and after. India (configured, 7.6%) is the benchmark that a config alone does not reach SA/AE levels. | users OTP (ready); smsengine delivery receipts by prefix to confirm the mechanism | Rates VALIDATED (T16, T17); cause NEEDS-GRANT (`ygag_smsengine_db` DLR status by prefix) |
| H3 | A birthday "treat yourself" message 3 days before the birthday lifts 14-day self-purchase (`is_buy_for_self`) by at least 2 pp against a 10% holdout. | marketers | Randomised 90/10 holdout on hash(username), stratified by country and signup year. Intent-to-treat on eligibility. Send day in the user's local date (I1). Outcome: orders with `is_buy_for_self=true` in [bday−3, bday+14]. | users birthdate (ready) + orders `order_order`, `order_orderlinequantitydetail.is_buy_for_self` (grant) + mailengine sends | NEEDS-GRANT (orders) |
| H4 | Gift-acquired signups (claimed a gift within 1 day of signup) are less likely than other signups to buy within 30 days, and a "send one back" nudge 48 h after the claim closes the gap. | growth | Cohort comparison of 30-day first-order rate, gift-acquired vs organic, same signup weeks. Then a holdout experiment on the nudge. | users activity log (ready) + orders first order per user (grant) | Weaker return signal VALIDATED (2.6% vs 4.4%, T9; a weak proxy, I7); purchase NEEDS-GRANT |
| H5 | Customers who ticked `is_reminder_added` repurchase for the same `occasion_code` within ±14 days of the anniversary at least 2x more than customers who didn't. A reminder 7 days before adds a further lift. | marketers | Observational: repurchase rate by reminder flag, controlled for occasion and country. Then a holdout on the reminder send. | orders personalise detail + orders (grant) | NEEDS-GRANT |
| H6 | On a peak day, OTP degradation costs about 20–25 signups per extra point of resend share. On Sep 22 2026 the sign_up recipient resend share was 15.6% against an 8.1% Sep 1–21 baseline (+7.5 pp), and 171 more recipients stayed unregistered than the baseline rate predicts (516 vs 345 expected): about 23 per point (T19). Across Sep 22–24 the excess was 164 unregistered recipients. | ops, growth | Replicate on the next 3 occasion peaks from the daily OTP snapshot: regress daily excess unregistered recipients on excess resend share, by channel and country. Control: the country without the occasion (AE on Saudi National Day). The hypothesis fails if the slope is below 10 per point, or if the interval includes 0. | users (ready) | Sep 22 estimate VALIDATED (T19, one day, n=1); the slope is untested. Recipients from Sep 22 have had 7 days to register, so a little late registration may still come in |
| H7 | Users who favourited a brand convert at least 3x more when that brand gets a Plus Offer than users who didn't favourite it. | marketers | Among users exposed to a new offer on brand B: favouriters vs non-favouriters, order with `offer_code` in 14 days. | emapi favouritebrand + plusoffer, orders order_line.offer_code (grant) | NEEDS-GRANT |
| H8 | Plus-offer claims (`useravailedoffer`) convert to an order with that `offer_code` less than 50% of the time, and the gap is concentrated in unique-promo-code offers that ran out of codes. | marketers, ops | Claim-to-redeem funnel per offer, split by `is_unique_promo_code`, available codes against `promo_code_threshold`. | emapi useravailedoffer, offerpromocode (md5); orders order_line (grant) | NEEDS-GRANT |
| H9 | Accounts that have a code accepted but never register (1,756 per 31 days on email, T18) register at 20% or more if emailed within 1 h with a "finish your account" deep link. | growth | Holdout 80/20 on hash(email) in-DB; outcome registered within 72 h. | users OTP + users_user (ready); send via mailengine | Audience VALIDATED (T18); lift untested |
| H10 | Legacy linked customers (56k, tenure back to 2012) have a higher first-order rate on the new platform after a "your account moved" message than native dormant users. | marketers | Cohort by `user_legacy_state` × tenure; holdout on the message. | users legacy dimension (ready) + orders (grant) | NEEDS-GRANT |
| H11 | 2FA account verification, where 1,208 of 3,555 resend chains (34.0%) never end with an accepted code (users profile §7 "Resend-chain friction", query B5 in its appendix), is where logged-in customers are lost at gift claim or checkout. Rescuing those chains within 10 min recovers orders. | product | Join 2FA chain failure day against order attempts (youpay) for the same user. | users OTP (ready) + orders/youpay (grant) | Failure rate VALIDATED (profile B5); the order impact NEEDS-GRANT (`order_order`, `youpayclient_youpayclienttransactiondata`) |
| H12 | Gift-acquired signups are the main referral channel: each purchasing sender brings in at least 0.05 new accounts a month through gifts, and senders whose recipient signed up gift again sooner than senders whose recipient did not. | growth, marketers | Build sender → recipient-signup edges from the orders recipient hash (I10). Metric: gift-acquired signups per active sender per month (viral coefficient); time to next gift, by whether the recipient signed up. | users (ready) + orders `order_orderlinepersonalisedetail` md5(email_address/phone_number), `order_line.order_id`, `order_order.user_id` (grant) | Proxy count VALIDATED (26,737, T8); the sender side NEEDS-GRANT |
| H13 | Sending SA lifecycle messages at 16:00–22:00 local and AE ones at 10:00–18:00 (the action peaks in I11) lifts 24-h action rate by at least 15% relative against a fixed 10:00 local send. | marketers | 50/50 randomised send-time test per country on hash(username), same message. Outcome: claim, signup completion or order within 24 h. | users (ready for claims and signups) + mailengine (send and open times) + orders (grant) | Action-time peaks VALIDATED (T23); the lift is untested |
| H14 | Users who qualify for 2 or more triggers in a week (3.8% of the eligible base, T24) show higher unsubscribe rates when all messages are sent than when a 2-per-week cap is applied, with no loss in 30-day outcome. | marketers, ops | Randomise capped vs uncapped among multi-trigger users. Outcomes: unsubscribe (mailengine), 30-day order (orders). | derived trigger views (ready) + mailengine + orders | Overlap VALIDATED (T24); effect NEEDS-GRANT / new source |

---

## 4. Campaign effectiveness measurement design (how atlas should measure "did it work")

With no attribution columns anywhere and no send logs yet, atlas must measure **eligibility-based, intent-to-treat** effects:

1. **Governed holdout assignment.** Atlas owns a deterministic `holdout_bucket = abs(hashtext(username || campaign_id)) % 100`, which is stable, needs no PII, and can be recomputed. A campaign declares its holdout % in the registry. Every trigger audience comes out already split into treated and holdout, and the split is logged in the audit log. Marketers never pick the control group by hand.
2. **Outcome windows are registry metadata** (for example birthday: [−3, +14] days; OTP rescue: 72 h). They are computed per user from the trigger timestamp, not calendar months.
3. **Incrementality = treated rate − holdout rate**, with a Wilson/Newcomb 95% interval and minimum-detectable-effect guidance, computed in the sandbox. Before a campaign runs, atlas reports the MDE for its audience size. For example, 26.8k birthdays a month with a 10% holdout detects about a 1.7 pp lift at a 10% base rate (80% power, α 0.05: SE = √(0.09 × (1/2,683 + 1/24,150)) ≈ 0.61 pp, × 2.8) [arithmetic, not data]. A single month is therefore under-powered for small lifts, so pool 2–3 months or use a 20% holdout.
4. **When there is no holdout** (occasion pushes, national campaigns): **difference-in-differences** against an unexposed geography (SA vs AE for Saudi National Day, T10) or against the same calendar window last year. The id-gap cutover in May 2025 makes year-on-year signup comparisons across that date invalid (profile §5).
5. **Guard metrics** on every campaign: OTP resend share, 2FA failure rate, blacklist adds (rule vs analyst) and unsubscribe rate (once mailengine arrives). A campaign that lifts signups while pushing OTP resends to 25% is flagged.
6. **Frequency cap after holdout.** Assign the holdout bucket first, then apply the cross-trigger cap (I12). A user suppressed by the cap stays in their bucket and is counted as treated-but-not-sent in the intent-to-treat readout.
7. **Provenance chip** on every campaign number: metric id, audience definition version, holdout %, outcome window, source tables, freshness (OTP snapshot date).

---

## 5. Atlas features

| id | Feature | Type | Backing plugin / tables | Readiness | Effort | Impact |
|---|---|---|---|---|---|---|
| F1 | **Birthday audience forecaster**: next 7/30/90 days of birthdays by country, signup cohort, language proxy, with shell and `01/01` default excluded and blacklist/promo-domain suppression applied | segment + snapshot metric | `ecom_users`: users_user, users_migratedtransactionlog, core_blacklisteduserdetail, users_promotionaldomainblacklist | ready-now | S | 5 |
| F2 | **Signup OTP rescue queue**: daily count of recipients who never got an accepted code (or had one accepted but never registered), by channel, country prefix, language and resend count. The alert fires when the rate is above baseline + 3σ. | alert_trigger + segment | `ecom_users`: notifications_twofactorauth(+verification), users_user (in-DB match, output counts or hashed keys only) | ready-now for the queue. The σ alert needs history: the tables keep only 31 days, and 21 clean pre-peak days (Sep 1–21) are the only baseline today, so for the first 6–8 weeks of snapshots the alert should use a fixed threshold (for example never-accepted share above 2x the Sep 1–21 rate of 6.3%, T19) and switch to baseline + 3σ once about 8 weeks of daily snapshots exist | M | 5 |
| F3 | **Signup funnel by channel and country**: requested → accepted → registered, per recipient | funnel | `ecom_users` OTP + users_user | ready-now | S | 4 |
| F4 | **Gift-recipient acquisition loop**: gift claims, share that created an account that day, their return rate, and (after the grant) their 30-day first order | metric + funnel | `ecom_users`: users_useridentityactivitylog, users_user, users_cognitoissuedtokens; later orders | ready-now (partial) / needs-grant | S | 5 |
| F5 | **Occasion impact analyst**: agentic sandbox run that detects signup, claim and OTP anomalies around occasion dates per country and runs the diff-in-diff against the control country and the same day last year | agentic_analysis | `ecom_users` (+ orders later); occasion calendar = registry seed file `occasions.yaml`, seeded from the I4 spike table (T20–T22: date, country, occasion label, source = `inferred-from-spike` until a marketer confirms it). `configurations_upcomingoccasion` replaces it once granted and populated | ready-now | M | 5 |
| F6 | **Legacy / welcome-back segment**: `user_legacy_state` × tenure × recently logged in | segment | `ecom_users` migration log, users_user, tokens | ready-now | S | 3 |
| F7 | **Marketing suppression list size**: blacklisted email/mobile, blacklisted domain, promo-blocked domain; as counts per campaign audience | segment + metric | `ecom_users` core blacklist, promo domain list | ready-now | S | 4 |
| F8 | **Holdout-governed campaign readout**: treated vs holdout with intervals, MDE, guard metrics | agentic_analysis + dashboard | any trigger segment + outcome metric (orders once granted) | needs-grant (outcomes) | L | 5 |
| F9 | **First-purchase nudge audience**: signed up N days ago, no order | segment + alert_trigger | `ecom_users` + orders `order_order`, `users_userprofile` | needs-grant | M | 5 |
| F10 | **Abandoned-basket trigger**: baskets with lines, not submitted after X h, registered owner, value bucket, brand | alert_trigger + funnel | orders `basket_basket`, `basket_line`, `basket_basketquantitydetail` | needs-grant | M | 5 |
| F11 | **Occasion anniversary reminder**: last year's personalised orders by `occasion_code` with `is_reminder_added`, due next N days | segment + alert_trigger | orders `order_orderlinepersonalisedetail`, `order_line`, `order_order` | needs-grant | M | 5 |
| F12 | **Plus-offer effectiveness board**: per offer, claims (emapi avails) → orders with `offer_code` → GMV, budget burn vs `budget_amount`, promo-code inventory vs threshold, `has_budget_exceeded` alerts | dashboard + breakdown + alert_trigger | orders `order_line`, `offer_plusoffer`, `offer_offerpromocode`; emapi `users_useravailedoffer`, `brands_plusoffer.usage_count` | needs-grant | M | 4 |
| F13 | **Favourite-brand × offer match**: users whose favourite brand just got an offer | segment | emapi `brands_favouritebrand`, `brands_plusoffer_happy_cards`, `brands_plusoffer` | needs-grant | S | 4 |
| F14 | **Dormant reactivation segment**: last order more than 180 days ago, last-order occasion and brand | segment | orders `order_order`, `order_line` | needs-grant | M | 4 |
| F15 | **Message delivery and engagement metrics**: sent / delivered / opened / clicked by template, channel and country; OTP delivery latency | metric + breakdown | `ygag_mailengine_aps_db`, `ygag_smsengine_db` (new plugins) | needs-new-source | L | 5 |
| F16 | **Template coverage checker**: every trigger's template present in EN and AR and active (flags `password_expiry_warning` AR missing today) | metric (snapshot) | `ecom_users` notifications_*template*; emapi/orders/ecomweb template tables (grant) | ready-now (users) / needs-grant | S | 2 |
| F17 | **Personalisation mix**: share of lines personalised, by occasion, greeting and delivery type (scheduled vs instant), and scheduled-send lead time | breakdown | orders personalise detail | needs-grant | S | 3 |
| F18 | **Record drill-down: "why is this user in this audience"**: rule trace for one pseudonymous user id (no PII) | record_drilldown | registry audience definitions | ready-now | M | 3 |
| F19 | **Gift-referral graph**: gift-acquired signups (ready now), then, after the grant, sender → recipient-signup edges, viral coefficient per month, second-generation gifting | metric + funnel | `ecom_users` activity log + users_user; later orders personalise recipient hash + `order_line`, `order_order` | ready-now (proxy) / needs-grant (sender) | M | 5 |
| F20 | **Send-time profile**: local hour-of-day and day-of-week of signups, gift claims and OTP requests per country, as a breakdown metric that each trigger's send window reads from | breakdown | `ecom_users` users_user, activity log, OTP tables | ready-now | S | 3 |
| F21 | **Trigger frequency governor**: registry `trigger_priority` + per-user cap, audience overlap report ("2,039 users qualify for 2+ triggers"), suppressed-by-cap guard metric, audit-logged winner per user | segment + metric | derived trigger views; orders (post-purchase suppression) later | ready-now (user triggers) | M | 4 |
| F22 | **Gender × occasion segment**: female share of gift claimers and signups by country on occasion days vs baseline, for cohorts since Jul 2025 where gender is about 100% captured | breakdown + segment | `ecom_users` users_user.gender, activity log; later orders `order_order.user_gender`, personalise `occasion_code` | ready-now (recipients) / needs-grant (senders) | S | 3 |

---

## 6. Plugin notes

**A. Extend the `ecom_users` plugin (readable now) with a `lifecycle` sub-area.**
- Entities: `user` (key `username`, never exposed raw in output; `user_legacy_state`, `signup_cohort`, `country`, `birthday_md` = derived month and day), `otp_chain` (derived: recipient hash, flow, channel, codes, accepted, registered, first_ts), `gift_claim` (activity row, derived `is_gift_driven_signup`), `suppression` (derived booleans).
- Allowlisted tables: `users_user` (column-restricted), `users_migratedtransactionlog` (user_reference, request_status, creation), `users_useridentityactivitylog` (activity, timestamp, user_id; **exclude `comment`, which holds the email**), `users_cognitoissuedtokens` (user_id, user_platform, created_on; exclude jti, token_hash, device_signature, request_meta except COUNTRY), `notifications_twofactorauth` (source, auth_type, language, created_on, delivery flags; email and phone used **only inside derived-view SQL**, never selected), `notifications_twofactorauthverification` (is_valid, reference_id_id), `core_blacklisteduserdetail` (type, source, is_removed, created_on; value only in-view), `users_promotionaldomainblacklist`, `notifications_*template*` and `notifications_communication*` (config).
- Derived views, which the connector should create or define as SQL CTEs in YAML rather than let the agent write:
  - `v_birthday`: `month`, `day`, `usable` (excludes `0000/01/01`, impossible dates, shell, deleted), `tz` (IANA zone from country, I1), `send_date_local` (29 Feb → 28 Feb in non-leap years).
  - `v_otp_recipient_31d`: `md5(lower(recipient))`, flow, channel, country prefix bucket (SA, AE, other GCC, IN, then top unconfigured countries by name, T16/T17), `routing_configured` flag, language of the first code, codes, any_valid, registered. One row per recipient, never per (recipient, language).
  - `v_gift_signup`: user_id, first_claim_ts, `gift_driven` (joined ≤ 1 d before). This is the referral proxy (I10).
  - `v_trigger_eligibility`: user_id, one boolean per trigger, `trigger_count`, `winning_trigger` after the priority and cap rules (I12).
  - `v_suppression`: user_id, `blacklisted_value`, `blacklisted_domain`, `promo_blocked_domain`.
- Snapshot job: OTP is purged at 31 days, so atlas needs a daily governed extract of `v_otp_recipient_31d` aggregates (not rows) to trend beyond a month.
- Metric flavours: snapshot (`birthdays_next_30d`, `suppressed_users`), range (`otp_rescue_audience`, `gift_driven_signups`), funnel (`signup_otp_funnel`), breakdown top-N (country prefix, language).

**B. New `campaigns` plugin (after grants) over orders + emapi, read-only.**
- Entities: `plus_offer` (key `code`; source of truth = orders `offer_plusoffer` for redemption joins and emapi `brands_plusoffer` for `usage_count`; never union the three copies), `promo_code` (md5 only), `offer_claim` (emapi avails, local `user_id` → `md5(username)`), `offer_redemption` (orders `order_line` where `is_offer_applied`), `personalised_line` (orders personalise detail, non-PII columns), `favourite_brand`, `recent_view` (ecomweb).
- PII exclusions: `promo_code` raw, recipient `phone_number` / `email_address` on personalise tables, `basket_basket.user_*`, `order_order.user_email/guest_email/user_name/user_phone/owner`, `personalization_detail.personalization_data`, all Kafka `data`.
- Every user key resolves to `md5(users_user.username)` inside its own DB (cross-db §6.1). Numeric ids are never joined across DBs.

**C. New `messaging` plugins (new sources): `mailengine`, `smsengine`.**
- Desired entities: `message_send` (template_code, channel, message_type, country prefix bucket, provider, sent_at, delivered_at, status, opened/clicked flags, hashed recipient), `template` (code ↔ `notifications_*template*.template_code` `ME…`/`WAT…`).
- These unblock delivery latency (which explains the OTP resends), the send → outcome join, and unsubscribe/consent.

---

## 7. Grants needed

| DB | Table | Columns (as a PII-safe view) | Unblocks |
|---|---|---|---|
| ygag_ecom_orders_db | `order_order` | id, user_id, guest_id (bool `is_guest`), date_placed, status, basket_id, platform, region_id, placed_country_id, language_code, user_gender, gift_create_event_triggered, currency, total_incl_tax, total_incl_tax_before_payment_in_reporting_currency, conversion_rate_reporting_currency (column names verified in pg_attribute, T25); **exclude user_email, guest_email, user_name, user_phone, owner, session_id, transaction_id, transaction_url** | F8–F12, F14, F19, F22, H3–H5, H7–H12 |
| ygag_ecom_orders_db | `order_line` | id, order_id, product_id, upc, is_offer_applied, offer_code, status, created_on | F12, H7, H8 |
| ygag_ecom_orders_db | `order_orderlinequantitydetail` | line_id, is_buy_for_self, delivery_method, denomination bucket | H3 |
| ygag_ecom_orders_db | `order_orderlinepersonalisedetail`, `basket_basketpersonalisedetail` | line_id, delivery_type, delivery_date, delivery_time_zone, greeting_code, occasion_code, is_reminder_added, created_on, plus **`md5(lower(trim(email_address)))` and `md5(phone_number)` as the recipient key only**; raw phone_number and email_address excluded | F11, F17, F19, H5, H12 |
| ygag_ecom_orders_db | `basket_basket`, `basket_line` | id, owner_id, is_guest flag, status, date_created, date_submitted, date_merged, platform; line: basket_id, product_id, quantity, price_incl_tax, date_created; **exclude user_email/user_name/user_phone** | F10 |
| ygag_ecom_orders_db | `users_userprofile` | user_id, md5(cognito_id) | all cross-DB user joins (G1) |
| ygag_ecom_orders_db | `offer_plusoffer`, `offer_plusoffer_happy_cards` | all columns (no PII) | F12 |
| ygag_ecom_orders_db | `user_tip_tip` | id, sender_id, created_on, status, platform, amount_in_aed, md5(receiver_phone_number); exclude extra | P2P gifting edges for F19 |
| ygag_ecom_orders_db | `offer_offerpromocode` | id, offer_id, brand_id, status, created_on, md5(promo_code) | F12, H8 |
| ygag_emapi_stores_db | `users_useravailedoffer`, `brands_favouritebrand`, `brands_plusoffer`, `brands_plusoffer_happy_cards`, `brands_occasion` | all columns (ids and dates) | F12, F13, H7, H8 |
| ygag_emapi_stores_db | `users_user` | id, md5(username), is_deleted, is_fraud, platform, app_version, date_joined | user resolution (G4) |
| ygag_emapi_stores_db | `notifications_emailtemplateconfiguration` | id, email_type, template_code, language_id, is_active (exclude to_emails) | F16 |
| ygag_ecomweb_stores_db | `configurations_lastviewedbrand` | md5(username), brand_id, store_id, created_on, modified_on | browse abandonment |
| ygag_ecomweb_stores_db | `configurations_emailsubscription` | id, platform_id, is_subscribed, created_on, modified_on, md5(lower(email_address)), jsonb keys of `extra` | consent baseline, attribution check |
| ygag_ecomweb_stores_db | `brands_occasion`, `brands_brandoccasion(_brands)`, `configurations_upcomingoccasion(_country)` | all (no PII) | occasion calendar seed |
| **new source** ygag_mailengine_aps_db | send / delivery / event log | template_code, channel, sent_at, status, delivered_at, opened_at, clicked_at, country bucket, md5(lower(recipient)) | F15, OTP latency, all campaign readouts |
| **new source** ygag_smsengine_db | SMS/WhatsApp send + DLR | message_type, provider, country prefix, sent_at, dlr_status, dlr_at, md5(recipient) | H2, F2 root cause |
| **new source** consent store (location unknown) | marketing opt-in per channel | md5(username), channel, opted_in, updated_at | legal gating of every marketing trigger |
| **new source** referral programme (does not exist yet) | invite / referral ledger | referrer md5(username), referee md5(username), code, created_at, reward_status | a true referral metric (I10) |
| ygag_plusoffers_db | offer ledger (per plusoffers profile) | offer code, user hash, redeemed_at, amount | reconcile `usage_count` vs `offer_code` vs avails |

PII-safe principle: all recipient identifiers become `md5(lower(trim(x)))` computed identically on every side. Raw contact data never leaves the DB. Atlas outputs audience **counts and definitions**. Activation (handing the audience to a CRM) is a separate governed export of hashed ids and needs its own approval. A plain md5 of an email or phone can be reversed by dictionary lookup, so it is pseudonymous, not anonymous. Prefer an HMAC with an atlas-held key applied identically in each view, and never output the hash itself; use it only as a join key.

---

## 8. Risks and data-quality traps

1. **Shell accounts pollute every lifecycle audience.** 105,501 live accounts that have never logged in, 48,920 of them with birthdays (T3). Exclude them by default via `user_legacy_state`.
2. **`birthdate` is `0000/DD/MM`, varchar.** Parse day before month. `0000/01/01` and an inflated day 1 are defaults. Capture doubled in Nov 2025 (T4), so "birthday coverage" trends are a form change, not behaviour.
3. **OTP retention is 31 days**, and `is_valid` is not a wrong-code counter: it means "not superseded". For sign_up and sign_in, several `true` codes can sit in one chain. Count chains or recipients, never true rows (profile C9).
4. **Tokens cannot define dormancy or engagement.** App tokens live 548 days, and web tokens are visible only from 2026-08-29 (T5, T14). About 67% of tokens are first logins right after signup.
5. **Signup counts are not comparable across May 2025** (id-gap cutover), and **`is_app_user` changed meaning in Aug 2024**. Both break year-on-year campaign comparisons.
6. **Three copies of Plus Offers, three usage numbers.** `usage_count` (emapi), `order_line.offer_code` (orders) and `useravailedoffer` (emapi, no UNIQUE, nullable offer) will disagree. Name the source in every metric.
7. **Promo codes: no UNIQUE, no user link.** Duplicates are possible, so use `md5(promo_code)` distinct counts.
8. **`hasofferbrands` is a churned sync table** (reltuples swinging by about 20%), not history. Never use it for "offer was live on date X". Use `plusoffer.start_date` / `end_date` / `is_active`.
9. **`personalization_detail` covers only about 19%** of personalised lines. Use the order-line personalise table as the denominator.
10. **Scheduled delivery is local wall-clock** (`delivery_date` + `delivery_time` + `delivery_time_zone`). Convert to UTC in the view, or anniversary triggers fire on the wrong day.
11. **Promotional domain list semantics are inferred.** Entries are uppercase labels with no TLD, and I matched them as the first domain label (5,544 users, T11). Confirm the matching rule with the owning team before using it as suppression.
12. **Two blacklists.** users has 8,760 rows and orders 48,646 (est.), and they are not replicas. Suppression from the users list alone under-suppresses.
13. **Bulk blacklist imports** (Jun and Aug 2026) and rule-generated entries (83%) make "suppressed users" jump without any change in behaviour.
14. **Occasion confounding.** Ramadan/Eid, Saudi National Day and AE spike days move signups 2–8.5x (T10, T20). Any campaign readout without a holdout or a control geography over-credits the campaign. Conversely, a spike is not proof of an occasion: Saudi National Day 2025 moved SA signups only about 1.5x (T21), and several AE spikes match no public holiday.
15. **`secondary_email_added_via_gift.comment` holds the recipient email.** It must never be selected. Use the activity type and user_id only.
16. **No attribution anywhere.** No UTM, referral or source columns exist in any DB (profiles, T25). The only referral proxy is the gift-acquired signup (I10). The only ways to measure a campaign are holdouts, eligibility-based intent-to-treat, or geo diff-in-diff.
17. **The gift-driven signup share has a moving denominator** (live table; 2026 signups taken from the profile snapshot). Recompute both sides in one query before publishing.
18. **Occasion labels in the seed calendar are inferred from dates.** A marketer must confirm each label (and whether a campaign ran) before it is used as a diff-in-diff anchor.
19. **Country buckets must name the configured countries.** "Non-GCC" or "other" buckets mixed GCC and India with truly unconfigured countries in the first draft of this analysis and understated their failure rate (13.6% vs 23.3%). The view should carry an explicit `routing_configured` flag.
20. **Per-recipient grouping.** OTP recipient metrics must group by recipient only. Grouping by (recipient, language) double-counts about 1% of recipients.
21. **US/Canada phone signups fail about half the time** (T17). Any campaign aimed at expatriates or at North American senders will look like a conversion failure until SMS delivery there is fixed.

---

## Appendix: SQL provenance (all run 2026-09-29 via `atlasq.sh`)

**T1: consent/notification columns in users** [`ygag_ecom_users_db`; VALIDATED catalog, 80 rows returned, none a consent column]
```sql
select table_name, column_name, data_type from information_schema.columns where table_schema='public'
 and (column_name ~* '(marketing|consent|subscri|newsletter|notif|opt_in|optin|promo|campaign|prefer|language|unsubscribe|dnd)'
  or table_name ~* '(notifications_|communication|template|promotional)') order by 1,2;
```
**T2: template and channel config** [users; VALIDATED]
```sql
select 'email', e.email_type, l.code, e.template_code, e.is_active::text, (jsonb keys of template_data) from notifications_emailtemplateconfiguration e left join core_language l on l.id=e.language_id
union all select 'wa', whatsapp_type||'/'||category, language, template_code, is_active::text, … from notifications_whatsapptemplateconfiguration
union all select 'chan', message_type, …, 'email='||email_communication||' sms='||sms_communication||' wa='||whatsapp_communication from notifications_communicationchannelconfig
union all select 'cc', message_type||'/'||channel, …, string_agg(country_code, ',') from notifications_communicationcountryconfigs group by message_type, channel, direct_delivery, resend_delivery
union all select 'ctry', channel, …, cardinality(countries)::text from notifications_communicationcountries;
-- email: twofactor EN/AR, sec_identity_added EN/AR, sec_identity_removed EN/AR, password_expiry_warning EN only; WA account_verification EN/AR;
-- channel config: 4 message types, all channels on; country configs: signin/whatsapp + signin/sms for AE,IN,SA,KW,QA,BH,OM; whatsapp 93 / sms 92 countries
```
**T3: birthday audience** [users; VALIDATED exact]
```sql
with shell as (select user_reference from users_migratedtransactionlog group by 1 having not bool_or(request_status)),
tok as (select distinct user_id from users_cognitoissuedtokens),
u as (select u.id, u.country_of_residence c,
  case when u.birthdate ~ '^\d{4}/\d{2}/\d{2}$' and substr(u.birthdate,9,2)::int between 1 and 12 and substr(u.birthdate,6,2)::int between 1 and 31 then 1 else 0 end bd_ok,
  case when u.birthdate ~ '^\d{4}/\d{2}/\d{2}$' then substr(u.birthdate,9,2)::int end bm, case when u.birthdate ~ '^\d{4}/\d{2}/\d{2}$' then substr(u.birthdate,6,2)::int end bdd,
  (u.birthdate='0000/01/01') jan1, (s.user_reference is not null) is_shell, (t.user_id is not null) has_tok
 from users_user u left join shell s on s.user_reference=u.username left join tok t on t.user_id=u.id where not u.is_deleted)
select count(*), count(*) filter (where not is_shell), count(*) filter (where bd_ok=1 and not jan1 and not is_shell),
 count(*) filter (where … and bm=10), count(*) filter (where … and ((bm=9 and bdd=30) or (bm=10 and bdd<=29))), … has_tok …, count(*) filter (where has_tok),
 count(*) filter (where has_tok and bd_ok=1 and not jan1), … c='SA', … c='AE', count(*) filter (where is_shell), count(*) filter (where is_shell and bd_ok=1) from u;
-- 974,197 | 868,696 | 303,223 | 27,525 (Oct) | 26,833 (next 30d) | 1,945 | 54,812 | 25,768 | SA 138,100 | AE 129,159 | shell 105,501 | shell_bd 48,920
```
**T4: birthday/gender capture by signup month** [users; VALIDATED exact]
```sql
select to_char(date_trunc('month',date_joined),'YYYY "m" MM'), count(*), count(*) filter (where birthdate ~ '^\d{4}/\d{2}/\d{2}$' and birthdate<>'0000/01/01'),
 count(*) filter (where is_app_user), count(*) filter (where is_app_user and birthdate ~ … and birthdate<>'0000/01/01'),
 count(*) filter (where coalesce(gender,'') in ('male','female')), count(*) filter (where birthdate='0000/01/01')
from users_user where date_joined >= '2025-07-01' group by date_trunc('month',date_joined) order by 1;
-- 2025-07 4,297/18,963 … 2025-10 4,665/21,925; 2025-11 9,889/24,649; 2025-12 14,439/28,186; 2026-09 11,608/23,903; gender known ≈100% every month
```
**T5: recent-login share by legacy state × cohort** [users; VALIDATED exact]
```sql
with m as (select user_reference, bool_or(request_status) rs from users_migratedtransactionlog group by 1),
tok as (select user_id from users_cognitoissuedtokens group by 1),
u as (select u.id, case when m.user_reference is null then 'native' when m.rs then 'linked' else 'shell' end st, u.date_joined dj, (t.user_id is not null) has_tok
 from users_user u left join m on m.user_reference=u.username left join tok t on t.user_id=u.id where not u.is_deleted)
select st, case when dj<'2025-01-01' then 'joined<2025' when dj<'2026-07-13' then '2025..Jul13-26' else 'since Jul13-26' end, count(*), count(*) filter (where has_tok) from u group by 1,2;
-- linked<2025 56,234 / 1,220; native<2025 330,710 / 4,731; native 2025–Jul13 428,480 / 7,785; native since Jul13 53,277 / 39,526; shell 105,501 / 1,557
```
**T6: email sign_up recipients by outcome × registration** [users; VALIDATED exact; hash join, counts only] **Superseded by T18**: it groups by (email, language) and double-counts about 1% of recipients.
```sql
with r as materialized (select lower(t.email) k, t.language lang, bool_or(v.is_valid) any_valid, count(*) codes
 from notifications_twofactorauth t join notifications_twofactorauthverification v on v.reference_id_id=t.id
 where t.source='sign_up' and t.auth_type='email' and coalesce(t.email,'')<>'' group by 1,2),
u as materialized (select lower(email) k from users_user where email is not null)
select r.any_valid, (u.k is not null) reg, count(*), count(*) filter (where codes>=2), count(*) filter (where lang='ar') from r left join u on u.k=r.k group by 1,2;
-- f/f 1,951 (729 multi, 492 ar) | f/t 185 | t/f 1,776 (462, 245) | t/t 13,267 (1,434, 2,737)
-- (a first version using correlated EXISTS on lower(email) timed out and was replaced by this hash join)
```
**T7: phone sign_up recipients by country prefix × outcome × registration** [users; VALIDATED exact] Its 'other' bucket mixes other GCC, India and unconfigured countries; **superseded by T16/T17** for country figures. Only the Arabic-share figures are still cited.
```sql
with r as materialized (select t.phone_number k, t.language lang, bool_or(v.is_valid) any_valid, count(*) codes,
  case when t.phone_number like '+966%' then 'SA' when t.phone_number like '+971%' then 'AE' else 'other' end cc
 from notifications_twofactorauth t join notifications_twofactorauthverification v on v.reference_id_id=t.id
 where t.source='sign_up' and t.auth_type<>'email' and coalesce(t.phone_number,'')<>'' group by 1,2,5),
u as materialized (select phone_number k from users_user where phone_number is not null)
select r.cc, r.any_valid, (u.k is not null), count(*), count(*) filter (where codes>=2), count(*) filter (where lang='ar') from r left join u on u.k=r.k group by 1,2,3;
-- AE f/f 231, t/f 70, t/t 8,238 (30 ar); SA f/f 384, f/t 22, t/f 116, t/t 13,645 (5,355 ar); other f/f 478 (155 multi), t/f 32, t/t 2,992
```
**T8: gift-claim users vs signup timing** [users; VALIDATED exact]
```sql
with a as (select l.user_id, l."timestamp" ts, u.date_joined dj, u.is_deleted del, row_number() over (partition by l.user_id order by l."timestamp") rn
 from users_useridentityactivitylog l join users_user u on u.id=l.user_id where l.activity='secondary_email_added_via_gift')
select to_char(date_trunc('year',ts),'YYYY'), count(*), count(distinct user_id), count(*) filter (where rn=1),
 count(*) filter (where rn=1 and ts>=dj and ts-dj<=interval '1 hour'), count(*) filter (where rn=1 and ts>=dj and ts-dj<=interval '1 day'),
 count(*) filter (where rn=1 and ts-dj>interval '30 days'), count(*) filter (where rn=1 and del) from a group by rollup(1);
-- 2024 14,280 users / 5,204 ≤1h / 5,789 ≤1d; 2025 27,476 / 11,532 / 12,778; 2026 17,740 / 7,258 / 8,170; total 59,496 / 23,994 / 26,737
```
**T9: returning-login rate, gift-driven vs other signups (cohort Jul 15 – Aug 28 2026)** [users; VALIDATED exact]
```sql
with g as (select distinct l.user_id from users_useridentityactivitylog l join users_user u on u.id=l.user_id
   where l.activity='secondary_email_added_via_gift' and l."timestamp" between u.date_joined and u.date_joined + interval '1 day'),
c as (select u.id, (g.user_id is not null) gift_signup, u.is_app_user app from users_user u left join g on g.user_id=u.id
   where u.date_joined >= '2026-07-15' and u.date_joined < '2026-08-29' and not u.is_deleted),
t as (select c.*, exists (select 1 from users_cognitoissuedtokens t join users_user uu on uu.id=t.user_id where t.user_id=c.id and t.created_on > uu.date_joined + interval '1 day') ret,
  exists (select 1 from users_cognitoissuedtokens t where t.user_id=c.id) anytok from c)
select gift_signup, app, count(*), count(*) filter (where anytok), count(*) filter (where ret) from t group by rollup(1,2);
-- gift & app 1,146 / 788 / 30 (2.6%); non-gift app 20,938 / 13,642 / 921 (4.4%); non-gift non-app 4,552 / 182 / 142 (web tokens purged before Aug 29)
```
**T10: daily signups by country around Sep 22–25** [users; VALIDATED exact]
```sql
with g as (select distinct user_id from users_useridentityactivitylog where activity='secondary_email_added_via_gift' and "timestamp">='2026-09-15')
select to_char(date_trunc('day',u.date_joined),'MM "d" DD'), count(*), count(*) filter (where country_of_residence='SA'), count(*) filter (where country_of_residence='AE'),
 count(*) filter (where country_of_residence not in ('SA','AE')), count(*) filter (where is_app_user), count(g.user_id), count(*) filter (where gender='female')
from users_user u left join g on g.user_id=u.id where u.date_joined >= '2026-09-15' group by date_trunc('day',u.date_joined) order by 1;
-- SA Sep15–21: 668,621,425,350,257,315,465 (avg 443); Sep22–24: 1,171, 961, 1,159; AE avg 258 vs 352/414/345; gift claimers avg 29 vs 89/72/67
```
**T11: suppression by domain lists** [users; VALIDATED exact]
```sql
select length(domain), domain like '@%', domain like '%.%', domain ~ '[A-Z]', translate(lower(domain),…) mask, is_active, to_char(created_on,'YYYY "m" MM') from users_promotionaldomainblacklist;
-- 7 rows, 3–6 chars, uppercase, no dot, active, created 2026-04
with d as materialized (select lower(domain) dom from users_promotionaldomainblacklist where is_active),
u as materialized (select lower(split_part(split_part(email,'@',2),'.',1)) lbl, lower(split_part(email,'@',2)) full_dom, is_deleted, date_joined from users_user where email like '%@%')
select d.dom is not null, count(*) filter (where not u.is_deleted), count(*) filter (where not u.is_deleted and u.date_joined>='2026-01-01'), count(distinct u.full_dom) from u left join d on d.dom=u.lbl group by 1;
-- matched: 5,544 live, 455 in 2026, 10 full domains (exact-domain match returned 0)
with bd as materialized (select distinct lower(value) dom from core_blacklisteduserdetail where type='user_domain' and not is_removed),
u as materialized (select lower(split_part(email,'@',2)) dom, is_deleted, date_joined from users_user where email like '%@%')
select count(*) filter (where u.dom in (select dom from bd) and not is_deleted), count(*) filter (where … and date_joined>='2026-01-01') from u;   -- 3,316 | 487
```
**T12: trigger-relevant columns in blocked DBs** [orders, ecomweb, emapi; STRUCTURAL catalog]
```sql
select c.relname, a.attname, format_type(a.atttypid,a.atttypmod), c.reltuples::bigint from pg_class c join pg_attribute a on a.attrelid=c.oid and a.attnum>0 and not a.attisdropped
where c.relnamespace='public'::regnamespace and c.relkind='r'
 and a.attname ~* '(remind|birth|anniver|occasion|consent|marketing|subscri|unsubscr|push|fcm|device_token|notif|newsletter|opt_in|is_promo|abandon|recommend|segment|campaign|greeting|interest|schedule|delivery_date|delivery_type)';
-- orders: basket/order personalise detail (delivery_date, delivery_type, greeting_code, occasion_code, is_reminder_added); ecomweb: emailsubscription.is_subscribed,
-- upcomingoccasion(occasion_date,…), brandoccasion, aigreetingmessages.occasion, cognitouser.birthdate; emapi: shopcategory.is_interest, users_user.birthdate. No consent/push-token columns anywhere.
```
**T13: sizes of occasion, subscription, template, merge tables** [ecomweb, orders; STRUCTURAL]
```sql
select relname, reltuples::bigint, relpages, pg_relation_size(oid), pg_indexes_size(oid) from pg_class where relnamespace='public'::regnamespace and relname in (…);
-- ecomweb: upcomingoccasion 0 B heap, upcomingoccasion_country 0 B, emailsubscription 32,768 B (never analyzed), brands_occasion 55, brandoccasion 21, lastviewedbrand 59,921, email templates 6
-- orders: personalization_detail 94,394 (178.6 MB heap), users_guestuser 82,502, users_mergeduser 33 pages, basket_mergedbasket 10 pages, offer_plusoffer 378, offer_offerpromocode 41, email templates 6, catalogue_productrecommendation 0 B
```
**T14: post-signup token coverage, Sep 1–21 2026 cohort** [users; VALIDATED exact]
```sql
with u as (select u.id, u.is_app_user app, (select min(t.created_on) from users_cognitoissuedtokens t where t.user_id=u.id) ft,
  (select count(*) from users_cognitoissuedtokens t where t.user_id=u.id and t.created_on > u.date_joined + interval '1 day') ret, u.date_joined dj
 from users_user u where u.date_joined >= '2026-09-01' and u.date_joined < '2026-09-22' and not u.is_deleted)
select app, count(*), count(ft), count(*) filter (where ft-dj<=interval '1 hour'), count(*) filter (where ret>0) from u group by rollup(1);
-- all 14,325 / 14,074 / 13,936 / 480; web (non-app) 2,786 / 2,723 / 2,711 / 102; app 11,539 / 11,351 / 11,225 / 378
```
**T15: figures reused from profiles** (SQL in their appendices): users B5/B6/C1/C8/C9, cross-db X25/X34/X30, emapi Q14–Q31, orders-funnel Q17/Q20/Q26/Q29, orders-customer-catalog Q24, ecomweb A9/A14.

### Revision queries (critic pass 1, run 2026-09-29 via `atlasq.sh`)

**T16: phone sign_up recipients by corrected country bucket** [users; VALIDATED exact; in-DB join, counts only]
```sql
with r as materialized (select t.phone_number k, bool_or(v.is_valid) any_valid, count(*) codes,
  case when t.phone_number like '+966%' then 'SA' when t.phone_number like '+971%' then 'AE'
       when t.phone_number ~ '^\+(965|974|973|968)' then 'GCC_other' when t.phone_number like '+91%' then 'IN' else 'unconfigured' end cc
 from notifications_twofactorauth t join notifications_twofactorauthverification v on v.reference_id_id=t.id
 where t.source='sign_up' and t.auth_type<>'email' and coalesce(t.phone_number,'')<>'' group by 1),
u as materialized (select distinct phone_number k from users_user where phone_number is not null)
select r.cc, count(*), count(*) filter (where not any_valid and u.k is null) ff_unreg, count(*) filter (where any_valid and u.k is null) tf_unreg,
 count(*) filter (where u.k is not null) reg, count(*) filter (where codes>=2) multi, count(*) filter (where codes>=2 and not any_valid and u.k is null) ff_multi
from r left join u on u.k=r.k group by 1;
-- AE 8,547 / 231 / 70 / 8,246 | GCC_other 1,467 / 56 / 13 / 1,398 | IN 341 / 26 / 9 / 306 | SA 14,137 / 380 / 116 / 13,641 | unconfigured 1,694 / 395 / 10 / 1,289 (multi 210, ff_multi 141)
```
**T17: unconfigured countries by country code, with trunk-zero check** [users; VALIDATED exact]
```sql
-- same r/u CTEs as T16, restricted to t.phone_number !~ '^\+(966|971|965|974|973|968|91)', with
--   cc = case on '^\+44' UK, '^\+20' EG, '^\+92' PK, '^\+962' JO, '^\+964' IQ, '^\+961' LB, '^\+967' YE, '^\+61' AU, '^\+1' US_CA, '^\+7' RU_KZ, '^\+49' DE, '^\+39' IT, '^\+63' PH, '^\+880' BD, else rest
--   trunk0 = t.phone_number ~ '^\+(44|20|92|61|49|39|63|880|962|964|961|967|1|7)0'
select cc, count(*), count(*) filter (where not any_valid and u.k is null), count(*) filter (where u.k is not null), count(*) filter (where trunk0), count(*) filter (where trunk0 and not any_valid and u.k is null)
from r left join u on u.k=r.k group by 1 order by 2 desc;
-- UK 352/71/281 (trunk0 50/4); EG 325/34/288 (122/6); rest 295/66/227; US_CA 267/133/133; RU_KZ 125/31/94; PK 65/16/48 (10/3); AU 57/11/44 (22/4);
-- JO 52/5/47; IQ 36/1/35; DE 26/4/22; YE 25/5/20; PH 24/6/18; LB 23/5/18; IT 23/8/14
```
**T18: email sign_up recipients, one row per recipient, language of the first code** [users; VALIDATED exact; replaces T6]
```sql
with r as materialized (select lower(t.email) k, (array_agg(t.language order by t.created_on))[1] lang, bool_or(v.is_valid) any_valid, count(*) codes
 from notifications_twofactorauth t join notifications_twofactorauthverification v on v.reference_id_id=t.id
 where t.source='sign_up' and t.auth_type='email' and coalesce(t.email,'')<>'' group by 1),
u as materialized (select distinct lower(email) k from users_user where email is not null)
select any_valid, (u.k is not null) reg, case when codes=1 then '1' when codes=2 then '2' else '3+' end cb, count(*), count(*) filter (where lang='ar')
from r left join u on u.k=r.k group by rollup(1,2,3);
-- total 16,996 (ar 3,427)
-- f/f: 1 code 1,185 | 2 403 | 3+ 300 | all 1,888 (ar 454)      f/t: 58 | 27 | 21 | 106 (ar 13)
-- t/f: 1,287 | 267 | 202 | 1,756 (ar 242)                       t/t: 11,754 | 955 | 537 | 13,246 (ar 2,718)
-- => 1 code: 14,284 recipients, 11,812 registered (82.7%); 2+: 2,712, 1,540 registered (56.8%); 2: 59.4%; 3+: 52.6%
```
**T19: daily sign_up recipients (email + phone), by day of first code** [users; VALIDATED exact]
```sql
with r as materialized (select case when t.auth_type='email' then 'e:'||lower(t.email) else 'p:'||t.phone_number end k,
   min(t.created_on) first_ts, bool_or(v.is_valid) any_valid, count(*) codes
 from notifications_twofactorauth t join notifications_twofactorauthverification v on v.reference_id_id=t.id
 where t.source='sign_up' and coalesce(case when t.auth_type='email' then t.email else t.phone_number end,'')<>'' group by 1),
u as materialized (select 'e:'||lower(email) k from users_user where email is not null union select 'p:'||phone_number from users_user where phone_number is not null)
select to_char(date_trunc('day',first_ts),'MM "d" DD'), count(*), count(*) filter (where codes>=2), count(*) filter (where u.k is null), count(*) filter (where u.k is null and not any_valid)
from r left join u on u.k=r.k group by 1 order by 1;
-- Sep 1–21 total: 24,691 recipients, 2,002 multi (8.1%), 2,781 unregistered (11.3%), 1,564 never-accepted unregistered (6.3%)
-- Sep 22: 3,063 / 477 (15.6%) / 516 / 426;  Sep 23: 2,581 / 298 / 314 / 218;  Sep 24: 2,702 / 165 / 274 / 182
-- excess unregistered vs baseline rate: Sep 22 +171, Sep 23 +23, Sep 24 −30 (3-day +164); arithmetic done offline on these rows
```
**T20: historical signup spike days (non-migrated users)** [users; VALIDATED exact]
```sql
with m as materialized (select distinct user_reference from users_migratedtransactionlog),
d as (select date_trunc('day',u.date_joined)::date d, count(*) filter (where country_of_residence='SA') sa, count(*) filter (where country_of_residence='AE') ae, count(*) n, count(*) filter (where gender='female') fem
 from users_user u where u.date_joined >= '2024-10-01' and not exists (select 1 from m where m.user_reference=u.username) group by 1),
w as (select d, sa, ae, n, fem, avg(sa) over (order by d rows between 28 preceding and 1 preceding) sa_b, avg(ae) over (order by d rows between 28 preceding and 1 preceding) ae_b from d)
select to_char(d,'YYYY "y" MM "m" DD "d" Dy'), sa, round(sa_b), round(sa/nullif(sa_b,0),2), ae, round(ae_b), round(ae/nullif(ae_b,0),2), round(100.0*fem/n,1) from w
where d >= '2024-11-01' and (sa >= 1.8*sa_b or ae >= 1.8*ae_b) order by d;
-- 25 days returned; see the I4 table (e.g. 2025-03-26 SA 3,628 vs 427 = 8.5x; 2026-03-18 AE 756 vs 234 = 3.23x)
-- note: dates are formatted with literal text because the PII redactor masks bare ISO dates
```
**T21: signups around specific occasion windows** [users; VALIDATED exact]
```sql
-- same m CTE; days in 2025-03-07..13, 2025-09-16..26, 2025-11-27..12-05, 2026-03-14..24
select to_char(d,'YYYY "y" MM "m" DD "d" Dy'), sa, ae, gk, round(100.0*fem/nullif(gk,0),1) from s order by d;
-- Saudi National Day 2025-09-23: SA 479 (Sep 16–22: 280, 300, 392, 255, 246, 343, 388); Mother's Day 2026-03-21: SA 402, AE 238, 13.5% female
-- UAE National Day 2025-12-02: AE 305; AE rises Dec 3–5 (544, 688, 663)
```
**T22: historical gift-claim spike days** [users; VALIDATED exact]
```sql
with d as (select date_trunc('day',l."timestamp")::date d, count(*) n, count(*) filter (where u.country_of_residence='SA') sa, count(*) filter (where u.country_of_residence='AE') ae,
   count(*) filter (where u.gender='female') fem, count(*) filter (where u.gender in ('male','female')) gk
 from users_useridentityactivitylog l join users_user u on u.id=l.user_id where l.activity='secondary_email_added_via_gift' and l."timestamp">='2024-10-01' group by 1),
w as (select *, avg(n) over (order by d rows between 28 preceding and 1 preceding) nb, avg(sa) over (…) sab, avg(ae) over (…) aeb from d)
select to_char(d,'YYYY "y" MM "m" DD "d" Dy'), n, round(nb), round(n/nullif(nb,0),2), sa, round(sab), ae, round(aeb), round(100.0*fem/nullif(gk,0),1), gk from w
where d >= '2024-11-01' and n >= 2.0*nb order by d;
-- 31 days returned; e.g. 2025-03-26 837 vs 86 (9.74x, SA 774, 3.7% female); 2024-12-13 574 vs 119 (AE 527, 59.8% female); 2026-03-08 438 vs 57 (7.67x)
```
**T23: local hour-of-day and day-of-week** [users; VALIDATED exact]
```sql
-- s = signups, g = gift claims (both 2026-06-29 .. 2026-09-27), o = phone OTP (31 d); local = UTC +3 (SA) / +4 (AE)
with s as (select extract(hour from date_joined + case country_of_residence when 'SA' then interval '3 h' else interval '4 h' end)::int h, country_of_residence c
  from users_user where date_joined >= '2026-06-29' and date_joined < '2026-09-28' and country_of_residence in ('SA','AE')), g as (…), o as (…)
select h, (select count(*) from s where s.h=x.h and c='SA'), … from generate_series(0,23) x(h);
-- SA signups by hour 0..23: 1241,992,711,595,492,494,564,552,828,956,1189,1449,1509,1627,1825,1915,2069,2046,1972,1949,1743,1741,1654,1577
-- AE signups: 559,349,233,166,117,134,234,403,761,1102,1275,1511,1546,1521,1561,1587,1516,1493,1548,1393,1312,1157,956,767
-- window shares computed offline from these rows (see I11)
select to_char(date_joined + case country_of_residence when 'SA' then interval '3 h' else interval '4 h' end,'ID Dy'), count(*) filter (where country_of_residence='SA'), count(*) filter (where country_of_residence='AE')
from users_user where date_joined >= '2026-06-29' and date_joined < '2026-09-28' and country_of_residence in ('SA','AE') group by 1;
-- SA Mon 4,154 Tue 5,291 Wed 5,214 Thu 5,775 Fri 3,986 Sat 3,324 Sun 3,946; AE 3,229 3,445 3,446 3,611 3,844 2,948 2,678
```
**T24: lifecycle trigger overlap (30-day windows)** [users; VALIDATED exact]
```sql
with m as materialized (select user_reference, bool_or(request_status) rs from users_migratedtransactionlog group by 1),
tok as materialized (select distinct user_id from users_cognitoissuedtokens),
g as materialized (select distinct user_id from users_useridentityactivitylog where activity='secondary_email_added_via_gift' and "timestamp" >= '2026-08-30'),
u as materialized (select u.id,
  (m.user_reference is null or m.rs) and u.birthdate ~ '^0000/\d{2}/\d{2}$' and u.birthdate<>'0000/01/01'
    and ((substr(u.birthdate,9,2)='09' and substr(u.birthdate,6,2)='30') or (substr(u.birthdate,9,2)='10' and substr(u.birthdate,6,2)::int<=29)) b,
  (g.user_id is not null) gc, (m.user_reference is not null and t.user_id is not null) wb, (u.date_joined >= '2026-08-30') nw
 from users_user u left join m on m.user_reference=u.username left join tok t on t.user_id=u.id left join g on g.user_id=u.id where not u.is_deleted)
select b, gc, wb, nw, count(*) from u where b or gc or wb or nw group by rollup(1,2,3,4) having grouping(b)+grouping(gc)+grouping(wb)+grouping(nw) in (0,4);
-- total 54,243; b only 25,832; nw only 22,905; wb only 2,711; gc+nw 1,004; b+nw 911; gc only 756; b+gc+nw 39; b+wb 34; gc+wb 32; b+gc 19 (NULL birthdate treated as false)
```
**T24b: actor on gift-claim activity rows** [users; VALIDATED exact]
```sql
select case when actor_id is null then 'null' when actor_id=user_id then 'self' else 'other' end, count(*), count(distinct actor_id)
from users_useridentityactivitylog where activity='secondary_email_added_via_gift' group by 1;
-- self 59,596 (59,497 distinct) — no sender recorded
```
**T25: order_order columns and referral-like columns** [orders; STRUCTURAL catalog] and users catalog check
```sql
select c.relname, a.attname, format_type(a.atttypid,a.atttypmod) from pg_class c join pg_attribute a on a.attrelid=c.oid and a.attnum>0 and not a.attisdropped
where c.relnamespace='public'::regnamespace and c.relkind='r' and (c.relname='order_order' or a.attname ~* '(refer|sender|recipient|invit|utm|source|channel|affiliat|gifted_by|from_user|to_user)');
-- order_order has total_incl_tax, total_incl_tax_before_payment_in_reporting_currency, conversion_rate_reporting_currency, placed_country_id, user_gender,
--   gift_create_event_triggered, language_code (no total_incl_tax_in_reporting_currency); sender/recipient: communication_notification (0 B heap), user_tip_tip (344 kB)
-- users (same pattern + campaign): no referral/invite/utm column; users_useridentityactivitylog = id, activity, actor_id, comment, timestamp, user_id
```
**T26: usable birthdays by country, leap-day and impossible dates** [users; VALIDATED exact]
```sql
with shell as materialized (select user_reference from users_migratedtransactionlog group by 1 having not bool_or(request_status)),
u as materialized (select coalesce(u.country_of_residence,'(null)') c, u.birthdate b from users_user u left join shell s on s.user_reference=u.username
  where not u.is_deleted and s.user_reference is null and u.birthdate ~ '^\d{4}/\d{2}/\d{2}$' and u.birthdate<>'0000/01/01')
select c, count(*), count(*) filter (where b like '0000/29/02'), count(*) filter (where b ~ '^0000/(30|31)/02$' or b ~ '^0000/31/(04|06|09|11)$')
from u group by rollup(1) order by 2 desc limit 15;
-- total 303,341 (feb29 144, impossible 50); SA 138,161; AE 129,207; QA 8,726; KW 4,591; IN 3,307; EG 2,902; AM 2,426; GB 2,326; OM 2,265; BH 2,129; PH 968; MX 802; US 662
```
**T27: baseline female share since Jul 2025** [users; VALIDATED exact]
```sql
select 'claims', u.country_of_residence, count(*) filter (where u.gender in ('male','female')), count(*) filter (where u.gender='female')
from users_useridentityactivitylog l join users_user u on u.id=l.user_id where l.activity='secondary_email_added_via_gift' and l."timestamp" >= '2025-07-01' and u.country_of_residence in ('SA','AE') group by 1,2
union all select 'signups', country_of_residence, count(*) filter (where gender in ('male','female')), count(*) filter (where gender='female') from users_user where date_joined >= '2025-07-01' and country_of_residence in ('SA','AE') group by 1,2;
-- claims AE 3,807 / 14,187 (26.8%), SA 976 / 10,070 (9.7%); signups AE 30,389 / 130,589 (23.3%), SA 15,250 / 168,808 (9.0%)
```
