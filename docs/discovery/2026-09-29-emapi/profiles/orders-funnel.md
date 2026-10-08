# Profile: orders-funnel (`ygag_ecom_orders_db`)

Profiled 2026-09-29 (v4, revised after a third critic review) through `atlasq.sh`, which runs on the atlas EC2 box over SSH against an Aurora read replica, read-only, PII-redacted. Every number is labelled **exact** (catalog/counter value read directly), **est.** (`pg_class.reltuples`, from the primary's last ANALYZE) or **extrap.** (reltuples scaled by current heap pages / `relpages`, Q20). The SQL behind every key number is in the appendix.

**Evidence labels (v4).** Insights in §1–§10 carry one of three labels; a catalog fact with no label is STRUCTURAL by default:
- **[STRUCTURAL]**: read from, or inferred from, the catalog (definitions, constraints, indexes, reltuples, relation sizes, replica counters). The catalog fact itself was queried; any business meaning drawn from it is an inference.
- **[NEEDS-GRANT]**: a hypothesis that needs row data this role cannot read. The table/columns and the prepared query are named.
- **[VALIDATED]**: backed by a data query that ran. **No claim in this profile is VALIDATED**, because the role has SELECT on 0 of 1,500 columns in this DB (Q28). Numbers labelled exact/est./extrap. are catalog numbers, i.e. STRUCTURAL.

**v3 staleness rule.** reltuples values come from different ANALYZE runs, so ratios between two raw estimates can be off by several percent. v3 recomputes every cross-table ratio from **extrapolated** counts (Q20). Growth since last ANALYZE (current pages / relpages, exact): `order_orderstatuschange` +4.54%, `order_lineprice` +3.91%, `kafka_giftcreationlog` +3.88%, `order_orderlinepersonalisedetail` +3.35%, `basket_line` +1.95%, `payment_paymentdetail` +1.01%, `basket_basketpersonalisedetail` +0.83%, youpay +0.68%, `order_orderlinequantitydetail` +0.43%, `basket_basket` +0.16%, `order_order` +0.14%, `order_line` and `basket_basketquantitydetail` +0.00%. Caveat: page growth is a lower bound on row growth when vacuum lets new rows reuse free space in existing pages. `order_line` showing 0 growth while `order_lineprice` (written with it) grew 3.9% suggests this is happening, so `order_line` is likely **under**-counted. `last_analyze`/`last_autoanalyze` and `n_live_tup` are NULL/0 on the replica (stats are not replicated), so the ANALYZE date itself cannot be read.

## 0. Blocking access finding (read first)

The connector role `<emapi_login_role>` can read **2 of 161 relations in `public`**, and both are the `pg_stat_statements` / `pg_stat_statements_info` views (Q6, re-run v2, exact). It has **no SELECT on any business table**, and no column-level grants either: `has_column_privilege` is false for **all 1,500 columns** of all ordinary tables in `public` (Q28, re-run v4, exact). Every `SELECT ... FROM order_order` / `order_orderstatuschange` returns `InsufficientPrivilegeError: permission denied` (Q5). The role also cannot see:
- `pg_stats` (0 rows visible, Q12), so there are no column distributions or null fractions;
- `pg_sequences.last_value` (NULL, Q11), so there are no id high-water marks;
- other roles' `pg_stat_statements` query text (4,877 of 4,897 cluster-wide entries are `<insufficient privilege>`, Q10, exact).

**What that means.** This profile is built **only from the catalog**: definitions, constraints, indexes, reltuples, relation sizes, and replica-side counters.
- **No status/enum distributions, time ranges, trends, failure rates or id ranges could be measured.** Sections 4, 5 and 7 are therefore **BLOCKED — needs grant** (see §12), backed by prepared queries (P1–P37). This unit cannot pass until the §12 grant lands. §12.4 states which P-queries run under the column-grant option (B) and which need the view option (A).
- Timestamps in tool output are over-redacted (ISO timestamps come back as `<phone>`). The workaround is `to_char(ts,'YYYY"y"MM"m"DD"d"')` (Q9b).

## 1. Summary

This database holds the transaction side of the YouGotAGift consumer ecommerce app. It is a Django + django-oscar deployment with heavy YGG customisation.
- **The funnel:** `basket_basket` (3,041,571 est. / 3,046,354 extrap.) → `basket_line` (1,789,338 est. / 1,824,296 extrap.) → `order_order` (1,232,173 est. / 1,233,955 extrap.) → `order_line` (1,473,029 est. and extrap., likely under-counted). Payment is recorded in two places:
  - `youpayclient_youpayclienttransactiondata` (1,229,851 est. / 1,238,225 extrap., **100.3% of the order count**). This is the **candidate payment ledger**, but its cardinality per order is **unknown**: it has only a PRIMARY KEY and no UNIQUE on `order_reference` or `transaction_id` (Q21). A row-count ratio says nothing about coverage; it may be one row per payment attempt. **Revenue must not be summed from youpay joined to orders** until P25 runs (§2.3).
  - `payment_paymentdetail` (761,949 est. / 769,659 extrap., about 62.4% of orders, **0..1 per order**).
  - `order_orderstatuschange` (1,157,239 est. / 1,209,722 extrap.) is a state-transition log that is **probably incomplete**: 0.98 rows per order (extrap.), a gap of about 24k rows. That is suggestive, not proof (§7.4); P11/P12 are the only valid test.
- **No acquisition attribution:** there are no referral, UTM, campaign or acquisition-source columns anywhere in this DB (Q22). Attribution must come from another unit (web analytics / ads; §6).
- **No refund tracking:** the only refund-like column (`payment_source.amount_refunded`) is in an empty table, and no refund/cancel/chargeback table exists (Q23). Refunds must live in `ygag_youpay_db` or a finance system, or show up only as `order_order.status` / `order_line.status` values (P26).
- **Gift configuration:** each basket or order line carries a 1:1 "quantity detail" (denomination, currency, delivery method, buy-for-self, brand skin, sender). About 31–34% of lines also carry a "personalise detail" (recipient channel, schedule, greeting, occasion, reminder). The out-of-scope `personalization_detail` (94,394 est.) looks like the vault behind `personal_data_ref`.
- **Money:** orders are multi-currency. There are cart, gateway and reporting currencies, plus processing fee, VAT, extra charges, and "before_payment" snapshots. **The fee rates are stored as varchar** (§10).
- **Unused oscar modules:** vouchers, oscar payment sources/transactions, shipping-method tables, addresses, order discounts/notes/events, and bank cards are **exact-empty**: 30 in-scope tables have a 0-byte heap (`pg_relation_size = 0`, Q29), not merely `reltuples = 0` [STRUCTURAL]. However, `order_order` still carries **NOT NULL `shipping_method` / `shipping_code` / `shipping_incl_tax` / `shipping_excl_tax`**, plus nullable `shipping_tax_code` and indexed `billing_address_id` / `shipping_address_id`. Whether these encode a delivery channel is **unverified** (P13).
- **Offers:** `order_line.offer_code` varchar(10) matches `offer_plusoffer.code` varchar(10) UNIQUE (378 offers est.). This is the campaign dimension (§3, §6).
- **Purchase-friction config** lives mostly outside the prefix scope: `core_currencybasketlimit` (8 est., one cap per currency), `core_unsupportedcountry` (geo-block list), `users_blacklisteduserdetail` (48,646 est., checkout block list), `catalogue_productdenominationrange` (11,376 est., per-product min/max denomination), `catalogue_producthandlingfee` (939 est. / 991 extrap., fee rules) and the `offer_plusoffer` promo-code limits. In-scope config: `order_giftactivationconfig.is_guest_enabled` and `payment_paymentmethod.is_active` (§7.1).

## 2. Entities & Tables

**Scope count (Q15, exact):** `order_` 23, `basket_` 7, `payment_` 8, `voucher_` 4, `shipping_` 5, `address_` 3, for a total of **50 tables**. Of these, 20 are populated and 30 are **exact-empty** (heap 0 bytes, `pg_relation_size = 0` on the replica, Q29) [STRUCTURAL]. The other two tables with `reltuples` ≤ 0 are `basket_mergedbasket` (-1, never analyzed, 81,920 B heap) and `payment_logentrydata` (-1, 49,152 B heap); both hold rows and count as populated. v1 said "order_* 26". That was a miscount: the catalog has exactly the 23 order_ tables the brief lists, so nothing is missing. Sizes come from Q1/Q9 (row counts est.; sizes exact).

### 2.1 Basket (pre-purchase cart)
| Table | Rows (est.) | Size | Purpose / key columns |
|---|---|---|---|
| `basket_basket` | 3,041,571 | 1,665 MB (heap 1,273 MB, about 439 B/row) | Cart header. `status` varchar(128) (oscar: Open/Merged/Saved/Frozen/Submitted), `date_created`, `date_merged`, `date_submitted`, `owner_id`→users_customuser, `guest_id`→users_guestuser, `parent_id` self-FK, `region_id`→catalogue_store, `platform`, `record_type` varchar(10) NOT NULL, `language_code`/`language_id`, `extra` jsonb NOT NULL, `note`. Denormalised PII: `user`, `user_email`, `user_name`, `user_phone`, `user_gender`. **No index on date_created or status.** **0 seq_scan and 0 idx_scan on this replica** (Q16, exact). |
| `basket_line` | 1,789,338 | 1,150 MB | Cart item. `line_reference` (unique per basket), `quantity` (CHECK ≥0), `price_currency`, `price_excl_tax`/`price_incl_tax`, `product_id`→catalogue_product, `stockrecord_id` (partner_stockrecord is empty), `parent_id` self-FK, `record_type` varchar(10) NOT NULL, `tax_code`, `purchase_origin` varchar(20), `is_white_label`, `date_created`/`date_updated` (both indexed). 0/0 scans on replica. |
| `basket_basketquantitydetail` | 1,783,453 | 453 MB | 1:1 with basket_line (UNIQUE line_id). `denomination` + `denomination_currency_id`→core_currency, `delivery_method`, `is_buy_for_self`, `personal_data_ref`, `brand_skin`, `sender_name`. 0/0 scans. |
| `basket_basketpersonalisedetail` | 553,383 | 114 MB | 0..1 per basket_line (UNIQUE line_id). `delivery_type`, `delivery_date`, `delivery_time`, `delivery_time_zone`, `greeting_code`, `occasion_code`, `is_reminder_added`. Recipient PII: `phone_number`, `email_address`. 0/0 scans. |
| `basket_mergedbasket` | never analyzed (-1), 10 pages | ~0 | Guest→user basket merge record (`guest_basket_id`, `user_basket_id`). |
| `basket_basket_vouchers`, `basket_lineattribute` | 0 | – | Unused oscar tables. |

### 2.2 Order (placed purchase)
| Table | Rows (est.) | Size | Purpose / key columns |
|---|---|---|---|
| `order_order` | 1,232,173 | 2,363 MB (heap 1,384 MB = **about 1,178 B/row heap**, about 2,011 B/row with indexes; TOAST 0 MB) | Order header. **Business keys:** `number` (UNIQUE), `order_reference` (UNIQUE), `payment_order_reference` varchar(21), `transaction_id` (indexed), `session_id`. **Dimensions:** `status` (custom index `order_order_status_2f1723_idx`, a hot filter), `date_placed` (indexed), `date_updated`, `sold_date`, `user_id`/`guest_id`/`owner` (indexed), `basket_id`→basket_basket, `region_id`→catalogue_store, `placed_country_id`→order_orderplacedcountry, `platform`, `language_code`, `site_id`, `quantity`. **Money:** `currency`, `gateway_currency`, `total_incl_tax`, `total_excl_tax`, `total_tax_amount`, `total_base_amount`, `total_extra_charge`, `process_fee`, and the `*_in_gateway_currency`, `*_before_payment` and reporting-currency variants, `conversion_rate_*`. **Shipping (oscar legacy, all NOT NULL):** `shipping_method` varchar(128), `shipping_code` varchar(128), `shipping_incl_tax`/`shipping_excl_tax` numeric(12,2); `shipping_tax_code` varchar(64) nullable; `billing_address_id`, `shipping_address_id` (indexed; their target tables are empty). **Flags:** `gift_create_event_triggered`, `is_visited`, `redemption_partner`, `transaction_url`, `extra` jsonb NOT NULL. **Actor:** `created_by_id` (NOT NULL, indexed) and `modified_by_id` (nullable, indexed) → users_customuser. Denormalised PII, each **column is NOT NULL (may be empty string)** (Q24, exact) [STRUCTURAL]: `user_email` varchar(512), `guest_email` varchar(254), `user_name` varchar(256), `user_phone` varchar(256), `owner` varchar(150). NOT NULL does not mean populated: a guest order may store `''` in `user_email`, a registered order `''` in `guest_email`. The share actually populated is measured PII-free through the derived `has_*` flags of the §12.2 view [NEEDS-GRANT]. Nullable PII: `user_gender`, `session_id` varchar(500), `transaction_url` varchar(512). 63 columns in total, 46 NOT NULL. |
| `order_line` | 1,473,029 | 956 MB | Order item. `line_reference` (UNIQUE, varchar 200), `status`, `quantity`, `line_price_*` / `unit_price_*` / `line_price_before_discounts_*`, `partner_id`→partner_partner (brand/merchant), `partner_name`, `partner_sku`, **`partner_line_reference` varchar(128) NOT NULL (not indexed)**, **`partner_line_notes` text NOT NULL**, `upc`, `title`, `product_id`, `is_instant_activated`, `instant_activated_date`, `is_offer_applied` (indexed), `offer_code` varchar(10), `purchase_origin`, `is_white_label`, `tax_code`, `created_on`/`modified_on` (not indexed). |
| `order_orderlinequantitydetail` | 1,474,250 | 484 MB | 1:1 with order_line. The full money breakdown per line in cart, denomination and reporting currency: price, tax, extra charge, `processing_fee_in_*`, `processing_fee_vat_in_*` (numeric), and the `*_before_pay` variants. **`processing_fee_rate` and `processing_fee_vat_rate` are varchar(20)**. Also `conversion_rate*`, `payment_gateway_charge`, `is_different_currency_denomination`, `reporting_currency`, `delivery_method`, `is_buy_for_self`, `brand_skin`, `sender_name`, `personal_data_ref`. |
| `order_orderlinepersonalisedetail` | 496,737 | 105 MB | 0..1 per order_line. Delivery schedule, greeting, occasion and reminder, plus recipient `phone_number`/`email_address`. |
| `order_lineprice` | 1,427,052 | 210 MB | Oscar per-line price rows (`quantity`, `price_*`, `shipping_*`, `tax_code`). FKs to line and order. |
| `order_orderstatuschange` | 1,157,239 (1,209,722 extrap.) | 161 MB | Order state-transition log: `old_status`, `new_status`, `date_created` (indexed), `order_id` (indexed). **Probably incomplete: 0.98 rows per order (extrap.)** (§7.4). |
| `order_orderplacedcountry` | 187 | – | Lookup of placing country (`code` PK varchar(5), `name`). |
| `order_giftactivationconfig` (+`_enabled_country`) | 1 (+6) | – | Singleton config: `is_instant_activation_enabled`, `activation_time`, `delivery_time`, `is_guest_enabled`, and the 6 countries where it is enabled. |
| Exact-empty (heap 0 B, Q29) | – | – | `order_billingaddress`, `order_shippingaddress`, `order_communicationevent`, `order_lineattribute`, `order_orderdiscount`, `order_orderlinediscount`, `order_ordernote`, `order_paymentevent`, `order_paymenteventquantity`, `order_paymenteventtype`, `order_shippingevent`, `order_shippingeventquantity`, `order_shippingeventtype`, `order_surcharge` (14 tables; 9 populated + 14 empty = 23). |

### 2.3 Payment
| Table | Rows (est.) | Size | Purpose / key columns |
|---|---|---|---|
| `payment_paymentdetail` | 761,949 (769,659 extrap.) | 252 MB | **0..1 per order** (UNIQUE order_id; covers about 62.4% of orders, extrap.). **Revenue or payment metrics must not inner-join this table; use LEFT JOIN, or the youpay ledger.** Columns: `payment_gateway`, `payment_method`, `payment_scheme`, `payment_status`, `currency`, `paid_amount`, `processing_fee`, `gateway_charge`, `settlement_entity`, `is_fraud`, `is_flagged`, `is_gcc_card`, `card_issuer_country` (indexed), `card_bin`, `card_last4`, `name_on_card`, `brand_calculations` jsonb, `exclude_instant_activation`, `point_collection_enabled` (indexed), `point_program`. |
| `payment_paymenttransactionpayload` | 65,123 | 150 MB (wide jsonb) | Raw gateway payload log: `order` varchar(128) (a logical key, **with no FK and no index**), `payload` jsonb, `created_on`. |
| `payment_paymentmethod` | 20 | – | Checkout payment-method catalogue: `payment_code` (UNIQUE with `is_active`), `method_name[_en/_ar]`, loyalty flags (`is_point_program`, `_partial_payment`, `_full_redemption`, `_data_push_enabled`, `point_program_code/name`), `is_show_payment_method_only`. 31,931 seq scans on replica (exact), so checkout reads it constantly. |
| `payment_logentrydata` | never analyzed, 4 pages | – | Extends django_admin_log with `old_data`/`modified_data` text (an admin audit trail for payment config). |
| Exact-empty (heap 0 B) | – | – | `payment_bankcard`, `payment_source`, `payment_sourcetype`, `payment_transaction`. |

**Adjacent payment ledger (out of prefix scope, essential):** `youpayclient_youpayclienttransactiondata` (1,229,851 est. / 1,238,225 extrap., 1,987 MB, about 1,454 B/row heap).

> **Cardinality warning (Q21, exact).** The only constraint on this table is `PRIMARY KEY (id)`. Nothing enforces uniqueness on `order_reference`, `transaction_id` or `payment_reference`. Its extrapolated row count is **100.3%** of the extrapolated order count, and it carries `order_history` jsonb (attempt history), so it may hold one row per payment **attempt** rather than one per order. Joining orders→youpay can then fan out and double-count revenue. **Until P25 runs** (sampled `count(*)` vs `count(DISTINCT order_reference)`, plus `approved=true` rows per `order_reference`), the registry must not sum money from a youpay join, and "youpay covers ~99.8% of orders" (v2) is withdrawn. Coverage is unknown.

Its columns:
- **keys:** `transaction_id`, `payment_reference`, `order_reference`, `invoice_id`, `session_id`;
- **money:** `amount`, `base_amount`, `vat_amount`, `service_fee`, `paid_amount`, `payable_amount`, `processing_fee`, `gateway_charge`, and `cart_*` in `cart_currency`;
- **outcome:** `approved` bool NOT NULL, `response_summary` varchar(500) (decline reason), `payment_status`, `payment_gateway`, `payment_method`, `payment_scheme`, `channel_code`, `platform`, `is_fraud`, `is_flagged`, `is_gcc_card`, `card_issuer_country` (indexed);
- **loyalty/points:** `is_full_redemption` (indexed), `redeemed_points`, `redeemed_amount`, `available_points`, `available_amount`, `earned_point`, `loyalty_level`, `point_program`, `point_collection_enabled` (indexed), `is_qitaf_enabled` (indexed), `qitaf_request_id` (indexed);
- **history:** `order_history` jsonb (attempt/retry history), `order_items` jsonb, `brand_calculations`/`brand_details` jsonb, `udf1` jsonb.

**Indexes exist only on pkey, card_issuer_country, is_full_redemption, is_qitaf_enabled, point_collection_enabled and qitaf_request_id. There is no index on `order_reference`, `transaction_id` or `created_on`** (Q18). Any youpay↔order join or time-bounded youpay query is a full scan of 2 GB, so it must be sampled or run against a view/extract.

### 2.4 Voucher / Shipping / Address
- **Voucher (all exact-empty, heap 0 B, Q29):** `voucher_voucher`, `voucher_voucherset`, `voucher_voucherapplication`, `voucher_voucher_offers`. Oscar vouchers are unused; promo codes live in `offer_offerpromocode` (§3).
- **Shipping-method tables (all exact-empty, heap 0 B, Q29):** `shipping_orderanditemcharges` (+countries), `shipping_weightbased` (+countries), `shipping_weightband`. **Correction to v1:** v1 called shipping "dead because products are digital". That is not established. The shipping-*config* tables are empty, but every order row still carries NOT NULL `shipping_method` and `shipping_code` (varchar 128) and shipping amounts. These may be a constant oscar default (e.g. "No shipping required" / `no-shipping-required`), or they may encode a delivery channel (email/SMS/WhatsApp/print). P13 checks the distribution. Until then, treat them as a **candidate dimension, not dead**.
- **Address:** `address_country` (22 rows est.) is the active-market reference (ISO codes, currency_id, timezone, phone formats/regex, `is_shipping_country`, `is_active`). It is the **declared country dimension for 5 out-of-scope tables** (§3) and the hottest table on the replica: 13,413,307 seq scans (exact, Q16). `address_countryvat` (14 est.) holds VAT % per country (UNIQUE country). `address_useraddress` is exact-empty (heap 0 B).

## 3. Relations

**Declared FKs inside scope (Q2):**
- `basket_line.basket_id → basket_basket.id`; `basket_basketquantitydetail.line_id` (UNIQUE, 1:1) and `basket_basketpersonalisedetail.line_id` (UNIQUE, 0..1) `→ basket_line.id`.
- `basket_basket.parent_id → basket_basket.id`; `basket_line.parent_id → basket_line.id` (parent/child baskets and lines, probably bundles or multi-recipient splits).
- `basket_mergedbasket.guest_basket_id` and `.user_basket_id → basket_basket.id`.
- `order_order.basket_id → basket_basket.id` (the basket→order conversion join; indexed on the order side).
- `order_line.order_id`, `order_lineprice.order_id` and `order_orderstatuschange.order_id → order_order.id`, all **0..n**. `payment_paymentdetail.order_id → order_order.id` is **UNIQUE, so 0..1** (about 62% coverage; never an inner join).
- `order_orderlinequantitydetail.line_id` (UNIQUE, about 1:1), `order_orderlinepersonalisedetail.line_id` (UNIQUE, 0..1) and `order_lineprice.line_id → order_line.id`.
- `order_order.user_id`, `basket_basket.owner_id`, and all `created_by_id`/`modified_by_id → users_customuser.id`; `order_order.guest_id`, `basket_basket.guest_id → users_guestuser.id`.
- `order_order.region_id`, `basket_basket.region_id → catalogue_store.id`; `order_line.partner_id → partner_partner.id`; `order_line.product_id`, `basket_line.product_id → catalogue_product.id`.
- `order_order.placed_country_id → order_orderplacedcountry.code`; `address_country.currency_id`, `*quantitydetail.denomination_currency_id → core_currency.id`.

**Declared inbound FKs from outside scope (Q13, re-run v2, exact, 5 rows):** all point to `address_country(iso_3166_1_a2)` through `country_id`:
- `catalogue_store`
- `offer_plusoffer`
- `partner_partneraddress`
- `user_tip_tipbrandconfiguration`
- `user_tip_tipbrandretailers`

So `address_country` is the declared **country dimension for stores, offers, partner addresses and tipping config**, not just a lookup. v1 said "no inbound FKs". That is true only for order_/basket_/payment_: none of them receives an inbound FK.

**Offer/campaign lineage (Q17, declared on the offer side, logical on the order side):**
- `order_line.offer_code` varchar(10) ↔ `offer_plusoffer.code` varchar(10) **UNIQUE** (378 est.). This is a logical join (no FK) with matching type and length.
- `offer_offerpromocode.offer_id → offer_plusoffer.id` (41 est.; `promo_code`, `status`, `brand_id`).
- `offer_plusoffer_happy_cards (plusoffer_id, product_id)` UNIQUE → offer_plusoffer / catalogue_product (10,627 est.): the products an offer applies to.
- `offer_plusoffer.brand_id → catalogue_product.id` (brands are modelled as catalogue products); `offer_plusoffer.country_id → address_country`.
- `offer_plusoffer` is heavily read: 13,235,752 idx scans (exact), so the offer lookup is on the hot path of browsing/checkout.

**Logical (undeclared) joins:**
- `youpayclient_youpayclienttransactiondata.order_reference` / `transaction_id` / `payment_reference` ↔ `order_order.order_reference` / `transaction_id` / `payment_order_reference`. Unindexed on the youpay side.
- `payment_paymenttransactionpayload.order` ↔ `order_order.order_reference` / `number` / `payment_order_reference` (to be verified).
- `kafka_giftcreationlog.order_id` (varchar) ↔ order ref.
- `personalization_detail.order_reference_id` / `cart_reference_id` (both indexed) ↔ `order_order.order_reference` / basket ref; `personalization_reference_id` (UNIQUE) ↔ `*quantitydetail.personal_data_ref` (hypothesis).
- `order_line.line_reference` ↔ `basket_line.line_reference`: line-level basket→order lineage, **UNVERIFIED** [STRUCTURAL + NEEDS-GRANT]. The constraints are asymmetric (Q30, exact): `order_line` has `UNIQUE (line_reference)` (globally unique), but `basket_line` has only `UNIQUE (basket_id, line_reference)` plus a non-unique index on `line_reference`, so a basket line reference is unique **only within its basket**. A join on `line_reference` alone can match lines from other baskets and fan out. The safe join goes through the order header: `order_line ol JOIN order_order o ON o.id = ol.order_id JOIN basket_line bl ON bl.basket_id = o.basket_id AND bl.line_reference = ol.line_reference`. Whether order lines actually reuse the basket line's reference at all is unknown until P8c runs (needs `basket_line.basket_id, line_reference, date_created`; `order_line.order_id, line_reference`; `order_order.id, basket_id`).
- `order_line.partner_line_reference` ↔ the partner/brand fulfilment system (issued-gift or partner order id; hypothesis, unindexed).

**Adjacent friction, fee, FX and identity tables (v3, Q21/Q25, declared FKs):**
- `catalogue_productdenominationrange.product_id → catalogue_product`, `.currency_id → core_currency` (both indexed). Join to `basket_line.product_id` + `basket_basketquantitydetail.denomination_currency_id` to test denominations against `minimum_amount`/`maximum_amount`.
- `catalogue_producthandlingfee.product_id → catalogue_product`, `.currency_id → core_currency`; `code` UNIQUE. This is the likely source of `order_order.process_fee` and the varchar `order_orderlinequantitydetail.processing_fee_rate` (hypothesis; logical join via `order_line.product_id` + order currency + `date_placed` within `start_date..end_date`).
- `core_currencyexchangerate (foreign_currency_id → core_currency, base_currency_id → core_basecurrency)`, UNIQUE per pair, with `buy_rate`/`sell_rate` and `modified_on`. It holds only the **current** rate per pair (437 est.; no history table), so FX drift is analysed by comparing it with the per-order snapshots `order_order.conversion_rate_gateway_currency` / `conversion_rate_reporting_currency` and `order_orderlinequantitydetail.conversion_rate*`.
- `users_mergeduser.guest_id → users_guestuser`, `.user_id → users_customuser` (both indexed; never analyzed, 33 pages). This is the guest→registered identity merge, the identity-level counterpart of `basket_mergedbasket`.
- `users_blacklisteduserdetail (type, value)` UNIQUE, `reference_id`, `source`, `is_guest`, `is_removed`. There is no FK to orders; the join is logical on the blacklisted `value` (an email/phone/card-like identifier, so PII), so it can only be matched inside the database by a view, never exported.
- `order_order.created_by_id` (NOT NULL, indexed) / `modified_by_id` (indexed) → `users_customuser`. `created_by_id <> user_id` marks orders placed on a customer's behalf (P30).

## 4. Lifecycle States

**BLOCKED — needs grant: `order_order.status`, `order_orderstatuschange.(old_status,new_status,date_created)`, `order_line.status`, `basket_basket.status`, `payment_paymentdetail.(payment_status,payment_gateway,payment_method,payment_scheme)`, youpay `(approved,payment_status,response_summary)` and the other columns in the table below (§12).** Only the column types are known [STRUCTURAL]. There are no Postgres enums, CHECK-constrained values or defaults for status columns (Q7, Q8). All are free varchar.

| Column | Type | Expected semantics | Prepared query |
|---|---|---|---|
| `order_order.status` | varchar(100), custom index | order lifecycle (pending/paid/failed/cancelled/…) | P1 |
| `order_orderstatuschange.old_status → new_status` | varchar(100) | transition matrix (partial log, §7.4) | P2 |
| `order_line.status` | varchar(255) | per-gift fulfilment state | P3 (sampled) |
| `basket_basket.status` | varchar(128) | oscar Open/Merged/Saved/Frozen/Submitted | P4 (sampled; no index) |
| `payment_paymentdetail.payment_status` / gateway / method / scheme | varchar | gateway outcome and method mix | P5 |
| youpay `approved` / `payment_status` / `response_summary` | bool / varchar | ledger outcome and decline reason | P20 |
| `order_order.shipping_method` / `shipping_code` | varchar(128) NOT NULL | constant oscar default vs delivery channel | P13 |
| `kafka_*datalog.status` (atwork, plusoffer, productoffer), `personalization_update_kafka_data_log.status` | varchar(20) | sync outcome (success/failed/…) | P21, P22 |
| `offer_offerpromocode.status`, `user_tip_tip.status`, `user_tip_invoice.state` | varchar | promo/tip lifecycle | P23 |
| `platform`, `record_type`, `purchase_origin`, `delivery_method`, `delivery_type`, `greeting_code`, `occasion_code`, `settlement_entity`, `redemption_partner` | varchar | channel, gift-type, occasion, B2B-vs-consumer dimensions | P6, P19 |
| refund/cancel-like values of `order_order.status`, `order_line.status`, `payment_paymentdetail.payment_status`, youpay `payment_status` | varchar | the only place refunds/cancellations could appear in this DB | P26 |
| `kafka_giftcreationlog.status` (varchar 200) + `error` | varchar | gift issuance outcome | P29 |
| `users_blacklisteduserdetail.type` / `source` / `is_guest` / `is_removed` | varchar(25) / bool | block-list mechanics | P27a |
| `catalogue_productdenominationrange.range_type`, `catalogue_producthandlingfee.handling_fee_type` | varchar(15/20) | denomination-range and fee-rule kinds | P27b, P27c |
| `offer_plusoffer.reason_code`, `is_unique_promo_code` / `is_generic_promo_code` | varchar(100) / bool | offer deactivation reason, promo-code mode | P28 |

## 5. Time Coverage & Trends

**BLOCKED — needs grant: the timestamp columns listed below, on `order_order`, `order_orderstatuschange`, `basket_line`, `basket_basket`, `order_line`, `payment_paymentdetail`, youpay and the `kafka_*` logs (§12).** Column types, indexes and replica counters below are [STRUCTURAL]. Main timestamp columns and whether they are indexed (Q3b/Q18):
- `order_order.date_placed` (indexed), `date_updated`, `sold_date`;
- `order_orderstatuschange.date_created` (indexed);
- `basket_line.date_created`/`date_updated` (indexed);
- `basket_basket.date_created`/`date_submitted`/`date_merged` (NOT indexed, so sample them);
- `order_line.created_on`, `instant_activated_date` (NOT indexed, so bound through `order_id` of date_placed-bounded orders);
- `payment_paymentdetail.created_on`; `payment_paymenttransactionpayload.created_on`;
- youpay `created_on` (**NOT indexed**);
- `kafka_*datalog.start_timestamp`/`completed_timestamp` (**NOT indexed**; pkey only).

All are `timestamp with time zone`. Personalise tables use `delivery_date` (date) + `delivery_time` (time without tz) + `delivery_time_zone` (varchar), so the scheduled send is local wall-clock time. The monthly trend query is P7; log start dates are P9 and P12.

**Replica read activity (Q16, exact, cumulative since table-stats start, last scans today):**
- `order_order` seq 2,178 / idx 452,617;
- `order_line` 36 / 738,306;
- `payment_paymentdetail` 36 / 101,859;
- `order_orderstatuschange` 834 / 1,668;
- youpay 909 / 129,122;
- `payment_paymentmethod` seq 31,931;
- `address_country` seq 13,413,307;
- `offer_plusoffer` idx 13,235,752;
- **`basket_basket`, `basket_line`, `basket_basketquantitydetail`, `basket_basketpersonalisedetail`, `kafka_giftcreationlog`, `kafka_atworkkafkadatalog`, `core_currencybasketlimit`: 0 seq and 0 idx scans.** Nothing currently reads baskets or the kafka logs from this replica. Basket analytics would be a **new, uncached workload** on a 1.6 GB table with no date/status index, so use TABLESAMPLE or an extract.

**Workload profile (pg_stat_statements, Q10/Q19; stats reset 2026-06-26). All figures are point-in-time snapshots that drift between runs and are exact only at the moment read:**
- The view is **cluster-wide**. At the v2 read: 4,897 entries and 420,026,587 calls across 6 DBs, with `ygag_ecomweb_stores_db` at 384,590,865 calls and `rdsadmin` at 33,582,381. At the v3 re-read (Q19b): 4,967 entries, 420,183,496 calls, `dealloc` 663,184.
- `ygag_ecom_orders_db` itself: **19 entries / 1,857,904 calls / 185 s exec** at v2; **20 entries / 1,858,725 calls** at v3 (the critic saw 18 / 1,859,038 in between). Entry counts go up and down because entries are evicted. Its top statement: 1,495,891 calls returning 0 rows at 0.03 ms (an existence or lock probe). Next are 224,777 calls at about 10 rows/call and 114,734 calls at about 8.4 rows/call (order-line style fetches); one rare heavy statement runs 19 calls at about 1,925 rows/call and 80 ms mean.
- `dealloc` = 662,982 (v2) → 663,184 (v3), so entries are evicted constantly. pg_stat_statements is **not a reliable workload record** for this DB; table counters (above) are the better signal.

## 6. Behavior Signals

Volumes are reltuples estimates unless marked; ratios use extrapolated counts (Q20).

**Explicitly absent dimensions (v3):**
- **Acquisition / attribution: none in this DB.** [STRUCTURAL] A catalog-wide column search for `refer|utm|campaign|source|channel|affiliate|medium|acquisition|attribution|gclid|fbclid` (Q22, exact) finds only false positives: `*_reference` keys, `offer_plusoffer.offer_channel` / `offer_productoffer.channel` (offer distribution channel), youpay `channel_code` (payment channel), `users_blacklisteduserdetail.source` (who added the block) and the empty oscar `payment_source*`. No order, basket or payment table carries a referral, UTM or first-touch source. **Owner of attribution:** web/app analytics (GA4/Firebase/AppsFlyer-style) and the ads units. The join back to this DB would have to be on `order_order.number` / `order_reference` / `session_id` (the last is PII-classified) and must be confirmed with those units. `platform` and `language_code` are the only acquisition-adjacent dimensions here.
- **Refunds / cancellations: not tracked in any populated table.** [STRUCTURAL] Refund-like columns (Q23, exact): `payment_source.amount_refunded` (0 rows), `customer_productalert.date_cancelled` (0 rows, a stock alert, not an order), youpay `cancel_url` (a redirect URL, PII-classified). `order_paymentevent` / `order_paymenteventtype` (oscar's refund-event mechanism) are empty. So refunds live in `ygag_youpay_db` (same cluster, Q19) or a finance system, **or** only as status values; P26 lists refund/cancel/reverse-like values across the four status columns.

- **Cart creation:** [STRUCTURAL ratio; empty-cart share NEEDS-GRANT: P8b] `basket_basket` about 3.05M (extrap.); only about 0.60 basket_lines per basket (1,824,296 / 3,046,354 extrap.), so a large share of baskets likely never get an item (session-created empty carts). Verify with P8b.
- **Gift configuration:** [STRUCTURAL ratio; gift/self split NEEDS-GRANT: P14] about 30.6% of basket lines personalised (557,973 / 1,824,296 extrap.). `is_buy_for_self` distinguishes gift from self-purchase (**gift vs self split: P14**).
- **Guest vs registered:** [NEEDS-GRANT: P15/P15b/P15c/P31/P34] `guest_id` on basket and order, `basket_mergedbasket`, `users_mergeduser` (guest→registered identity merge, indexed on both ids), `order_giftactivationconfig.is_guest_enabled`. **Guest vs registered order mix: P15; basket-side conversion by guest flag: P15b; merge-after-guest-purchase: P15c.** `users_cognitouserdatasynclog` (93,871 est.; `status` varchar(10), `error` jsonb NOT NULL, `payload` jsonb) is the Cognito identity-sync log. A sync error there means a registered identity that failed to land locally, which is friction on the guest→registered step (P31).
- **Orders placed on someone's behalf:** [NEEDS-GRANT: P30] `order_order.created_by_id` is NOT NULL and indexed. For self-service orders it should equal `user_id`. `created_by_id <> user_id` (or `user_id IS NULL` with a staff `created_by_id`) marks admin, API or @Work orders placed on a customer's behalf. `modified_by_id IS NOT NULL` marks manual interventions after placement. Unmined signal: **P30**.
- **Order placement:** [STRUCTURAL ratio] about 1.23M orders, about 1.19 lines per order (extrap.; a lower bound because `order_line` is likely under-counted), about 34.9% of order lines personalised (513,374 / 1,473,029 extrap.).
- **Scheduled vs instant delivery:** [NEEDS-GRANT: P16] personalise `delivery_date` not null vs `order_line.is_instant_activated`. **Mix plus lead time `instant_activated_date - created_on`: P16.**
- **Stuck fulfilment:** [NEEDS-GRANT: P17/P29] `order_order.gift_create_event_triggered = false` among paid orders (**P17**). It cross-checks against the out-of-scope `kafka_giftcreationlog` (3,134,464 est., status/error).
- **Gift-issuance multiplicity (v3):** [STRUCTURAL ratio; cause NEEDS-GRANT: P29] `kafka_giftcreationlog` is 3,256,033 extrap. (+3.9% since ANALYZE), which is **about 2.64 events per order** and **about 2.21 per order line** (extrap.; the per-line figure is an upper bound because `order_line` is likely under-counted). Only `event_id` is UNIQUE (Q21); `order_id` is varchar(255) NOT NULL and **unindexed**; `created_on` is **unindexed** (Q25). More than two events per line suggests per-gift-unit events (quantity > 1), retries, or duplicate issuance events. The distinction matters for "gifts issued" metrics and for detecting double issuance. **P29** measures events per distinct `order_id` by `status` and `(error IS NOT NULL)`, and cross-checks against `gift_create_event_triggered` (P17).
- **Payment and loyalty (youpay ledger):** [NEEDS-GRANT: P20/P20b/P25]
  - `approved` / `response_summary` give the decline mix (**P20**);
  - points-based payment: `is_full_redemption`, `redeemed_points`/`redeemed_amount`, `available_points` (a partial-redemption behaviour, and "insufficient points" friction), `earned_point`, `loyalty_level`, `is_qitaf_enabled`/`qitaf_request_id` (Qitaf/STC points);
  - `channel_code` and `platform` for the payment channel;
  - `order_history` jsonb for attempt history (retries).
- **Offers/campaigns:** [STRUCTURAL columns; uptake NEEDS-GRANT: P18/P28/P21] `order_line.is_offer_applied` (indexed) + `offer_code` → `offer_plusoffer` (`offer_type`, `offer_mode`, `offer_channel`, `funding_method`/`funded_by`, `budget_*`, `has_budget_exceeded`, `sponsor_payment_network`, meaning card-network-sponsored offers). **Offer uptake by offer_type/funded_by: P18.** **Offer mechanics (v3, Q26):** `offer_plusoffer` also carries `start_date`/`end_date` (NOT NULL), `is_active`, `is_budget_available`, `budget_type`/`budget_amount`/`budget_threshold`, `has_budget_exceeded`, `reason_code` varchar(100) (likely the deactivation/exhaustion reason), `promo_code_threshold` int (redemption cap), `promo_code_end_date`, and the NOT NULL flags `is_unique_promo_code` / `is_generic_promo_code` (a single shared code vs one code per customer). Together these cover promo exhaustion (budget or threshold hit), expiry (`promo_code_end_date` before `end_date`) and the unique-vs-generic split. **P28.** `kafka_plusofferkafkadatalog` (201,682 est., 1,477 MB, mostly TOAST 1,455 MB, so large jsonb payloads) and `kafka_productofferkafkadatalog` (767 est.) are the offer-sync streams (`status`, `error_data`, start/completed). Like the atwork log they have **no offer or order key column** (Q31); the link to `offer_plusoffer.code`/`id` exists only inside `data` jsonb, so the offer-sync-error → failed-offer-order hypothesis needs the extracted-key view in §12.2 [NEEDS-GRANT]. **Status mix: P21 (B); error presence and key extraction: P21-A.**
- **YGG@Work / B2B:** [hypothesis, NEEDS-GRANT: P19/P22-A] `kafka_atworkkafkadatalog` (1,700,549 est., 528 MB; `data` jsonb, `status`, `error_data`, start/completed timestamps; pkey only) is the second-largest log in the DB.
  - **Hypothesis:** it is the YGG@Work corporate purchase/sync stream, and the B2B vs consumer split is visible on `basket_basket.record_type` / `basket_line.record_type` (varchar(10) NOT NULL) and `purchase_origin` (varchar 20), which exist on basket_line and order_line (not on order_order).
  - **No key column (Q31, exact):** `kafka_atworkkafkadatalog` has exactly `id, data jsonb NOT NULL, status varchar(20) NOT NULL, error_data text NOT NULL, start_timestamp, completed_timestamp`, and only a pkey index. There is **no order, basket, line, company or offer key column**, so any join from this log to `order_order` depends entirely on keys inside `data`. [STRUCTURAL]
  - To verify: P19 (record_type/purchase_origin mix, runs under Option B) and P22 (atwork status mix, runs under B; payload key names and extracted order keys, **Option A only**, via `atlas_ro.kafka_atworkkafkadatalog` in §12.2). **Without that view, P22 cannot confirm the @Work mapping** [NEEDS-GRANT].
- **Personalisation edits after purchase:** [STRUCTURAL ratio; behaviour NEEDS-GRANT: P22c] `personalization_detail` (94,394 est.; `personalization_data` jsonb, `cart_reference_id`, `order_reference_id`) and `personalization_update_kafka_data_log` (**128,996 est. = extrap.**, 0% page growth since ANALYZE, Q20 re-run v4; v3's 139,132 is no longer the catalog value: `relpages` now equals the current page count, so the primary has re-analyzed the table since v3 read it). The update log outnumbers the details (128,996 / 94,394 ≈ **1.37 updates per detail**, extrap.) [STRUCTURAL], which suggests edit/resend-after-purchase behaviour [NEEDS-GRANT: P22c]. **The log has no order, line or personalisation key column** (only `id, data jsonb, status, error_data text, start_timestamp, completed_timestamp`; Q31), so linking an update to `personalization_detail` or an order depends on keys inside `data` jsonb.
- **Tipping add-on:** [NEEDS-GRANT: P23] `user_tip_tip` (never analyzed; `status`, `platform`, `amount`, `amount_in_aed`, `send_tip_gift_event_triggered`, `receiver_phone_number` PII), `user_tip_invoice` (never analyzed; `state`, `amount`, `service_charge`, `vat_amount`, `payment_method`), `user_tip_tipbrandconfiguration` (7 est.), `user_tip_tipbrandretailers` (42 est.). P23 (needs the v4 grants on `user_tip_tip` / `user_tip_invoice` in §12.1; `receiver_phone_number`, `extra`, `card_last4` excluded).
- **Post-purchase reviews:** [STRUCTURAL; out of scope for grants] `reviews_googlereview` (23,984 est.; `is_reviewed`, `reviewed_date`, `platform`; PII `user_email`, `user_ip_address`, `user_agent`). This is a satisfaction proxy joinable by `user_reference` uuid.
- **Sold/redemption:** [STRUCTURAL] `order_order.sold_date`, `redemption_partner`; `kafka_solddateupdatekafkadatalog` (34,582 est.).
- **White label / origin:** [NEEDS-GRANT: P19] `is_white_label`, `purchase_origin`. **Order view tracking:** `order_order.is_visited`.
- **Repeat purchase (v4)** [NEEDS-GRANT: P35]. `order_order.user_id` and `guest_id` are both indexed, as is `date_placed` (Q30), so orders per `user_id` (and per `guest_id` for guests) over a bounded `date_placed` window is a cheap index-driven query. It gives the repeat rate, the orders-per-customer distribution and the days to second order. It needs `order_order.(user_id, guest_id, date_placed, status)` only (all in the Option B grant); which statuses count as purchases comes from P1 first. A guest who later registers appears under two ids; `users_mergeduser` (guest_id → user_id) deduplicates them.
- **Guest sessions vs guest orders (v4)** [NEEDS-GRANT: P34]. `users_guestuser` (82,502 est. = extrap., 41 MB heap; Q31) is the guest identity row created before a guest checks out. Its non-PII columns are `id, created_on, modified_on, platform varchar(20) NOT NULL, last_accessed, is_active`; `email`, `username`, `session_id` (UNIQUE), `db_session_id`, `extra` jsonb and `note` are PII or identifiers and are excluded. It has **no index on created_on or platform** (pkey and `session_id` only), but at 41 MB a full scan is cheap. Guests created per platform per month vs guest orders (`order_order.guest_id`, indexed) per platform per month is the guest-checkout completion rate. It is independent of the basket sample in P15b. 82.5k guest rows against about 1.23M orders means guests are a small share of orders, **or** guest rows are reused or pruned. [STRUCTURAL ratio; interpretation NEEDS-GRANT]
- **Registered-user base (v4)** [STRUCTURAL]. `users_customuser` 991,558 est. / 996,517 extrap. (+0.5%; 108 MB heap). Non-PII columns: `id, last_login, date_joined, is_active, is_staff, is_superuser`; excluded: `password`, `first_name`, `last_name`, `email` (UNIQUE), `username`. No index on `date_joined`, so a monthly-signup query is a 108 MB full scan (acceptable off-peak, or TABLESAMPLE). `is_staff`/`is_superuser` are needed by P30 to separate staff-created orders.
- **Admin config-change history (v4)** [STRUCTURAL; NEEDS-GRANT: P33]. `django_admin_log` (2,608 est. / 2,742 extrap., +5.1% page growth; Q20) records every Django-admin add/change/delete: `action_time` timestamptz, `action_flag` smallint (1 add, 2 change, 3 delete in stock Django), `content_type_id` → `django_content_type` (150 est.; `app_label`, `model`), `object_id` text, `user_id` → users_customuser, plus `object_repr` varchar(200) and `change_message` text (**excluded: `object_repr` is the object's string form and can be an email or name**). Indexed on `content_type_id` and `user_id`, not `action_time`, but it is tiny. Grouped by model × action × month, it is the change history of the friction config in §7.1 (`core_currencybasketlimit`, `payment_paymentmethod`, `order_giftactivationconfig`, `catalogue_productdenominationrange`, `offer_plusoffer`, `users_blacklisteduserdetail`), so a conversion shift can be matched to the config change that caused it. `payment_logentrydata` (§2.3) extends it with before/after payloads for payment config; it stays excluded.
- **Preset vs custom denominations (v4)** [NEEDS-GRANT: P36]. `catalogue_productdenomination` (22,404 est. = extrap.; `product_id`, `currency_id` → core_currency, `amount` numeric(15,6), `is_default` bool NOT NULL, `is_active`, `order_number` (display order), `gencode`) is the list of preset gift values per product/currency, with one flagged as the pre-selected default. Matching `basket_basketquantitydetail.denomination` (numeric(20,6)) + `denomination_currency_id` against it, via `basket_line.product_id`, gives the share of lines that keep the default, pick another preset, or enter a custom amount. That is a UX-friction signal on the product page, and it complements the out-of-range test (P27b).
- Not in this DB-unit: logins, 2FA, sessions (`django_session`, `otp_*` are other units), notifications (`communication_*` is empty).

## 7. Friction & Errors

**BLOCKED — needs grant for every rate or count in this section (§12).** The mechanisms and config tables are [STRUCTURAL]; every friction hypothesis is [NEEDS-GRANT] with its prepared query named.

### 7.1 Purchase-friction configuration (explanations for blocked checkouts)
| Config | Rows (est.) | Mechanism | Prepared query |
|---|---|---|---|
| `core_currencybasketlimit` | 8 | `limit_amount` numeric(15,6) per `currency_id` (UNIQUE), `is_active`. It caps basket value per currency, so baskets over the cap cannot check out. | P24a: list caps; P24b: sampled baskets whose line total exceeds the active cap for their currency and have no order |
| `core_unsupportedcountry` | never analyzed | `country_code` varchar(2) UNIQUE, `is_active` (indexed). A geo-block list. | P24c: list active codes; compare with `order_order.placed_country_id` mix (P6) |
| `order_giftactivationconfig.is_guest_enabled` | 1 | guest checkout toggle | P15 over time (a guest share drop means the toggle was off) |
| `payment_paymentmethod.is_active` | 20 | disabled methods | P24d: list methods × is_active, joined to P5/P20 method mix |
| `users_blacklisteduserdetail` | 48,646 (extrap. same; 0 growth) | Checkout block list: `type` varchar(25) (what is blocked, e.g. email/phone/card/device), `value` varchar(256) (**PII, never select**), UNIQUE(type, value), `source` varchar(25) (who or what added it: admin, fraud sync, …), `reference_id`, `is_guest`, `is_removed` (soft unblock), `created_on`. A blocked identifier cannot check out. `kafka_blacklistuserkafkadatalog` / `kafka_blacklistusergiftlog` (§7.5) are the sync streams that feed and act on it. Only pkey, (type,value) and created/modified_by are indexed (Q25), but at 48k rows a full scan is cheap. | P27a: `type × source × is_guest × is_removed` mix and monthly adds |
| `catalogue_productdenominationrange` | 11,376 | Per-product (`product_id`) and per-currency (`currency_id`) `minimum_amount` / `maximum_amount` numeric(15,6), `range_type` varchar(15), `is_active`. It bounds the gift value a customer can pick; a denomination outside the range is rejected before or at basket. | P27b: sampled `basket_basketquantitydetail.denomination` outside the active range for its product/currency, and whether those baskets converted |
| `catalogue_producthandlingfee` | 939 (991 extrap.) | Per-product fee rules: `code` UNIQUE, `amount` numeric(25,3) and/or `percentage` numeric(5,2), `handling_fee_type` varchar(20), `currency_id`, `start_date`/`end_date` (date), `is_active`. The **likely source** of `order_order.process_fee` and the varchar `processing_fee_rate` (hypothesis). A fee shown at checkout is price friction. | P27c: active rules by type; orders with `process_fee > 0` by whether an active rule exists for the line's product |
| `django_admin_log` (change history of the configs above) | 2,608 (2,742 extrap.) | Every admin add/change/delete with `action_time`, `action_flag`, `content_type_id`, `object_id`, `user_id`. It dates each config change above so friction can be attributed to it. | P33: model × action × month; then the change dates for the friction-config content types against P7/P15 trends |
| `catalogue_productdenomination.is_default` | 22,404 | Preset gift values and the pre-selected default per product/currency | P36 |
| `offer_plusoffer` promo limits | 378 | `promo_code_threshold`, `promo_code_end_date`, `has_budget_exceeded`, `budget_*`, `reason_code`, `is_unique_promo_code`/`is_generic_promo_code`. Once exhausted or expired, the code is rejected at checkout. | P28 |

### 7.2 Abandonment and unpaid orders (catalog ratios only; BLOCKED — needs grant for real rates)
- **Basket abandonment:** [STRUCTURAL ratio; real rate NEEDS-GRANT: P8/P8b/P15b] 1 − 1,233,955/3,046,354 ≈ **59.5%** of baskets have no order (extrap.). This is crude: it includes empty session baskets. The real metric needs P8/P8b/P15b.
- **Orders without a paymentdetail row:** [STRUCTURAL ratio; cause NEEDS-GRANT: P9/P20/P25] about 37.6% (extrap.). v2 explained this with "youpay covers 99.8%". That is withdrawn: youpay's per-order cardinality is unknown (§2.3), so youpay row counts cannot show which orders it covers. The gap may be a paymentdetail coverage gap (a backfill starting after launch, or detail written only for some gateways) **or** unpaid/failed orders. P9 checks start dates; P25 checks distinct youpay order coverage; P20 gives the decline rate.
- **Middle step:** [STRUCTURAL; NEEDS-GRANT: P8c] order_line/basket_line = 80.7% (extrap.) is **not a conversion rate**. Lines are keyed per basket, baskets and lines can be split or merged via `parent_id` / `basket_mergedbasket`, and one order line can carry quantity > 1. The line-level conversion must be measured by P8c, which joins through `order_order.basket_id` because `basket_line.line_reference` is unique only per basket (§3).

### 7.3 Payment errors, fraud, price drift
- **Decline mix:** [NEEDS-GRANT: P20/P20b] youpay `approved=false` grouped by `response_summary`, `payment_method`, `payment_gateway` (P20). Points friction: `is_full_redemption` / `redeemed_points` vs `available_points` (P20b).
- **Fraud/flags:** [NEEDS-GRANT: P5/P20] `is_fraud`, `is_flagged` on paymentdetail and youpay (P5, P20).
- **Price drift between checkout and payment:** [NEEDS-GRANT: P10] the `*_before_payment` / `*_before_pay` columns (P10).
- **Retries:** [NEEDS-GRANT: P25] youpay `order_history` jsonb (attempt history), possibly several youpay rows per order (P25), and `payment_paymenttransactionpayload` (65k, likely gateway callbacks). Status-change counts are **not** usable as retry evidence (see 7.4).
- **FX drift:** [NEEDS-GRANT: P32] `core_currencyexchangerate` (437 est.; `buy_rate`/`sell_rate`, UNIQUE per foreign/base pair) holds only the current rate. Drift is the gap between the rate snapshotted on the order (`conversion_rate_gateway_currency`, `conversion_rate_reporting_currency`, line `conversion_rate*`) and today's rate. It can only be computed for recent orders, or over time if the rate table is snapshotted by the atlas (P32).

### 7.4 The status-change log is probably incomplete (corrected in v3) [STRUCTURAL ratio; proof NEEDS-GRANT: P11/P12]
**v2 was wrong to call this "provable" with a 75k lower bound.** v2 compared two raw reltuples taken from different ANALYZE runs. Staleness-adjusted (Q20): the log has grown **4.54%** since its last ANALYZE (10,209 → 10,672 pages) and `order_order` only **0.14%** (176,977 → 177,233 pages). That gives **1,209,722 status changes vs 1,233,955 orders ≈ 0.98 per order**, a gap of about **24k**, and both figures are estimates. If every order has at least one transition (placed → paid/failed), the ratio still hints that some orders have no status-change row, but a 2% gap is within estimation error. It could equally be a log that writes about one row per order with some orders having several and others none. Possible causes, if confirmed: the log started after launch; it is written only for some transitions; or orders are inserted directly in their final status. **Until P11/P12 run, the funnel must not be built on `order_orderstatuschange`.** Use `order_order.status` + `date_placed` + (deduplicated) youpay outcome. Checks, the only valid proof:
- P11: share of orders (last 90 days, date_placed-bounded) with zero status-change rows, by final status;
- P12: `min(date_created)` in the log vs `min(date_placed)` in orders (both indexed).

### 7.5 Adjacent error logs (join keys: declared column vs inside jsonb)

**Correction to v3:** v3 called these logs "joinable by order/offer ref". Only `kafka_giftcreationlog` has a key column. The atwork, plusoffer, productoffer and personalization-update logs share one 6-column shape with no business key (Q31), so their errors can be tied to orders or offers only through keys extracted from `data` jsonb, which needs the Option A views in §12.2 [STRUCTURAL]. Option B (status + timestamps) gives only status mix and latency over time.

| Log | Rows (est.) | Error columns | Join key to the funnel |
|---|---|---|---|
| `kafka_giftcreationlog` | 3,134,464 (3,256,033 extrap.) | status, error varchar(255), failure text (gift issuance); about 2.64 events per order (§6, P29) | `order_id` varchar(255) column (unindexed; which order key it holds is Open Question 4) |
| `users_cognitouserdatasynclog` | 93,871 | status varchar(10), error jsonb NOT NULL (identity sync; P31) | none: columns are `id, created_on, modified_on, payload, status, error`; user identity only inside `payload` (PII) |
| `kafka_atworkkafkadatalog` | 1,700,549 | status, error_data (B2B sync, hypothesis) | **none: only inside `data` jsonb** (Q31) |
| `kafka_plusofferkafkadatalog` | 201,682 (203,047 extrap.) | status, error_data (offer sync) | **none: only inside `data` jsonb** (Q31) |
| `personalization_update_kafka_data_log` | **128,996** (extrap. same) | status, error_data | **none: only inside `data` jsonb** (Q31) |
| `kafka_solddateupdatekafkadatalog` | 34,582 | sold-date sync | not checked in v4 |
| `kafka_legacyfraudsynclog` | 16,691 | fraud sync | not checked in v4 |
| `kafka_blacklistusergiftlog` / `kafka_blacklistuserkafkadatalog` | 7,354 / 2,317 | blacklist | not checked in v4 |
| `kafka_productofferkafkadatalog` | 767 | status, error_data | **none: only inside `data` jsonb** (Q31) |
| `webhooks_merchantwebhookmessage` | about 5.2k (v1 Q14) | `error_message` | not checked in v4 |

## 8. Cross-DB Keys

Types come from the catalog. **Numeric ranges could not be read.**

| Column | Type | Likely shared with |
|---|---|---|
| `order_order.user_id`, `basket_basket.owner_id` → `users_customuser.id` | bigint | the local users table (Cognito sub bridge via `users_cognitouserdatasynclog`) |
| `order_order.owner`, `basket_basket.user` | varchar(150) | username/email string (**PII**) |
| `order_order.guest_id` → `users_guestuser.id` | bigint | local only |
| `order_order.number`, `order_reference`, `payment_order_reference` (varchar 21), `transaction_id`, `session_id` | varchar | `ygag_youpay_db` (the same cluster hosts it, Q19), youpay client table, gift-creation service, finance/BI |
| `order_line.line_reference` | varchar(200) | gift/voucher service (per-gift ref, likely the gift-creation idempotency key) |
| **`order_line.partner_line_reference`** | varchar(128) NOT NULL | **partner/brand fulfilment reference or issued-gift id** in brand/gift services; a key cross-DB join candidate (unindexed here) |
| **`order_line.partner_line_notes`** | text NOT NULL | partner fulfilment notes. **Classified potentially sensitive** (may hold gift codes/PINs or recipient data) until inspected; exclude from views |
| `order_line.partner_id` / `partner_name` / `partner_sku` / `upc` | bigint / varchar | brand ids/codes in catalogue/brand-portal DBs |
| `order_order.region_id` → catalogue_store; `placed_country_id` (varchar 5); `address_country.iso_3166_1_a2` | bigint / varchar | store/region/country codes across YGG apps |
| `order_line.offer_code` (varchar 10) → `offer_plusoffer.code` | varchar | campaign/offer service (via `kafka_plusofferkafkadatalog`) |
| `personal_data_ref` (varchar 200) ↔ `personalization_detail.personalization_reference_id` | varchar | personal-data vault |
| youpay `qitaf_request_id`, `point_program` | varchar | STC Qitaf / loyalty partners |
| `payment_paymentdetail.settlement_entity`, `redemption_partner` | varchar | finance / partner systems |
| `kafka_giftcreationlog.order_id` (varchar 255), `event_id` (uuid UNIQUE) | varchar / uuid | gift-creation service (event id is the cross-service idempotency key) |
| `order_order.created_by_id` / `modified_by_id` → users_customuser | bigint | staff/admin or API actor; the @Work unit if @Work orders are created by service users |
| **acquisition source** | – | **absent here**: must come from web/app analytics or ads units (§6) |
| **refunds** | – | **absent here**: `ygag_youpay_db` or finance (§6, P26) |

## 9. PII (column names only)

- `basket_basket`: `user`, `user_email`, `user_name`, `user_phone`, `user_gender`, `note`.
- `order_order`: `user_email`, `guest_email`, `user_name`, `user_phone`, `owner` (**each column is NOT NULL (may be empty string)**; the share of rows with a non-empty value is unknown and is measured only through the `has_*` flags in the §12.2 view), plus nullable `user_gender`, `session_id`, `transaction_url`, and `extra` (jsonb NOT NULL, may contain PII).
- `order_line`: `partner_line_notes` (potentially sensitive: gift codes or recipient data), `partner_line_reference` (secret-adjacent until verified).
- `basket_basketpersonalisedetail` / `order_orderlinepersonalisedetail`: `phone_number`, `email_address`.
- `basket_basketquantitydetail` / `order_orderlinequantitydetail`: `sender_name`, `personal_data_ref`.
- `payment_paymentdetail`: `name_on_card`, `card_bin`, `card_last4`, `brand_calculations` (jsonb).
- `payment_paymenttransactionpayload.payload`.
- youpay: `customer_email`, `customer_name`, `customer_ip_address`, `name_on_card`, `card_bin`, `card_last4`, `session_id`, `points_collected_mobile_number`, `points_redeemed_mobile_number`, `order_history`/`order_items`/`udf1` jsonb, `*_url`.
- `personalization_detail.personalization_data` (jsonb); `kafka_*datalog.data` (jsonb payloads).
- **`kafka_giftcreationlog`: `payload` (text), `created_gift_details` (text) and `failure` (text).** `created_gift_details` plausibly holds **issued gift codes/PINs/redemption links** (secret-class, at least as sensitive as `partner_line_notes`). `payload` likely carries recipient/sender data. `failure` may echo either. All three are excluded from grants; only `status` and `error` varchar(255) are exposed, and `error` should be reviewed on first sample.
- `users_blacklisteduserdetail.value` (the blocked email/phone/card identifier; PII by definition), `reference_id`.
- `users_cognitouserdatasynclog.payload` (jsonb, identity attributes); `error` jsonb (may echo payload).
- `user_tip_tip.receiver_phone_number`, `extra`; `user_tip_invoice.card_last4`.
- `reviews_googlereview.user_email`, `user_ip_address`, `user_agent`.
- v4 adjacent identity/admin tables: `users_customuser.password` (hash, secret-class), `first_name`, `last_name`, `email`, `username`; `users_guestuser.email`, `username`, `session_id`, `db_session_id`, `extra`, `note`; `django_admin_log.object_repr` (the object's string form, often an email or name) and `change_message`; `offer_offerpromocode.promo_code` (a redeemable code, secret-class). All excluded in §12.
- Empty but PII by definition: `address_useraddress`, `order_billingaddress`, `order_shippingaddress`, `payment_bankcard`, `order_ordernote.message`; `payment_logentrydata.old_data`/`modified_data`.

## 10. Data Quality

- **30 of the 50 in-scope tables are exact-empty** (0-byte heap, Q29) [STRUCTURAL]. Exclude them from the registry, **except that the `order_order.shipping_*` columns stay pending P13**.
- **Duplicated concepts:**
  - order totals exist in `order_order`, `order_line`, `order_lineprice` and `order_orderlinequantitydetail`;
  - payment appears in `payment_paymentdetail` (0..1, about 62%) vs youpay (row count 100.3% of orders, **per-order cardinality unknown, not enforced by any constraint**).

  Proposal: the revenue source is `order_orderlinequantitydetail.*_in_reporting_currency`; payment outcome and loyalty come from youpay **only after deduplication to one row per order** (e.g. latest `approved=true` row per `order_reference`, pending P25); paymentdetail is only an optional enrichment via LEFT JOIN.
- **Fee rates as strings:** `processing_fee_rate` and `processing_fee_vat_rate` are varchar(20) (nullable). Fee-rate math needs a safe cast. Values may be "2.5", "2.5%", "" or text, so check with P13b. Prefer the numeric `processing_fee_in_*` / `processing_fee_vat_in_*` amounts for metrics.
- **1:1 detail tables are near-complete:** quantitydetail ≈ line (basket 97.8%, order 100.5%, extrap.). Values at or above 100% for UNIQUE(line_id) tables show that `order_line` is under-counted by page extrapolation (§0), not that details exceed lines.
- `order_lineprice` / order_line is 100.7% extrap. (96.9% raw est. in v2). The v2 figure came from stale stats. The true coverage is unmeasured, and lineprice is 0..n per line.
- **Never analysed** (`reltuples=-1`): `basket_mergedbasket`, `payment_logentrydata`, `core_unsupportedcountry`, `user_tip_tip`, `user_tip_invoice`, `offer_productoffer*`.
- **Weak / unindexed keys:**
  - `payment_paymenttransactionpayload.order` (no FK, no index);
  - youpay `order_reference`/`transaction_id`/`created_on` (no index; 2 GB);
  - `kafka_giftcreationlog.order_id` varchar and `created_on` (only `event_id` and pkey indexed; any time or order bound needs TABLESAMPLE);
  - youpay has **no uniqueness** on `order_reference` / `transaction_id` / `payment_reference` (PK only);
  - `order_line.partner_line_reference`, `created_on`, `instant_activated_date` (no index);
  - `stockrecord_id` points to the empty `partner_stockrecord`.
- **Transition log is probably incomplete** (0.98/order extrap., §7.4; unproven).
- **Stale planner stats:** growth since last ANALYZE ranges from 0% to 4.5% across key tables (§0, Q20). Registry row-count checks must use live `count(*)` on views once granted, never reltuples.
- **Row width:** `order_order` is about 1,177 B/row heap (177,233 current pages × 8 KB / 1,233,955 extrap.) with **0 MB TOAST**. It has **63 non-dropped columns** (46 NOT NULL; Q24), not ~80 as v2 said. Width comes from many numeric money variants plus wide varchars: `user_email` (512), `transaction_url` (512), `session_id` (500), `user_name`/`user_phone` (256), `transaction_id` (256), `redemption_partner` (255), `guest_email` (254). Heap bytes per row also include **dead tuples and page free space**, so 1,177 B is not purely column width (`n_dead_tup` is not replicated, so bloat cannot be measured here). Profile the `extra` keys (P13c) once access exists. By contrast, `kafka_plusofferkafkadatalog` is 98.5% TOAST (1,455 of 1,477 MB), so its payloads are large.
- `basket_basket` (1.6 GB) has **no date/status index and 0 replica reads**.
- Personalise delivery time is local date + time without tz + a tz string.
- The output redactor mangles ISO timestamps into `<phone>`.

## 11. Open Questions

1. **Access (blocking; escalate to DBA).** Consolidated in **§12 Grant request**: Option B column grants (§12.1), Option A PII-free views with derived flags and extracted jsonb keys (§12.2), index/extract asks (§12.3), and the P-query ↔ grant matrix (§12.4). **Until §12 lands, §4, §5 and §7 are BLOCKED and this unit cannot pass.**
2. What values do `order_order.status` / `order_line.status` take, and which ones mean "paid/sold"? Is `sold_date` the canonical recognition date?
3. Is `payment_paymentdetail` populated only since some date, or only for some gateways (P9)? Confirm that youpay is the canonical payment ledger.
4. Which order key do `payment_paymenttransactionpayload.order`, `kafka_giftcreationlog.order_id` and youpay `order_reference` hold (`number`, `order_reference` or `payment_order_reference`)?
5. Are empty baskets created per session (P8b)? That decides the abandonment denominator.
6. What do `record_type`, `purchase_origin`, `is_white_label` and `redemption_partner` mean? Does `kafka_atworkkafkadatalog` represent YGG@Work (B2B) purchases, and does `record_type` separate them?
7. Are `order_order.shipping_method`/`shipping_code` a constant or a delivery channel (P13)?
8. What is in `order_line.partner_line_reference` / `partner_line_notes`? Can a partner reference be exposed? Do notes ever contain gift codes?
9. When did `order_orderstatuschange` logging start, and which transitions are logged (P11/P12)?
10. How recent is the primary's last ANALYZE? **Partly answered in v3 without a grant (Q20):** the replica does not expose `last_analyze`, but page growth since the last ANALYZE is 0–4.5% per key table (§0), and v3 ratios are staleness-adjusted. The remaining uncertainty is page reuse (e.g. `order_line` +0.00%).
11. Is youpay one row per order or one per payment attempt (P25)? Which row is canonical: latest `approved=true` per `order_reference`?
12. Where are refunds and cancellations recorded (`ygag_youpay_db`? finance?), and do any status values encode them (P26)?
13. Which system owns acquisition attribution, and which order key does it capture (`number`, `order_reference`, `session_id`)?
14. Is `kafka_giftcreationlog` one event per gift unit, or does it contain retries or duplicates (P29)? Does `created_gift_details` contain gift codes (if so, it must never be granted)?
15. Which `created_by_id` users are service/API accounts vs staff (P30)? Does that separate @Work orders?

## 12. Grant request (consolidated, v4)

**Status: BLOCKED.** `<emapi_login_role>` has SELECT on 0 of 1,500 columns in this DB (Q28). Everything below is a request to the DBA; nothing in it has been granted. Grants must be run on the **primary**; they replicate to the read replica the atlas uses.

**Always excluded (never granted as raw values):** `user`, `user_email`, `guest_email`, `user_name`, `user_phone`, `user_gender`, `owner`, `session_id`, `transaction_url`, `note`, `name_on_card`, `card_bin`, `card_last4`, `phone_number`, `email_address`, `sender_name`, `personal_data_ref`, `payload`, `partner_line_notes`, `partner_line_reference` (until Open Question 8 is answered), `created_gift_details`, `failure`, blacklist `value`/`reference_id`, `brand_calculations`/`brand_details`, `customer_email`, `customer_name`, `customer_ip_address`, `points_*_mobile_number`, `*_url`, `extra`/`order_history`/`order_items`/`udf1`/`data`/`personalization_data` jsonb (expose only extracted keys). v4 adds: `users_customuser.password/first_name/last_name/email/username`; `users_guestuser.email/username/session_id/db_session_id/extra/note`; `django_admin_log.object_repr/change_message`; `user_tip_tip.receiver_phone_number/extra`; `user_tip_invoice.card_last4`; `offer_offerpromocode.promo_code`. Where the atlas needs to know whether such a column is populated, or which keys a jsonb holds, Option A exposes a **derived** boolean, key list or extracted key instead. **No hashes of identifiers are proposed:** the DB has no `pgcrypto` (only `pg_stat_statements` and `plpgsql` are installed, Q32), and an unsalted `md5(email)` is reversible by dictionary. A salt placed in a view definition is readable by anyone through `pg_get_viewdef`.

**Column-level privileges fail closed.** Under Option B, any query that names a single ungranted column fails with `permission denied` as a whole. §12.4 therefore marks each prepared query **B** (runs on the column grants alone) or **A** (needs a §12.2 view); several queries have a B variant and an A variant.

### 12.1 Option B: column grants (minimum ask)
```sql
-- Option B: table grants on non-PII tables + column grants on PII-bearing ones
GRANT SELECT ON public.order_orderstatuschange, public.order_lineprice, public.order_orderplacedcountry,
  public.order_giftactivationconfig, public.order_giftactivationconfig_enabled_country,
  public.basket_mergedbasket, public.payment_paymentmethod, public.address_country, public.address_countryvat,
  public.core_currencybasketlimit, public.core_unsupportedcountry, public.offer_plusoffer,
  public.offer_plusoffer_happy_cards TO <emapi_login_role>;
-- Option B column-level grants (v3). Generated from pg_attribute (Q27, exact, 318 columns across 12 tables).
-- Column lists are complete as of 2026-09-29. A new column added later is NOT granted automatically (fail-closed).
-- Note: response_summary (youpay decline reason, varchar 500) IS granted because the decline mix needs it;
--   review the first P20 sample for echoed card/customer data and revoke if any appears.
-- basket_basket: 20 columns, 13 granted; EXCLUDED: user, extra, user_email, user_gender, user_name, user_phone, note
GRANT SELECT (id, status, date_created, date_merged, date_submitted, owner_id, region_id, parent_id, platform, record_type, language_code, guest_id, language_id)
  ON public.basket_basket TO <emapi_login_role>;
-- basket_basketpersonalisedetail: 15 columns, 13 granted; EXCLUDED: phone_number, email_address
GRANT SELECT (id, created_on, modified_on, delivery_type, delivery_date, delivery_time, line_id, delivery_time_zone, created_by_id, modified_by_id, greeting_code, occasion_code, is_reminder_added)
  ON public.basket_basketpersonalisedetail TO <emapi_login_role>;
-- basket_basketquantitydetail: 13 columns, 11 granted; EXCLUDED: personal_data_ref, sender_name
GRANT SELECT (id, created_on, modified_on, is_buy_for_self, denomination, denomination_currency_id, line_id, created_by_id, modified_by_id, delivery_method, brand_skin)
  ON public.basket_basketquantitydetail TO <emapi_login_role>;
-- basket_line: 16 columns, 16 granted; EXCLUDED: none
GRANT SELECT (id, line_reference, quantity, price_currency, price_excl_tax, price_incl_tax, date_created, basket_id, product_id, stockrecord_id, date_updated, parent_id, record_type, tax_code, purchase_origin, is_white_label)
  ON public.basket_line TO <emapi_login_role>;
-- kafka_giftcreationlog: 10 columns, 7 granted; EXCLUDED: payload, failure, created_gift_details
GRANT SELECT (id, created_on, modified_on, event_id, status, error, order_id)
  ON public.kafka_giftcreationlog TO <emapi_login_role>;
-- order_line: 31 columns, 29 granted; EXCLUDED: partner_line_reference, partner_line_notes
GRANT SELECT (id, partner_name, partner_sku, title, upc, quantity, line_price_incl_tax, line_price_excl_tax, line_price_before_discounts_incl_tax, line_price_before_discounts_excl_tax, unit_price_incl_tax, unit_price_excl_tax, status, order_id, partner_id, product_id, stockrecord_id, created_by_id, created_on, line_reference, modified_by_id, modified_on, instant_activated_date, is_instant_activated, tax_code, is_offer_applied, offer_code, purchase_origin, is_white_label)
  ON public.order_line TO <emapi_login_role>;
-- order_order: 63 columns, 54 granted; EXCLUDED: guest_email, extra, owner, transaction_url, user_email, user_gender, user_name, user_phone, session_id
GRANT SELECT (id, number, currency, total_incl_tax, total_excl_tax, shipping_incl_tax, shipping_excl_tax, shipping_method, shipping_code, status, date_placed, basket_id, billing_address_id, shipping_address_id, site_id, user_id, gateway_currency, is_visited, order_reference, platform, region_id, total_base_amount, total_base_amount_in_gateway_currency, total_extra_charge, total_extra_charge_in_gateway_currency, total_incl_tax_in_gateway_currency, total_tax_amount, total_tax_in_gateway_currency, created_by_id, date_updated, modified_by_id, language_code, transaction_id, process_fee, process_fee_in_gateway_currency, quantity, vat_on_process_fee_in_gateway_currency, placed_country_id, payment_order_reference, total_incl_tax_before_payment, total_incl_tax_in_gateway_currency_before_payment, total_tax_amount_before_payment, total_tax_in_gateway_currency_before_payment, gift_create_event_triggered, conversion_rate_gateway_currency, conversion_rate_reporting_currency, total_incl_tax_before_payment_in_reporting_currency, total_extra_charge_before_payment, total_extra_charge_in_gateway_currency_before_pay, guest_id, sold_date, shipping_tax_code, language_id, redemption_partner)
  ON public.order_order TO <emapi_login_role>;
-- order_orderlinepersonalisedetail: 15 columns, 13 granted; EXCLUDED: phone_number, email_address
GRANT SELECT (id, created_on, modified_on, delivery_time_zone, delivery_type, delivery_date, delivery_time, created_by_id, line_id, modified_by_id, greeting_code, occasion_code, is_reminder_added)
  ON public.order_orderlinepersonalisedetail TO <emapi_login_role>;
-- order_orderlinequantitydetail: 38 columns, 36 granted; EXCLUDED: personal_data_ref, sender_name
GRANT SELECT (id, created_on, modified_on, denomination_currency_id, line_id, created_by_id, denomination_in_cart_currency, denomination_in_denomination_currency, denomination_in_reporting_currency, extra_charge_in_cart_currency, extra_charge_in_denomination_currency, extra_charge_in_reporting_currency, is_buy_for_self, is_different_currency_denomination, modified_by_id, price_in_cart_currency, price_in_denomination_currency, price_in_reporting_currency, reporting_currency, tax_rate_in_cart_currency, tax_rate_in_denomination_currency, tax_rate_in_reporting_currency, conversion_rate, payment_gateway_charge, conversion_rate_cart_currency, delivery_method, extra_charge_in_denomination_currency_before_pay, price_in_denomination_currency_before_pay, tax_rate_in_denomination_currency_before_pay, brand_skin, processing_fee_rate, processing_fee_vat_in_cart_currency, processing_fee_vat_in_reporting_currency, processing_fee_vat_rate, processing_fee_in_cart_currency, processing_fee_in_reporting_currency)
  ON public.order_orderlinequantitydetail TO <emapi_login_role>;
-- payment_paymentdetail: 26 columns, 22 granted; EXCLUDED: card_bin, card_last4, name_on_card, brand_calculations
GRANT SELECT (id, created_on, modified_on, payment_gateway, currency, is_fraud, is_flagged, payment_method, payment_scheme, is_gcc_card, processing_fee, card_issuer_country, paid_amount, created_by_id, modified_by_id, order_id, gateway_charge, payment_status, settlement_entity, exclude_instant_activation, point_collection_enabled, point_program)
  ON public.payment_paymentdetail TO <emapi_login_role>;
-- payment_paymenttransactionpayload: 7 columns, 6 granted; EXCLUDED: payload
GRANT SELECT (id, created_on, modified_on, "order", created_by_id, modified_by_id)
  ON public.payment_paymenttransactionpayload TO <emapi_login_role>;
-- youpayclient_youpayclienttransactiondata: 64 columns, 46 granted; EXCLUDED: customer_ip_address, customer_email, card_bin, card_last4, cancel_url, customer_name, failure_url, name_on_card, order_history, order_items, session_id, success_url, verify_url, brand_calculations, brand_details, points_collected_mobile_number, points_redeemed_mobile_number, udf1
GRANT SELECT (id, created_on, modified_on, transaction_id, payment_reference, order_reference, invoice_id, amount, currency, service_fee, base_amount, vat_amount, payment_gateway, payment_status, channel_code, is_fraud, is_flagged, payment_method, payment_scheme, is_gcc_card, card_issuer_country, platform, approved, response_summary, available_amount, available_points, is_full_redemption, payable_amount, redeemed_amount, redeemed_points, "cart_VAT_amount", cart_amount, cart_base_amount, cart_currency, cart_service_fee, language, loyalty_level, processing_fee, paid_amount, gateway_charge, settlement_entity, earned_point, is_qitaf_enabled, qitaf_request_id, point_collection_enabled, point_program)
  ON public.youpayclient_youpayclienttransactiondata TO <emapi_login_role>;
-- adjacent friction / FX / identity tables (v3). No PII columns, so table-level grants:
GRANT SELECT ON public.catalogue_productdenominationrange, public.catalogue_producthandlingfee,
  public.core_currencyexchangerate, public.core_currency, public.users_mergeduser TO <emapi_login_role>;
-- users_blacklisteduserdetail: 11 columns, 9 granted; EXCLUDED: value (blocked identifier = PII), reference_id
GRANT SELECT (id, created_on, modified_on, type, created_by_id, modified_by_id, is_removed, source, is_guest)
  ON public.users_blacklisteduserdetail TO <emapi_login_role>;
-- users_cognitouserdatasynclog: 6 columns, 4 granted; EXCLUDED: payload (identity attributes), error (jsonb; grant after a DBA review of its keys)
GRANT SELECT (id, created_on, modified_on, status)
  ON public.users_cognitouserdatasynclog TO <emapi_login_role>;
-- kafka offer/@Work/personalisation logs: status + timestamps only (data/error_data after review)
GRANT SELECT (id, status, start_timestamp, completed_timestamp) ON public.kafka_atworkkafkadatalog TO <emapi_login_role>;
GRANT SELECT (id, status, start_timestamp, completed_timestamp) ON public.kafka_plusofferkafkadatalog TO <emapi_login_role>;
GRANT SELECT (id, status, start_timestamp, completed_timestamp) ON public.personalization_update_kafka_data_log TO <emapi_login_role>;
-- v4 additions: tables the prepared queries P23, P30, P33-P36 need (column lists from Q31, exact)
-- users_customuser: 11 columns, 6 granted; EXCLUDED: password, first_name, last_name, email, username
GRANT SELECT (id, last_login, date_joined, is_active, is_staff, is_superuser) ON public.users_customuser TO <emapi_login_role>;
-- users_guestuser: 12 columns, 6 granted; EXCLUDED: email, username, session_id, db_session_id, extra, note
GRANT SELECT (id, created_on, modified_on, platform, last_accessed, is_active) ON public.users_guestuser TO <emapi_login_role>;
-- django_admin_log: 8 columns, 6 granted; EXCLUDED: object_repr (object's string form, can be an email/name), change_message
GRANT SELECT (id, action_time, object_id, action_flag, content_type_id, user_id) ON public.django_admin_log TO <emapi_login_role>;
GRANT SELECT ON public.django_content_type TO <emapi_login_role>;          -- 150 rows: app_label, model
-- user_tip_tip: 16 columns, 14 granted; EXCLUDED: receiver_phone_number, extra
GRANT SELECT (id, created_on, modified_on, platform, status, reference_id, amount, amount_in_aed, created_by_id, currency_id, modified_by_id, sender_id, language, send_tip_gift_event_triggered)
  ON public.user_tip_tip TO <emapi_login_role>;
-- user_tip_invoice: 14 columns, 13 granted; EXCLUDED: card_last4
GRANT SELECT (id, created_on, modified_on, reference_id, object_id, state, amount, service_charge, vat_amount, is_flagged_email_sent, payment_method, content_type_id, currency_id)
  ON public.user_tip_invoice TO <emapi_login_role>;
-- offer_offerpromocode: 9 columns, 8 granted; EXCLUDED: promo_code
GRANT SELECT (id, created_on, modified_on, status, brand_id, created_by_id, modified_by_id, offer_id) ON public.offer_offerpromocode TO <emapi_login_role>;
-- catalogue_productdenomination: no PII (amount, gencode, is_default, is_active, order_number, product/currency ids)
GRANT SELECT ON public.catalogue_productdenomination TO <emapi_login_role>;
```
That covers the 20 populated in-scope tables (10 with column grants, 9 with table grants, plus `payment_logentrydata`, which is deliberately excluded because it is an admin audit trail) and the adjacent ledger, gift, offer, B2B and friction tables. v4 adds the identity, admin-history, tipping, promo-code and denomination tables above.

### 12.2 Option A: PII-free views with derived columns (preferred)
Each view selects the Option B column list of its table **plus** the derived columns below. The raw PII/jsonb columns never leave the view. Views run with the owner's privileges, so the derived expressions can read columns the atlas role cannot. **`TABLESAMPLE` does not apply to views**, so A-variant queries bound themselves by the latest N rows of the indexed primary key (`WHERE id >= (SELECT max(id) - N FROM view)`). That is a recency window, not a random sample; say so when reporting.
```sql
CREATE SCHEMA atlas_ro; GRANT USAGE ON SCHEMA atlas_ro TO <emapi_login_role>;

-- PII presence flags (the columns are NOT NULL but may be empty strings, §2.2)
CREATE VIEW atlas_ro.order_order AS SELECT <54 Option B columns>,
  (user_email <> '') has_user_email, (guest_email <> '') has_guest_email, (user_name <> '') has_user_name,
  (user_phone <> '') has_user_phone, (owner <> '') has_owner, (session_id IS NOT NULL AND session_id <> '') has_session_id,
  (transaction_url IS NOT NULL AND transaction_url <> '') has_transaction_url, (user_gender IS NOT NULL AND user_gender <> '') has_user_gender,
  CASE WHEN jsonb_typeof(extra)='object' THEN ARRAY(SELECT jsonb_object_keys(extra) ORDER BY 1) END extra_keys   -- key names only (P13c)
FROM public.order_order;
CREATE VIEW atlas_ro.basket_basket AS SELECT <13 Option B columns>,
  ("user" IS NOT NULL AND "user" <> '') has_user, (user_email <> '') has_user_email, (user_phone <> '') has_user_phone,
  (user_name <> '') has_user_name, (note IS NOT NULL AND note <> '') has_note,
  CASE WHEN jsonb_typeof(extra)='object' THEN ARRAY(SELECT jsonb_object_keys(extra) ORDER BY 1) END extra_keys
FROM public.basket_basket;
CREATE VIEW atlas_ro.order_orderlinepersonalisedetail AS SELECT <13 Option B columns>,
  (phone_number IS NOT NULL AND phone_number <> '') has_recipient_phone, (email_address IS NOT NULL AND email_address <> '') has_recipient_email
FROM public.order_orderlinepersonalisedetail;          -- same shape for atlas_ro.basket_basketpersonalisedetail
CREATE VIEW atlas_ro.order_orderlinequantitydetail AS SELECT <36 Option B columns>,
  (sender_name IS NOT NULL AND sender_name <> '') has_sender_name, (personal_data_ref IS NOT NULL AND personal_data_ref <> '') has_personal_data_ref
FROM public.order_orderlinequantitydetail;             -- same shape for atlas_ro.basket_basketquantitydetail
CREATE VIEW atlas_ro.order_line AS SELECT <29 Option B columns>,
  (partner_line_reference <> '') has_partner_line_reference, (partner_line_notes <> '') has_partner_line_notes,
  length(partner_line_notes) partner_line_notes_len    -- length only, never content (Open Question 8)
FROM public.order_line;
-- youpay: attempt count without exposing the history
CREATE VIEW atlas_ro.youpay_transaction AS SELECT <46 Option B columns>,
  CASE WHEN jsonb_typeof(order_history)='array' THEN jsonb_array_length(order_history) END order_history_len,
  CASE WHEN jsonb_typeof(order_history)='object' THEN ARRAY(SELECT jsonb_object_keys(order_history) ORDER BY 1) END order_history_keys
FROM public.youpayclient_youpayclienttransactiondata;
-- gift issuance: presence flags for the secret-class text columns (P29)
CREATE VIEW atlas_ro.kafka_giftcreationlog AS SELECT id, created_on, modified_on, event_id, status, error, order_id,
  (failure IS NOT NULL AND failure <> '') has_failure, (created_gift_details IS NOT NULL AND created_gift_details <> '') has_created_gift_details
FROM public.kafka_giftcreationlog;
-- kafka sync logs have NO key column (Q31): expose error presence, the key NAMES in data, and candidate extracted keys.
-- Step 1: DBA runs the key histogram (P22-A step 1) and confirms which key names exist and hold order/offer references, not PII.
-- Step 2: the view extracts only those keys. The names below are candidates to be confirmed, not known keys.
CREATE VIEW atlas_ro.kafka_atworkkafkadatalog AS SELECT id, status, start_timestamp, completed_timestamp,
  (error_data <> '') has_error,                                           -- error text itself not exposed
  CASE WHEN jsonb_typeof(data)='object' THEN ARRAY(SELECT jsonb_object_keys(data) ORDER BY 1) END data_keys,
  data->>'order_reference' order_reference, data->>'order_number' order_number, data->>'order_id' order_id,
  data->>'company_id' company_id, data->>'record_type' record_type
FROM public.kafka_atworkkafkadatalog;
CREATE VIEW atlas_ro.kafka_plusofferkafkadatalog AS SELECT id, status, start_timestamp, completed_timestamp,
  (error_data <> '') has_error,
  CASE WHEN jsonb_typeof(data)='object' THEN ARRAY(SELECT jsonb_object_keys(data) ORDER BY 1) END data_keys,
  data->>'code' offer_code, data->>'id' offer_id, data->>'offer_type' offer_type
FROM public.kafka_plusofferkafkadatalog;               -- same shape for kafka_productofferkafkadatalog
CREATE VIEW atlas_ro.personalization_update_kafka_data_log AS SELECT id, status, start_timestamp, completed_timestamp,
  (error_data <> '') has_error,
  CASE WHEN jsonb_typeof(data)='object' THEN ARRAY(SELECT jsonb_object_keys(data) ORDER BY 1) END data_keys,
  data->>'personalization_reference_id' personalization_reference_id, data->>'order_reference' order_reference
FROM public.personalization_update_kafka_data_log;
-- identity sync: error presence and error key names, never payload/error values (P31)
CREATE VIEW atlas_ro.users_cognitouserdatasynclog AS SELECT id, created_on, modified_on, status,
  (jsonb_typeof(error)='object' AND error <> '{}'::jsonb) OR (jsonb_typeof(error)='array' AND jsonb_array_length(error) > 0)
    OR (jsonb_typeof(error)='string' AND error #>> '{}' <> '') has_error,
  CASE WHEN jsonb_typeof(error)='object' THEN ARRAY(SELECT jsonb_object_keys(error) ORDER BY 1) END error_keys
FROM public.users_cognitouserdatasynclog;
-- tables with no PII columns or with only excluded columns: views = the Option B column lists of §12.1 unchanged
GRANT SELECT ON ALL TABLES IN SCHEMA atlas_ro TO <emapi_login_role>;
```
Extracted keys such as `data->>'order_reference'` are business references, not PII, **only if** step 1 confirms it. Any extracted key that turns out to hold an email or phone is removed before the grant.

### 12.3 Index / extract asks
- youpay: `(order_reference)` and `(created_on)` indexes on the primary, or a nightly extract. Today every youpay↔order join and time-bounded youpay query is a 2 GB seq scan (§2.3).
- `kafka_giftcreationlog`: `(order_id)` and `(created_on)`; 3.26M rows, only pkey and `event_id` are indexed (Q25).
- `kafka_atworkkafkadatalog` (1.7M): `(start_timestamp)`, or an expression index on the confirmed order key in `data`.
- `basket_basket`: `(date_created)`; 3.05M rows, no date or status index, 0 reads on the replica today.
- Alternatively, one nightly extract of the §12.2 views to the atlas store removes all of these from the replica.

### 12.4 Prepared query ↔ grant matrix
| Runs under | Prepared queries |
|---|---|
| **Option B** (column grants in §12.1, including the v4 additions) | P1, P2, P3, P4, P5, P6, P7, P8, P8b, **P8c (v4 join)**, P9, P10, P11, P12, P13, P13b, P14, P15, P15b, P15c, P16, P17, P18, P19, P20, P20b, **P21 (status/latency variant)**, **P22a, P22c (status variants)**, **P23 (needs the v4 user_tip_* / offer_offerpromocode grants)**, P24a–d, P25, P26, P27a, P27b, P27c, P28, **P29 (B variant: no `failure` test)**, **P30 (needs the v4 users_customuser grant)**, **P31 (B variant: status × month only)**, P32, P33, P34, P35, P36 |
| **Option A only** (a §12.2 view) | **P13c** (`extra_keys`), **P21-A** (`has_error`, extracted offer key), **P22b / P22-A** (atwork `data_keys`, extracted order key: the only way to test the @Work mapping), **P29-A** (`has_failure`, `has_created_gift_details`), **P31-A** (`has_error`, `error_keys`), **P37** (PII-presence flags), youpay attempt count (`order_history_len`, P25-A) |
| **Rewritten in v4 because v3 would fail under B** | P13c (was `jsonb_object_keys(extra)` on `public.order_order`), P21/P22 (tested `error_data`, read `data`), P29 (tested `failure`), P31 (read `error`), P23 (no grant existed), P30 (no users_customuser grant existed) |

## Appendix: SQL provenance

All from `atlasq.sh ygag_ecom_orders_db` on 2026-09-29. v2 re-ran Q6, Q13 and Q3-note, and added Q15–Q19. v3 added Q19b–Q27 (staleness, constraints, attribution/refund searches, adjacent friction tables, grant column lists) and P15b/P15c, the P24b rewrite and P25–P32. v4 re-ran Q20 with the personalisation, kafka, identity and admin tables, added Q28–Q32 (column privileges, exact-empty heaps, line_reference constraints, v4 adjacent-table columns/indexes/FKs, extensions), rewrote P8c, P13c, P21, P22, P29, P30 and P31 so each has a variant that runs under Option B, and added P25-A and P33–P37. All Q-queries are catalog-only, so their results are STRUCTURAL; no P-query has run.

- **Q1: in-scope tables, reltuples, size** (every row estimate in §2/§6/§7)
```sql
SELECT c.relname, c.reltuples::bigint est, pg_total_relation_size(c.oid)/1024/1024 mb
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname='public' AND c.relkind='r' AND (c.relname ~ '^(order|basket|payment|voucher|shipping|address)') ORDER BY 1;
```
- **Q2: PK/FK/UNIQUE in scope**
```sql
SELECT conrelid::regclass t, contype, pg_get_constraintdef(oid) def FROM pg_constraint
WHERE connamespace='public'::regnamespace AND contype IN ('p','f','u')
AND conrelid::regclass::text ~ '^(order|basket|payment|voucher|shipping|address)' ORDER BY 1,2;
```
- **Q3: columns** via pg_attribute. `information_schema.columns` returns **0 rows for in-scope tables**; it returns 45 rows overall (43 for `pg_stat_statements`, 2 for `pg_stat_statements_info`), because it only shows relations the role can access (Q3-note, re-run v2).
```sql
SELECT c.relname t, a.attname col, format_type(a.atttypid,a.atttypmod) typ, a.attnotnull nn
FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
WHERE c.relnamespace='public'::regnamespace AND c.relkind='r' AND a.attnum>0 AND NOT a.attisdropped AND c.relname IN (...)
ORDER BY c.relname, a.attnum;
-- Q3-note: SELECT table_name, count(*) FROM information_schema.columns WHERE table_schema NOT IN ('pg_catalog','information_schema') GROUP BY 1;
-- Q3c (v2): same pg_attribute query for order_order ~ '(shipping|billing|guest)', order_line ~ '(partner_line|offer)',
--   order_orderlinequantitydetail ~ 'fee', and adjacent tables (youpay, kafka_*datalog, offer_*, personalization_*, core_*, user_tip_*, reviews_googlereview)
```
- **Q3b: indexes**: `SELECT tablename, indexname, indexdef FROM pg_indexes WHERE schemaname='public' AND tablename IN ('order_order','order_line','order_orderstatuschange','kafka_giftcreationlog','user_tip_tip','user_tip_invoice','offer_offerpromocode',...);`
- **Q4: replica activity** (v1; superseded by Q16)
- **Q5: data access attempts** (all failed: `permission denied`): `SELECT status, count(*) FROM order_order GROUP BY 1;` etc.
- **Q6: privilege check** (v2: public 161 relations, 2 readable, both pg_stat_statements views)
```sql
SELECT n.nspname, count(*) tables, count(*) FILTER (WHERE has_table_privilege(c.oid,'SELECT')) readable
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE c.relkind IN ('r','v','m') AND n.nspname NOT IN ('pg_catalog','information_schema') GROUP BY n.nspname;
SELECT c.relname FROM pg_class c WHERE c.relnamespace='public'::regnamespace AND c.relkind IN ('r','v','m') AND has_table_privilege(c.oid,'SELECT');
```
- **Q7: CHECK constraints**, **Q8: defaults/comments** (0 rows each), as in v1.
- **Q9: sizes and per-row width** (v2)
```sql
SELECT c.relname, c.reltuples::bigint est, pg_relation_size(c.oid)/1048576 heap_mb, pg_total_relation_size(c.oid)/1048576 total_mb,
 round(pg_relation_size(c.oid)/c.reltuples) heap_bytes_per_row, round(pg_total_relation_size(c.oid)/c.reltuples) total_bytes_per_row,
 pg_total_relation_size(c.reltoastrelid)/1048576 toast_mb
FROM pg_class c WHERE c.relnamespace='public'::regnamespace AND c.relname IN ('order_order','basket_basket','basket_line','order_line','order_orderstatuschange','payment_paymentdetail','youpayclient_youpayclienttransactiondata','kafka_atworkkafkadatalog','kafka_plusofferkafkadatalog');
-- Q9b: to_char(last_seq_scan,'YYYY"y"MM"m"DD"d"') from pg_stat_user_tables
```
- **Q10: pg_stat_statements totals** (cluster-wide: 4,897 entries, 420,026,587 calls, 4,877 hidden, 3 users, 6 DBs)
```sql
SELECT count(*), sum(calls), sum(rows), round(sum(total_exec_time)/1000), count(*) FILTER (WHERE query='<insufficient privilege>'), count(DISTINCT userid), count(DISTINCT dbid) FROM pg_stat_statements;
SELECT dealloc, to_char(stats_reset,'YYYY"y"MM"m"DD"d"') FROM pg_stat_statements_info;   -- 662,982 / 2026-06-26
```
- **Q11: sequences** → last_value NULL. **Q12: pg_stats** → 0 rows.
- **Q13: inbound FKs from outside scope** (v2 corrected: 5 rows, all `country_id → address_country(iso_3166_1_a2)`)
```sql
SELECT conrelid::regclass src, confrelid::regclass tgt, pg_get_constraintdef(oid) FROM pg_constraint
WHERE contype='f' AND connamespace='public'::regnamespace
AND confrelid::regclass::text ~ '^(order|basket|payment|voucher|shipping|address)_'
AND conrelid::regclass::text !~ '^(order|basket|payment|voucher|shipping|address)_';
```
- **Q14: out-of-scope reltuples** (youpay 1,229,851; kafka_giftcreationlog 3,134,464; webhooks 5.2k), as in v1; v2 adjacent tables:
```sql
SELECT c.relname, c.reltuples::bigint, pg_total_relation_size(c.oid)/1048576 mb, s.seq_scan, s.idx_scan
FROM pg_class c LEFT JOIN pg_stat_user_tables s ON s.relid=c.oid WHERE c.relnamespace='public'::regnamespace AND c.relkind='r'
AND c.relname ~ '^(kafka_|personalization|core_currencybasketlimit|core_unsupportedcountry|offer_|user_tip|reviews_|youpay)';
```
- **Q15: scope counts** (order_ 23, basket_ 7, payment_ 8, voucher_ 4, shipping_ 5, address_ 3)
```sql
SELECT count(*) FILTER (WHERE relname ~ '^order_'), count(*) FILTER (WHERE relname ~ '^basket_'), ... FROM pg_class WHERE relnamespace='public'::regnamespace AND relkind='r';
```
- **Q16: replica scan counters and recency** (exact)
```sql
SELECT relname, seq_scan, idx_scan, to_char(last_seq_scan,'YYYY"y"MM"m"DD"d"'), to_char(last_idx_scan,'YYYY"y"MM"m"DD"d"')
FROM pg_stat_user_tables WHERE relname IN ('basket_basket','basket_line','basket_basketquantitydetail','basket_basketpersonalisedetail','order_orderstatuschange','youpayclient_youpayclienttransactiondata','address_country','core_currencybasketlimit','offer_plusoffer','offer_offerpromocode','kafka_giftcreationlog','payment_paymentmethod');
```
- **Q17: offer/config constraints**: `SELECT conrelid::regclass, contype, pg_get_constraintdef(oid) FROM pg_constraint WHERE contype IN ('u','f') AND conrelid::regclass::text IN ('offer_plusoffer','offer_offerpromocode','offer_plusoffer_happy_cards','core_currencybasketlimit','user_tip_tip','user_tip_invoice','personalization_detail');`
- **Q18: adjacent-table indexes**: `SELECT tablename, indexname, indexdef FROM pg_indexes WHERE schemaname='public' AND (indexname ~ '_[0-9a-f]{6}_idx$' OR tablename IN ('youpayclient_youpayclienttransactiondata','kafka_atworkkafkadatalog','kafka_plusofferkafkadatalog','personalization_detail','core_currencybasketlimit','core_unsupportedcountry'));`
- **Q19: workload per DB** (orders DB: 19 entries, 1,857,904 calls, 185 s)
```sql
SELECT d.datname, count(*), sum(s.calls), sum(s.rows), round(sum(s.total_exec_time)/1000) FROM pg_stat_statements s LEFT JOIN pg_database d ON d.oid=s.dbid GROUP BY 1 ORDER BY 3 DESC;
SELECT s.calls, s.rows, round(s.mean_exec_time::numeric,2), round(s.rows::numeric/nullif(s.calls,0),1), round(s.shared_blks_hit::numeric/nullif(s.calls,0))
FROM pg_stat_statements s JOIN pg_database d ON d.oid=s.dbid WHERE d.datname='ygag_ecom_orders_db' ORDER BY s.calls DESC;
```

- **Q19b: workload snapshot re-read (v3, point-in-time)**: orders DB 20 entries / 1,858,725 calls; cluster 4,967 entries / 420,183,496 calls; dealloc 663,184
```sql
SELECT d.datname, count(*), sum(s.calls) FROM pg_stat_statements s LEFT JOIN pg_database d ON d.oid=s.dbid WHERE d.datname='ygag_ecom_orders_db' GROUP BY 1;
SELECT dealloc, to_char(stats_reset,'YYYY"y"MM"m"DD"d"'), (SELECT count(*) FROM pg_stat_statements), (SELECT sum(calls) FROM pg_stat_statements) FROM pg_stat_statements_info;
```
- **Q20: staleness / extrapolated counts (v3)** (every "extrap." number and growth %). `last_analyze`, `last_autoanalyze`, `n_live_tup` and `n_dead_tup` come back NULL/0 on the replica.
```sql
SELECT c.relname, c.reltuples::bigint est, c.relpages, (pg_relation_size(c.oid)/8192)::bigint cur_pages,
 round(((pg_relation_size(c.oid)/8192.0)/nullif(c.relpages,0))::numeric,4) growth,
 round((c.reltuples*(pg_relation_size(c.oid)/8192.0)/nullif(c.relpages,0))::numeric) extrap,
 s.n_live_tup, s.n_dead_tup, s.n_mod_since_analyze, to_char(greatest(s.last_analyze,s.last_autoanalyze),'YYYY"y"MM"m"DD"d"')
FROM pg_class c LEFT JOIN pg_stat_user_tables s ON s.relid=c.oid
WHERE c.relnamespace='public'::regnamespace AND c.relname IN ('order_order','order_line','order_orderstatuschange','order_orderlinequantitydetail',
 'order_orderlinepersonalisedetail','order_lineprice','basket_basket','basket_line','basket_basketquantitydetail','basket_basketpersonalisedetail',
 'payment_paymentdetail','youpayclient_youpayclienttransactiondata','kafka_giftcreationlog','users_blacklisteduserdetail',
 'catalogue_productdenominationrange','catalogue_producthandlingfee','core_currencyexchangerate','users_mergeduser','users_cognitouserdatasynclog','payment_paymenttransactionpayload',
 -- v4 additions:
 'personalization_update_kafka_data_log','personalization_detail','kafka_atworkkafkadatalog','kafka_plusofferkafkadatalog','kafka_productofferkafkadatalog',
 'django_admin_log','django_content_type','users_guestuser','users_customuser','user_tip_tip','user_tip_invoice','offer_offerpromocode','catalogue_productdenomination');
```
  Results (est. → extrap., growth): order_order 1,232,173 → 1,233,955 (1.0014); order_orderstatuschange 1,157,239 → 1,209,722 (1.0454); youpay 1,229,851 → 1,238,225 (1.0068); kafka_giftcreationlog 3,134,464 → 3,256,033 (1.0388); basket_basket 3,041,571 → 3,046,354 (1.0016); basket_line 1,789,338 → 1,824,296 (1.0195); order_line 1,473,029 → 1,473,029 (1.0000); order_lineprice 1,427,052 → 1,482,841 (1.0391); order_orderlinequantitydetail 1,474,250 → 1,480,661 (1.0043); order_orderlinepersonalisedetail 496,737 → 513,374 (1.0335); basket_basketquantitydetail 1,783,453 (1.0000); basket_basketpersonalisedetail 553,383 → 557,973 (1.0083); payment_paymentdetail 761,949 → 769,659 (1.0101); catalogue_producthandlingfee 939 → 991 (1.0556); users_blacklisteduserdetail 48,646, catalogue_productdenominationrange 11,376, core_currencyexchangerate 437, users_cognitouserdatasynclog 93,871, payment_paymenttransactionpayload 65,123 (all 1.0000); users_mergeduser never analyzed (33 pages). **v4 additions:** personalization_update_kafka_data_log **128,996** (29,005 = 29,005 pages, 1.0000; replaces v3's 139,132, read before a re-ANALYZE); personalization_detail 94,394 (1.0000); kafka_atworkkafkadatalog 1,700,549 (1.0000); kafka_plusofferkafkadatalog 201,682 → 203,047 (2,217 → 2,232 pages, 1.0068); kafka_productofferkafkadatalog 767 (1.0000); django_admin_log 2,608 → 2,742 (39 → 41 pages, 1.0513); django_content_type 150; users_guestuser 82,502 (1.0000, 41 MB heap); users_customuser 991,558 → 996,517 (13,798 → 13,867 pages, 1.0050; 108 MB heap); offer_offerpromocode 41; catalogue_productdenomination 22,404 (1.0000); user_tip_tip and user_tip_invoice never analyzed (-1; 42 and 15 pages).
- **Q21: constraints on adjacent tables (v3)**: youpay has **PRIMARY KEY (id) only**; kafka_giftcreationlog PK + UNIQUE(event_id); users_blacklisteduserdetail UNIQUE(type,value); catalogue_producthandlingfee UNIQUE(code); core_currencyexchangerate UNIQUE(foreign_currency_id, base_currency_id); FKs as listed in §3.
```sql
SELECT conrelid::regclass t, contype, pg_get_constraintdef(oid) FROM pg_constraint
WHERE connamespace='public'::regnamespace AND conrelid::regclass::text IN ('youpayclient_youpayclienttransactiondata','kafka_giftcreationlog',
 'users_blacklisteduserdetail','catalogue_productdenominationrange','catalogue_producthandlingfee','core_currencyexchangerate','users_mergeduser','users_cognitouserdatasynclog') ORDER BY 1,2;
```
- **Q22: attribution column search (v3)**: 25 matches, none an acquisition source (§6)
```sql
SELECT c.relname, a.attname, format_type(a.atttypid,a.atttypmod), c.reltuples::bigint FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
WHERE c.relnamespace='public'::regnamespace AND c.relkind='r' AND a.attnum>0 AND NOT a.attisdropped
AND a.attname ~* '(refer|utm|campaign|source|channel|affiliate|medium|acquisition|attribution|gclid|fbclid)' ORDER BY 1,2;
```
- **Q23: refund/cancel column and table search (v3)**: 3 matches: payment_source.amount_refunded (0 rows), customer_productalert.date_cancelled (0 rows), youpay cancel_url
```sql
SELECT c.relname, a.attname, format_type(a.atttypid,a.atttypmod), c.reltuples::bigint FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
WHERE c.relnamespace='public'::regnamespace AND c.relkind='r' AND a.attnum>0 AND NOT a.attisdropped
AND (a.attname ~* '(refund|cancel|revers|chargeback|void|reverted)' OR c.relname ~* '(refund|cancel|chargeback|revers)') ORDER BY 1,2;
```
- **Q24: order_order column count and NOT NULL PII (v3)**: 63 columns, 46 NOT NULL; NOT NULL: guest_email, user_email, user_name, user_phone, owner, extra, created_by_id
```sql
SELECT count(*), count(*) FILTER (WHERE a.attnotnull) FROM pg_attribute a WHERE a.attrelid='public.order_order'::regclass AND a.attnum>0 AND NOT a.attisdropped;
SELECT a.attname, format_type(a.atttypid,a.atttypmod), a.attnotnull FROM pg_attribute a WHERE a.attrelid='public.order_order'::regclass AND a.attnum>0 AND NOT a.attisdropped
AND (a.attname IN ('user_email','guest_email','user_name','user_phone','owner','user_gender','session_id','transaction_url','transaction_id','extra','created_by_id','modified_by_id','user_id','guest_id')
     OR format_type(a.atttypid,a.atttypmod) ~ 'character varying\((2[0-9][0-9]|[3-9][0-9][0-9])\)');
```
- **Q25: columns and indexes of adjacent friction/identity tables (v3)**: order_order has btree indexes on created_by_id and modified_by_id; kafka_giftcreationlog has only pkey + event_id (no order_id/created_on index)
```sql
SELECT c.relname, a.attname, format_type(a.atttypid,a.atttypmod), a.attnotnull FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
WHERE c.relnamespace='public'::regnamespace AND c.relkind='r' AND a.attnum>0 AND NOT a.attisdropped
AND c.relname IN ('kafka_giftcreationlog','users_blacklisteduserdetail','catalogue_productdenominationrange','catalogue_producthandlingfee','core_currencyexchangerate','users_mergeduser','users_cognitouserdatasynclog');
SELECT tablename, indexname, indexdef FROM pg_indexes WHERE schemaname='public' AND (tablename IN ('kafka_giftcreationlog','users_blacklisteduserdetail',
 'catalogue_productdenominationrange','catalogue_producthandlingfee','core_currencyexchangerate','users_mergeduser','users_cognitouserdatasynclog')
 OR (tablename='order_order' AND indexdef ~ '(created_by_id|modified_by_id)'));
```
- **Q26: offer mechanics columns (v3)**
```sql
SELECT a.attname, format_type(a.atttypid,a.atttypmod), a.attnotnull FROM pg_attribute a WHERE a.attrelid='public.offer_plusoffer'::regclass AND a.attnum>0 AND NOT a.attisdropped
AND a.attname ~ '(reason|promo|unique|generic|budget|exceed|start|end|status|active)';
```
- **Q27: full column lists for the §12.1 GRANT statements (v3; moved from §11.1 in v4)**: 318 rows, not truncated. The grant text was rendered from this output with the exclusion list in §12; the kafka log columns were confirmed by a separate `string_agg(attname)` query.
```sql
SELECT c.relname, a.attname, a.attnum FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
WHERE c.relnamespace='public'::regnamespace AND a.attnum>0 AND NOT a.attisdropped
AND c.relname IN ('order_order','order_line','order_orderlinequantitydetail','order_orderlinepersonalisedetail','basket_basket','basket_line',
 'basket_basketquantitydetail','basket_basketpersonalisedetail','payment_paymentdetail','payment_paymenttransactionpayload',
 'youpayclient_youpayclienttransactiondata','kafka_giftcreationlog') ORDER BY 1,3;
```

- **Q28: column-level privileges (v4)**: 1,500 columns, **0 readable**, 0 readable tables
```sql
SELECT count(*) cols, count(*) FILTER (WHERE has_column_privilege(c.oid,a.attnum,'SELECT')) readable_cols,
 count(DISTINCT c.oid) FILTER (WHERE has_table_privilege(c.oid,'SELECT')) readable_tables
FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid WHERE c.relnamespace='public'::regnamespace AND c.relkind='r' AND a.attnum>0 AND NOT a.attisdropped;
```
- **Q29: exact-empty in-scope tables (v4)**: 50 tables; 32 with reltuples ≤ 0; **30 with a 0-byte heap**. The two others are basket_mergedbasket (-1, 81,920 B) and payment_logentrydata (-1, 49,152 B).
```sql
SELECT c.relname, c.reltuples::bigint est, pg_relation_size(c.oid) heap_bytes FROM pg_class c
WHERE c.relnamespace='public'::regnamespace AND c.relkind='r' AND c.relname ~ '^(order|basket|payment|voucher|shipping|address)_'
AND (c.reltuples<=0 OR pg_relation_size(c.oid)=0) ORDER BY 3 DESC,1;
```
- **Q30: line_reference constraints and order_order key indexes (v4)**: basket_line `UNIQUE (basket_id, line_reference)` + non-unique btree on `line_reference`; order_line `UNIQUE (line_reference)`; order_order btree on `basket_id`, `date_placed`, `guest_id`, `user_id`
```sql
SELECT conrelid::regclass::text t, contype, pg_get_constraintdef(oid) FROM pg_constraint
WHERE connamespace='public'::regnamespace AND contype IN ('u','p') AND conrelid::regclass::text IN ('basket_line','order_line')
UNION ALL SELECT tablename, 'i', indexdef FROM pg_indexes WHERE schemaname='public' AND tablename IN ('basket_line','order_line') AND indexdef ~ 'line_reference';
SELECT indexdef FROM pg_indexes WHERE schemaname='public' AND tablename='order_order' AND indexdef ~ '\((user_id|guest_id|date_placed|basket_id)';
```
- **Q31: columns, indexes and FKs of the v4 adjacent tables**: the four kafka sync logs (atwork, plusoffer, productoffer, personalization_update) all have exactly `id, data jsonb NN, status varchar(20) NN, error_data text NN, start_timestamp NN, completed_timestamp` and only a pkey index; users_cognitouserdatasynclog `id, created_on, modified_on, payload jsonb NN, status varchar(10), error jsonb NN`; users_customuser, users_guestuser, django_admin_log, user_tip_tip, user_tip_invoice, offer_offerpromocode and catalogue_productdenomination column lists as in §6/§12.1; django_admin_log indexed on content_type_id, user_id; users_guestuser only pkey + UNIQUE(session_id); users_customuser only pkey + UNIQUE(email); catalogue_productdenomination FKs product_id → catalogue_product, currency_id → core_currency; basket_basketquantitydetail.denomination numeric(20,6)
```sql
SELECT c.relname, a.attnum, a.attname, format_type(a.atttypid,a.atttypmod), a.attnotnull FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
WHERE c.relnamespace='public'::regnamespace AND a.attnum>0 AND NOT a.attisdropped
AND c.relname IN ('kafka_atworkkafkadatalog','kafka_plusofferkafkadatalog','kafka_productofferkafkadatalog','personalization_update_kafka_data_log',
 'django_admin_log','users_guestuser','users_customuser','user_tip_tip','user_tip_invoice','offer_offerpromocode','catalogue_productdenomination','users_cognitouserdatasynclog','django_content_type') ORDER BY 1,2;
SELECT tablename, indexdef FROM pg_indexes WHERE schemaname='public' AND tablename IN (<same list>) ORDER BY 1,2;
SELECT conrelid::regclass, contype, pg_get_constraintdef(oid) FROM pg_constraint WHERE connamespace='public'::regnamespace AND contype IN ('f','u')
AND conrelid::regclass::text IN ('catalogue_productdenomination','django_admin_log','user_tip_tip','user_tip_invoice','users_guestuser','offer_offerpromocode');
```
- **Q32: installed extensions (v4)**: `pg_stat_statements` 1.10, `plpgsql` 1.0 (no pgcrypto): `SELECT extname, extversion FROM pg_extension;`

**Derived ratios (v3: extrapolated counts from Q20; the v2 raw-reltuples value is in brackets):**
- orders/baskets 1,233,955/3,046,354 = 40.5% [40.5%];
- paymentdetail/orders 769,659/1,233,955 = 62.4% [61.8%];
- youpay rows/orders 1,238,225/1,233,955 = 100.3% [99.8%]. **This is a row ratio, not coverage** (§2.3);
- statuschanges/orders 1,209,722/1,233,955 = 0.980, gap ≈ 24,233 [0.94, "≥75k", withdrawn];
- order_lines/orders 1.194 [1.195] (lower bound);
- basket_lines/baskets 0.599 [0.588];
- order_lines/basket_lines 80.7% [82.3%] (not a conversion rate, §7.2);
- personalised basket lines 557,973/1,824,296 = 30.6% [30.9%]; personalised order lines 513,374/1,473,029 = 34.9% [33.7%];
- lineprice/order_line 100.7% [96.9%] (order_line under-counted);
- gift-creation events/order 3,256,033/1,233,955 = 2.64 [2.54]; per order_line 2.21;
- personalization update log/detail 128,996/94,394 = **1.37** (extrap., both 0% page growth; Q20 v4). v3's 1.47 used a stale 139,132;
- order_order heap bytes/row 177,233×8192/1,233,955 = 1,177 [1,178];
- kafka_plusoffer TOAST share 1,455/1,477 = 98.5%.

### Prepared queries (run once SELECT is granted; all bounded)
- **P1:** `SELECT status, count(*) FROM order_order GROUP BY 1 ORDER BY 2 DESC;` (status index)
- **P2:** `SELECT old_status, new_status, count(*) FROM order_orderstatuschange WHERE date_created >= now()-interval '90 days' GROUP BY 1,2 ORDER BY 3 DESC;`
- **P3:** `SELECT status, count(*) FROM order_line TABLESAMPLE SYSTEM (1) GROUP BY 1;`
- **P4:** `SELECT status, platform, record_type, count(*) FROM basket_basket TABLESAMPLE SYSTEM (1) GROUP BY 1,2,3;`
- **P5:** `SELECT payment_gateway, payment_method, payment_status, is_fraud, is_flagged, count(*) FROM payment_paymentdetail TABLESAMPLE SYSTEM (5) GROUP BY 1,2,3,4,5 ORDER BY 6 DESC;`
- **P6:** `SELECT platform, language_code, placed_country_id, count(*) FROM order_order WHERE date_placed >= now()-interval '30 days' GROUP BY 1,2,3;`
- **P7:** `SELECT date_trunc('month',date_placed) m, status, count(*) FROM order_order WHERE date_placed >= now()-interval '18 months' GROUP BY 1,2 ORDER BY 1;`
- **P8:** `SELECT count(*) FILTER (WHERE basket_id IS NULL), count(*) FROM order_order WHERE date_placed >= now()-interval '30 days';`
- **P8b:** `SELECT (SELECT count(*) FROM basket_line l WHERE l.basket_id=b.id)>0 has_lines, b.status, count(*) FROM basket_basket b TABLESAMPLE SYSTEM (1) GROUP BY 1,2;`
- **P8c (v4 rewrite; B):** `basket_line.line_reference` is unique only per basket (Q30), so the v3 join on `line_reference` alone could match lines of other baskets. The join goes through the order header; `basket_line.date_created` and `order_order.basket_id` are indexed.
```sql
WITH bl AS (SELECT id, basket_id, line_reference FROM basket_line WHERE date_created >= now()-interval '7 days')
SELECT count(*) basket_lines,
       count(*) FILTER (WHERE o.id IS NOT NULL) in_ordered_basket,
       count(*) FILTER (WHERE ol.id IS NOT NULL) line_ref_matched   -- also tests whether order lines reuse basket line refs
FROM bl LEFT JOIN order_order o ON o.basket_id = bl.basket_id
LEFT JOIN order_line ol ON ol.order_id = o.id AND ol.line_reference = bl.line_reference;
```
  If `line_ref_matched` ≪ `in_ordered_basket`, order lines do not carry the basket line reference and the lineage row in §3 is withdrawn.
- **P9:** `SELECT min(created_on), max(created_on) FROM payment_paymentdetail;` vs `SELECT min(date_placed) FROM order_order;`
- **P10:** `SELECT count(*) FILTER (WHERE total_incl_tax <> total_incl_tax_before_payment), count(*) FROM order_order WHERE date_placed >= now()-interval '30 days';`
- **P11 (no-transition share):** `SELECT o.status, count(*) orders, count(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM order_orderstatuschange s WHERE s.order_id=o.id)) no_change FROM order_order o WHERE o.date_placed >= now()-interval '90 days' GROUP BY 1;`
- **P12 (log start):** `SELECT to_char(min(date_created),'YYYY"y"MM"m"DD"d"') FROM order_orderstatuschange;` and `SELECT to_char(min(date_placed),'YYYY"y"MM"m"DD"d"') FROM order_order;`
- **P13 (shipping as channel?):** `SELECT shipping_method, shipping_code, shipping_tax_code, (shipping_incl_tax<>0) nonzero, count(*) FROM order_order WHERE date_placed >= now()-interval '30 days' GROUP BY 1,2,3,4;` and `SELECT count(*) FILTER (WHERE billing_address_id IS NOT NULL), count(*) FILTER (WHERE shipping_address_id IS NOT NULL) FROM order_order WHERE date_placed >= now()-interval '30 days';`
- **P13b (fee-rate strings):** `SELECT processing_fee_rate ~ '^-?[0-9]+(\.[0-9]+)?$' numeric_like, count(*), count(DISTINCT processing_fee_rate) FROM order_orderlinequantitydetail TABLESAMPLE SYSTEM (1) GROUP BY 1;` (same for `processing_fee_vat_rate`; list only the non-numeric distinct values)
- **P13c (order extra keys; A only, v4):** `SELECT k, count(*) FROM atlas_ro.order_order, unnest(extra_keys) k WHERE date_placed >= now()-interval '7 days' GROUP BY 1 ORDER BY 2 DESC;` (v3 read `public.order_order.extra`, which is excluded under B and would fail.)
- **P14 (gift vs self):** `SELECT q.is_buy_for_self, q.delivery_method, count(*) FROM order_orderlinequantitydetail q JOIN order_line l ON l.id=q.line_id JOIN order_order o ON o.id=l.order_id WHERE o.date_placed >= now()-interval '30 days' GROUP BY 1,2;`
- **P15 (guest vs registered order mix):** `SELECT date_trunc('week',date_placed), guest_id IS NOT NULL is_guest, status, count(*) FROM order_order WHERE date_placed >= now()-interval '90 days' GROUP BY 1,2,3;`. This is an order mix, **not** a conversion rate.
- **P15b (guest vs registered basket→order conversion; v3).** `basket_basket.date_created` is unindexed, so sample; `order_order.basket_id` is indexed, so the LEFT JOIN is an index probe per sampled basket.
```sql
WITH b AS (SELECT id, guest_id IS NOT NULL is_guest, owner_id IS NOT NULL is_registered FROM basket_basket TABLESAMPLE SYSTEM (1))
SELECT b.is_guest, b.is_registered, count(*) baskets, count(DISTINCT o.basket_id) converted,
       round(count(DISTINCT o.basket_id)::numeric/count(*),4) conv_rate
FROM b LEFT JOIN order_order o ON o.basket_id=b.id GROUP BY 1,2;
```
- **P15c (guest→registered after purchase; v3):** `SELECT count(*) guest_orders, count(m.id) guest_later_merged FROM order_order o LEFT JOIN users_mergeduser m ON m.guest_id=o.guest_id WHERE o.guest_id IS NOT NULL AND o.date_placed >= now()-interval '90 days';` (merge id index)
- **P16 (scheduled vs instant, lead time):** `SELECT l.is_instant_activated, (p.delivery_date IS NOT NULL) scheduled, count(*), percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM l.instant_activated_date-l.created_on)) median_s FROM order_line l JOIN order_order o ON o.id=l.order_id LEFT JOIN order_orderlinepersonalisedetail p ON p.line_id=l.id WHERE o.date_placed >= now()-interval '30 days' GROUP BY 1,2;`
- **P17 (stuck fulfilment):** `SELECT status, gift_create_event_triggered, count(*) FROM order_order WHERE date_placed >= now()-interval '30 days' GROUP BY 1,2;`
- **P18 (offer uptake):** `SELECT po.offer_type, po.funded_by, po.offer_channel, count(*) lines FROM order_line l JOIN order_order o ON o.id=l.order_id LEFT JOIN offer_plusoffer po ON po.code=l.offer_code WHERE o.date_placed >= now()-interval '90 days' AND l.is_offer_applied GROUP BY 1,2,3;`
- **P19 (B2B/@Work vs consumer):** `SELECT record_type, purchase_origin, is_white_label, count(*) FROM basket_line WHERE date_created >= now()-interval '30 days' GROUP BY 1,2,3;` and `SELECT purchase_origin, is_white_label, count(*) FROM order_line TABLESAMPLE SYSTEM (1) GROUP BY 1,2;`
- **P20 (youpay decline mix; no created_on index, so sample):** `SELECT approved, payment_method, payment_gateway, left(response_summary,60), count(*) FROM youpayclient_youpayclienttransactiondata TABLESAMPLE SYSTEM (1) GROUP BY 1,2,3,4 ORDER BY 5 DESC;`
- **P20b (points):** `SELECT point_program, is_qitaf_enabled, is_full_redemption, approved, count(*), avg(redeemed_amount), avg(loyalty_level) FROM youpayclient_youpayclienttransactiondata TABLESAMPLE SYSTEM (1) GROUP BY 1,2,3,4;`
- **P21 (offer sync; B, v4):** `SELECT status, to_char(date_trunc('month',start_timestamp),'YYYY"y"MM"m"') m, count(*), percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM completed_timestamp-start_timestamp)) median_s FROM kafka_plusofferkafkadatalog TABLESAMPLE SYSTEM (5) GROUP BY 1,2 ORDER BY 2;` (same for kafka_productofferkafkadatalog without sampling).
- **P21-A (offer-sync errors per offer; A only):** `SELECT offer_code, has_error, count(*) FROM atlas_ro.kafka_plusofferkafkadatalog WHERE id >= (SELECT max(id) - 20000 FROM atlas_ro.kafka_plusofferkafkadatalog) GROUP BY 1,2 ORDER BY 3 DESC LIMIT 100;` then join `offer_code` to `offer_plusoffer.code` and to P18 uptake. Valid only after the P22-A step-1 key check confirms that `data->>'code'` is the offer code.
- **P22a (@Work sync status; B, v4):** `SELECT status, to_char(date_trunc('month',start_timestamp),'YYYY"y"MM"m"') m, count(*) FROM kafka_atworkkafkadatalog TABLESAMPLE SYSTEM (1) GROUP BY 1,2 ORDER BY 2;`
- **P22b / P22-A (@Work mapping; A only).** Step 1, key names (run by the DBA before the extracted-key columns are finalised, or through the view's `data_keys`): `SELECT k, count(*) FROM atlas_ro.kafka_atworkkafkadatalog, unnest(data_keys) k WHERE id >= (SELECT max(id) - 5000 FROM atlas_ro.kafka_atworkkafkadatalog) GROUP BY 1 ORDER BY 2 DESC;`. Step 2, order linkage on a bounded order set:
```sql
WITH a AS (SELECT coalesce(order_reference, order_number) ref, has_error FROM atlas_ro.kafka_atworkkafkadatalog
           WHERE start_timestamp >= now()-interval '1 day')          -- unindexed: needs the §12.3 index or an extract
SELECT (o.id IS NOT NULL) matched_order, a.has_error, count(*)
FROM a LEFT JOIN order_order o ON o.order_reference = a.ref OR o.number = a.ref GROUP BY 1,2;
```
  Matched orders are then profiled by `basket_line.record_type` / `order_line.purchase_origin` (P19) to test whether record_type separates @Work.
- **P22c (personalisation update sync; B):** `SELECT status, to_char(date_trunc('month',start_timestamp),'YYYY"y"MM"m"') m, count(*) FROM personalization_update_kafka_data_log TABLESAMPLE SYSTEM (5) GROUP BY 1,2 ORDER BY 2;`; error presence and linkage to `personalization_detail` via `atlas_ro.personalization_update_kafka_data_log.(has_error, personalization_reference_id)` (A).
- **P23 (tips/promos; B with the v4 grants on user_tip_tip, user_tip_invoice and offer_offerpromocode):** `SELECT status, platform, count(*), sum(amount_in_aed) FROM user_tip_tip GROUP BY 1,2;`; `SELECT state, count(*) FROM user_tip_invoice GROUP BY 1;`; `SELECT status, count(*) FROM offer_offerpromocode GROUP BY 1;`
- **P24 (friction config):** (a) `SELECT c.code, l.limit_amount, l.is_active FROM core_currencybasketlimit l JOIN core_currency c ON c.id=l.currency_id;` (b) see P24b below; (c) `SELECT country_code, is_active FROM core_unsupportedcountry;` (d) `SELECT payment_code, is_active, is_point_program FROM payment_paymentmethod;`
- **P24b (baskets over the currency cap; v3 rewrite of the broken v2 SQL).** Sample baskets first, sum lines per (basket, currency) so mixed-currency baskets are not summed across currencies, join the active cap, then aggregate. The LEFT JOIN to orders uses the `basket_id` index.
```sql
WITH sb AS (SELECT id FROM basket_basket TABLESAMPLE SYSTEM (1)),
bt AS (SELECT bl.basket_id, bl.price_currency, sum(bl.price_incl_tax*bl.quantity) total
       FROM sb JOIN basket_line bl ON bl.basket_id=sb.id GROUP BY 1,2),
capped AS (SELECT bt.*, l.limit_amount FROM bt JOIN core_currency c ON c.code=bt.price_currency
           JOIN core_currencybasketlimit l ON l.currency_id=c.id AND l.is_active)
SELECT capped.price_currency, count(*) basket_currency_rows,
       count(*) FILTER (WHERE total > limit_amount) over_cap,
       count(*) FILTER (WHERE total > limit_amount AND o.id IS NULL) over_cap_no_order,
       count(*) FILTER (WHERE total <= limit_amount AND o.id IS NULL) under_cap_no_order
FROM capped LEFT JOIN order_order o ON o.basket_id=capped.basket_id GROUP BY 1 ORDER BY 3 DESC;
```
- **P25 (youpay cardinality; v3; required before any youpay money metric).** No usable index, so sample.
```sql
SELECT count(*) rows_, count(DISTINCT order_reference) distinct_orders,
       count(*) FILTER (WHERE approved) approved_rows, count(DISTINCT order_reference) FILTER (WHERE approved) approved_orders,
       count(*) FILTER (WHERE order_reference IS NULL) null_ref, count(DISTINCT transaction_id) distinct_txn
FROM youpayclient_youpayclienttransactiondata TABLESAMPLE SYSTEM (1);
-- attempts-per-order distribution (a 1% block sample under-samples repeats spread across blocks; treat as a lower bound):
SELECT n_rows, n_approved, count(*) FROM (SELECT order_reference, count(*) n_rows, count(*) FILTER (WHERE approved) n_approved
  FROM youpayclient_youpayclienttransactiondata TABLESAMPLE SYSTEM (1) GROUP BY 1) x GROUP BY 1,2 ORDER BY 3 DESC;
-- exact per-order check on a bounded order set (youpay side is a seq scan filtered by the IN list; run off-peak or on an extract):
-- SELECT o.status, count(*) orders, count(DISTINCT y.order_reference) with_youpay, count(y.id) youpay_rows
-- FROM (SELECT id, status, order_reference FROM order_order WHERE date_placed >= now()-interval '1 day') o
-- LEFT JOIN youpayclient_youpayclienttransactiondata y ON y.order_reference=o.order_reference GROUP BY 1;
```
- **P25-A (attempts inside one youpay row; A only):** `SELECT approved, least(order_history_len,10) attempts, count(*) FROM atlas_ro.youpay_transaction WHERE id >= (SELECT max(id) - 20000 FROM atlas_ro.youpay_transaction) GROUP BY 1,2 ORDER BY 1,2;` (tells whether retries are rows or entries in `order_history`).
- **P26 (refund/cancel-like status values; v3):** `SELECT 'order' src, status v, count(*) FROM order_order WHERE status ~* '(refund|cancel|revers|void|chargeback|return|reject|expire)' GROUP BY 1,2 UNION ALL SELECT 'line', status, count(*) FROM order_line TABLESAMPLE SYSTEM (5) WHERE status ~* '(refund|cancel|revers|void|chargeback|return|reject|expire)' GROUP BY 1,2 UNION ALL SELECT 'paymentdetail', payment_status, count(*) FROM payment_paymentdetail TABLESAMPLE SYSTEM (5) WHERE payment_status ~* '(refund|cancel|revers|void|chargeback)' GROUP BY 1,2 UNION ALL SELECT 'youpay', payment_status, count(*) FROM youpayclient_youpayclienttransactiondata TABLESAMPLE SYSTEM (1) WHERE payment_status ~* '(refund|cancel|revers|void|chargeback)' GROUP BY 1,2;` (order_order uses the status index only if the regex is replaced with the literal values from P1; run P1 first)
- **P27a (block list mechanics; 48k rows, full scan cheap):** `SELECT type, source, is_guest, is_removed, count(*) FROM users_blacklisteduserdetail GROUP BY 1,2,3,4 ORDER BY 5 DESC;` and `SELECT to_char(date_trunc('month',created_on),'YYYY"y"MM"m"') m, type, count(*) FROM users_blacklisteduserdetail WHERE created_on >= now()-interval '18 months' GROUP BY 1,2 ORDER BY 1;` (never select `value`)
- **P27b (denomination out of range):**
```sql
WITH s AS (SELECT q.line_id, q.denomination, q.denomination_currency_id, bl.product_id, bl.basket_id
           FROM basket_basketquantitydetail q TABLESAMPLE SYSTEM (1) JOIN basket_line bl ON bl.id=q.line_id)
SELECT r.range_type, (s.denomination < r.minimum_amount) below_min, (s.denomination > r.maximum_amount) above_max,
       count(*) lines, count(o.id) converted
FROM s JOIN catalogue_productdenominationrange r ON r.product_id=s.product_id AND r.currency_id=s.denomination_currency_id AND r.is_active
LEFT JOIN order_order o ON o.basket_id=s.basket_id GROUP BY 1,2,3;
```
  (A line that matches several active ranges is counted once per range; check `count(*) per (product_id,currency_id) FILTER (WHERE is_active)` first.)
- **P27c (handling-fee rules vs charged fees):** `SELECT handling_fee_type, is_active, (end_date IS NULL OR end_date >= current_date) current, count(*), count(*) FILTER (WHERE amount IS NOT NULL) fixed, count(*) FILTER (WHERE percentage IS NOT NULL) pct FROM catalogue_producthandlingfee GROUP BY 1,2,3;` and
```sql
SELECT (f.id IS NOT NULL) has_active_rule, (o.process_fee > 0) charged, count(DISTINCT o.id)
FROM order_order o JOIN order_line l ON l.order_id=o.id
LEFT JOIN catalogue_producthandlingfee f ON f.product_id=l.product_id AND f.is_active
     AND o.date_placed::date BETWEEN f.start_date AND coalesce(f.end_date,'9999-12-31')
WHERE o.date_placed >= now()-interval '7 days' GROUP BY 1,2;
```
- **P28 (offer/promo mechanics; 378 rows):** `SELECT is_active, has_budget_exceeded, is_unique_promo_code, is_generic_promo_code, (promo_code_end_date < now()) promo_expired, (end_date < now()) offer_ended, reason_code, count(*) FROM offer_plusoffer GROUP BY 1,2,3,4,5,6,7 ORDER BY 8 DESC;`, then uptake by mode: P18 grouped by `po.is_unique_promo_code, po.has_budget_exceeded`.
- **P29 (gift issuance per order; created_on and order_id unindexed, so sample):**
```sql
-- B variant (v4): references only granted columns (failure is not granted, so v3's presence test would fail under B)
SELECT status, (error IS NOT NULL AND error<>'') has_error, count(*) events, count(DISTINCT order_id) orders
FROM kafka_giftcreationlog TABLESAMPLE SYSTEM (1) GROUP BY 1,2 ORDER BY 3 DESC;
-- A variant (P29-A): adds the derived presence flags from atlas_ro.kafka_giftcreationlog
SELECT status, (error<>'') has_error, has_failure, has_created_gift_details, count(*) events, count(DISTINCT order_id) orders
FROM atlas_ro.kafka_giftcreationlog WHERE id >= (SELECT max(id) - 50000 FROM atlas_ro.kafka_giftcreationlog) GROUP BY 1,2,3,4 ORDER BY 5 DESC;
SELECT n, count(*) FROM (SELECT order_id, count(*) n FROM kafka_giftcreationlog TABLESAMPLE SYSTEM (1) GROUP BY 1) x GROUP BY 1 ORDER BY 1;
```
  Cross-check: for a date_placed-bounded order set, compare `gift_create_event_triggered` (P17) with the existence of a success event, and `sum(order_line.quantity)` with the successful event count, keyed on whichever order key `order_id` holds (Open Question 4). Run on an extract because `order_id` is unindexed.
- **P30 (orders created on behalf):** `SELECT (o.created_by_id = o.user_id) self_created, (o.user_id IS NULL) no_user, (o.guest_id IS NOT NULL) guest, (o.modified_by_id IS NOT NULL) modified, o.platform, count(*), count(DISTINCT o.created_by_id) creators FROM order_order o WHERE o.date_placed >= now()-interval '30 days' GROUP BY 1,2,3,4,5 ORDER BY 6 DESC;` then (B, needs the v4 `users_customuser` column grant): `SELECT u.is_staff, u.is_superuser, u.is_active, count(*) orders, count(DISTINCT o.created_by_id) creators FROM order_order o JOIN users_customuser u ON u.id=o.created_by_id WHERE o.date_placed >= now()-interval '30 days' AND o.created_by_id IS DISTINCT FROM o.user_id GROUP BY 1,2,3;` (ids and flags only, no names).
- **P31 (identity-sync status; B, v4; 94k rows):** `SELECT status, to_char(date_trunc('month',created_on),'YYYY"y"MM"m"') m, count(*) FROM users_cognitouserdatasynclog GROUP BY 1,2 ORDER BY 2;` (v3 also tested `error`, which is not granted under B and would fail.)
- **P31-A (identity-sync errors; A only):** `SELECT status, has_error, to_char(date_trunc('month',created_on),'YYYY"y"MM"m"') m, count(*) FROM atlas_ro.users_cognitouserdatasynclog GROUP BY 1,2,3 ORDER BY 3;` and `SELECT k, count(*) FROM atlas_ro.users_cognitouserdatasynclog, unnest(error_keys) k GROUP BY 1 ORDER BY 2 DESC;` (key names only, never values).
- **P32 (FX drift vs current rate):** `SELECT c.code, count(*) orders, avg(o.conversion_rate_reporting_currency) avg_order_rate, max(r.buy_rate) current_buy, max(r.sell_rate) current_sell FROM order_order o JOIN core_currency c ON c.code=o.currency JOIN core_currencyexchangerate r ON r.foreign_currency_id=c.id WHERE o.date_placed >= now()-interval '7 days' GROUP BY 1;` (the rate table has no history; verify which side of the pair `conversion_rate_*` expresses before interpreting)
- **P33 (config-change history; B with the v4 django_admin_log + django_content_type grants; 2.7k rows):**
```sql
SELECT ct.app_label, ct.model, l.action_flag, to_char(date_trunc('month',l.action_time),'YYYY"y"MM"m"') m, count(*) changes, count(DISTINCT l.object_id) objects, count(DISTINCT l.user_id) admins
FROM django_admin_log l LEFT JOIN django_content_type ct ON ct.id=l.content_type_id
WHERE l.action_time >= now()-interval '24 months' GROUP BY 1,2,3,4 ORDER BY 4,5 DESC;
```
  Then, for the friction configs (`core.currencybasketlimit`, `payment.paymentmethod`, `order.giftactivationconfig`, `catalogue.productdenominationrange`, `offer.plusoffer`, `users.blacklisteduserdetail`), list the change dates (`to_char(action_time,'YYYY"y"MM"m"DD"d"')`, `object_id`, `action_flag`) and overlay them on the P7 / P15 weekly series.
- **P34 (guest identities vs guest orders; B with the v4 users_guestuser grant; 82k rows, full scan):**
```sql
WITH g AS (SELECT platform, date_trunc('month',created_on) m, count(*) guests FROM users_guestuser WHERE created_on >= now()-interval '12 months' GROUP BY 1,2),
     o AS (SELECT gu.platform, date_trunc('month',o.date_placed) m, count(*) guest_orders, count(DISTINCT o.guest_id) ordering_guests
           FROM order_order o JOIN users_guestuser gu ON gu.id=o.guest_id
           WHERE o.date_placed >= now()-interval '12 months' AND o.guest_id IS NOT NULL GROUP BY 1,2)
SELECT coalesce(g.platform,o.platform) platform, to_char(coalesce(g.m,o.m),'YYYY"y"MM"m"') m, g.guests, o.guest_orders, o.ordering_guests
FROM g FULL JOIN o ON o.platform=g.platform AND o.m=g.m ORDER BY 2,1;
```
- **P35 (repeat purchase; B; `user_id`, `guest_id`, `date_placed` indexed):** replace `<purchase statuses>` with the paid/sold values found by P1.
```sql
WITH c AS (SELECT coalesce('u'||o.user_id, 'g'||o.guest_id) cust, count(*) n,
                  min(o.date_placed) first_o, (array_agg(o.date_placed ORDER BY o.date_placed))[2] second_o
           FROM order_order o WHERE o.date_placed >= now()-interval '180 days' AND o.status IN (<purchase statuses>)
           AND (o.user_id IS NOT NULL OR o.guest_id IS NOT NULL) GROUP BY 1)
SELECT left(cust,1) kind, least(n,5) orders_bucket, count(*) customers,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM second_o-first_o)/86400) median_days_to_2nd
FROM c GROUP BY 1,2 ORDER BY 1,2;
```
  If 180 days exceeds the 20 s timeout, narrow to 90 days. Guests who registered later are split across two ids; a second pass maps `guest_id` → `user_id` through `users_mergeduser`.
- **P36 (preset vs custom denomination; B with the v4 catalogue_productdenomination grant):**
```sql
WITH s AS (SELECT q.denomination, q.denomination_currency_id cur, bl.product_id, bl.basket_id
           FROM basket_basketquantitydetail q TABLESAMPLE SYSTEM (1) JOIN basket_line bl ON bl.id=q.line_id)
SELECT (d.id IS NOT NULL) is_preset, coalesce(d.is_default,false) is_default_preset,
       EXISTS (SELECT 1 FROM catalogue_productdenomination x WHERE x.product_id=s.product_id AND x.is_active) product_has_presets,
       count(*) lines, count(o.id) lines_in_ordered_baskets
FROM s
LEFT JOIN LATERAL (SELECT id, is_default FROM catalogue_productdenomination d
                   WHERE d.product_id=s.product_id AND d.currency_id=s.cur AND d.amount=s.denomination AND d.is_active
                   ORDER BY d.is_default DESC LIMIT 1) d ON true
LEFT JOIN order_order o ON o.basket_id=s.basket_id
GROUP BY 1,2,3;
```
- **P37 (PII presence without values; A only):** `SELECT (guest_id IS NOT NULL) is_guest, has_user_email, has_guest_email, has_user_phone, has_user_name, has_owner, count(*) FROM atlas_ro.order_order WHERE date_placed >= now()-interval '30 days' GROUP BY 1,2,3,4,5,6;` and the same over `atlas_ro.order_orderlinepersonalisedetail (has_recipient_phone, has_recipient_email)`. It answers how often the NOT NULL PII columns are actually empty (§2.2) without exposing any value.
