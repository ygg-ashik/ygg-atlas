# Theme: Purchase flows & friction

Built 2026-09-29 (queries 14:00–14:40 UTC) by the analytics strategist for ygg-atlas, from the seven critiqued profiles (`cross-db.md`, `users.md`, `orders-funnel.md`, `orders-customer-catalog.md`, `orders-integrations.md`, `ecomweb-stores.md`, `emapi-stores.md`) plus 13 new queries (T1–T13, appendix). All queries went through `atlasq.sh` (READ ONLY transaction, Aurora read replica, PII-redacted output).

**Evidence labels.** **VALIDATED** = a data query was run (T-queries below or a profile appendix; profile ids like `B5`, `X36` point to the appendix of `users.md` / `cross-db.md`). **STRUCTURAL** = catalog/metadata only (reltuples, column types, constraints, replica counters). **NEEDS-GRANT** = hypothesis that needs rows we cannot read; exact table.columns named. **[inferred]** = reasoning on top of a labelled fact.

**Access reality (unchanged today).** `ygag_ecom_users_db`: all 40 tables readable. `ygag_ecom_orders_db`, `ygag_ecomweb_stores_db`, `ygag_emapi_stores_db`: 0 readable tables (T10 re-confirms `has_table_privilege = false` on every funnel table). **Every basket / order / payment / gift-creation number below is STRUCTURAL.** The only data-backed purchase-adjacent flows are in the identity service: signup verification, and the **gift-recipient claim** step (a finding of this theme, §1.1).

---

## 0. The funnel and where each step is measurable today

| # | Step | Data home | Volume | Readiness |
|---|---|---|---|---|
| 1 | Browse (web "recently viewed", app favourites) | ecomweb `configurations_lastviewedbrand` (~59.9k), emapi `brands_favouritebrand` (~19.8k) | STRUCTURAL est | needs-grant; not a clickstream (no views/search logs anywhere, `analytics_*` empty) |
| 2 | Signup + OTP (a registered account is needed for non-guest checkout) | users `notifications_twofactorauth(+verification)`, `users_user` | 68k OTPs / 31 days; ~23k signups/month | **ready-now** (VALIDATED, T1, T7–T9) |
| 3 | Basket | orders `basket_basket` 3,046,354, `basket_line` 1,824,573, `basket_basketquantitydetail` 1,783,453, `basket_basketpersonalisedetail` 558,032 | STRUCTURAL extrap (T10) | needs-grant |
| 4 | Order | `order_order` 1,233,955; `order_line` 1,473,029; `order_orderlinepersonalisedetail` 513,432; `order_orderstatuschange` 1,209,949 | STRUCTURAL extrap (T10) | needs-grant |
| 5 | Payment | `youpayclient_youpayclienttransactiondata` 1,238,225 (100.3% of orders, cardinality per order unknown); `payment_paymentdetail` 769,729 (62.4%, 0..1 per order) | STRUCTURAL | needs-grant (+ dedup, P25) |
| 6 | Gift creation | `kafka_giftcreationlog` 3,256,033 (~2.64 events/order extrap) | STRUCTURAL | needs-grant |
| 7 | Delivery / notify | not in these four DBs (`ygag_mailengine_aps_db`, `ygag_smsengine_db`) | — | needs-new-source |
| 8 | **Recipient claim into an account** | users `2fa_account_verification` OTP → `users_useridentityactivitylog.secondary_email_added_via_gift` | 3,181 claim-OTP recipients / 31 d; ~1.5–2.8k claims / month | **ready-now** (VALIDATED, T2–T6, T12–T13) |
| 9 | Repeat purchase | `order_order(user_id, guest_id, date_placed)` (all indexed) | — | needs-grant (P35) |

---

## 1. Insights

### 1.1 `2fa_account_verification` is the gift-recipient claim step, and it fails for 1 in 4 recipients — VALIDATED

The users profile treated `2fa_account_verification` as generic 2FA ("worst flow, 34% of chains never accepted"). Joining its recipients to the identity tables shows what it actually is:

- Of 3,568 claim-OTP chains in the 31-day window, **3,518 go to an email that is not any user's primary email**; the other 50 go to accounts created less than a day earlier (T2). It is not a login or checkout 2FA.
- Of **3,181 distinct recipient emails**, **2,284 (72%) are now a secondary email** on some account and **1,868 (59%) were attached through `secondary_email_added_via_gift`**; 0 are blacklisted; only 4 also appear in sign_in OTPs (T3).
- Outcome by recipient (T4): **2,342 recipients got an accepted code; 1,853 of them (79%) then attached the email via a gift claim and 479 (20%) self-added it — together 99.6% of accepted recipients end with a linked email.** The **839 recipients (26.4%) who never got an accepted code attached it 0 times after the OTP.** The OTP is a hard gate on claiming.
- Time from first claim OTP to the claim grows with each resend (T4): median **30 s** with 1 code, **94 s** with 2, **162 s** with 3, **386 s** with 4, **8.1 h** with 5 or more.
- **[inferred]** So the claim step is: recipient opens the gift → enters an email to keep it in their account → gets an emailed code → the email is attached as a secondary identity. Resends (23.4% of chains need 2+ codes, T1) and non-acceptance (33.9% of chains, 26.4% of recipients) are **recipient-side delivery friction**, not buyer friction. It matters to marketers because the claim is the moment a recipient becomes a known account (§1.2).

### 1.2 About half of all gift claims create a brand-new account: gifts are an acquisition channel of ~4–5% of signups — VALIDATED

- Gift claims (`secondary_email_added_via_gift`) run **1,536–2,757 per month** (Jul 2025–Sep 2026), peaking Dec 2025 (2,757), Mar 2026 (2,624) and Apr 2026 (2,366) (T5). That is Ramadan/Eid and year-end gifting.
- **37–52% of claims land on an account created less than 1 day before the claim** (e.g. Sep 2026 893 of 1,746; Apr 2026 1,235 of 2,366) (T5). These are **gift-acquired signups**: 777–1,276 per month, **3.2–5.3% of all signups** (Mar 2026 960 / 29,608; Apr 2026 1,235 / 23,266; Sep 2026 893 / 23,785 using the users profile's monthly signups).
- 27–42% of claims go to accounts older than a year (existing customers receiving gifts; Apr 2026 26.7%, Sep 2025 41.7%).
- Claims are an **app flow**: 80% of claimers are `is_app_user` in Jul 2025, 92% in Sep 2026 (T5); in the Jul 15–Aug 28 2026 signup cohort, all 1,146 gift-acquired signups are app users (T6).
- Early engagement is weak but under-measured: in that cohort 2.6% of gift-acquired signups logged in again more than a day later vs 4.4% of other app signups (T6). **Caveat:** app tokens live 548 days, so an app user who stays logged in never issues a new token. This is a lower bound, not retention. Whether gift-acquired users **buy** is NEEDS-GRANT (H3).

### 1.3 A resend costs about a quarter of signups: completion falls from 82% to 59% on email, and to 33% for non-GCC phones — VALIDATED

- **Email sign_up, 1–26 Sep 2026** (T8): recipients who needed **1 code: 82.3% registered** (9,867 / 11,990); **2 codes: 58.7%** (833 / 1,420); **3–4: 51.1%**; **5+: 55.0%**.
- **Phone (WhatsApp+SMS) sign_up**, same window (T9): 1 code SA 97.1%, AE 96.9%, other GCC 95.8%, **non-GCC 83.3%**; with 2+ codes SA 76.8%, AE 80.6%, other GCC 84.1%, **non-GCC 32.5%** (49 / 151).
- Chain-level friction by channel (T1, 31 days): email sign_up chains need 2+ codes **13.9%** of the time and **16.0% never end accepted**; WhatsApp+SMS chains for SA/AE numbers need a resend only **2.2–2.7%** of the time with **3.3%** unaccepted; **non-GCC numbers 6.3% / 14.6%**. So the email leg of signup is the leaky one, about 5x worse than the GCC phone leg.
- Time to create the account after the first email code (T7): median **52 s** (p90 104 s) with 1 code, **259 s** with 2, **43.5 min** with 3+ codes, and **47% of 3+-code signups take more than an hour** (252 / 535). Resend chains turn a one-minute signup into an abandoned session that sometimes comes back later.
- **[inferred]** Registration is a gate before any non-guest purchase, so this is the top of the purchase funnel measurable today. Whether resend-affected signups buy less is NEEDS-GRANT (H1).

### 1.4 OTP retry storms are visible and dateable: Sep 22 claim-OTP volume was 10x normal for 2x the claims — VALIDATED

- Normal days (Sep 15–21, 26–28): **81–145 claim OTPs → 38–78 claims** (about 1.5–2.3 OTPs per claim) (T12).
- **Sep 22: 1,060 claim OTPs, only 140 valid, 100 claims** (10.6 OTPs per claim). Sep 23: 553 OTPs → 122 claims (4.5). Sep 24: 214 → 107 (2.0), back to normal (T12).
- It was broad, not one bot: on Sep 22, 459 recipients: 237 needed 1 code, 147 needed 2–3, **68 needed 4–10 (374 codes), 7 needed 11–50 (105 codes)**, across all 24 hours (T13).
- Signups were high on the same days (1,640 / 1,484 / 1,637 on Sep 22–24, about 2x baseline; users profile B6), and gift claims doubled (100–122/day). **[inferred]** A campaign drove both gift sends and signups, and email OTP delivery degraded on Sep 22–23. A ratio alert "OTPs per successful outcome" would have fired within hours (F3).

### 1.5 There is no checkout OTP in the readable data; purchase-time verification is card 3DS and brand-level mobile verification — STRUCTURAL

- The users OTP `source` vocabulary is sign_up, sign_in, 2fa_account_verification (claim, §1.1), and the two change-phone flows (users profile §4). None is a checkout step.
- Orders has no OTP/verification columns except `users_userprofile.is_email_verified / is_phone_number_verified`, `catalogue_product.require_mobile_verification` and youpay `verify_url` varchar(500) (T11). **[inferred]** Purchase-time friction is therefore (a) card 3DS via `verify_url` (a redirect URL, PII-classified, expose only as `has_verify_url`), and (b) brands flagged `require_mobile_verification` (also in emapi/ecomweb `brands_brand`, with `allow_any_country_mobile_verification`). The rates are NEEDS-GRANT.

### 1.6 The structural funnel: ~60% of baskets never become orders, but at least 40% of baskets are empty — STRUCTURAL

From T10 (extrapolated reltuples; the orders-funnel profile's Q20 gives the same):
- **3,046,354 baskets → 1,824,573 basket lines → 1,233,955 orders → 1,473,029 order lines.** 0.60 lines per basket, so **at least ~40% of baskets have no line** (session carts). The "3M baskets vs 1.2M orders = 59.5% abandonment" figure mixes empty session carts with real abandonment and **must not be published** (R1).
- **Personalisation is common:** 30.6% of basket lines (558,032) and 34.9% of order lines (513,432) have a personalise row (schedule, greeting, occasion, recipient channel). Personalised lines are a *larger* share of order lines than of basket lines, which hints that personalised gifts convert at least as well as plain ones **[inferred, ratio of estimates]**.
- **Payment has two records.** youpay 1,238,225 rows (100.3% of orders, no UNIQUE on `order_reference`, `order_history` jsonb holds attempts) and paymentdetail 769,729 (62.4%). Payment-failure and retry rates are unknowable until P25 dedups youpay.
- **Gift creation:** 3,256,033 events, 2.64 per order and 2.21 per line; unexplained (per unit, retries, or duplicates).
- **Status log:** 1,209,949 status changes, 0.98 per order. Do not build the funnel on it (orders-funnel §7.4).
- **Guests:** `users_guestuser` 82,502 est, `users_mergeduser` and `basket_mergedbasket` never analysed (33 and 10 pages). Guests are at most ~7% of orders if each guest ordered once **[inferred]**; guest checkout is gated by `order_giftactivationconfig.is_guest_enabled` and `core_siteconfig.is_guest_enabled` (T11).

### 1.7 Friction is encoded as config, so the causes of a blocked checkout are enumerable — STRUCTURAL

Orders holds a small, joinable set of purchase gates (T11; orders-funnel §7.1): `core_currencybasketlimit` (8 caps, one per currency), `catalogue_productdenominationrange` (11,376 min/max ranges), `catalogue_productdenomination` (22,404 presets with `is_default`), `catalogue_producthandlingfee` (939 fee rules), `core_unsupportedcountry` (geo-block), `payment_paymentmethod` (20 methods, `is_active`), `offer_plusoffer` promo limits (`promo_code_threshold`, `has_budget_exceeded`, `promo_code_end_date`), `users_blacklisteduserdetail` (48,646 est), and `django_admin_log` to date every change. **[inferred]** An agent that correlates a conversion drop with the config change that preceded it is buildable once granted (F15). The storefront reads these configs constantly: `payment_paymentmethod` 31,931 seq scans and `offer_plusoffer` 13.2M index scans on the replica (orders-funnel Q16); ecomweb `core_captchaconfigurations` 2.55M and `core_unsupportedcountry` 3,185 seq scans (ecomweb A14).

### 1.8 Currency / FX is a first-class friction dimension, but only current FX rates are kept — STRUCTURAL

Orders carry a cart currency, a gateway currency and a reporting currency, with snapshotted `conversion_rate_gateway_currency` / `conversion_rate_reporting_currency` on the order and `conversion_rate`, `conversion_rate_cart_currency`, `is_different_currency_denomination` on each line; `*_before_payment` / `*_before_pay` snapshots record the pre-payment amount (T11). `core_currencyexchangerate` (437 rows) keeps only the **current** rate per pair. **[inferred]** Cross-currency gifting (buyer pays in AED, gift denominated in SAR, etc.) is directly flaggable per line, and price drift between checkout and payment is measurable per order. Historical FX drift is not, unless atlas snapshots the rate table daily (P32).

### 1.9 Channel: app dominates identity activity; web is visible only from Aug 29 — VALIDATED

Since 2026-08-29: 35,579 users logged in, **25,589 app-only, 8,157 web-only, 1,830 both** (cross-db X36). 67% of Sep tokens are first logins right after signup (users C4). **[inferred]** Platform splits of purchase friction must come from `order_order.platform`, `basket_basket.platform`, youpay `platform` and `users_guestuser.platform` (NEEDS-GRANT). Tokens are a "recent login channel" flag only.

### 1.10 Blacklist enforcement at checkout is unverified — VALIDATED gap, NEEDS-GRANT outcome

903 live accounts match an active email/mobile blacklist entry, and 12 of them were issued 18 login tokens after being blacklisted (users C8). 1,298 orders→users blacklist events are stuck `in_progress` (cross-db X30). Orders keeps its own 48,646-entry block list (5.6x the users list). Whether blacklisted users still **complete purchases** needs `order_order(user_id, date_placed, status)` + `users_userprofile.cognito_id` (NEEDS-GRANT, V6).

---

## 2. Hypotheses (testable, for end users)

| id | Statement | Audience | Test | Data | Evidence |
|---|---|---|---|---|---|
| H1 | Users who need 2+ email OTP codes at signup are ≥25% less likely to place a first order within 7 days than 1-code signups (on top of the 82%→59% registration drop). | growth, product | Cohort of registered signups by codes (T8 logic) → `order_order` first `date_placed` within 7 d; compare rates; control for country and app/web. | users OTP tables (ready) + orders `order_order(user_id, date_placed, status)`, `users_userprofile(user_id, cognito_id)` | NEEDS-GRANT (first half VALIDATED) |
| H2 | Offering WhatsApp as the claim-OTP channel (instead of email) raises the recipient claim rate from ~74% of recipients toward the ~97% seen for GCC phone OTPs. | product, CRM | A/B on the claim flow: email vs WhatsApp code; metric = recipients with `secondary_email_added_via_gift` within 1 h / recipients with a claim OTP (T4 logic). | users DB only | VALIDATED baseline (T1, T4, T9); experiment needed |
| H3 | Gift-acquired signups (account created ≤1 day before a gift claim) make a first purchase within 60 days at a rate at least half that of organic signups; the recipient-to-buyer rate makes gifts measurable as an acquisition channel. | marketers, leadership | Cohort gift-acquired vs other signups by month → first order within 30/60/90 d. | users `users_useridentityactivitylog`, `users_user` (ready) + orders `order_order(user_id, date_placed, status)`, `users_userprofile.cognito_id` | NEEDS-GRANT |
| H4 | Non-GCC phone signups that need a resend complete only ~33% of the time; an email fallback after the first failed code lifts completion above 70%. | growth, product | Before/after or A/B on fallback; metric = registered / recipients by geo × codes (T9). | users DB only | VALIDATED baseline (T9) |
| H5 | Baskets whose value is within 10% of the currency cap (`core_currencybasketlimit`) convert at half the rate of other baskets, and baskets over the cap never convert. | product, ops | Sample baskets, sum lines per currency, compare with active cap; LEFT JOIN `order_order.basket_id` (P24b). | orders `basket_basket(id, date_created, status)`, `basket_line(basket_id, price_incl_tax, price_currency, quantity)`, `core_currencybasketlimit`, `core_currency`, `order_order(basket_id)` | NEEDS-GRANT |
| H6 | Lines that keep the pre-selected default denomination convert better than custom amounts; custom amounts outside `catalogue_productdenominationrange` are rejected and abandoned. | product, merchandising | Classify basket lines as default / other preset / custom / out-of-range (P36, P27b); conversion via `order_order.basket_id`. | `basket_basketquantitydetail(line_id, denomination, denomination_currency_id)`, `basket_line(product_id, basket_id)`, `catalogue_productdenomination`, `catalogue_productdenominationrange` | NEEDS-GRANT |
| H7 | Scheduled (future-dated) personalised gifts are placed ≥3 days before occasions and cluster before Ramadan/Eid; reminder-enabled lines (`is_reminder_added`) repeat the following year. | marketers | Lead-time distribution `delivery_date − date_placed` by occasion_code × month; next-year repeat by user. | `order_orderlinepersonalisedetail(line_id, delivery_date, delivery_type, occasion_code, greeting_code, is_reminder_added)`, `order_line(order_id)`, `order_order(user_id, date_placed)` | NEEDS-GRANT |
| H8 | Non-GCC cards decline 2–3x more than GCC cards on the same gateway, and ≥30% of declined orders are rescued by a retry within 30 min. | ops/risk, finance | youpay approval by `is_gcc_card × payment_gateway × card_issuer_country`; retry = later approved row for the same `order_reference` (after P25 dedup). | youpay `(order_reference, created_on, approved, payment_gateway, payment_method, is_gcc_card, card_issuer_country, response_summary→class)` | NEEDS-GRANT |
| H9 | Partial points redemption (`redeemed_amount > 0` and not `is_full_redemption`) has a lower approval rate than card-only payment. | loyalty, product | youpay approval by redemption mode × point_program (P20b). | youpay loyalty columns | NEEDS-GRANT |
| H10 | Guests who later register (`users_mergeduser`) have a 2x higher repeat-purchase rate than guests who never register; and guests whose basket did not merge (`basket_mergedbasket` missing) show cart-loss friction. | growth | P15c + P35 on guest cohorts. | `order_order(guest_id, user_id, date_placed)`, `users_mergeduser(guest_id, user_id, created_on)`, `basket_mergedbasket`, `users_guestuser(id, created_on, platform)` | NEEDS-GRANT |
| H11 | Cross-currency lines (`is_different_currency_denomination`) have lower basket→order conversion and higher decline rates than same-currency lines. | product, finance | Conversion and approval by the flag and currency pair. | `order_orderlinequantitydetail(is_different_currency_denomination, denomination_currency_id, reporting_currency)`, basket equivalents, youpay | NEEDS-GRANT |
| H12 | Brands with `require_mobile_verification` and no `allow_any_country_mobile_verification` convert worse for non-local buyers and generate more claim friction for recipients. | merchandising | Conversion by brand flag × `placed_country_id`. | `catalogue_product(id, require_mobile_verification)`, emapi `brands_brand(code, allow_any_country_mobile_verification)`, basket/order lines | NEEDS-GRANT |
| H13 | Days when claim OTPs per claim exceed 3 (as on Sep 22–23) cost ≥20% of that day's potential claims, and the lost recipients rarely come back. | ops, CRM | Alert on the ratio; compare recipients with failed OTP on storm days vs normal days for a claim in the next 7 days. | users DB only | VALIDATED signal (T12, T13) |
| H14 | Blacklisted-but-live users (903) keep placing orders after their blacklist date. | ops/risk | Orders by these users after `min(blacklist.created_on)`. | users (ready) + `order_order(user_id, date_placed, status)`, `users_userprofile(user_id, cognito_id)` | NEEDS-GRANT |
| H15 | A price change between checkout and payment (`total_incl_tax <> total_incl_tax_before_payment`) raises abandonment at the payment step. | product, finance | P10 share by currency and gateway, then approval rate. | `order_order(total_incl_tax, total_incl_tax_before_payment, currency, gateway_currency, status)` | NEEDS-GRANT |

---

## 3. Atlas features

| id | Name | Type | Plugin / tables | Readiness | Effort | Impact | Why it wows |
|---|---|---|---|---|---|---|---|
| F1 | **Gift-claim funnel** (claim OTP sent → accepted → email attached, with codes and median time) | funnel | `ecom_users`: `notifications_twofactorauth`, `…verification`, `users_useridentityactivitylog` | ready-now | S | 5 | First measurement of the recipient side of the business; 26% of recipients stuck at one step. |
| F2 | **Gift-acquired signups** (monthly count, share of all signups, app share) | metric (range) | `ecom_users`: `users_useridentityactivitylog`, `users_user` | ready-now | S | 5 | Shows gifting as an acquisition channel: ~800–1,300 new accounts a month. |
| F3 | **OTP retry-storm alert** (OTPs per successful outcome by flow, hourly, vs trailing 7-day baseline) | alert_trigger | `ecom_users` OTP tables + activity log + `users_user` | ready-now | S | 4 | Would have flagged Sep 22 within hours (10.6 OTPs per claim vs ~2). |
| F4 | **Signup verification funnel** by channel × country × codes, with completion time p50/p90 | funnel + breakdown | `ecom_users` OTP tables + `users_user` | ready-now (31-day window) | M | 4 | Quantifies what a resend costs (−24 pts) and where (email leg, non-GCC phones). |
| F5 | **Stuck-claim segment** (recipients with a failed claim OTP in the last N days and no claim since) — counts in atlas; activation list handed to CRM through a governed export, never raw emails in chat | segment | `ecom_users` | ready-now (count); export needs a policy | M | 4 | Recoverable recipients a CRM nudge can target. |
| F6 | **OTP snapshot job** (daily aggregate snapshot of chains, because OTP tables keep only ~31 days) | metric (snapshot) | `ecom_users` → atlas store | ready-now | S | 4 | Without it every OTP/claim trend dies after 31 days. |
| F7 | **Purchase funnel**: non-empty basket → order → approved payment (deduped) → gift event, by platform, guest/registered, country | funnel | `ecom_orders`: `basket_basket`, `basket_line`, `order_order`, youpay, `kafka_giftcreationlog` | needs-grant (+ extract, basket has no date index) | L | 5 | The core "where do we lose buyers" view; replaces the misleading 59.5%. |
| F8 | **Payment decline breakdown** (approval by gateway × method × GCC card × issuer country × decline class; retry rescue rate) | breakdown | `ecom_orders`: youpay view with `response_class` | needs-grant | M | 5 | Directly actionable by ops/finance (routing, gateway choice). |
| F9 | **Checkout-gate diagnostics** agent: for a period or brand, attribute non-converting baskets to cap, denomination range, blocked country, inactive payment method, exhausted promo, blacklist, mobile-verification brand, and date config changes from `django_admin_log` | agentic_analysis | `ecom_orders`: §1.7 config tables + basket/order + `django_admin_log(action_time, content_type_id, object_id, action_flag)` | needs-grant | L | 5 | "Why did conversion drop on Tuesday?" answered with the config change that caused it. |
| F10 | **Denomination choice analysis** (default / preset / custom / out-of-range share and conversion, per brand and currency) | breakdown | `ecom_orders`: `basket_basketquantitydetail`, `catalogue_productdenomination`, `…range` | needs-grant | M | 4 | Merchandising lever: which default values sell. |
| F11 | **Repeat purchase and time-to-second-order** cohorts (registered + merged guests) | metric + breakdown | `ecom_orders`: `order_order(user_id, guest_id, date_placed, status)`, `users_mergeduser` | needs-grant | M | 5 | Retention for marketers; occasion-driven repeat cycles. |
| F12 | **Gift-recipient → buyer conversion** (gift-acquired signups who later buy, days to first purchase) | agentic_analysis (cross-plugin) | `ecom_users` + `ecom_orders` via `users_user.username` = `users_userprofile.cognito_id` | needs-grant (+ V2 key test) | L | 5 | The "gifts pay for their own acquisition" story leadership wants. |
| F13 | **Guest checkout health** (guest identities vs guest orders per platform; merge rate; cart carry-over) | funnel | `ecom_orders`: `users_guestuser`, `order_order.guest_id`, `users_mergeduser`, `basket_mergedbasket` | needs-grant | M | 3 | Tells product whether guest checkout helps or leaks. |
| F14 | **Gift issuance health alert** (paid orders with `gift_create_event_triggered=false`, gift-creation error rate, events per order anomalies) | alert_trigger | `ecom_orders`: `order_order`, `kafka_giftcreationlog(status, error, order_id, created_on)` | needs-grant (+ index/extract) | M | 4 | Catches "paid but no gift" before customers complain. |
| F15 | **Order journey drill-down** (one order: basket → order → status changes → payment attempts → gift events → personalisation edits; PII-free) | record_drilldown | `ecom_orders` views (§5) | needs-grant | M | 3 | Ops/CS answer "what happened to order X" without DB access. |
| F16 | **Cross-currency and price-drift breakdown** (share of lines with different denomination currency; checkout→payment price change; approval by currency pair) | breakdown | `ecom_orders`: `order_orderlinequantitydetail`, `order_order`, youpay; daily snapshot of `core_currencyexchangerate` | needs-grant | M | 3 | Explains cross-border friction in GCC gifting. |
| F17 | **Occasion and scheduling breakdown** (occasion_code, greeting_code, scheduled vs instant, lead time) | breakdown | `ecom_orders`: personalise details, `order_line.is_instant_activated` | needs-grant | S | 4 | Campaign-timing input for Ramadan/Eid, birthdays (users has 369k birthdays without year). |
| F18 | **Checkout health dashboard** (F1, F3, F4 now; F7, F8, F14 once granted; each tile with provenance and freshness) | dashboard | both plugins | ready-now partially | M | 4 | One page for growth, product and ops. |

Features deliberately **not** proposed: raw "baskets vs orders" abandonment (misleading, R1); status-change funnels (incomplete log); token counts as engagement (mostly first logins).

---

## 4. Plugin notes

### 4.1 `ecom_users` plugin (readable now) — purchase-friction slice

- **Entities:** `user` (key `username` UUID; dims `country_of_residence`, `is_app_user` (trend only from Aug 2024), `user_legacy_state`, `is_deleted`), `otp_request` (no user FK; recipient is PII), `otp_chain` (derived), `identity_event` (`users_useridentityactivitylog.activity`), `login_token` (channel only).
- **Allowlisted tables:** `notifications_twofactorauth` (cols: id, created_on, source, auth_type, email_delivery, sms_delivery, language; `email`/`phone_number` usable **only inside** a definition's SQL for chain keys, joins and the phone-prefix `CASE`, never in the select list), `notifications_twofactorauthverification` (reference_id_id, is_valid, created_on), `users_useridentityactivitylog` (activity, timestamp, user_id; `comment` holds the email, so join-only), `users_secondaryuseridentity` (user_id, is_active, is_deleted, created_on; `alternate_email` join-only), `users_user` (id, username, date_joined, is_app_user, is_deleted, country_of_residence; `email`/`phone_number` join-only), `users_cognitoissuedtokens` (user_id, created_on, user_platform).
- **Derived definitions (SQL inside YAML, since we cannot create views on the replica):**
  - `otp_chain`: codes to the same recipient and flow no more than 10 minutes apart (users B5/C9 logic); exposes `source, auth_type, geo_bucket, codes, any_accepted, started_at, span_s` and never the recipient. **Count chains, not `is_valid=true` rows** (sign_up/sign_in can hold several trues per chain, users C9).
  - `gift_claim`: claim OTP chain → `secondary_email_added_via_gift` within 24 h, matched in-DB on lower(email) (T4 logic).
  - `gift_acquired_signup`: user whose first `secondary_email_added_via_gift` is less than 1 day after `date_joined` (T5).
  - `signup_completion`: OTP recipient → `users_user` row (T8/T9 logic), by codes and geo.
- **PII exclusions:** never select email, phone_number, alternate_email, comment, auth_code, request_meta IP/UA, device_signature; phone country comes from a prefix `CASE` only.
- **Freshness:** OTP tables keep about 31 days, so the plugin needs a **daily snapshot** of aggregated chains (F6). Provenance must stamp the as-of time; the tables are live and drift during the day.
- **Performance:** a DISTINCT over `lower(users_user.email)` timed out at 20 s; use hash semi-joins from the small OTP side (`materialized` CTEs, T3), and bound the OTP window.

### 4.2 `ecom_orders` plugin (blocked) — funnel slice

- **Entities:** `basket` (non-empty only by default), `basket_line`, `order`, `order_line`, `payment_attempt` (youpay rows) and `payment` (deduped to one per `order_reference`), `gift_issuance_event`, `guest_identity`, `checkout_gate_config` (the §1.7 tables), `offer` (`plusoffer.code`).
- **Allowlist:** the Option B column lists of orders-funnel §12.1 for `basket_basket`, `basket_line`, `basket_basketquantitydetail`, `basket_basketpersonalisedetail`, `order_order`, `order_line`, `order_orderlinequantitydetail`, `order_orderlinepersonalisedetail`, `payment_paymentdetail`, youpay, `kafka_giftcreationlog`, `users_guestuser`, `users_mergeduser`, `basket_mergedbasket`, config tables, `django_admin_log` (no object_repr/change_message), plus the catalogue columns in §5.
- **Derived views (preferred, Option A):** `atlas_ro.payment` = latest row per `order_reference` with `attempts`, `first_created_on`, `final_approved`, `response_class` (normalized decline class; no free text); `atlas_ro.basket_summary` = per basket `n_lines`, `value_by_currency`, `has_order`, `is_guest`, `platform`, `created_week` (removes the need to read 1.6 GB baskets); `atlas_ro.gift_issuance` = per order `events`, `failed_events`, `has_failure`, `first/last created_on`; `atlas_ro.order_order` with `has_*` PII-presence flags.
- **Performance:** basket has no date/status index and 0 replica reads today; youpay and giftcreationlog have no `created_on`/`order_reference` index. Serve these from a nightly extract of the views (orders-funnel §12.3), not live replica scans. The single reader is shared by 40 databases (orders-customer-catalog rev5).
- **Cross-plugin join:** only via `users_user.username` = `users_userprofile.cognito_id` resolved inside orders first, pending V2. Never join numeric user ids across DBs.

---

## 5. Grants needed (theme subset, PII-safe)

Everything in `ygag_ecom_orders_db` unless stated. Hash note: `md5()` is a core Postgres function (pgcrypto not needed), but unsalted hashes of **emails/phones are dictionary-reversible** and must not be used; **UUID keys** (`cognito_id`, `username`) are pseudonymous and can be exposed raw or md5'd.

| DB.table | Columns | PII-safe alternative / note |
|---|---|---|
| orders.`order_order` | id, number, order_reference, basket_id, user_id, guest_id, created_by_id, status, date_placed, sold_date, platform, placed_country_id, region_id, currency, gateway_currency, total_incl_tax, total_incl_tax_before_payment, total_incl_tax_in_gateway_currency, process_fee, conversion_rate_gateway_currency, conversion_rate_reporting_currency, gift_create_event_triggered, language_code | exclude user_email, guest_email, user_name, user_phone, owner, session_id, transaction_url, extra; view adds `has_*` flags |
| orders.`order_line` | id, order_id, line_reference, product_id, partner_id, quantity, line_price_incl_tax, status, is_offer_applied, offer_code, is_instant_activated, instant_activated_date, purchase_origin, record_type-equivalents, created_on | exclude partner_line_reference, partner_line_notes |
| orders.`order_orderlinequantitydetail` | line_id, denomination_currency_id, denomination_in_denomination_currency, denomination_in_reporting_currency, price_in_reporting_currency, is_buy_for_self, is_different_currency_denomination, delivery_method, reporting_currency, processing_fee_in_reporting_currency, price_in_denomination_currency_before_pay | exclude sender_name, personal_data_ref |
| orders.`order_orderlinepersonalisedetail` | line_id, delivery_type, delivery_date, delivery_time_zone, greeting_code, occasion_code, is_reminder_added, created_on | exclude phone_number, email_address (view: `has_recipient_phone`, `has_recipient_email`) |
| orders.`basket_basket` | id, status, date_created, date_submitted, date_merged, owner_id, guest_id, platform, record_type, region_id | exclude user, user_email, user_name, user_phone, user_gender, note, extra; better: `atlas_ro.basket_summary` |
| orders.`basket_line`, `basket_basketquantitydetail`, `basket_basketpersonalisedetail` | as orders-funnel §12.1 | same exclusions |
| orders.`youpayclient_youpayclienttransactiondata` | id, created_on, modified_on, order_reference, transaction_id, approved, payment_status, payment_gateway, payment_method, payment_scheme, channel_code, platform, is_gcc_card, card_issuer_country, is_fraud, is_flagged, amount, currency, cart_amount, cart_currency, redeemed_amount, available_amount, is_full_redemption, point_program, is_qitaf_enabled | exclude card_bin/last4, name_on_card, customer_*, *_url, order_history, order_items, udf1; view: `response_class` (normalized), `has_verify_url` (3DS proxy), `order_history_len` |
| orders.`kafka_giftcreationlog` | id, created_on, modified_on, event_id, status, error, order_id | exclude payload, failure, created_gift_details (secret-class); view: `has_failure` |
| orders.`users_guestuser` | id, created_on, platform, last_accessed, is_active | exclude email, username, session_id, db_session_id, extra, note |
| orders.`users_mergeduser`, `basket_mergedbasket` | all (ids + timestamps) | no PII |
| orders.`users_userprofile` | user_id, cognito_id (UUID, or md5(cognito_id)), is_email_verified, is_phone_number_verified | enables cross-plugin joins (V2) |
| orders.`catalogue_product` | id, upc, currency_id, require_mobile_verification, is_discountable, buy_for_yourself, allow_instant_activation, is_active, is_launched | no PII |
| orders.config: `core_currencybasketlimit`, `core_currency`, `core_currencyexchangerate`, `catalogue_productdenomination`, `catalogue_productdenominationrange`, `catalogue_producthandlingfee`, `core_unsupportedcountry`, `payment_paymentmethod`, `order_giftactivationconfig`, `core_siteconfig(is_guest_enabled)`, `offer_plusoffer` | all | no PII |
| orders.`django_admin_log` + `django_content_type` | id, action_time, action_flag, content_type_id, object_id, user_id | exclude object_repr, change_message |
| emapi.`brands_brand` | code, require_mobile_verification, allow_any_country_mobile_verification, buy_for_yourself, is_active | no PII |
| ecomweb.`configurations_lastviewedbrand` | brand_id, store_id, created_on, md5(username) | username is a UUID-like key; hash or resolve in-DB |

Minimum viable grant for this theme: `order_order` + `users_userprofile` (H1, H3, H11, H14, F11, F12), then youpay view (F8), then basket summary view (F7, F9).

---

## 6. Risks (traps that make purchase metrics wrong)

- **R1 Basket denominator.** 3.05M baskets include at least ~40% empty session carts (0.60 lines per basket). "Abandonment = 1 − orders/baskets" (59.5%) is wrong; use non-empty baskets (P8b).
- **R2 youpay fan-out.** No UNIQUE on `order_reference`; rows may be attempts. Summing money or counting declines on a youpay↔order join double-counts. Dedup first (P25).
- **R3 paymentdetail coverage.** 0..1 per order, ~62%: never inner-join it; it may start late or cover some gateways only (P9).
- **R4 Status-change log incomplete** (0.98 per order): not a funnel source.
- **R5 Gift events per order 2.64.** Units vs retries vs duplicates unknown; "gifts issued" from event counts is wrong until P29.
- **R6 OTP retention 31 days.** Any OTP/claim trend longer than a month needs atlas-side daily snapshots; the window moves during the day.
- **R7 `is_valid` is not a success flag.** Count chains with any accepted code; sign_up/sign_in chains can have several trues (users C9). `2fa_account_verification` is the claim flow, not login 2FA (§1.1). Do not call it "2FA failure".
- **R8 Signup trend breaks.** users_user id-gap cutover in May 2025, `is_app_user` definition change in Aug 2024, dead `type`/`platform`/social ids. Signup-based denominators must not cross those dates.
- **R9 Token-based engagement.** App tokens live 548 days; 67% of tokens are first logins; web tokens are visible only from 2026-08-29. Return-login rates (T6) are lower bounds.
- **R10 Guest identity.** `is_guest` on blacklist rows is unreliable, and orders puts registered usernames into `guest_id` (396 events). Guest/registered must come from `order_order.guest_id` / `user_id`; a guest who registers has two ids until `users_mergeduser` dedups.
- **R11 Currency mixing.** Sum money only in `*_in_reporting_currency`; basket lines carry `price_currency` per line, so mixed-currency baskets must be summed per currency (P24b). FX history does not exist unless snapshotted.
- **R12 Fee rates are varchar** (`processing_fee_rate`); use the numeric fee amounts.
- **R13 Reader contention.** One shared Aurora reader for 40 DBs; basket/youpay/gift-log scans are unindexed. Live atlas queries must stay sampled/indexed, and recurring funnels should run on an extract.
- **R14 Stale reltuples.** All orders-side volumes are estimates up to ~4.5% stale; use live counts on views once granted.
- **R15 Campaign-day confounding.** Sep 22–25 combined an acquisition push with an OTP delivery incident; friction baselines should exclude or flag such days.
- **R16 Claim email matching.** The claim join matches `lower(email)` between OTP and activity comment; case or whitespace variants can miss a few (users X40 showed 2 case variants in 3,775 blacklist emails).

---

## Appendix: SQL provenance (queries run for this theme, 2026-09-29)

All via `atlasq.sh <db> <rows>`. T1–T9, T12–T13 on `ygag_ecom_users_db` (VALIDATED); T10–T11 on `ygag_ecom_orders_db` (catalog only, STRUCTURAL). One attempt of T3 with a `DISTINCT lower(users_user.email)` CTE hit the 20 s timeout and was rewritten without it (not retried as-is).

**T1: OTP chain friction by flow × channel × geo** (31-day window)
```sql
with r as (select t.id, t.source, t.auth_type,
  case when t.phone_number like '+966%' then 'SA' when t.phone_number like '+971%' then 'AE' when coalesce(t.phone_number,'')<>'' then 'other_phone' else 'email' end geo,
  coalesce(t.email,'')||'|'||coalesce(t.phone_number,'') k, t.created_on, v.is_valid,
  case when t.created_on - lag(t.created_on) over (partition by coalesce(t.email,'')||'|'||coalesce(t.phone_number,''), t.source order by t.created_on, t.id) <= interval '10 minutes' then 0 else 1 end newc
 from notifications_twofactorauth t join notifications_twofactorauthverification v on v.reference_id_id=t.id),
c as (select *, sum(newc) over (partition by k, source order by created_on, id rows unbounded preceding) cid from r),
ch as (select source, k, cid, min(auth_type) auth_type, min(geo) geo, count(*) codes, bool_or(is_valid) any_valid from c group by 1,2,3)
select source, auth_type, geo, count(*) chains, count(*) filter (where codes>=2) multi, round(100.0*count(*) filter (where codes>=2)/count(*),1) pct_multi,
 count(*) filter (where not any_valid) no_accept, round(100.0*count(*) filter (where not any_valid)/count(*),1) pct_no_accept,
 round(100.0*count(*) filter (where codes>=2 and any_valid)/nullif(count(*) filter (where codes>=2),0),1) pct_multi_recovered
from ch where source in ('sign_up','sign_in','2fa_account_verification') group by 1,2,3 having count(*)>=100 order by 1,2,3;
-- 2fa/email 3,568 chains, 23.4% multi, 33.9% no accept, 49.6% multi recovered
-- sign_in/email 10,910 / 8.0 / 11.3; sign_up/email 18,467 / 13.9 / 16.0 / 57.8
-- sign_up/whatsappsms AE 8,611 / 2.2 / 3.3; SA 14,261 / 2.7 / 3.3; other_phone 3,509 / 6.3 / 14.6 / 37.8
```
**T2: claim-OTP (`2fa_account_verification`) chains by recipient tenure**
```sql
with r as (select t.id, t.email, t.created_on, v.is_valid,
  case when t.created_on - lag(t.created_on) over (partition by t.email order by t.created_on, t.id) <= interval '10 minutes' then 0 else 1 end newc
 from notifications_twofactorauth t join notifications_twofactorauthverification v on v.reference_id_id=t.id
 where t.source='2fa_account_verification' and t.email is not null and t.email<>''),
c as (select *, sum(newc) over (partition by email order by created_on, id rows unbounded preceding) cid from r),
ch as (select email, cid, min(created_on) st, count(*) codes, bool_or(is_valid) ok from c group by 1,2)
select case when u.id is null then 'not_registered' when u.is_deleted then 'deleted' when ch.st - u.date_joined < interval '1 day' then 'a_<1d'
  when ch.st - u.date_joined < interval '30 days' then 'b_1-30d' when ch.st - u.date_joined < interval '365 days' then 'c_30-365d' else 'd_>1y' end tenure,
 count(*) chains, count(distinct ch.email) recipients, count(*) filter (where ch.ok) accepted, round(100.0*count(*) filter (where ch.ok)/count(*),1) pct_ok,
 count(*) filter (where ch.codes>=2) multi,
 count(*) filter (where exists (select 1 from users_cognitoissuedtokens tk where tk.user_id=u.id and tk.created_on between ch.st - interval '1 hour' and ch.st + interval '1 hour')) token_pm1h
from ch left join users_user u on lower(u.email)=lower(ch.email) group by 1 order by 1;
-- a_<1d 50 chains / 41 recipients / 11 accepted; not_registered 3,518 / 3,140 / 2,348 (66.7%), 812 multi
```
**T3: claim-OTP recipients vs identity tables**
```sql
with e as materialized (select lower(t.email) e, count(*) n, bool_or(v.is_valid) ok
  from notifications_twofactorauth t join notifications_twofactorauthverification v on v.reference_id_id=t.id
  where t.source='2fa_account_verification' and coalesce(t.email,'')<>'' group by 1),
s as materialized (select distinct lower(alternate_email) e from users_secondaryuseridentity),
su as materialized (select distinct lower(email) e from notifications_twofactorauth where source='sign_up' and coalesce(email,'')<>''),
si as materialized (select distinct lower(email) e from notifications_twofactorauth where source='sign_in' and coalesce(email,'')<>''),
g as materialized (select distinct lower(comment) e from users_useridentityactivitylog where activity='secondary_email_added_via_gift'),
b as materialized (select distinct lower(value) e from core_blacklisteduserdetail where type='user_email' and not is_removed)
select count(*) recipients, count(*) filter (where ok) any_ok, count(s.e) is_secondary_email, count(su.e) also_signup_otp, count(si.e) also_signin_otp,
 count(g.e) claimed_gift_as_secondary, count(b.e) blacklisted_email, count(*) filter (where n>=10) ge10_codes, count(*) filter (where n=1) one_code
from e left join s on s.e=e.e left join su on su.e=e.e left join si on si.e=e.e left join g on g.e=e.e left join b on b.e=e.e;
-- 3,181 | 2,342 | 2,284 | 408 | 4 | 1,868 | 0 | 17 | 2,335
```
**T4: claim-OTP outcome → subsequent email attach, by codes per recipient**
```sql
with e as materialized (select lower(t.email) e, count(*) n, bool_or(v.is_valid) ok, min(t.created_on) first_at
  from notifications_twofactorauth t join notifications_twofactorauthverification v on v.reference_id_id=t.id
  where t.source='2fa_account_verification' and coalesce(t.email,'')<>'' group by 1),
g as materialized (select lower(comment) e, min("timestamp") ts from users_useridentityactivitylog where activity='secondary_email_added_via_gift' group by 1),
sa as materialized (select lower(comment) e, min("timestamp") ts from users_useridentityactivitylog where activity='secondary_email_added' group by 1)
select e.ok, least(e.n,5) codes_capped, count(*) recipients, count(g.e) via_gift_any, count(g.e) filter (where g.ts>=e.first_at) via_gift_after_otp,
 count(sa.e) filter (where sa.ts>=e.first_at) self_added_after_otp,
 percentile_cont(0.5) within group (order by extract(epoch from g.ts-e.first_at)) filter (where g.ts>=e.first_at) median_s_to_claim
from e left join g on g.e=e.e left join sa on sa.e=e.e group by 1,2 order by 1,2;
-- ok=false: 514/161/66/39/59 recipients (codes 1..5+), 0 claims after OTP
-- ok=true: 1,821/311/120/43/47 recipients; via_gift_after 1,428/257/98/36/34 (=1,853); self_added_after 383/54/22/7/13 (=479)
-- median s to claim: 30.4 / 93.6 / 162.3 / 386.1 / 28,996
```
**T5: monthly gift claims by account age**
```sql
select to_char(date_trunc('month',a."timestamp"),'YYYY "m" MM') m, count(*) claims, count(distinct a.user_id) users,
 count(*) filter (where a."timestamp" - u.date_joined < interval '1 day') new_acct_1d,
 round(100.0*count(*) filter (where a."timestamp" - u.date_joined < interval '1 day')/count(*),1) pct_new_1d,
 count(*) filter (where a."timestamp" - u.date_joined >= interval '365 days') acct_gt_1y, count(*) filter (where u.is_app_user) app_users
from users_useridentityactivitylog a join users_user u on u.id=a.user_id
where a.activity='secondary_email_added_via_gift' and a."timestamp">='2025-07-01'
group by date_trunc('month',a."timestamp") order by date_trunc('month',a."timestamp");
-- 2025-07 1,839/924 (50.2%)/579/1,476; 2025-12 2,757/1,276 (46.3%)/914/2,378; 2026-03 2,624/960 (36.6%)/721/2,334;
-- 2026-04 2,366/1,235 (52.2%)/632/2,178; 2026-09 1,746/893 (51.1%)/478/1,614 (15 months returned; min 1,536 in 2025-08)
```
**T6: return-login rate, gift-acquired vs other signups** (cohort joined 2026-07-15 → 08-28, not deleted)
```sql
with gift as materialized (select distinct a.user_id from users_useridentityactivitylog a join users_user u on u.id=a.user_id
   where a.activity='secondary_email_added_via_gift' and a."timestamp" - u.date_joined < interval '1 day'),
coh as materialized (select u.id, u.is_app_user, (u.id in (select user_id from gift)) gift_acq from users_user u
   where u.date_joined >= '2026-07-15' and u.date_joined < '2026-08-29' and not u.is_deleted),
t as materialized (select tk.user_id, bool_or(tk.created_on - u.date_joined > interval '1 day') returned,
   bool_or(tk.created_on - u.date_joined > interval '7 days') returned7, count(*) toks
   from users_cognitoissuedtokens tk join users_user u on u.id=tk.user_id where u.date_joined >= '2026-07-15' and u.date_joined < '2026-08-29' group by 1)
select coh.gift_acq, coh.is_app_user, count(*) users, count(t.user_id) any_token, count(*) filter (where t.returned) returned_gt1d,
 round(100.0*count(*) filter (where t.returned)/count(*),1) pct_ret1d, count(*) filter (where t.returned7) returned_gt7d, round(100.0*count(*) filter (where t.returned7)/count(*),1) pct_ret7d
from coh left join t on t.user_id=coh.id group by 1,2 order by 1,2;
-- other/non-app 4,552 / 182 tok / 3.1%; other/app 20,938 / 13,642 / 4.4% (7d 3.3%); gift/app 1,146 / 788 / 2.6% (7d 2.3%); gift/non-app: no rows
```
**T7: signup duration from first email OTP to account creation** (email sign_up, from 2026-09-01)
```sql
with f as materialized (select lower(t.email) e, min(t.created_on) first_otp, count(*) codes
  from notifications_twofactorauth t where t.source='sign_up' and t.auth_type='email' and coalesce(t.email,'')<>'' and t.created_on >= '2026-09-01' group by 1),
j as materialized (select f.*, u.date_joined, u.is_app_user from f join users_user u on lower(u.email)=f.e)
select case when codes=1 then '1' when codes=2 then '2' else '3+' end codes, count(*) registered, count(*) filter (where date_joined >= first_otp) joined_after_otp,
 round(percentile_cont(0.5) within group (order by extract(epoch from date_joined-first_otp)) filter (where date_joined>=first_otp)::numeric,0) p50_s,
 round(percentile_cont(0.9) within group (order by extract(epoch from date_joined-first_otp)) filter (where date_joined>=first_otp)::numeric,0) p90_s,
 count(*) filter (where date_joined - first_otp > interval '1 hour') gt_1h
from j group by 1 order by 1;
-- 1: 11,180 / p50 52 / p90 104 / 15 >1h; 2: 929 / 259 / 38,786 / 161; 3+: 535 / 2,613 / 177,934 / 252
```
**T8: email signup completion by codes per recipient** (2026-09-01 → 09-26)
```sql
with f as materialized (select lower(t.email) e, count(*) codes from notifications_twofactorauth t
  where t.source='sign_up' and t.auth_type='email' and coalesce(t.email,'')<>'' and t.created_on >= '2026-09-01' and t.created_on < '2026-09-27' group by 1),
r as materialized (select f.e from f join users_user u on lower(u.email)=f.e)
select case when codes=1 then '1' when codes=2 then '2' when codes<=4 then '3-4' else '5+' end codes, count(*) recipients, count(r.e) registered_now, round(100.0*count(r.e)/count(*),1)
from f left join r on r.e=f.e group by 1 order by 1;
-- 1: 11,990 / 9,867 / 82.3; 2: 1,420 / 833 / 58.7; 3-4: 587 / 300 / 51.1; 5+: 382 / 210 / 55.0
```
**T9: phone signup completion by geo × codes** (whatsappsms, same window)
```sql
with f as materialized (select t.phone_number p, count(*) codes,
   case when t.phone_number like '+966%' then 'SA' when t.phone_number like '+971%' then 'AE' when t.phone_number ~ '^\+(974|965|973|968)' then 'other_GCC' else 'non_GCC' end geo
  from notifications_twofactorauth t where t.source='sign_up' and t.auth_type='whatsappsms' and coalesce(t.phone_number,'')<>'' and t.created_on >= '2026-09-01' and t.created_on < '2026-09-27' group by 1,3),
r as materialized (select f.p from f join users_user u on u.phone_number=f.p)
select geo, case when codes=1 then '1' else '2+' end codes, count(*) recipients, count(r.p) registered_now, round(100.0*count(r.p)/count(*),1)
from f left join r on r.p=f.p group by 1,2 order by 1,2;
-- AE 6,997/96.9% | 216/80.6%; SA 11,569/97.1% | 380/76.8%; other_GCC 1,182/95.8% | 44/84.1%; non_GCC 1,457/83.3% | 151/32.5%
```
**T10: orders funnel table estimates and privilege** (orders DB, catalog)
```sql
select c.relname, c.reltuples::bigint est, c.relpages, (pg_relation_size(c.oid)/8192) cur_pages,
 round((c.reltuples * (pg_relation_size(c.oid)/8192.0) / nullif(c.relpages,0))::numeric,0) extrap, has_table_privilege(c.oid,'SELECT') readable
from pg_class c where c.relnamespace='public'::regnamespace and c.relkind='r' and c.relname in ('basket_basket','basket_line','basket_basketquantitydetail',
 'basket_basketpersonalisedetail','basket_mergedbasket','order_order','order_line','order_orderlinepersonalisedetail','order_orderstatuschange','payment_paymentdetail',
 'youpayclient_youpayclienttransactiondata','kafka_giftcreationlog','users_guestuser','users_mergeduser','users_customuser','personalization_detail',
 'catalogue_productdenomination','catalogue_productdenominationrange','core_currencybasketlimit','core_currency','core_currencyexchangerate','payment_paymentmethod','payment_paymenttransactionpayload') order by 1;
-- extrap: basket 3,046,354; basket_line 1,824,573; basket_personalise 558,032; order 1,233,955; order_line 1,473,029; order_personalise 513,432;
-- statuschange 1,209,949; paymentdetail 769,729; youpay 1,238,225; giftcreationlog 3,256,033; guestuser 82,502; mergeduser/mergedbasket -1 (33/10 pages);
-- denomination 22,404; range 11,376; basketlimit 8; currency 23; fx 437; paymentmethod 20. readable = false on all.
```
**T11: friction-related columns in orders** (catalog)
```sql
select c.relname, a.attname, format_type(a.atttypid,a.atttypmod), c.reltuples::bigint
from pg_class c join pg_attribute a on a.attrelid=c.oid and a.attnum>0 and not a.attisdropped
where c.relnamespace='public'::regnamespace and c.relkind='r' and c.relpages>0
 and a.attname ~* '(otp|verif|captcha|retry|attempt|abandon|expire|currency|is_guest|guest_enabled|platform|app_version|denomination$|is_default|minimum_amount|maximum_amount|limit_amount)'
 and c.relname !~ '^(auth_|django_|otp_|two_factor)' order by 1,2;
-- 82 rows; verification-type columns only: catalogue_product.require_mobile_verification, users_userprofile.is_email_verified/is_phone_number_verified,
-- youpay verify_url; guest toggles core_siteconfig.is_guest_enabled, order_giftactivationconfig.is_guest_enabled; no retry/attempt/abandon columns.
```
**T12: daily claims, claim OTPs and signups, Sep 15–28**
```sql
with d as (select generate_series('2026-09-15'::date,'2026-09-28'::date,'1 day')::date dd)
select to_char(d.dd,'MM "d" DD') dday,
 (select count(*) from users_useridentityactivitylog a where a.activity='secondary_email_added_via_gift' and a."timestamp">=d.dd and a."timestamp"<d.dd+1) gift_claims,
 (select count(*) from notifications_twofactorauth t where t.source='2fa_account_verification' and t.created_on>=d.dd and t.created_on<d.dd+1) claim_otps,
 (select count(*) from notifications_twofactorauth t join notifications_twofactorauthverification v on v.reference_id_id=t.id where t.source='2fa_account_verification' and v.is_valid and t.created_on>=d.dd and t.created_on<d.dd+1) claim_otps_valid,
 (select count(*) from users_user u where u.date_joined>=d.dd and u.date_joined<d.dd+1) signups
from d order by d.dd;
-- Sep 21: 44 / 94 / 62 / 858; Sep 22: 100 / 1,060 / 140 / 1,640; Sep 23: 122 / 553 / 158 / 1,484; Sep 24: 107 / 214 / 137 / 1,637; Sep 28: 60 / 108 / 72 / 994
```
**T13: Sep 22 claim-OTP recipients by codes per recipient**
```sql
with r as (select lower(email) e, count(*) n, extract(hour from min(created_on) at time zone 'Asia/Dubai')::int h0, extract(hour from max(created_on) at time zone 'Asia/Dubai')::int h1
  from notifications_twofactorauth where source='2fa_account_verification' and created_on>='2026-09-22' and created_on<'2026-09-23' group by 1)
select case when n=1 then '1' when n<=3 then '2-3' when n<=10 then '4-10' when n<=50 then '11-50' else '>50' end bucket, count(*) recipients, sum(n) otps, min(h0), max(h1)
from r group by 1 order by 1;
-- 1: 237/237; 2-3: 147/344; 4-10: 68/374; 11-50: 7/105; hours 0–23 in every bucket
```
**Reused profile figures:** users S1, B5, B6, C4, C8, C9 (users.md appendix); cross-db X30, X36, X40; orders-funnel Q16, Q20, Q21, Q30, P-queries P8b, P10, P15b, P15c, P20, P20b, P24b, P25, P27b, P29, P32, P35, P36 (not run: blocked); orders-customer-catalog rev5 (Q43, shared reader); ecomweb A14.
