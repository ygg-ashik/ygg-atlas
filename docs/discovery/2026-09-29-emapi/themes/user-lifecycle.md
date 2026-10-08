# Theme: User lifecycle & behavior

Written 2026-09-29 by the analytics strategist for ygg-atlas. It draws on `profiles/users.md` (v3), `profiles/cross-db.md` (rev 3), `orders-customer-catalog.md`, `orders-funnel.md` and `ecomweb-stores.md`/`emapi-stores.md`, all read in full or skimmed. It also uses **17 validating queries in the first pass (U1–U15, plus U10b and U14a/U14b as separate queries)**, run today between 13:30 and 14:10 UTC, and **10 more in the revision pass (U16–U25)**, run around 15:00 UTC. All of them went through `atlasq.sh` against `ygag_ecom_users_db`, the only readable DB. The revision pass also ran two catalog-only checks (C1, C2) on the orders and ecomweb DBs. All output is aggregate-only and PII-redacted.

Evidence labels:
- **VALIDATED** means backed by a data query that was actually run (a U-query here, or a profile appendix id).
- **STRUCTURAL** means inferred from schema or catalog statistics only.
- **NEEDS-GRANT** means a hypothesis that requires data we cannot read today. The exact table and columns are named.

The users DB is live, so totals drift by about 0.1% between queries. Each figure carries the query id that produced it.

---

## 0. Executive takeaways

1. **Gift recipients are an acquisition channel that nobody measures.** 59,496 users have claimed a gift into their account. **26,737 of them signed up within one day of that claim, and 23,994 within the same hour** (U1). These are accounts created *to receive a gift*. The identity-activity log only starts in Jul 2024, and its first gift claim is in Aug 2024 (U16), so every gift-acquired user joined on or after 2024-08-05. The all-time 45% share is therefore censored. **Among users who joined after the log started and later claimed a gift, 69% (26,737 of 38,915) signed up within a day of the claim** (U18). Gift-acquired signups make up 3.2–6.3% of every month's signups since Aug 2024 (U2).
   - **Quality.** The raw deletion gap (0.48% vs 1.78%, 3.7x) is survivorship-confounded: 42.5% of deletions happen within an hour of signup, and a gift claimer has by definition acted after signup. Counting only accounts that survived their first day, the gap is **0.39% vs 0.76%, or 2.0x** (U19). Risk flags are close to zero: 0.02% of gift-acquired users match an active blacklist entry against 0.76% of organic signups (U20), and 0 share a device against 0.54% (U21).
   - **Retention.** Gift-acquired users do *not* re-login more: their 30-day re-login rate is 0.99% against 1.23% (U13).
   - **Summary.** This is a clean, low-risk channel, not a proven high-retention one. The count is a lower bound, because the log only covers claims into an alternate email. **VALIDATED.**
2. **The recipient-claim path has the worst verification friction in the product.** The OTP flow `2fa_account_verification` is, in practice, the step that verifies a gift-claim or alternate email. 1,841 of the 1,857 gift-claim alternate emails added in the retention window used it (U14b), and only 41 of its 3,182 recipients were primary account emails (U14a). **Only 66% of these chains end in an accepted code, and in Arabic only 46%, against 74% in English** (U10). 857 of the 3,182 recipient emails (27%) never became an identity at all (U14a). **VALIDATED.**
3. **One resend at signup costs 24–32 points of registration.** For signup email chains, 80.7% register after a single code and 56.7% after two. For phone (WhatsApp/SMS) chains the figures are 95.8% and 63.5% (U3). That is a drop of 24.0 points for email and 32.3 for phone. Phone signup completes in a median of 12 s, against 54 s for email. Returning users hit the same wall. **44.7% of matched users whose email sign-in chain failed had no login token within 7 days, against 5.6% of users whose chain succeeded** (344 of 770 against 350 of 6,302; U22). That is a win-back trigger that fires about 15 times a day. **VALIDATED.**
4. **Returning activity is almost invisible to the data, and the "shell" legacy accounts are not dead.** Excluding users who joined in the last 30 days, only about 10.5k users (about 1.1% of the live base) received a new login token in the last 30 days (U4). App tokens last 548 days and web tokens last 30 days (U17), so this is a floor, not MAU, and web users are forced to re-login every month. About a third of those returning users are web-only (U23). Rates are comparable across platforms only when split by app vs web. The 110,937 legacy "shell" accounts, which were thought never to have logged in, reactivate at the same 0.93% rate as native 2023 users (U4). They are a win-back pool, not junk to exclude. **VALIDATED.**
5. **The signup flow was redesigned in two steps, and every lifecycle trend crosses both.** In **May 2025**, gender became mandatory (14% captured in Apr, 84% in May, 100% from Jun) and the id-sequence gap closed. In **Nov 2025**, birthday capture doubled (22% in Oct, 42% in Nov, 53% in Dec) (U6). 351k live users now have a usable birthday. That gives **about 31k birthdays in the next 30 days and about 7.4k a week** (U5), a ready-made trigger audience for a gifting company. **VALIDATED.**

---

## 1. Insights

### 1.1 Acquisition & signup

| # | Insight | Label | Evidence |
|---|---|---|---|
| I1 | **Recipient-led acquisition.** Of the 59,496 users with a `secondary_email_added_via_gift` event, **23,994 claimed within 1 h of signup, 2,743 between 1 h and 1 day, 4,320 between 1 and 30 days, 10,770 between 30 and 365 days, and 17,669 after more than a year**. The all-time split (45% signed up *because of* a gift, 48% existing users) is **censored by the log start**. The activity log begins in Jul 2024 (self-adds) and Aug 2024 (gift claims), and the earliest gift-acquired user joined 2024-08-05 (U16). Pre-2024 users can only appear in the ">1 year" buckets. **For joiners since 2024-08-05 who claimed a gift, 68.7% claimed within 1 day, 11.0% within 1–30 days and 20.3% later** (26,737 / 4,271 / 7,907; U18). Recent joiners have had less time to claim later, so this is still biased upward. | VALIDATED | U1, U16, U18 |
| I2 | Gift-acquired signups are **3.2–6.3% of monthly signups** (Aug 2024 4.4%, Nov–Dec 2024 6.3%, Mar 2025 5.9%, Mar 2026 3.2%, Apr 2026 5.3%, Sep 2026 3.7%). **Every one of them is flagged `is_app_user`** (26,736 of 26,737; U2). Caveat: the gift log starts in Aug 2024, the same month `is_app_user` was redefined, so this cannot separate "the claim path is app-only" from "post-Aug 2024 signups are almost all flagged app". This is a **lower bound**: recipients who claim with their primary email leave no identity event. | VALIDATED (share); STRUCTURAL (lower-bound and app-only reasoning) | U2, U16 |
| I3 | Gift-acquired users (2025 to Aug 2026 signups) are **50% AE / 40% SA**, against 37% AE / 50% SA for organic signups.<br>**Deletion.** The raw rate is 0.48% (97 of 20,007) against 1.78% (7,775 of 436,289). **This comparison is survivorship-biased**: 4,504 of the organic deletions happen within a day of signup, while a gift claimer has already acted after signup. **Among accounts that survived day 1, deletion is 0.39% (77 of 19,987) against 0.76% (3,271 of 431,785), a 2.0x gap rather than 3.7x** (U19).<br>**Re-login.** The 30-day re-login rate is *lower* for gift-acquired users: 0.99% against 1.23%. Existing users who later claim a gift ("gift_later") are the most active group at 2.55%. | VALIDATED | U13, U19 |
| I3b | **Risk overlay: gift-acquired signups are clean.** Matches against active `core_blacklisteduserdetail` entries (2025 to Aug 2026 signups): gift-acquired 1 email, 2 domain and 1 mobile out of 20,007 (0.02%). Organic: 528 email, 2,427 domain and 382 mobile out of 436,289 (up to 0.76%) (U20).<br>In the token era (joined 2026-07-15 to 09-21), the shared-device rate is 0 of 1,403 gift-acquired users with a token against 155 of 28,730 organic users (0.54%). Out-of-GCC token country is the same for both groups: 9.3% against 9.6% (U21). This supports "low-risk channel" but not "high-retention channel". | VALIDATED | U20, U21 |
| I4 | **Signup verification pattern.** Among 24,555 signups since 2026-08-31, 52.8% verified both a phone OTP and an email OTP, **45.8% verified phone only**, 0.1% email only, and 1.3% neither. The phone step is effectively universal. A phone-only signup has an email that the flow did not verify, which is consistent with a social-IdP signup (Google/Apple supply a verified email). That matters because the social-id columns have been dead since Dec 2024. | VALIDATED (split); inferred (social-login meaning), see H4 | U7 |
| I5 | **SA overtook AE.** SA share of signups was 43.3% in 2024, 49.3% in 2025 and 50.3% in 2026 YTD. AE fell from 43.7% to 38.6% to 37.1%. Egypt collapsed (4,319, then 2,209, then 1,988). India has a high deletion rate: 5.8% of 2024 signups against 2.0% for SA. | VALIDATED | U8 |
| I6 | **Day-of-week rhythm** (Dubai time, Oct 2025 to Sep 2026): Thursday is the peak (45,598) and Saturday the trough (34,169, −25%). **AE peaks on Friday (17,997) while SA's Friday is its second-weakest day (17,552).** The weekend calendars differ, so a single GCC send-day is wrong. | VALIDATED | U9 |
| I7 | Hour of day: every OTP flow peaks at 15–18h Dubai time and bottoms at 05h, a 5.9x swing for sign_up. | VALIDATED | users.md B9 |
| I8 | **Acquisition source (UTM, referral, campaign) exists in none of the four DBs.** Column searches in orders, ecomweb and emapi find nothing. The only "channel" signals are `is_app_user` (redefined in Aug 2024), the first token's `user_platform` (only since Jul/Aug 2026) and the gift-claim signal above. | STRUCTURAL | cross-db §5; orders-funnel Q22; ecomweb A10 |
| I8b | **Referral / invite: no data exists in users DB.** A catalog search of users DB for columns or tables matching refer, invite, utm, campaign, promo or affiliat finds only `users_promotionaldomainblacklist` (a promo-abuse domain list) and unrelated `reference_id` / `user_reference` keys (U24). Together with I8, that means no referral programme data exists in any of the four DBs. **The only referral proxy is the gift loop:** a recipient who signs up to claim (I1) and later becomes a sender (F14, H3a). Atlas should label that metric "gift-driven referral (proxy)". | VALIDATED (users catalog); STRUCTURAL (other three DBs) | U24; I8 |
| I9 | Burst detection works on signups alone. The 2026-09-22 to 25 push doubled daily signups (1.1–1.6k/day) and came with a resend storm on Sep 22–23 (25.6% of sign_up codes were resends). | VALIDATED | users.md B6 |

### 1.2 Activation, verification & login friction

| # | Insight | Label | Evidence |
|---|---|---|---|
| I10 | **Signup OTP chain length against registration** (31 days): email chains: 1 code 80.7% (12,832 of 15,896), 2 codes 56.7%, 3–4 codes 51.8%, 5 or more 54.2%. Phone chains: 1 code 95.8% (24,586 of 25,652), 2 codes 63.5%, 3–4 codes 55.9%. **The first resend is the cliff.** Median time from first code to account creation: phone 12 s, email 54 s, 2-code email 237 s. | VALIDATED | U3 |
| I11 | **`2fa_account_verification` is the alternate-email / gift-claim verification step, not login 2FA.** Of its 3,182 recipient emails, 2,284 (71.8%) became a `users_secondaryuseridentity` *after* the request, only 41 are primary account emails, and 857 (26.9%) match nothing, which means abandoned claims. Of the 1,857 gift-claim alternate emails added in the window, 1,841 (99.1%) went through this OTP. | VALIDATED | U14a, U14b |
| I12 | **The Arabic email OTP is the weak link.** Chain acceptance by language (same 10-minute chain rule): 2fa/gift-claim ar **46.0%** (454 of 987, 33% resend) vs en 73.8% (1,905 of 2,582); sign_up email ar 78.4% vs en 85.6%; sign_in email ar 85.5% vs en 89.2%. **Phone OTP shows no Arabic gap** (sign_up phone ar 96.6% vs en 94.7%). Candidate causes are the Arabic email template, RTL rendering of the code, or deliverability. | VALIDATED (gap); cause is a hypothesis (H2) | U10 |
| I13 | The median resend comes at 77–129 s, well inside the 5-minute code validity. Users give up waiting on delivery; they are not being timed out. `whatsapp_delivery` is never true, so WhatsApp delivery cannot be observed. | VALIDATED | users.md B4, B8 |
| I14 | Fresh signups almost always get a token (98.1% of the last-30-day cohort), so signup equals first login. **67% of all tokens are first logins**, and token counts are a signup proxy. | VALIDATED | U4; users.md C4 |

### 1.3 Returning activity, dormancy & retention proxies

| # | Insight | Label | Evidence |
|---|---|---|---|
| I15 | **30-day new-token rate by signup cohort** (live users, token issued since 2026-08-30): Jul–Aug 2026 2.2%; 2026 H1 1.29%; 2025 1.09%; 2024 0.92%; 2023 native 0.90%; 2023 linked-legacy 1.60%; pre-migration linked 1.28%. **About 10.5k returning users a month out of about 974k live.**<br>**Platform asymmetry:** web tokens expire after exactly 30.0 days (median) and app tokens after 547.9 days (U17). Web users therefore re-issue a token every month just by staying active, while an active app user may issue none. The blended rate mixes two different measurements. **Split app vs web** (U23):<br>• App-token rate: pre-migration 0.87%, 2023 0.68%, 2024 0.63%, 2025 0.74%, 2026 H1 0.84%, Jul–Aug 2026 1.42%.<br>• Web-only returners are a stable 31–36% of each cohort's returners, so the ordering between cohorts holds, but levels are not comparable across platforms. The measure is a floor, not MAU. | VALIDATED | U4, U17, U23 |
| I16 | **The shell legacy accounts are reactivating.** 981 of 105,501 live shell accounts (0.93%) logged in within 30 days, the same rate as native 2023 users. The cross-db rev 3 statement that shell accounts are "never logged in" rests on the frozen legacy `last_login` and does not describe current behaviour. These are dormant legacy customers who can be won back. | VALIDATED | U4 (corrects cross-db §1.3b usage) |
| I17 | **Two-week return by first platform** (joined 2026-08-30 to 09-14): iOS 2.3% (111 of 4,928), Android 4.1% (108 of 2,637), **Web 6.8%** (156 of 2,306). **88 web-first users (3.8% of web signups) later logged in on another platform, mostly the app.** That is a measurable web-to-app migration. 211 signups (2.1%) never received a token.<br>**Not comparable across platforms:** a returning app user usually keeps a 548-day token and issues no new one, while a returning web user needs a new token on any new browser or session, and every 30 days at the latest (U17). "Web 6.8% vs iOS 2.3%" is a measurement artefact until activity is measured from orders. | VALIDATED (counts); interpretation STRUCTURAL | U12, U17 |
| I18 | **Identity engagement goes with activity.** The 30-day token rate among users older than 30 days is 1.05% with no identity events, 1.65% for gift-claim only, 2.13% for self-added alternate email, 2.7% for phone change and 3.5% for gift plus self. | VALIDATED (correlation only) | U11 |
| I19 | **Account deletion is mostly regret at signup.** Of 5,644 soft-deleted accounts created since Jun 2025, 42.5% were deleted within 1 hour of signup and 60.4% within 1 day (`modified_on` proxy; the ≤1h bucket is robust because later writes can only lengthen the gap). SA accounts are 54% of deletions within a day. This early-deletion mass is why any comparison of deletion rates between segments defined by post-signup behaviour must exclude day-1 deletions (see I3 and U19). | VALIDATED | U15, U19 |
| I20 | `users_user.last_login` is a frozen legacy-platform timestamp (57,377 rows, 99.95% before 2024), and ecomweb `users_cognitouser` has no last-activity column at all. **emapi `users_user.last_login` may be live**: it is in the column inventory, but its values are unreadable. | VALIDATED (users); STRUCTURAL (emapi); NEEDS-GRANT (emapi values) | cross-db X34; emapi-stores §3 |

### 1.4 Identity, legacy & multi-email

| # | Insight | Label | Evidence |
|---|---|---|---|
| I21 | Legacy states: linked 57,754, shell 110,937, native 827,585. Linked legacy users are the most loyal cohort: their 30-day token rate is 1.6% against 0.9% for 2023 natives. | VALIDATED | cross-db X34; U4 |
| I22 | Alternate emails: 72,637 active. At most one live alternate per user. 81% were added through a gift claim. | VALIDATED | users.md §4, U11 |
| I23 | The canonical cross-DB key is the `username` UUID, never the numeric id. The orders, ecomweb and emapi user tables are about 980–996k rows, so the same population. | VALIDATED (users side); STRUCTURAL (mirrors) | cross-db §1.3 |
| I24 | Guest checkout identities (`users_guestuser`, 82.5k–88.7k est) and the guest-to-registered merge (`users_mergeduser` ≤3.7k, `basket_mergedbasket` ≤1.2k) make a guest-to-account conversion funnel possible. **`users_guestuser` also carries `last_accessed` (timestamptz), `platform` and `is_active`** (C1, pg_attribute). That allows guest dormancy bands and a "returning guest, never signed up" nudge segment, not just merge counts. | STRUCTURAL; NEEDS-GRANT | orders-customer-catalog; C1 |

### 1.5 Demographics, geography, moments

| # | Insight | Label | Evidence |
|---|---|---|---|
| I25 | **Birthday moments.** 351,315 live users have a usable birthday (`0000/DD/MM`, excluding the 01/01 default). **31,004 of those birthdays fall between 2026-09-30 and 10-29, and 7,411 in the next 7 days.** By country: SA 13,655 in the next 30 days, AE 12,845, other 4,504. | VALIDATED | U5 |
| I26 | The birthday audience (account holders whose own birthday is coming up) is 29% female overall: SA 18% and **AE 41%**. A birthday campaign addresses the account holder ("treat yourself", or "let friends gift you"), not a gift recipient. **SA birthday creative should therefore be written mainly for men (82%), and AE creative should be gender-balanced.** | VALIDATED | U5 |
| I27 | **Anniversary and occasion moments exist in orders but cannot be read.** `order_orderlinepersonalisedetail` (496,737 est) and `basket_basketpersonalisedetail` (553,383 est) carry `occasion_code`, `delivery_date` and **`is_reminder_added`**. emapi/ecomweb `brands_occasion` defines the occasions (55 in ecomweb). This is the data behind "remind me next year" and "you gifted Mom on this date last year" triggers. ecomweb `configurations_upcomingoccasion` is empty but polled 89k times, so an upcoming-occasion feature was built and left empty. | STRUCTURAL; NEEDS-GRANT | orders-funnel §2.2; ecomweb A14 |
| I27b | **Browse-interest signal exists but is unreadable.** ecomweb `configurations_lastviewedbrand(username, brand_id, store_id, created_on, modified_on)` has about 59.9k rows (reltuples) and is actively read (4,652 seq and 3,261 index scans) (C2). Joined to orders, it supports a "viewed brand X, no order in 72 h" browse-abandon trigger and brand-affinity segments. The stats show `n_live_tup` 0 and `n_tup_ins` 0 (stats reset or low insert churn), so freshness is unknown until granted. | STRUCTURAL; NEEDS-GRANT | C2; ecomweb-stores |
| I28 | Language: 21.5% of OTPs are Arabic. SA phone signups are 39% Arabic and AE phone signups 0.4% (35 of 8,829). | VALIDATED | U10b |
| I29 | Residence-versus-login mismatch: 6.1% of AE and 3.6% of SA tokens come from outside the GCC. About half are signup-day tokens, and SA→Spain and AE→Brazil show about one token per user, which fits VPN exit or farming. This is a risk signal, not travel. | VALIDATED | users.md C5/C6 |

### 1.6 App vs web, device

| # | Insight | Label | Evidence |
|---|---|---|---|
| I30 | Since web tokens begin (2026-08-29): 25,589 users were app-only, 8,157 web-only and 1,830 used both. Of app tokens, iOS takes 66% (32,163 vs 16,804). | VALIDATED | cross-db X36 |
| I31 | The platform fields in users (`platform`, `type`, social ids) are dead. **ecomweb `users_cognitouser` and emapi `users_user` still carry `platform`, `app_version`, `user_agent`, `is_app_user` and `type`.** They may be populated there, which is the only way to recover signup method and app version. | STRUCTURAL; NEEDS-GRANT | ecomweb §1; emapi §3 |
| I32 | Device sharing: 117 app devices serve 2–3 accounts and 2 devices serve 4–10. This is a multi-account and promo-abuse seed list. | VALIDATED | users.md B11 |
| I33 | Forced-upgrade exposure (users below `required_version`) is computable in emapi from `app_version` and `emapi_generics_client_mobileappplatformversion`. | STRUCTURAL; NEEDS-GRANT | emapi-stores Friction |

---

## 2. Hypotheses (testable, for end users)

| id | Statement | Audience | Test | Data needed | Label |
|---|---|---|---|---|---|
| H1 | **A resend at signup lowers 7-day purchase, not just registration.** Users whose signup chain needed 2 or more codes are at least 20% less likely to place an order within 7 days than single-code signups. | Growth, product | Chain length from U3 logic, joined via username to first `order_order.date_placed`. Compare 7-day purchase rate, controlling for country and channel. | users OTP (readable, 31-day retention, needs a daily snapshot); orders `order_order(user_id, date_placed, status)` + `users_userprofile(user_id, md5(cognito_id))` | NEEDS-GRANT (orders G1/G9) |
| H2 | **A fix to the Arabic email OTP template recovers about 275 verified alternate-email chains a month, about 220 of them gift claims.** Raising ar `2fa_account_verification` acceptance from 46.0% to the en level of 73.8% on about 987 ar chains per 31 days gives 274 extra accepted chains. That flow also verifies self-added alternate emails (443 of 512 self-adds used it, against 1,841 gift claims), so about 81% of its traffic is gift-related (U14b). Chains are not distinct claims, because a user can retry in a new chain, so this is an upper bound on claims recovered. | Product, CRM | A/B test a new Arabic email template (plain LTR code block, code in the subject line). Metric: chain acceptance for 2fa_account_verification, ar. Guardrail: resend share. | users `notifications_twofactorauth(+verification)` (readable today) | VALIDATED baseline; experiment pending |
| H3a | **Gift-acquired users place a first order within 90 days at a lower rate than organic signups (≤0.8x).** This is the gift-driven referral loop: recipient to sender. | Marketing (referral proxy) | Segment gift_acquired vs organic (U13 logic, joiners since 2024-08-05 only, excluding day-1 deletions), then compare the 90-day first-order rate. | orders `order_order(user_id, date_placed, status)` + `users_userprofile(user_id, md5(cognito_id))` | NEEDS-GRANT |
| H3b | **Among users who do place a first order, gift-acquired users have a higher 180-day repeat-order rate than organic users (≥1.2x).** | Marketing, CRM | Same segments, restricted to first-orderers. Compare the share with at least 2 orders within 180 days of the first. | same as H3a | NEEDS-GRANT |
| H3c | **A failed sign-in chain predicts dormancy.** Users whose email sign-in chain fails and who get no token within 7 days (44.7% of failed-chain users, against 5.6% after success) still have no token at 30 days in at least 70% of cases. A same-day fallback nudge (WhatsApp code or magic link) halves that. | CRM, product | Baseline is ready now (U22 logic; needs a daily snapshot). Randomise the nudge to half of the failed-no-token users and measure a token within 7 or 30 days. Break down by language, because ar sign-in acceptance is 85.5% against 89.2% for en (U10). | users OTP + tokens (readable) | VALIDATED baseline; experiment pending |
| H4 | **"Phone-only verification" at signup is a usable proxy for social-IdP signup.** At least 90% of phone-only signups came through Google or Apple. | Growth (channel mix) | Compare against Cognito identity-provider data, or emapi/ecomweb `type`/`google_id`/`apple_id` for the same usernames. | emapi `users_user(md5(username), type, has_google_id, has_apple_id, date_joined)` or Cognito export | NEEDS-GRANT |
| H5 | **Birthday-week offers beat generic offers.** A "gift yourself" offer sent in the user's birthday week gets at least 2x the conversion of the same offer at a random time. | CRM | Randomised holdout within the weekly birthday audience (about 7.4k; U5). Measure order within 7 days. | users birthdate (readable); orders for outcome | VALIDATED audience; outcome NEEDS-GRANT |
| H6 | **Occasion reminders drive repeat gifting.** Senders who set `is_reminder_added` on a line reorder within ±14 days of the anniversary at least 3x more often than senders who do not. | CRM, product | Cohort of lines with occasion_code plus reminder vs without, then an order from the same user_id 350–380 days later. | orders `order_orderlinepersonalisedetail(line_id, occasion_code, is_reminder_added, delivery_date)`, `order_line`, `order_order(user_id, date_placed)` | NEEDS-GRANT |
| H7 | **Shell legacy accounts are a cheaper win-back pool than cold acquisition.** A win-back campaign to shell accounts with a verified phone gets more than 3% login and more than 1% purchase in 30 days. The current organic rate is 0.93% login. | Marketing | Holdout test on shell accounts (U4 segment); measure new token and first order. | users (readable) + orders outcome | VALIDATED baseline; outcome NEEDS-GRANT |
| H8 | **Web-first users who adopt the app are worth more.** The 3.8% of web signups who later log in on app (U12) have at least 2x the 90-day order count of web-only users. | Product, growth | Split on tokens (readable), outcome from orders. | orders `order_order(user_id, platform, date_placed)` | NEEDS-GRANT |
| H9 | **Signup-then-delete within 1 hour is concentrated in fraud or promo-abuse clusters.** Accounts deleted within 1 h over-index on shared devices, blacklisted domains and out-of-GCC signup tokens. | Risk | Rates of each risk flag among ≤1h-deleted vs retained signups. Deleted users' tokens persist (9 tokens on soft-deleted users). | users (readable). Expand with orders `payment_paymentdetail.is_fraud` | VALIDATED feasible; not yet run |
| H10 | **Timing campaign sends by country weekend lifts signups.** AE Friday sends and SA Thursday sends beat a single GCC send day. | Marketing | Geo-split send-day test; outcome daily signups by country. | users (readable) | VALIDATED baseline (U9) |
| H11 | **A browse without an order converts after a reminder.** Users with a `configurations_lastviewedbrand` row and no order for that brand within 72 h convert at least 1.5x more often within 7 days when sent a brand-specific reminder than a holdout. | CRM, growth | Build the segment (lastviewedbrand × orders), randomise the reminder, measure a 7-day order containing that brand. | ecomweb `configurations_lastviewedbrand(md5(username), brand_id, store_id, created_on)`; orders `order_order`, `order_line(product_id)` joined to brand | NEEDS-GRANT |
| H11b | **Returning guests who never sign up are a recoverable pool.** Guests with `last_accessed` in the last 30 days and no merge record have at least 20% as many orders as registered users of the same recency. A signup nudge at checkout converts at least 10% of them to accounts. | Growth | Count guests by `last_accessed` band without a `users_mergeduser` row; compare their order frequency; A/B test the signup nudge. | orders `users_guestuser(id, platform, last_accessed, is_active, created_on)`, `users_mergeduser(guest_id, user_id)`, `order_order(guest_id, date_placed)` | NEEDS-GRANT |
| H12 | **Users below the app's `required_version` show a login gap.** Users on forced-upgrade versions have a 30-day new-token rate at least 2x baseline (the forced update generates re-login), or they churn. | Product | emapi app_version bucket × users tokens by username. | emapi `users_user(md5(username), platform, app_version)`, `emapi_generics_client_mobileappplatformversion` | NEEDS-GRANT |

---

## 3. Atlas features

Readiness: **ready-now** means buildable on `ygag_ecom_users_db` today; **needs-grant** means it needs a listed grant; **needs-new-source** means it needs a DB or system outside the four.

| id | Feature | Type | Backing | Readiness | Effort | Impact | Why it is a wow |
|---|---|---|---|---|---|---|---|
| F1 | **Gift-recipient acquisition** metric (`signups_gift_acquired`, range, breakdown by country) plus share of signups; `valid_from` 2024-08-05 | metric | users: `users_user`, `users_useridentityactivitylog` | ready-now | S | 5 | It exposes an acquisition channel that nobody reports: 3–6% of signups a month, with about 0 risk flags and 2x lower post-day-1 deletion |
| F2 | **Signup verification funnel**: OTP requested → accepted → account created → first token, with a resend-chain breakdown by channel and language | funnel | users: `notifications_twofactorauth(+verification)`, `users_user`, `users_cognitoissuedtokens` | ready-now (31-day window; add a daily snapshot) | M | 5 | Shows the 24–32 point cliff at the first resend |
| F3 | **Gift-claim verification funnel** (2fa_account_verification chain → alternate email added via gift) by language | funnel | users: same plus `users_secondaryuseridentity` | ready-now | M | 5 | Arabic claimants succeed 46% of the time against 74% in English; a direct fix target |
| F4 | **OTP friction alert**: resend share per flow per hour above baseline + 3σ, or chain acceptance below threshold | alert_trigger | users OTP tables | ready-now | S | 4 | Would have flagged the Sep 22–23 storm while it happened |
| F5 | **Birthday audience** segment (next 7/30 days, country, gender, excluding the 01/01 default) plus a weekly birthday-moment dashboard | segment | users: `users_user.birthdate` (derived month/day only) | ready-now | S | 5 | 31k addressable birthdays a month, ready for campaigns |
| F6 | **Cohort retention grid (login-proxy)** by signup month × legacy state, **always split app vs web** (30-day web expiry against 548-day app), with an explicit "floor" caveat | breakdown | users: `users_user`, `users_cognitoissuedtokens`, `users_migratedtransactionlog` | ready-now, but thin: about 60k tokens since 2026-07-13 (app) / 08-29 (web). It is a single 30-day slice until the daily snapshot job accumulates history | M (L until the snapshot has at least 3 months) | 3 | First honest retention view; later upgraded with orders |
| F7 | **Legacy dimension** `user_legacy_state` (linked/shell/native) plus a **shell win-back segment** | segment | users: `users_migratedtransactionlog`, `users_user` | ready-now | S | 4 | 105k reactivatable accounts |
| F8 | **Web-to-app migration** metric (web-first signups later seen on app) | metric | users tokens | ready-now (about 60k tokens since Jul/Aug 2026, 1–2.5 month retention; needs a snapshot for trends) | S | 3 | The app-adoption KPI that product asks for |
| F9 | **Signup-regret / early-deletion** metric (deleted ≤1h / ≤1d / ≤7d of signup) by country, with risk overlays; also the "survived-day-1" denominator used for any segment deletion comparison | metric | users `users_user` | ready-now | S | 3 | 42% of deletions happen in the first hour |
| F10 | **Signup calendar heatmap** (Dubai hour × weekday × country) for send-time planning | breakdown | users `users_user`, OTP | ready-now | S | 3 | Shows AE-Friday vs SA-Thursday |
| F11 | **Lifecycle-change annotations** registry: auto-annotate charts at the known cutovers (Oct 2023 `type` death, Aug 2024 `is_app_user`, Dec 2024 social ids, May 2025 signup redesign, Nov 2025 birthday capture, Jul/Aug 2026 token history start) | dashboard | registry metadata | ready-now | S | 4 | Stops wrong trend conclusions; provenance in practice |
| F12 | **Identity record drill-down** (one user, pseudonymous): legacy state, identity events, token platforms and countries, blacklist hits. No raw PII | record_drilldown | users all identity tables | ready-now | M | 3 | CS and risk triage in one view |
| F13 | **Agentic analysis: "why did signups move?"** Decompose a signup change into country × gift-acquired × verification-channel × resend-rate, then check the cutover calendar | agentic_analysis | users (sandbox over governed extracts) | ready-now | M | 5 | Answers the leadership question in one prompt |
| F14 | **Recipient-to-sender loop (gift-driven referral proxy)** metric: gift-acquired users who place their first order (7/30/90 d). This is the stand-in for referral, which has no data in any DB (I8b) | funnel | users + orders `order_order` via `cognito_id` hash | needs-grant | M | 5 | The viral-loop KPI for a gifting business |
| F15 | **Occasion/anniversary trigger** segment: senders with an occasion line and a reminder whose anniversary is in the next N days | segment | orders `order_orderlinepersonalisedetail`, `order_line`, `order_order`; emapi `brands_occasion` | needs-grant | M | 5 | "You gifted for Eid/birthday last year" moments |
| F16 | **True retention/dormancy**: days since last order, dormancy bands (30/90/180/365), and a cohort repeat-purchase grid | breakdown | orders `order_order(user_id, guest_id, date_placed, status, platform)` | needs-grant | M | 5 | Replaces the login floor with purchase recency |
| F17 | **Guest-to-account conversion funnel** (guest created → merged → first registered order) | funnel | orders `users_guestuser`, `users_mergeduser`, `basket_mergedbasket` | needs-grant | M | 4 | Quantifies checkout-to-account value |
| F18 | **Signup-method mix recovery** (social vs conventional since Dec 2024) and **app-version / forced-upgrade exposure** | breakdown | emapi `users_user`, ecomweb `users_cognitouser` (hashed username, type, has_*_id, platform, app_version); emapi version config | needs-grant | M | 3 | Restores two dead dimensions |
| F19 | **Agentic analysis: OTP resend → purchase impact** (H1) | agentic_analysis | users OTP snapshot + orders | needs-grant | M | 4 | Turns friction into money |
| F20 | **Lifecycle dashboard**: signups (with gift-acquired share), verification funnel, returning-login floor, birthdays this week, deletions, web-to-app, and change annotations | dashboard | users (now), orders later | ready-now (v1) | M | 5 | A daily page for growth and CRM |
| F23 | **Failed sign-in win-back trigger**: an email or phone sign-in chain with no accepted code and no token within 24 h / 7 d fires a fallback-login nudge. Breakdown by language and channel | alert_trigger | users `notifications_twofactorauth(+verification)`, `users_cognitoissuedtokens`, `users_user` (in-DB join, emits user key and flag only) | ready-now (needs a daily snapshot, because OTP data is kept 31 days) | S | 5 | About 344 locked-out users a month (U22) caught the same day |
| F24 | **Gift-acquired risk overlay**: blacklist-match, shared-device and out-of-GCC rates by acquisition class (gift-acquired, gift-later, organic) | breakdown | users `core_blacklisteduserdetail` (hashed value), tokens (device_signature hashed in view, `request_meta->>'COUNTRY'` derived) | ready-now | S | 4 | Validates channel quality: 0.02% vs 0.76% blacklist match |
| F25 | **Browse-abandon trigger**: viewed brand, no order for that brand within 72 h; also brand-affinity segments | alert_trigger | ecomweb `configurations_lastviewedbrand`; orders `order_order`, `order_line` | needs-grant | M | 4 | The only browse-behaviour signal in the estate |
| F26 | **Guest dormancy and returning-guest segment**: guests by `last_accessed` band and platform, without a merge record | segment | orders `users_guestuser`, `users_mergeduser`, `order_order` | needs-grant | S | 3 | Recovers checkout users who never made an account |
| F21 | **OTP delivery receipts** by provider and channel, to explain resends | metric | `ygag_mailengine_aps_db`, `ygag_smsengine_db` | needs-new-source | L | 4 | Root cause for the Arabic and email gaps |
| F22 | **Acquisition attribution** (UTM, campaign, install source) | breakdown | GA4 / Firebase / AppsFlyer | needs-new-source | L | 5 | The attribution gap in all four DBs |

---

## 4. Plugin notes

**Plugin `ecom_users` (backend/app/sources/ecom_users/)** is the lifecycle backbone and is buildable now.

- **Entities**
  - `user`: key `username`. Expose only derived columns: `signup_month`, `country_of_residence`, `is_app_user` (with its Aug 2024 validity caveat), `gender_known`/`gender`, `birthday_month`, `birthday_day` (derived; `birthday_is_default` for 01/01), `legacy_state`, `is_deleted`, `trusted_user`.
  - `identity_event`: from activity; derived `event_type` and `timestamp`; the `comment` holds an email and is **excluded**.
  - `login_token`: source columns are only `id, created_on, modified_on, jti, token_hash, device_signature, user_platform, request_meta (jsonb), expires_at, user_id` (U25).
    - **Direct columns:** `user_platform`, `created_on`, `expires_at`, `user_id`.
    - **Derived in a view, never exposed raw:** `country = request_meta->>'COUNTRY'` (a full country name, e.g. "Saudi Arabia", not ISO-2), `os_family = request_meta->'OS_TYPE'->>'name'`, `token_lifetime_days = expires_at − created_on` (30 for WEB, 548 for app), `device_shared = count(distinct user_id) over device_signature ≥ 2` (a flag only).
    - **`is_new_user_login` is not a column.** Derive it as "first token for this user_id and created_on ≤ date_joined + 1 day".
    - **Excluded:** jti, token_hash, raw device_signature, and all of raw `request_meta`, which holds IP_ADDRESS, USER_AGENT, BROWSER and TOKEN_DERIVATIVES.
  - `otp_chain`: a derived view. Chain id, flow, channel, language, codes, accepted, first_ts, `registered_after` flag. The recipient is hashed in the view and never exposed.
  - `legacy_migration` (derived state only).
- **Allowlist**: `users_user` (column allowlist), `users_useridentityactivitylog` (no `comment`), `users_secondaryuseridentity` (no `alternate_email`; hash only), `users_cognitoissuedtokens`: column allowlist `user_platform, created_on, expires_at, user_id` only, with country and OS exposed **only through the derived view `v_token`**. `request_meta` is never allowlisted. `notifications_twofactorauth` and `notifications_twofactorauthverification` (no email, phone or auth_code; phone prefix → country derived), `users_migratedtransactionlog` (states only), `core_blacklisteduserdetail` (type, source, is_removed, created_on and a hashed value, for risk overlays).
- **PII exclusions**: email, phone_number, name*, nickname, ip_address, location, picture, social ids (derive `has_*`), password, legacy_auth_code raw, token/jti/device_signature, request_meta IP/UA, blacklist `value`/`remarks`, all admin/session tables.
- **Derived views to create** (in atlas, or requested as DB views):
  - `v_user_lifecycle`: one row per user with signup_month, legacy_state, first_token_platform, `gift_acquired` (claim ≤1 day after join), `has_alt_email`, `deleted_within_1h/1d`, birthday month/day.
  - `v_otp_chain`: the 10-minute chain rule; must be **snapshotted daily** because the source keeps only about 31 days.
  - `v_token`: one row per token with derived `country`, `os_family`, `is_new_user_login`, `lifetime_days` and a `device_shared` flag. `v_token_daily` aggregates it by platform × country × new/returning.
  - `v_signin_outcome`: sign-in chain → accepted flag → token within 1 or 7 days (for F23), recipient hashed.
  - `v_birthday_calendar`: counts by month/day × country × gender.
- **Metric types**: range metrics (signups, gift-acquired signups, deletions, returning-login users), snapshot metrics (birthday audience, legacy states, live base), funnels (signup verification, gift-claim verification) and top-N breakdowns (country, language, platform).
- **Guardrails in definitions**:
  - Every signup-trend metric declares `valid_from` and warns across 2025-05 (id gap / redesign) and 2024-08 (`is_app_user`).
  - Login metrics declare "floor, not MAU", and window_start is 2026-07-13 (app) or 2026-08-29 (web). They must be split by app vs web, because of the 30-day web vs 548-day app token lifetime.
  - Gift-acquired metrics declare `valid_from: 2024-08-05`, the start of the gift-claim log.
  - Any segment deletion comparison uses the survived-day-1 denominator.
  - `2fa_account_verification` is labelled "alternate-email / gift-claim verification".

**Plugin `ecom_orders`** (after grant) contributes `order`, `guest`, `guest_merge`, `occasion_line` and keeps its user resolution **inside** the DB through `users_userprofile.cognito_id`, exposed as a hash. **Plugins `emapi_stores` / `ecomweb_stores`** (after grant) contribute the user-profile mirrors, but only as hashed username, platform, app_version, type and has_*_id, plus `brands_occasion` as a dimension.

---

## 5. Grants needed (PII-safe)

| DB.table | Columns | PII-safe form |
|---|---|---|
| orders `users_userprofile` | user_id, cognito_id, trusted_user, is_deleted, created_on | `md5(cognito_id)` only; never raw |
| orders `order_order` | id, user_id, guest_id, date_placed, status, platform, region_id, total_incl_tax (reporting currency via lines) | no user_email/guest_email/user_name/phone/session_id |
| orders `order_orderlinepersonalisedetail` | line_id, occasion_code, is_reminder_added, delivery_date, delivery_type, created_on | recipient email/phone excluded |
| orders `order_line` | id, order_id, product_id, offer_code, is_offer_applied | — |
| orders `users_guestuser`, `users_mergeduser`, `basket_mergedbasket` | guestuser: id, platform, created_on, last_accessed, is_active; mergeduser: guest_id, user_id, created_on; mergedbasket all | email/username/session hashed or excluded |
| emapi `users_user` | id, md5(username), date_joined, last_login, platform, app_version, is_app_user, type, has_google_id/has_apple_id/has_facebook_id (derived), is_fraud, is_deleted | no email/phone/UA/IP; `os_family` derived from UA |
| emapi `emapi_generics_client_mobileappplatformversion`, `brands_occasion` | all (config) | — |
| ecomweb `users_cognitouser` | id, md5(username), date_joined, platform, app_version, is_app_user, type, is_deleted | same exclusions |
| ecomweb `configurations_lastviewedbrand` | md5(username), brand_id, store_id, created_on | hashed username |
| `ygag_mailengine_aps_db` / `ygag_smsengine_db` (new source) | OTP send/delivery status, provider, latency, language | message body and recipient excluded; join via OTP `reference_id` |
| `ygag_ecom_gifts_db` (new source) | gift id, order id, recipient-email hash, claimed/redeemed status and dates | hash only |

---

## 6. Risks and data-quality traps

1. **Cutovers**:
   - `type` died in Oct 2023, social ids in Dec 2024, and `platform` has not been populated since 2024.
   - `is_app_user` was redefined in Aug 2024.
   - May 2025 brought the signup redesign: the id gap closed and gender became mandatory. Nov 2025 brought birthday capture.
   - Every lifecycle trend that crosses these dates is wrong unless it is annotated.
2. **31-day OTP retention and 1–2.5 month token retention.** Funnels and returning-login metrics have no history until atlas snapshots them daily. Build the snapshot job first.
3. **Tokens are not activity, and platforms are not comparable.** App tokens last 548 days and web tokens 30 days (U17). Returning-login rates are floors, and web rates are inflated by forced monthly re-login. Never label them MAU or DAU, and never compare web vs app, or cohorts with different web mixes, on the blended rate.
4. **`is_valid` is not success.** Count chains, not true rows. Sign_up and sign_in chains can hold several true codes.
5. **`last_login` is a legacy fossil.** Using it for dormancy would mark 94% of users dormant and 57k legacy users as "last seen 2014–2024".
6. **Shell legacy accounts** (110,937): excluding them as "never active" is now wrong (0.93% reactivate). Report them separately rather than excluding them.
7. **The birthday 01/01 default** (9,940) and the elevated day-1 counts inflate January and day-1 triggers. Parse `0000/DD/MM` explicitly and never cast it to a date.
8. **The gift-acquired signal is a lower bound and left-censored.** It only captures claims into an alternate email, the log starts in Jul/Aug 2024 (U16), and it is app-flagged. Do not call it "all recipient signups", and never compute all-time shares across the log start.
9. **OTP↔user joins are PII joins** (email/phone). Do them only inside the DB, in views that emit hashes or flags.
10. **Deletion timing uses `modified_on`.** It is an upper bound on time-to-delete. There is no deleted_at column.
11. **Numeric user ids do not join across DBs.** Resolve to the `username` UUID in each DB, and use `cognito_id` in orders.
12. **Live-replica drift** of about 0.1% during the day. Stamp as-of time on every number.
13. **Guest-merge tables** have no UNIQUE constraints and nullable keys. Count DISTINCT guest_id with both keys non-null.
14. **`2fa_account_verification` naming** misleads analysts into reading it as login 2FA. The registry must relabel it.
15. **Survivorship in segment comparisons.** Segments defined by post-signup behaviour (gift claim, alternate email, phone change) cannot have day-1 deletions. Compare them against day-1 survivors only (U19), otherwise quality gaps are inflated (3.7x raw vs 2.0x adjusted).

---

## Appendix: SQL provenance (all `atlasq.sh ygag_ecom_users_db` unless noted; U1–U15 run 2026-09-29 13:30–14:10 UTC, U16–U25 and C1–C2 run around 15:00 UTC)

```sql
-- U1 gift-claim timing vs signup [exact]
with g as (select a.user_id, min(a.timestamp) first_gift from users_useridentityactivitylog a where a.activity='secondary_email_added_via_gift' group by 1)
select case when g.first_gift < u.date_joined then 'before_join' when g.first_gift - u.date_joined <= interval '1 hour' then '<=1h' when g.first_gift - u.date_joined <= interval '1 day' then '1h-1d' when g.first_gift - u.date_joined <= interval '30 days' then '1-30d' when g.first_gift - u.date_joined <= interval '365 days' then '30-365d' else '>365d' end b, count(*) users, count(*) filter (where u.is_deleted) deleted
from g join users_user u on u.id=g.user_id group by 1 order by 1;
-- <=1h 23,994 | 1h-1d 2,743 | 1-30d 4,320 | 30-365d 10,770 | >365d 17,669

-- U2 monthly gift-acquired signups [exact]
with g as (select a.user_id, min(a.timestamp) first_gift, count(*) n from users_useridentityactivitylog a where a.activity='secondary_email_added_via_gift' group by 1)
select to_char(date_trunc('month',u.date_joined),'YYYY Mon') m, count(*) signups,
 count(g.user_id) filter (where g.first_gift between u.date_joined and u.date_joined + interval '1 day') gift_acq_1d,
 count(g.user_id) filter (where g.first_gift between u.date_joined and u.date_joined + interval '1 hour') gift_acq_1h,
 count(g.user_id) gift_ever, count(*) filter (where u.is_app_user) app,
 count(g.user_id) filter (where g.first_gift between u.date_joined and u.date_joined + interval '1 day' and u.is_app_user) gift_acq_app
from users_user u left join g on g.user_id=u.id where u.date_joined >= '2024-08-01' group by date_trunc('month',u.date_joined) order by date_trunc('month',u.date_joined);
-- e.g. 2024 Dec 29,411 / 1,851; 2026 Sep 23,900 / 892; gift_acq_app = gift_acq_1d in every month but 2025 Sep (865/866)

-- U3 sign_up OTP chain length vs registration [exact; in-DB PII join, aggregates only]
with r as (select t.id, t.auth_type, lower(t.email) em, t.phone_number ph, t.created_on, v.is_valid,
  case when t.created_on - lag(t.created_on) over (partition by coalesce(t.email,'')||'|'||coalesce(t.phone_number,'') order by t.created_on, t.id) <= interval '10 minutes' then 0 else 1 end newc
 from notifications_twofactorauth t join notifications_twofactorauthverification v on v.reference_id_id=t.id where t.source='sign_up'),
c as (select *, sum(newc) over (partition by coalesce(em,'')||'|'||coalesce(ph,'') order by created_on, id rows unbounded preceding) cid from r),
ch as (select coalesce(em,'')||'|'||coalesce(ph,'') k, cid, min(auth_type) at, max(em) em, max(ph) ph, min(created_on) st, count(*) codes, bool_or(is_valid) ok from c group by 1,2),
j as (select ch.*, coalesce(ue.date_joined, up.date_joined) dj, coalesce(ue.id, up.id) uid from ch left join users_user ue on ch.em is not null and lower(ue.email)=ch.em left join users_user up on ch.ph is not null and up.phone_number=ch.ph)
select case when at='email' then 'email' else 'phone' end chan, case when codes=1 then '1' when codes=2 then '2' when codes<=4 then '3-4' else '5+' end codes_b, count(*) chains,
 count(*) filter (where ok) accepted, count(uid) filter (where dj >= st - interval '1 minute') registered_after, count(uid) filter (where dj < st - interval '1 minute') preexisting,
 percentile_cont(0.5) within group (order by extract(epoch from dj-st)) filter (where dj >= st - interval '1 minute') med_sec_to_join
from j group by 1,2 order by 1,2;
-- email 1: 15,896/12,832 (54 s); 2: 1,694/961; 3-4: 639/331; 5+: 238/129
-- phone 1: 25,652/24,586 (12 s); 2: 683/434; 3-4: 93/52; 5+: 26/17

-- U4 30-day new-token rate by cohort x legacy state [exact]
with t as (select user_id, count(*) toks, bool_or(user_platform='WEB') web, bool_or(user_platform like 'app%') app from users_cognitoissuedtokens where created_on >= '2026-08-30' group by 1),
m as (select distinct user_reference, bool_or(request_status) over (partition by user_reference) rs from users_migratedtransactionlog)
select case when u.date_joined < '2023-05-09' then 'a_pre_migration' when u.date_joined < '2024-01-01' then 'b_2023' when u.date_joined < '2025-01-01' then 'c_2024' when u.date_joined < '2026-01-01' then 'd_2025' when u.date_joined < '2026-07-01' then 'e_2026H1' when u.date_joined < '2026-08-30' then 'f_2026JulAug' else 'g_last30d' end cohort,
 case when m.user_reference is null then 'native' when m.rs then 'linked' else 'shell' end legacy,
 count(*) live_users, count(t.user_id) with_token_30d, count(t.user_id) filter (where t.web) web, count(t.user_id) filter (where t.app) app
from users_user u left join t on t.user_id=u.id left join (select distinct user_reference, rs from m) m on m.user_reference=u.username
where not u.is_deleted group by 1,2 order by 1,2;
-- shell 2023: 105,501 / 981; native 2023 67,040 / 604; linked 2023 31,879 / 509; 2024 263,665 / 2,424; 2025 275,942 / 3,020; last30d 24,821 / 24,354

-- U5 upcoming birthdays (live, usable, 01/01 excluded) [exact]
with b as (select u.*, substr(birthdate,6,2)::int dd, substr(birthdate,9,2)::int mm from users_user u where birthdate ~ '^0000/\d{2}/\d{2}$' and not is_deleted),
v as (select *, make_date(2026, mm, least(dd, extract(day from (make_date(2026,mm,1)+interval '1 month - 1 day'))::int)) bd26 from b where mm between 1 and 12 and dd between 1 and 31 and not (dd=1 and mm=1))
select case when country_of_residence in ('SA','AE') then country_of_residence else 'other' end c, count(*) with_bday,
 count(*) filter (where bd26 between date '2026-09-30' and date '2026-10-29') next30d, count(*) filter (where bd26 between date '2026-09-30' and date '2026-10-06') next7d,
 count(*) filter (where gender='female') female, count(*) filter (where gender='male') male
from v group by rollup(1) order by 2 desc;
-- total 351,315 | 31,004 | 7,411 | female 101,517

-- U6 birthday / gender capture by signup month [exact]
select to_char(date_trunc('month',date_joined),'YYYY Mon') m, count(*) n, count(*) filter (where birthdate ~ '^0000/\d{2}/\d{2}$') bday, count(*) filter (where birthdate ~ '^0000/\d{2}/\d{2}$' and is_app_user) bday_app, count(*) filter (where is_app_user) app,
 count(*) filter (where coalesce(gender,'') in ('male','female')) gender_known, count(*) filter (where birthdate='0000/01/01') jan1
from users_user where date_joined >= '2025-01-01' group by date_trunc('month',date_joined) order by date_trunc('month',date_joined);
-- gender 2025 Apr 3,141/22,384 -> May 21,249/25,192 -> Jun 25,239/25,239; birthday 2025 Oct 4,785/21,925 -> Nov 10,303/24,649 -> Dec 14,968/28,186

-- U7 verification channel of recent signups (in-DB PII join) [exact]
with e as (select distinct lower(email) em from notifications_twofactorauth where source='sign_up' and email is not null and email<>''),
p as (select distinct phone_number ph from notifications_twofactorauth where source='sign_up' and phone_number is not null and phone_number<>'')
select case when u.country_of_residence in ('SA','AE','QA','KW','OM','BH') then u.country_of_residence else 'other' end c, u.is_app_user,
 count(*) n, count(*) filter (where e.em is not null and p.ph is not null) both, count(*) filter (where e.em is not null and p.ph is null) email_only, count(*) filter (where e.em is null and p.ph is not null) phone_only, count(*) filter (where e.em is null and p.ph is null) neither
from users_user u left join e on e.em=lower(u.email) left join p on p.ph=u.phone_number where u.date_joined >= '2026-08-31' group by 1,2 order by 3 desc;
-- totals: 24,555 | both 12,972 | email_only 21 | phone_only 11,251 | neither 311

-- U8 signups by country per year [exact]
select extract(year from date_joined)::int y, case when country_of_residence in ('SA','AE','QA','KW','OM','BH','IN','EG','GB','US') then country_of_residence when country_of_residence is null or country_of_residence='' then 'null' else 'other' end c, count(*) n, count(*) filter (where is_deleted) del
from users_user where date_joined >= '2024-01-01' group by 1,2 order by 1,3 desc;

-- U9 signups by ISO weekday, Dubai time, 2025-10-01..2026-09-27 [exact]
select extract(isodow from date_joined at time zone 'Asia/Dubai')::int dow, count(*) n, count(*) filter (where country_of_residence='SA') sa, count(*) filter (where country_of_residence='AE') ae
from users_user where date_joined >= '2025-10-01' and date_joined < '2026-09-28' group by 1 order by 1;

-- U10 chain acceptance by flow x channel x language [exact]
with r as (select t.id, t.source, t.language, t.auth_type, coalesce(t.email,'')||'|'||coalesce(t.phone_number,'') k, t.created_on, v.is_valid,
  case when t.created_on - lag(t.created_on) over (partition by coalesce(t.email,'')||'|'||coalesce(t.phone_number,''), t.source order by t.created_on, t.id) <= interval '10 minutes' then 0 else 1 end newc
 from notifications_twofactorauth t join notifications_twofactorauthverification v on v.reference_id_id=t.id where t.source in ('sign_up','sign_in','2fa_account_verification')),
c as (select *, sum(newc) over (partition by k, source order by created_on, id rows unbounded preceding) cid from r),
ch as (select source, k, cid, min(auth_type) at, (array_agg(language order by created_on))[1] lang, count(*) codes, bool_or(is_valid) ok from c group by 1,2,3)
select source, case when at='email' then 'email' else 'phone' end chan, lang, count(*) chains, count(*) filter (where codes>=2) resend, count(*) filter (where ok) accepted from ch group by 1,2,3 order by 1,2,3;
-- 2fa email ar 987/330/454, en 2,582/505/1,905; sign_up email ar 3,882/650/3,044, en 14,588/1,921/12,482; sign_up phone ar 5,814/129/5,619, en 20,643/673/19,554

-- U10b OTP language by flow and phone prefix [exact]
with r as (select t.source, t.language, case when t.phone_number like '+966%' then 'SA' when t.phone_number like '+971%' then 'AE' when t.phone_number like '+%' then 'other_phone' else 'email' end c, v.is_valid
 from notifications_twofactorauth t join notifications_twofactorauthverification v on v.reference_id_id=t.id)
select source, c, count(*) n, count(*) filter (where language='ar') ar, count(*) filter (where is_valid) valid, count(*) filter (where language='ar' and is_valid) ar_valid
from r where source in ('sign_up','sign_in','2fa_account_verification') group by 1,2 order by 1,3 desc;
-- sign_up SA phone 14,774 (ar 5,739); AE phone 8,829 (ar 35)

-- U11 30-day token rate by identity-event class [exact]
with a as (select user_id, bool_or(activity='secondary_email_added_via_gift') gift, bool_or(activity='secondary_email_added') self, bool_or(activity='secondary_email_removed') rem, bool_or(activity='updated_phone_number') phone, count(*) filter (where activity='secondary_email_added_via_gift') ngift from users_useridentityactivitylog group by 1),
t as (select distinct user_id from users_cognitoissuedtokens where created_on >= '2026-08-30')
select case when a.user_id is null then 'no_identity_events' when a.gift and a.self then 'gift+self' when a.gift then 'gift_only' when a.self then 'self_only' else 'other(phone/removed)' end cls,
 count(*) users, count(t.user_id) token_30d, count(*) filter (where u.date_joined < '2026-08-30') older_users, count(t.user_id) filter (where u.date_joined < '2026-08-30') older_token_30d,
 count(*) filter (where a.ngift >= 2) multi_gift, count(*) filter (where a.phone) phone_changed
from users_user u left join a on a.user_id=u.id left join t on t.user_id=u.id where not u.is_deleted group by 1 order by 2 desc;
-- older: none 874,086/9,184; gift_only 57,653/950; self_only 14,239/303; other 2,858/77; gift+self 539/19

-- U12 two-week return by first-token platform (joined 2026-08-30..09-14) [exact]
with u as (select id, date_joined from users_user where date_joined >= '2026-08-30' and date_joined < '2026-09-15' and not is_deleted),
f as (select distinct on (t.user_id) t.user_id, t.user_platform p, t.created_on from users_cognitoissuedtokens t join u on u.id=t.user_id order by t.user_id, t.created_on),
r as (select t.user_id, min(t.created_on) first_ret, bool_or(t.user_platform<>f.p) switched from users_cognitoissuedtokens t join u on u.id=t.user_id join f on f.user_id=t.user_id where t.created_on > u.date_joined + interval '1 day' group by 1)
select coalesce(f.p,'no_token') first_platform, count(*) users, count(r.user_id) returned_after_d1, count(r.user_id) filter (where r.first_ret <= u.date_joined + interval '7 days') ret_by_d7, count(r.user_id) filter (where r.switched) switched_platform
from u left join f on f.user_id=u.id left join r on r.user_id=u.id group by 1 order by 2 desc;
-- ios 4,928/111/53/43; android 2,637/108/59/29; WEB 2,306/156/87/88; no_token 211

-- U13 gift-acquired vs organic (2025-01-01..2026-08-29 signups) [exact]
with g as (select user_id, min(timestamp) fg from users_useridentityactivitylog where activity='secondary_email_added_via_gift' group by 1),
t as (select user_id, count(*) n from users_cognitoissuedtokens where created_on >= '2026-08-30' group by 1)
select case when g.fg between u.date_joined and u.date_joined + interval '1 day' then 'gift_acquired' when g.fg is not null then 'gift_later' else 'no_gift_claim' end cls,
 count(*) users, count(*) filter (where u.is_deleted) deleted, count(t.user_id) filter (where not u.is_deleted) token_30d,
 count(*) filter (where u.birthdate ~ '^0000/') bday, count(*) filter (where u.gender='female') female, count(*) filter (where u.country_of_residence='SA') sa, count(*) filter (where u.country_of_residence='AE') ae
from users_user u left join g on g.user_id=u.id left join t on t.user_id=u.id where u.date_joined >= '2025-01-01' and u.date_joined < '2026-08-30' group by 1 order by 2 desc;
-- no_gift 436,289/7,775/5,288 (SA 218,609, AE 163,194); gift_acquired 20,007/97/197 (SA 7,934, AE 10,050); gift_later 8,533/27/218

-- U14a who receives 2fa_account_verification codes (in-DB PII join) [exact]
with f as (select lower(email) em, min(created_on) first_req, count(*) n from notifications_twofactorauth where source='2fa_account_verification' and email is not null group by 1),
s as (select lower(alternate_email) ae, min(created_on) sc, bool_or(not is_deleted) live from users_secondaryuseridentity group by 1),
b as (select distinct lower(value) v from core_blacklisteduserdetail where type='user_email')
select count(*) recipients, count(s.ae) is_secondary_email, count(s.ae) filter (where s.sc >= f.first_req - interval '1 minute') secondary_added_after_req,
 count(u.id) is_primary, count(b.v) blacklisted_email, count(*) filter (where s.ae is null and u.id is null) unmatched
from f left join s on s.ae=f.em left join users_user u on lower(u.email)=f.em left join b on b.v=f.em;
-- 3,182 | 2,284 | 2,284 | 41 | 2 | 857
-- (companion query: tenure of primary-email matches -> 41 recipients, all joined <=1 day before; 3,141 no primary user)

-- U14b alternate emails added in the OTP window, by path, with/without 2fa OTP [exact]
with f as (select lower(email) em, min(created_on) first_req from notifications_twofactorauth where source='2fa_account_verification' and email is not null group by 1),
s as (select s.user_id, lower(s.alternate_email) ae, s.created_on sc from users_secondaryuseridentity s where s.created_on >= '2026-08-29 20:00'),
a as (select user_id, activity, timestamp from users_useridentityactivitylog where timestamp >= '2026-08-29 20:00' and activity in ('secondary_email_added','secondary_email_added_via_gift'))
select a.activity, count(distinct s.ae) sec_emails, count(distinct s.ae) filter (where f.em is not null) with_2fa_otp, count(distinct s.ae) filter (where f.em is null) without_2fa_otp
from s join a on a.user_id=s.user_id and abs(extract(epoch from a.timestamp - s.sc)) < 5 left join f on f.em=s.ae group by 1;
-- via_gift 1,857 / 1,841 / 16; self 512 / 443 / 69

-- U15 signup-to-soft-delete gap, joiners since 2025-06-01 [exact]
select case when modified_on - date_joined <= interval '1 hour' then 'a<=1h' when modified_on - date_joined <= interval '1 day' then 'b1h-1d' when modified_on - date_joined <= interval '7 days' then 'c1-7d' when modified_on - date_joined <= interval '30 days' then 'd7-30d' when modified_on - date_joined <= interval '180 days' then 'e30-180d' else 'f>180d' end gap,
 count(*) n, count(*) filter (where is_app_user) app, count(*) filter (where country_of_residence='SA') sa, count(*) filter (where country_of_residence='AE') ae
from users_user where is_deleted and date_joined >= '2025-06-01' group by 1 order by 1;
-- <=1h 2,399 | 1h-1d 1,013 | 1-7d 873 | 7-30d 510 | 30-180d 619 | >180d 230

-- U16 identity-activity log extents [exact] (dates via to_char to survive redaction)
select activity, to_char(min(timestamp),'Mon YYYY') mn, to_char(max(timestamp),'Mon DD YYYY') mx from users_useridentityactivitylog group by 1 order by 1;
-- secondary_email_added Jul 2024 | via_gift Aug 2024 | removed Jul 2024 | updated_phone_number Jan 2025 (all through Sep 29 2026)
with g as (select user_id, min(timestamp) fg from users_useridentityactivitylog where activity='secondary_email_added_via_gift' group by 1)
select to_char(min(u.date_joined),'Mon DD YYYY'), count(*) from users_user u join g on g.user_id=u.id where g.fg between u.date_joined and u.date_joined + interval '1 day';
-- Aug 05 2024 | 26,737

-- U17 token lifetime by platform [exact]
select user_platform, count(*) n, percentile_cont(0.5) within group (order by extract(epoch from expires_at-created_on)/86400) med_days from users_cognitoissuedtokens group by 1;
-- app-ios 32,198 / 547.86 | app-android 16,814 / 547.86 | WEB 10,853 / 30.00 | UNACCOUNTED 168 / 547.86 ; first tokens: android Jul 13, ios Jul 15, UNACCOUNTED Aug 01, WEB Aug 29 2026

-- U18 uncensored gift-claim timing, joiners since log start [exact]
with g as (select user_id, min(timestamp) fg from users_useridentityactivitylog where activity='secondary_email_added_via_gift' group by 1)
select case when g.fg < u.date_joined then 'before' when g.fg <= u.date_joined + interval '1 day' then 'le1d' when g.fg <= u.date_joined + interval '30 days' then '1-30d' else 'gt30d' end b, count(*)
from g join users_user u on u.id=g.user_id where u.date_joined >= '2024-08-05' group by 1;
-- le1d 26,737 | 1-30d 4,271 | gt30d 7,907 (68.7% / 11.0% / 20.3%)

-- U19 survivorship-adjusted deletion (2025-01-01..2026-08-29 signups) [exact]
with g as (select user_id, min(timestamp) fg from users_useridentityactivitylog where activity='secondary_email_added_via_gift' group by 1)
select case when g.fg between u.date_joined and u.date_joined + interval '1 day' then 'gift_acquired' when g.fg is not null then 'gift_later' else 'no_gift_claim' end cls, count(*) users, count(*) filter (where u.is_deleted) deleted,
 count(*) filter (where u.is_deleted and u.modified_on - u.date_joined <= interval '1 day') del_le1d,
 count(*) filter (where not (u.is_deleted and u.modified_on - u.date_joined <= interval '1 day')) survived_1d,
 count(*) filter (where u.is_deleted and u.modified_on - u.date_joined > interval '1 day') del_after1d
from users_user u left join g on g.user_id=u.id where u.date_joined >= '2025-01-01' and u.date_joined < '2026-08-30' group by 1;
-- no_gift 436,289 / 7,775 / 4,504 / 431,785 / 3,271 (0.76%) | gift_acquired 20,007 / 97 / 20 / 19,987 / 77 (0.39%) | gift_later 8,533 / 27 / 0 / 8,533 / 27

-- U20 active-blacklist overlay by acquisition class (in-DB PII join, counts only) [exact]
with g as (...as U19...),
be as (select distinct lower(value) v from core_blacklisteduserdetail where type='user_email' and not is_removed),
bd as (select distinct lower(value) v from core_blacklisteduserdetail where type='user_domain' and not is_removed),
bm as (select distinct value v from core_blacklisteduserdetail where type='user_mobile_no' and not is_removed),
u as (select u.*, <cls as U19> cls from users_user u left join g on g.user_id=u.id where u.date_joined >= '2025-01-01' and u.date_joined < '2026-08-30')
select cls, count(*), count(*) filter (where exists (select 1 from be where be.v=lower(u.email))) bl_email,
 count(*) filter (where exists (select 1 from bd where bd.v=lower(split_part(u.email,'@',2)))) bl_domain,
 count(*) filter (where exists (select 1 from bm where bm.v=u.phone_number or bm.v=ltrim(u.phone_number,'+'))) bl_mobile from u group by 1;
-- no_gift 436,289 / 528 / 2,427 / 382 | gift_acquired 20,007 / 1 / 2 / 1 | gift_later 8,533 / 5 / 2 / 5

-- U21 token-era risk overlay (joined 2026-07-15..09-21) [exact]
with g as (...), ds as (select device_signature from users_cognitoissuedtokens where device_signature is not null and device_signature<>'' group by 1 having count(distinct user_id)>=2),
t as (select user_id, bool_or(coalesce(request_meta->>'COUNTRY','') not in ('United Arab Emirates','Saudi Arabia','Qatar','Kuwait','Oman','Bahrain')) out_gcc, bool_or(ds.device_signature is not null) shared_dev from users_cognitoissuedtokens c left join ds using (device_signature) group by 1),
u as (select u.id, u.is_deleted, <cls> cls from users_user u left join g on g.user_id=u.id where u.date_joined >= '2026-07-15' and u.date_joined < '2026-09-22')
select cls, count(*), count(t.user_id) with_tok, count(*) filter (where t.out_gcc), count(*) filter (where t.shared_dev), count(*) filter (where is_deleted) from u left join t on t.user_id=u.id group by 1;
-- no_gift 41,241 / 28,730 / 2,755 / 155 / 557 | gift_acquired 1,763 / 1,403 / 131 / 0 / 2 | gift_later 318 / 244 / 28 / 0 / 0

-- U22 sign_in chain outcome -> later token (chains started > 8 days ago; in-DB PII join, counts only) [exact]
-- chain rule as U3 (10-minute gap, partition by email|phone), source='sign_in'; user match by lower(email), else phone
select chan, ok, count(*) chains, count(uid) matched,
 count(*) filter (where exists (select 1 from users_cognitoissuedtokens k where k.user_id=j.uid and k.created_on between j.st and j.st + interval '1 day')) tok_1d,
 count(*) filter (where exists (select 1 from users_cognitoissuedtokens k where k.user_id=j.uid and k.created_on between j.st and j.st + interval '7 days')) tok_7d,
 count(*) filter (where not ok and exists (select 1 from ch c2 where c2.k=j.k and c2.st > j.st and c2.st <= j.st + interval '7 days')) retried_7d
from j group by 1,2;
-- email fail 791 / 770 / 386 / 426 / 191 | email ok 6,371 / 6,302 / 5,914 / 5,952 | phone fail 75 / 73 / 45 / 50 / 9 | phone ok 271 / 266 / 242 / 245
-- failed email, no token by d7: 770-426 = 344 (44.7%) vs ok 6,302-5,952 = 350 (5.6%); window is about 23 days of chains

-- U23 30-day token rate by cohort, app vs web-only [exact]
with t as (select user_id, bool_or(user_platform='WEB') web, bool_or(user_platform like 'app%') app from users_cognitoissuedtokens where created_on >= '2026-08-30' group by 1)
select <cohort as U4>, count(*) live, count(t.user_id) tok, count(t.user_id) filter (where t.app) app_tok, count(t.user_id) filter (where t.web and not t.app) web_only_tok
from users_user u left join t on t.user_id=u.id where not u.is_deleted group by 1;
-- pre_mig 24,360/312/212/99 | 2023 204,420/2,095/1,393/702 | 2024 263,665/2,425/1,662/763 | 2025 275,942/3,022/2,038/984 | 2026H1 143,692/1,855/1,203/652 | JulAug 37,296/829/529/299

-- U24 referral / campaign catalog search (users DB)
select table_name, column_name from information_schema.columns where table_schema='public' and (column_name ~* 'refer|invite|utm|campaign|promo|affiliat' or table_name ~* 'refer|invite|campaign|promo');
-- only users_promotionaldomainblacklist (promo-abuse domain list) and *reference_id / user_reference keys; no referral/invite/UTM

-- U25 column inventory: users_cognitoissuedtokens, core_blacklisteduserdetail (information_schema.columns)
-- tokens: id, created_on, modified_on, jti, token_hash, device_signature, user_platform, request_meta(jsonb), expires_at, user_id
-- request_meta keys (TABLESAMPLE 10%): COUNTRY, OS_TYPE, PLATFORM, IS_BOT (always false/null), BROWSER, USER_AGENT, IP_ADDRESS, TIMESTAMP, TOKEN_DERIVATIVES(_INDEX)
-- blacklist types: user_domain 3,645, user_email 3,775 across sources, user_mobile_no 718, user_ip 305, user_device_id 166, sms_country_code 117

-- C1 (ygag_ecom_orders_db, catalog only) pg_attribute users_guestuser
-- id, created_on, modified_on, email, username, session_id, db_session_id, extra, platform, last_accessed, note, is_active
-- C2 (ygag_ecomweb_stores_db, catalog only) configurations_lastviewedbrand: cols id, created_on, modified_on, username, brand_id, store_id; reltuples 59,921; seq_scan 4,652; idx_scan 3,261; n_live_tup 0
```

Figures reused from profiles cite their ids: users.md B4, B6, B8, B9, B11, C4, C5, C6; cross-db.md X34, X36.
