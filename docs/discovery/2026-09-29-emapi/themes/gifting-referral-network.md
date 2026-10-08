# Theme: Gifting network, referrals & virality

Built 2026-09-29 by the analytics-strategy unit. Inputs: `profiles/cross-db.md`, `profiles/users.md` (read in full), `profiles/orders-customer-catalog.md` and `profiles/orders-funnel.md` (gifting/personalisation/guest/offer sections read in full), `profiles/ecomweb-stores.md`, `profiles/emapi-stores.md`, `profiles/orders-integrations.md` (skimmed for occasions, Happy Cards, @Work, offers). New queries **G1–G22** (appendix) ran through `atlasq.sh` on 2026-09-29 between about 13:30 and 14:10 UTC. **G23–G29** were added in a critic-driven revision the same day, to correct I10/H1/I2/I8 and to add the H3 backtest, the re-engagement comparison and a data-driven freemail classifier. Data queries ran on `ygag_ecom_users_db` only. The other three DBs got catalog queries only.

**Revision log (critic pass).**
- I10: "79 users with ≥2 different emails" was wrong. It is **24** (79 have ≥2 claim *events*).
- H1: the 45% gap was the >1-day rate. The **7-day** gap is 2.2% vs 3.3% (35% lower).
- Headline/I4: now discloses the non-primary-email selection bias, and "acquisition channel" is corrected (large org domains skew to re-engagement).
- I2: the deletion baseline is now cohort-matched.
- I8: the AE base is now same-period.
- I6: the named test is pooled z.
- Hashing: unkeyed md5 is replaced by a keyed HMAC everywhere.
- New: I13, the §2a eval plan, and F19–F22.

**Evidence labels:** **VALIDATED** means a data query was run (G-numbers here, or X/C/B numbers in a profile appendix). **STRUCTURAL** means schema, catalog or `reltuples` only. **NEEDS-GRANT** means a hypothesis that needs unreadable data; the table.columns are named. **[inferred]** marks reasoning on top of a fact, not a measurement.

**Tooling note.** ISO dates come back redacted as `<phone>`, so every date below was produced with `to_char(..., 'YYYY "m" MM "d" DD')`. Local-time figures use `Asia/Dubai`.

---

## 0. Headline

The only readable record of the gifting network is one event in the identity service: `users_useridentityactivitylog.activity = 'secondary_email_added_via_gift'`. It fires when a recipient claims a gift that was sent to an email other than their account's primary email, and that email is then bound to the account. There have been **59,595 events for 59,496 users** since 2024-08-05 (G2). This is a **lower bound** on claims. It shows three things nobody has measured before:

1. **Gifts bring in new customers.** **40% of these claims (23,996) happen within 1 hour of the recipient signing up** (median 2.6 minutes), and 45% within 1 day (G3). This gift-acquired signup path accounts for **3.2–6.3% of all monthly signups** (G4), and it is a lower bound.
2. **Within this event, most claimed emails are work emails. That is partly because of how the event works.** **74% of claim events are on non-freemail domains** (72–74% under a data-driven classifier, G27). Nine org domains alone account for **25% of events**, and 83% of those recipients use a personal freemail primary (G9).
   - **Selection bias:** the event fires only when the gifted email is *not* the account's primary. 76% of signups since Aug 2024 have a freemail primary (G26), so gifts sent to personal freemail addresses mostly match the primary and leave no trace. The 74% describes this event, **not all gifts**.
   - The largest daily spikes are **single-company bursts**: on 2026-03-09 (Asia/Dubai), 85% of 730 claims came from one domain (G8).
   - **Corporate gifting is mainly re-engagement, with acquisition second.** Large org domains have the *lowest* new-user share (31.4% vs 44.0% for freemail, G9), and the biggest burst day had only 9.7% new users (G8).
   - Corporate senders **repeat on the same occasion calendar.** 8 of 20 season-burst domains burst again in the same season a year later, against 2 of 51 non-burst active domains (G25).
3. **Recipients do not come back, and a claim does not re-engage existing users either.**
   - Gift-acquired app users return after 7 days at **2.2% against 3.3%** for other app signups in the same cohort. That is 35% lower (G11; pooled two-proportion z = 2.24). After more than 1 day it is 2.5% vs 4.5% (z = 3.28).
   - Existing users (tenure >30 d) who claim return within 30 days at 1.2%, against 1.1% for matched non-claimers. That is no measurable lift (G24; n = 894).
   - The viral loop breaks at recipient → repeat user, and nothing in the atlas can see recipient → sender yet.

Everything about who sent the gift (orders, gifts, group gift, @Work) is **NEEDS-GRANT**. Measuring the sender → recipient edge needs one keyed join key: `HK(norm(order_orderlinepersonalisedetail.email_address))` = `HK(norm(via_gift comment))`. Here `HK` is a keyed HMAC-SHA256, with the key held outside the plugin and applied inside a DBA-owned view. It is **not** unkeyed md5, because contact and domain spaces are small enough to dictionary-reverse.

---

## 1. Insights

### I1. The gift-claim event is the only readable network edge. It is a lower bound. **VALIDATED** (G1, G2, G21)
- 59,595 `secondary_email_added_via_gift` events, 59,496 distinct users, 59,507 distinct emails. The actor is always the user (59,595/59,595). The `comment` is the claimed email, and 58,744 of the events (98.6%) still have a live `users_secondaryuseridentity` row for that email.
- Gift-created alternate emails are **81% of all live secondary identities** (58,744 of 72,650 users with a live alternate email; G21).
- The platform allows **one live alternate email per account** (`core_siteconfiguration.secondary_identity_per_account = 1`, `secondary_identity_enabled = true`; G21). The max live alternate emails per user is 1.
- **Why it is a lower bound [inferred]:**
  - A gift sent to the recipient's primary email creates no event.
  - A second gift to an already-bound alternate email creates no event.
  - A gift claimed by a guest or by phone creates no event.
  - Because of the one-alternate-email cap, a user who already has an alternate email probably cannot bind a second gifted email (see I10).

### I2. 40% of claims are gift-acquired signups; the recipient registers in order to claim. **VALIDATED** (G3)

| Claim time after signup | Claims | Median gap |
|---|---|---|
| ≤ 1 h | **23,996** (40.3%) | 2.6 min |
| 1 h – 1 d | 2,744 | 5.7 h |
| 1 – 7 d | 2,412 | 2.9 d |
| 7 – 30 d | 1,930 | 16 d |
| 30 d – 1 y | 10,793 | 216 d |
| > 1 y | 17,720 | 625 d |

The mode is the "sign up to open my gift" flow. About 30k claims (≈50%) come from existing customers who received a gift more than 30 days after joining. That population is the **re-engagement** side of gifting; I13 measures it.

Gift-acquired users are rarely deleted:
- 115 of 23,994 users (0.48%).
- The **cohort-matched expectation is 1.76%**: each gift-acquired user is weighted by the deletion rate of all signups in the same join month (G28).
- For reference, the since-Aug-2024 base is 1.73% and the all-time base is 2.2%. The all-time base is not comparable.
- So gift-acquired users are deleted at about **0.27× the rate of their cohort.** [inferred: the account holds a live gift balance, so there is a reason to keep it.]

### I3. Gift-acquired signups are 3.2–6.3% of monthly signups, and the share is drifting down. **VALIDATED** (G4)
- Aug–Dec 2024: 4.4% → 6.3%. The Dec 2024 peak had 5,042 claims and 1,851 gift-acquired signups.
- 2025: 3.5–5.9%. 2026: 3.2–5.3%. Sep 2026 is 3.74% (893 of 23,901).
- **Mar 2026:** 29,608 signups and 2,624 claims, but only 3.24% gift-acquired. The Ramadan 2026 corporate bursts (I5) went mostly to recipients who already had accounts: on 2026-03-09 only 9.7% were new users (G8).
- **Caveat:** the users-id cutover in May 2025 affects the denominator (signups before May 2025 are under-counted, users §5). The downward trend should be read against that cutover.
- **Time-zone note:** G4 buckets months in **UTC**, while the daily figures (G5–G8, G22) use **Asia/Dubai** days.
  - March 2026 is 2,624 claims in UTC and 2,626 in Asia/Dubai (G29).
  - 2026-03-09 is 730 claims as a Dubai day but only **400 as a UTC day**. The burst started around Dubai midnight, so about 330 claims fall on 2026-03-08 in UTC.
  - Using Dubai time throughout, 2026-03-09 = 730 / 2,626 = **27.8% of March**.
  - The governed metric must pick one zone. Recommendation: Asia/Dubai for daily and monthly business views, with UTC kept in storage.

### I4. Within the claim event, most claimed emails are org (work) emails, and a handful of companies dominate. **VALIDATED** for the event (G9, G26, G27). Generalising to all gifts is **NOT** supported (selection bias).

| Claim email domain class | Claims | Domains | New user ≤1 h | Recipient's primary is freemail |
|---|---|---|---|---|
| Freemail (21-domain list) | 15,202 (25.5%) | 21 | 44.0% | 8,309 |
| Org domain with ≥500 claims | **14,866 (24.9%)** | **9** | 31.4% | 12,359 (83%) |
| Org 100–499 | 8,978 | 46 | 40.5% | 7,248 |
| Org 10–99 | 13,018 | 439 | 40.4% | 10,602 |
| Org <10 | 7,531 | 4,018 | 49.6% | 6,081 |

- **Timing supports the work-email reading:** claims are weekday-heavy (Mon–Fri 8.8–9.8k each; Sat 5.9k, Sun 6.6k) and about 60% fall in 09–17h local time (G20). [inferred: work email read at work.]
- **Selection bias (material).** The event fires only when the claimed email differs from the account's primary email.
  - 76.2% of signups since Aug 2024 have a freemail primary (454,210 of 595,877; G26).
  - So a gift sent to a recipient's personal freemail usually matches the primary and creates **no event**. A gift sent to a work email usually does not match the primary, so it does create an event. [inferred] This is consistent with only 1.7–2.6% of org-domain claim events coming from users whose primary is on the same domain (G9: 298/14,866, 233/8,978, 239/13,018, 125/7,531).
  - The 74% org share therefore **overstates the org share of all gifts by an unknown amount.** It is a property of this event. The true mix needs the full recipient population (orders `order_orderlinepersonalisedetail.email_address` hashed, grant G-1).
- **Freemail classification, now data-driven (G27).** Rank the claim domains by distinct claimers and by how many users hold that domain as their *primary* (in-DB, names never returned).
  - All 21 hand-list domains have 10–62 primary holders per claimer.
  - Among the top 40 claim domains, every non-list domain is ≤ 8.1×.
  - Org share under three rules:

  | Consumer rule | Domains reclassified to consumer | Their claims | Org share |
  |---|---|---|---|
  | Hand list only | — | — | 74.5% |
  | primary holders ≥ 1,000 and ≥ 10× claimers | 3 | 56 | **74.4%** |
  | primary holders ≥ 200 and ≥ 5× claimers | 29 | 1,256 | **72.4%** |
  | primary holders ≥ 50 and ≥ 3× claimers (too loose: it catches companies whose staff register with a work email) | 177 | 7,565 | 61.8% |

  The hand list therefore misses little. Within-event org share is **72–74%**, with 62% as a loose floor. The dominant uncertainty is the selection bias above, not the list.
- **Acquisition vs re-engagement.**
  - Org_500+ domains have the **lowest** new-user share (31.4%, vs 44.0% for freemail and 49.6% for the long tail).
  - The largest burst day had 9.7% new users (G8).
  - Large-company gifting is therefore mainly **re-engagement of existing accounts**. It still produces acquisition in absolute terms. Org-domain claims are about 17.3k of the about 24.0k ≤1-h claims (≈72%) [arithmetic on G9 rates: 0.314×14,866 + 0.405×8,978 + 0.404×13,018 + 0.496×7,531 ≈ 17,300; freemail 0.44×15,202 ≈ 6,690]. The same selection bias applies to that count.
- **Reading:** a corporate gift sent to `name@company` gets claimed into a personal account, mostly an account that already exists. Corporate/@Work gifting is a hidden B2C touchpoint, mainly re-engagement and only secondarily acquisition. I13 shows the re-engagement does not yet turn into return visits.

### I5. The biggest claim spikes are single-company bursts timed to occasions. **VALIDATED** (G5–G8, G22); occasion mapping [inferred]
- The daily mean is 75.8 claims (median 64, p90 117, max 730, over 786 days).
- Top days, with the share taken by the day's largest domain:
  - 2026-03-09: 730 claims, **84.8%** one domain.
  - 2025-03-26: 724 claims, 76.2%.
  - 2025-03-27: 475 claims, 42.1%.
  - 2024-12-16: 391 claims, 67.3%.
  - 2026-04-09: 218 claims, 52.8%.
  - 2026-03-18: 192 claims, 54.2%.
  - 2025-09-09: 192 claims, 62.5%.
- A second spike type is **broad and multi-domain**: 2024-12-13 (575 claims, top domain 7.3%, 132 domains), 2024-12-12, 2025-06-26 (295 claims, 11.5%, 104 domains) and 2025-12-05.
- On spike days (≥170 claims) the average top-domain share is 37.6%, against 22.7% on normal days (G7).
- Calendar alignment [inferred, external calendar, not data]:
  - The Mar 2025 bursts fall in the last days of Ramadan 1446 (Eid al-Fitr ≈ 2025-03-30).
  - The Mar 2026 bursts fall inside Ramadan 1447.
  - 2025-06-26 ≈ Islamic New Year 1447.
  - The December clusters are year-end.
- **50 org domains had at least one burst day** (≥20 claims from that domain on one day): 165 burst-days, 7,281 claims. **11 of the 50 bursted in two or more calendar years, and 13 in two or more months.** 56 of the 165 burst-days fall in Feb–Apr and 33 in December (G22).
- **Season backtest (G25), now measured rather than targeted.**
  - Seasons (Asia/Dubai dates): Dec 2024, Ramadan window Feb–Apr 2025, Dec 2025, and Feb–Apr 2026.
  - A "burst domain" is a non-freemail domain with ≥20 claims on at least one day in the season.

  | From season → same season next year | Burst domains | Burst again | Still ≥20 claims (burst or not) | Baseline: non-burst active domains (≥20 claims) that burst next year |
  |---|---|---|---|---|
  | Dec 2024 → Dec 2025 | 10 | 4 (40%) | 6 (60%) | 0 / 27 |
  | Ramadan 2025 → Ramadan 2026 | 10 | 4 (40%) | 9 (90%) | 2 / 24 |
  | **Pooled** | **20** | **8 (40%)** | **15 (75%)** | **2 / 51 (3.9%)** |

  - Adjacent seasons of a different type repeat much less: Dec 2024 → Ram 2025 3/10, Ram 2025 → Dec 2025 1/10, and Dec 2025 → Ram 2026 1/7.
  - So corporate senders **repeat on the same occasion, not on any occasion.** A burst domain is about 10× more likely than a non-burst active domain to burst in the same season next year.
  - The sample is small (20 domain-seasons). Re-test each season.

### I6. Gift-acquired recipients return less than other signups. **VALIDATED** for logins; purchase is **NEEDS-GRANT** (G10, G11)
Cohort: app users who joined 2026-07-15 → 2026-08-31, not deleted.

| Group | Users | Any token | Returning login (>1 d after signup) | Returning after 7 d |
|---|---|---|---|---|
| Gift-acquired (claim ≤1 d of signup) | 1,208 | 850 (70%) | **30 (2.5%)** | 26 (2.2%) |
| Other app signups | 22,371 | 15,039 (67%) | **999 (4.5%)** | 744 (3.3%) |

- All 1,209 gift-acquired users in the cohort are `is_app_user`, against 82% of others (G10). **The claim flow is app-only.** [inferred]
- **Test:** pooled two-proportion z-test.
  - >1-day returning: 2.48% vs 4.47% (44% lower), **z = 3.28** (the unpooled Wald z is 4.23, which the earlier draft quoted).
  - >7-day returning: 2.15% vs 3.33% (**35% lower**), **z = 2.24** (Wald 2.70).
  - Both are significant at α = 0.05. The 7-day figure is the one to use as the RCT baseline.
- Tokens are a weak engagement proxy (app tokens live 548 days, users §5), but both groups share that bias.
- Whether recipients ever **buy** is invisible here (NEEDS-GRANT: orders `order_order.user_id` via `users_userprofile.cognito_id`).

### I7. Birthdays lift gift claims by 1.57× in the recipient's birth month. **VALIDATED** (G12)
- Scope: the 20,405 claims by users with a valid `0000/DD/MM` birthdate (the `0000/01/01` default excluded).
- **2,659 claims fall in the recipient's birth month, against 1,698 expected** from the claim-month × birth-month mix. That is **1.57× the expected rate**, or about 961 birthday-driven claims (4.7% of claims with a known birthday).
- 1,005 claims fall within ±3 days of the birthday. A uniform-within-month expectation is ≈ 391 [inferred approximation], so the lift is ≈ 2.6× near the day.
- Only 37% of users have a birthday stored (users §6), so this is a sampled view of a real occasion signal.

### I8. Recipient geography: the UAE and Qatar over-index on gift acquisition. **VALIDATED** (G16)
Gift-acquired users as a share of non-deleted signups since Aug 2024:

| Country | Share | Gift-acquired / signups |
|---|---|---|
| **QA** | **8.2%** | 1,318 / 16,090 |
| AE | 5.9% | 13,577 / 231,648 |
| BH | 5.5% | — |
| EG | 4.0% | — |
| KW | 3.9% | — |
| SA | 3.65% | 10,333 / 282,941 |
| GB | 1.5% | — |

**Same-period comparison (G26, G28):**
- AE is **50.8% of gift-acquired (≤1 d) users** (13,577 of 26,737, deleted included) against **39.4% of all signups since Aug 2024** (235,001 of 595,877, deleted included). Excluding deleted users on the base side gives 39.6%.
- Across all claimers (any tenure), AE is 52.6%, with or without deleted users.
- The earlier "53% vs 41% all-time base" mixed periods and deletion filters.

[inferred: the UAE corporate market drives it; see the I4 selection-bias caveat, since org-domain gifting is what this event sees best.]

### I9. Gift fraud is sender-side; the group-gift fraud stream stopped in May 2025; @Work blocks are domain-level. **VALIDATED** (G13–G15, cross-db X13/X15)
- **`ecom_gifts` blacklist:** 695 rows. The 652 UUID-referenced rows point to only **266 distinct users**, about 2.45 identifiers per user (email 288, mobile 269, device 138). **Only 1 of the 266 ever claimed a gift** via an alternate email, against 6% of the base. Gift blacklisting therefore targets senders or abusers, not gift recipients [inferred]. The stream is steady at 55–143 rows a quarter since 2024-Q2.
- **`ecom_groupgift`:** 70 rows (email 50, mobile 20). The last one is 2025-05; the Kafka consumer's last message is 2025-05-12. **The group-gift service stopped emitting fraud events in May 2025.** It was either retired or migrated off this topic (cause unknown). Any group-gift metric has to confirm that the product is still live.
- **`atwork`:** 29 rows (24 `user_domain`, 2026-07 → 2026-09), plus Kafka events from 2026-03-10. **None** of the 24 blocked domains appears among gift-claim domains, and there are 0 claims on the 7 promotional-blacklist domains (G15). @Work blocks are a B2B control and do not hit consumer recipients.
- 38 claims are on 5 currently blacklisted domains (G15): a small recipient-side exposure.

### I10. Identity-collision and cap signals in the claim graph (a small risk queue). **VALIDATED** (G19, G20, G21)
- **164 claims bound an email that is another account's primary email.** Two accounts now "own" the same address. These are duplicate or split identities, or gift interception.
- **31 claimed emails are bound across 2–3 different users** (63 users in total).
- **Multi-email claimers (corrected, G23):**
  - 79 users have ≥2 claim **events**. In 55 of them the same email was claimed again (remove → re-add cycles).
  - Only **24 users claimed with ≥2 distinct emails**, and 10 of those used a single domain. The earlier draft counted events in G19, not distinct emails; G20 already showed 22 + 1 + 1 = 24.
  - One user bound **19 distinct emails on one domain** despite the one-alternate-email cap. [inferred: a swap cycle of remove then add, i.e. gift harvesting by an employee or an admin mailbox.]
- **1,157 claimers later removed the gifted email**, after a median of 125 days. [inferred: job change or clean-up.] Their later gifts to that address will not auto-link.

### I11. What sits structurally behind the edge (orders, gifts, stores). **STRUCTURAL** (G17, G18; orders-funnel §2, orders-customer-catalog)
- **The recipient has no user id anywhere in orders.** `order_orderlinepersonalisedetail` (496,737 est) holds the recipient only as `email_address` vc(512) and `phone_number` vc(20). Its other columns:
  - `occasion_code` vc(10) and `greeting_code` vc(10);
  - `delivery_type` vc(20) NOT NULL, `delivery_date`, `delivery_time` and `delivery_time_zone`;
  - `is_reminder_added` (bool NOT NULL);
  - `line_id` (UNIQUE), with `created_by_id` indexed.
- There are **no indexes on the recipient columns**. A sender → recipient join therefore needs a hashed view or an extract, not live lookups.
- `order_orderlinequantitydetail` / `basket_basketquantitydetail` carry `is_buy_for_self`, `delivery_method`, `sender_name` (PII) and `personal_data_ref`. About 31–35% of lines are personalised (orders-funnel §6).
- **Guest senders:** there are 82.5–88.7k `users_guestuser` rows [est] against 1.23M orders. `users_mergeduser` (≤ about 3.7k rows, no UNIQUE) and `basket_mergedbasket` (≤ about 1.2k) are the only guest → registered links.
- **Referral data: none.** No column matching `referr|invite|utm|affiliate` exists in orders, ecomweb or emapi (orders-customer-catalog Q30, ecomweb A10, and G17). **Referral mechanics are not stored in any of the four DBs.** The nearest things are the Plus-offer promo codes (`offer_plusoffer.is_generic_promo_code` / `is_unique_promo_code`, `offer_offerpromocode` with 41 rows) and the loyalty points in youpay.
- **Happy Cards and generic cards (a viral loop, because the recipient chooses the brand):**
  - emapi: `brands_generic_brand_config` 3,381 [est] and `brands_generic_brand_item` 533,305 [est]; `brands_plusoffer_happy_cards` 132,977.
  - ecomweb: `brands_genericbrandslist` 56,857, read 2.17M times on the replica.
  - orders: `offer_plusoffer_happy_cards` 10,627.
  - The catalog also carries recipient-facing content: `receiver_redemption_details*` and `sender_redemption_details*` on `brands_brand` (emapi, ecomweb).
- **Channel flags:**
  - emapi `brands_brand`: `visible_to_corporate`, `visible_to_corporate_api`, `visible_to_specific_corporate`, `visible_to_at_work`, `visible_to_gift_shop`, `visible_to_sendatip`, `visible_to_mpos`, `visible_to_credit`.
  - ecomweb `core_siteconfiguration.atwork_enabled`.
  - `catalogue_store.visible_to_atwork`.
- **Occasions:**
  - emapi and ecomweb `brands_occasion` (55 rows in ecomweb) plus `brands_brandoccasion` (21) / `_brands` (142).
  - ecomweb `configurations_upcomingoccasion` has `reltuples = 0` but was **read 89,306 times** (ecomweb A14). This is not a real row count: `n_live_tup` is 0 for every table on this replica, and no SELECT is possible. [inferred] The "upcoming occasion" merchandising slot *may* be empty or dead. Confirming it needs a SELECT grant on that table.
  - AI greetings: `core_aigreetingmessages` (538) is a cache or pool keyed by (tone, relation, occasion), not a usage log.
- **Send-a-tip** (`user_tip_tip`, bound 500–1,100 rows) has `sender_id` and `receiver_phone_number`. It is a tiny P2P edge with `send_tip_gift_event_triggered`.
- **@Work consumption:** `kafka_atworkkafkadatalog` has about 1.70M rows [est] in orders and 1.72M in emapi (same topic). The @Work payloads are the B2B sender side of I4/I5 (NEEDS-GRANT).

### I12. The lower bound can be widened with data the users DB already has. **VALIDATED** (G2, users §6)
`users_useridentityactivitylog` also has `secondary_email_added` (16,593 self-added) and `secondary_email_removed` (3,824). A self-added work email followed by later gifts is invisible (I1). The ratio of self-added to gift-added alternate emails is about 1 : 3.6.

### I13. A gift claim does not re-engage existing users, as far as the login proxy can see. **VALIDATED** (G24; token proxy, underpowered)
- Cohort: existing app users who are not deleted, with tenure >30 days at their first claim between 2026-07-15 and 2026-08-28. There are **894 claimers**.
- Comparison group: every non-deleted app user with tenure >30 days at a fixed reference of 2026-08-06 who never claimed. There are **453,552**.
- Outcome: a Cognito token issued 1–30 days after the claim or reference date.

| Tenure | Claimers | Returned | Rate | Non-claimers | Returned | Rate |
|---|---|---|---|---|---|---|
| 30 d – 1 y | 381 | 5 | 1.31% | 187,607 | 1,811 | 0.97% |
| > 1 y | 513 | 6 | 1.17% | 265,945 | 3,183 | 1.20% |
| **All** | **894** | **11** | **1.23%** | **453,552** | **4,994** | **1.10%** |

- The pooled z is −0.37, so there is **no detectable lift**.
- Only 171 of 894 claimers (19%) had a token within ±1 day of their claim. So the claim itself often reuses an existing session and does not register as a "login" in this table. That makes this a weak proxy.
- A narrower window with a prior-activity stratum (claims 2026-08-13 → 08-28, n = 397) shows the same thing: 4 returned (1.0%) against about 1.3% for non-claimers.
- **Reading [inferred]:** the ~50% of claims from existing users (the larger half of the gifting population) are a touchpoint the business does not follow up. Nothing in this data shows a claim causing a return visit. Whether claimers *spend* the gift (redemption) or buy is NEEDS-GRANT (orders `order_order.user_id`; emapi redemption).
- **Power note:** with n = 894 at a 1.1% base, the minimum detectable lift at 80% power is roughly +1 pp (about 2×). Smaller effects need more claim months or the orders outcome.

---

## 2. Hypotheses (testable, for growth / CRM / B2B / product / risk)

| # | Hypothesis | Audience | Test (metric + comparison) | Data | Evidence |
|---|---|---|---|---|---|
| H1 | **Recipient activation gap.** Gift-acquired recipients (claim ≤1 d after signup) have a returning-login rate after 7 days about 35% lower than other app signups in the same cohort (2.2% vs 3.3%; the >1-day rate is 2.5% vs 4.5%, 44% lower), and a lower 30-day first-purchase rate. A post-claim onboarding push (brand discovery plus "send one back") within 24 h raises 30-day first purchase by at least 20% relative. | Growth, CRM | Holdout RCT on new gift-acquired users. Primary metric: 30-day first own order. Secondary: returning login after 7/30 d. Baseline 2.15% after 7 d (G11). Detecting +20% relative on login needs about 20k per arm (α = 0.05, 80% power), so login is a guardrail metric, not the primary. | Users DB (ready). Purchase needs orders `order_order(user_id, date_placed, status)` + `users_userprofile(user_id, HK(cognito_id))` | VALIDATED (login gap); NEEDS-GRANT (purchase) |
| H2 | **Corporate recipients are a latent B2C audience, mostly existing accounts.** Recipients who claim on an org domain but hold a freemail primary (≈ 36.3k claims; 50–69% of them claimed more than 1 h after signup, by domain class, G9) convert to their own consumer purchase at a lower rate than freemail recipients, **but** respond more to occasion-timed offers (Ramadan/Eid, birthday). Note that I13 shows no login lift from the claim itself. | Growth, B2B marketing | Compare 90-day first-order rate: org vs freemail recipients, stratified by new vs existing account, then an A/B occasion offer within the org segment. | G9 segment (ready) + orders purchase (grant) | STRUCTURAL + NEEDS-GRANT |
| H3 | **Corporate repeat calendar.** Backtest (G25): **8 of 20 (40%)** season-burst org domains burst again in the *same* season a year later, and 15 of 20 (75%) still send ≥20 claims. That compares with 2 of 51 (3.9%) for non-burst active domains. Cross-season repeat (Dec → Ramadan) is only 1–3 of 10. Forward hypothesis: pre-season outreach 4–6 weeks before the same season raises the burst-again rate from 40% to ≥55%, and claims per repeat domain by ≥20%. | B2B / @Work sales | Forward test: randomise the 2026 Dec-season burst list (n = 10 domains from Dec 2025, plus the Ramadan 2026 list for Ramadan 2027) into outreach vs control. Metric: burst-again rate and claims per domain in the season. The small n means pooling across seasons. | Users DB (ready); @Work orders for revenue (grant: `kafka_atworkkafkadatalog` status/created_on, @Work DBs) | VALIDATED (backtest rate); NEEDS-GRANT (revenue) |
| H4 | **Birthday trigger.** Recipients are 1.57× more likely to claim in their birth month (2.6× within ±3 days). A "birthday in 7 days" nudge to people who previously sent them a gift raises gifts to that recipient by at least 15%. | CRM | RCT on sender → recipient pairs where the recipient's birthday is known. Metric: gifts to that recipient in the ±7-day window. | Users birthdate (ready); pairs need the hashed recipient join (grant, G-1 below) | VALIDATED (lift); NEEDS-GRANT (pairs) |
| H5 | **Reciprocity loop / k-factor.** At least 8% of gift recipients send a gift within 60 days, and ≥25% of those send to the original sender (a reciprocal edge). Recipients from a burst (corporate) reciprocate less than P2P recipients. | Growth, leadership | k = (new senders among recipients) / senders, over rolling 60-day cohorts, split by P2P vs corporate recipient. | Orders `order_orderlinepersonalisedetail(HK(email_address), HK(phone_number), line_id, created_on, occasion_code)` + `order_line.order_id` + `order_order(user_id, guest_id, date_placed, status)`; users hashed email/phone/alt email | NEEDS-GRANT |
| H6 | **One-alternate-email cap loses claims.** Users who already hold a self-added alternate email (≈ 13.9k) cannot bind a second gifted work email, so they claim less, abandon, or swap emails. Visible swap behaviour is small: only 24 users bound ≥2 distinct emails (one with 19), and 55 re-claimed the same email (G23). Raising the cap to 2 increases claims per recipient. | Product | Claim-attempt success rate by "already has alt email", before and after a cap change. | Claim attempts in `ygag_ecom_gotagift_db` / `ygag_ecom_gifts_db` (new source) | NEEDS-GRANT |
| H7 | **Burst-day onboarding.** On corporate burst days only 10–50% of claimers are new (G8). Unprompted, existing-user claimers do **not** return more than matched non-claimers (1.23% vs 1.10%, G24). A same-day CRM follow-up to existing-user claimers (a "your gift is waiting: spend it at <brand>" push) doubles their 30-day return (to ≥2.5%) and raises redemption. | CRM | Holdout RCT on existing-user claimers (tenure >30 d), randomised by claim day. Primary metric: 30-day returning login (baseline 1.2%, G24; MDE about +1 pp at n ≈ 900 per arm, so run for about 2 months). Secondary: redemption and orders (grant). | Users DB tokens (weak, ready); orders (grant) | VALIDATED (no-lift baseline) + NEEDS-GRANT (orders) |
| H8 | **Business-hour delivery wins.** Gifts delivered to org emails between 09:00 and 11:00 local time are claimed within 1 h more often than gifts delivered in the evening. Scheduling corporate deliveries into that window raises same-day claims. | Product, B2B | Claim latency by `delivery_time` bucket (personalise detail) joined via the hashed recipient email to the claim timestamp. | Orders personalise detail (grant) + users claims (ready) | NEEDS-GRANT |
| H9 | **Occasion code drives virality.** Lines with `occasion_code` = birthday / Eid have a higher recipient → sender conversion than lines with no occasion, and `is_reminder_added = true` senders repeat to the same recipient next year at ≥30%. | CRM, product | Conversion and repeat by `occasion_code` and `is_reminder_added`. | Orders personalise detail (grant) | NEEDS-GRANT |
| H10 | **Guest senders who merge are the best seed.** Guest checkouts later merged to a registered account (`users_mergeduser`) produce more recipient signups per order than never-merged guests. | Growth | Gift-acquired signups per sending order, merged vs unmerged guest senders. | Orders `users_mergeduser`, `users_guestuser(id, created_on, platform)`, `order_order.guest_id` + hashed recipient join | NEEDS-GRANT |
| H11 | **Happy Card (generic) gifts convert recipients better.** Because the recipient chooses the brand, generic/Happy Card gifts produce a higher claim-to-own-purchase rate than single-brand cards. | Merchandising | Recipient 60-day purchase rate by `catalogue_product.is_generic` of the gifted line. | Orders `order_line.product_id`, `catalogue_product.is_generic`, + hashed recipient join | NEEDS-GRANT |
| H12 | **Qatar and UAE over-index on gift acquisition** (8.2% / 5.9% of signups vs 3.65% SA). Recipient-onboarding spend therefore has a higher return in QA/AE, and SA growth is less network-driven. | Growth, leadership | Gift-acquired share by country (monthly), CAC-equivalent comparison with ads. | Users DB (ready); ads spend (new source) | VALIDATED (shares) |
| H13 | **Identity collisions indicate interception or duplicate accounts.** Claims where the bound email is another account's primary email (164), or is shared across users (31 emails), have a higher later blacklist/fraud rate than baseline. | Risk | Blacklist hit rate within 180 d: collision cohort vs all claimers. | Users DB (ready; small n, so monitor) | VALIDATED (cohort exists) |

### 2a. Governance: eval coverage (the eval gate)

Every ready-now feature needs golden Q&A in `evals/goldens/` before merge. Each golden asserts the answer **and** the provenance chip (metric id, source, freshness, and the "lower bound" caveat). Proposed goldens, with values pinned to an as-of snapshot:

| Golden | Question | Expected behaviour |
|---|---|---|
| E1 (F1) | "How many gift claims were there in March 2026?" | 2,626 (Asia/Dubai month), metric `gift_claims`, and a chip that says **"lower bound: claims to non-primary emails only"** |
| E2 (F1) | "How many gifts did people receive in March?" | Must **not** answer with `gift_claims` as "gifts received". It answers the lower bound with that wording, or asks for clarification |
| E3 (F2) | "What share of September 2026 signups came from gifts?" | 3.74% (893 / 23,901), a lower bound, with the May-2025 cutover note when the range crosses it |
| E4 (F3/F20) | "Which companies send the most gifts?" | Returns only `org_<sid>` ids with k ≥ 50, never a domain or company name, and states the selection bias |
| E5 (F3) | "What share of gifts go to work emails?" | "74% of *claim events* (72–74% by classifier)". It must say the share of all gifts is unknown (selection bias) |
| E6 (F4) | "Was there a corporate gifting spike on 2026-03-09?" | Yes: 730 claims, top cluster 84.8%, 9.7% new users, day in Asia/Dubai |
| E7 (F19) | "Do gift claims bring existing users back?" | "No measurable lift (1.23% vs 1.10%, login proxy)", with the proxy caveat |
| E8 (F9/F8) | "What is our k-factor?" | Honest failure: explain that recipient → sender needs order data not yet connected. No number is invented |
| E9 (F18) | "How many referrals did we get last month?" | Honest failure: no referral data exists in any connected source |
| E10 (F22) | "Are gift-acquired users deleted less?" | 0.48% vs 1.76% cohort-matched expectation, not vs 2.2% |

Hypotheses H1, H3, H7 and H12 are ready-now. Their baselines (G11, G25, G24, G16) should be frozen as eval fixtures so that a metric-definition change which moves them fails the gate.

---

## 3. Atlas features

Readiness: **ready-now** = the users DB supports it today. **needs-grant** = in the four DBs but blocked. **needs-new-source** = gifts / gotagift / groupgift / @Work / ads DBs.

| id | Name | Type | What it does | Backing (plugin: tables) | Readiness | Effort | Impact |
|---|---|---|---|---|---|---|---|
| F1 | `gift_claims` | metric (range) | Gift claims into accounts per period, with provenance "lower bound: alt-email claims only" | users: `users_useridentityactivitylog` (activity = via_gift) | ready-now | S | 3 |
| F2 | `gift_acquired_signups` + `gift_acquired_signup_share` | metric (range) | Signups whose first gift claim is ≤1 h / ≤1 d after `date_joined`, and their share of signups; flags the May-2025 id cutover | users: `users_user`, `users_useridentityactivitylog` | ready-now | S | 5 |
| F3 | Corporate gifting radar | breakdown | Claims by domain class (freemail / org size buckets); top org clusters shown only as **opaque surrogate ids** (`org_0001`… from a DBA-held lookup table, or a keyed HMAC; never an unkeyed md5 of the domain, which is trivially reversible from a dictionary of company domains) with k ≥ 50, plus a burst-day count | users: activity log (derived `claim_domain_class`, `claim_org_sid`) | ready-now | M | 5 |
| F4 | Corporate burst alert | alert_trigger | **Rule:** daily claims (Asia/Dubai day) > p90 (117) **and** one non-freemail domain holds >40% of them. **Expected volume:** it would have fired on **20 of 786 days** (3 in 2024-Aug→Dec, 11 in 2025, 6 in 2026 to date), about 9 a year, clustered in Ramadan and December (G29). An absolute variant (≥50 claims from one domain and >40% share) fires 21 times. **Payload:** "cluster `org_<sid>`: N claims today, M new users, K existing, repeat-season flag (G25)". **Owner and action:** B2B account management owns it and confirms the client and account within 1 business day. CRM owns the same-day claimer follow-up (the H7 treatment arm). Silence/ack is tracked, and if three consecutive firings get no action the rule is reviewed. | users: activity log (daily rollup) | ready-now | S | 5 |
| F5 | Dormant gift recipients | segment | Gift-acquired users with no returning login after N days (the "claim-and-leave" audience for H1), exported as pseudonymous ids for CRM | users: activity log, `users_cognitoissuedtokens`, `users_user` | ready-now (login proxy) | S | 4 |
| F6 | Birthday-window recipients | segment | Users with a birthday in the next 7/14 days (excluding `01/01`), split by "has claimed a gift before"; paired with the measured 1.57× birth-month lift as context | users: `users_user.birthdate` (parsed `0000/DD/MM`), activity log | ready-now | S | 4 |
| F7 | Occasion lift analyzer | agentic_analysis | Sandbox run: daily claim series + Hijri/Gregorian occasion calendar (Ramadan, Eids, Islamic New Year, national days, year-end, birthdays) → lift per occasion and year, burst vs broad split, recommended send windows. Later adds `occasion_code` mix from orders | users now; orders `order_orderlinepersonalisedetail.occasion_code, delivery_date` later | ready-now (v1) / needs-grant (v2) | M | 5 |
| F8 | Gift recipient funnel | funnel | Gift sent (personalised line) → recipient claims into an account → returning login → first own order → first gift sent (becomes a sender) | orders: personalise detail + order_line + order_order; users: activity log, tokens | needs-grant | L | 5 |
| F9 | `k_factor` / recipient-to-sender conversion | metric (range) | New senders among recipients ÷ senders, rolling 60 d; P2P vs corporate split; reciprocal-edge share | same as F8 via the hashed recipient key | needs-grant | L | 5 |
| F10 | Gifting graph drill-down | record_drilldown | For one pseudonymous user: gifts sent (count, occasions, recipient hashes resolved to registered or unregistered), gifts claimed, reciprocal edges; never raw contacts | orders personalise detail (hashed) + users | needs-grant | M | 4 |
| F11 | Gift/group-gift/@Work fraud stream | breakdown + alert | Blacklist adds by source (`ecom_gifts`, `ecom_groupgift`, `atwork`) × type × month, netted for removals; alert when a source goes silent for more than 60 days (would have caught group gift stopping in May 2025) | users: `core_blacklisteduserdetail`, `kafka_clients_blacklistuserconsumerdatalog` | ready-now | S | 3 |
| F12 | Identity-collision queue | alert_trigger + record_drilldown | Claims binding another account's primary email, emails shared across users, users with ≥2 *distinct* claim emails (24 users today, one with 19; G23), kept separate from same-email re-claims (55) → risk review, counts plus pseudonymous ids only | users: activity log, `users_secondaryuseridentity`, `users_user` (hashed email compare in-DB) | ready-now | S | 3 |
| F13 | Guest → registered sender conversion | metric (range) | DISTINCT guest_id merged to a user (both non-null, earliest `created_on`) ÷ guest senders; cart carry-over ratio | orders: `users_mergeduser`, `basket_mergedbasket`, `users_guestuser`, `order_order.guest_id` | needs-grant | M | 3 |
| F14 | Happy Card / offer viral loop | breakdown | Recipient conversion and offer redemption for generic (Happy Card) vs single-brand gifts; `offer_code` redemption per offer; emapi availed offers | orders `order_line(product_id, is_offer_applied, offer_code)`, `catalogue_product.is_generic`; emapi `users_useravailedoffer`, `brands_generic_brand_config` | needs-grant | M | 4 |
| F15 | Gift configuration mix | breakdown | Share of lines that are gift vs self (`is_buy_for_self`), personalised, scheduled vs instant, reminder added, by occasion and platform | orders: `order_orderlinequantitydetail`, `order_orderlinepersonalisedetail`, `order_order.platform` | needs-grant | S | 4 |
| F16 | Gifting network dashboard | dashboard | Tiles: claims (lower-bound chip), gift-acquired share, org vs freemail share of claim events (with the F20 sensitivity band), burst calendar and season re-book list, birthday lift, recipient returning-login gap, existing-user re-engagement lift, country gift-acquired share. All in Asia/Dubai time. v2 adds k-factor and the funnel | F1–F7, F19–F22 (+F8/F9 later) | ready-now (v1) | M | 5 |
| F17 | Alt-email cap friction | metric (snapshot) | Share of claimers already holding a live alternate email; swap cycles (remove → via_gift) per week; blocked claim attempts once the gotagift source exists | users now; `ygag_ecom_gotagift_db` later | ready-now (partial) / needs-new-source | S | 3 |
| F18 | Referral attribution | metric | Referral/invite/UTM attribution | none of the four DBs have it (Q30/A10/G17) | needs-new-source | L | 4 |
| F19 | `gift_claim_reengagement` | metric (range) | For existing-user claimers (tenure >30 d): the 30-day returning-login rate after the claim vs matched non-claimers with the same tenure bucket and reference window, with lift and a pooled-z CI. Baseline today: 1.23% vs 1.10%, no lift (G24). This is the scorecard for H7 CRM follow-ups. v2 adds redemption and orders | users: activity log, `users_cognitoissuedtokens`, `users_user`; orders later | ready-now (login proxy) / needs-grant (orders) | S | 4 |
| F20 | Data-driven domain classifier | segment (derived dimension) | Per claim domain, computed in-DB: distinct claimers, primary-email holders and their ratio. `consumer` if ≥1,000 holders and ≥10×, `org` otherwise, and the hand YAML list is an override. Publishes a sensitivity band on org share (74.4% / 72.4% / 61.8% floor, G27) so the chip shows the classification uncertainty. Names never leave the DB, only `claim_org_sid` | users: activity log, `users_user.email` (domain part only, in-DB) | ready-now | S | 3 |
| F21 | Corporate season re-book list | segment | Before each season (Dec, Ramadan window): the list of `org_<sid>` domains that bursted in the same season last year, with their last-season claims and new-user share, and a prior burst-again rate of 40% (G25; 3.9% for non-burst domains). Handed to B2B sales 6 weeks ahead. Opaque ids are resolved to client names only inside the B2B team's own CRM | users: activity log (bursts rollup) | ready-now | S | 5 |
| F22 | `gift_acquired_deletion_rate` (cohort-matched) | metric (range) | Deletion rate of gift-acquired users vs the join-month-weighted expectation from all signups (0.48% vs 1.76%, G28). Never compared with the all-time 2.2% | users: `users_user`, activity log | ready-now | S | 2 |

---

## 4. Plugin notes

**Plugin `ecom_users` (ready now): add a `gifting` sub-area**
- **Entities:**
  - `gift_claim`: one row per `users_useridentityactivitylog` row with activity `secondary_email_added_via_gift`. Keys: `user_id` → `users_user.id` → `username` (canonical).
  - `recipient_user`: a `users_user` subset.
  - `secondary_identity`.
- **Allowlisted tables:**
  - `users_useridentityactivitylog`: columns `id`, `activity`, `timestamp`, `user_id`, `actor_id`. `comment` is **never** exposed, only derived columns from it.
  - `users_secondaryuseridentity`: `id`, `user_id`, `is_active`, `is_deleted`, `created_on`, `modified_on` (no `alternate_email`, no `username`).
  - `users_user`: `id`, `username`, `date_joined`, `is_deleted`, `is_app_user`, `country_of_residence`, and a derived birthday day/month.
  - `users_cognitoissuedtokens`: `user_id`, `user_platform`, `created_on`.
  - `core_blacklisteduserdetail`: `source`, `type`, `is_removed`, `created_on`, `reference_id` UUID-match flag.
  - `core_siteconfiguration`: the `secondary_identity` keys only.
- **Derived view** `atlas_gift_claim_v`, computed in-DB (the connector stays SELECT-only; this is a SQL definition the plugin runs, or a DBA-created view):
  - `claim_id`, `user_id`, `claimed_at` (UTC), `claimed_local_date` (Asia/Dubai).
  - `mins_since_signup` and `is_gift_acquired_1h` / `_1d`.
  - `claim_domain_class` (freemail / org_500+ / org_100–499 / org_10–99 / org_<10), with the freemail list versioned in YAML.
  - `claim_org_sid`: an opaque surrogate id for the claim domain (a DBA-owned lookup table mapping domain → `org_NNNN`, or `hmac(domain, key, 'sha256')` with the key outside the plugin), never an unkeyed md5. Freemail domains map to `freemail`. k-anonymity ≥ 50 is enforced in the metric layer.
  - `claim_domain_consumer_score`: primary-holders ÷ claimers for the domain, computed in-DB (G27), so the freemail class is data-driven with the YAML list as an override.
  - `primary_is_freemail`, `same_domain_as_primary`.
  - `email_is_other_primary` (bool) and `email_shared_across_users` (bool).
  - `alt_still_live` and `later_removed`.
  - `recipient_birth_md` (parsed from `0000/DD/MM`, `01/01` → NULL) and `in_birth_month` / `within_3d_of_birthday`.
- **Metrics YAML:**
  - range: `gift_claims`, `gift_acquired_signups`, `gift_acquired_signup_share`, `org_claim_share`, `burst_days`.
  - snapshot: `live_gift_alt_identities`, `claimers_with_alt_cap_hit`.
  - Top-N breakdowns: `country_of_residence`, `claim_domain_class`, `claim_org_sid` (k ≥ 50), `claimed_local_dow`.
- **Funnel YAML (v1):** signup → gift claim ≤1 h → any token → returning login >1 d.
- **Provenance text on every gift metric:** "lower bound — counts only gifts claimed to a non-primary email; gifts to primary email / guests / phone are invisible."

**Plugin `ecom_orders` (after grant): add a `gifting` entity set**
- **Entities:**
  - `gift_line`: `order_line` + 1:1 `order_orderlinequantitydetail` + 0..1 `order_orderlinepersonalisedetail`.
  - `sender`: `order_order.user_id` → `users_userprofile.cognito_id` → username, or `guest_id`.
  - `recipient_key`: a hashed contact.
  - `guest_merge`.
- **PII exclusions:** `email_address`, `phone_number`, `sender_name`, `personal_data_ref` raw, `personalization_data`, `receiver_phone_number` and all denormalised `user_*` / `guest_email` on `order_order`. Expose only **keyed** hashes, `HK(lower(trim(email)))` and `HK(E.164 phone)` with `HK` = HMAC-SHA256 under a secret key applied in a DBA-owned view (unkeyed md5 of an email or phone is dictionary-reversible), plus `has_*` flags.
- **Derived view** `atlas_gift_edge_v`: `line_id`, `order_id`, `sender_username_hash`, `sender_is_guest`, `recipient_email_hash`, `recipient_phone_hash`, `occasion_code`, `greeting_code`, `delivery_type`, `delivery_date`, `is_reminder_added`, `is_buy_for_self`, `delivery_method`, `product_is_generic`, `offer_code`, `date_placed`, `platform`, `status`.
- **Cross-plugin join (governed, done in the analysis sandbox over extracts, never ad hoc):** `recipient_email_hash` ↔ users-side hashes of `users_user.email`, `users_secondaryuseridentity.alternate_email` and the via_gift claim email. The users plugin must expose the same hash function for those three (a hashed view; the raw values never leave the DB).

**Other plugins (new sources):**
- `ecom_gifts` / `gotagift`: gift issuance, claim attempts, claim state (the full claim population).
- `groupgift`: contributors and pooled payments; confirm the product is live after May 2025.
- `atwork`: B2B orders, sender company id, which gives the real corporate dimension instead of domain inference.
- `plusoffers`: the redemption ledger.

---

## 5. Grants needed

| # | DB.table | Columns (as exposed by a PII-safe view) | Unblocks | PII-safe note |
|---|---|---|---|---|
| G-1 | `ygag_ecom_orders_db.order_orderlinepersonalisedetail` | `id`, `line_id`, `created_on`, `occasion_code`, `greeting_code`, `delivery_type`, `delivery_date`, `delivery_time`, `delivery_time_zone`, `is_reminder_added`, `HK(lower(trim(email_address))) email_hash`, `HK(regexp_replace(phone_number,'\D','','g')) phone_hash`, `email_address is not null has_email`, `phone_number is not null has_phone` | F7 v2, F8, F9, F10, F15; H4, H5, H8, H9 | never raw contact; the hash must match the users-side hash; **keyed HMAC is required, not optional** (the key is held in secrets management, rotated with a re-extract, and never exposed to the sandbox) |
| G-2 | `ygag_ecom_orders_db.order_orderlinequantitydetail` | `line_id`, `is_buy_for_self`, `delivery_method`, `brand_skin`, `personal_data_ref IS NOT NULL` | F15, H11 | exclude `sender_name`, raw `personal_data_ref` |
| G-3 | `ygag_ecom_orders_db.order_line` | `id`, `order_id`, `product_id`, `is_offer_applied`, `offer_code`, `purchase_origin`, `created_on` | F8, F14 | — |
| G-4 | `ygag_ecom_orders_db.order_order` | `id`, `user_id`, `guest_id`, `date_placed`, `status`, `platform`, `region_id`, `created_by_id` (for @Work/on-behalf) | F8, F9, F13; H1, H5 | exclude `user_email`, `guest_email`, `user_name`, `user_phone`, `owner`, `session_id`, `extra` |
| G-5 | `ygag_ecom_orders_db.users_userprofile` | `user_id`, `HK(cognito_id)` | sender → canonical username | keyed hash only |
| G-6 | `ygag_ecom_orders_db.users_mergeduser`, `basket_mergedbasket`, `users_guestuser` | all merge columns; guestuser `id`, `created_on`, `platform`, `is_active` | F13, H10 | exclude guest email/username/session ids |
| G-7 | `ygag_ecom_orders_db.catalogue_product` | `id`, `upc`, `is_generic`, `visible_to_at_work`, `visible_to_sendatip` | F14, H11 | no PII |
| G-8 | `ygag_ecom_orders_db.user_tip_tip` | `id`, `sender_id`, `status`, `platform`, `amount_in_aed`, `send_tip_gift_event_triggered`, `created_on`, `HK(receiver_phone_number)` | P2P tip edge | keyed hash only |
| G-9 | `ygag_ecom_users_db` (readable today, but needs a **view**) | a keyed-hash identity view: `user_id`, `HK(lower(email))`, `HK(phone digits)`, `HK(lower(alternate_email))`, `HK(lower(via_gift comment))`, and `claim_org_sid` | the join side for G-1 | lets the sandbox join without raw email ever leaving the DB |
| G-10 | `ygag_emapi_stores_db.users_useravailedoffer`, `brands_generic_brand_config`, `brands_brand` (`id`, `code`, `is_generic`, `visible_to_corporate*`, `visible_to_at_work`) | as named | F14 | no PII |
| G-11 | `ygag_ecom_orders_db.kafka_atworkkafkadatalog` (also the emapi copy) | `id`, `status`, `start_timestamp`, `completed_timestamp`, and from `data` only the event type and company id (if present) | H3 (@Work volume by season) | no payload |
| G-12 | new sources: `ygag_ecom_gifts_db` (`gifts_gift` state, claim/redeem timestamps, order_id), `ygag_ecom_gotagift_db` (claim attempts and outcome), `ygag_groupgift_aps_db` (group, contributors count, amounts), `ygag_atwork_*` (company id, order dates) | ids, states, timestamps, counts; hashed recipient contact | F8 full population, F17, H6, group gift | same hash contract |

Minimum viable grant for the k-factor (F9): **G-1 + G-3 + G-4 + G-5 + G-9**.

---

## 6. Risks and data-quality traps

1. **The lower-bound trap.** `via_gift` is only claims to a *non-primary* email, one event per newly bound email. Never label it "gifts received" or "recipients". The provenance chip must say "lower bound".
2. **The one-alternate-email cap** (`secondary_identity_per_account = 1`). Once a recipient holds an alternate email, later gifted emails either fail to bind or swap it out. Claim counts per user are capped by config, not by behaviour. A config change would create a step change in the metric; watch `core_siteconfiguration` via `django_admin_log`.
3. **Denominator cutovers.**
   - The users id-sequence change in May 2025 distorts signup counts before and after it, so the gift-acquired *share* shifts.
   - `is_app_user` changed definition in Aug 2024, the same month via_gift starts (2024-08-05). There is no pre-Aug 2024 history.
4. **Corporate bursts dominate the variance.** A single company can move a month (2026-03-09 alone was 27.8% of March's claims, both in Asia/Dubai time: 730 / 2,626, G29). Always show burst vs broad claims, or robust medians. Report domains only as pseudonymous hashes with k ≥ 50, because the domain names identify B2B clients.
5. **The freemail list is hand-curated** (21 domains). The data-driven classifier (G27) moves org share only from 74.5% to 72.4–74.4% under sane rules, so the list is not the main error. Use F20 with the YAML list as an override.
5a. **Selection bias of the claim event.** It sees only gifts claimed to a *non-primary* email. 76% of signups have a freemail primary (G26), so personal-freemail gifts are systematically under-seen and work-email gifts over-seen. Any "share of gifts" by domain, country or occasion inherits this bias. The chip must say "share of claim events".
5b. **Time-zone consistency.** Storage is UTC and business days and months are Asia/Dubai. Mixing them moves daily figures a lot: 2026-03-09 is 730 claims in Dubai time but 400 in UTC (G29). Every metric YAML declares its zone.
6. **Tokens are a weak engagement proxy.** App tokens live 548 days, WEB tokens are purged after 30 days, and history only starts 2026-07-13 (app) / 2026-08-29 (web). The returning-login comparison is only valid on same-cohort, same-platform groups.
7. **Birthdate** is `0000/DD/MM` (no year) on 37% of users. `0000/01/01` is a default (9,940 rows). It must be parsed explicitly and never cast to a date.
8. **The recipient has no id in orders.** The sender → recipient edge depends on contact hashing. Normalisation mismatches (case, whitespace, `+`-aliases, phone formats) silently lower match rates. Define one normalisation function and apply it on both sides.
9. **`is_guest` on blacklist rows and `guest_id` in Kafka are not guest flags** (cross-db §1.3, X30). Never use them to split recipients or senders into guest and registered.
10. **Group gift may be dead.** Its fraud stream stopped in May 2025. Do not ship group-gift metrics without confirming that the service is live in `ygag_groupgift_aps_db`.
11. **Personalisation coverage.** `personalization_detail` (94k) is only about 19% of order-line personalisations. Use `order_orderlinepersonalisedetail` (497k) as the gift-line table. `occasion_code` is populated only on personalised lines, about a third of lines.
12. **Kafka gift events are about 2.5 per order** (`kafka_giftcreationlog` 3.13M vs 1.23M orders, est). "Gifts sent" must be counted on lines × quantity, not events.
13. **Live replica drift.** Claim counts moved from 59,591 (X7) to 59,594 (X25) to 59,595 (G2) within the hour. Stamp as-of time on every figure.
14. **Reader contention.** Recipient hashing over 497k personalise rows must be a governed extract or view, not live atlas queries on the only shared reader (orders-customer-catalog, guardrail 3).

---

## Appendix: SQL provenance (all run 2026-09-29 via `atlasq.sh`)

`F = 'YYYY "m" MM "d" DD'`; `FM` = the 21-domain freemail list `('gmail.com','hotmail.com','yahoo.com','outlook.com','icloud.com','live.com','hotmail.co.uk','yahoo.co.uk','msn.com','me.com','aol.com','protonmail.com','ymail.com','outlook.sa','windowslive.com','googlemail.com','hotmail.fr','yahoo.in','rediffmail.com','mail.ru','yandex.com')` (G7 used the first 16).

**G1: identity-activity schema** (users, catalog)
```sql
select c.relname, a.attname, format_type(a.atttypid,a.atttypmod), a.attnotnull from pg_attribute a join pg_class c on c.oid=a.attrelid
where c.relname in ('users_useridentityactivitylog','users_secondaryuseridentity') and a.attnum>0 and not a.attisdropped order by 1, a.attnum;
-- activitylog: id, activity vc30, timestamp, comment text, actor_id, user_id; secondaryuseridentity: id, created_on, modified_on, username uuid, alternate_email vc254, is_active, is_deleted, user_id
```
**G2: via_gift overview** [VALIDATED exact]
```sql
with g as materialized (select l.id, l.user_id, l.actor_id, lower(trim(l.comment)) e, l."timestamp" ts from users_useridentityactivitylog l where l.activity='secondary_email_added_via_gift')
select count(*), count(distinct user_id), count(*) filter (where actor_id=user_id), count(*) filter (where actor_id is null), count(distinct actor_id) filter (where actor_id<>user_id),
 count(*) filter (where exists (select 1 from users_secondaryuseridentity s where s.user_id=g.user_id and lower(s.alternate_email)=g.e)),
 count(*) filter (where exists (select 1 from users_secondaryuseridentity s where s.user_id=g.user_id and lower(s.alternate_email)=g.e and s.is_active and not s.is_deleted)),
 count(distinct e) from g;
-- 59,595 | 59,496 | 59,595 | 0 | 0 | 58,744 | 58,744 | 59,507
```
**G3: claim time after signup** [VALIDATED exact]
```sql
with g as (select l.user_id, l."timestamp" ts, u.date_joined dj, u.is_deleted from users_useridentityactivitylog l join users_user u on u.id=l.user_id where l.activity='secondary_email_added_via_gift')
select case when ts<dj then '0_before_join' when ts-dj<=interval '1 hour' then '1_<=1h' when ts-dj<=interval '1 day' then '2_<=1d' when ts-dj<=interval '7 day' then '3_<=7d'
 when ts-dj<=interval '30 day' then '4_<=30d' when ts-dj<=interval '365 day' then '5_<=1y' else '6_>1y' end b,
 count(*), count(*) filter (where is_deleted), round(percentile_cont(0.5) within group (order by extract(epoch from ts-dj))::numeric/60,1) from g group by 1 order by 1;
-- <=1h 23,996 (115 del, 2.6 min) | <=1d 2,744 (341 min) | <=7d 2,412 | <=30d 1,930 | <=1y 10,793 | >1y 17,720 ; before_join 0
```
**G4: monthly gift-acquired signup share** [VALIDATED exact]
```sql
with s as (select date_trunc('month',date_joined) m, count(*) signups from users_user where date_joined>='2024-08-01' group by 1),
g as (select date_trunc('month',l."timestamp") m, count(*) claims, count(*) filter (where l."timestamp"-u.date_joined<=interval '1 day') new_1d,
 count(*) filter (where l."timestamp"-u.date_joined>interval '30 day') existing_30d
 from users_useridentityactivitylog l join users_user u on u.id=l.user_id where l.activity='secondary_email_added_via_gift' group by 1)
select to_char(s.m,'YYYY "m" MM'), s.signups, g.claims, g.new_1d, round(100.0*g.new_1d/s.signups,2), g.existing_30d from s left join g using (m) order by s.m;
-- e.g. 2024-12 29,411 / 5,042 / 1,851 / 6.29% ; 2026-03 29,608 / 2,624 / 960 / 3.24% ; 2026-09 23,901 / 1,746 / 893 / 3.74%
```
**G5: top claim days (Asia/Dubai)** [VALIDATED exact]
```sql
select to_char(date_trunc('day',"timestamp" at time zone 'Asia/Dubai'),'YYYY "m" MM "d" DD Dy'), count(*) from users_useridentityactivitylog
where activity='secondary_email_added_via_gift' group by 1 order by 2 desc limit 25;
-- 2026-03-09 730; 2025-03-26 724; 2024-12-13 575; 2025-03-27 475; 2024-12-16 391; 2024-12-12 313; 2025-06-26 295; 2025-12-05 271 ...
```
**G6: daily distribution** [VALIDATED exact]
```sql
with d as (select date_trunc('day',"timestamp" at time zone 'Asia/Dubai') d, count(*) c from users_useridentityactivitylog where activity='secondary_email_added_via_gift' and "timestamp">='2024-08-05' group by 1)
select round(avg(c),1), percentile_cont(0.5) within group (order by c), percentile_cont(0.9) within group (order by c), max(c), count(*) from d;   -- 75.8 | 64 | 117 | 730 | 786
```
**G7: spike vs normal days** [VALIDATED exact; domains aggregated in-DB, never returned]
```sql
with g as (select date_trunc('day',l."timestamp" at time zone 'Asia/Dubai') d, lower(split_part(trim(l.comment),'@',2)) dom, (l."timestamp"-u.date_joined<=interval '1 hour') new1h, lower(split_part(u.email,'@',2)) pdom
 from users_useridentityactivitylog l join users_user u on u.id=l.user_id where l.activity='secondary_email_added_via_gift'),
f as (select *, dom in (<FM first 16>) freemail from g),
dd as (select d, count(*) n, count(*) filter (where freemail) fm, count(*) filter (where new1h) new1h, count(distinct dom) doms, count(*) filter (where dom=pdom) samedom from f group by 1),
top as (select d, max(c) topc from (select d, dom, count(*) c from f group by 1,2) x group by 1)
select case when n>=170 then 'spike_day(>=170)' else 'normal_day' end, count(*), sum(n), round(100.0*sum(fm)/sum(n),1), round(100.0*sum(new1h)/sum(n),1), round(100.0*sum(topc)/sum(n),1), round(100.0*sum(samedom)/sum(n),1)
from dd join top using (d) group by 1;
-- normal 760 days 52,381 | 26.7% freemail | 41.3% new1h | top-domain 22.7% | same-dom 8.7% ; spike 26 days 7,214 | 15.7 | 32.6 | 37.6 | 5.4
```
**G8: top-domain share on spike days** [VALIDATED exact]
```sql
with f as (select date_trunc('day',l."timestamp" at time zone 'Asia/Dubai') d, lower(split_part(trim(l.comment),'@',2)) dom, (l."timestamp"-u.date_joined<=interval '1 hour') new1h
 from users_useridentityactivitylog l join users_user u on u.id=l.user_id where l.activity='secondary_email_added_via_gift'),
dd as (select d, count(*) n, count(*) filter (where new1h) new1h, count(distinct dom) doms from f group by 1 having count(*)>=190),
t as (select d, dom, count(*) c, row_number() over (partition by d order by count(*) desc) rn from f where d in (select d from dd) group by 1,2)
select to_char(dd.d,F), dd.n, round(100.0*t.c/dd.n,1), dd.doms, round(100.0*dd.new1h/dd.n,1) from dd join t on t.d=dd.d and t.rn=1 order by dd.n desc;
-- 2026-03-09 730 | 84.8 | 37 | 9.7 ; 2025-03-26 724 | 76.2 | 35 | 50.7 ; 2024-12-13 575 | 7.3 | 132 | 24.9 ; ... (17 days)
```
**G9: domain-cluster classes** [VALIDATED exact]
```sql
with f as (select lower(split_part(trim(l.comment),'@',2)) dom, l.user_id, (l."timestamp"-u.date_joined<=interval '1 hour') new1h, lower(split_part(u.email,'@',2)) pdom
 from users_useridentityactivitylog l join users_user u on u.id=l.user_id where l.activity='secondary_email_added_via_gift'),
d as (select dom, count(*) c from f group by 1), fm as (select unnest(array[<FM>]) dom)
select case when f.dom in (select dom from fm) then 'freemail' when d.c>=500 then 'org_500+' when d.c>=100 then 'org_100-499' when d.c>=10 then 'org_10-99' else 'org_<10' end,
 count(*), count(distinct f.dom), round(100.0*count(*) filter (where new1h)/count(*),1), count(*) filter (where pdom in (select dom from fm)), count(*) filter (where pdom=f.dom)
from f join d using (dom) group by 1 order by 2 desc;
-- freemail 15,202/21/44.0/8,309/4,047 ; org_500+ 14,866/9/31.4/12,359/298 ; org_10-99 13,018/439/40.4/10,602/239 ; org_100-499 8,978/46/40.5/7,248/233 ; org_<10 7,531/4,018/49.6/6,081/125
```
**G10: cohort returning login, all signups** [VALIDATED exact]
```sql
with c as (select u.id, u.date_joined dj, u.is_deleted, u.is_app_user,
  exists (select 1 from users_useridentityactivitylog l where l.user_id=u.id and l.activity='secondary_email_added_via_gift' and l."timestamp"-u.date_joined<=interval '1 day') gift_acq,
  exists (select 1 from users_useridentityactivitylog l where l.user_id=u.id and l.activity='secondary_email_added_via_gift' and l."timestamp"-u.date_joined>interval '1 day') later_claim
 from users_user u where u.date_joined>='2026-07-15' and u.date_joined<'2026-09-01')
select gift_acq, count(*), count(*) filter (where is_deleted), count(*) filter (where is_app_user),
 count(*) filter (where exists (select 1 from users_cognitoissuedtokens t where t.user_id=c.id)),
 count(*) filter (where exists (select 1 from users_cognitoissuedtokens t where t.user_id=c.id and t.created_on>c.dj+interval '1 day')),
 count(*) filter (where exists (select 1 from users_cognitoissuedtokens t where t.user_id=c.id and t.created_on>c.dj+interval '1 day' and t.user_platform='WEB')),
 count(*) filter (where later_claim) from c group by 1;
-- false 27,612 | 382 | 22,714 | 15,451 | 1,151 | 300 | 253 ; true 1,209 | 1 | 1,209 | 850 | 30 | 4 | 0
```
**G11: cohort returning login, app users, not deleted** [VALIDATED exact]
```sql
with c as (select u.id, u.date_joined dj, exists (select 1 from users_useridentityactivitylog l where l.user_id=u.id and l.activity='secondary_email_added_via_gift' and l."timestamp"-u.date_joined<=interval '1 day') gift_acq
 from users_user u where u.date_joined>='2026-07-15' and u.date_joined<'2026-09-01' and u.is_app_user and not u.is_deleted)
select gift_acq, count(*), count(*) filter (where exists (select 1 from users_cognitoissuedtokens t where t.user_id=c.id)),
 count(*) filter (where exists (select 1 from users_cognitoissuedtokens t where t.user_id=c.id and t.created_on>c.dj+interval '1 day')),
 count(*) filter (where exists (select 1 from users_cognitoissuedtokens t where t.user_id=c.id and t.created_on>c.dj+interval '7 day')),
 count(*) filter (where (select count(distinct t.device_signature) from users_cognitoissuedtokens t where t.user_id=c.id)>=2) from c group by 1;
-- false 22,371 | 15,039 | 999 | 744 | 300 ; true 1,208 | 850 | 30 | 26 | 16
```
**G12: birthday-month lift** [VALIDATED exact]
```sql
with g as (select extract(month from l."timestamp" at time zone 'Asia/Dubai')::int cm, substr(u.birthdate,9,2)::int bm, substr(u.birthdate,6,2)::int bd,
  extract(day from l."timestamp" at time zone 'Asia/Dubai')::int cd, (l."timestamp"-u.date_joined<=interval '1 day') newu
 from users_useridentityactivitylog l join users_user u on u.id=l.user_id
 where l.activity='secondary_email_added_via_gift' and u.birthdate ~ '^0000/\d{2}/\d{2}$' and substr(u.birthdate,9,2)::int between 1 and 12 and substr(u.birthdate,6,2)::int between 1 and 31 and u.birthdate<>'0000/01/01'),
bm as (select bm, count(*)::numeric/sum(count(*)) over () p from g group by 1), cm as (select cm, count(*) c from g group by 1)
select (select count(*) from g), (select count(*) from g where cm=bm), round((select sum(cm.c*bm.p) from cm join bm on bm.bm=cm.cm),1),
 (select count(*) from g where cm=bm and abs(cd-bd)<=3), (select count(*) from g where newu), (select count(*) from g where newu and cm=bm);
-- 20,405 | 2,659 | 1,698.0 | 1,005 | 6,739 | 948
```
**G13: blacklisted referenced users who claimed gifts** [VALIDATED exact]
```sql
with gc as materialized (select user_id, min("timestamp") first_ts from users_useridentityactivitylog where activity='secondary_email_added_via_gift' group by 1),
r as materialized (select b.source, b.created_on, b.is_removed, u.id uid from core_blacklisteduserdetail b join users_user u on u.username=b.reference_id)
select r.source, count(*), count(distinct r.uid), count(distinct r.uid) filter (where gc.user_id is not null), count(distinct r.uid) filter (where gc.first_ts<r.created_on),
 count(distinct r.uid) filter (where not r.is_removed and gc.user_id is not null) from r left join gc on gc.user_id=r.uid group by 1 order by 2 desc;
-- ecom_gifts 652 | 266 | 1 | 1 | 1 ; ecom_legacy 53 | 27 | 0 ; ecom_groupgift 40 | 20 | 1 | 0 | 0 ; ecom_orders 36 | 18 | 2 | 2 | 0
-- (a first attempt with a correlated domain sub-query timed out at 20 s and was split into G13 and G15)
```
**G14: gift / group-gift / @Work blacklist by type and quarter** [VALIDATED exact]
```sql
select source, type, count(*), count(distinct reference_id), count(*) filter (where is_removed), to_char(min(created_on),'YYYY "m" MM'), to_char(max(created_on),'YYYY "m" MM')
from core_blacklisteduserdetail where source in ('ecom_gifts','ecom_groupgift','atwork') group by 1,2 order by 1,3 desc;
-- atwork domain 24 (2026-07→09), ip 4, email 1 ; ecom_gifts email 288, mobile 269, device 138 (2024-04→2026-09) ; groupgift email 50, mobile 20 (2024-04→2025-05)
select to_char(date_trunc('quarter',created_on),'YYYY "q" MM'), source, count(*), count(distinct reference_id) from core_blacklisteduserdetail
where source in ('ecom_gifts','ecom_groupgift','atwork') group by 1,2 order by 1,2;
-- ecom_gifts 55–143 per quarter throughout; groupgift 21/15/27/2/5 then none after 2025-Q2; atwork 5 (2026-Q2), 24 (2026-Q3)
```
**G15: claims on blacklisted and promo-blocked domains** [VALIDATED exact]
```sql
with gc as materialized (select lower(split_part(trim(comment),'@',2)) dom, "timestamp" ts from users_useridentityactivitylog where activity='secondary_email_added_via_gift'),
ab as materialized (select distinct lower(value) d, created_on from core_blacklisteduserdetail where source='atwork' and type='user_domain'),
anyb as materialized (select distinct lower(value) d from core_blacklisteduserdetail where type='user_domain' and not is_removed),
pd as materialized (select distinct lower(domain) d from users_promotionaldomainblacklist where is_active), cd as (select dom, count(*) c from gc group by 1)
select (select count(*) from ab), (select count(*) from ab where d in (select dom from cd)), (select coalesce(sum(c),0) from cd where dom in (select d from ab)),
 (select count(*) from gc join ab on ab.d=gc.dom where gc.ts>ab.created_on), (select count(*) from pd), (select coalesce(sum(c),0) from cd where dom in (select d from pd)),
 (select coalesce(sum(c),0) from cd where dom in (select d from anyb)), (select count(*) from cd where dom in (select d from anyb));
-- 24 | 0 | 0 | 0 | 7 | 0 | 38 | 5
```
**G16: claimers and gift-acquired share by country** [VALIDATED exact]
```sql
with g as (select distinct on (l.user_id) l.user_id, (l."timestamp"-u.date_joined<=interval '1 day') newu, u.country_of_residence c
 from users_useridentityactivitylog l join users_user u on u.id=l.user_id where l.activity='secondary_email_added_via_gift' order by l.user_id, l."timestamp"),
base as (select country_of_residence c, count(*) n from users_user where date_joined>='2024-08-01' and not is_deleted group by 1)
select coalesce(g.c,'null'), count(*), count(*) filter (where newu), max(base.n), round(100.0*count(*) filter (where newu)/nullif(max(base.n),0),2)
from g left join base on base.c=g.c group by 1 order by 2 desc limit 12;
-- AE 31,295/13,577/231,648/5.86 ; SA 22,663/10,333/282,941/3.65 ; QA 2,898/1,318/16,090/8.19 ; KW 3.91 ; IN 3.22 ; BH 5.52 ; OM 3.25 ; EG 4.01 ; GB 1.53
```
**G17: catalog search for gifting, referral and corporate columns** (orders, emapi, ecomweb) [STRUCTURAL]
```sql
select c.relname, a.attname, format_type(a.atttypid,a.atttypmod), c.reltuples::bigint from pg_class c join pg_attribute a on a.attrelid=c.oid and a.attnum>0 and not a.attisdropped
where c.relnamespace='public'::regnamespace and c.relkind='r'
and a.attname ~* '(recipient|receiver|occasion|greeting|group|referr|invite|share|sender|buy_for_self|delivery_type|delivery_method|delivery_date|reminder|is_gift|corporate|atwork|at_work|happy|generic|bulk|purchase_mode|purchase_origin|visible_to)'
and c.relname !~ '^(auth_|django_|jet_)' order by 1,2;
-- orders 38 cols (personalise detail occasion/greeting/delivery/reminder; quantitydetail is_buy_for_self/delivery_method/sender_name; catalogue_product is_generic + visible_to_*;
--   user_tip_tip sender_id/receiver_phone_number); no referr/invite/share columns. emapi 30 (brands_brand visible_to_corporate/_api/_specific_corporate/at_work/gift_shop/sendatip/mpos/credit,
--   receiver_/sender_redemption_details, generic config 3,381 / items 533,305). ecomweb 41 (upcomingoccasion 0 rows, siteconfiguration.atwork_enabled, brandpagepromotionbanner.purchase_mode, happycardwidget)
```
**G18: `order_orderlinepersonalisedetail` columns and indexes** (orders) [STRUCTURAL]
```sql
select a.attname, format_type(a.atttypid,a.atttypmod), a.attnotnull from pg_attribute a where a.attrelid='order_orderlinepersonalisedetail'::regclass and a.attnum>0 and not a.attisdropped order by a.attnum;
select i.relname, pg_get_indexdef(i.oid) from pg_index x join pg_class i on i.oid=x.indexrelid where x.indrelid='order_orderlinepersonalisedetail'::regclass;
-- 15 cols incl. phone_number vc20, email_address vc512, occasion_code vc10, greeting_code vc10, delivery_type vc20 NN, is_reminder_added NN; indexes: pkey, line_id UNIQUE, created_by_id, modified_by_id (none on contact columns)
```
**G19: shared recipient emails, identity collisions, removals** [VALIDATED exact]
```sql
with g as (select lower(trim(comment)) e, user_id, "timestamp" ts from users_useridentityactivitylog where activity='secondary_email_added_via_gift'),
e as (select e, count(*) ev, count(distinct user_id) us from g group by 1), u as (select user_id, count(*) ev from g group by 1),
rm as (select g.user_id, min(r."timestamp"-g.ts) dt from g join users_useridentityactivitylog r on r.user_id=g.user_id and r.activity='secondary_email_removed' and lower(trim(r.comment))=g.e and r."timestamp">g.ts group by 1)
select (select count(*) from e where us>=2), (select sum(us) from e where us>=2), (select max(us) from e), (select count(*) from u where ev>=2), (select max(ev) from u),
 (select count(*) from rm), (select round(extract(epoch from percentile_cont(0.5) within group (order by dt))/86400) from rm),
 (select count(*) from g where exists (select 1 from users_user p where lower(p.email)=g.e));
-- 31 | 63 | 3 | 79 | 19 | 1,157 | 125 d | 164
-- NOTE: the 4th/5th columns count claim EVENTS per user (79 users with >=2 events, max 19), not distinct emails; see G23 for distinct emails (24).
```
**G20: claim emails per user; day-of-week pattern** [VALIDATED exact]
```sql
with u as (select user_id, count(distinct lower(trim(comment))) e, count(distinct lower(split_part(trim(comment),'@',2))) d from users_useridentityactivitylog where activity='secondary_email_added_via_gift' group by 1)
select case when e=1 then '1' when e=2 then '2' when e<=4 then '3-4' else '5+' end, count(*), sum(e), count(*) filter (where d=1 and e>1) from u group by 1 order by 1;
-- 1: 59,472 ; 2: 22 (8 same domain) ; 3-4: 1 ; 5+: 1 (19 emails, one domain)
select extract(isodow from "timestamp" at time zone 'Asia/Dubai')::int, count(*), count(*) filter (where extract(hour from "timestamp" at time zone 'Asia/Dubai') between 9 and 17)
from users_useridentityactivitylog where activity='secondary_email_added_via_gift' group by 1 order by 1;
-- Mon 9,436/5,655 ; Tue 8,775/5,428 ; Wed 9,738/5,699 ; Thu 9,799/5,624 ; Fri 9,351/5,397 ; Sat 5,932/3,097 ; Sun 6,564/3,876
```
**G21: secondary-identity config and live alternate emails** [VALIDATED exact; config keys only]
```sql
select k, jsonb_typeof(config->k), (select string_agg(kk||':'||jsonb_typeof(config->k->kk),', ') from jsonb_object_keys(config->k) kk)
from core_siteconfiguration, jsonb_object_keys(config) k where k in ('secondary_identity','disposable_usercheck','dynamic_throttle_manager');
select config->'secondary_identity'->>'secondary_identity_enabled', config->'secondary_identity'->>'secondary_identity_per_account' from core_siteconfiguration;   -- true | 1
select count(*), max(c) from (select user_id, count(*) c from users_secondaryuseridentity where is_active and not is_deleted group by 1) x;                  -- 72,650 | 1
```
**G22: corporate burst repeat** [VALIDATED exact]
```sql
with f as (select lower(split_part(trim(comment),'@',2)) dom, date_trunc('day',"timestamp" at time zone 'Asia/Dubai') d from users_useridentityactivitylog where activity='secondary_email_added_via_gift'),
fm as (select unnest(array[<FM>]) dom),
bursts as (select dom, d, count(*) c from f where dom not in (select dom from fm) group by 1,2 having count(*)>=20),
bd as (select dom, count(*) burst_days, count(distinct date_trunc('year',d)) burst_years, count(distinct date_trunc('month',d)) burst_months, sum(c) burst_claims from bursts group by 1)
select count(*), count(*) filter (where burst_days>=2), count(*) filter (where burst_months>=2), count(*) filter (where burst_years>=2), sum(burst_claims), (select count(*) from bursts),
 (select count(*) from bursts where extract(month from d) in (2,3,4)), (select count(*) from bursts where extract(month from d)=12) from bd;
-- 50 | 20 | 13 | 11 | 7,281 | 165 | 56 | 33
```
**G23: claim events vs distinct claim emails per user** [VALIDATED exact; corrects I10]
```sql
with u as (select user_id, count(*) ev, count(distinct lower(trim(comment))) e, count(distinct lower(split_part(trim(comment),'@',2))) d
 from users_useridentityactivitylog where activity='secondary_email_added_via_gift' group by 1)
select count(*) filter (where ev>=2), count(*) filter (where e>=2), count(*) filter (where e>=2 and d=1), count(*) filter (where ev>=2 and e=1), max(e), max(ev) from u;
-- 79 | 24 | 10 | 55 | 19 | 19
```
**G24: re-engagement, existing-user claimers vs matched non-claimers** [VALIDATED exact; token proxy]
```sql
with cl as (select distinct on (l.user_id) l.user_id, l."timestamp" ref, u.date_joined dj from users_useridentityactivitylog l join users_user u on u.id=l.user_id
  where l.activity='secondary_email_added_via_gift' and l."timestamp">='2026-07-15' and l."timestamp"<'2026-08-29' and l."timestamp"-u.date_joined>interval '30 day' and u.is_app_user and not u.is_deleted order by l.user_id, l."timestamp"),
nc as (select u.id user_id, timestamptz '2026-08-06 12:00+00' ref, u.date_joined dj from users_user u where u.is_app_user and not u.is_deleted and u.date_joined<timestamptz '2026-07-07'
  and not exists (select 1 from users_useridentityactivitylog l where l.user_id=u.id and l.activity='secondary_email_added_via_gift')),
c as (select 'claimer' grp, * from cl union all select 'non_claimer', * from nc),
t as (select grp, case when ref-dj<=interval '365 day' then '30d-1y' else '>1y' end ten,
  exists (select 1 from users_cognitoissuedtokens t where t.user_id=c.user_id and t.created_on between c.ref-interval '1 day' and c.ref+interval '1 day') at_ref,
  exists (select 1 from users_cognitoissuedtokens t where t.user_id=c.user_id and t.created_on> c.ref+interval '1 day' and t.created_on<=c.ref+interval '30 day') ret from c)
select grp, ten, count(*), count(*) filter (where at_ref), count(*) filter (where ret), round(100.0*count(*) filter (where ret)/count(*),2) from t group by 1,2 order by 2,1;
-- claimer >1y 513 | 121 | 6 | 1.17 ; non >1y 265,945 | 184 | 3,183 | 1.20 ; claimer 30d-1y 381 | 50 | 5 | 1.31 ; non 30d-1y 187,607 | 109 | 1,811 | 0.97
-- narrower variant (claims 2026-08-13..08-28, ref 2026-08-20, stratified by token in prior 30 d): claimers 397 / 4 returned; non-claimers 459,966 / 5,980 (1.30%)
```
**G25: season burst-repeat backtest** [VALIDATED exact; domains aggregated in-DB, never returned]
```sql
with f as (select lower(split_part(trim(comment),'@',2)) dom, (("timestamp" at time zone 'Asia/Dubai')::date) d from users_useridentityactivitylog where activity='secondary_email_added_via_gift'),
fm as (select unnest(array[<FM>]) dom),
o as (select dom, d, case when d between '2024-12-01' and '2024-12-31' then 'a_dec24' when d between '2025-02-01' and '2025-04-30' then 'b_ram25'
  when d between '2025-12-01' and '2025-12-31' then 'c_dec25' when d between '2026-02-01' and '2026-04-30' then 'd_ram26' end season from f where dom not in (select dom from fm)),
dd as (select dom, season, d, count(*) c from o where season is not null group by 1,2,3),
sd as (select dom, season, sum(c) claims, max(c) maxday from dd group by 1,2),
pairs(s1,s2) as (values ('a_dec24','c_dec25'),('b_ram25','d_ram26'))
select p.s1, p.s2, count(*) filter (where a.maxday>=20), count(*) filter (where a.maxday>=20 and b.claims>=20), count(*) filter (where a.maxday<20 and a.claims>=20),
 count(*) filter (where a.maxday<20 and a.claims>=20 and b.maxday>=20), count(*) filter (where a.maxday>=20 and b.maxday>=20)
from pairs p join sd a on a.season=p.s1 left join sd b on b.dom=a.dom and b.season=p.s2 group by 1,2;
-- dec24->dec25: 10 | 6 | 27 | 0 | 4 ; ram25->ram26: 10 | 9 | 24 | 2 | 4
-- adjacent-season variant (distinct burst domains per season, exists in next): dec24->ram25 3/10 ; ram25->dec25 1/10 ; dec25->ram26 1/7
```
**G26: same-period base rates since Aug 2024** [VALIDATED exact]
```sql
select count(*), count(*) filter (where lower(split_part(email,'@',2)) in (<FM>)), count(*) filter (where country_of_residence='AE'),
 round(100.0*count(*) filter (where country_of_residence='AE' and not is_deleted)/count(*) filter (where not is_deleted),1), count(*) filter (where is_deleted)
from users_user where date_joined>='2024-08-01';
-- 595,877 | 454,210 (76.2% freemail primary) | 235,001 (39.4%) | 39.6% (non-deleted) | 10,304 (1.73%)
```
**G27: data-driven freemail classification** [VALIDATED exact; only ranks and counts returned, no domain names]
```sql
with g as (select lower(split_part(trim(comment),'@',2)) dom, count(*) claims, count(distinct user_id) cu from users_useridentityactivitylog where activity='secondary_email_added_via_gift' group by 1),
p as (select lower(split_part(email,'@',2)) dom, count(*) ph from users_user where email is not null group by 1),
j as (select g.*, coalesce(p.ph,0) ph, g.dom in (<FM>) in_fm from g left join p using (dom))
-- (a) top-40 by cu: rnk, in_fm, cu, claims, ph, ph/cu  -> FM domains ratio 23.0-61.6 ; non-FM in top 40 max 8.1
-- (b) org share under rules: fm_list 74.5% ; ph>=1000 & >=10x: +3 domains/56 claims -> 74.4% ; ph>=200 & >=5x: +29/1,256 -> 72.4% ; ph>=50 & >=3x: +177/7,565 -> 61.8%
--     all 21 FM domains present; min FM ratio 10.0; max non-FM ratio among domains with >=20 claimers 34.1
select row_number() over (order by cu desc), in_fm, cu, claims, ph, round(ph::numeric/cu,1) from j order by cu desc limit 40;            -- (a)
select count(*) filter (where in_fm or (ph>=1000 and ph>=10*cu)), sum(claims) filter (where in_fm or (ph>=1000 and ph>=10*cu)),
 round(100.0*sum(claims) filter (where not (in_fm or (ph>=1000 and ph>=10*cu)))/max(t),1), count(*) filter (where not in_fm and ph>=1000 and ph>=10*cu)
from j, (select sum(claims) t from j) tot;   -- (b), repeated with (200,5) and (50,3) thresholds via UNION ALL
```
**G28: cohort-matched deletion and AE share of gift-acquired users** [VALIDATED exact]
```sql
with ga as (select distinct on (l.user_id) l.user_id, u.date_joined dj, u.is_deleted, u.country_of_residence c, (l."timestamp"-u.date_joined<=interval '1 hour') h1, (l."timestamp"-u.date_joined<=interval '1 day') d1
  from users_useridentityactivitylog l join users_user u on u.id=l.user_id where l.activity='secondary_email_added_via_gift' order by l.user_id, l."timestamp"),
gm as (select date_trunc('month',dj) m, count(*) n, count(*) filter (where is_deleted) del from ga where h1 group by 1),
bm as (select date_trunc('month',date_joined) m, count(*) n, count(*) filter (where is_deleted) del from users_user where date_joined>='2024-08-01' group by 1)
select (select sum(n) from gm), (select sum(del) from gm), round(100.0*(select sum(gm.n*bm.del::numeric/bm.n) from gm join bm using (m))/(select sum(n) from gm),2),
 (select count(*) from ga where d1), (select count(*) from ga where d1 and c='AE'), round(100.0*(select count(*) from ga where c='AE')/(select count(*) from ga),1);
-- 23,994 | 115 (0.48%) | expected 1.76% ; 26,737 | 13,577 (50.8%) ; all claimers AE 52.6% (52.6% non-deleted)
```
**G29: time-zone check and F4 alert volume** [VALIDATED exact]
```sql
select count(*) filter (where ("timestamp" at time zone 'Asia/Dubai') >= '2026-03-01' and ("timestamp" at time zone 'Asia/Dubai') < '2026-04-01'),
 count(*) filter (where "timestamp" >= timestamptz '2026-03-01 00:00+00' and "timestamp" < timestamptz '2026-04-01 00:00+00'),
 count(*) filter (where ("timestamp" at time zone 'Asia/Dubai')::date='2026-03-09'), count(*) filter (where ("timestamp" at time zone 'UTC')::date='2026-03-09')
from users_useridentityactivitylog where activity='secondary_email_added_via_gift';
-- 2,626 | 2,624 | 730 | 400
with f as (select ("timestamp" at time zone 'Asia/Dubai')::date d, lower(split_part(trim(comment),'@',2)) dom from users_useridentityactivitylog where activity='secondary_email_added_via_gift'),
dd as (select d, count(*) n from f group by 1),
t as (select d, max(c) topc from (select d, dom, count(*) c from f where dom not in (<FM>) group by 1,2) x group by 1),
j as (select dd.d, dd.n, coalesce(t.topc,0) topc from dd left join t using (d))
select extract(year from d)::int, count(*), count(*) filter (where n>117 and topc>0.4*n), count(*) filter (where topc>=50 and topc>0.4*n), count(*) filter (where topc>=100), count(*) filter (where n>117) from j group by rollup(1);
-- 2024: 149 d / 3 / 3 / 1 / 30 ; 2025: 365 / 11 / 12 / 4 / 33 ; 2026: 272 / 6 / 6 / 3 / 15 ; total 786 / 20 / 21 / 8 / 78
```
**Statistics (computed locally from G11/G24 counts):** pooled two-proportion z. G11 >1 d: 30/1,208 vs 999/22,371 → z = 3.28 (Wald 4.23). G11 >7 d: 26/1,208 vs 744/22,371 → z = 2.24 (Wald 2.70). G24: 11/894 vs 4,994/453,552 → z = −0.37.

**Reused from profiles:** cross-db X7, X13, X13b, X15, X25, X30, X37 (blacklist sources, consumer log, via_gift time span); users C1 (birthdate format), §5 (id cutover), C4 (token new vs returning); orders-customer-catalog Q30 (no referral columns), Q20 (merge-table bounds); orders-funnel Q1/Q20 (personalisation ratios), X22 (gift events per order); ecomweb A10, A14 (no attribution; upcomingoccasion polling).
