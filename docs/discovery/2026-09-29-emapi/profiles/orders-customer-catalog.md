# Profile: orders-customer-catalog (ygag_ecom_orders_db)

Profiled 2026-09-29 through `atlasq.sh`: the atlas EC2 box over SSH, a READ ONLY transaction on the Aurora read replica, running as role `<emapi_login_role>`. Revision 2 (after the first critic review): corrections are marked **[rev2]**. Revision 3 (after the second critic review, Q28–Q36): corrections are marked **[rev3]**. Revision 4 (after the third critic review, Q37–Q42, all run 2026-09-29): corrections are marked **[rev4]**. Revision 5 (after the fourth critic review, Q43–Q47, all run 2026-09-29): corrections are marked **[rev5]**.

**Evidence labels [rev4].** Every claim in this profile is one of:
- **VALIDATED**: backed by a data query. *No claim in this profile is VALIDATED*, because no data query on this DB is possible (see BLOCKER).
- **STRUCTURAL**: inferred from schema, catalog statistics or replica counters only. This is the default label for everything below unless marked otherwise.
- **NEEDS-GRANT**: a hypothesis that needs data not currently readable; the table/columns needed are named inline and consolidated in the Grant request.

## BLOCKER: this profile is metadata only

`<emapi_login_role>` has **no SELECT privilege on any of the 71 in-scope tables**. `has_table_privilege(oid,'SELECT')` is false for all 71 (Q4, re-checked in rev2 as Q17: 0 of 71). The first data query failed with `InsufficientPrivilegeError: permission denied for table offer_productoffer` (Q3). Across the whole database the role can read only 2 relations, `pg_stat_statements` and `pg_stat_statements_info`, and it has no column-level grants on any public table (Q5).

The catalog views that depend on privileges are also empty:
- `information_schema.columns` returns 0 rows. I used `pg_attribute` instead.
- `pg_stats` returns 0 rows.
- `pg_sequences.last_value` is NULL.
- `pg_stat_statements` hides the query text for 4,793 of its 4,809 statements (Q11).

As a result, **items 3–6 of the brief could not be measured**: status/enum distributions, min/max timestamps, monthly trends, and failure/friction rates. I did not try to get around the permission. The sibling unit `orders-integrations.md` hit the same issue.

Every number below comes from the catalog. It is one of:
- **estimate**: `pg_class.reltuples`, the planner statistic replicated from the primary's last VACUUM/ANALYZE.
- **bound**: derived from exact page counts and declared column widths. Rough, not a count.
- **exact**: a catalog fact, such as bytes, pages, a constraint definition, or a replica-local scan counter.

### Grant request: minimal grant list [rev2, consolidated rev4]

All BLOCKED sections below point here. Where a raw column is PII, prefer a PII-safe view (derived flag, hash or bucket) over the raw column.

Grant `SELECT` to `<emapi_login_role>` on the tables below. Where a table holds PII, grant **column-level** SELECT only on the listed non-PII columns. Password, hash, session and token columns are never granted.

| Table | Grant (columns) | Excluded (PII / secret) |
|---|---|---|
| users_customuser | id, date_joined, is_active, is_staff; **last_login only as a date-truncated view** (`date_trunc('day', last_login)`) [rev3] | email, username, password, first_name, last_name, is_superuser (not needed); raw last_login timestamp (quasi-identifier, see PII) |
| users_userprofile | id, user_id, created_by_id, country_of_residence, gender, language_code, language_id, is_phone_number_verified, is_email_verified, trusted_user, is_deleted, is_enabled, created_on, modified_on | phone_number, cognito_id (grant only to a hashed view if a cross-DB join is needed) |
| users_guestuser | id, platform, is_active, created_on, modified_on, last_accessed [rev3: modified_on added] | email, username, session_id, db_session_id, extra, note |
| users_mergeduser | all (id, guest_id, user_id, created_on, modified_on) | — |
| basket_mergedbasket (out of scope) [rev3] | all (id, guest_basket_id, user_basket_id, created_on, modified_on) | — (no PII) |
| users_blacklisteduserdetail | id, type, source, is_guest, is_removed, created_on, modified_on | value, reference_id |
| users_cognitouserdatasynclog | id, status, created_on, **modified_on** [rev3] | payload, error (error keys could come later through a view that extracts only error codes) |
| personalization_detail | id, created_by_id, cart_reference_id, order_reference_id, created_on | personalization_data |
| personalization_update_kafka_data_log | id, status, start_timestamp, completed_timestamp | data, error_data |
| reviews_googlereview | is_reviewed, reviewed_date, platform, **created_on, modified_on** [rev3]; user_reference only through a **hashed view** (`md5(user_reference::text)`) for dedupe [rev3] | raw user_reference (pseudonymous uuid, but it is the PK and may be joinable to a person elsewhere), user_email, user_ip_address, user_agent |
| user_tip_tip | id, sender_id, created_by_id, amount, amount_in_aed, currency_id, platform, status, language, **send_tip_gift_event_triggered** [rev3], created_on, modified_on | receiver_phone_number, extra |
| user_tip_invoice | id, state, amount, service_charge, vat_amount, payment_method, is_flagged_email_sent, created_on | card_last4 |
| catalogue_*, partner_partner, offer_* (all non-empty tables), analytics_recommendedbrand, notifications_emailtemplateconfiguration | all columns | — (no PII) |
| Out of scope but needed for this unit's signals: kafka_blacklistusergiftlog, kafka_blacklistuserkafkadatalog, kafka_legacyfraudsynclog | id, status, created_on / start_timestamp / completed_timestamp | payload, data, error, error_data |
| order_line (for offer redemption) | id, order_id, product_id, partner_id, is_offer_applied, offer_code, line_price_before_discounts_incl_tax, line_price_incl_tax | — |
| catalogue_product (already "all columns" above) [rev4] | includes **is_discountable**, **rating** | — |
| payment_paymentdetail (out of scope; fraud outcome) [rev4] | id, order_id, created_by_id, created_on, modified_on, **is_fraud, is_flagged**, payment_status, payment_gateway, payment_method, payment_scheme, is_gcc_card, card_issuer_country, currency, paid_amount | card_bin, card_last4, name_on_card (card/cardholder data); brand_calculations jsonb (not needed) |
| youpayclient_youpayclienttransactiondata (out of scope; fraud outcome) [rev4] | id, created_on, modified_on, **is_fraud, is_flagged**, approved, payment_status, payment_gateway, payment_method, payment_scheme, channel_code, **platform**, is_gcc_card, card_issuer_country, currency, amount, loyalty_level; order_reference only as a **hashed view** (`md5(order_reference)`) for joins | customer_email, customer_name, customer_ip_address, name_on_card, card_bin, card_last4, session_id, points_collected_mobile_number, points_redeemed_mobile_number, transaction_id, payment_reference, qitaf_request_id, order_history, order_items, udf1, *_url |
| basket_basket (out of scope; platform dimension + cart merge state) [rev5: corrected] | id, **platform**, region_id, owner_id, guest_id, parent_id, **status**, record_type, **date_created**, **date_merged**, date_submitted, language_code | `user` vc(150), user_email, user_name, user_phone, user_gender, note, extra jsonb |
| order_order (out of scope; platform dimension) [rev5: corrected] | id, **platform**, region_id, user_id, guest_id, created_by_id, basket_id, status, **date_placed**, date_updated, sold_date, currency, total_incl_tax, quantity, gift_create_event_triggered | guest_email, user_email, user_name, user_phone, user_gender, owner vc(150), session_id, transaction_id, transaction_url, payment_order_reference, extra jsonb |

**[rev5] Column check (Q44):** every column named in the grant rows above was checked against `pg_attribute`; all 152 exist. Rev4's row for basket_basket/order_order named `created_on` (neither table has it; basket_basket uses date_created/date_merged/date_submitted, order_order uses date_placed/date_updated/sold_date) and `user_id` on basket_basket (it is owner_id). Both rows are now split and corrected, and they list the PII columns on those tables, which rev4 wrongly said had none.

First queries to run once granted (all cheap: small tables, or TABLESAMPLE on large ones):

```sql
-- 1. exact counts for small/never-analyzed tables
SELECT 'mergeduser',count(*) FROM users_mergeduser UNION ALL SELECT 'tip',count(*) FROM user_tip_tip
UNION ALL SELECT 'invoice',count(*) FROM user_tip_invoice UNION ALL SELECT 'productoffer',count(*) FROM offer_productoffer
UNION ALL SELECT 'blacklist',count(*) FROM users_blacklisteduserdetail UNION ALL SELECT 'cognito_log',count(*) FROM users_cognitouserdatasynclog;
-- 2. lifecycle enums (small tables, full scan OK)
SELECT type, source, is_removed, is_guest, count(*) FROM users_blacklisteduserdetail GROUP BY 1,2,3,4;
SELECT status, count(*) FROM users_cognitouserdatasynclog GROUP BY 1;
SELECT status, count(*), avg(extract(epoch FROM completed_timestamp-start_timestamp)) FROM personalization_update_kafka_data_log GROUP BY 1;
SELECT status, platform, count(*) FROM user_tip_tip GROUP BY 1,2;  SELECT state, count(*) FROM user_tip_invoice GROUP BY 1;
SELECT offer_mode, offer_type, offer_channel, funding_method, budget_type, is_active, has_budget_exceeded, count(*) FROM offer_plusoffer GROUP BY 1,2,3,4,5,6,7;
SELECT status, count(*) FROM offer_offerpromocode GROUP BY 1;
-- 3. users: sampled distributions (992k rows -> TABLESAMPLE)
SELECT to_char(date_joined,'YYYYMM') m, count(*)*100 FROM users_customuser TABLESAMPLE SYSTEM (1) GROUP BY 1 ORDER BY 1;
SELECT is_deleted, is_enabled, trusted_user, is_email_verified, is_phone_number_verified, count(*)*100 FROM users_userprofile TABLESAMPLE SYSTEM (1) GROUP BY 1,2,3,4,5;
-- 4. guest conversion cardinality
SELECT count(*), count(DISTINCT guest_id), count(DISTINCT user_id), count(*) FILTER (WHERE guest_id IS NULL OR user_id IS NULL) FROM users_mergeduser;
-- 5. per-user personalization rate (created_by_id = acting customer)
SELECT count(DISTINCT created_by_id) FROM personalization_detail;
-- 6. offer redemption (order_line.offer_code is indexed via is_offer_applied only; sample)
SELECT is_offer_applied, offer_code IS NOT NULL, count(*)*100 FROM order_line TABLESAMPLE SYSTEM (1) GROUP BY 1,2;
-- 7. [rev3] cognito sync retry/reprocess rate (row touched after insert)
SELECT status, modified_on > created_on AS reprocessed, count(*) FROM users_cognitouserdatasynclog GROUP BY 1,2;
-- 8. [rev3] basket-level guest->user merge (10 heap pages, full scan OK)
SELECT count(*), count(DISTINCT guest_basket_id), count(DISTINCT user_basket_id),
       count(*) FILTER (WHERE guest_basket_id IS NULL OR user_basket_id IS NULL) FROM basket_mergedbasket;
-- 9. [rev3] tip -> gift event emission
SELECT status, send_tip_gift_event_triggered, count(*) FROM user_tip_tip GROUP BY 1,2;
-- 10. [rev3] who creates profiles: self vs Cognito sync / system user
SELECT (created_by_id = user_id) self_created, count(*)*100 FROM users_userprofile TABLESAMPLE SYSTEM (1) GROUP BY 1;
SELECT created_by_id, count(*)*100 FROM users_userprofile TABLESAMPLE SYSTEM (1) GROUP BY 1 ORDER BY 2 DESC LIMIT 5;
-- 11. [rev3] google review semantics: is reviewed_date the prompt time or the review time?
SELECT is_reviewed, count(*), avg(extract(epoch FROM reviewed_date-created_on)) s, count(*) FILTER (WHERE modified_on>created_on) touched
FROM reviews_googlereview GROUP BY 1;
-- 12. [rev3] guest last_accessed freshness: is it ever refreshed after insert?
SELECT count(*) FILTER (WHERE last_accessed > created_on + interval '1 minute')*100, count(*)*100 FROM users_guestuser TABLESAMPLE SYSTEM (1);
-- 13. [rev3] personalization service cutover
SELECT to_char(created_on,'YYYYMM') m, count(*)*20 FROM personalization_detail TABLESAMPLE SYSTEM (5) GROUP BY 1 ORDER BY 1;  -- 178 MB heap, sample
SELECT to_char(created_on,'YYYYMM') m, count(*)*100 FROM order_orderlinepersonalisedetail TABLESAMPLE SYSTEM (1) GROUP BY 1 ORDER BY 1;
-- 14. [rev4] fraud outcome on payments (762k / 1.23M rows -> sample; is_fraud/is_flagged not indexed)
SELECT is_fraud, is_flagged, payment_status, count(*)*100 FROM payment_paymentdetail TABLESAMPLE SYSTEM (1) GROUP BY 1,2,3;
SELECT is_fraud, is_flagged, approved, platform, count(*)*100 FROM youpayclient_youpayclienttransactiondata TABLESAMPLE SYSTEM (1) GROUP BY 1,2,3,4;
-- 15. [rev4] conformed platform dimension: value sets must agree across tables
SELECT platform, is_active, count(*) FROM users_guestuser GROUP BY 1,2;          -- 43 MB heap, full scan OK
SELECT platform, count(*)*100 FROM basket_basket TABLESAMPLE SYSTEM (1) GROUP BY 1;
SELECT platform, count(*)*100 FROM order_order  TABLESAMPLE SYSTEM (1) GROUP BY 1;
SELECT platform, count(*) FROM reviews_googlereview GROUP BY 1;  SELECT platform, count(*) FROM user_tip_tip GROUP BY 1;
-- 16. [rev4] offer eligibility gate
SELECT is_discountable, is_active, count(*), avg(rating), count(rating) FROM catalogue_product GROUP BY 1,2;
-- 17. [rev4] blacklist actor cardinality (index size is a weak hint only, see Relations)
SELECT count(*), count(DISTINCT created_by_id) FROM users_blacklisteduserdetail;
-- 18. [rev5] Oscar-native cart carry-over: basket status and date_merged (3.04M rows, neither column indexed -> sample)
SELECT status, date_merged IS NOT NULL AS merged, count(*)*100 FROM basket_basket TABLESAMPLE SYSTEM (1) GROUP BY 1,2;
-- 19. [rev5] calibrate index-size readings: distinct counts behind the userprofile indexes
SELECT count(DISTINCT language_id), count(DISTINCT created_by_id), count(*) FILTER (WHERE created_by_id = user_id)*100 FROM users_userprofile TABLESAMPLE SYSTEM (1);
```

## Summary

This unit holds the Django-Oscar-derived **customer, catalog and offer** half of the YGG consumer ecommerce app.

**Customers**
- About 992k registered users (`users_customuser`, estimate).
- A 1:1 Cognito-linked `users_userprofile`, about 978k (estimate), which holds `cognito_id`, verification flags, trusted_user, is_deleted and is_enabled.
- About 82.5k–88.7k guest checkout identities (`users_guestuser`; heap estimate 82,502, PK-index estimate 88,689), plus a guest→registered merge table (bound: up to about 3.7k rows) and its basket-level companion, out-of-scope `basket_mergedbasket` (bound: up to about 1.2k rows) [rev3].
- A fraud **blacklist**, estimate 48.6k (type,value) entries, **low confidence** [rev2].
- A **Cognito sync log**, estimate 93.9k rows with status and error JSON, **low confidence** [rev2].

**Catalog**
- About 3.2k–3.4k "products", which are really gift-card **brands**, with channel-visibility flags: ecommerce, iOS, Android, app, at-work, send-a-tip, whitelabel.
- 22 regional **stores**, `catalogue_store`, which acts as the region/country storefront.
- 63 categories.
- About 22.4k fixed denominations, about 11.4k denomination ranges and 939 handling-fee rules.
- About 715 partners/retailers.

**Hosting topology [rev5] (Q43, exact).** `aurora_replica_status()` returns exactly **two instances**: one writer (`ecom-shared-read-optimized-1`) and **one reader**, which is the instance this role is connected to (`aurora_db_instance_identifier()`; pg_is_in_recovery = true). The cluster hosts **40 non-template databases** (42 rows in pg_database). So this single reader is shared by every ecom database and carries all of the production online read traffic described in Behavior Signals. Measured replica lag: **8–26 ms** across five samples on 2026-09-29.

**Offers and campaigns**
- `offer_plusoffer`: about 378 brand promotions with budgets, sponsor payment networks, promo codes and merchandising placement.
- `offer_plusoffer_happy_cards`: about 10.6k brand links.
- `offer_offerpromocode`: 41 promo codes.
- `offer_productoffer`: never analyzed; 28 heap pages, so small.
- The whole Oscar `offer_conditionaloffer` / range / benefit engine is **empty (0 pages)**. So are **all voucher tables** (voucher_voucher, voucherset, voucherapplication, voucher_offers, basket_basket_vouchers) and **order_orderdiscount / order_orderlinediscount** [rev2]. The live redemption record is `order_line.is_offer_applied` + `order_line.offer_code` (vc(10), same type as `offer_plusoffer.code`).

**Other**
- Personalization: about 94k gift personalization payloads keyed by cart and order reference. Each is linked to the acting user through `created_by_id` (NOT NULL FK to users_customuser) [rev2]. This covers only about 19% of the order-line personalisations (497k, out of scope), so it is probably a newer service or a partial rollout [rev3].
- A Kafka update log of about 129k–141k rows (heap estimate 128,996, PK-index estimate 140,520) with status and error text, **about 1.37–1.49 messages per personalization** [rev4: refreshed; rev3 said 139k / 1.47].
- About 24k Google-review prompts.
- A small "send a tip" product: `user_tip_*`.

**Dead Oscar modules.** 39 tables in scope have 0 pages, including all of analytics_* except recommendedbrand, wishlists, product reviews, communication, stock records and product alerts. Behavior events (views, searches) are **not** captured in this unit. Baskets and orders live in out-of-scope `basket_basket` (about 3.04M rows, estimate) and `order_order` (about 1.23M rows, estimate).

## Entities & Tables

Volumes: `est` = reltuples (estimate). A value of `-1` means the table has never been analyzed; its heap page count and a rough bound are given instead.

### Customer / identity
| Table | est rows | Size | Purpose / key columns |
|---|---|---|---|
| users_customuser | 991,558 | 241 MB (heap 114 MB, idx 138 MB) | Django auth user. id (bigint PK), email (UNIQUE), username, password, first/last_name, date_joined, last_login, is_active/is_staff/is_superuser. The central user id used by order_order.user_id, basket_basket.owner_id and others. |
| users_userprofile | 978,022 | 478 MB (heap 158 MB, idx 343 MB) | 1:1 with customuser (user_id UNIQUE). **cognito_id** (UNIQUE, NOT NULL), phone_number (UNIQUE), country_of_residence, gender, language_code/language_id, is_phone_number_verified, is_email_verified, **trusted_user**, **is_deleted**, **is_enabled**, created_on/modified_on. created_by_id is NOT NULL and indexed (acting user). |
| users_guestuser | 82,502 (PK index: 88,689) | 56 MB | Guest checkout identity: email, username, session_id vc(512) (UNIQUE, indexed), db_session_id vc(512) (logical link to django_session, no FK, **not indexed** [rev3]), extra jsonb, **platform**, last_accessed (nullable), note, is_active, created_on/modified_on. Referenced by basket_basket.guest_id and order_order.guest_id. **Heap 100% all-visible** (5,300/5,300), so rows are effectively write-once [rev3]. No created_by_id. |
| users_mergeduser | -1 (33 pages; bound ≤ about 3.7k rows) | 0.3 MB heap | Guest→registered conversion link: guest_id (nullable FK), user_id (nullable FK), created_on/modified_on. **No UNIQUE on either column**, only plain indexes [rev2]. No created_by_id. |
| basket_mergedbasket (out of scope) [rev3] | -1 (10 pages, 100% all-visible; bound ≤ about 1.2k rows) | 80 KB heap | **Basket-level guest→registered merge at login**: guest_basket_id and user_basket_id (both nullable FKs to basket_basket, each indexed, no UNIQUE), created_on/modified_on. It is the companion to users_mergeduser: cart carry-over on login. 0 seq / 0 idx scans on the replica. |
| users_blacklisteduserdetail | 48,646 (low confidence) | 208 MB (heap 164 MB, no TOAST data) | Fraud blacklist: **type**, value (UNIQUE together), **source**, reference_id, is_guest, **is_removed**, created_on/modified_on. |
| users_cognitouserdatasynclog | 93,871 (low confidence) | 105 MB | Cognito→DB user sync attempts: payload jsonb (NOT NULL), **status** vc(10) (nullable), **error** jsonb (NOT NULL), created_on, **modified_on** (timestamptz NOT NULL) [rev3]. `modified_on > created_on` marks a row that was retried or reprocessed after insert. Only index is the PK. No created_by_id. |
| users_usermetadata | 25 | tiny | password_last_changed, has_received_expiry_warning (staff password policy). |
| users_passwordhistory | -1 (0 pages) | empty | Password-reuse history. |
| users_customuser_groups | 30 | tiny | Staff group membership. |
| users_customuser_user_permissions | 0 | empty | |

### Catalog (brands, regions, pricing)
| Table | est rows | Purpose / key columns |
|---|---|---|
| catalogue_product | 3,442 (PK index: 3,168) | Brand / gift card. id, upc (UNIQUE), slug (UNIQUE), **reference_name** (vc; external brand reference name, a cross-DB key candidate) [rev2], title/title_en/title_ar, **structure**, **classification**, **redemption_type**, **activation_fee_deduct_type**, activation_fee, retailer_id→partner_partner, store_id→catalogue_store, primary_category_id, parent_id (self), currency_id, is_active, is_public, is_launched, is_obsolete, is_generic, is_whitelabel, buy_for_yourself, allow_instant_activation, require_mobile_verification, and visibility flags for ecommerce, ecommerce_app, ios_app, android_app, at_work and sendatip. **is_discountable** (bool NOT NULL, not indexed) [rev4]: the Oscar per-product discount switch, i.e. **the offer-eligibility gate**. Any offer-redemption analysis must restrict its denominator to is_discountable brands, otherwise non-eligible brands dilute the redemption rate (NEEDS-GRANT: catalogue_product.is_discountable; first query 16). **rating** (double precision, nullable) [rev4]: a brand rating, source unknown (no review table is populated; reviews_productreview is empty). date_created/date_updated. |
| catalogue_store | 22 | Regional storefront: code vc(4) UNIQUE, name, country_id (ISO-2), currency_id, visible_to_ecommerce, visible_to_atwork, is_active. Referenced by order_order.region_id and basket_basket.region_id. |
| catalogue_category | 63 | Tree (path/depth/numchild), code UNIQUE, is_public. |
| catalogue_productcategory | 31,311 (PK index: 31,881) | Product↔category M2M. |
| catalogue_productdenomination | 22,404 | Fixed card values: amount, currency_id, **gencode**, is_default, is_active, order_number. |
| catalogue_productdenominationrange | 11,376 | Open-amount ranges: **range_type**, minimum_amount, maximum_amount, currency. |
| catalogue_producthandlingfee | 939 | Fees: code UNIQUE, **handling_fee_type**, amount/percentage, start_date/end_date, is_active. |
| catalogue_productclass | 2 | Oscar product classes. |
| catalogue_attributeoption, attributeoptiongroup, option, product_product_options, productattribute, productattributevalue, productattributevalue_value_multi_option, productclass_options, productimage, productrecommendation | 0 pages (10 tables) [rev2] | Unused Oscar modules. |

### Partners
| Table | est rows | Purpose |
|---|---|---|
| partner_partner | 715 | Retailer/fulfilment partner: code UNIQUE, ref_code, name, accepts_generic, code_generate, is_active. Referenced by order_line.partner_id and catalogue_product.retailer_id. |
| partner_partner_users, partner_partneraddress, partner_stockrecord, partner_stockalert | 0 | Unused (no stock tracking for digital cards). |

### Offers / campaigns
| Table | est rows | Purpose |
|---|---|---|
| offer_plusoffer | 378 | YGG "Plus" brand campaigns (59 columns, Q24). **Identity/time:** code vc(10) UNIQUE, name, start_date/end_date. **Type:** **offer_mode**, **offer_type**, **offer_channel**, **funding_method**, funded_by, **reason_code**. **Value:** percentage/fixed_amount, has_min_max_restriction, minimum/maximum_amount. **Budget:** **is_budget_available** (NOT NULL), **budget_type**, budget_amount, budget_threshold, **has_budget_exceeded**. **Promo code lifecycle:** is_generic_promo_code, is_unique_promo_code, **promo_code_end_date**, promo_code_threshold. **Sponsor:** sponsor_payment_network(_en/_ar), sponsor_payment_network_code, sponsor_payment_threshold, **sponsor_payment_threshold_type**. **Merchandising placement:** **featured_order**, **brand_tile_order_number**, **offer_order_number** (all int NOT NULL). **Content (trilingual):** offer_text*, offer_details*, standard_terms*, special_terms*, purchase_offer_header* vc(500), how_it_works* jsonb. is_active, brand_id→catalogue_product, country_id. [rev2: columns added] |
| offer_plusoffer_happy_cards | 10,627 | Plus offer ↔ eligible product ("Happy Card") M2M. |
| offer_offerpromocode | 41 | Promo codes for a plus offer: **status**, promo_code, brand_id, offer_id. |
| offer_productoffer | -1 (28 pages + 240 KB toast) | Brand/product discount offers: **offer_base**, code, **offer_type**, **channel**, start/end date, till_future, percentage/fixed, min/max, budget, **funding_method**, funded_by, has_budget_exceeded, brand_id, store_id. |
| offer_productoffer_happy_cards | -1 (16 pages) | M2M. |
| offer_conditionaloffer, benefit, condition, range*, rangeproduct*, conditionaloffer_combinations | 0 | Oscar offer engine, unused. |
| Out of scope, for reference: voucher_voucher, voucher_voucherset, voucher_voucherapplication, voucher_voucher_offers, basket_basket_vouchers, order_orderdiscount, order_orderlinediscount | **0 pages, all empty** [rev2] | The Oscar voucher/discount path is dead. |

### Personalization / gifting content
| Table | est rows | Size | Purpose |
|---|---|---|---|
| personalization_detail | 94,394 | 235 MB (toast 34 MB) | Gift personalization payload (personalization_data jsonb, about 1.9 KB/row heap). **personalization_reference_id** UNIQUE, **cart_reference_id**, **order_reference_id** (both indexed). **created_by_id** NOT NULL, FK to users_customuser, indexed: the acting customer (or a system user for guest flows) [rev2]. |
| personalization_update_kafka_data_log | 128,996 (PK index: 140,520) [rev4: was 139,132] | 343 MB (heap 238 MB, toast 101 MB) | Kafka consumer log for personalization updates: data jsonb, **status**, error_data text, start_timestamp, completed_timestamp. PK index only. No created_by_id (no actor link). **About 1.37–1.49 log messages per personalization_detail row** (128,996 / 94,394 = 1.37 to 140,520 / 94,394 = 1.49, all estimates) [rev4: restated as a range]: post-creation edits, retries, or both (NEEDS-GRANT: status). The table estimate moved from 139,132 to 128,996 within the profiling day, so the primary re-vacuumed/analyzed it. The heap and PK-index estimates bracket the count; neither is exact. |
| Out of scope, related: basket_basketpersonalisedetail 553,383; order_orderlinepersonalisedetail 496,737 (estimates) | | | Line-level personalisation in basket and order. These are the denominators for any "personalized gift" rate. **personalization_detail is only about 19% of order_orderlinepersonalisedetail (94,394 / 496,737) and about 17% of basket_basketpersonalisedetail** [rev3]. See Data Quality: coverage/cutover caveat. |

### Engagement / reviews / notifications
| Table | est rows | Purpose |
|---|---|---|
| reviews_googlereview | 23,984 | Google-review tracking. **PK = user_reference uuid**, user_email, **reviewed_date (NOT NULL)**, is_reviewed (NOT NULL), **platform**, user_ip_address, user_agent, created_on/modified_on [rev3]. No created_by_id (no actor link). **Semantics are ambiguous [rev3]:** because reviewed_date is NOT NULL, either it records the prompt/redirect time (and is_reviewed flips later), or rows are only created when a review happens (and is_reviewed is nearly always true). The visibility map (30% all-visible) favors in-place updates, i.e. the first reading. Unverified. |
| analytics_recommendedbrand | 85 [rev3: was 86] | Regional brand recommendations (region vc(4), product vc(64) as text, count, date_placed). Precomputed aggregate. |
| notifications_emailtemplateconfiguration | 6 | Email template config (email_type, template_code, language, template_data jsonb). |
| analytics_productrecord / userrecord / userproductview / usersearch | 0 | Oscar analytics, never populated. |
| communication_email / notification / communicationeventtype | 0 | Unused. |
| customer_productalert, wishlists_*, reviews_productreview, reviews_vote | 0 | Unused. |

### Send-a-tip
| Table | est rows | Purpose |
|---|---|---|
| user_tip_tip | -1 (42 pages; bound roughly 500–1,100 rows at 300–700 B/row) | Tips: sender_id→customuser, **created_by_id** (NOT NULL, indexed, acting user), receiver_phone_number, amount, amount_in_aed, currency, **platform**, **status**, reference_id uuid UNIQUE, language, extra jsonb, **send_tip_gift_event_triggered (bool NOT NULL)** [rev3]: a system trigger flag, meaning the tip emitted a downstream gift event (the tip becomes a gift). created_on/modified_on. |
| user_tip_invoice | -1 (15 pages) | Tip payment invoice (no created_by_id): reference_id UNIQUE, generic FK (content_type_id, object_id), **state**, amount, service_charge, vat_amount, payment_method, card_last4, is_flagged_email_sent. |
| user_tip_tipbrandconfiguration | 7 | Brand/country/currency config. |
| user_tip_tipbrandretailers | 42 | Brand/country ordering. |
| user_tip_configurationdata | 1 | config jsonb, user_throttling_limit. |

## Relations

Declared FKs (Q6) inside the unit:
- users_userprofile.user_id → users_customuser.id (1:1). users_mergeduser.(user_id → users_customuser, guest_id → users_guestuser), both nullable and non-unique. users_usermetadata and users_passwordhistory → users_customuser.
- catalogue_product → catalogue_store(store_id), partner_partner(retailer_id), catalogue_category(primary_category_id), catalogue_productclass, catalogue_product(parent_id), core_currency.
- catalogue_productdenomination / productdenominationrange / producthandlingfee / productcategory → catalogue_product.
- offer_plusoffer.brand_id → catalogue_product. offer_plusoffer_happy_cards → (offer_plusoffer, catalogue_product). offer_offerpromocode → (offer_plusoffer.offer_id, catalogue_product.brand_id).
- offer_productoffer → catalogue_product(brand_id), catalogue_store(store_id), core_currency (×3).
- user_tip_tip.sender_id → users_customuser. user_tip_tipbrand* → catalogue_product(brand_id), address_country.

**created_by_id / modified_by_id [rev3: corrected].** This is **not** universal. Of the 32 non-empty in-scope tables (Q28), **16 carry `created_by_id` + `modified_by_id`** and **16 carry neither**.
- **With an actor column (16):** catalogue_category, catalogue_product, catalogue_productdenomination, catalogue_productdenominationrange, catalogue_producthandlingfee, catalogue_store, notifications_emailtemplateconfiguration, offer_offerpromocode, offer_plusoffer, offer_productoffer, partner_partner, personalization_detail, user_tip_configurationdata, user_tip_tip, users_blacklisteduserdetail, users_userprofile.
- **Without an actor column (16):** users_customuser, users_guestuser, users_mergeduser, users_cognitouserdatasynclog, users_usermetadata, users_customuser_groups, reviews_googlereview, personalization_update_kafka_data_log, user_tip_invoice, user_tip_tipbrandconfiguration, user_tip_tipbrandretailers, analytics_recommendedbrand, catalogue_productcategory, catalogue_productclass, offer_plusoffer_happy_cards, offer_productoffer_happy_cards.
- **So guest identity (guestuser, mergeduser), reviews and the Cognito sync log have no actor link.** Attribution for them has to go through their own keys: mergeduser.user_id, a hashed googlereview.user_reference, and the cognito payload (not granted).

Where it exists, the meaning depends on the table:
- On **admin/config tables** (catalogue_*, offer_*, partner_*, notifications_*, user_tip_configurationdata) it is the staff or system actor. That is audit, not customer behavior.
- **users_blacklisteduserdetail.created_by_id: unknown [rev4, weakened rev5].** Its created_by_id index is 1,569 pages, about the same as the pkey (1,560) and modified_by_id (1,650). Rev4 read this as "near-unique actors". That comparison is weak for three reasons: (1) the pkey is on a monotonic id, so its leaves split at the right edge and stay about 90% full, while a secondary index on non-monotonic keys splits in the middle and settles nearer 70% full, so equal page counts do not mean equal entry counts; (2) the pkey is itself about 11x oversized (page-density anomaly), so all indexes on this table carry unexplained dead space; (3) on users_userprofile a 3-value index is larger than a many-value one (calibration below), so index size does not order cardinality. **No conclusion about who creates blacklist rows is drawn.** STRUCTURAL; NEEDS-GRANT: users_blacklisteduserdetail.created_by_id (first query 17).
- On **customer-generated tables** it is presumably the **acting customer** (or a system user for guest flows): personalization_detail, user_tip_tip (next to sender_id), and out-of-scope basket_basketpersonalisedetail, order_orderlinepersonalisedetail, payment_paymentdetail, order_line. So `personalization_detail.created_by_id` gives a direct per-user personalization link, with no need for the varchar cart/order reference join. The share of rows owned by a system/guest user must be measured once granted.
- **users_userprofile.created_by_id is unverified [rev3].** It is a separate FK to users_customuser from user_id (userprofile has 3 FKs to customuser: user_id, created_by_id, modified_by_id; Q36). Profiles may be created by the Cognito sync or a system user rather than by the customer (hypothesis, NEEDS-GRANT). **[rev4, narrowed rev5] The catalog shows only that created_by_id contains duplicates.** Its index is 1,790 pages, below the ≈2,665–2,720 pages that 978k distinct keys need, so some keys repeat and created_by_id cannot equal user_id on every row. It does **not** show how many distinct creators there are, or that one system/Cognito-sync user dominates: the language_id calibration below (at most 3 distinct keys, but a *larger* index) shows page counts are not monotone in cardinality. STRUCTURAL; the self-share and top creators need first queries 10 and 19 (NEEDS-GRANT: users_userprofile.user_id, created_by_id, language_id).

**Index-size cardinality [rev4] (Q39).** The server is PostgreSQL 16.11, so btree **deduplication** is on by default: a non-unique index on a heavily repeated key stores one key per posting list and ends up smaller than an index over the same number of distinct keys. The "packed minimum" below is the size of a bigint btree with every key distinct and no dead space (about 360–367 entries per 8 KB leaf page). An index below it must hold repeated keys. That one-sided test is the **only** valid reading. STRUCTURAL only.

**Calibration [rev5] (Q39, Q45): index pages are a weak, non-monotone signal.** users_userprofile.language_id references core_language, which has **2 rows** (reltuples 2), and the column is nullable, so the index holds at most 3 distinct keys. Under full deduplication that would approach the posting-list floor of about 6 bytes per heap TID, ≈720–800 pages for 978k entries. It is actually **2,127 pages**, *larger* than created_by_id (1,790) and modified_by_id (1,917). So a near-constant key can yield a bigger index than a many-valued one. Deduplication is only partly effective in practice (pages written before dedup or before the last REINDEX, page splits, dead space), and page count depends on insert order and history as much as on cardinality. The same pattern holds on basket_basket (Q45): language_id (≤ 3 keys) is 4,817 pages versus region_id (22 stores) at 5,435 and owner_id at 8,501, so the ordering there is plausible but the gaps are small. Use language_id as the reference: an index *well below* it (not merely below the packed minimum) would be needed before claiming "few distinct values".

| Index | est rows | Pages | Packed minimum (all distinct) | Same table's unique index | Reading |
|---|---|---|---|---|---|
| users_userprofile.created_by_id | 978,022 | **1,790** | ≈2,665–2,720 | user_id_key 3,943; pkey 4,030; **language_id (≤ 3 keys) 2,127** [rev5] | **Some keys repeat** (below the packed minimum). Not created by self on every row. The number of distinct creators is unknown; "mostly a system user" is *not* shown [rev5]. |
| personalization_detail.created_by_id | 94,394 | **136** | ≈257–262 | pkey 395 | **Some keys repeat** (about half the packed minimum). Repeat senders and/or a shared system/guest user; the split is unknown [rev5]. The share owned by a system user must be removed before any per-user rate (Open Question 9). |
| users_blacklisteduserdetail.created_by_id | 48,646 | **1,569** | ≈133–135 | pkey 1,560 (itself ≈11x oversized) | **No reading [rev5].** Above the packed minimum, so the one-sided test says nothing; the pkey comparison is confounded by fill factor and bloat (see the actor note above). |

Inbound FKs from out-of-scope tables, with sizes [rev4: rewritten from a fresh Q18 run, Q37; 65 FK rows]. Row counts are reltuples estimates; pages are exact.

**Populated transactional referrers** (the join points that matter):

| Source table | est rows | Pages | Column → target |
|---|---|---|---|
| order_order | 1,232,173 | 176,977 | user_id → users_customuser; guest_id → users_guestuser; region_id → catalogue_store; **created_by_id, modified_by_id → users_customuser** |
| basket_basket | 3,041,571 | 162,789 | owner_id → users_customuser; guest_id → users_guestuser; region_id → catalogue_store |
| order_line | 1,473,029 | 51,146 | product_id → catalogue_product; partner_id → partner_partner; created_by_id, modified_by_id → users_customuser |
| order_orderlinequantitydetail | 1,474,250 | 48,292 | created_by_id, modified_by_id → users_customuser |
| basket_basketquantitydetail | 1,783,453 | 37,861 | created_by_id, modified_by_id → users_customuser |
| basket_line | 1,789,338 | 32,298 | product_id → catalogue_product |
| payment_paymentdetail | 761,949 | 21,939 | created_by_id, modified_by_id → users_customuser |
| payment_paymenttransactionpayload | 65,123 | 16,961 | created_by_id, modified_by_id → users_customuser |
| basket_basketpersonalisedetail | 553,383 | 9,403 | created_by_id, modified_by_id → users_customuser |
| order_orderlinepersonalisedetail | 496,737 | 8,599 | created_by_id, modified_by_id → users_customuser |

Note: order_order has **three** FKs to users_customuser (user_id, created_by_id, modified_by_id). The buyer is user_id (or guest_id); created_by_id is the acting user and may differ (staff-placed orders, system user on guest checkout). Never join on created_by_id to mean "the customer" without checking.

**Small staff/config referrers** (audit actors only, not customer behavior):

| Source table | est rows | Column → target |
|---|---|---|
| django_admin_log | 2,608 | user_id → users_customuser (staff) |
| core_currencyexchangerate | 437 | created_by_id, modified_by_id |
| order_orderplacedcountry | 187 | created_by_id, modified_by_id |
| otp_totp_totpdevice / otp_static_staticdevice | 28 / 1 | user_id (**staff admin 2FA**, django-otp) |
| core_currency 23, address_country 22, payment_paymentmethod 20, core_basecurrency 19, address_countryvat 14, core_remoteurlconfig 9, core_currencybasketlimit 8, core_language 2, core_siteconfig 1, order_giftactivationconfig 1, webhooks_webhookconfig 1, core_commandexecuter (-1, 2 pages) | as listed | created_by_id, modified_by_id |

**Empty (0 pages), so not join points:** address_useraddress, payment_bankcard, voucher_voucherapplication, order_ordernote, two_factor_phonedevice, jet_bookmark, jet_pinnedapplication, core_unsupportedcountry.

Logical keys (not FKs):
- personalization_detail.cart_reference_id / order_reference_id → basket and order references (varchar).
- order_line.offer_code vc(10) → offer_plusoffer.code vc(10) (same type; probably also offer_productoffer.code vc(50)). order_line.is_offer_applied is indexed [rev2].
- users_guestuser.db_session_id vc(512) → django_session.session_key vc(40) (no FK) [rev2]. **db_session_id is not indexed** (only id and session_id are, Q30). A join from django_session to guests would therefore seq-scan the 43 MB guest heap. This is a cost caveat; drive the join from the guest side or filter first [rev3].
- basket_mergedbasket.(guest_basket_id, user_basket_id) → basket_basket.id (declared FKs, both indexed) [rev3]. Together with users_mergeduser it gives a full guest→registered conversion: identity merge plus cart carry-over. basket_basket.guest_id / owner_id then bridges back to users_guestuser / users_customuser.
- user_tip_invoice (content_type_id, object_id) → generic FK, probably to user_tip_tip.
- analytics_recommendedbrand.product is a varchar, not an FK.

## Lifecycle States

**BLOCKED — needs grant: the enum columns in the table below (see Grant request).** SELECT is denied (Q3/Q4/Q17). These are the enum-like columns to profile once access is granted. The Django choices are not in the DB, and there are no CHECK constraints on them (Q7).

| Column | Type | Notes |
|---|---|---|
| users_blacklisteduserdetail.type / source / is_removed / is_guest | vc(25)/vc(25)/bool/bool | Blacklist dimension (likely email/phone/card/ip) and origin. is_removed is a soft delete. |
| users_cognitouserdatasynclog.status (+ modified_on > created_on) | vc(10), nullable | Sync success/failure. `error` jsonb is NOT NULL. A NULL status could mean in-flight. modified_on after created_on is a retry/reprocess marker [rev3]. |
| personalization_update_kafka_data_log.status | vc(20) | Kafka consume outcome. error_data holds the failure text. |
| kafka_blacklistuserkafkadatalog.status; kafka_blacklistusergiftlog.status; kafka_legacyfraudsynclog.status (out of scope) | vc(20) / vc(200) / vc(200) | Blacklist and fraud event ingestion outcome. |
| users_userprofile.is_deleted / is_enabled / trusted_user / is_email_verified / is_phone_number_verified | bool | Account lifecycle and trust. |
| users_customuser.is_active / is_staff | bool | |
| users_guestuser.platform / is_active | vc(20) / bool | Channel (web/ios/android?). |
| catalogue_product.structure / classification / redemption_type / activation_fee_deduct_type | vc | Brand taxonomy. |
| catalogue_productdenominationrange.range_type; catalogue_producthandlingfee.handling_fee_type | vc | |
| offer_plusoffer.offer_mode / offer_type / offer_channel / funding_method / budget_type / sponsor_payment_threshold_type / reason_code | vc | Campaign type and state. |
| offer_plusoffer.is_active / is_budget_available / has_budget_exceeded, start_date/end_date, promo_code_end_date | bool / tstz | Campaign lifecycle: scheduled → live → budget-exhausted → expired; promo codes have their own expiry. |
| offer_offerpromocode.status | vc(20) | |
| offer_productoffer.offer_base / offer_type / channel / funding_method | vc | |
| user_tip_tip.status / platform; user_tip_invoice.state | vc | Tip payment state machine (state vc(63) looks like django-fsm). |
| user_tip_tip.send_tip_gift_event_triggered | bool NOT NULL | Event-emission flag [rev3]: whether the tip's downstream gift event fired. status = paid with the flag false would be a stuck-trigger friction signal. |
| reviews_googlereview.platform / is_reviewed | vc(15) / bool | See the semantics caveat (reviewed_date NOT NULL). |
| System toggles (out of scope) [rev3]: core_siteconfig.is_guest_enabled; order_giftactivationconfig.is_guest_enabled, is_instant_activation_enabled | bool, 1-row config tables (Q31/Q32) | Global switches that shape the guest-checkout and gift-activation funnels. Any guest-conversion or activation trend must be read against when these flipped. There is no history table, so a flip is only visible as a discontinuity. Related: catalogue_product.allow_instant_activation (per brand) and payment_paymentdetail.exclude_instant_activation (per payment). |

## Time Coverage & Trends

**BLOCKED — needs grant: the timestamp columns listed below (see Grant request).** SELECT is denied. There are no min/max timestamps and no monthly trend. Main timestamp columns to use once granted:
- users_customuser.date_joined (signup), users_customuser.last_login.
- users_userprofile.created_on, users_guestuser.created_on / last_accessed (see the write-once caveat below), users_mergeduser.created_on and basket_mergedbasket.created_on (guest conversion) [rev3].
- users_blacklisteduserdetail.created_on, users_cognitouserdatasynclog.created_on / modified_on (retry lag) [rev3].
- personalization_detail.created_on, personalization_update_kafka_data_log.start_timestamp / completed_timestamp (latency).
- offer_plusoffer.start_date / end_date (indexed together), promo_code_end_date, reviews_googlereview.reviewed_date, user_tip_tip.created_on.
- django_session.expire_date (out of scope; session activity window).

Index caveat (Q9, Q14): **none of these timestamp columns is indexed**, except offer_plusoffer (start_date, end_date) and the unused catalogue_product date indexes. Trends on users_customuser (about 992k rows) and the log tables will need TABLESAMPLE SYSTEM or `id`-range bucketing (PK index) rather than timestamp filters.

Freshness: the replica is in recovery (Q8), with **35.5 days** of uptime and a stats window of the same length (Q21, exact). `pg_stat_user_tables.last_analyze` is NULL on the replica.

**Replica lag is measurable [rev5: rev1–rev4 were wrong] (Q43, exact).** `pg_last_xact_replay_timestamp()` is unsupported on Aurora, but `aurora_replica_status().replica_lag_in_msec` works for this role. Five samples on 2026-09-29 (four in Q43 plus the critic's re-run) read **8, 10, 22, 24 and 26 ms** for the reader this role is connected to. Aurora readers share the writer's storage volume, so this lag is the delay in applying changes to the reader's buffer cache: sub-second, not the minutes-to-hours of a logical replica. **For guardrail 2 (provenance on every number)**, the atlas connector should read `replica_lag_in_msec` for its own instance (`server_id = aurora_db_instance_identifier()`) at query time and thread it into the freshness chip as "replica lag N ms as of <now()>". A value above a threshold (for example 5 s) should be surfaced as a stale-data warning. This is a runtime metadata call and needs no grant.

**Daily full-extract cadence [rev4] (Q40).** Over a 35.53-day stats window, exactly five tables show **seq_scan = 36**, and each scan reads the whole table (seq_tup_read / 36 ≈ the row estimate):

| Table | seq_scan | seq_tup_read | per scan | est rows | idx_scan |
|---|---|---|---|---|---|
| users_customuser | 36 | 35,283,827 | ≈980k | 991,558 | 144 (= 4 × 36) |
| users_userprofile | 36 | 35,282,819 | ≈980k | 978,022 | 72 (= 2 × 36) |
| order_line | 36 | 52,250,619 | ≈1.45M | 1,473,029 | 745,225 |
| order_orderlinequantitydetail | 36 | 52,250,619 | ≈1.45M | 1,474,250 | 72 (= 2 × 36) |
| payment_paymentdetail | 36 | 27,095,666 | ≈753k | 761,949 | 102,248 |

36 scans in 35.5 days is **one full read per day** (plus the partial first day). The index-scan counts on customuser, userprofile and orderlinequantitydetail are exact multiples of 36, so it is the same job doing a few indexed lookups per run.

**order_line ↔ order_orderlinequantitydetail is strictly 1:1 [rev5] (Q40, Q46; STRUCTURAL, catalog-exact).** Their seq_tup_read totals are *identical* (52,250,619 each, re-confirmed in Q46), even though their reltuples estimates differ (1,473,029 vs 1,474,250). Identical tuple totals over 36 scans mean the two tables had the same live row count at every run, and the constraints explain why: `order_orderlinequantitydetail.line_id` is **UNIQUE** and an **FK to order_line(id)** (Q46), and its line_id_key index (4,084 pages) matches its pkey (4,089). So each order line has at most one quantity-detail row, and in practice exactly one. For the atlas: this is a safe 1:1 join (no fan-out), the detail table can be modelled as an extension of order_line rather than as its own entity, and the reltuples gap (≈1.2k) is estimate noise, not missing rows. **Reading (STRUCTURAL):** some role runs a **daily full extract** of users, profiles, order lines, line quantities and payments on this replica, most likely an ETL/warehouse feed. For freshness this matters twice: (1) any downstream copy of these tables is at most about one day stale; (2) that feed may already be a governed source the atlas could reuse instead of new grants (Open Question 16). pg_stat_statements hides the query text and role for these (Q11), so the job cannot be identified from this role.

**Index-vs-table reltuples cross-check [rev2] (Q19).** VACUUM sets a btree index's reltuples to the exact number of index entries it saw. The table's reltuples may be an ANALYZE sample or a VACUUM extrapolation, so a gap between the two is a free freshness/growth signal. It is not a count.

| Table | table est | PK index est | Gap | Reading |
|---|---|---|---|---|
| users_guestuser | 82,502 | 88,689 | +7.5% | Index saw more entries. Either guests grew about 7.5% after the table's stat, or the table figure is an extrapolation. Use 88.7k as the better lower bound. |
| catalogue_product | 3,442 | 3,168 | −8% | Index stat is older (products added since), or the table estimate overshoots. Range 3.2k–3.4k. |
| catalogue_productcategory | 31,311 | 31,881 | +1.8% | Minor growth. |
| django_session (oos) | 284,567 | 284,510 | ~0 | Consistent. |
| kafka_blacklistusergiftlog (oos) | 7,354 | 7,393 | +0.5% | Consistent. |
| users_blacklisteduserdetail | 48,646 | 48,646 | 0 | Same VACUUM event. Consistent in count, but see the page-density anomaly below. |
| users_cognitouserdatasynclog | 93,871 | 93,871 | 0 | Same as above. |
| users_mergeduser, user_tip_tip, user_tip_invoice, offer_productoffer | -1 | 0 (1 page) | — | Index stats date from index creation (empty). Never refreshed. Unusable. |

**Visibility map: write-once vs mutable [rev3] (Q29).** `relallvisible / relpages` is replicated from the primary's last VACUUM. A page stays all-visible until a row on it is updated or deleted. So a high ratio means rows are effectively write-once, and a low ratio means rows are rewritten in place (or deleted) between vacuums. These are exact page counts, but they are a snapshot as of the last vacuum.

**Caveat: timing-dependent, weak evidence [rev4].** relallvisible depends on *when the last vacuum ran*. Right after a vacuum almost every page is all-visible; just before the next one, any table with inserts, updates or deletes looks "mutable". So a low ratio does not prove in-place updates. It can mean "vacuum is due". **Example from this profiling window:** personalization_update_kafka_data_log read 17,822 / 28,464 = **62.6%** all-visible in Q29 and **29,002 / 29,005 = 99.99%** later the same day (Q38), after the primary vacuumed it. The rev3 reading "log rows updated in place" is **refuted** by that flip. Readings in this table such as "googlereview rows updated in place, so it is a prompt table" or "cognito log rows are retried" are therefore **weak evidence and must not drive semantics** until the NEEDS-GRANT first queries (7, 11, 12) run. Only the extremes, 100% on a large table (guestuser) or ≈0% on a large table (customuser), are reasonably robust, and even they are single snapshots.

| Table | all-visible / pages | % | Reading |
|---|---|---|---|
| users_guestuser | 5,300 / 5,300 | 100.0 | **Write-once.** last_accessed is probably not refreshed in place. Any "guest activity / last seen" metric on last_accessed is suspect (first query 12). |
| users_mergeduser, basket_mergedbasket, user_tip_tip, user_tip_invoice, offer_productoffer, partner_partner | all pages | 100.0 | Write-once or rarely edited. Tip status and invoice state probably settle before the next vacuum, or the rows are small and rarely vacuumed. |
| catalogue_product | 1,064 / 1,065 | 99.9 | Brand config is stable. |
| personalization_detail | 21,699 / 21,798 | 99.5 | Write-once payloads (single snapshot). The 1.37–1.49 Kafka messages per personalization then land in the log, not as in-place edits [rev4: ratio range]. |
| users_blacklisteduserdetail | 19,822 / 20,078 | 98.7 | Stable (is_removed rarely flipped). |
| offer_plusoffer | 426 / 453 | 94.0 | Churn is periodic, not constant. |
| catalogue_productdenomination | 307 / 351 | 87.5 | Some denomination edits. |
| offer_plusoffer_happy_cards | 60 / 76 | 78.9 | Offer↔brand link churn. |
| order_orderlinepersonalisedetail (oos) | 6,161 / 8,599 | 71.6 | |
| users_userprofile | 13,146 / 19,162 | 68.6 | Moderate profile edits (verification flags, language). |
| kafka_plusofferkafkadatalog (oos) | 1,434 / 2,217 | 64.7 | |
| personalization_update_kafka_data_log | 29,002 / 29,005 (Q38) [rev4]; was 17,822 / 28,464 in Q29 | 99.99 (was 62.6) | **[rev4] The rev3 reading "log rows updated in place" is refuted.** The table was vacuumed during the profiling window and is now fully all-visible. The ratio only reflects vacuum timing. |
| basket_basketpersonalisedetail (oos) | 5,521 / 9,403 | 58.7 | |
| catalogue_producthandlingfee | 9 / 18 | 50.0 | **Active fee-rule churn.** |
| users_cognitouserdatasynclog | 4,076 / 12,171 | 33.5 | Mutable, or vacuum due, or retention deletes. **Weak evidence of retries** [rev4] (NEEDS-GRANT: first query 7). |
| reviews_googlereview | 278 / 935 | 29.7 | Consistent with in-place updates (is_reviewed flips), but **weak evidence** [rev4]: it may only mean a vacuum is due. Do not use it to decide the prompt-vs-review semantics (NEEDS-GRANT: first query 11). |
| catalogue_productdenominationrange | 34 / 200 | 17.0 | **Active pricing-range churn.** |
| users_customuser | 50 / 13,798 | 0.4 | Nearly every page rewritten (last_login updates across the user base). |
| offer_offerpromocode | 0 / 2 | 0.0 | **Promo-code status churn** (tiny table). |

**Page-density anomaly [rev2] (Q19, Q20).** It affects the two tables whose volumes are now marked low-confidence:
- users_blacklisteduserdetail: 20,078 heap pages for 48,646 rows is **2.4 rows/page**. The widest possible row is at least 498 B (bounded columns only, no unbounded types) plus a 24 B header, and there is no TOAST data. **[rev3] 498 B is a lower bound, not a maximum:** the varchar typmod counts characters, not bytes. The four varchars total 456 characters (type 25, value 256, source 25, reference_id 150; Q35), so the true byte maximum under UTF-8 is up to about 1.9 KB (4 bytes/char), or about 0.95 KB for 2-byte Arabic. For ASCII values (emails, phones, card fingerprints, IPs) about 500 B holds, and a page fits 15 or more rows, i.e. room for 300k or more rows. Even at the 4-byte extreme a page fits about 4 rows, which is still above the observed 2.4, so the anomaly stands, but it is weaker than stated in rev2. The PK btree (bigint) is **1,560 pages**. About 135 pages would be expected for 48.6k packed entries, roughly 11x. By contrast users_customuser_pkey is 2,775 pages for 991k rows, which is consistent. 98.7% of the heap pages are all-visible (19,822 of 20,078), so there is no ongoing update churn. **Interpretation:** either reltuples is badly stale (the table is much bigger than 48.6k), or there was a past mass insert followed by a mass delete/prune, which leaves sparse heap and index pages that new inserts reuse without extending. **48.6k is low-confidence.** An exact count(*) is the first thing to run once granted.
- users_cognitouserdatasynclog: the PK is **1,231 pages** against about 256 expected for 93.9k rows (about 4.8x). Only 33% of heap pages are all-visible (4,076 of 12,171), consistent with active inserts plus retention deletes. **93.9k is low-confidence** for the same reasons.

## Behavior Signals

What this unit **can** capture (volumes are estimates):
- **Registration / identity:** about 992k registered users, about 978k profiles and 82.5k–88.7k guest identities. users_mergeduser records guest→registered conversion (at most about 3.7k rows, bound). That makes a guest-conversion funnel possible, but see the cardinality caveat in Data Quality.
- **Guest-conversion funnel, two layers [rev3]:** (1) identity merge, `users_mergeduser` (≤ about 3.7k); (2) **cart carry-over at login**, out-of-scope `basket_mergedbasket` (≤ about 1.2k rows, bound from 10 heap pages × about 68 B/row). A guest who logs in with a live cart should produce both rows. So (mergedbasket rows) / (mergeduser rows) is a **cart carry-over friction signal**: guests who converted but whose cart did not merge. Both bounds are upper bounds, so the ratio cannot be estimated yet (first query 8). Guest-checkout volume is also gated by the `is_guest_enabled` switches (core_siteconfig, order_giftactivationconfig).
  - **[rev5] Second carry-over signal, on basket_basket itself (Q44, Q45).** basket_basket (3.04M est) has **`status` vc(128) NOT NULL** and **`date_merged` timestamptz (nullable)**, next to date_created and date_submitted. In django-oscar, merging one basket into another sets the source basket's status to `Merged` and stamps `date_merged` (Oscar's other native states are Open, Saved, Frozen, Submitted; YGG's actual values are unverified). So basket_basket records every merged basket, not only the ones that reached basket_mergedbasket (≤ about 1.2k). Comparing `count(status='Merged' or date_merged IS NOT NULL)` with basket_mergedbasket rows tells whether basket_mergedbasket is the complete merge log or a later, partial one. Neither column is indexed (Q45: basket_basket indexes are pkey, owner_id, parent_id, guest_id, region_id, language_id only), so this needs TABLESAMPLE. STRUCTURAL; NEEDS-GRANT: basket_basket.status, date_merged, date_created (first query 18).
- **Verification / trust [rev2]:** email- and phone-verified flags and trusted_user on users_userprofile. **There is no customer 2FA.** two_factor_phonedevice is empty (0 pages). otp_totp_totpdevice (28) and otp_static_staticdevice (1) are **staff admin 2FA** (django-otp), in line with users_usermetadata (25) and users_customuser_groups (30). They must not be used as customer trust signals.
- **Account lifecycle:** is_deleted and is_enabled on the profile. The Cognito sync log records the identity-provider sync. Its **retry/reprocess rate** is visible as `modified_on > created_on` by status (first query 7). The 33.5% all-visible heap is only weak, timing-dependent evidence that rows are touched after insert [rev4: downgraded, see the visibility-map caveat].
- **Guest activity caveat [rev3]:** users_guestuser is 100% all-visible, so guest rows are not updated in place between vacuums. `last_accessed` is therefore probably an insert-time value, not a live "last seen". Do not build a guest-recency metric on it until first query 12 confirms it changes.
- **Login activity (system signal) [rev2]:** only 50 of users_customuser's 13,798 heap pages are all-visible (0.4%). Nearly every page has been rewritten since the last vacuum, which is consistent with last_login updates spread across the whole user base. users_userprofile is 69% all-visible.
- **Gift creation / personalization [rev2]:** about 94k personalization payloads, each tied to the acting user by `created_by_id` (NOT NULL FK) as well as to cart/order references. So a **per-user personalization rate** = count(DISTINCT created_by_id) / active purchasers can be computed directly. Line-level personalisation also exists out of scope (basket_basketpersonalisedetail 553k, order_orderlinepersonalisedetail 497k).
  - **[rev4] Ratios (estimates, refreshed Q38):** personalization_update_kafka_data_log / personalization_detail = 128,996 / 94,394 ≈ 1.37 (heap estimate) to 140,520 / 94,394 ≈ 1.49 (PK-index estimate), so **about 1.37–1.49 update messages per personalization** (rev3 said 1.47 from 139,132). Detail rows are 99.5% all-visible (write-once, single snapshot), so the extra messages are post-creation edits propagated through Kafka, retries of failed consumes, or both. NEEDS-GRANT: personalization_update_kafka_data_log.status to tell which.
  - **[rev3] Coverage:** personalization_detail is ≈ **19%** of order_orderlinepersonalisedetail (94,394 / 496,737) and ≈ 17% of basket_basketpersonalisedetail (94,394 / 553,383). It is not the full personalization record: most likely a newer personalization service with a start date after the line-level tables, or a partial (per-channel/per-brand) rollout. **A "personalization rate" must be defined on order_orderlinepersonalisedetail** or restricted to the period after personalization_detail's first created_on (first query 13).
- **Campaigns / offers [rev2]:** 378 Plus offers with budgets, sponsor payment networks, promo codes (with their own `promo_code_end_date` expiry), and merchandising placement (`featured_order`, `brand_tile_order_number`, `offer_order_number`), plus about 10.6k offer↔brand links and 41 promo codes. **The voucher path is dead:** voucher_* tables, basket_basket_vouchers and order_orderdiscount / order_orderlinediscount are all empty. Per-line redemption is recorded in **out-of-scope `order_line.is_offer_applied` (indexed) and `order_line.offer_code` vc(10)**, which joins logically to offer_plusoffer.code. Offer config changes stream through kafka_plusofferkafkadatalog (about 201.7k, oos) and kafka_productofferkafkadatalog (767, oos).
- **offer_plusoffer row-size anomaly [rev2, re-ranked rev3] (Q14, Q20, Q29, Q34):** the heap is 3.71 MB (453 pages) plus 1.8 MB TOAST for 378 rows, about **9.8 KB of heap per row (0.83 rows/page)**. PostgreSQL toasts rows above about 2 KB, so the live inline data needs about 100 pages at most. The remaining space is dead-tuple churn from rewrites of a 59-column, trilingual row.
  - **Primary evidence: Kafka config-sync rewrites.** kafka_plusofferkafkadatalog holds about 201,682 messages (estimate) for 378 offers, ≈ **534 config messages per offer**. If each message upserts its offer row, that alone produces hundreds of dead versions per row, which is enough to explain the bloat.
  - **Hypothesis, unverified: per-redemption budget updates** (has_budget_exceeded / budget fields changing on redemption). The replica's counters are all zero (n_tup_ins/upd/del = 0 on offer_plusoffer and the Kafka log, Q34), so the two causes cannot be distinguished from this role.
  - **Supporting evidence: Kafka log size [rev4] (Q38).** kafka_plusofferkafkadatalog is 1.55 GB total, of which **1.53 GB (1,525,874,688 B) is TOAST** against an 18 MB heap. That is ≈ **7.6 KB of toasted payload per message** (1.526 GB / 201,682). A 7.6 KB message is the size of a full 59-column trilingual offer document, not a small budget delta. So the messages look like **full-config re-publishes**, which fits "each message rewrites the whole offer row". STRUCTURAL.
  - **Cost / retention note [rev4].** At about 534 messages per offer and 7.6 KB each, this log (1.55 GB) is larger than any in-scope table (the largest, users_userprofile, is about 0.5 GB) and about 260x offer_plusoffer itself (6 MB) and has no visible retention. The atlas should never scan it; if offer-change history is ever needed, a governed view of (offer id, created_on, status) without the payload is enough.
  - 94% of pages are all-visible (single snapshot), consistent with periodic sync bursts rather than constant churn.
- **Reviews:** about 24k Google-review rows. is_reviewed gives a prompt→review conversion **only if** rows are created at prompt time. reviewed_date is NOT NULL, which makes that ambiguous (see Entities). The 29.7% all-visible heap is consistent with in-place updates (is_reviewed flips), but this is weak, vacuum-timing-dependent evidence and must not decide the semantics [rev4]. NEEDS-GRANT: reviews_googlereview.is_reviewed, reviewed_date, created_on, modified_on (first query 11).
- **Tipping:** a small tip product (sender, status, platform, invoice state). Bound roughly 500–1,100 tips. **Trigger signal [rev3]:** `send_tip_gift_event_triggered` (bool NOT NULL) records whether the tip emitted its downstream gift event. Tip → gift event conversion = share true among successful tips, and a successful status with the flag false is a stuck-event failure (first query 9).
- **Incentive programs (out of scope, nearest to "referral") [rev3] (Q31):** payment_paymentmethod (20 rows) has is_point_program, is_point_program_full_redemption / partial_payment / data_push_enabled and point_program_code. payment_paymentdetail (about 762k, estimate) has point_program and point_collection_enabled. youpayclient_youpayclienttransactiondata (about 1.23M, estimate) has earned_point, redeemed_points, available_points and loyalty_level. These are bank/loyalty point programs used at payment, not customer referral, but they are the only incentive signals in the DB.
- **Conformed platform dimension [rev4] (Q41).** Five tables carry a `platform` column: basket_basket (vc(20) NOT NULL, 3.04M est), order_order (vc(20) NOT NULL, 1.23M), users_guestuser (vc(20) NOT NULL, 82.5k), user_tip_tip (vc(15) NOT NULL, indexed), reviews_googlereview (vc(15), nullable). A sixth, youpayclient_youpayclienttransactiondata.platform (vc(200), nullable), sits on the payment side. Only user_tip_tip indexes it. These should be modelled as **one conformed `platform` dimension** (web / iOS / Android / ...) so funnels can be cut by channel end to end: guest identity → basket → order → payment → review/tip. Risks (STRUCTURAL): the widths differ (15 vs 20 vs 200), so the value sets may not match (e.g. `ios` vs `iOS` vs `ios_app`); googlereview allows NULL. NEEDS-GRANT: the platform column on each of these tables; first queries 15 (guestuser full distribution, basket/order via TABLESAMPLE SYSTEM(1), googlereview and tip full) establish the value sets and a mapping.
- **Web sessions (oos) [rev2]:** django_session holds about 284.6k rows (estimate), and users_guestuser.db_session_id points into it. `expire_date` gives a live-session count and a session-activity window. session_data is a token and must never be read.

What is **not** captured here: product views, searches, basket additions and per-user analytics (all analytics_* tables are empty), and wishlists, product alerts and in-app notifications (empty). **No referral data anywhere in ygag_ecom_orders_db [rev3: DB-wide finding] (Q30).** No public table name and no column name anywhere in the database matches `referr|invite|utm|affiliate` (0 tables, 0 columns). Acquisition attribution (referral, UTM, affiliate) is not stored in this DB and must come from another source (analytics stack or marketing DB). The nearest incentive signal is the loyalty point-program columns in payment_* and youpayclient_* (above).

Replica read-traffic signals (exact, replica-local counters over the 35.5-day stats window, Q9/Q21, **Q10 re-run without the `_like` exclusion as Q33** [rev3]):
- catalogue_product: 29.07M index scans. **[rev3 corrected] The largest is `catalogue_product_upc_91f72b90_like` at 13,449,875 (≈46%)**, then pkey 10,524,655 (≈36%), retailer_id 3,526,874 (≈12%) and store_id 1,564,800 (≈5%). The plain `upc_key` unique index has 0 scans, so UPC lookups go through the `varchar_pattern_ops` index, i.e. equality or prefix (`LIKE 'x%'`) lookups by UPC. **UPC is the dominant operational brand-resolution key on the replica.** Slug indexes: 0 scans.
- partner_partner: 16.9M index scans, all on pkey (16,944,848).
- offer_plusoffer: 13.2M index scans: pkey 6.12M, brand_id 3.71M, (start_date, end_date) 3.40M. code_key / code_like have 0 scans, so the replica does not resolve offers by code.
- offer_plusoffer_happy_cards: 3.3M index scans (plusoffer_id 1.82M, product_id 0.90M, the unique pair 0.56M).
- catalogue_store: 2.08M sequential scans. A small table scanned on every request.
- analytics_recommendedbrand: 6,028 sequential scans (6,021 at rev2; the counter is live) [rev3].
- payment_paymentmethod (oos): 31,953 sequential scans. The point-program config is read on the replica [rev3].
- order_order 452.7k idx / 2,178 seq; order_line 738.4k idx at rev2, 745.2k in Q40 (oos).
- **Daily full extract [rev4] (Q40):** users_customuser, users_userprofile, order_line, order_orderlinequantitydetail and payment_paymentdetail each have **exactly 36 full-table seq scans** in 35.5 days (one per day). See Time Coverage → Freshness for the table and Open Question 16.

**Replica non-usage [rev2] (Q22, Q23).** Over 35.5 days the following show **idx_scan = 0 on every index and seq_scan = 0** on the replica: personalization_detail, users_blacklisteduserdetail, users_guestuser, users_mergeduser, users_cognitouserdatasynclog, catalogue_productdenomination, catalogue_productdenominationrange, catalogue_producthandlingfee (1 seq scan), offer_offerpromocode, offer_productoffer, user_tip_tip, user_tip_invoice, reviews_googlereview, personalization_update_kafka_data_log, the kafka_blacklist*/legacyfraud logs, django_session, **basket_basket**, basket_mergedbasket, core_siteconfig and order_giftactivationconfig [rev3, Q32]. users_userprofile has 72 idx scans (all on user_id_key), and users_customuser has 144 idx + 36 seq.

So the replica's **online** traffic is brand listings, active-offer lookups and some order reads, and it **also serves a daily full extract** of users, profiles, order lines, line quantities and payments [rev4: corrected; rev3 said "only"].

**Checkout-path lookups run on the writer [rev5: now backed by topology].** The cluster has exactly one writer and one reader (Q43), and the reader shows zero scans on the checkout-path tables (denomination, handling fee, promo code, blacklist check, guest session, personalization, basket) over 35.5 days. With no second reader to absorb them, those lookups must be served by the writer. STRUCTURAL (it assumes the app talks only to this cluster).

**Order reads on the reader are full scans [rev5] (Q46, exact).** order_order has 2,180 seq scans reading 2,615,645,228 tuples, ≈1.2M per scan, which is the whole table (1.23M est, 176,977 pages ≈ 1.45 GB). That is ≈61 full scans of a 1.45 GB table per day on the reader, beyond the daily extract.

For the atlas:
1. The reader has no warm cache to rely on for the checkout-path tables; atlas queries on them would read cold pages.
2. Freshness is measurable: replica lag was 8–26 ms (Q43). Checkout-path and user-state metrics read from the reader are sub-second behind the writer, and the lag should be recorded per query (see Time Coverage → Freshness).
3. **Reader contention risk (guardrail 3).** This single reader is shared by 40 databases and already carries the production online read traffic (catalogue_product 29.07M index scans, partner_partner 16.9M, offer_plusoffer 13.2M, catalogue_store 2.08M seq scans, ≈61 full order_order scans a day) plus a daily full extract. Heavy atlas queries do not touch the writer, but they compete for the *only* reader's CPU, I/O and buffer cache with the app's live reads. If the reader is saturated the app's reads slow down, and if it becomes unavailable Aurora's reader endpoint falls back to the writer, which moves atlas load onto the primary. So "safe for the writer" is not enough: atlas load on this reader must stay light (catalog stats, TABLESAMPLE, indexed filters, statement_timeout), and any recurring heavy workload (trends over basket_basket/order_order, full-table aggregates) belongs on a separate replica, an Aurora clone, or the daily extract's downstream copy (Open Question 16). BLOCKED for a quantitative load assessment: CloudWatch reader CPU / ReadIOPS / BufferCacheHitRatio is not reachable from this role (grant request: CloudWatch read on the cluster for the atlas team, or have the DBA supply it).

## Friction & Errors

**BLOCKED — needs grant: the status/flag columns in the table below (see Grant request).** Rates are not measurable. Friction and error sources identified (all STRUCTURAL):

| Source | est rows | Signal |
|---|---|---|
| users_blacklisteduserdetail | 48,646 (**low confidence**, see page-density anomaly) | Blocked identities by type and source. Removals use is_removed. The heap/index size points to either stale stats or a past mass delete/prune, **not** per-row update churn (98.7% all-visible). |
| kafka_blacklistusergiftlog (oos) | 7,354 (idx 7,393) | Event source for blacklist decisions tied to gifts: event_id uuid, payload text, **status** vc(200), error. |
| kafka_blacklistuserkafkadatalog (oos) | 2,317 | Blacklist ingestion: data jsonb, **status** vc(20), error_data, start/completed timestamps (latency). |
| kafka_legacyfraudsynclog (oos) | 16,691 | Legacy fraud-system sync: event_id, payload, **status**, error. Probably the upstream for blacklist `source`. |
| users_cognitouserdatasynclog | 93,871 (**low confidence**) | Cognito sync failures: status plus error jsonb. Retry/reprocess rate: modified_on > created_on [rev3]. |
| basket_mergedbasket vs users_mergeduser (oos / in scope) [rev3] | ≤ about 1.2k / ≤ about 3.7k (bounds) | Guests who converted but whose cart did not carry over (identity merge without a basket merge). |
| basket_basket.status = 'Merged' / date_merged IS NOT NULL (oos) [rev5] | 3.04M est (share unknown) | Oscar-native merge state on every basket. Cross-check against basket_mergedbasket to see whether that table is complete. NEEDS-GRANT: first query 18. |
| user_tip_tip.send_tip_gift_event_triggered = false on a completed tip [rev3] | — | Tip paid but gift event not emitted (stuck trigger). |
| personalization_update_kafka_data_log | 128,996–140,520 [rev4] | Kafka consumer failures (status, error_data) and processing latency (completed − start). |
| offer_plusoffer.has_budget_exceeded / is_budget_available / promo_code_end_date; offer_productoffer.has_budget_exceeded | — | Campaign exhaustion and promo expiry friction ("offer no longer available"). |
| users_userprofile.is_enabled = false / is_deleted | — | Disabled or deleted accounts. |
| user_tip_invoice.state, is_flagged_email_sent | — | Payment failure or flagging for tips. |
| catalogue_product.require_mobile_verification | — | Purchase gating (extra verification step). |
| **payment_paymentdetail.is_fraud / is_flagged** (oos) [rev4] (Q42) | 761,949 est | **Fraud outcome per payment**, both bool NOT NULL, not indexed. This is the outcome counterpart to the blacklist: the blacklist says who is blocked, these flags say which payments were judged fraudulent or held for review. With payment_status, payment_gateway and card_issuer_country they give a fraud/flag rate by gateway, country and channel. Linked to the order via order_id and to the actor via created_by_id. NEEDS-GRANT: first query 14. |
| **youpayclient_youpayclienttransactiondata.is_fraud / is_flagged / approved** (oos) [rev4] (Q42) | 1,229,851 est | The same fraud outcome on the YouPay payment-client side, plus `approved` and `response_summary` (decline reason, possibly free text: grant only after inspection). Carries `platform` and `channel_code`. NEEDS-GRANT: first query 14. |

## Cross-DB Keys

Types are from the catalog (Q2, Q13). Value ranges could not be measured: SELECT is denied and pg_sequences is NULL.

| Column | Type | Likely shared with |
|---|---|---|
| users_customuser.id | bigint | ecom user id. Used by order_order.user_id and possibly by other YGG DBs and analytics. |
| users_userprofile.cognito_id | varchar(150), UNIQUE, NOT NULL | **AWS Cognito sub**. The strongest cross-system user key (auth, mobile apps, other YGG services). |
| users_guestuser.session_id / db_session_id | varchar(512) | Web session → django_session.session_key vc(40). Treat as a token (PII-like). |
| **catalogue_product.upc** [rev3: promoted] | vc(64) UNIQUE | **Primary operational brand key.** It is the most-used catalogue_product lookup on the replica (13.45M of 29.07M index scans, ≈46%, via `upc_like`, Q33), ahead of the pkey. Other services and apps resolve brands by UPC, so it is the first-choice cross-DB brand join key. |
| catalogue_product.id / slug / reference_name | bigint / vc / vc | Brand id: pkey 10.52M scans (internal FK joins: order_line.product_id, basket_line.product_id). slug is UNIQUE but has 0 scans. reference_name is the external brand name/reference, a secondary candidate for a brand master in other DBs. |
| catalogue_productdenomination.gencode | vc(50) | Supplier denomination code (card-issuing / inventory systems). |
| catalogue_store.code / country_id | vc(4) / vc(2) ISO | Region code (e.g. store per country). Shared dimension. |
| partner_partner.code / ref_code | vc(32) UNIQUE / vc(20) | Retailer code for supplier and finance systems. |
| offer_plusoffer.code; offer_productoffer.code; offer_offerpromocode.promo_code | vc(10) / vc(50) / vc(200) | Campaign codes (marketing, campaigns DB). plusoffer.code joins order_line.offer_code vc(10). |
| offer_plusoffer.sponsor_payment_network_code | vc(20) | Payment network (bank or card sponsor campaigns). |
| personalization_detail.cart_reference_id / order_reference_id / personalization_reference_id | vc(255) | Cart and order reference shared with order and gift services. |
| user_tip_tip.reference_id / user_tip_invoice.reference_id | uuid / vc(50) | Payment reference (payment gateway). |
| users_blacklisteduserdetail.reference_id | vc(150) | Origin reference (order or payment?). Cross-reference with kafka_blacklist*.event_id / kafka_legacyfraudsynclog.event_id (uuid) from the fraud pipeline. |
| reviews_googlereview.user_reference | uuid (PK) | External user reference, possibly a gift-receiver or app user UUID. Pseudonymous: expose only as a hash for dedupe [rev3]. |
| basket_mergedbasket.guest_basket_id / user_basket_id (oos) [rev3] | bigint → basket_basket.id | Internal only. Bridges the guest and registered baskets. |
| payment_paymentdetail.order_id + is_fraud / is_flagged (oos) [rev4] | bigint / bool | Fraud outcome keyed by order: the join from the blacklist world (users_blacklisteduserdetail.reference_id, kafka_* event_id) to actual payments. Fraud/risk systems in other YGG DBs likely consume the same flags. |
| youpayclient_youpayclienttransactiondata.order_reference / payment_reference + is_fraud / is_flagged (oos) [rev4] | vc(200) / bool | Payment-client fraud outcome, keyed by external order/payment reference (shared with the payment gateway). Expose the references only as hashes. |

## PII

Column names only:
- users_customuser: email, username, first_name, last_name, password (hash, **secret**), last_login (a quasi-identifier: exact timestamps can re-identify someone when joined to other logs). **[rev3] Consistency with the grant list:** raw last_login is not granted. Only a day-truncated view is granted, which is enough for activity/recency metrics.
- users_userprofile: phone_number, cognito_id, gender, country_of_residence.
- users_guestuser: email, username, session_id, db_session_id (**session tokens**), extra (jsonb, may hold PII), note.
- users_blacklisteduserdetail: value (email, phone, card or IP by type), reference_id.
- users_passwordhistory: password_hash (**secret**).
- users_cognitouserdatasynclog: payload, error (jsonb, likely user attributes).
- personalization_detail: personalization_data (jsonb: sender and recipient names, messages, possibly contact details).
- personalization_update_kafka_data_log: data, error_data.
- reviews_googlereview: user_email, user_ip_address, user_agent, user_reference (pseudonymous uuid; hashed view only) [rev3].
- user_tip_tip: receiver_phone_number, extra. user_tip_invoice: card_last4.
- Out of scope: django_session.session_data (**token**); kafka_blacklist*/legacyfraud payload/data/error (fraud subject identifiers).
- communication_email: email, subject, body_* (empty). customer_productalert.email; wishlists_wishlistsharedemail.email; partner_partneraddress (first_name, last_name, line1–4, postcode); reviews_productreview (name, email). All of these are empty.

## Data Quality

- **Access:** 0 of 71 in-scope tables are readable (re-checked, Q17). This blocks every content metric.
- **Dead tables [rev2]:** 39 tables have 0 pages. They are all unused Oscar modules: analytics_* (4 of 5), wishlists_* (3), reviews_productreview and vote, communication_* (3), customer_productalert, partner_partner_users, partneraddress, stockrecord, stockalert, the offer_conditionaloffer / range / benefit / condition family (10), **catalogue attribute/option/image/recommendation (10: attributeoption, attributeoptiongroup, option, product_product_options, productattribute, productattributevalue, productattributevalue_value_multi_option, productclass_options, productimage, productrecommendation)** and users_customuser_user_permissions. users_passwordhistory has an empty heap. Out of scope, the voucher_*, basket_basket_vouchers and order_*discount tables are also empty.
- **Never analyzed [rev2]:** reltuples = -1 for user_tip_tip, user_tip_invoice, users_mergeduser, offer_productoffer, offer_productoffer_happy_cards and users_passwordhistory. Their PK index stats are also from creation (0 rows). Rough bounds from exact heap sizes and declared column widths (Q20):
  - users_mergeduser: 33 pages × about 110 rows/page (about 68 B/row) ≤ **about 3.7k merges**.
  - user_tip_tip: 42 pages, with jsonb `extra`, **roughly 500–1,100 rows** at 300–700 B/row.
  - offer_productoffer: 28 pages plus 240 KB toast, a few hundred rows.
  - user_tip_invoice: 15 pages, a few hundred rows.
  - basket_mergedbasket (oos) [rev3]: 10 pages × about 120 rows/page (24 B header + 40 B data + 4 B line pointer ≈ 68 B/row) ≤ **about 1.2k basket merges**.
  - These are upper-bound-style estimates that assume no dead space.
- **Low-confidence volumes [rev2]:** users_blacklisteduserdetail (48.6k) and users_cognitouserdatasynclog (93.9k). Their PK index is 11x and 4.8x larger than their reltuples implies, and the heap density is far below the column-width capacity. See Time Coverage for the evidence.
- **Order-line quantity detail is 1:1 [rev5] (Q46):** order_orderlinequantitydetail.line_id is UNIQUE with an FK to order_line, and both tables return identical seq_tup_read under the daily extract. Joins between them do not fan out.
- **Guest-conversion cardinality risk [rev2] (Q23b):** users_mergeduser has **no UNIQUE constraint** on guest_id or user_id, and **both are nullable**. One guest can map to many users, one user can absorb many guests, and rows can be half-null. A funnel "guest → registered" must count DISTINCT guest_id with both keys non-null, and be deduplicated by earliest created_on. **basket_mergedbasket has the same shape [rev3]** (Q30): both keys nullable, indexed but not UNIQUE, never analyzed (10 pages, ≤ about 1.2k rows bound). It needs the same DISTINCT/non-null treatment. There is no FK between the two merge tables, so pairing them requires basket_basket.guest_id/owner_id → mergeduser.guest_id/user_id, with the pair created_on values close together.
- **Personalization coverage / cutover [rev3]:** personalization_detail (94k) is ≈19% of order_orderlinepersonalisedetail (497k) and ≈17% of basket_basketpersonalisedetail (553k), all estimates. Do not define a "personalization rate" on personalization_detail without a coverage note and a time cutover (its first created_on). Until then the governed metric should sit on the order-line table.
- **Write-once guest rows [rev3]:** users_guestuser is 100% all-visible, so `last_accessed` is probably not maintained. Caveat any guest-recency metric.
- **Missing actor links [rev3]:** 16 of the 32 non-empty in-scope tables have no created_by_id (see Relations). Guest identity, reviews and the Cognito log cannot be attributed through a common actor column.
- **Join cost [rev3]:** users_guestuser.db_session_id is not indexed, so guest↔django_session joins seq-scan the guest heap (43 MB). This is acceptable at the current size, but it should be run guest-side and filtered first.
- **Duplicated concepts:**
  - Two offer systems (offer_plusoffer vs offer_productoffer) plus the unused Oscar conditionaloffer and voucher engines.
  - "Brand" is modeled as catalogue_product.
  - Brand recommendations use a text `product` column (analytics_recommendedbrand) instead of an FK.
  - Language lives in both users_userprofile.language_code and language_id.
  - Guest and registered users are separate identity tables.
- **Profile vs user gap:** 991,558 users vs 978,022 profiles (estimates) means about 13.5k users may have no profile or Cognito link. Verify with an exact anti-join once granted.
- **Bloat:** offer_plusoffer uses about 9.8 KB heap/row (at least 4x its live inline data), most plausibly from Kafka config-sync rewrites (≈534 messages/offer of ≈7.6 KB each; the log's 1.53 GB TOAST has no visible retention) [rev3, rev4]. users_userprofile index size (343 MB) is more than twice its heap (158 MB). The blacklist and cognito-log sizes are ambiguous between stale stats and post-delete sparsity (see above).
- **No timestamp or status indexes** on the log tables (cognito sync, kafka log) or on the user tables. This affects the cost of future governed metrics.
- reviews_googlereview has no surrogate id; a uuid is the PK.
- The DB redaction layer masks date-looking strings as `<phone>` in output, even in harmless catalog timestamps (Q8). Use epoch or interval arithmetic instead (Q21 worked).

## Open Questions

1. Can SELECT be granted to `<emapi_login_role>` using the grant list above (table- and column-level)? Every distribution, trend and rate in this unit is blocked on that.
2. Where are referrals stored? **Nothing referral/invite/UTM/affiliate-related exists anywhere in ygag_ecom_orders_db** (DB-wide, Q30) [rev3]. Check the analytics stack or the marketing/campaigns DB. Are the payment point programs (payment_paymentmethod.is_point_program*, youpayclient earned/redeemed points) in scope for "incentives"?
3. What are the choice values for blacklist type/source, cognito sync status, kafka log status, tip status and invoice state (from the Django code)?
4. Is catalogue_product (about 3.2k–3.4k rows) the canonical brand master, or is it a copy of a brand DB (via upc or reference_name)?
5. Does order_line.offer_code record both plus-offer and product-offer codes? Does basket_line carry an equivalent (no offer/discount column was found there)?
6. What does reviews_googlereview.user_reference point to?
7. Should behavior events (views, searches) be sourced from an analytics stack (GA/Firebase/Mixpanel), given that the Oscar analytics tables are empty?
8. What is the true row count of users_blacklisteduserdetail and users_cognitouserdatasynclog? Is there a retention/prune job that explains the sparse pages?
9. For guest flows, which system user id appears in created_by_id on personalization_detail / order_line? It has to be excluded from per-user rates.
10. [rev3] Is users_userprofile.created_by_id the customer or the Cognito-sync/system user (first query 10)?
11. [rev3] reviews_googlereview: is reviewed_date the prompt/redirect time or the actual review time? Are rows created at prompt time (first query 11)?
12. [rev3] When did personalization_detail start receiving rows, and which flows write to it versus order_orderlinepersonalisedetail?
13. [rev3] What drives the ≈534 Kafka messages per plus offer: full-config re-publishes on every edit, periodic re-syncs, or budget updates?
14. [rev3] When were core_siteconfig.is_guest_enabled / order_giftactivationconfig.is_guest_enabled / is_instant_activation_enabled last flipped? They are needed to annotate funnel trends.
15. [rev3] Is users_guestuser.last_accessed ever updated after insert?
16. [rev4] **Which role or job runs a daily full extract of users_customuser, users_userprofile, order_line, order_orderlinequantitydetail and payment_paymentdetail on the replica** (36 seq scans each in 35.5 days, Q40)? If it is an existing governed warehouse/ETL feed, the atlas may be able to reuse it instead of requesting new grants on the replica. Who owns it, where does it land, and which columns does it carry?
17. [rev4] What sets payment_paymentdetail.is_fraud vs is_flagged (and the youpayclient equivalents): the gateway's risk engine, the legacy fraud sync (kafka_legacyfraudsynclog), or staff review? Do flagged payments feed users_blacklisteduserdetail?
18. [rev4] What are the platform value sets on basket_basket, order_order, users_guestuser, user_tip_tip, reviews_googlereview and youpayclient, and do they map to one conformed list?
19. [rev5] What are basket_basket's status values, and does every basket with status 'Merged' / date_merged set have a basket_mergedbasket row (first query 18)?
20. [rev5] Reader capacity: what are the shared reader's CPU, ReadIOPS and buffer-cache hit ratio at peak? Should the atlas get a dedicated Aurora reader (or clone) instead of sharing the one reader that serves 40 databases and production reads?

## Appendix: SQL provenance

Every query ran via `atlasq.sh ygag_ecom_orders_db`.

**Q1 — tables, reltuples, total size** (estimate rows, exact bytes)
```sql
SELECT c.relname, c.reltuples::bigint est, pg_total_relation_size(c.oid) bytes
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname='public' AND c.relkind='r' AND (c.relname ~ '^(users_|user_|customer_|personalization_|offer_|catalogue_|reviews_|partner_|analytics_|communication_|notifications_|wishlists_)')
ORDER BY 1;
```
Result: 71 tables. information_schema.columns returned 0 rows because of privileges.

**Q2 — columns** (pg_attribute; exact)
```sql
SELECT c.relname t, a.attname col, format_type(a.atttypid,a.atttypmod) ty, a.attnotnull nn
FROM pg_class c JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped
WHERE c.relnamespace='public'::regnamespace AND c.relname IN (...core tables...) ORDER BY c.relname, a.attnum;
```

**Q3 — first data query (failed)**
```sql
SELECT 'offer_productoffer' t, count(*) FROM offer_productoffer UNION ALL ... ;
-- InsufficientPrivilegeError: permission denied for table offer_productoffer
```

**Q4 — privileges** (exact: 0 of 71 in scope)
```sql
SELECT c.relname, has_table_privilege(c.oid,'SELECT') sel FROM pg_class c
WHERE c.relnamespace='public'::regnamespace AND c.relkind='r' AND c.relname ~ '^(users_|...|wishlists_)' ORDER BY 2,1;
```

**Q5 — what is selectable at all** (exact: 2 relations; column grants only on pg_stat_statements*)
```sql
SELECT current_user, (SELECT count(*) FROM pg_class c WHERE c.relkind IN ('r','v','m') AND has_table_privilege(c.oid,'SELECT')
  AND c.relnamespace NOT IN ('pg_catalog'::regnamespace,'information_schema'::regnamespace)) selectable, ...;
SELECT table_name, count(*), string_agg(DISTINCT privilege_type, ',') FROM information_schema.column_privileges WHERE table_schema='public' GROUP BY 1;
```

**Q6 — FK / unique constraints** (exact)
```sql
SELECT conrelid::regclass::text tbl, contype, pg_get_constraintdef(oid) def
FROM pg_constraint WHERE connamespace='public'::regnamespace AND contype IN ('f','u')
AND conrelid::regclass::text ~ '^(users_|...|wishlists_)' ORDER BY 1;
```

**Q7 — CHECK constraints** (exact: 34, all `>= 0` counters; none encode enums)
```sql
SELECT conrelid::regclass::text tbl, pg_get_constraintdef(oid) FROM pg_constraint
WHERE connamespace='public'::regnamespace AND contype='c' AND conrelid::regclass::text ~ '^(users_|...)' ORDER BY 1;
```

**Q8 — replica status** (replica=true. `pg_last_xact_replay_timestamp()` is unsupported on Aurora; **[rev5] lag is instead measured with `aurora_replica_status()`, Q43**. Dates in the output were masked by the redactor.)
```sql
SELECT datname, stats_reset, pg_is_in_recovery() replica, now()::date, pg_postmaster_start_time()
FROM pg_stat_database WHERE datname=current_database();
```

**Q9 — table activity counters** (exact, replica-local. n_tup_* = 0 on the replica. seq_scan and idx_scan are the numbers quoted in Behavior Signals.)
```sql
SELECT relname, n_live_tup, n_dead_tup, n_tup_ins, n_tup_upd, n_tup_del, seq_scan, idx_scan, last_analyze...
FROM pg_stat_user_tables WHERE schemaname='public' AND relname ~ '^(users_|...)' ORDER BY n_live_tup DESC;
```

**Q10 — index usage and definitions** (exact. **[rev3] Superseded for scan attribution by Q33.** The `_like$` exclusion below hid catalogue_product_upc_91f72b90_like, the largest index by scans.)
```sql
SELECT i.relname, i.indexrelname, i.idx_scan, pg_get_indexdef(i.indexrelid)
FROM pg_stat_user_indexes i WHERE i.schemaname='public' AND i.relname ~ '^(users_|...)' AND i.indexrelname !~ '_like$'
ORDER BY i.relname, i.idx_scan DESC;
```

**Q11 — pg_stat_statements visibility** (exact: 4,809 statements, 4,793 with hidden text, 3 roles. No visible statements touch scope tables.)
```sql
SELECT count(*), sum(calls), count(*) FILTER (WHERE query IS NULL OR query LIKE '<insufficient%'), count(DISTINCT userid) FROM pg_stat_statements;
```

**Q12 — inbound FKs from out-of-scope tables** (exact). Superseded by Q18, which adds sizes.

**Q13 — candidate cross-DB key columns** (exact)
```sql
SELECT c.relname, a.attname, format_type(a.atttypid,a.atttypmod) FROM pg_class c JOIN pg_attribute a ON ...
WHERE ... AND (a.attname ~ '(reference|cognito|_ref|uuid|gencode|upc|sku|code$|ref_code|session)' OR a.atttypid='uuid'::regtype);
```

**Q14 — heap / index / toast sizes** (exact bytes, estimate rows; includes out-of-scope order_order 1,232,173, basket_basket 3,041,571, order_line 1,473,029)
```sql
SELECT c.relname, c.reltuples::bigint, c.relpages, pg_relation_size(c.oid), pg_indexes_size(c.oid),
 coalesce(pg_total_relation_size(nullif(c.reltoastrelid,0)),0), (SELECT count(*) FROM pg_index i WHERE i.indrelid=c.oid)
FROM pg_class c WHERE c.relnamespace='public'::regnamespace AND c.relname IN (...) ORDER BY 3 DESC;
```

**Q15 — empty / never-analyzed tables** (exact pages)
```sql
SELECT c.relname, c.reltuples::bigint, c.relpages, pg_relation_size(c.oid) FROM pg_class c
WHERE c.relnamespace='public'::regnamespace AND c.relkind='r' AND c.relname ~ '^(users_|...)' AND c.reltuples<=0 ORDER BY 4 DESC;
```

**Q16 — sequences / pg_stats** (last_value NULL, has_sequence_privilege false. pg_stats returned 0 rows for public.)
```sql
SELECT sequencename, last_value, has_sequence_privilege(schemaname||'.'||sequencename,'SELECT') FROM pg_sequences WHERE schemaname='public' AND ...;
SELECT count(*) FROM pg_stats WHERE schemaname='public';
```

**Q17 [rev2] — privilege re-check** (exact: sel=0, tot=71)
```sql
SELECT count(*) FILTER (WHERE has_table_privilege(c.oid,'SELECT')) sel, count(*) tot
FROM pg_class c WHERE c.relnamespace='public'::regnamespace AND c.relkind='r'
AND c.relname ~ '^(users_|user_|customer_|personalization_|offer_|catalogue_|reviews_|partner_|analytics_|communication_|notifications_|wishlists_)';
```

**Q18 [rev2] — inbound FKs with source sizes** ([rev4] re-run as Q37; the Relations table now comes from Q37) (exact FK defs, estimate rows, exact pages; 65 rows. Populated sources: order_order, basket_basket, order_line, basket_line, *personalisedetail, payment_*, django_admin_log, otp_*; zero-page sources: address_useraddress, jet_bookmark, jet_pinnedapplication, order_ordernote, payment_bankcard, two_factor_phonedevice, voucher_voucherapplication, core_unsupportedcountry)
```sql
SELECT conrelid::regclass::text src, (SELECT string_agg(attname,',') FROM pg_attribute WHERE attrelid=conrelid AND attnum=ANY(conkey)) col,
 confrelid::regclass::text tgt, c.reltuples::bigint est, c.relpages pages
FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid
WHERE k.connamespace='public'::regnamespace AND k.contype='f'
AND confrelid::regclass::text IN ('users_customuser','users_guestuser','catalogue_product','catalogue_store','partner_partner')
AND conrelid::regclass::text !~ '^(users_|user_|customer_|personalization_|offer_|catalogue_|reviews_|partner_|analytics_|communication_|notifications_|wishlists_)'
ORDER BY pages DESC, 1;
```
The related sizes query (voucher_*, kafka_*, django_session, two_factor, otp_*):
```sql
SELECT c.relname, c.reltuples::bigint est, c.relpages FROM pg_class c
WHERE c.relnamespace='public'::regnamespace AND c.relkind='r' AND c.relname ~ '^(voucher_|basket_basket_vouchers|kafka_|django_session|two_factor|otp_)' ORDER BY 1;
-- two_factor_phonedevice 0/0, otp_totp_totpdevice 28, otp_static_staticdevice 1, voucher_* all 0/0,
-- django_session 284,567, kafka_blacklistusergiftlog 7,354, kafka_blacklistuserkafkadatalog 2,317, kafka_legacyfraudsynclog 16,691,
-- kafka_plusofferkafkadatalog 201,682, kafka_productofferkafkadatalog 767
```

**Q19 [rev2] — table vs PK-index reltuples, heap/toast bytes** (estimates + exact pages/bytes)
```sql
SELECT t.relname tbl, t.reltuples::bigint tbl_est, t.relpages tbl_pages, i.relname idx, i.reltuples::bigint idx_est, i.relpages idx_pages,
 pg_relation_size(t.oid) heap_b, coalesce(pg_total_relation_size(nullif(t.reltoastrelid,0)),0) toast_b
FROM pg_class t JOIN pg_index x ON x.indrelid=t.oid AND x.indisprimary JOIN pg_class i ON i.oid=x.indexrelid
WHERE t.relnamespace='public'::regnamespace AND t.relkind='r' AND t.relpages>0
AND t.relname ~ '^(users_|user_|...|wishlists_|kafka_|django_session$|order_order$|basket_basket$|order_line$)'
ORDER BY t.relpages DESC;
-- users_guestuser 82,502 / pkey 88,689 (476 pages); users_blacklisteduserdetail 48,646 / pkey 1,560 pages, toast 0;
-- users_cognitouserdatasynclog 93,871 / pkey 1,231 pages; users_customuser 991,558 / pkey 2,775 pages;
-- offer_plusoffer 378 rows, 453 pages, heap 3,710,976 B, toast 1,835,008 B; catalogue_product 3,442 / pkey 3,168
```
Expected packed btree size uses about 360 bigint entries per leaf page (8 KB page, 20 B per entry, 90% fill).

**Q20 [rev2] — page density, visibility map and max bounded row width** (exact pages; width = sum of fixed attlen + varchar typmod−4; unbounded = text/jsonb count)
```sql
SELECT c.relname, c.relpages, c.relallvisible, round((c.reltuples/nullif(c.relpages,0))::numeric,2) rows_per_page,
 (SELECT sum(CASE WHEN a.attlen>0 THEN a.attlen WHEN a.atttypmod>4 THEN a.atttypmod-4 ELSE 0 END) FROM pg_attribute a WHERE a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped) max_bounded_width_b,
 (SELECT count(*) FROM pg_attribute a WHERE a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped AND a.attlen<0 AND a.atttypmod<=4) unbounded_cols
FROM pg_class c WHERE c.relnamespace='public'::regnamespace AND c.relname IN ('users_blacklisteduserdetail','users_cognitouserdatasynclog','users_guestuser','users_customuser','users_userprofile','offer_plusoffer','personalization_detail','django_session','users_mergeduser','user_tip_tip','user_tip_invoice','offer_productoffer','offer_productoffer_happy_cards')
ORDER BY 2 DESC;
-- blacklist 20,078 pages / 19,822 all-visible / 2.42 rows/page / 498 B max / 0 unbounded
-- cognito log 12,171 / 4,076 / 7.71 / 34 B + 2 jsonb; customuser 13,798 / 50 / 71.86; userprofile 19,162 / 13,146
-- offer_plusoffer 453 / 426 / 0.83; users_mergeduser 33 / 33 / max 40 B
```

**Q21 [rev2] — replica uptime / stats window** (exact: 35.5 days both; catalogue_product idx 29,065,730; catalogue_store seq 2,081,665; blacklist/denomination/promo/personalization/guest seq 0)
```sql
SELECT round((extract(epoch FROM now()-pg_postmaster_start_time())/86400)::numeric,1) replica_uptime_days,
 round((extract(epoch FROM now()-coalesce(stats_reset,pg_postmaster_start_time()))/86400)::numeric,1) stats_age_days, ...
FROM pg_stat_database WHERE datname=current_database();
```

**Q22 [rev2] — per-index idx_scan on checkout-path tables** (exact: every index 0, except users_userprofile_user_id_key 72)
```sql
SELECT i.relname, i.indexrelname, i.idx_scan FROM pg_stat_user_indexes i
WHERE i.schemaname='public' AND i.indexrelname !~ '_like$' AND i.relname IN ('personalization_detail','users_blacklisteduserdetail','users_guestuser','catalogue_productdenomination','catalogue_producthandlingfee','offer_offerpromocode','user_tip_tip','reviews_googlereview','users_userprofile','users_mergeduser','catalogue_productdenominationrange','personalization_update_kafka_data_log','users_cognitouserdatasynclog','offer_productoffer','user_tip_invoice')
ORDER BY 1, 3 DESC;
```

**Q23 [rev2] — table seq/idx scans incl. out-of-scope** (exact: basket_basket 0/0, django_session 0/0, kafka_blacklist*/legacyfraud 0/0, order_order 2,178/452,722, order_line 36/738,430, users_customuser 36/144, producthandlingfee 1/0)
```sql
SELECT relname, seq_scan, coalesce(idx_scan,0) idx_scan FROM pg_stat_user_tables WHERE schemaname='public' AND relname IN
('catalogue_producthandlingfee','catalogue_productdenominationrange','user_tip_tip','user_tip_invoice','reviews_googlereview','users_userprofile','users_customuser','users_mergeduser','users_cognitouserdatasynclog','personalization_update_kafka_data_log','offer_productoffer','kafka_blacklistusergiftlog','kafka_blacklistuserkafkadatalog','kafka_legacyfraudsynclog','django_session','order_line','order_order','basket_basket')
ORDER BY 1;
```

**Q23b [rev2] — users_mergeduser constraints** (exact: PK only + 2 non-unique indexes; guest_id, user_id nullable)
```sql
SELECT 'con' k, contype::text a, pg_get_constraintdef(oid) b FROM pg_constraint WHERE conrelid='users_mergeduser'::regclass
UNION ALL SELECT 'idx', indisunique::text, pg_get_indexdef(indexrelid) FROM pg_index WHERE indrelid='users_mergeduser'::regclass
UNION ALL SELECT 'col', a.attnotnull::text, a.attname||' '||format_type(a.atttypid,a.atttypmod) FROM pg_attribute a WHERE attrelid='users_mergeduser'::regclass AND attnum>0 AND NOT attisdropped;
```

**Q24 [rev2] — offer_plusoffer full column list** (exact: 59 columns)
```sql
SELECT a.attnum, a.attname, format_type(a.atttypid,a.atttypmod) ty, a.attnotnull nn FROM pg_attribute a
WHERE attrelid='offer_plusoffer'::regclass AND attnum>0 AND NOT attisdropped ORDER BY 1;
```

**Q25 [rev2] — created_by_id / sender_id / user_id semantics** (exact: created_by_id NOT NULL + FK + indexed on personalization_detail, users_userprofile, user_tip_tip, users_blacklisteduserdetail, offer_plusoffer, catalogue_product. **[rev3]** This checked only a named subset. The rev2 generalization to "every table" was wrong; see Q28.)
```sql
SELECT c.relname, a.attname, format_type(a.atttypid,a.atttypmod) ty, a.attnotnull nn,
 EXISTS (SELECT 1 FROM pg_constraint k WHERE k.conrelid=c.oid AND k.contype='f' AND a.attnum=ANY(k.conkey)) is_fk,
 EXISTS (SELECT 1 FROM pg_index x WHERE x.indrelid=c.oid AND x.indkey[0]=a.attnum) is_idx_lead
FROM pg_class c JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped
WHERE c.relnamespace='public'::regnamespace AND c.relkind='r' AND a.attname IN ('created_by_id','modified_by_id','sender_id','user_id')
AND c.relname IN ('personalization_detail','users_userprofile','user_tip_tip',...) ORDER BY 1,2;
```

**Q26 [rev2] — redemption / discount columns and tables** (exact: order_line.is_offer_applied (indexed), offer_code vc(10), line_price_before_discounts_*; order_orderdiscount / order_orderlinediscount / voucher_* 0 pages)
```sql
SELECT c.relname, a.attname, format_type(a.atttypid,a.atttypmod) ty FROM pg_class c JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped
WHERE c.relnamespace='public'::regnamespace AND c.relname IN ('order_order','order_line','basket_basket','basket_line','order_orderdiscount','payment_paymentdetail')
AND a.attname ~ '(offer|discount|promo|voucher|coupon|campaign|plus|sponsor|incentive)' ORDER BY 1,2;
SELECT c.relname, c.reltuples::bigint, c.relpages FROM pg_class c WHERE c.relnamespace='public'::regnamespace AND c.relkind='r'
AND c.relname ~ '(discount|offer|promo|voucher|coupon|referr|invite)' AND c.relname !~ '^offer_' ORDER BY 1;
SELECT pg_get_indexdef(indexrelid) FROM pg_index WHERE indrelid='order_line'::regclass AND pg_get_indexdef(indexrelid) ~ '(offer|product_id|partner)';
```

**Q27 [rev2] — dead catalogue tables, kafka/session/guest columns** (exact: 10 catalogue_* with 0 pages; django_session = session_key vc(40), session_data text, expire_date; no FK from users_guestuser to django_session)
```sql
SELECT c.relname FROM pg_class c WHERE c.relnamespace='public'::regnamespace AND c.relkind='r' AND c.relname ~ '^catalogue_' AND c.relpages=0 ORDER BY 1;
SELECT c.relname, string_agg(a.attname||':'||format_type(a.atttypid,a.atttypmod), ', ' ORDER BY a.attnum) FROM pg_class c JOIN pg_attribute a ON ...
WHERE c.relname IN ('kafka_blacklistusergiftlog','kafka_blacklistuserkafkadatalog','kafka_legacyfraudsynclog','django_session',...) GROUP BY 1;
SELECT conrelid::regclass::text, pg_get_constraintdef(oid) FROM pg_constraint WHERE contype='f' AND (conrelid IN ('users_guestuser'::regclass,'users_blacklisteduserdetail'::regclass) OR confrelid='django_session'::regclass);
```

**Q28 [rev3] — created_by_id / modified_by_id presence on every non-empty in-scope table** (exact: 32 tables with relpages>0; 16 have both, 16 have neither)
```sql
SELECT c.relname, c.relpages, c.reltuples::bigint est,
 EXISTS (SELECT 1 FROM pg_attribute a WHERE a.attrelid=c.oid AND a.attname='created_by_id' AND NOT a.attisdropped) has_cb,
 EXISTS (SELECT 1 FROM pg_attribute a WHERE a.attrelid=c.oid AND a.attname='modified_by_id' AND NOT a.attisdropped) has_mb
FROM pg_class c WHERE c.relnamespace='public'::regnamespace AND c.relkind='r' AND c.relpages>0
AND c.relname ~ '^(users_|user_|customer_|personalization_|offer_|catalogue_|reviews_|partner_|analytics_|communication_|notifications_|wishlists_)'
ORDER BY 4,1;
-- also: analytics_recommendedbrand reltuples = 85 (estimate)
```

**Q29 [rev3] — visibility map (relallvisible / relpages)** (exact page counts as of the primary's last vacuum; the rows in the Time Coverage table)
```sql
SELECT c.relname, c.reltuples::bigint est, c.relpages, c.relallvisible,
 round(100.0*c.relallvisible/nullif(c.relpages,0),1) pct_allvis, pg_relation_size(c.oid) heap_b
FROM pg_class c WHERE c.relnamespace='public'::regnamespace AND c.relkind='r'
AND c.relname IN ('users_guestuser','personalization_detail','reviews_googlereview','catalogue_productdenominationrange','offer_offerpromocode',
 'catalogue_producthandlingfee','users_customuser','users_userprofile','users_blacklisteduserdetail','users_cognitouserdatasynclog','offer_plusoffer',
 'personalization_update_kafka_data_log','basket_mergedbasket','users_mergeduser','catalogue_product','catalogue_productdenomination','user_tip_tip',
 'user_tip_invoice','offer_productoffer','kafka_plusofferkafkadatalog','order_orderlinepersonalisedetail','basket_basketpersonalisedetail',
 'partner_partner','offer_plusoffer_happy_cards')
ORDER BY 5;
-- guestuser 5300/5300 100%; personalization_detail 21699/21798 99.5%; googlereview 278/935 29.7%; denominationrange 34/200 17%;
-- offerpromocode 0/2 0%; handlingfee 9/18 50%; customuser 50/13798 0.4%; cognito log 4076/12171 33.5%; basket_mergedbasket 10/10 (reltuples -1)
-- ratio inputs (estimates): personalization_update_kafka_data_log 139,132; personalization_detail 94,394; order_orderlinepersonalisedetail 496,737;
-- basket_basketpersonalisedetail 553,383; kafka_plusofferkafkadatalog 201,682; offer_plusoffer 378
-- => 1.47 msgs/personalization; 19.0% / 17.1% coverage; 533.6 msgs/offer
-- [rev4] kafka log figures superseded by Q38 (128,996 / PK 140,520; 29,002/29,005 all-visible)
```

**Q30 [rev3] — guest/mergedbasket indexes + DB-wide referral search** (exact: guestuser indexes = pkey, session_id_key, session_id_like; **no db_session_id index**; basket_mergedbasket = pkey + non-unique idx on guest_basket_id, user_basket_id + 2 FKs to basket_basket; referral tables 0, referral columns 0)
```sql
SELECT indrelid::regclass::text tbl, pg_get_indexdef(indexrelid) def FROM pg_index
WHERE indrelid IN ('users_guestuser'::regclass,'basket_mergedbasket'::regclass)
UNION ALL SELECT conrelid::regclass::text, contype::text || ': ' || pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid='basket_mergedbasket'::regclass
UNION ALL SELECT 'tables_named_referral', count(*)::text FROM pg_class WHERE relnamespace='public'::regnamespace AND relkind='r' AND relname ~* '(referr|invite|utm|affiliate)'
UNION ALL SELECT 'cols_named_referral', count(*)::text FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
  WHERE c.relnamespace='public'::regnamespace AND c.relkind='r' AND a.attnum>0 AND NOT a.attisdropped AND a.attname ~* '(referr|invite|utm|affiliate)'
ORDER BY 1;
```

**Q31 [rev3] — DB-wide incentive / guest-toggle columns** (exact column list; row counts are reltuples estimates: payment_paymentdetail 761,949; youpayclient_youpayclienttransactiondata 1,229,851; payment_paymentmethod 20; core_siteconfig 1; order_giftactivationconfig 1)
```sql
SELECT c.relname, c.reltuples::bigint est, a.attname, format_type(a.atttypid,a.atttypmod) ty
FROM pg_class c JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped
WHERE c.relnamespace='public'::regnamespace AND c.relkind='r'
AND a.attname ~* '(referr|invite|utm|affiliate|point|loyal|guest_enabled|instant_activation)'
ORDER BY 1,3;
```

**Q32 [rev3] — sizes and replica scans of related out-of-scope tables** (exact counters: basket_mergedbasket 10 pages, 0 seq / 0 idx; core_siteconfig, order_giftactivationconfig 0/0; payment_paymentmethod 31,953 seq; analytics_recommendedbrand 6,028 seq)
```sql
SELECT c.relname, c.reltuples::bigint est, c.relpages, (SELECT count(*) FROM pg_index x WHERE x.indrelid=c.oid) n_idx, s.seq_scan, coalesce(s.idx_scan,0) idx_scan
FROM pg_class c LEFT JOIN pg_stat_user_tables s ON s.relid=c.oid
WHERE c.relnamespace='public'::regnamespace AND c.relname IN ('basket_mergedbasket','core_siteconfig','order_giftactivationconfig','payment_paymentmethod',
 'payment_paymentdetail','youpayclient_youpayclienttransactiondata','analytics_recommendedbrand','users_mergeduser') ORDER BY 1;
```

**Q33 [rev3] — per-index scans on hot catalog tables, `_like` indexes included** (exact, replica-local: catalogue_product upc_like 13,449,875 / pkey 10,524,655 / retailer_id 3,526,874 / store_id 1,564,800 / upc_key 0 / slug 0; partner_partner pkey 16,944,848; offer_plusoffer pkey 6,121,924 / brand_id 3,714,556 / (start_date,end_date) 3,402,931 / code 0; happy_cards plusoffer_id 1,823,015 / product_id 898,876 / pair 558,441)
```sql
SELECT i.relname, i.indexrelname, i.idx_scan FROM pg_stat_user_indexes i
WHERE i.schemaname='public' AND i.relname IN ('catalogue_product','partner_partner','offer_plusoffer','offer_plusoffer_happy_cards','catalogue_store')
ORDER BY 1, 3 DESC;
```

**Q34 [rev3] — replica write counters** (exact: n_tup_ins/upd/hot_upd/del and n_dead_tup all 0 for offer_plusoffer, kafka_plusofferkafkadatalog, reviews_googlereview, users_guestuser. Writes happen on the primary and are not counted on the replica.)
```sql
SELECT relname, n_tup_ins, n_tup_upd, n_tup_hot_upd, n_tup_del, n_dead_tup FROM pg_stat_user_tables
WHERE schemaname='public' AND relname IN ('offer_plusoffer','kafka_plusofferkafkadatalog','reviews_googlereview','users_guestuser');
```

**Q35 [rev3] — column inventories: cognito log, mergedbasket, tip, googlereview, guestuser, blacklist typmods** (exact: cognito log has modified_on tstz NOT NULL and status nullable; user_tip_tip.send_tip_gift_event_triggered bool NOT NULL; reviews_googlereview.reviewed_date NOT NULL plus created_on/modified_on; blacklist varchar lengths 25+256+25+150 = 456 chars)
```sql
SELECT c.relname, a.attnum, a.attname, format_type(a.atttypid,a.atttypmod) ty, a.attnotnull nn
FROM pg_class c JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped
WHERE c.relnamespace='public'::regnamespace AND c.relname IN ('users_cognitouserdatasynclog','basket_mergedbasket','user_tip_tip','reviews_googlereview','users_guestuser')
ORDER BY 1,2;
-- run separately for the blacklist typmods:
SELECT c.relname, a.attname, format_type(a.atttypid,a.atttypmod) ty, a.atttypmod FROM pg_class c JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped
WHERE c.relname='users_blacklisteduserdetail' ORDER BY a.attnum;
```

**Q36 [rev3] — users_userprofile FKs to users_customuser** (exact: 3 FKs, on user_id, created_by_id and modified_by_id)
```sql
SELECT conrelid::regclass::text, pg_get_constraintdef(oid) FROM pg_constraint
WHERE contype='f' AND confrelid='users_customuser'::regclass AND conrelid='users_userprofile'::regclass;
```

**Q37 [rev4] — inbound FKs with source sizes, fresh run** (exact FK defs, estimate rows, exact pages; 65 FK rows; replaces the rev2 Q18 summary in Relations. Same SQL as Q18.)
```sql
SELECT conrelid::regclass::text src, (SELECT string_agg(attname,',') FROM pg_attribute WHERE attrelid=conrelid AND attnum=ANY(conkey)) col,
 confrelid::regclass::text tgt, c.reltuples::bigint est, c.relpages pages
FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid
WHERE k.connamespace='public'::regnamespace AND k.contype='f'
AND confrelid::regclass::text IN ('users_customuser','users_guestuser','catalogue_product','catalogue_store','partner_partner')
AND conrelid::regclass::text !~ '^(users_|user_|customer_|personalization_|offer_|catalogue_|reviews_|partner_|analytics_|communication_|notifications_|wishlists_)'
ORDER BY pages DESC, 1, 2;
-- order_order 1,232,173 / 176,977 pages (user_id, guest_id, region_id, created_by_id, modified_by_id); basket_basket 3,041,571 / 162,789;
-- order_line 1,473,029 / 51,146; order_orderlinequantitydetail 1,474,250 / 48,292; basket_basketquantitydetail 1,783,453 / 37,861;
-- basket_line 1,789,338 / 32,298; payment_paymentdetail 761,949 / 21,939; payment_paymenttransactionpayload 65,123 / 16,961;
-- basket_basketpersonalisedetail 553,383 / 9,403; order_orderlinepersonalisedetail 496,737 / 8,599; django_admin_log 2,608; core_currencyexchangerate 437;
-- order_orderplacedcountry 187; otp_totp 28; small core_/address_/payment_paymentmethod/webhooks config tables; 8 zero-page sources
```

**Q38 [rev4] — table vs PK-index reltuples, visibility map, heap/toast bytes (refresh)** (estimate rows; exact pages/bytes)
```sql
SELECT t.relname, t.reltuples::bigint est, t.relpages, t.relallvisible, round(100.0*t.relallvisible/nullif(t.relpages,0),2) pct,
 i.relname idx, i.reltuples::bigint idx_est, i.relpages idx_pages,
 pg_relation_size(t.oid) heap_b, coalesce(pg_total_relation_size(nullif(t.reltoastrelid,0)),0) toast_b, pg_total_relation_size(t.oid) total_b
FROM pg_class t JOIN pg_index x ON x.indrelid=t.oid AND x.indisprimary JOIN pg_class i ON i.oid=x.indexrelid
WHERE t.relnamespace='public'::regnamespace AND t.relname IN ('personalization_update_kafka_data_log','personalization_detail','kafka_plusofferkafkadatalog',
 'offer_plusoffer','reviews_googlereview','users_cognitouserdatasynclog','users_blacklisteduserdetail','users_userprofile','users_guestuser',
 'order_orderlinepersonalisedetail','basket_basketpersonalisedetail')
ORDER BY 1;
-- personalization_update_kafka_data_log 128,996 / 29,005 pages / 29,002 all-visible (99.99%) / pkey 140,520 (481 pages) / heap 237,608,960 B / toast 101,105,664 B / total 342,753,280 B
-- kafka_plusofferkafkadatalog 201,682 / heap 18,284,544 B / toast 1,525,874,688 B / total 1,548,787,712 B  => 7,566 B toast per message
-- unchanged vs rev3: personalization_detail 94,394 (99.55%); googlereview 29.73%; cognito log 33.49%; blacklist 98.72%; guestuser 100% (pkey 88,689); userprofile 68.6%
```

**Q39 [rev4] — per-index sizes for created_by_id cardinality** (exact pages; estimate entries. Server PostgreSQL 16.11, so btree deduplication applies.)
```sql
SELECT t.relname tbl, i.relname idx, pg_get_indexdef(i.oid) def, i.reltuples::bigint idx_est, i.relpages idx_pages, t.reltuples::bigint tbl_est
FROM pg_index x JOIN pg_class i ON i.oid=x.indexrelid JOIN pg_class t ON t.oid=x.indrelid
WHERE t.relname IN ('users_userprofile','personalization_detail','users_blacklisteduserdetail','user_tip_tip')
ORDER BY 1, 5 DESC;
SELECT version(), current_setting('server_version_num');   -- 160011
-- users_userprofile: created_by_id 1,790; modified_by_id 1,917; language_id 2,127; user_id_key 3,943; pkey 4,030 (978,022 entries)
-- personalization_detail: created_by_id 136; modified_by_id 132; pkey 395 (94,394 entries)
-- users_blacklisteduserdetail: created_by_id 1,569; modified_by_id 1,650; pkey 1,560; (type,value) 1,807 (48,646 entries)
-- packed minimum = entries / ~360-367 per leaf page: 978,022 -> ~2,665-2,720; 94,394 -> ~257-262; 48,646 -> ~133-135
```

**Q40 [rev4] — seq-scan cadence** (exact, replica-local; stats window 35.53 days)
```sql
SELECT relname, seq_scan, coalesce(idx_scan,0) idx_scan, seq_tup_read, n_live_tup
FROM pg_stat_user_tables WHERE schemaname='public' AND seq_scan BETWEEN 30 AND 45 ORDER BY seq_scan, relname;
SELECT round((extract(epoch FROM now()-pg_postmaster_start_time())/86400)::numeric,2) uptime_days,
 round((extract(epoch FROM now()-coalesce(stats_reset,pg_postmaster_start_time()))/86400)::numeric,2) stats_days
FROM pg_stat_database WHERE datname=current_database();
-- seq_scan=36: order_line (seq_tup_read 52,250,619; idx 745,225), order_orderlinequantitydetail (52,250,619; 72),
-- payment_paymentdetail (27,095,666; 102,248), users_customuser (35,283,827; 144), users_userprofile (35,282,819; 72); offer_plusoffer 33 (12,056 tuples)
-- uptime 35.53 d, stats 35.53 d
```

**Q41 [rev4] — fraud / flag / platform / discount columns DB-wide** (exact column facts; reltuples estimates)
```sql
SELECT c.relname, c.reltuples::bigint est, a.attname, format_type(a.atttypid,a.atttypmod) ty, a.attnotnull nn,
 EXISTS (SELECT 1 FROM pg_index x WHERE x.indrelid=c.oid AND x.indkey[0]=a.attnum) idx_lead
FROM pg_class c JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped
WHERE c.relnamespace='public'::regnamespace AND c.relkind='r'
AND (a.attname ~* '(fraud|flag)' OR a.attname='platform' OR (c.relname='catalogue_product' AND a.attname ~* '(discount|rating)'))
ORDER BY 3,1;
-- is_fraud / is_flagged bool NOT NULL, not indexed: payment_paymentdetail (761,949), youpayclient_youpayclienttransactiondata (1,229,851)
-- platform: basket_basket vc(20)!, order_order vc(20)!, users_guestuser vc(20)!, user_tip_tip vc(15)! (indexed), reviews_googlereview vc(15), youpayclient vc(200)
-- catalogue_product.is_discountable bool NOT NULL; catalogue_product.rating double precision (nullable); neither indexed
```

**Q42 [rev4] — payment_paymentdetail and youpayclient column inventories** (exact; used for the non-PII grant columns)
```sql
SELECT c.relname, a.attnum, a.attname, format_type(a.atttypid,a.atttypmod) ty, a.attnotnull nn
FROM pg_class c JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped
WHERE c.relnamespace='public'::regnamespace AND c.relname IN ('payment_paymentdetail','youpayclient_youpayclienttransactiondata')
ORDER BY 1,2;
-- payment_paymentdetail: 26 columns (id, created_on, modified_on, payment_gateway, currency, is_fraud, is_flagged, card_bin, card_last4, payment_method,
--   payment_scheme, is_gcc_card, processing_fee, card_issuer_country, name_on_card, paid_amount, created_by_id, modified_by_id, order_id, gateway_charge,
--   payment_status, settlement_entity, brand_calculations, exclude_instant_activation, point_collection_enabled, point_program)
-- youpayclient_youpayclienttransactiondata: 64 columns incl. PII customer_email, customer_name, customer_ip_address, name_on_card, session_id,
--   points_collected_mobile_number, points_redeemed_mobile_number
```

**Q43 [rev5] — Aurora topology and replica lag** (exact; instance ids partly masked by the redactor as `<phone>`)
```sql
SELECT server_id, CASE WHEN session_id='MASTER_SESSION_ID' THEN 'writer' ELSE 'reader' END role, replica_lag_in_msec,
 aurora_db_instance_identifier() connected_to, pg_is_in_recovery() in_recovery,
 (SELECT count(*) FROM pg_database) n_databases, (SELECT count(*) FROM pg_database WHERE NOT datistemplate) n_nontemplate
FROM aurora_replica_status();
-- 2 rows: writer ecom-shared-read-optimized-1 (lag NULL); one reader (lag 10 ms) = connected_to; in_recovery true; 42 databases, 40 non-template
-- repeated 3x (role, replica_lag_in_msec, now()-last_update_timestamp): reader lag 22, 26, 8 ms
```

**Q44 [rev5] — grant-list column verification + basket_basket / order_order inventories** (exact)
```sql
WITH g(t, cols) AS (VALUES ('users_customuser','id,date_joined,is_active,is_staff,last_login'), ... one row per grant-list table ...,
 ('basket_basket','id,platform,region_id,owner_id,guest_id,date_created,date_merged,date_submitted,status'),
 ('order_order','id,platform,region_id,user_id,guest_id,created_by_id,date_placed,status')),
x AS (SELECT t, trim(unnest(string_to_array(cols,','))) col FROM g)
SELECT x.t, x.col, EXISTS (SELECT 1 FROM pg_attribute a WHERE a.attrelid=to_regclass('public.'||x.t) AND a.attname=x.col AND a.attnum>0 AND NOT a.attisdropped) ok
FROM x ORDER BY 3,1,2;
-- 152 of 152 true; separately basket_basket.user_id = false, order_order.owner_id = false (created_on absent on both, per inventory below)
SELECT c.relname, a.attnum, a.attname, format_type(a.atttypid,a.atttypmod) ty, a.attnotnull nn FROM pg_class c JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped
WHERE c.relnamespace='public'::regnamespace AND c.relname IN ('basket_basket','order_order') ORDER BY 1,2;
-- basket_basket 20 cols: status vc(128) NOT NULL, date_created tstz NOT NULL, date_merged tstz NULL, date_submitted tstz NULL, owner_id, guest_id, parent_id, platform, record_type, user/user_email/user_name/user_phone/user_gender (PII), note, extra, language_code, language_id
-- order_order 63 cols: date_placed tstz NOT NULL, date_updated, sold_date; no created_on; PII guest_email, user_email, user_name, user_phone, owner, session_id, transaction_id
```

**Q45 [rev5] — basket_basket and users_userprofile index sizes (calibration)** (exact pages, estimate entries)
```sql
SELECT t.relname tbl, i.relname idx, pg_get_indexdef(i.oid) def, i.reltuples::bigint idx_est, i.relpages, s.idx_scan
FROM pg_index x JOIN pg_class i ON i.oid=x.indexrelid JOIN pg_class t ON t.oid=x.indrelid LEFT JOIN pg_stat_user_indexes s ON s.indexrelid=i.oid
WHERE t.relname IN ('basket_basket','users_userprofile') ORDER BY 1, 5 DESC;
-- basket_basket (3,041,571): pkey 17,134; owner_id 8,501; parent_id 8,252; guest_id 5,798; region_id 5,435; language_id 4,817; all idx_scan 0; no index on status/date_*
-- users_userprofile (978,022): cognito_id_key 9,018; pkey 4,030; user_id_key 3,943 (72 scans); language_id 2,127; modified_by_id 1,917; created_by_id 1,790
SELECT a.attrelid::regclass::text, a.attname, a.attnotnull FROM pg_attribute a WHERE a.attrelid IN ('users_userprofile'::regclass,'basket_basket'::regclass)
 AND a.attname IN ('language_id','created_by_id','status','date_merged');   -- language_id nullable on both; core_language reltuples 2 (Q46)
```

**Q46 [rev5] — scan counters refresh + order_orderlinequantitydetail constraints** (exact, replica-local)
```sql
SELECT c.relname, c.reltuples::bigint est, c.relpages, s.seq_scan, s.seq_tup_read, coalesce(s.idx_scan,0) idx_scan
FROM pg_class c LEFT JOIN pg_stat_user_tables s ON s.relid=c.oid WHERE c.relnamespace='public'::regnamespace
AND c.relname IN ('core_language','order_line','order_orderlinequantitydetail','basket_basket','order_order','catalogue_store','catalogue_product','basket_mergedbasket') ORDER BY 1;
-- order_line 36 / 52,250,619 / idx 745,309; order_orderlinequantitydetail 36 / 52,250,619 / idx 72; order_order 2,180 / 2,615,645,228 / idx 454,435 (176,977 pages);
-- catalogue_store seq 2,082,114; catalogue_product idx 29,072,457; basket_basket 0/0; basket_mergedbasket 0/0; core_language est 2
SELECT conrelid::regclass::text, pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid='order_orderlinequantitydetail'::regclass;
-- UNIQUE (line_id); PRIMARY KEY (id); FK line_id -> order_line(id); FK created_by_id, modified_by_id -> users_customuser; FK denomination_currency_id -> core_currency
SELECT i.relname, i.reltuples::bigint, i.relpages FROM pg_index x JOIN pg_class i ON i.oid=x.indexrelid WHERE x.indrelid IN ('order_line'::regclass,'order_orderlinequantitydetail'::regclass);
-- orderlinequantitydetail line_id_key 4,084 pages vs pkey 4,089
```

**Q47 [rev5] — derived figures** (arithmetic on Q39/Q43/Q46 outputs, no new query)
- Posting-list floor for users_userprofile.language_id: 978,022 TIDs × 6 B ≈ 5.87 MB ÷ 8,150–7,300 usable B/page ≈ 720–800 pages (observed 2,127).
- order_order: 2,615,645,228 / 2,180 ≈ 1.20M tuples per seq scan (full table); 2,180 / 35.53 days ≈ 61 per day.
- Replica lag range: 8–26 ms (Q43 samples 10, 22, 26, 8 plus the critic's 24).

