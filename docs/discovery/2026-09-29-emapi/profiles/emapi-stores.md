# Profile: emapi-stores (`ygag_emapi_stores_db`)

Profiled 2026-09-29 through `atlasq.sh`: SSH to the atlas EC2 box, a READ ONLY transaction, a production Aurora read replica (`is_replica: true`), role `<emapi_login_role>`. Revised the same day after three critic reviews (rev 2, rev 3, rev 4): all figures below were re-queried from the catalog. Rev 3 corrections: the "empty" table list, the `brands_offer_happy_cards` row bound, the forced-upgrade query (a), new missing-uniqueness findings, the `users_user` index breakdown and replica `pg_stat_database` counters (Q20–Q25). **Rev 4** (third critic review): new Schema chronology section (Q27), `mobile_app_client_config` corrected (Q28/Q29), `brands_hasofferbrands` row estimate re-read and corrected for drift (49,787 → 40,079, Q31), `brands_generic_brand_item` added to the churn list (Q30), new friction signals (validity/expiry, recipient instructions, password rotation, promo-code inventory), merchandising layout flags and email-template inventory, IDENTITY columns and unused extensions, all queued queries rewritten against the view columns in the Grant request, and a consolidated **Grant request** section (Q26–Q31).

**Evidence labels.** Every claim carries one of three labels:
- **[VALIDATED]**: backed by a data query that was run. No data query is possible in this database, so **no claim in this profile is VALIDATED**.
- **[STRUCTURAL]**: inferred from schema, constraints, sizes, planner estimates or oid order. Exact catalog facts (a column exists, a constraint exists, a byte size) also get this label, because they say nothing about row values.
- **[NEEDS-GRANT]**: a hypothesis that needs rows this role cannot read. The table and columns are named each time.

Where a table row or bullet carries no label, it is a schema description and is [STRUCTURAL].

**Units.** "MB" means 10^6 bytes and "MiB" means 2^20 bytes. Exact byte counts are in the appendix. `pg_size_pretty` output (the database total) uses 1024-based units, so it is reported as MiB.

> **BLOCKER. The role cannot read any rows in this database.**
> Re-checked in rev 2 (Q13), rev 3 (Q24) and rev 4 (Q26, 2026-09-29): **0 of 84** public tables are SELECT-able and **0 of 83** sequences are readable. Every `SELECT ... FROM <table>` fails with `InsufficientPrivilegeError: permission denied` (Q4, Q6). `pg_stats` returns 0 rows for `public` (Q7), because the view hides columns the role cannot read, and `pg_statistic` is denied. Sequence `last_value` is NULL (Q8). The replica's `pg_stat_user_tables` counters are all 0 (Q7), and its `pg_stat_database` counters are near-empty (Q25), so replica activity statistics cannot stand in for data either.
> So this profile is **catalog-only**: schema, constraints, indexes, planner row estimates (`pg_class.reltuples`) and on-disk sizes. **Status and enum distributions, timestamp min/max, monthly trends, failure rates and id ranges could not be measured.** Those sections are marked **BLOCKED — needs grant** and list the exact queries to run once access is granted. **The concrete, column-level request is the "Grant request" section** (referenced as Open Question 1). I did not try to bypass this.

## Summary

`ygag_emapi_stores_db` is the backend database for the **EMAPI "stores" Django service**. It holds the master **brand/product catalog** and the **storefront merchandising configuration** for YouGotAGift's consumer app and web. It also holds:
- a **consumer user registry** of about 992k rows (estimate) [STRUCTURAL]
- **"Plus Offers"**: brand-funded promotions with two mechanics, discount-at-purchase and spend-to-earn, plus promo codes and per-user avails (claims) [STRUCTURAL; the mechanic split is NEEDS-GRANT on `brands_plusoffer.purchase_offer_header`/`spend_offer_header`]
- **Kafka ingest logs** recording data synced in from other YGG services (at-work, plus-offers, web-stores, emapi-stores) [STRUCTURAL]

The database is 3,612 MiB, 3,787,549,271 B ≈ 3.79 GB (exact, Q9, re-read Q31) [STRUCTURAL]. Most of the space is the Kafka logs and `users_user`. `kafka_plusofferkafkadatalog` alone has 1.53 GB (1.43 GiB) of TOAST, so its JSON payloads are large [STRUCTURAL].

Behavior signals in this database are thin but useful (all [STRUCTURAL] column inventory; every measurement of them is [NEEDS-GRANT]):
- `users_user`: `last_login`, `date_joined`, `modified_on` (profile-update recency), `platform`, `app_version`, `custom_profile_img`, `is_fraud`, `is_deleted`, `trusted_user`, social-login ids and verification flags
- favourite brands (about 19.8k rows, estimate)
- availed (claimed/activated) plus-offers (about 6.5k rows, estimate). No amount, order or channel column, so these are not proven spend events
- 2FA/OTP devices (admin-only scale)
- inbound webhook messages that carry an `error_message` JSON (about 1.6k rows now, but index size suggests a much larger purged history)
- Kafka consumer logs with `status`, `error_data`, and start/complete timestamps. This is the main **system-behavior and error signal**.

This database has **no orders, baskets, payments, gifts or referrals**. Those live in the `ygag_ecom_*`, `ygag_checkout_db` and wallet databases. This database supplies the **brand and user dimensions** they join to.

## Entities & Tables

Volumes are `pg_class.reltuples` **estimates** (Q1, re-read in Q14) unless noted. "~N (pages)" means the table was never analyzed (`reltuples=-1`), so the only size information is its heap pages. `!` marks NOT NULL. The table inventory at the end of this section lists all 84 tables individually.

### 1. Brand / product catalog (core dimension)
| Table | Est. rows | Purpose / key columns |
|---|---|---|
| `brands_brand` | 6,610 | Master brand (gift card product). `code` varchar(16) UNIQUE, `slug` UNIQUE, `name/_en/_ar`, `redemption_type`!, `classification`!, `generic_type`, `is_generic`, `is_active`, `is_launched`, `is_obsolete`, **validity/expiry** `non_expirable`! bool, `validity_months`! int, `validity_days`! int, `expiry_details`! jsonb (all NOT NULL, Q28), **recipient/sender instructions** `receiver_redemption_details[_en/_ar]` text (nullable), `sender_redemption_details[_en/_ar]` text (nullable), `short_redemption_details[_en/_ar]` varchar(255) (nullable) (Q28), **redemption-mode flags** `has_code`!/`has_pin`!/`has_redeem_url`! (what the recipient receives: a code, a PIN, a redeem URL, or a combination), **`buy_for_yourself`!** (self-purchase enabled, not just gifting) (Q21), `plus_offers_details` jsonb. 87 columns (Q15). **Channel visibility flags:** `visible_to_ecommerce`, `_ecommerce_app`, `_android`, `_ios`, `_at_work`, `_corporate`, `_corporate_api`, `_specific_corporate`, `_credit`, `_gift_shop`, `_mpos`, `_sendatip`. **Redemption-friction flags** (Q16): `require_mobile_verification`!, `allow_any_country_mobile_verification`!, `pin_redeemable`!, `pin_redeemable_location_required`!, `pin_label`, `can_be_split`!, `can_be_swapped`! (recipient can exchange the card for another brand, i.e. friction relief), `minimum_usage_amount` numeric(20,3), `redeemable_brands` text. FKs: `currency_id`→core_currency, `primary_category_id`→brands_category, `store_id`→locations_store, `company_id`→brands_retailers. **Size (Q15):** heap 180.9 MB (172.5 MiB), TOAST 32.8 MB (31.3 MiB), indexes 5.0 MB. Heap alone is about 27.4 KB per row, and wide text is moved to TOAST, so it is not what makes the heap large. The likely cause is update bloat (dead tuples from frequent in-place updates to an 87-column row). This is an inference: dead-tuple counters are 0 on the replica. |
| `brands_brand_denomination` | 44,317 | Fixed face values per brand: `amount` numeric(15,6), `gencode`, `currency_id`, `is_active` |
| `brands_brand_denomination_range` | 24,273 | Open-amount ranges: `range_type`, `minimum_amount`, `maximum_amount`, `currency_id` |
| `brands_brand_images` | 11,129 | Brand gallery images |
| `brands_category` / `brands_brand_categories` | 65 / 37,811 | Categories (`code` UNIQUE, `tag_id`) and the brand↔category auto-M2M (id, brand_id, category_id) |
| `brands_tag` / `brands_tag_brand` | 147 / 41,405 | Merchandising tags, hierarchical (`parent_tag_id`, `redirect_to_tag_id`, `tag_type`, `seo_name`), with visibility flags `is_visible`!, `is_active`! and **`visible_to_ecommerce_app`!** (app vs web exposure) (Q21), and the tag↔brand mapping with ordering |
| `brands_brand_search_tag` / `brands_brand_search_tags` | 17,743 / 63,720 | Search keywords and the brand↔keyword auto-M2M |
| `brands_occasion` | ~<100 (3 pages) | Gifting occasions (birthday etc.): `code` UNIQUE, `card_message`, `is_custom` |
| `brands_retailers` | 795 | Retailers/companies: `code`, `ref_code`, `accepts_generic`. Referenced as `brands_brand.company_id` |
| `brands_storelocation` | 4,063 | Physical redemption locations per brand: `code` UNIQUE, `community_id`, contact fields (PII-like) |
| `brands_generic_brand_config` | 3,381 | Config for "generic" multi-brand cards (one per brand, UNIQUE brand_id): `generic_type`, `process_mode`!, `enable_pdf_resend`, `enable_gift_resend`, `auto_brand_sync` |
| `brands_generic_brand_item` | 533,305 | Brands redeemable inside a generic card: `generic_config_id`, `brand_id`, `is_active`!, `order_number`, `ecom_order_number`. **`generic_config_id` and `brand_id` are both nullable and there is no UNIQUE(generic_config_id, brand_id)** (Q20, Q21, Q22: only a pkey and single-column btree indexes). **Fan-out: 533,305 / 3,381 ≈ 158 rows per generic-card config (est.)** [STRUCTURAL, from reltuples]. This is an average of rows, not distinct brands: duplicate (config, brand) pairs, inactive rows and null-keyed rows are all possible and would inflate it. If only some configs are populated, the per-card fan-out is higher. `auto_brand_sync` suggests a job keeps these lists filled [STRUCTURAL]. **Size (Q30/Q31):** heap 57.3 MB (≈107 B per 10-column row, normal), but the pkey is 25.4 MB against about 12 MB expected, so ≈2x: consistent with rows being deleted and re-inserted by `auto_brand_sync` [STRUCTURAL]. |
| `brands_productchannel` | 2 | Sales channels for `brands_offer.channel_id` |

### 2. Offers & promotions (campaigns)
| Table | Est. rows | Purpose |
|---|---|---|
| `brands_plusoffer` | 378 | **Plus Offer** campaign: `code` UNIQUE, `start_date`/`end_date` (tstz, indexed), `offer_mode`!, `offer_type`! (indexed), `offer_channel`!, `funding_method`, `funded_by`, `percentage`, `fixed_amount`, min/max amounts, **budget** (`is_budget_available`!, `budget_type`, `budget_amount`, `budget_threshold`, `has_budget_exceeded`!), **usage** (`has_usage_limit`!, `usage_count`), **promo codes** (`is_generic_promo_code`! bool, `is_unique_promo_code`! bool, `promo_code_end_date` tstz nullable, `promo_code_threshold` int nullable, Q28: a generic code is one shared code, a unique code is one per user; the threshold is probably a low-inventory alert level) [STRUCTURAL], sponsor payment network (card-scheme sponsored offers), `reason_code`, `brand_id`, `country_id`. **Two offer mechanics** (Q16): `purchase_offer_header[_en/_ar]` (discount or reward at purchase) and `spend_offer_header[_en/_ar]` (spend-to-earn), both varchar(500) and nullable. Which one is populated probably marks the mechanic. **Merchandising placement:** `featured_order`!, `brand_tile_order_number`!, `offer_order_number`! (int), used to rank campaigns on featured, brand-tile and offer-list surfaces. **`how_it_works[_en/_ar]` jsonb** holds step-by-step explainer content. TOAST is 6 MB (T&C and explainer text). |
| `brands_plusoffer_happy_cards` | 132,977 | **Django auto-M2M** (`ManyToManyField`): only `id, plusoffer_id, brand_id`, UNIQUE(plusoffer_id, brand_id), no timestamps or audit columns (Q14, Q17). Edited as a multi-select in the admin. These are the gift-card brands ("happy cards") that the offer can be applied to. |
| `brands_hasofferbrands` | **40,079** (re-read Q31; rev 3 had 49,787) | **Explicit through-model**: `id, created_on!, modified_on!, brand_id!, offer_id!`, FKs **`offer_id`→brands_plusoffer and `brand_id`→brands_brand** (Q29), **no UNIQUE on (offer_id, brand_id)** (Q17, Q29). **Estimate drift:** `reltuples` fell from 49,787 to 40,079 between rev 3 and rev 4 while `relpages` stayed at 4,317 and heap bytes stayed at 35,364,864, so the primary re-analyzed the table and its live row count moved by about 20% with no heap growth: rows are being removed and replaced inside the existing pages [STRUCTURAL]. Heavy churn bloat: heap 35.4 MB (33.7 MiB) and indexes 45.1 MB (43.0 MiB), which is about 882 B of heap per 5-column row (35,364,864 / 40,079) against roughly 70 B expected. The pkey index alone is 26.6 MB (Q18, unchanged in Q31), about 30x what 40k bigint keys need. A table that a sync job repeatedly deletes and re-inserts (for example, rebuilding "brands that currently have an offer" for listing badges) would look like this [STRUCTURAL]. The Schema chronology section shows it was created in the same migration window as `kafka_emapistoreskafkadatalog` and `kafka_atworkkafkadatalog`, which supports the sync-job reading [STRUCTURAL]. Compare `happy_cards`: its heap is about 204 B per 3-column row (≈4x expected) and its pkey index is 27.6 MB, so it churns too, but less. |
| `brands_offerpromocode` | 72 | Promo codes issued for a plus offer: `status`! varchar(20), `promo_code`! varchar(200) (secret-like), `offer_id`!→brands_plusoffer, `brand_id`!. **No UNIQUE on `promo_code`** (only pkey plus offer_id/brand_id indexes, Q20, Q22), so duplicate codes are possible. **No `user_id` or `redeemed_at` column** (Q21): codes are not tied to users in this database, so redemption of a code by a user cannot be traced here. |
| `brands_offer` | ~<1k (44 pages) | Older/simple brand offer: `offer_base`!, `offer_type`!, `percentage`/`fixed_amount`, `start_date`/`end_date` (date), budget flags, `has_min_max_order`, `till_future`, `country_id`, `channel_id` |
| `brands_offer_happy_cards` | **≤24.5k (upper bound from 156 heap pages; never analyzed)** | Auto-M2M `offer_id!, brand_id!`, UNIQUE(offer_id, brand_id) (Q20). Bound: a 3-bigint tuple is 24 B header + 24 B data = 48 B plus a 4 B line pointer = 52 B; (8,192 − 24 B page header) / 52 = 157 tuples per page at 100% fill; 156 × 157 = 24,492 rows maximum (Q23). The true count is lower if pages are not full. |
| `users_useravailedoffer` | 6,487 | **User availed a plus offer** (claim/activation): `user_id`!→users_user, `plus_offer_id` (**nullable**)→brands_plusoffer, `created_on`!, `modified_on`!, and **`created_by_id`! NOT NULL / `modified_by_id`, both indexed** (Q17, Q18, Q21). Only 7 columns: **no amount, order, basket or channel column**, so a row records that a user availed/claimed an offer, not a proven spend or redemption. **No UNIQUE(user_id, plus_offer_id)** (Q20, Q22: only single-column indexes), so the same user can avail the same offer many times, and rows with a null offer (orphans) are allowed. Reconcile against `brands_plusoffer.usage_count` and the `ygag_plusoffers_db` ledger before calling it redemption (Open Question 5). |

### 3. Users & auth
| Table | Est. rows | Purpose |
|---|---|---|
| `users_user` | 992,399 | Consumer/app user (custom Django user). Identity: `username` UNIQUE, `email` UNIQUE, `phone_number` UNIQUE, `sub` (Cognito-style subject), `apple_id`, `google_id`, `facebook_id`, `legacy_auth_code[]`, `secondary_emails[]` (GIN). Behavior and state: `date_joined`!, `last_login`, **`modified_on`!** (last profile write), `platform`! varchar(10), `app_version` varchar(60), `user_agent` **varchar(100)** (Q28: long UA strings are truncated at 100 chars, so any OS version parsed from it is lossy), `ip_address` inet, `language_code`, `country_of_residence` (ISO2), **`custom_profile_img`! bool** (profile-completion signal), `type`, `is_active`, `is_enabled`, `is_deleted`, `is_fraud`, `trusted_user`, `email_verified`, `phone_number_verified`, `is_native_user`, `is_app_user`, `new_password_policy`! bool, `is_staff`, `is_superuser`. 41 columns. **No `created_on` and no `created_by_id`** (Q13a). Heap 283.6 MB (283,598,848 B), indexes 478.4 MB (478,380,032 B) across 9 indexes (Q31; rev 3 read 283,574,272 / 478,347,264, so it grew by about 24 KB of heap and 33 KB of index) [STRUCTURAL]. **The index size is redundant indexing, not bloat** (Q22b): 446.8 MB (93%) is seven btrees on three columns: `username` UNIQUE 79.5 MB + `username` `_like` (varchar_pattern_ops) 77.8 MB + composite `(username, is_enabled)` 77.6 MB; `email` UNIQUE 62.6 MB + `email` `_like` 61.1 MB; `phone_number` UNIQUE 44.1 MB + `phone_number` `_like` 44.1 MB. The rest is pkey 24.1 MB and the `secondary_emails` GIN 7.5 MB. The `_like` indexes are Django's automatic LIKE-prefix companions. The `(username, is_enabled)` composite shows the login path filters on `is_enabled` (disabled accounts are rejected at lookup). Its leading column duplicates the UNIQUE `username` index. |
| `users_usermetadata` | unknown (1 heap page of 8,192 B allocated, never analyzed) | **Password-expiry state per user** (Q28/Q29): `id` (IDENTITY), `user_id` (nullable) UNIQUE→users_user, `password_last_changed` tstz (nullable), `has_received_expiry_warning`! bool, `created_on`!, `modified_on`!. With `users_user.new_password_policy`! bool this forms a **password-rotation funnel**: on new policy → last changed → warned before expiry → changed again (users_passwordhistory) [STRUCTURAL]. One heap page (about 70 B per row, so at most roughly 110 live rows) means the policy has reached very few users or is new [STRUCTURAL; NEEDS-GRANT on row count]. |
| `users_passwordhistory` | unknown (1 heap page of 8,192 B allocated, never analyzed) | Password-reuse history: `id` (IDENTITY), `user_id`!→users_user, `password_hash`! varchar(255), `created_on`!, `modified_on`! (Q28/Q29). No UNIQUE on user_id, so many rows per user |
| `users_user_groups` / `users_user_user_permissions` | 4 / ~<100 (2 pages) | Django admin RBAC links |
| `auth_group` / `auth_permission` / `auth_group_permissions` | 2 / ~<300 (3 pages) / ~<500 (2 pages) | Django RBAC: 2 admin groups. Permissions are keyed by `content_type_id`→django_content_type with UNIQUE(content_type_id, codename). The group↔permission link is UNIQUE(group_id, permission_id) (Q17) |
| `django_content_type` | 66 | `app_label, model` UNIQUE (Q17): about 66 registered models. **Decodes** `django_admin_log.content_type_id`, `auth_permission.content_type_id` and the `configurations_homepageslideritem` generic FK. |
| `django_migrations` | ~<100 (2 pages, never analyzed) | `app, name, applied` tstz!. Once readable, the `applied` timestamps give a schema and deploy timeline. |
| `django_site` | unknown (1 heap page of 8,192 B, never analyzed; Django normally keeps 1 row) | Sites framework |
| `brands_favouritebrand` | 19,821 | **User favourited a brand**: `id, created_on!, modified_on!, brand_id, user_id`, UNIQUE(user_id, brand_id). **No created_by/modified_by columns** (Q17) |
| `otp_totp_totpdevice` / `otp_static_staticdevice` / `otp_static_statictoken` / `two_factor_phonedevice` | 13 / 1 / 10 / 0 | 2FA devices, almost certainly for admin/staff only. `throttling_failure_count`, `throttling_failure_timestamp`, `created_at`, `last_used_at` |
| `django_session` | 228 | Admin web sessions (`expire_date`) |
| `django_admin_log` | 42,347 | **Admin change audit** (`action_time`, `action_flag` 1=add/2=change/3=delete, `content_type_id`→django_content_type, `object_id`, `user_id`): catalog and config edit history |
| `dashboard_userdashboardmodule`, `jet_bookmark`, `jet_pinnedapplication` | 78 / 0 / 0 | Django-JET admin UI state |

### 4. Storefront merchandising (configurations_*)
The `configurations_*` group has 17 tables. They configure the home page and shop layout per `locations_store`, for guests or logged-in users, per `configurations_platform` (3 rows).
- `homepageslider` (56; audience flags `is_for_guests`! and `is_for_logged_in_users`!, `is_active`!, `order_number`!, `store_id`!, `slider_type_id`!), `homepageslideritem` (914; generic FK via `content_type_id`→django_content_type and `object_id`), `slidertype` (8), `homepageslider_platform_type` (~<100, 2 pages)
- `carousel` (7, one per store), `carouselitem` (98; `type`!, `is_active`!, `start_time`/`end_time` (nullable) scheduling, `is_wide_image`!, `video_url[_en/_ar]` (nullable, video vs static), `image_webp*`, `meta_data` jsonb!)
- `banner` (8), `banneritem` (~<100, 2 pages; `config`! and `config_ar`! jsonb carry per-item display/redirect config, `redirect_id`!, `is_active`!), `bannerimage` (0 bytes), `bannertype` (1)
- `shopcategory` (16), `shopcategorybrand` (6,186), `myshopcategory` (9), `myshopcategorybrand` (2,436), `myshopcategory_platforms` (26)
  - **`shopcategory` layout flags** (Q28): `is_interest`! (category offered as a user interest), `is_slider`! (rendered as a slider), `is_horizontal_scroll`! (horizontal row), `row_count` and `column_count` int (nullable, grid dimensions), plus `is_visible`!, `is_active`!, `order_number`, `code` UNIQUE (Q29). `myshopcategory` has none of the layout flags; it has `border_color_id`/`ribbon_color_id` and a per-platform M2M instead [STRUCTURAL].
  - **`shopcategory` is most likely the successor of `myshopcategory`** [STRUCTURAL]: it was created much later (oid 36,404,056 vs 2,516,530, Schema chronology), has the same core columns (`code`, `title[_en/_ar]`, `image`, `image_webp`, `order_number`, `is_visible`, `is_active`) plus layout flags, and carries 2.5x more brand links (6,186 vs 2,436). Neither table has a `store_id`; `shopcategory` also has no platform link. Whether `myshopcategory` is still served is [NEEDS-GRANT: `configurations_myshopcategory.is_active`, `modified_on`].
- `color` (21), `platform` (3)

### 5. Geography / currency / locale (core_*, locations_*)
- `core_country` (22): ISO `code` and `code_three_letter`, phone regex, `timezone`
- `core_stateprovince` (~<100, 3 pages), `core_city` (320), `core_community` (1,105): hierarchy country→state→city→community
- `core_currency` (23), `core_basecurrency` (19)
- `core_currencyexchangerate` (437): `buy_rate`!, `sell_rate`! numeric(15,6), `base_currency_id`→core_basecurrency, `foreign_currency_id`→core_currency, `created_by_id`! (Q17). **It is a current-rate matrix with one row per (base, foreign) pair, not a history.** Evidence: 437 = 19 base currencies × 23 currencies exactly (reltuples estimates, Q14), and there is no effective-date column. **Label: inference from reltuples.** No UNIQUE(base, foreign) constraint enforces this, so duplicate pairs are possible. When a rate changes, it is overwritten, and `modified_on` records the last update. Rate history must come from elsewhere.
- `core_language` (2: en/ar), `core_country_languages` (24)
- `locations_store` (22): a storefront per country, with `code` UNIQUE, `visible_to_ecommerce`, `visible_to_atwork`, `currency_id`, `country_id`
- `locations_store_languages` (23): auto-M2M store↔language, UNIQUE(store_id, language_id) (Q17). Most stores are single-language: 23 links over 22 stores.

### 6. Integration / system
| Table | Est. rows | Purpose |
|---|---|---|
| `kafka_atworkkafkadatalog` | 1,715,930 | Consumer log of messages from the **at-work** (corporate) service. Columns are only `id, data jsonb!, status varchar(20)!, error_data text!, start_timestamp!, completed_timestamp`. Heap 517.3 MB. **Only a pkey index** (no index on status or timestamp) |
| `kafka_emapistoreskafkadatalog` | 741,210 | Same shape, for emapi-stores events. Its id default is `nextval('kafka_plusofferapidatapublisherlog_id_seq')`, so the table was renamed from a "plus offer API data publisher log". Heap 155.4 MB, TOAST 25.8 MB |
| `kafka_plusofferkafkadatalog` | 410,354 | Same shape, for plus-offer events. **1.53 GB TOAST**, so payloads are very large |
| `kafka_webstoreskafkadatalog` | 18 | Same shape, for web-stores. Nearly dead |
| `webhooks_webhookconfig` | 1 | Inbound webhook endpoint: `webhook_key` UNIQUE, `sender_ips[]`, `created_by_id`! |
| `webhooks_webhookmessage` | 1,629 | Inbound webhook payloads: `id, ip_address, message jsonb, received_at!, error_message jsonb, type varchar(20)`. **Only a pkey index, yet that index is 8.15 MB (995 pages) against a 1.06 MB heap** (Q18). A 1,629-row bigint pkey would be about 5 leaf pages. The index must once have covered hundreds of thousands of ids, so a large historical volume was **purged or rotated**, and current row counts understate webhook traffic (inference from sizes). |
| `remote_url_config_remoteurlconfig` | 4 | Downstream service URLs plus `api_key`/`api_secret` (**secrets stored in DB**) |
| `emapi_generics_client_mobileappplatformversion` | 16 | Mobile app force/optional-update config: `app_platform` varchar(50)!, `latest_version` varchar(50)!, `required_version` varchar(50)!, `optional` bool!, **`os_version_check_enabled` bool!** and **`required_os_version` varchar(50)** (nullable): a second, **OS-level** forced-upgrade gate that blocks devices whose operating system is below a minimum, independent of app version (Q21). `reference_id` uuid UNIQUE. **The only UNIQUE is `reference_id`; there is no UNIQUE(app_platform)** (Q20), so 16 rows over a handful of platforms means several rows per platform (history, or per-variant config). Any join on platform must first pick one row per platform. It is the **first** of two app-version gates; the second is the per-client, per-version `expiry_date` in `mobile_app_client_config` (currently empty) [STRUCTURAL]. |
| `mobile_app_client_config` | 0 (0 heap bytes) | **Per-client app-version sunset/expiry table** (Q28/Q29): `client_name`! varchar(255), `platform`! varchar(50), `version`! varchar(50), `expiry_date` tstz (nullable), `reference_id` uuid! UNIQUE, `created_on`/`modified_on` (nullable), audit FKs. **UNIQUE(client_name, platform, version)** (index `unique_client_app_version`). One row says "client X's app version V on platform P expires on date D". This is a **second upgrade gate**, next to the platform-level `required_version`: it can retire individual versions (or versions of a specific client app, e.g. a white-label or partner app) on a date. **It is currently empty (0 heap bytes)**, so the gate exists in schema but is not configured [STRUCTURAL]. |
| `notifications_emailtemplateconfiguration` | unknown (1 heap page of 8,192 B plus an 8,192 B TOAST relation, never analyzed) | **Email trigger configuration** (Q28/Q29): `id` (IDENTITY), `email_type` varchar(25), `template_code` varchar(10), `language_id`→core_language, `template_data` jsonb, `to_emails` text (PII), `is_active`!, audit FKs. No UNIQUE on (email_type, language_id). Each row maps an email trigger type to a template per language. Emptiness is **not** proven; the TOAST page suggests at least one wide row (`template_data` or `to_emails`) was written [STRUCTURAL]. The inventory (which triggers exist, per language, active or not) is [NEEDS-GRANT: `email_type`, `template_code`, `language_id`, `is_active`]. |
| `assets_image`, `assets_imagetag` | ~1 each | Nearly empty |

### Full table inventory (84, Q14)
Format: name = est. rows / heap pages. -1 means never analyzed. `relpages=0` on a never-analyzed table does not mean empty: check `pg_relation_size` (Q20a).
- **brands_* (23):** brand 6,610/22,085 · brand_categories 37,811/243 · brand_denomination 44,317/689 · brand_denomination_range 24,273/390 · brand_images 11,129/262 · brand_search_tag 17,743/174 · brand_search_tags 63,720/445 · category 65/7 · favouritebrand 19,821/173 · generic_brand_config 3,381/52 · generic_brand_item 533,305/6,994 · hasofferbrands 40,079/4,317 (was 49,787 in rev 3, Q31) · occasion -1/3 · offer -1/44 · offer_happy_cards -1/156 (≤24,492 rows, Q23) · offerpromocode 72/23 · plusoffer 378/596 · plusoffer_happy_cards 132,977/3,307 · productchannel 2/1 · retailers 795/14 · storelocation 4,063/111 · tag 147/12 · tag_brand 41,405/578
- **configurations_* (17):** banner 8 · bannerimage 0/0 · banneritem -1/2 · bannertype 1 · carousel 7 · carouselitem 98 · color 21 · homepageslider 56 · homepageslider_platform_type -1/2 · homepageslideritem 914 · myshopcategory 9 · myshopcategory_platforms 26 · myshopcategorybrand 2,436 · platform 3 · shopcategory 16 · shopcategorybrand 6,186 · slidertype 8
- **core_* (9):** basecurrency 19 · city 320 · community 1,105 · country 22 · country_languages 24 · currency 23 · currencyexchangerate 437 · language 2 · stateprovince -1/3
- **kafka_* (4):** atwork 1,715,930/63,144 · emapistores 741,210/18,450 · plusoffer 410,354/8,388 · webstores 18/3
- **users_* (6):** user 992,399/34,467 · user_groups 4 · user_user_permissions -1/2 · useravailedoffer 6,487/61 · usermetadata -1/0 (8,192 B heap) · passwordhistory -1/0 (8,192 B heap)
- **auth_* (3):** group 2 · permission -1/3 · group_permissions -1/2
- **django_* (5):** admin_log 42,347/673 · content_type 66 · migrations -1/2 · session 228/13 · site -1/0 (8,192 B heap)
- **locations_* (2):** store 22 · store_languages 23
- **otp/2FA (4):** otp_totp_totpdevice 13 · otp_static_staticdevice 1 · otp_static_statictoken 10 · two_factor_phonedevice 0/0
- **others (11):** webhooks_webhookconfig 1 · webhooks_webhookmessage 1,629/130 · remote_url_config_remoteurlconfig 4 · emapi_generics_client_mobileappplatformversion 16 · mobile_app_client_config 0/0 · notifications_emailtemplateconfiguration -1/0 (8,192 B heap + 8,192 B TOAST) · assets_image 1 · assets_imagetag 1 · dashboard_userdashboardmodule 78 · jet_bookmark 0/0 · jet_pinnedapplication 0/0

Total: 23 + 17 + 9 + 4 + 6 + 3 + 5 + 2 + 4 + 11 = **84**.

## Relations

All FKs below were read from `pg_constraint` (Q3, Q17).

**Audit FKs.** There are 94 `created_by_id`/`modified_by_id` FKs to `users_user` across 47 tables (Q13). Interpret them per table:
- **Catalog and config tables** (`brands_brand` and children, `configurations_*`, `core_*`, `brands_plusoffer`, `webhooks_webhookconfig`): the author is most likely an admin/staff user or a sync service account.
- **`users_useravailedoffer`**: `created_by_id` is NOT NULL and has its own index. The row is created in the consumer flow, so `created_by_id` is most likely **the end user themself** (often equal to `user_id`) or a service account. It is not staff. Verify with `count(*) filter (where created_by_id = user_id)` once readable.
- **`brands_favouritebrand`** has **no** audit columns, so the only actor is `user_id`.
- **`users_user`** has no `created_by`.

Other relations:
- `brands_brand` → `core_currency`, `brands_category` (primary), `locations_store`, `brands_retailers` (company)
- `brands_brand_{denomination,denomination_range,images,categories,search_tags}` and `brands_tag_brand` → `brands_brand`
- `brands_generic_brand_config.brand_id` (UNIQUE) → brand; `brands_generic_brand_item` → `brands_generic_brand_config` and `brands_brand`
- `brands_plusoffer` → `brands_brand`, `core_country`
- `brands_plusoffer_happy_cards` (auto-M2M, UNIQUE pair), `brands_hasofferbrands` (through-table, no UNIQUE; FKs `offer_id`→`brands_plusoffer` and `brand_id`→`brands_brand`, both DEFERRABLE INITIALLY DEFERRED, Q29), `brands_offerpromocode` → `brands_plusoffer` and `brands_brand`
- `brands_offer` → brand, country, currency (x2), `brands_productchannel`; `brands_offer_happy_cards` → `brands_offer` and brand
- `users_useravailedoffer` → `users_user` (user_id, created_by_id, modified_by_id), `brands_plusoffer`
- `brands_favouritebrand` → `users_user`, `brands_brand` (UNIQUE pair)
- `otp_*`, `two_factor_phonedevice`, `users_passwordhistory`, `users_usermetadata` (UNIQUE), `dashboard_userdashboardmodule`, `jet_*` → `users_user`
- `auth_permission` → `django_content_type`; `auth_group_permissions` → `auth_group`, `auth_permission`; `users_user_groups` → `auth_group`
- `django_admin_log` → `django_content_type`, `users_user`
- `brands_storelocation` → brand, `core_community`; geography chain `core_community`→`core_city`→`core_stateprovince`→`core_country`
- `configurations_*` → `locations_store`, `configurations_platform`, `configurations_color`, `django_content_type` (generic slider items)
- `core_currencyexchangerate` → `core_basecurrency` (base_currency_id), `core_currency` (foreign_currency_id)
- `locations_store_languages` → `locations_store`, `core_language`
- `notifications_emailtemplateconfiguration.language_id` → `core_language` (Q29)
- `configurations_shopcategorybrand` → `configurations_shopcategory` (`shop_category_id`), `brands_brand` (Q29); `configurations_shopcategory` has only audit FKs (no store, no platform)
- `mobile_app_client_config` has only audit FKs; its `platform` is a logical (no-FK) link to `users_user.platform` and `emapi_generics_client_mobileappplatformversion.app_platform`
- **Logical, no FK:** `emapi_generics_client_mobileappplatformversion.app_platform` ↔ `users_user.platform` (many config rows per platform, no UNIQUE, so reduce to one row per platform before joining), and the app-version comparison is done by application code. The OS-version gate needs the user's OS version, which is not a column on `users_user`; it can only be parsed from `user_agent` (PII-restricted).
- Kafka and webhook message tables have **no FKs**. Their links to other entities are inside `data` / `message` jsonb, which I could not inspect.

## Schema chronology (relative order, not timestamps)

Built from `pg_class.oid` order of the 84 tables (Q27). PostgreSQL assigns oids from one counter as objects are created, and the counter shows no sign of wrapping here (the highest table oid is 42.1M, far below 2^32, and the order matches the feature dependencies, e.g. `users_useravailedoffer` after `brands_plusoffer`), so **a higher oid means the table was created later**. Gaps between oids come from every other object created in between (indexes, sequences, TOAST tables, other databases on the cluster), so **the gaps are not proportional to time and these are not dates** [STRUCTURAL]. Real dates need `django_migrations.applied` [NEEDS-GRANT: `django_migrations.app`, `name`, `applied`]. The `rewritten` column is `relfilenode <> oid`: the table's storage was replaced after creation (TRUNCATE, VACUUM FULL, CLUSTER, or an ALTER that rewrites the table) [STRUCTURAL].

| Wave (oid range) | Tables created, in order | Reading |
|---|---|---|
| 1 (29,440–30,979) | django_migrations, content_type, auth_*, **users_user** (rewritten), users_user_groups/permissions, django_admin_log, assets_*, core_language/currency/country/country_languages/city/stateprovince/community, locations_store(+languages), **brands_brand**, generic_brand_config, tag, tag_brand, occasion, generic_brand_item, category, brand_search_tag, brand_images, denomination_range, denomination (rewritten), brand_categories, brand_search_tags, **brands_offer** (rewritten), offer_happy_cards, favouritebrand, retailers, productchannel, storelocation, configurations_banner/bannertype/banneritem/bannerimage, dashboard (rewritten), jet_*, otp_*, remote_url_config, django_session, two_factor_phonedevice, webhooks_webhookmessage, webhooks_webhookconfig | Initial schema: users, geography, catalog, the **legacy `brands_offer`**, banners, admin, 2FA and webhooks all created together |
| 2 (59,152–59,160) | core_basecurrency, core_currencyexchangerate | Exchange-rate matrix added |
| 3 (137,014–137,024) | configurations_carousel, carouselitem | Carousel added |
| 4 (2,516,505–2,516,597) | configurations_color, homepageslider, **myshopcategory**, slidertype, platform, myshopcategorybrand, myshopcategory_platforms, homepageslideritem, homepageslider_platform_type | Home-page slider and **"my shop" category** system |
| 5 (8,808,246) | emapi_generics_client_mobileappplatformversion | **Forced-upgrade gate #1** (platform-level required/latest version plus the OS-version gate columns; whether those columns were added in a later migration is not visible from oids) |
| 6 (12,750,239–12,750,307) | **brands_plusoffer** (rewritten), plusoffer_happy_cards, kafka_plusofferkafkadatalog | **Plus Offers launched**, with its admin-edited eligibility M2M and its Kafka feed in the same release |
| 7 (14,655,011) | users_useravailedoffer | **Offer avails** added after the offer model |
| 8 (16,158,996–16,159,034) | brands_offerpromocode, mobile_app_client_config | **Promo codes** for plus offers, and **forced-upgrade gate #2** (per-client version expiry) |
| 9 (20,302,605–20,302,639) | **brands_hasofferbrands**, kafka_emapistoreskafkadatalog, kafka_atworkkafkadatalog | **Sync wave**: the timestamped offer↔brand through-table was created next to the emapi-stores and at-work Kafka logs, and `kafka_emapistoreskafkadatalog` reuses the `kafka_plusofferapidatapublisherlog_id_seq` sequence (renamed table). This supports the reading that `hasofferbrands` is maintained by a sync/publish job, not by admins [STRUCTURAL] |
| 10 (32,060,301) | kafka_webstoreskafkadatalog | Web-stores feed added (now nearly dead, 18 rows est.) |
| 11 (36,404,056–36,404,067) | **configurations_shopcategory**, shopcategorybrand | **Successor of `myshopcategory`** (wave 4): same core columns plus layout flags (see Section 4) [STRUCTURAL] |
| 12 (41,994,079–41,994,087) | users_usermetadata, users_passwordhistory | **Password policy** (expiry warning, rotation, reuse history). First tables with IDENTITY ids |
| 13 (42,121,684–42,121,710) | notifications_emailtemplateconfiguration, django_site | **Email notification templates** (and the Django sites framework, likely pulled in by the same feature). IDENTITY ids |

**Relative order of features** [STRUCTURAL]: legacy offers (1) → exchange rates (2) → carousel (3) → sliders and "my shop" (4) → app-upgrade gate (5) → **plus offers** (6) → offer avails (7) → **promo codes** and client version expiry (8) → offer↔brand sync and emapi/at-work Kafka logs (9) → web-stores feed (10) → new shop categories (11) → **password policy** (12) → **email notifications** (13).

**Rewritten tables** (5): `users_user`, `brands_brand_denomination`, `brands_offer`, `dashboard_userdashboardmodule`, `brands_plusoffer`. Django migrations that change a column type or add a column with a volatile default rewrite the table; so does a VACUUM FULL. `brands_brand` was **not** rewritten, which fits its 180.9 MB heap: it has never been compacted since creation [STRUCTURAL].

## Lifecycle States

> **BLOCKED — needs grant:** every column listed below, via the blanket grant (a) and the views in the Grant request. Re-verified 0/84 in Q26.

**I could not measure any value distributions because the role has no SELECT privilege (0/84, Q13, Q26).** These are the enum-like columns found [STRUCTURAL]; every distribution is [NEEDS-GRANT]. Each needs `SELECT col, count(*) ... GROUP BY 1` once access is granted:

- `kafka_*kafkadatalog.status` varchar(20)! is the consumer processing state (likely pending/success/failed). This is the most important one.
- `brands_offerpromocode.status` varchar(20)!: promo-code lifecycle (available/used/expired?)
- `brands_plusoffer`: `offer_mode`, `offer_type`, `offer_channel`, `funding_method`, `funded_by`, `budget_type`, `sponsor_payment_threshold_type`, `reason_code`, `is_active`, `has_budget_exceeded`. The mechanic is derived from which of `purchase_offer_header` / `spend_offer_header` is non-null.
- `brands_offer`: `offer_base`, `offer_type`, `is_active`, `has_budget_exceeded`
- `brands_brand`: `redemption_type`, `classification`, `generic_type`, `is_active`, `is_launched`, `is_obsolete`, 12 `visible_to_*` channel flags, and the redemption-friction flags
- `brands_generic_brand_config`: `generic_type`, `process_mode`
- `brands_brand_denomination_range.range_type`; `brands_tag.tag_type`, `brand_ordering`
- `users_user`: `platform`, `type`, `language_code`, `country_of_residence`, `is_active`, `is_enabled`, `is_deleted`, `is_fraud`, `trusted_user`, `email_verified`, `phone_number_verified`, `is_native_user`, `is_app_user`, `custom_profile_img`
- `emapi_generics_client_mobileappplatformversion.app_platform`, `optional`, `os_version_check_enabled`; `mobile_app_client_config.client_name`, `platform`, `expiry_date` (expired vs future)
- `brands_brand.non_expirable`, `validity_months`, `validity_days` (validity policy); `brands_plusoffer.is_generic_promo_code` × `is_unique_promo_code`
- `users_user.new_password_policy`; `users_usermetadata.has_received_expiry_warning`
- `configurations_shopcategory.is_interest`, `is_slider`, `is_horizontal_scroll`, `row_count`, `column_count`
- `notifications_emailtemplateconfiguration.email_type`, `template_code`, `language_id`, `is_active`
- `brands_brand` redemption-mode booleans `has_code`/`has_pin`/`has_redeem_url` (combination = mode), `buy_for_yourself`, `can_be_swapped`
- `brands_plusoffer.has_min_max_restriction`, `sponsor_payment_threshold_type` varchar(10)!
- `configurations_homepageslider.is_for_guests` × `is_for_logged_in_users`; `brands_tag.is_visible`, `visible_to_ecommerce_app`
- `webhooks_webhookmessage.type`; `configurations_banner.redirect_type` (2-char code); `configurations_carouselitem.type`
- `django_admin_log.action_flag` (Django standard: 1 add, 2 change, 3 delete)

## Time Coverage & Trends

> **BLOCKED — needs grant:** min/max and monthly counts on every time column below (blanket grant (a) plus the `atlas_users_user`, `atlas_kafka_*` and `atlas_webhookmessage` views).

**Not measurable** (no SELECT). The only time ordering available is the **relative table-creation order** in the Schema chronology section [STRUCTURAL]. This is the actual time-column inventory per table from `pg_attribute` (Q13a). 67 of 84 tables have at least one date/timestamp column:

| Table(s) | Time columns |
|---|---|
| 51 catalog/config/core/location/offer tables (brands_* except the auto-M2Ms, configurations_* except the 2 M2Ms, core_* except country_languages, locations_store, assets_*, webhooks_webhookconfig, remote_url_config, notifications, users_useravailedoffer, users_passwordhistory, users_usermetadata) | `created_on`, `modified_on` (tstz NOT NULL) |
| `emapi_generics_client_mobileappplatformversion`, `mobile_app_client_config` | `created_on`, `modified_on` (tstz, **nullable**); mobile_app_client_config also `expiry_date` |
| `users_user` | `date_joined`!, `last_login`, `modified_on`!. **No `created_on`** |
| `kafka_*kafkadatalog` (4) | `start_timestamp`!, `completed_timestamp`. **No `created_on`/`modified_on`** |
| `webhooks_webhookmessage` | `received_at`! only |
| `brands_plusoffer` | also `start_date`/`end_date` (tstz!, indexed), `promo_code_end_date` |
| `brands_offer` | also `start_date` (date!), `end_date` (date) |
| `configurations_carouselitem` | also `start_time`, `end_time` (scheduling) |
| `users_usermetadata` | also `password_last_changed` |
| `django_admin_log` | `action_time`! |
| `django_migrations` | `applied`! |
| `django_session` | `expire_date`! |
| `otp_totp_totpdevice`, `otp_static_staticdevice` | `created_at`, `last_used_at`, `throttling_failure_timestamp`; `two_factor_phonedevice` only `throttling_failure_timestamp` |
| `jet_bookmark`, `jet_pinnedapplication` | `date_add` |
| **No time column (17):** `brands_plusoffer_happy_cards`, `brands_offer_happy_cards`, `brands_brand_categories`, `brands_brand_search_tags`, `configurations_homepageslider_platform_type`, `configurations_myshopcategory_platforms`, `core_country_languages`, `locations_store_languages`, `users_user_groups`, `users_user_user_permissions`, `auth_group`, `auth_permission`, `auth_group_permissions`, `django_content_type`, `django_site`, `otp_static_statictoken`, `dashboard_userdashboardmodule` | none |

Indexing affects how cheaply trends can be computed: `users_user.date_joined`, `last_login` and `modified_on` are **not indexed**, and the `kafka_*` timestamps are **not indexed**. Trends on those need `TABLESAMPLE SYSTEM (1)` or pkey id-range slicing. `brands_plusoffer.start_date`/`end_date` are indexed.

## Behavior Signals

> **BLOCKED — needs grant** for every measurement in this table. The signal columns and table scales are [STRUCTURAL] (column inventory and `reltuples` estimates); what each signal *shows* is [NEEDS-GRANT] on the columns named. View names refer to the Grant request section.

| Signal | Table | Scale (estimate) | Notes |
|---|---|---|---|
| Account creation, login recency, platform/app version | `atlas_users_user` | 992,399 users | `date_joined`, `last_login`, `platform`, `app_version`, `language_code`, `country_of_residence`. Only the latest value per user is stored, not an event history |
| Profile-update recency | `atlas_users_user.modified_on` | 992,399 | Last write to the user row, from profile edits, app-version refreshes or service updates. Its distribution relative to `last_login` shows how often profiles are touched |
| Profile completion | `atlas_users_user.custom_profile_img` | — | Share of users who uploaded their own avatar (aggregate only) |
| Forced-upgrade exposure (app, gate #1) | `atlas_users_user.app_version` × `emapi_generics_client_mobileappplatformversion` | 16 config rows (several per platform) | Share of users per platform below `required_version` (forced) or below `latest_version` with `optional=true`, against **one current config row per platform** |
| Forced-upgrade exposure (version sunset, gate #2) | `mobile_app_client_config` × `atlas_users_user` | **0 rows (0 heap bytes, Q20a)** | Per (client_name, platform, version) `expiry_date`. Empty today, so no version is being retired through this table [STRUCTURAL]. Once rows exist, count users on an expired (platform, version). `users_user` has no `client_name`, so the client dimension cannot be joined from this database [STRUCTURAL] |
| Forced-upgrade exposure (OS) | `emapi_generics_client_mobileappplatformversion.os_version_check_enabled`, `required_os_version` | 16 config rows | Which platforms gate on OS version and at what minimum. User-side OS version is not a column (only inside `user_agent` varchar(100), truncated), so the affected-user share is not directly measurable |
| Social / SSO login adoption | `atlas_users_user` | — | `has_sub`, `has_apple_id`, `has_google_id`, `has_facebook_id` (derived booleans, aggregate only) |
| Verification friction | `atlas_users_user` | — | `email_verified`, `phone_number_verified` |
| Fraud / trust | `atlas_users_user` | — | `is_fraud`, `trusted_user`, `is_enabled`, `is_deleted` |
| Password rotation | `users_usermetadata` × `atlas_users_user.new_password_policy` × `atlas_passwordhistory` | ≤ ~110 metadata rows (1 page) | Users on the new policy, warned before expiry, and who changed their password after the warning |
| Brand interest | `brands_favouritebrand` | 19,821 | User→brand favourites with timestamp; actor is `user_id` (no audit FK) |
| Offer availed (claim/activation) | `users_useravailedoffer` | 6,487 | User availed a plus offer, with timestamp. **Not a proven spend event**: no amount, order or channel column. Repeat avails per (user, offer) are allowed (no UNIQUE) and measurable; `plus_offer_id` is nullable, so orphan avails are possible. `created_by_id` is likely the user or a service account |
| Campaign mechanics and budget/usage | `brands_plusoffer` | 378 offers | purchase vs spend mechanic, `usage_count`, `has_budget_exceeded`, budget amounts, placement orders |
| Promo-code inventory | `brands_plusoffer` × `atlas_offerpromocode` | 378 offers, 72 codes | Codes per offer and per `status` against `promo_code_threshold` and `promo_code_end_date`, split by `is_generic_promo_code`/`is_unique_promo_code` |
| Brand redemption difficulty | `brands_brand` | 6,610 brands | `require_mobile_verification`, `allow_any_country_mobile_verification`, `pin_redeemable_location_required`, `can_be_split`, `minimum_usage_amount`, `redeemable_brands`; relief via `can_be_swapped` |
| Gift-card validity policy | `brands_brand.non_expirable`, `validity_months`, `validity_days`, `expiry_details` | 6,610 brands | Non-expiring vs months vs days validity, by `classification` |
| Recipient instructions coverage | `brands_brand.receiver_redemption_details_en/_ar` | 6,610 brands | Active, launched brands with no recipient redemption instructions in English or Arabic |
| Redemption mode | `brands_brand.has_code/has_pin/has_redeem_url` | 6,610 brands | Code, PIN, URL or combined delivery; the mix determines recipient steps |
| Self-purchase enablement | `brands_brand.buy_for_yourself` | 6,610 brands | Share of catalog open to self-gifting vs gift-only |
| Merchandising exposure | `configurations_homepageslider`, `carouselitem`, `banneritem`, `brands_tag` | 56 sliders, 98 carousel items, 147 tags | Guest vs logged-in personalization (`is_for_guests`/`is_for_logged_in_users`), scheduled carousel items (`start_time`/`end_time`), wide/video creatives (`is_wide_image`, `video_url`), tag visibility on the app (`visible_to_ecommerce_app`), banner `config` jsonb |
| Shop-category layout | `configurations_shopcategory` (+ `shopcategorybrand`) | 16 categories, 6,186 links | Layout mix: `is_interest`, `is_slider`, `is_horizontal_scroll`, `row_count` × `column_count`; brands per category |
| Email trigger configuration | `notifications_emailtemplateconfiguration` | unknown (1 page) | Inventory of `email_type` × `language_id` × `template_code`, active or not: which lifecycle emails are configured, and any trigger missing its Arabic or English template |
| Multi-brand card breadth | `brands_generic_brand_item` | ≈158 rows/config (est.) | Breadth of choice inside a generic card. Rows, not distinct brands (duplicates, inactive and null-keyed rows possible); exact fan-out needs `generic_config_id`, `brand_id`, `is_active` |
| Promo code issuance | `atlas_offerpromocode` | 72 | `status`. Not linked to users (no user_id/redeemed_at); duplicates possible (no UNIQUE on promo_code), measured through `promo_code_md5` |
| 2FA (staff) | `otp_*` | 13 TOTP, 1 static | `throttling_failure_count`, `last_used_at` |
| Admin catalog operations | `atlas_django_admin_log` × `django_content_type` | 42,347 log rows, 66 models | Merchandising and catalog change cadence per model |
| Deploy cadence | `django_migrations` | ~<100 est. | `applied` per month; would put dates on the Schema chronology waves |
| Cross-service sync events | `atlas_kafka_*` | about 2.87M total | Throughput, latency (`completed - start`), failures (`has_error`) |

Not present in this database: sessions and page views (other than admin `django_session`), baskets, orders, payments, gifts, redemptions of cards, referrals, and notification send events (`notifications_emailtemplateconfiguration` is configuration, not a send log; its row count is unknown) [STRUCTURAL].

## Friction & Errors

> **BLOCKED — needs grant.** None of these could be quantified. Each bullet names the columns it needs; the queries are in "Queries to run once SELECT is granted" and use the view columns from the Grant request. Every bullet is a [NEEDS-GRANT] hypothesis resting on [STRUCTURAL] schema facts.

- **Kafka consumer failure rate**: `status` distribution plus the share of rows with `has_error` in each of the 4 `atlas_kafka_*` views. Also processing latency `completed_timestamp - start_timestamp` and the stuck count (`completed_timestamp IS NULL` and older than 1h). Use TABLESAMPLE or pkey id ranges; there are no secondary indexes. *Needs:* `kafka_*.id, status, start_timestamp, completed_timestamp` plus derived `has_error`.
  - **Structural limit** [STRUCTURAL]: the Kafka log tables have **no topic, partition, offset, message-key, retry or attempt column** (Q19; the columns are only `id, data, status, error_data, start_timestamp, completed_timestamp`). Retry and idempotency behaviour cannot be read from columns. Detecting a re-delivered or retried message means comparing `data_md5` (a view column computed as `md5(data::text)`) or a whitelisted business key extracted from `data`. The role never reads `data` itself.
- **Webhook errors**: share of `atlas_webhookmessage` rows with `has_error_message`, by `type`. Retention caveat: the table was purged, so these rates cover only the retained window. *Needs:* `webhooks_webhookmessage.id, type, received_at` plus derived `has_error_message`.
- **Forced-upgrade friction (gate #1)**: share of users per platform whose `app_version` is below `required_version`. Needs semantic version comparison, e.g. `string_to_array(app_version,'.')::int[]`, with both sides guarded by a numeric regex, and **one config row per platform** (latest `modified_on`), because the config table has several rows per platform and no UNIQUE(app_platform); joining all rows would multiply users. *Needs:* `atlas_users_user.platform, app_version`; `emapi_generics_client_mobileappplatformversion.*`.
- **Version sunset (gate #2)**: `mobile_app_client_config` can expire a (client, platform, version) on `expiry_date`. It is **empty today** (0 heap bytes, Q20a), so this gate adds no friction now [STRUCTURAL]. Two gates that can disagree (a version above `required_version` but past its `expiry_date`, or the reverse) are a consistency risk to check once rows appear. There is no `client_name` on `users_user`, so user exposure can be computed per (platform, version) only.
- **OS-level forced upgrade**: `os_version_check_enabled` and `required_os_version` gate devices on OS version. The config side is measurable; the user side is not (no OS-version column; only `user_agent`, which is PII-restricted and **truncated at varchar(100)**). A derived `os_family`/`os_major_version` view column would close part of this gap, but values parsed from a truncated UA are lossy (see Grant request item b).
- **Brand redemption friction**: a flag matrix by `classification`. A card is harder to redeem when it requires mobile verification without `allow_any_country_mobile_verification`, requires location-bound PIN redemption, sets `minimum_usage_amount`, or has `can_be_split=false`. `can_be_swapped=true` relieves friction (the recipient can switch brand), so report hard-to-redeem brands with and without swap. Cut by redemption mode (`has_code`/`has_pin`/`has_redeem_url`) and `buy_for_yourself`. *Needs:* `brands_brand` (blanket grant a).
- **Gift-card validity / expiry friction** (new, rev 4): short validity is a recipient friction (cards expire before use). By `classification`: share of `non_expirable`, and the distribution of `validity_months`/`validity_days` among expiring brands; brands where both are 0 but `non_expirable=false` (no usable validity) and brands where both are set (conflicting units) are hygiene issues. `expiry_details` jsonb keys show what extra expiry text is stored. *Needs:* `brands_brand.non_expirable, validity_months, validity_days, expiry_details, classification, is_active, is_launched`.
- **Missing recipient redemption instructions** (new, rev 4): among `is_active and is_launched and not is_obsolete` brands, the share whose `receiver_redemption_details_en` or `_ar` is null or blank. The recipient then gets a code with no how-to, the most direct catalog-caused redemption friction. Cross with redemption mode and `pin_redeemable_location_required`. *Needs:* `brands_brand.receiver_redemption_details_en, receiver_redemption_details_ar` (only a null/blank test; the text itself is not needed).
- **Password-rotation funnel** (new, rev 4): users with `new_password_policy=true` → with a `users_usermetadata` row → with `password_last_changed` → `has_received_expiry_warning=true` → changed again after the warning (a `users_passwordhistory` row created after the warning date). The metadata table is only 1 heap page, so the funnel is small or new [STRUCTURAL]. *Needs:* `atlas_users_user.id, new_password_policy`; `users_usermetadata.user_id, password_last_changed, has_received_expiry_warning, modified_on`; `atlas_passwordhistory.user_id, created_on` (no `password_hash`).
- **Promo-code inventory vs threshold** (new, rev 4): per plus offer, available codes (`status` = the available value) against `promo_code_threshold`, and offers past `promo_code_end_date` that still hold available codes. Split by `is_generic_promo_code` (one shared code, so count should be 1) and `is_unique_promo_code` (one per user, so inventory can run out). An offer flagged unique with 0 available codes, or generic with several distinct codes, is a friction or hygiene flag. *Needs:* `brands_plusoffer.id, is_generic_promo_code, is_unique_promo_code, promo_code_threshold, promo_code_end_date, is_active, start_date, end_date`; `atlas_offerpromocode.offer_id, status, promo_code_md5`.
- **Offer budget exhaustion**: `brands_plusoffer.has_budget_exceeded`, and `usage_count` compared with the limits, split by mechanic, by `has_min_max_restriction` and by `sponsor_payment_threshold_type`. Campaign liveness must cross `is_active` with the `start_date`/`end_date` window (an active flag outside the window, or inside the window but inactive, are both hygiene issues). *Needs:* `brands_plusoffer` (blanket grant a).
- **Offer avail anomalies**: repeat avails per (user, offer), orphan avails with `plus_offer_id IS NULL`, and duplicate promo codes (`promo_code_md5`). *Needs:* `users_useravailedoffer` (blanket grant a), `atlas_offerpromocode.promo_code_md5`.
- **Account friction**: unverified email/phone rates, `is_fraud` rate, disabled/deleted rate. *Needs:* `atlas_users_user` flags.
- **2FA throttling**: `throttling_failure_count > 0` on the staff devices. *Needs:* `atlas_otp_*` (no `key`/`token`).
- **Catalog hygiene** (supply-side friction): brands that are active but not launched, or obsolete but still visible. *Needs:* `brands_brand`.

## Cross-DB Keys

These are identified by name and type only [STRUCTURAL]. I could not read any ranges (min/max; 0/83 sequences readable), so every join below is [NEEDS-GRANT] until overlap is tested.
- `users_user.id` bigint (range unknown): local user id. Other YGG databases (`ygag_ecom_users_db`, `ygag_ecom_orders_db`, wallet, rewards) probably have their own user ids. **The join key is more likely `users_user.sub` varchar(150)**, a Cognito-style subject, not indexed here. `username` (UNIQUE) and `legacy_auth_code[]` are candidates for legacy system joins.
- `brands_brand.code` varchar(16) UNIQUE and `brands_brand.id` bigint: the **brand key** shared with ecom orders/gifts, giftshop, merchant console, at-work, plus-offers and mycredits. `gencode` (brand and denomination) looks like a supplier/product code.
- `brands_plusoffer.code` varchar(10) UNIQUE: the plus-offer campaign key, likely shared with `ygag_plusoffers_db` and the `kafka_plusofferkafkadatalog` payloads.
- `brands_offer.code`, `brands_retailers.code` and `ref_code`, `brands_storelocation.code`
- `locations_store.code`, `core_country.code` (ISO2), `core_currency.code` (ISO 4217), `core_language.code`: shared reference codes
- `mobile_app_client_config.reference_id` and `emapi_generics_client_mobileappplatformversion.reference_id` (uuid, UNIQUE): likely mirrored from `ygag_emapi_generics_db`
- Kafka `data` jsonb probably carries order, brand and user references from the at-work, plus-offer and web-stores services (not inspected)

## PII

These are column names only; I read no values.
- `users_user`: `email`, `secondary_emails`, `phone_number`, `name`, `middle_name`, `nickname`, `username`, `birthdate`, `gender`, `location`, `ip_address`, `user_agent`, `picture`, `apple_id`, `google_id`, `facebook_id`, `sub`, `legacy_auth_code`, `password` (hash)
- `mobile_app_client_config.client_name` is not PII (an app/client identifier)
- `users_passwordhistory.password_hash`
- `two_factor_phonedevice.number` and `key`; `otp_totp_totpdevice.key`; `otp_static_statictoken.token`
- `brands_storelocation.contact_number`, `contact_email`, `address*` (business contact, but treat as PII)
- `webhooks_webhookmessage.ip_address` and `message`/`error_message` jsonb (payloads may contain PII); `webhooks_webhookconfig.webhook_key`, `sender_ips`
- `kafka_*.data` and `error_data` (payloads likely contain user and order PII)
- `notifications_emailtemplateconfiguration.to_emails`
- `remote_url_config_remoteurlconfig.api_key` and `api_secret` (**credentials**)
- `brands_offerpromocode.promo_code` (redeemable secret)
- `django_session.session_data`; `django_admin_log.object_repr` and `change_message` (may embed names or emails)

## Data Quality

- **Access**: 0/84 tables and 0/83 sequences are readable (Q13). This blocks the whole analysis. Re-verified in Q26 (rev 4). See the Grant request section.
- **Empty tables (0 heap bytes, Q20a)**: only `configurations_bannerimage`, `jet_bookmark`, `jet_pinnedapplication`, `mobile_app_client_config` and `two_factor_phonedevice`.
- **Row count unknown, 1 page allocated**: `users_usermetadata`, `users_passwordhistory`, `django_site` and `notifications_emailtemplateconfiguration` each have `pg_relation_size` = 8,192 B (one heap page) but `relpages=0` and `reltuples=-1` because they were never analyzed. `notifications_emailtemplateconfiguration` also has an 8,192 B TOAST relation. Emptiness is unproven; they may hold a few rows (Django normally keeps 1 row in `django_site`). Nearly dead: `kafka_webstoreskafkadatalog` (18), `assets_image`/`assets_imagetag` (about 1), `webhooks_webhookconfig` (1), `configurations_bannertype` (1).
- **Never analyzed** (`reltuples=-1`): `brands_offer`, `brands_offer_happy_cards`, `brands_occasion`, `core_stateprovince`, `configurations_banneritem`, `configurations_homepageslider_platform_type`, `users_user_user_permissions`, `users_usermetadata`, `users_passwordhistory`, `auth_permission`, `auth_group_permissions`, `django_migrations`, `django_site`, `notifications_emailtemplateconfiguration`. Planner estimates for these are unreliable.
- **Retention and churn (size far exceeds what row counts imply)**, Q15/Q18:
  - `webhooks_webhookmessage`: an 8.15 MB pkey against a 1.06 MB heap for about 1.6k rows. Historical messages were purged, so today's rows understate traffic.
  - `brands_hasofferbrands`: about 882 B heap per 5-col row, and a 26.6 MB pkey for about 40k rows (reltuples re-read in Q31: 40,079, down from 49,787 in rev 3 with unchanged pages, so churn continues). Rows are repeatedly deleted and re-inserted, probably by a sync job [STRUCTURAL].
  - `brands_generic_brand_item` (new, rev 4, Q30/Q31): heap 57.3 MB is normal (≈107 B per 10-column row), but the pkey is 25,395,200 B against ≈12 MB expected for 533k bigint keys (533,305 × 20 B / 0.9 fill), so ≈2x. The other indexes are normal-sized (`generic_config_id` 10.1 MB, `brand_id` 9.2 MB, audit FKs 6.5 and 6.7 MB). An oversized pkey with a normal heap is the pattern of rows being deleted and re-inserted with new ids (the pkey keeps sparse pages for old id ranges while the heap reuses freed space), consistent with `auto_brand_sync` rebuilding item lists [STRUCTURAL; NEEDS-GRANT on `brands_generic_brand_item.id, created_on` per `generic_config_id` to confirm].
  - `brands_plusoffer_happy_cards`: about 204 B heap per 3-col row, and a 27.6 MB pkey. Moderate churn from admin re-saves (Django clears and re-adds M2M rows).
  - `brands_brand`: 180.9 MB heap (plus 32.8 MB TOAST) for 6.6k rows. Update bloat.
  - `users_user`: 478.3 MB of indexes over a 283.6 MB heap. **This is redundant indexing, not churn** (Q22b): 93% (446.8 MB) is UNIQUE + `_like` pairs on `username`, `email` and `phone_number` plus a `(username, is_enabled)` composite. Dropping the composite (covered by the UNIQUE username index for lookups) or unused `_like` indexes would save up to about 235 MB on the username side alone; this is a primary-side decision, noted only.
- **Duplicated concepts**:
  - Two offer models: `brands_offer`/`brands_offer_happy_cards` (legacy) and `brands_plusoffer`/`brands_plusoffer_happy_cards`.
  - Two plus-offer↔brand link tables, now distinguished: `happy_cards` is the admin-edited eligibility M2M; `hasofferbrands` is a timestamped, sync-maintained through-table with no uniqueness guarantee.
  - Two ordering columns: `order_number` and `ecom_order_number`.
  - Two validity columns: `validity_months` and `validity_days`.
  - Two storefront category systems: `shopcategory` and `myshopcategory`.
  - Two tagging systems: `brands_tag` and `brands_brand_search_tag`.
- **Missing uniqueness** (Q17, Q20, Q22): duplicates are possible in all of these.
  - `brands_hasofferbrands`: no UNIQUE(offer_id, brand_id)
  - `core_currencyexchangerate`: no UNIQUE(base_currency_id, foreign_currency_id)
  - `users_useravailedoffer`: no UNIQUE(user_id, plus_offer_id), and `plus_offer_id` is nullable (orphan avails allowed)
  - `brands_offerpromocode`: no UNIQUE(promo_code)
  - `brands_generic_brand_item`: no UNIQUE(generic_config_id, brand_id), and both columns are nullable
  - `emapi_generics_client_mobileappplatformversion`: no UNIQUE(app_platform); several config rows per platform
  By contrast, `brands_offer_happy_cards`, `brands_plusoffer_happy_cards` and `brands_favouritebrand` do enforce their pair uniqueness.
- **Schema drift**: `kafka_emapistoreskafkadatalog` draws its ids from `kafka_plusofferapidatapublisherlog_id_seq` (the table was renamed). The typo'd FK column `myshop_cateogory_id` is in `configurations_myshopcategorybrand`.
- **Missing indexes for analytics**: the `kafka_*` tables have no index on `status` or `start_timestamp`. `users_user` has none on `date_joined`, `last_login`, `modified_on` or `sub`. Time-range analytics on these need sampling.
- **Kafka log lacks delivery metadata**: there is no topic/partition/offset/key column, so dedup and retry analysis requires payload hashing.
- **Loose types**: `users_user.birthdate` is varchar(50), not a date. `gender` is free varchar(10). `app_version` is varchar(60), so version comparison needs parsing.
- **Inconsistent audit columns**: `emapi_generics_client_mobileappplatformversion` and `mobile_app_client_config` have nullable `created_on`/`modified_on`, unlike every other business table.
- **Mixed id generation** (Q28, Q32) [STRUCTURAL]: the 4 newest tables (`users_usermetadata`, `users_passwordhistory`, `notifications_emailtemplateconfiguration`, `django_site`; waves 12–13 in the Schema chronology) use `GENERATED BY DEFAULT AS IDENTITY` ids (`attidentity='d'`, with sequences `*_id_seq`), while the other 80 use `bigserial`-style `nextval()` defaults. This is what Django 4.1+ emits for new tables, so the service moved to Django ≥4.1 between waves 11 and 12. BY DEFAULT identity still accepts explicit ids, so it does not protect against manual inserts. Any tooling that reads id ranges through `pg_get_serial_sequence` works for both kinds.
- **Unused extensions** (Q12, Q30) [STRUCTURAL]: `pg_trgm` 1.5 and `btree_gin` 1.3 are installed, but **no index uses a trigram or btree_gin operator class**. The only GIN index is `secondary_emails_gin_idx` on `users_user.secondary_emails` (a text[] with the default array opclass). Brand/tag name search therefore cannot use trigram indexes; `ILIKE '%x%'` on `brands_brand.name` is a sequential scan (cheap here at 6.6k rows but on a bloated 181 MB heap). Either the extensions are left over from a removed index or the app does search elsewhere.
- **Secrets in DB**: `remote_url_config_remoteurlconfig.api_key` and `api_secret`.
- **Replica stats are unusable**: `pg_stat_user_tables` counters are 0 on the replica (Q7). `pg_stat_database` for this database shows only `xact_commit`=228, `xact_rollback`=63, `tup_returned`=284,282, `blks_hit`=191,759 and a **null `stats_reset`** (Q25, exact at query time; the critic saw 210 / 268,451 earlier, so the counters only reflect this replica's own light read traffic, largely ours). Neither view says anything about production write activity, dead tuples or table popularity.

## Grant request

**Status: BLOCKED.** Re-verified 2026-09-29 (Q26): 0/84 tables and 0/83 sequences SELECT-able for `<emapi_login_role>` on `ygag_emapi_stores_db`. The request below is for the DBA, on the **read replica only**. It prefers PII-safe views (derived flags, hashes, buckets) over raw columns. Every view keeps the source table's `id` and time columns so that sampling by pkey range works.

**(a) Blanket table grant.** `GRANT SELECT ON ALL TABLES IN SCHEMA public TO <emapi_login_role>`, **except** the tables in (b)–(h), which get only the view (or a column-limited grant with the same columns). This covers the catalog (`brands_*` except `offerpromocode` and `storelocation`), `configurations_*`, `core_*`, `locations_*`, `users_useravailedoffer`, `users_usermetadata`, `brands_favouritebrand`, `emapi_generics_client_mobileappplatformversion`, `mobile_app_client_config`, `django_content_type`, `django_migrations`, `auth_*` and `assets_*`. None of these hold personal data beyond ids (`users_usermetadata` holds only dates and a flag).

**(b) `atlas_users_user`** (replaces `users_user`):
- Keep: `id`, `date_joined`, `last_login`, `modified_on`, `platform`, `app_version`, `language_code`, `country_of_residence`, `type`, `custom_profile_img`, `is_active`, `is_enabled`, `is_deleted`, `is_fraud`, `trusted_user`, `email_verified`, `phone_number_verified`, `is_native_user`, `is_app_user`, `new_password_policy`, `is_staff`, `is_superuser`.
- Derived: `has_sub` (`sub is not null`), `has_apple_id`, `has_google_id`, `has_facebook_id`, `has_secondary_emails` (`cardinality(secondary_emails)>0`), `has_legacy_auth_code`, `sub_md5` (`md5(sub)`, for cross-DB joins against the same hash in `ygag_ecom_users_db`), and optionally `os_family` / `os_major_version` parsed from `user_agent`.
- **Caveat on the OS columns:** `users_user.user_agent` is **varchar(100)** (Q28). Real UA strings are often longer than 100 characters, so the stored value is truncated and a parsed OS version will be missing or wrong for some rows. Report the parse-success rate next to any OS-gate number, and treat the result as a lower bound.
- Exclude: `email`, `secondary_emails`, `phone_number`, `name`, `middle_name`, `nickname`, `username`, `birthdate`, `gender`, `location`, `ip_address`, `user_agent`, `picture`, `apple_id`, `google_id`, `facebook_id`, `sub`, `legacy_auth_code`, `password`.

**(c) `atlas_kafka_atworkkafkadatalog`, `atlas_kafka_emapistoreskafkadatalog`, `atlas_kafka_plusofferkafkadatalog`, `atlas_kafka_webstoreskafkadatalog`** (one per `kafka_*` table):
- Keep: `id`, `status`, `start_timestamp`, `completed_timestamp`.
- Derived: `has_error` (`error_data <> ''`; `error_data` is `text NOT NULL`, so empty string means no error), `error_len_bucket` (width bucket of `length(error_data)`), `data_md5` (`md5(data::text)`, for duplicate-delivery detection), `data_bytes` (`pg_column_size(data)`), and a service-owner-approved set of non-PII business keys from `data` (e.g. brand code, offer code, event type).
- Exclude: `data`, `error_data`.

**(d) `atlas_webhookmessage`** (replaces `webhooks_webhookmessage`):
- Keep: `id`, `type`, `received_at`.
- Derived: `has_error_message` (`error_message is not null`), `message_md5`, `message_bytes`.
- Exclude: `message`, `error_message`, `ip_address`.

**(e) `atlas_offerpromocode`** (replaces `brands_offerpromocode`):
- Keep: `id`, `offer_id`, `brand_id`, `status`, `created_on`, `modified_on`.
- Derived: `promo_code_md5` (`md5(promo_code)`: duplicates are then `count(*) - count(distinct promo_code_md5)` without exposing a redeemable code), `promo_code_len`.
- Exclude: `promo_code`.

**(f) Column-limited or views for the remaining sensitive tables:**
- `atlas_passwordhistory`: `id`, `user_id`, `created_on`, `modified_on` (exclude `password_hash`).
- `atlas_django_admin_log`: `id`, `action_time`, `action_flag`, `content_type_id`, `object_id`, `user_id` (exclude `object_repr`, `change_message`).
- `atlas_django_session`: `expire_date` only, or a count (exclude `session_key`, `session_data`).
- `atlas_otp_totpdevice`, `atlas_otp_staticdevice`: `id`, `user_id`, `confirmed`, `created_at`, `last_used_at`, `throttling_failure_count`, `throttling_failure_timestamp` (exclude `name`, and `key` on TOTP); `atlas_two_factor_phonedevice`: `id`, `user_id`, `confirmed`, `method`, `throttling_failure_count`, `throttling_failure_timestamp` (exclude `number`, `key`, `name`); `otp_static_statictoken`: count per `device_id` only (exclude `token`). Column lists verified in Q33.
- `atlas_storelocation`: every column except `contact_number`, `contact_email`, `address`, `address_en`, `address_ar` (Q33).
- `atlas_notifications_emailtemplateconfiguration`: `id`, `email_type`, `template_code`, `language_id`, `is_active`, `created_on`, `modified_on`, plus `has_to_emails`, `to_email_count` and `template_data` **keys only** (`jsonb_object_keys`) (exclude `to_emails`, `template_data` values).
- `atlas_webhookconfig`: `id`, `name`, `is_active`, `created_on`, `modified_on`, `cardinality(sender_ips)` (exclude `webhook_key`, `sender_ips`).

**(g) Never granted:** `remote_url_config_remoteurlconfig.api_key` / `api_secret` (credentials). A view with `id`, `server`, `is_active`, the host part of `url` and timestamps is enough (Q33).

**(h) Sequences.** `GRANT SELECT ON ALL SEQUENCES IN SCHEMA public` (83 sequences, including the 4 identity sequences) so that id ranges and growth can be read without scanning.

Until (a)–(e) and (h) land, the Lifecycle, Time Coverage, Behavior Signals and Friction sections stay BLOCKED.

**Consolidated BLOCKED list** (section → what it needs):
| Section / signal | Needs grant on |
|---|---|
| All lifecycle distributions | (a) plus the enum columns listed in Lifecycle States |
| Kafka failure, latency, stuck, duplicates | (c) `status`, `start_timestamp`, `completed_timestamp`, `has_error`, `data_md5` |
| Webhook error rate | (d) `type`, `received_at`, `has_error_message` |
| Signups, login recency, profile recency, SSO, verification, fraud | (b) |
| Forced upgrade gate #1 and #2 | (b) `platform`, `app_version`; (a) `emapi_generics_client_mobileappplatformversion`, `mobile_app_client_config` |
| OS gate, user side | (b) `os_family`, `os_major_version` (lossy, see caveat) |
| Password-rotation funnel | (a) `users_usermetadata`; (b) `new_password_policy`; (f) `atlas_passwordhistory` |
| Promo-code duplicates and inventory | (e) `offer_id`, `status`, `promo_code_md5`; (a) `brands_plusoffer` promo columns |
| Validity/expiry, recipient instructions, redemption friction, catalog hygiene | (a) `brands_brand` |
| Merchandising, shop-category layout | (a) `configurations_*`, `brands_tag` |
| Email trigger inventory | (f) `atlas_notifications_emailtemplateconfiguration` |
| Admin cadence | (f) `atlas_django_admin_log`; (a) `django_content_type` |
| Chronology dates, deploy cadence | (a) `django_migrations` |
| Id ranges, growth | (h) sequences |

## Open Questions

1. **Grant access (BLOCKER).** See the Grant request section above for the exact tables, views and columns.
2. Is `users_user` here the same population as `ygag_ecom_users_db`? Which key is canonical across databases: `sub`, `username` or `id`? (A `sub_md5` on both sides would test overlap without exposing `sub`.)
3. What values does `kafka_*.status` take? With no offset or attempt column, is a retry written as a new row, or is the same row updated in place? This needs a service-owner answer or `data_md5`.
4. *(Answered from the catalog; see Section 2 and the Schema chronology.)* `brands_plusoffer_happy_cards` is the admin-edited auto-M2M of eligible brands, created with `brands_plusoffer`. `brands_hasofferbrands` is a timestamped through-table showing churn-level bloat and a 20% row-estimate swing with no page growth, created in the same wave as the emapi-stores and at-work Kafka logs, so it is likely rebuilt by a sync job. **Still open:** which job writes `hasofferbrands`, and whether `brands_offer` (initial-schema, rewritten once) is still in use.
5. Is `brands_plusoffer.usage_count` authoritative, or is `users_useravailedoffer` the redemption ledger (and does it cover all channels)? `useravailedoffer` has no amount, order or channel, and allows repeat and null-offer rows, so it looks like a claim/activation log; the spend side is probably in `ygag_plusoffers_db`. Is `useravailedoffer.created_by_id` the user or a service account?
6. What does `brands_brand.classification` mean, and what is the full set of `visible_to_*` channels? Which one maps to which YGG product (ecommerce, at-work, corporate API, gift shop, mPOS, SendATip, credit)?
7. What upstream systems send webhooks to the single `webhooks_webhookconfig`, and what retention or purge job trims `webhooks_webhookmessage`?
8. What does a second (and further) `emapi_generics_client_mobileappplatformversion` row for the same platform mean: history, or config per OS/device variant? Which row does the app read (latest `modified_on`, or some other rule)?
9. Is `mobile_app_client_config` (per-client version expiry) meant to replace or complement the platform-level `required_version` gate, and which `client_name` values are planned? It is empty today.
10. Is `configurations_myshopcategory` still served by any app version, or fully replaced by `configurations_shopcategory`?

## Appendix: SQL provenance

Everything was run through `atlasq.sh ygag_emapi_stores_db`. All size and count values in Q1–Q3, Q9–Q25 and Q26–Q33 are **exact catalog values** [STRUCTURAL]. No data query has succeeded, so nothing here is [VALIDATED]. Row counts are **estimates** (`reltuples`). Ratios such as bytes per row, 158 rows per config and 19 × 23 are arithmetic on those values, so they are **estimates**.

**Q1: table list, row estimates, sizes** (source of the original "Est. rows" figures)
```sql
select c.relname, c.reltuples::bigint est, pg_total_relation_size(c.oid) bytes, s.n_live_tup, s.last_autoanalyze::date
from pg_class c join pg_namespace n on n.oid=c.relnamespace left join pg_stat_user_tables s on s.relid=c.oid
where n.nspname='public' and c.relkind='r' order by c.relname;
```
**Q2: columns** (`information_schema.columns` returned 0 rows because of privileges, so I used pg_attribute)
```sql
select c.relname t, a.attname col, format_type(a.atttypid,a.atttypmod) typ, a.attnotnull nn
from pg_class c join pg_namespace n on n.oid=c.relnamespace join pg_attribute a on a.attrelid=c.oid and a.attnum>0 and not a.attisdropped
where n.nspname='public' and c.relkind='r' and a.attname not in ('id','created_on','modified_on','created_by_id','modified_by_id')
  and c.relname not like 'django%' and c.relname not like 'auth%' order by c.relname, a.attnum offset {0,500,1000} limit 500;
```
Note: Q2 excluded `created_on`/`modified_on`, so rev 1 assumed they existed everywhere. That assumption was wrong, and Q13a corrects it.

**Q3: FK / unique constraints**
```sql
select conrelid::regclass::text t, contype, (select string_agg(attname,',') from pg_attribute where attrelid=conrelid and attnum=any(conkey)) cols, confrelid::regclass::text ref
from pg_constraint where connamespace='public'::regnamespace and contype in ('f','u') and conrelid::regclass::text not like 'django%' and conrelid::regclass::text not like 'auth%' order by 1,2;
```
**Q4: attempted exact counts** (failed with `permission denied for table brands_plusoffer_happy_cards`)
```sql
select 'assets_image' t, count(*) n from assets_image union all ... ;  -- all tables except the 6 largest
```
**Q5: privilege check** (returned all 84 tables); superseded by Q13
```sql
select relname from pg_class where relnamespace='public'::regnamespace and relkind='r' and not has_table_privilege(oid,'SELECT') order by 1;
```
**Q6: single-table probe** (failed: permission denied for table locations_store)
```sql
select count(*) from locations_store;
```
**Q7: stats visibility** (pgstats=0, seqs=83, seqscans=0, idxscans=0, ins=0, last_analyze=null)
```sql
select (select count(*) from pg_stats where schemaname='public') pgstats, (select count(*) from pg_sequences where schemaname='public') seqs,
 (select sum(seq_scan) from pg_stat_user_tables) seqscans, (select sum(idx_scan) from pg_stat_user_tables) idxscans,
 (select sum(n_tup_ins) from pg_stat_user_tables) ins, (select max(last_analyze) from pg_stat_user_tables) la;
```
**Q8: sequence values** (all last_value NULL, privilege false)
```sql
select sequencename, last_value, has_sequence_privilege(schemaname||'.'||sequencename,'SELECT') p from pg_sequences where schemaname='public' and sequencename ~ '(users_user_id|kafka|webhook|brands_brand_id|plusoffer_id|favourite|availed)';
```
**Q9: id defaults, heap / index / TOAST sizes, DB size** (source of 1.53 GB and 3,612 MiB, and of the sequence-rename finding)
```sql
select c.relname, pg_get_expr(d.adbin,d.adrelid) def, c.relpages, c.reltuples::bigint, pg_relation_size(c.oid) heap, pg_indexes_size(c.oid) idx, coalesce(pg_total_relation_size(c.reltoastrelid),0) toast
from pg_class c left join pg_attrdef d on d.adrelid=c.oid and d.adnum=1
where c.relnamespace='public'::regnamespace and c.relkind='r' and (c.relname like 'kafka%' or c.relname in ('users_user','brands_brand', ...));
select 'dbsize', current_database(), pg_size_pretty(pg_database_size(current_database()));   -- '3612 MB' = MiB
```
**Q10: empty / never-analyzed tables** (rev 2 misread relpages=0 as empty; corrected by Q20a, which reads pg_relation_size)
```sql
select relname, reltuples::bigint, relpages, pg_relation_size(oid) heap from pg_class where relnamespace='public'::regnamespace and relkind='r' and reltuples<=1 order by 1;
```
**Q11: secondary indexes** (source of the "no index on kafka status/timestamp" finding)
```sql
select t.relname tbl, i.relname idx, pg_get_indexdef(i.oid) def from pg_index x join pg_class t on t.oid=x.indrelid join pg_class i on i.oid=x.indexrelid
where t.relnamespace='public'::regnamespace and not x.indisprimary and t.relname !~ '^(django|auth)' and pg_get_indexdef(i.oid) !~ '(created_by_id|modified_by_id)' order by 1;
```
**Q12: check constraints, triggers, publications, extensions** (only positive-integer checks; no triggers or publications; extensions plpgsql, btree_gin, pg_trgm)

**Q13: privilege re-check and audit-FK count** (rev 2 result: tables=84, selectable=0, seqs=83, seq_sel=0, audit_fks=94, audit_tables=47)
```sql
select (select count(*) from pg_class where relnamespace='public'::regnamespace and relkind='r') tables,
 (select count(*) from pg_class where relnamespace='public'::regnamespace and relkind='r' and has_table_privilege(oid,'SELECT')) selectable,
 (select count(*) from pg_sequences where schemaname='public') seqs,
 (select count(*) from pg_sequences where schemaname='public' and has_sequence_privilege('public.'||quote_ident(sequencename),'SELECT')) seq_sel,
 (select count(*) from pg_constraint where connamespace='public'::regnamespace and contype='f' and (select attname from pg_attribute where attrelid=conrelid and attnum=conkey[1]) in ('created_by_id','modified_by_id')) audit_fks,
 (select count(distinct conrelid) from pg_constraint where connamespace='public'::regnamespace and contype='f' and (select attname from pg_attribute where attrelid=conrelid and attnum=conkey[1]) = 'created_by_id') audit_tables;
```
**Q13a: time columns per table** (67 tables have one; source of the Time Coverage table and of the refutation of "every table has created_on")
```sql
select c.relname t, string_agg(a.attname||':'||format_type(a.atttypid,a.atttypmod)||case when a.attnotnull then '!' else '' end, ', ' order by a.attnum) tcols
from pg_class c join pg_attribute a on a.attrelid=c.oid and a.attnum>0 and not a.attisdropped
where c.relnamespace='public'::regnamespace and c.relkind='r' and a.atttypid in ('timestamptz'::regtype,'timestamp'::regtype,'date'::regtype)
group by 1 order by 1;
-- complement: the 17 tables with no time column, with their full column lists
select c.relname, c.reltuples::bigint, c.relpages, (select string_agg(attname,',' order by attnum) from pg_attribute where attrelid=c.oid and attnum>0 and not attisdropped) cols
from pg_class c where c.relnamespace='public'::regnamespace and c.relkind='r'
and not exists (select 1 from pg_attribute a where a.attrelid=c.oid and a.attnum>0 and not a.attisdropped and a.atttypid in ('timestamptz'::regtype,'timestamp'::regtype,'date'::regtype)) order by 1;
```
**Q14: full 84-table inventory** (source of the inventory list, 19/23/437, 3,381/533,305, 66 content types, 23 store languages, 2 auth groups)
```sql
select relname, reltuples::bigint, relpages from pg_class where relnamespace='public'::regnamespace and relkind='r' order by 1;
```
**Q15: heap / index / TOAST bytes for key tables** (exact bytes. brands_brand: heap 180,920,320, idx 4,980,736, toast 32,776,192, 87 cols. hasofferbrands: 4,317 pages, heap 35,364,864, idx 45,129,728. happy_cards: 3,307 pages, heap 27,090,944, idx 66,772,992. webhookmessage: 130 pages, heap 1,064,960, idx 8,175,616, 1 index. users_user: heap 283,574,272, idx 478,347,264, 41 cols, 9 idx. kafka_atwork heap 517,275,648. kafka_emapistores heap 155,377,664, toast 25,812,992. kafka_plusoffer toast 1,530,216,448)
```sql
select c.relname, c.reltuples::bigint est, c.relpages, pg_relation_size(c.oid) heap, pg_indexes_size(c.oid) idx,
 coalesce(pg_total_relation_size(nullif(c.reltoastrelid,0)),0) toast,
 (select count(*) from pg_attribute where attrelid=c.oid and attnum>0 and not attisdropped) ncols,
 (select count(*) from pg_index where indrelid=c.oid) nidx
from pg_class c where c.relnamespace='public'::regnamespace and c.relkind='r'
and c.relname in ('brands_hasofferbrands','brands_plusoffer_happy_cards','webhooks_webhookmessage','brands_brand','users_user','core_currencyexchangerate','core_currency','core_basecurrency','brands_generic_brand_item','brands_generic_brand_config','django_content_type','django_migrations','locations_store_languages','auth_group','auth_permission','auth_group_permissions','kafka_atworkkafkadatalog','kafka_emapistoreskafkadatalog','kafka_plusofferkafkadatalog','kafka_webstoreskafkadatalog','brands_offer_happy_cards','brands_favouritebrand','users_useravailedoffer')
order by 1;
```
**Q16: plus-offer mechanic / placement, brand friction flags, user profile columns**
```sql
select c.relname t, a.attname, format_type(a.atttypid,a.atttypmod) typ, a.attnotnull nn
from pg_class c join pg_attribute a on a.attrelid=c.oid and a.attnum>0 and not a.attisdropped
where c.relnamespace='public'::regnamespace and (
 (c.relname='brands_plusoffer' and a.attname ~ '(header|order|how_it|featured|tile|usage|budget)') or
 (c.relname='brands_brand' and a.attname ~ '(mobile|pin_|redeemable|minimum|split|swap|location)') or
 (c.relname='users_user' and a.attname ~ '(modified|profile|img|app_version|platform)'))
order by 1, a.attnum;
-- plus full column lists for core_currencyexchangerate, brands_hasofferbrands, kafka_atworkkafkadatalog,
-- emapi_generics_client_mobileappplatformversion, users_useravailedoffer, brands_favouritebrand, django_migrations, webhooks_webhookmessage
```
**Q17: constraints on the tables examined in rev 2** (source of: happy_cards UNIQUE pair; hasofferbrands no UNIQUE; exchangerate has FKs but no UNIQUE pair; favouritebrand has no audit FKs; useravailedoffer created_by FK; content_type UNIQUE(app_label, model); auth and store_languages FKs)
```sql
select conrelid::regclass::text t, contype, conname, pg_get_constraintdef(oid) def
from pg_constraint where connamespace='public'::regnamespace and conrelid::regclass::text in ('core_currencyexchangerate','users_useravailedoffer','brands_favouritebrand','brands_hasofferbrands','brands_plusoffer_happy_cards','webhooks_webhookmessage','locations_store_languages','django_content_type','auth_permission','auth_group_permissions','emapi_generics_client_mobileappplatformversion') order by 1,2;
```
**Q17b: created_by NOT NULL check** (created_by_id is NOT NULL on core_currencyexchangerate, users_useravailedoffer and webhooks_webhookconfig; users_user and brands_favouritebrand have no created_by_id)
```sql
select c.relname, a.attnotnull from pg_class c join pg_attribute a on a.attrelid=c.oid and a.attname='created_by_id'
where c.relnamespace='public'::regnamespace and c.relkind='r' and c.relname ~ '^(users_|brands_favourite|brands_plusoffer$|brands_offerpromo|webhooks|kafka|core_currencyex)' order by 1;
```
**Q18: per-index sizes** (webhookmessage_pkey 8,151,040 B; hasofferbrands_pkey 26,632,192 B; plusoffer_happy_cards_pkey 27,574,272 B; useravailedoffer has a created_by_id index of 65,536 B)
```sql
select t.relname tbl, i.relname idx, pg_relation_size(i.oid) bytes, pg_get_indexdef(i.oid) def from pg_index x join pg_class t on t.oid=x.indrelid join pg_class i on i.oid=x.indexrelid
where t.relnamespace='public'::regnamespace and t.relname in ('users_useravailedoffer','brands_favouritebrand','brands_hasofferbrands','brands_plusoffer_happy_cards','webhooks_webhookmessage','core_currencyexchangerate') order by 1,2;
```
**Q19: Kafka delivery-metadata columns** (0 rows: no topic/partition/offset/key/retry/attempt column in any kafka_* table)
```sql
select c.relname, a.attname from pg_class c join pg_attribute a on a.attrelid=c.oid and a.attnum>0 and not a.attisdropped
where c.relnamespace='public'::regnamespace and c.relname in ('kafka_atworkkafkadatalog','kafka_emapistoreskafkadatalog','kafka_plusofferkafkadatalog','kafka_webstoreskafkadatalog') and a.attname ~ '(topic|partition|offset|key|retry|attempt)';
```

**Q20: constraints on the rev-3 tables** (only UNIQUE on the mobile config table is `reference_id`; `users_useravailedoffer`, `brands_offerpromocode`, `brands_generic_brand_item` have only pkey + FKs, no UNIQUE; `brands_offer_happy_cards` has UNIQUE(offer_id, brand_id))
```sql
select conrelid::regclass::text t, contype, pg_get_constraintdef(oid) def
from pg_constraint where connamespace='public'::regnamespace and conrelid::regclass::text in ('emapi_generics_client_mobileappplatformversion','users_useravailedoffer','brands_offerpromocode','brands_generic_brand_item','brands_offer_happy_cards') order by 1,2;
```
**Q20a: empty vs never-analyzed tables** (exact bytes. 0 heap bytes: configurations_bannerimage, jet_bookmark, jet_pinnedapplication, mobile_app_client_config, two_factor_phonedevice. 8,192 B heap with relpages=0 and reltuples=-1: users_usermetadata, users_passwordhistory, django_site, notifications_emailtemplateconfiguration (plus 8,192 B TOAST). brands_offer_happy_cards: 156 pages, 1,277,952 B heap, 3,104,768 B indexes)
```sql
select c.relname, c.relpages, c.reltuples::bigint, pg_relation_size(c.oid) heap,
 coalesce(pg_relation_size(nullif(c.reltoastrelid,0)),0) toast_heap, coalesce(pg_total_relation_size(nullif(c.reltoastrelid,0)),0) toast_total, pg_indexes_size(c.oid) idx
from pg_class c where c.relnamespace='public'::regnamespace and c.relkind='r' and (c.reltuples<=1 or c.relname in ('brands_offer_happy_cards')) order by 1;
```
**Q21: column lists for rev-3 signals** (source of os_version_check_enabled bool NOT NULL / required_os_version varchar(50) nullable; useravailedoffer 7 columns with plus_offer_id nullable; offerpromocode 7 columns, no user_id/redeemed_at; generic_brand_item generic_config_id and brand_id nullable; brands_brand has_code/has_pin/has_redeem_url/buy_for_yourself/can_be_swapped all bool NOT NULL; plusoffer has_min_max_restriction!, is_active!, sponsor_payment_threshold numeric(20,6) nullable, sponsor_payment_threshold_type varchar(10)!; homepageslider is_for_guests!/is_for_logged_in_users!; carouselitem is_wide_image!, video_url nullable, start/end_time nullable; banneritem config/config_ar jsonb!; brands_tag is_visible!/visible_to_ecommerce_app!)
```sql
select c.relname t, a.attname, format_type(a.atttypid,a.atttypmod) typ, a.attnotnull nn
from pg_class c join pg_attribute a on a.attrelid=c.oid and a.attnum>0 and not a.attisdropped
where c.relnamespace='public'::regnamespace and (
 c.relname in ('emapi_generics_client_mobileappplatformversion','users_useravailedoffer','brands_offerpromocode','brands_generic_brand_item','brands_offer_happy_cards','configurations_homepageslider','configurations_carouselitem','configurations_banneritem','brands_tag')
 or (c.relname='brands_brand' and a.attname ~ '(buy_for|has_code|has_pin|has_redeem|swap)')
 or (c.relname='brands_plusoffer' and a.attname ~ '(min_max|sponsor|is_active|start_date|end_date)'))
order by 1, a.attnum;
```
**Q22: indexes on the rev-3 tables** (no UNIQUE index beyond pkeys on useravailedoffer, offerpromocode, generic_brand_item; mobile config has UNIQUE only on reference_id)
```sql
select t.relname tbl, i.relname idx, pg_relation_size(i.oid) bytes, pg_get_indexdef(i.oid) def from pg_index x join pg_class t on t.oid=x.indrelid join pg_class i on i.oid=x.indexrelid
where t.relnamespace='public'::regnamespace and t.relname in ('users_useravailedoffer','brands_offerpromocode','brands_generic_brand_item','brands_offer_happy_cards','emapi_generics_client_mobileappplatformversion') order by 1,2;
```
**Q22b: users_user per-index sizes** (exact bytes: username_uniq 79,527,936; username_like 77,766,656; (username,is_enabled) 77,635,584; email_key 62,562,304; email_like 61,063,168; phone_like 44,122,112; phone_key 44,097,536; pkey 24,092,672; secondary_emails GIN 7,462,912. Sum of the seven email/phone/username btrees = 446,775,296 B = 93.4% of pg_indexes_size 478,347,264 B. Sum of all nine = 478,330,880 B)
```sql
select i.relname idx, pg_relation_size(i.oid) bytes, pg_get_indexdef(i.oid) def from pg_index x join pg_class t on t.oid=x.indrelid join pg_class i on i.oid=x.indexrelid
where t.relnamespace='public'::regnamespace and t.relname='users_user' order by 2 desc;
```
**Q23: brands_offer_happy_cards upper bound** (arithmetic, estimate/upper bound; block_size = 8,192 confirmed in Q24)
```
tuple = 24 B heap-tuple header (23 B, MAXALIGNed) + 3 x 8 B bigint = 48 B; + 4 B line pointer = 52 B
usable page = 8,192 - 24 B page header = 8,168 B  ->  floor(8,168 / 52) = 157 tuples/page at 100% fill
156 heap pages x 157 = 24,492 rows maximum  (rev 2's "~28k" exceeded this and was wrong)
```
**Q24: privilege re-check, rev 3** (tables=84, selectable=0, seqs=83, seq_sel=0, block_size=8192)
```sql
select (select count(*) from pg_class where relnamespace='public'::regnamespace and relkind='r') tables,
 (select count(*) from pg_class where relnamespace='public'::regnamespace and relkind='r' and has_table_privilege(oid,'SELECT')) selectable,
 (select count(*) from pg_sequences where schemaname='public') seqs,
 (select count(*) from pg_sequences where schemaname='public' and has_sequence_privilege('public.'||quote_ident(sequencename),'SELECT')) seq_sel,
 current_setting('block_size') bs;
```
**Q25: replica database counters** (exact at query time: xact_commit 228, xact_rollback 63, tup_returned 284,282, tup_fetched 143,197, blks_read 1,736, blks_hit 191,759, stats_reset null, pg_is_in_recovery true)
```sql
select datname, xact_commit, xact_rollback, tup_returned, tup_fetched, blks_read, blks_hit, stats_reset, pg_is_in_recovery() replica
from pg_stat_database where datname=current_database();
```

**Q26: privilege re-check, rev 4** (2026-09-29: tables=84, selectable=0, seqs=83, seq_sel=0)
```sql
select (select count(*) from pg_class where relnamespace='public'::regnamespace and relkind='r') tables,
 (select count(*) from pg_class where relnamespace='public'::regnamespace and relkind='r' and has_table_privilege(oid,'SELECT')) selectable,
 (select count(*) from pg_sequences where schemaname='public') seqs,
 (select count(*) from pg_sequences where schemaname='public' and has_sequence_privilege('public.'||quote_ident(sequencename),'SELECT')) seq_sel;
```
**Q27: schema chronology** (84 rows in oid order; source of the Schema chronology table. Lowest oid 29,440 django_migrations, highest 42,121,710 django_site. rewritten=true for users_user 29,513, brands_brand_denomination 30,010, brands_offer 30,304, dashboard_userdashboardmodule 30,758, brands_plusoffer 12,750,239. Key oids: myshopcategory 2,516,530; mobileappplatformversion 8,808,246; plusoffer_happy_cards 12,750,252; kafka_plusoffer 12,750,307; useravailedoffer 14,655,011; offerpromocode 16,158,996; mobile_app_client_config 16,159,034; hasofferbrands 20,302,605; kafka_emapistores 20,302,628; kafka_atwork 20,302,639; kafka_webstores 32,060,301; shopcategory 36,404,056; shopcategorybrand 36,404,067; usermetadata 41,994,079; passwordhistory 41,994,087; emailtemplateconfiguration 42,121,684. Also returned reltuples: hasofferbrands 40,079)
```sql
select oid::bigint, relname, relfilenode<>oid rewritten, reltuples::bigint est
from pg_class where relnamespace='public'::regnamespace and relkind='r' order by oid;
```
**Q28: column details for rev-4 issues** (mobile_app_client_config: client_name varchar(255)!, platform varchar(50)!, version varchar(50)!, expiry_date tstz, reference_id uuid!; shopcategory: is_interest!, is_slider!, is_horizontal_scroll!, row_count int, column_count int; notifications: email_type varchar(25), template_code varchar(10), template_data jsonb, to_emails text, is_active!, language_id; users_usermetadata: password_last_changed tstz, has_received_expiry_warning!, user_id nullable; users_passwordhistory: password_hash varchar(255)!, user_id!; users_user.user_agent varchar(100), new_password_policy bool!; brands_brand: non_expirable!, validity_months int!, validity_days int!, expiry_details jsonb!, receiver/sender_redemption_details[_en/_ar] text nullable, short_redemption_details[_en/_ar] varchar(255); brands_plusoffer: is_generic_promo_code!, is_unique_promo_code!, promo_code_end_date tstz, promo_code_threshold int; attidentity='d' on the id of usermetadata, passwordhistory, emailtemplateconfiguration, django_site)
```sql
select c.relname t, a.attname, format_type(a.atttypid,a.atttypmod) typ, a.attnotnull nn, a.attidentity idn
from pg_class c join pg_attribute a on a.attrelid=c.oid and a.attnum>0 and not a.attisdropped
where c.relnamespace='public'::regnamespace and (
 c.relname in ('mobile_app_client_config','configurations_shopcategory','configurations_myshopcategory','notifications_emailtemplateconfiguration','users_usermetadata','users_passwordhistory','brands_hasofferbrands')
 or a.attidentity<>''
 or (c.relname='users_user' and a.attname in ('user_agent','new_password_policy'))
 or (c.relname='brands_brand' and a.attname ~ '(expir|validity|receiver|redemption_details)')
 or (c.relname='brands_plusoffer' and a.attname ~ '(promo)'))
order by 1, a.attnum;
```
**Q29: constraints for rev-4 tables** (hasofferbrands: pkey + FK offer_id→brands_plusoffer + FK brand_id→brands_brand, no UNIQUE; mobile_app_client_config: UNIQUE(client_name, platform, version), UNIQUE(reference_id), audit FKs; notifications: FK language_id→core_language + audit FKs, no UNIQUE; shopcategory: UNIQUE(code) + audit FKs; shopcategorybrand: FKs shop_category_id, brand_id; usermetadata: UNIQUE(user_id), FK user_id; passwordhistory: FK user_id)
```sql
select conrelid::regclass::text t, contype, pg_get_constraintdef(oid) def
from pg_constraint where connamespace='public'::regnamespace and conrelid::regclass::text in ('mobile_app_client_config','brands_hasofferbrands','notifications_emailtemplateconfiguration','configurations_shopcategory','configurations_shopcategorybrand','users_usermetadata','users_passwordhistory') order by 1,2;
```
**Q30: indexes on brands_generic_brand_item / mobile_app_client_config, any GIN or trigram index, installed extensions** (exact bytes. generic_brand_item: pkey 25,395,200; generic_config_id 10,067,968; brand_id 9,207,808; modified_by_id 6,742,016; created_by_id 6,512,640. mobile_app_client_config: 5 indexes of 16,384 B each (metapage only), including unique_client_app_version. Only GIN index in the schema: users_user secondary_emails_gin_idx 7,462,912 (default array opclass); no gin_trgm_ops / gist_trgm_ops index. Extensions: btree_gin 1.3, pg_trgm 1.5, plpgsql 1.0)
```sql
select t.relname tbl, i.relname idx, pg_relation_size(i.oid) bytes, pg_get_indexdef(i.oid) def from pg_index x join pg_class t on t.oid=x.indrelid join pg_class i on i.oid=x.indexrelid
where t.relnamespace='public'::regnamespace and (t.relname in ('brands_generic_brand_item','mobile_app_client_config') or pg_get_indexdef(i.oid) ~* 'trgm|gin') order by 1,2;
select extname, extversion from pg_extension order by 1;
```
Arithmetic (estimate): expected bigint pkey ≈ 533,305 × (8 B index-tuple header + 8 B key + 4 B line pointer = 20 B) / 0.9 leaf fill ≈ 11.85 MB, plus <1% internal pages ≈ 12 MB; 25,395,200 / 12,000,000 ≈ 2.1x. Heap 57,294,848 / 533,305 ≈ 107 B per row for 10 columns (Q32a).

**Q31: size re-read for drift, rev 4** (exact bytes. hasofferbrands: est 40,079 (rev 3: 49,787), relpages 4,317, heap 35,364,864, idx 45,129,728 — pages and bytes unchanged. users_user: heap 283,598,848 (rev 3: 283,574,272), idx 478,380,032 (rev 3: 478,347,264). generic_brand_item: est 533,305, heap 57,294,848, idx 58,048,512. brands_brand, happy_cards, webhookmessage, kafka_*, useravailedoffer, favouritebrand, offerpromocode, plusoffer: unchanged vs Q15. Per-index: hasofferbrands_pkey 26,632,192, offer_id 9,945,088, brand_id 8,478,720; plusoffer_happy_cards pkey 27,574,272, unique pair 20,611,072; webhookmessage_pkey 8,151,040. DB size 3,787,549,271 B = '3612 MB'. last_autoanalyze/last_autovacuum null on the replica)
```sql
select c.relname, c.reltuples::bigint est, c.relpages, pg_relation_size(c.oid) heap, pg_indexes_size(c.oid) idx,
 coalesce(pg_total_relation_size(nullif(c.reltoastrelid,0)),0) toast, s.last_autoanalyze, s.last_autovacuum
from pg_class c left join pg_stat_user_tables s on s.relid=c.oid where c.relnamespace='public'::regnamespace and c.relkind='r'
and c.relname in ('brands_hasofferbrands','brands_plusoffer_happy_cards','webhooks_webhookmessage','brands_brand','users_user','brands_generic_brand_item','kafka_atworkkafkadatalog','kafka_emapistoreskafkadatalog','kafka_plusofferkafkadatalog','users_useravailedoffer','brands_favouritebrand','brands_offerpromocode','brands_plusoffer')
order by 1;
select t.relname tbl, i.relname idx, pg_relation_size(i.oid) bytes from pg_index x join pg_class t on t.oid=x.indrelid join pg_class i on i.oid=x.indexrelid
where t.relnamespace='public'::regnamespace and t.relname in ('brands_hasofferbrands','brands_plusoffer_happy_cards','webhooks_webhookmessage') order by 1,2;
select pg_database_size(current_database()) b, pg_size_pretty(pg_database_size(current_database())) p;
```
Arithmetic: 35,364,864 / 40,079 ≈ 882 B heap per row (rev 3's ≈710 B used 49,787).

**Q32: identity columns and their sequences; generic_brand_item column list; server version** (identity 'd' on users_usermetadata.id → users_usermetadata_id_seq, users_passwordhistory.id → users_passwordhistory_id_seq, notifications_emailtemplateconfiguration.id → notifications_emailtemplateconfiguration_id_seq, django_site.id → django_site_id_seq; no other table has an identity column. Q32a: brands_generic_brand_item has 10 columns; server_version 16.11)
```sql
select c.relname, a.attname, a.attidentity, pg_get_serial_sequence('public.'||c.relname, a.attname) seq
from pg_class c join pg_attribute a on a.attrelid=c.oid where c.relnamespace='public'::regnamespace and c.relkind='r' and a.attidentity<>'' order by c.oid;
select count(*) n, current_setting('server_version') v from pg_attribute a
where a.attrelid='public.brands_generic_brand_item'::regclass and a.attnum>0 and not a.attisdropped;  -- Q32a
```
**Q33: column lists for the sensitive tables in the Grant request** (verifies the keep/exclude lists: otp_totp_totpdevice has key; two_factor_phonedevice has number, key, method, confirmed, no created_at/last_used_at; otp_static_statictoken id, token, device_id; django_session session_key, session_data, expire_date; brands_storelocation address, address_en, address_ar, contact_number, contact_email; remote_url_config server, url, api_key, api_secret; webhooks_webhookconfig name, webhook_key, sender_ips, is_active)
```sql
select c.relname, string_agg(a.attname, ',' order by a.attnum) cols
from pg_class c join pg_attribute a on a.attrelid=c.oid and a.attnum>0 and not a.attisdropped
where c.relnamespace='public'::regnamespace and c.relname in ('otp_totp_totpdevice','otp_static_staticdevice','two_factor_phonedevice','otp_static_statictoken','django_session','brands_storelocation','webhooks_webhookconfig','remote_url_config_remoteurlconfig','django_admin_log')
group by 1 order by 1;
```

### Queries to run once SELECT is granted (not yet run)
```sql
-- Rev 4: every query below reads only the tables of grant (a) or the atlas_* views of the Grant request,
-- and uses only the columns those views expose (has_error, data_md5, has_error_message, promo_code_md5, has_sub, ...).
-- NOTE: TABLESAMPLE works on tables, not on plain views. On a view, sample by pkey range instead
-- (where id >= :lo and id < :hi), or ask the DBA to add the derived columns as a column grant on the table.
-- kafka failure rate + latency (repeat per atlas_kafka_* view)
select status, count(*), count(*) filter (where has_error) with_err,
       percentile_cont(0.5) within group (order by extract(epoch from completed_timestamp-start_timestamp)) p50_s
from atlas_kafka_atworkkafkadatalog where id >= :lo and id < :hi group by 1;
-- (d) kafka stuck rows (>1h without completion), sliced by pkey range: first find the id at a time boundary
--     with a few probes (select start_timestamp from atlas_kafka_atworkkafkadatalog where id = :probe),
--     then count inside [lo, hi) using only the pkey index:
select count(*) filter (where completed_timestamp is null and start_timestamp < now()-interval '1 hour') stuck, count(*) total
from atlas_kafka_atworkkafkadatalog where id >= :lo and id < :hi;
-- kafka duplicate deliveries (data_md5 view column; no offset/key column exists)
select count(*) n, count(*) - count(distinct data_md5) dup_rows, count(*) filter (where has_error) err_rows
from atlas_kafka_plusofferkafkadatalog where id >= :lo and id < :hi;
-- user signup trend (sampled, x100 to scale)
select date_trunc('month',date_joined) m, count(*) n from atlas_users_user
where id >= :lo and id < :hi and date_joined >= now()-interval '18 months' group by 1 order by 1;  -- scale by range share
-- (e) profile-update recency vs login recency (sampled)
select width_bucket(extract(day from now()-modified_on),0,730,8) mod_bucket,
       count(*) n, count(*) filter (where last_login >= now()-interval '90 days') active90,
       count(*) filter (where custom_profile_img) with_img
from atlas_users_user where id >= :lo and id < :hi group by 1 order by 1;
-- user flags (derived booleans only; sub itself is never exposed)
select platform, count(*), count(*) filter (where is_fraud) fraud, count(*) filter (where email_verified) ev,
       count(*) filter (where has_sub) has_sub, count(*) filter (where has_apple_id) apple,
       count(*) filter (where has_google_id) google, count(*) filter (where has_facebook_id) facebook
from atlas_users_user where id >= :lo and id < :hi group by 1;
-- (a0) config shape first: how many rows per platform, and the OS gate
select lower(app_platform) p, count(*) n_rows, count(distinct required_version) n_req, max(modified_on) last_mod,
       bool_or(os_version_check_enabled) os_gate, max(required_os_version) max_req_os
from emapi_generics_client_mobileappplatformversion group by 1;
-- (a) forced-upgrade gap by platform (rev 3: ONE config row per platform, numeric guards on BOTH sides)
with v as (
  select distinct on (lower(app_platform)) lower(app_platform) p, required_version, latest_version, optional
  from emapi_generics_client_mobileappplatformversion
  order by lower(app_platform), modified_on desc nulls last, id desc),
u as (select lower(platform) p, app_version from atlas_users_user where id >= :lo and id < :hi and app_version ~ '^\d+(\.\d+)*$')
select u.p, count(*) users,
  count(*) filter (where v.required_version ~ '^\d+(\.\d+)*$'
                   and string_to_array(u.app_version,'.')::int[] < string_to_array(v.required_version,'.')::int[]) below_required,
  count(*) filter (where v.latest_version ~ '^\d+(\.\d+)*$'
                   and string_to_array(u.app_version,'.')::int[] < string_to_array(v.latest_version,'.')::int[]) below_latest,
  bool_or(v.optional) latest_optional
from u join v on v.p = u.p group by 1;
-- (a2) OS-version gate: config side only. The user side needs an OS version that users_user does not store
--      (only inside user_agent varchar(100), truncated, PII-restricted); run once the view exposes os_major_version,
--      and report count(*) filter (where os_major_version is null) as the parse-failure share.
select lower(app_platform) p, os_version_check_enabled, required_os_version, count(*)
from emapi_generics_client_mobileappplatformversion group by 1,2,3 order by 1;
select min(id), max(id) from atlas_users_user;  -- or last_value from users_user_id_seq once grant (h) lands
-- (b) plus-offer mechanic split
select case when purchase_offer_header is not null and spend_offer_header is not null then 'both'
            when purchase_offer_header is not null then 'purchase' when spend_offer_header is not null then 'spend' else 'none' end mechanic,
       count(*), sum(usage_count), count(*) filter (where has_budget_exceeded) budget_exceeded,
       count(*) filter (where is_active and now() between start_date and end_date) live,
       count(*) filter (where is_active and not (now() between start_date and end_date)) active_outside_window,
       count(*) filter (where not is_active and now() between start_date and end_date) inactive_inside_window,
       count(*) filter (where has_min_max_restriction) min_max_restricted
from brands_plusoffer group by 1;
select offer_type, offer_mode, offer_channel, sponsor_payment_threshold_type, is_active, has_min_max_restriction,
       count(*), sum(usage_count), count(*) filter (where has_budget_exceeded) budget_exceeded,
       count(*) filter (where sponsor_payment_threshold is not null) has_sponsor_threshold
from brands_plusoffer group by 1,2,3,4,5,6;
-- (c) brand redemption-friction matrix
select classification, count(*) brands,
  count(*) filter (where require_mobile_verification) mob_verif,
  count(*) filter (where require_mobile_verification and not allow_any_country_mobile_verification) mob_verif_country_locked,
  count(*) filter (where pin_redeemable_location_required) pin_loc_required,
  count(*) filter (where not can_be_split) not_splittable,
  count(*) filter (where minimum_usage_amount > 0) has_min_usage,
  count(*) filter (where redeemable_brands is not null and redeemable_brands<>'') has_redeemable_brands,
  count(*) filter (where can_be_swapped) swappable,
  count(*) filter (where (require_mobile_verification or pin_redeemable_location_required) and not can_be_swapped) hard_no_swap,
  count(*) filter (where buy_for_yourself) self_purchase
from brands_brand where is_active group by 1;
-- (c2) redemption mode mix
select has_code, has_pin, has_redeem_url, count(*), count(*) filter (where buy_for_yourself) self_purchase,
       count(*) filter (where can_be_swapped) swappable
from brands_brand where is_active group by 1,2,3 order by 4 desc;
-- generic-card fan-out (exact)
select count(*) configs, avg(n), percentile_cont(0.5) within group (order by n) from
 (select generic_config_id, count(*) n from brands_generic_brand_item where is_active group by 1) s;
-- hasofferbrands duplicates / churn
select count(*), count(distinct (offer_id, brand_id)), min(created_on), max(created_on) from brands_hasofferbrands;
-- exchange-rate matrix check
select count(*), count(distinct (base_currency_id, foreign_currency_id)), max(modified_on) from core_currencyexchangerate;
-- availed-offer actor check, repeat avails and orphans (rev 3)
select count(*) n, count(*) filter (where created_by_id = user_id) self_created,
       count(*) filter (where plus_offer_id is null) orphan_avails,
       count(*) - count(distinct (user_id, plus_offer_id)) repeat_avail_rows,
       count(distinct user_id) users, count(distinct plus_offer_id) offers
from users_useravailedoffer;
-- avails vs usage_count per offer (claim log vs counter)
select p.code_bucket, count(*) offers, sum(p.usage_count) usage_sum, sum(a.n) avail_sum from (
  select id, usage_count, case when usage_count is null then 'null' else 'set' end code_bucket from brands_plusoffer) p
left join (select plus_offer_id, count(*) n from users_useravailedoffer group by 1) a on a.plus_offer_id = p.id group by 1;
-- duplicate promo codes (aggregate only; never select promo_code values)
select count(*) n, count(distinct promo_code_md5) distinct_codes, count(*) - count(distinct promo_code_md5) dup_rows
from atlas_offerpromocode;
-- duplicate / null-keyed generic items
select count(*) n, count(distinct (generic_config_id, brand_id)) distinct_pairs,
       count(*) filter (where generic_config_id is null or brand_id is null) null_keyed,
       count(*) filter (where is_active) active
from brands_generic_brand_item;
-- (h) merchandising exposure
select store_id, count(*) sliders, count(*) filter (where is_active) active,
       count(*) filter (where is_for_guests) guest, count(*) filter (where is_for_logged_in_users) logged_in,
       count(*) filter (where is_for_guests and not is_for_logged_in_users) guest_only,
       count(*) filter (where is_for_logged_in_users and not is_for_guests) logged_in_only
from configurations_homepageslider group by 1 order by 1;
select c.store_id, count(*) items, count(*) filter (where ci.is_active) active,
       count(*) filter (where ci.is_active and (ci.start_time is null or ci.start_time <= now()) and (ci.end_time is null or ci.end_time > now())) live_now,
       count(*) filter (where ci.end_time < now() and ci.is_active) active_but_expired,
       count(*) filter (where ci.is_wide_image) wide, count(*) filter (where ci.video_url is not null and ci.video_url<>'') video
from configurations_carouselitem ci join configurations_carousel c on c.id = ci.carousel_id group by 1 order by 1;
select is_active, is_visible, visible_to_ecommerce_app, tag_type, count(*) from brands_tag group by 1,2,3,4 order by 5 desc;
select jsonb_object_keys(config) k, count(*) from configurations_banneritem group by 1 order by 2 desc;  -- key inventory only
-- never-analyzed small tables: exact counts
select (select count(*) from users_usermetadata) usermetadata, (select count(*) from atlas_passwordhistory) pwhist,
       (select count(*) from django_site) site, (select count(*) from atlas_notifications_emailtemplateconfiguration) email_tpl,
       (select count(*) from brands_offer_happy_cards) offer_happy_cards;
-- (f) admin activity by model per month
select date_trunc('month',l.action_time) m, ct.app_label||'.'||ct.model model, l.action_flag, count(*)
from atlas_django_admin_log l join django_content_type ct on ct.id=l.content_type_id
where l.action_time >= now()-interval '12 months' group by 1,2,3 order by 1,4 desc;
-- (g) deploy timeline
select date_trunc('month',applied) m, count(*), count(distinct app) from django_migrations group by 1 order by 1;
select status, count(*) from atlas_offerpromocode group by 1;
select type, count(*), count(*) filter (where has_error_message) with_err, min(received_at), max(received_at) from atlas_webhookmessage group by 1;
select date_trunc('month',created_on), count(*) from users_useravailedoffer group by 1 order by 1;
-- ===== rev 4 additions =====
-- (i) gift-card validity / expiry policy by classification
select classification, count(*) brands,
       count(*) filter (where non_expirable) non_expirable,
       count(*) filter (where not non_expirable and validity_months > 0 and validity_days = 0) months_only,
       count(*) filter (where not non_expirable and validity_days > 0 and validity_months = 0) days_only,
       count(*) filter (where validity_months > 0 and validity_days > 0) both_units,
       count(*) filter (where not non_expirable and validity_months = 0 and validity_days = 0) no_validity_set,
       percentile_cont(0.5) within group (order by validity_months) filter (where not non_expirable and validity_months > 0) p50_months,
       count(*) filter (where not non_expirable and coalesce(validity_months,0)*30 + coalesce(validity_days,0) < 180) under_6m
from brands_brand where is_active and is_launched and not is_obsolete group by 1 order by 2 desc;
select k, count(*) from brands_brand, jsonb_object_keys(case when jsonb_typeof(expiry_details)='object' then expiry_details else '{}'::jsonb end) k
group by 1 order by 2 desc;  -- key inventory only
-- (j) missing recipient redemption instructions among live brands (null/blank test only)
select classification, has_code, has_pin, has_redeem_url, count(*) live_brands,
       count(*) filter (where coalesce(btrim(receiver_redemption_details_en),'') = '') missing_en,
       count(*) filter (where coalesce(btrim(receiver_redemption_details_ar),'') = '') missing_ar,
       count(*) filter (where coalesce(btrim(receiver_redemption_details_en),'') = '' and coalesce(btrim(receiver_redemption_details_ar),'') = '') missing_both,
       count(*) filter (where pin_redeemable_location_required and coalesce(btrim(receiver_redemption_details_en),'') = '') loc_pin_missing_en
from brands_brand where is_active and is_launched and not is_obsolete group by 1,2,3,4 order by 5 desc;
-- (k) password-rotation funnel
select count(*) users,
       count(*) filter (where u.new_password_policy) on_new_policy,
       count(m.id) with_metadata,
       count(*) filter (where m.password_last_changed is not null) changed_once,
       count(*) filter (where m.has_received_expiry_warning) warned,
       count(*) filter (where m.has_received_expiry_warning and exists (
           select 1 from atlas_passwordhistory h where h.user_id = u.id and h.created_on > m.modified_on)) changed_after_warning,
       count(*) filter (where m.password_last_changed < now() - interval '90 days') stale_90d
from atlas_users_user u left join users_usermetadata m on m.user_id = u.id
where u.new_password_policy or m.id is not null;
select count(distinct user_id) users_with_history, count(*) rows, max(n) max_per_user from (
  select user_id, count(*) over (partition by user_id) n from atlas_passwordhistory) s;
-- (l) promo-code inventory vs threshold, by code type
with c as (select offer_id, status, count(*) n, count(distinct promo_code_md5) distinct_codes
           from atlas_offerpromocode group by 1,2)
select p.is_generic_promo_code, p.is_unique_promo_code, c.status, count(distinct p.id) offers, sum(c.n) codes,
       count(distinct p.id) filter (where p.promo_code_threshold is not null and c.n < p.promo_code_threshold) below_threshold,
       count(distinct p.id) filter (where p.promo_code_end_date < now() and c.n > 0) past_code_end_with_codes,
       count(distinct p.id) filter (where p.is_generic_promo_code and c.distinct_codes > 1) generic_with_many_codes,
       count(distinct p.id) filter (where p.is_active and now() between p.start_date and p.end_date) live_offers
from brands_plusoffer p left join c on c.offer_id = p.id
where p.is_generic_promo_code or p.is_unique_promo_code or c.offer_id is not null
group by 1,2,3 order by 1,2,3;
-- (m) shop-category layout flags
select is_active, is_visible, is_interest, is_slider, is_horizontal_scroll, row_count, column_count, count(*) categories,
       sum((select count(*) from configurations_shopcategorybrand b where b.shop_category_id = s.id)) brand_links
from configurations_shopcategory s group by 1,2,3,4,5,6,7 order by 8 desc;
select 'myshop' sys, count(*) filter (where is_active) active, count(*) n, max(modified_on) last_mod from configurations_myshopcategory
union all select 'shop', count(*) filter (where is_active), count(*), max(modified_on) from configurations_shopcategory;
-- (n) email trigger configuration inventory
select e.email_type, e.template_code, l.code lang, e.is_active, count(*) rows, bool_or(e.has_to_emails) has_recipients
from atlas_notifications_emailtemplateconfiguration e left join core_language l on l.id = e.language_id
group by 1,2,3,4 order by 1,3;
select email_type, count(distinct language_id) langs from atlas_notifications_emailtemplateconfiguration
where is_active group by 1 having count(distinct language_id) < 2;  -- triggers missing a language
-- (o) forced-upgrade gate #2: per-client version expiry
select client_name, lower(platform) p, count(*) versions,
       count(*) filter (where expiry_date < now()) expired, count(*) filter (where expiry_date >= now()) scheduled,
       count(*) filter (where expiry_date is null) no_expiry, min(expiry_date) first_expiry, max(expiry_date) last_expiry
from mobile_app_client_config group by 1,2 order by 1,2;
select lower(u.platform) p, count(*) users_on_expired_version     -- client dimension not joinable (no client_name on users_user)
from atlas_users_user u join mobile_app_client_config c
  on lower(c.platform) = lower(u.platform) and c.version = u.app_version and c.expiry_date < now()
where u.id >= :lo and u.id < :hi group by 1;
-- (p) generic-item churn check (pkey 2x): id spread vs row count per config
select count(*) n, max(id) - min(id) + 1 id_span, round(count(*)::numeric / nullif(max(id)-min(id)+1,0), 3) density,
       min(created_on), max(created_on), count(*) filter (where created_on > now() - interval '30 days') created_30d
from brands_generic_brand_item;
```
