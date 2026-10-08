# Profile: ecomweb-stores (`ygag_ecomweb_stores_db`)

Profiled 2026-09-29 through `atlasq.sh` (atlas EC2 over SSH, read-only transaction, Aurora PostgreSQL 16.11 read replica, `pg_is_in_recovery()=true`).

> **Blocking access limitation. Read this first.** The `<emapi_login_role>` role has **no SELECT privilege on any of the 134 tables** in this database. `has_table_privilege(...,'SELECT')` is false for all 134, `has_any_column_privilege` is 0, `information_schema.columns` returns nothing, and `SELECT ... FROM users_cognitouser` fails with `InsufficientPrivilegeError`. The role has USAGE on schema `public` only. So **this profile is built only from the system catalog**: pg_class, pg_attribute, pg_constraint, pg_indexes, pg_sequences, plus the replica's cumulative `pg_stat_all_tables` / `pg_stat_all_indexes` read counters. That means:
> - No value distributions, no min/max timestamps, no monthly trends, no null rates, no orphan checks. Row counts are `reltuples` **estimates**.
> - `pg_sequences.last_value` is NULL for all 133 sequences (no privilege), so ID ranges are unknown.
> - On a replica, `n_live_tup`, `last_analyze` and `last_autovacuum` read 0 or NULL. `reltuples` comes from the primary's last ANALYZE; its date is unknown.
> - To finish sections 3–8 at full depth, a DBA must run `GRANT SELECT ON ALL TABLES IN SCHEMA public TO <emapi_login_role>` (ideally excluding or column-masking the credential and PII tables). See Open Questions.
> - **This is not an isolated miss.** The same check (A9) shows `ygag_emapi_stores_db` 0/84 tables readable and `ygag_plusoffers_db` 0/49, while `ygag_ecom_users_db` is fully readable (40/40). The grant request should cover all three blocked DBs.

## Summary

`ygag_ecomweb_stores_db` is the **Django backend of the YouGotAGift consumer web storefront ("ecomweb")**. It holds:
- the **brand/gift-card catalog**: brands, denominations, categories, tags, occasions, store locations, commissions, handling fees;
- **offers**: brand offers and "Plus Offers" with promo codes and budgets;
- a large **CMS/configuration** layer for the storefront: banners, sliders, headers/footers, announcements, testimonials, themes, white-label configs;
- **reference data**: countries, currencies, FX rates, languages, locations, per-country "stores";
- a **Cognito user mirror** (`users_cognitouser`, about 980K rows), which is the consumer identity table;
- a small **Django-admin staff** user base (about 18 users) with OTP/TOTP 2FA;
- **Django sessions** (about 1.29M rows);
- a small amount of behavioral data: `configurations_lastviewedbrand` (about 60K brand-view rows keyed by username), an AI-greeting table that index usage suggests is a **response cache or pre-generated greeting pool** keyed by tone/relation/occasion, not a usage log, and a 10-row OTP table.

Orders, payments and gifts are **not** here. They live in the ecom_orders, ecom_gifts and checkout DBs. There are **no referral, UTM, campaign-source or affiliate columns** anywhere in the DB (catalog search, A10). The integration/error tables are all **empty on the heap**: `webhooks_webhookmessage` (13 MB primary-key index only, 0 heap), `kafka_webstoreskafkadatalog` and `kafka_giftkafkadatalog`. This points to periodic purging, so no error history is kept here.

The replica's read counters show this DB is a **hot catalog-serving database**: `brands_brand` has 8.46B index scans, `core_country` 168.7M seq scans and `locations_store` 97.1M seq scans. Small CMS config tables (`configurations_platformchoice` 73.2M, `header_platform_type` 48.1M, `menuitem` 24.3M seq scans) are read on what looks like every page render. It is primarily a source of **catalog dimensions and user identity** for atlas, not of transactional facts. For the consumer base, the readable `ygag_ecom_users_db.users_user` (about 976K est, with `last_login`) is the better source.

## Entities & Tables

Volumes are `reltuples` estimates (`-1` = never analyzed on the primary). Sizes are `pg_total_relation_size`. DB size is 1,282 MB (exact).

### 1. Consumer identity (Cognito mirror)
| Table | Est. rows | Size | Purpose / key columns |
|---|---|---|---|
| `users_cognitouser` | 980,177 | 667 MB (heap 221 MB, idx 446 MB) | Local mirror of AWS Cognito users. `id` bigint PK, `username` (unique), `sub` (Cognito subject), `email` (unique), `phone_number` (unique), `secondary_emails[]` (GIN), `legacy_auth_code[]`, `platform`!, `app_version`, `user_agent`, `ip_address` inet, `country_of_residence`(2), `language_code`, `gender`, `birthdate`(varchar), `type`, `location`, flags `email_verified`, `phone_number_verified`, `trusted_user`, `is_deleted`, `is_enabled`, `is_native_user`, `is_active`, `is_app_user`; timestamps `date_joined`!, `modified_on`!. No `created_on`, and **no `last_login` or other last-activity column** (full 30-column list checked, A2b). **No index on `date_joined`**, so trend queries will be full scans. `sub` is **nullable, not unique and not indexed**. `username` (NOT NULL, unique) is the only indexed unique consumer key. |
| `django_session` | 1,287,606 | 414 MB | Django sessions (`session_key` PK, `session_data` text, `expire_date` indexed). Anonymous and logged-in storefront sessions. |

### 2. Staff / admin users (Django admin)
| Table | Est. rows | Notes |
|---|---|---|
| `users_customuser` | 18 | Admin/staff users: `email` unique, `password`, `is_staff`, `is_superuser`, `last_login`, `date_joined`. Every `created_by_id`/`modified_by_id` FK in the DB points here. |
| `users_customuser_groups` / `users_customuser_user_permissions` | 19 / 18 | RBAC links |
| `auth_group` / `auth_permission` / `auth_group_permissions` | 7 / 328 / -1 | Django RBAC |
| `users_usermetadata` | 11 | `password_last_changed`, `has_received_expiry_warning` (password-expiry policy) |
| `users_passwordhistory` | -1 (8 KB heap) | Password-reuse history (`password_hash`) |
| `otp_totp_totpdevice` / `otp_static_staticdevice` / `otp_static_statictoken` / `two_factor_phonedevice` | 15 / 1 / 10 / 0 | Admin 2FA devices, with `throttling_failure_count` and `throttling_failure_timestamp` |
| `django_admin_log` | 13,528 | Admin change audit (`action_time`, `action_flag`, `content_type_id`, `object_id`, `change_message`) |
| `dashboard_userdashboardmodule`, `jet_bookmark`, `jet_pinnedapplication` | -1 / 0 / 0 | Django-Jet admin UI state |

### 3. Brand catalog (`brands_*`, 29 tables)
| Table | Est. rows | Purpose |
|---|---|---|
| `brands_brand` | 3,243 | Gift-card brand master. `code` (unique, varchar 20), `slug` (unique), `gencode`, names/descriptions EN/AR, `redemption_type`!, `generic_type`, `classification`!, `expiry_type`, `validity_months`/`validity_days`/`expiry_date`, `non_expirable`, flags (`has_code`, `has_pin`, `has_redeem_url`, `is_generic`, `pin_redeemable`, `can_be_split`, `can_be_swapped`, `buy_for_yourself`, `require_mobile_verification`), visibility per channel (`visible_to_ecommerce`, `_ecommerce_app`, `_android_app`, `_ios_app`, `_at_work`), `is_launched`, `is_active`, `is_obsolete`, `is_whitelabel`, `is_default_brand`, `is_preview_brand`, `date_disabled`, `activation_fee` + `activation_fee_deduct_type`, `plus_offers_details` jsonb. FKs: `company_id`, `store_id`, `currency_id`, `activation_currency_id`, `primary_category_id`. |
| `brands_branddenomination` | 23,283 | Fixed denominations per brand (`amount`, `gencode`, `currency_id`, `is_active`) |
| `brands_branddenominationrange` | 11,987 | Open-amount ranges (`range_type`, `minimum_amount`, `maximum_amount`) |
| `brands_brandcategory` / `brands_brand_categories` | 82 / 32,218 | Categories, plus a brand↔category M2M |
| `brands_tag` / `brands_tagbrand` | 147 / 32,851 | Hierarchical tags (`tag_type`, `parent_tag_id`, `redirect_to_tag_id`, `brand_ordering`), plus brand↔tag with ordering |
| `brands_brandsearchtag` / `brands_brand_search_tags` | 16,864 / 52,715 | Search keywords, plus M2M |
| `brands_occasion` / `brands_brandoccasion` / `brands_brandoccasion_brands` | 55 / 21 / 142 | Occasions (birthday, Eid, …) with card messages and `channels[]` |
| `brands_brandimagegallery` | 9,648 | Brand images |
| `brands_storelocation` | 3,702 | Physical redemption locations (address, contact, city/state/community) |
| `brands_brandgenericconfig` / `brands_genericbrandslist` | 555 / 56,857 | "Generic"/multi-brand cards (Happy Card style): `generic_type`, `process_mode`, `enable_pdf_resend`, `enable_gift_resend`, `auto_brand_sync`, and the list of redeemable brands |
| `brands_brandcommission` / `brands_brandcommissiondetail` | -1 (112 KB) / -1 (104 KB) | Commission rules (`commission_type`, `gift_type`, `date_type`, `threshold`), plus detail (`percentage`, `fixed`, `denomination`, `deduct_amount`) |
| `brands_brandhandlingfee` | 736 | Handling fees (`handling_fee_type`, `amount`, `percentage`, date window) |
| `brands_brandoffer` / `brands_brandoffer_happy_cards` | -1 (224 KB) / -1 (208 KB) | Brand-level promotions: `offer_base`, `offer_type`, `percentage`/`fixed_amount`, min/max order, budget + `has_budget_exceeded`, `funding_method`, `funded_by`, `channel_id` → `brands_productchannel` |
| `brands_plusoffer` / `brands_plusoffer_happy_cards` / `brands_hasofferbrands` | 378 / 14,804 / 1,018 | "Plus Offers" (YGG Plus) campaigns: `code` unique, `start_date`/`end_date` (indexed), `offer_mode`, `offer_type`, `offer_channel`, funding, budget (`budget_type`, `budget_amount`, `budget_threshold`, `has_budget_exceeded`), promo-code mode (`is_generic_promo_code`, `is_unique_promo_code`, `promo_code_threshold`, `promo_code_end_date`), sponsor payment network (card-network-sponsored offers), `reason_code`, `country_id` |
| `brands_offerpromocode` | 40 | Promo codes for plus offers (`status`, `promo_code`, `offer_id`) |
| `brands_defaultstorebrandforoffer` | 7 | Default offer brand per country |
| `brands_productchannel` | 1 | Offer channel dimension |
| `brands_brandslug` | 1 | Old-slug redirects |
| `brands_categorygender` | 0 | Dead |

### 4. Corporate / partner
| `company_company` | 812 | Brand-owning merchant companies: `code` unique(10), `ref_code`, `commission_fixed`, `commission_percentage`, `accepts_generic`, `is_active`. Referenced by `brands_brand.company_id`. |
|---|---|---|

### 5. Storefront CMS (`configurations_*`, 54 tables)
Banners (`banner` 82, `banner_country` 119, `banner_platform_type` 252, `bannercategory` 6), `brandpagepromotionbanner` 26 (links to `plus_offer_id`, `purchase_mode`), `homepageslider` (-1) + `sliderbrand` 292, `customcategoryslider`, `header`/`headertype`/`menuitem` 64 (MPTT tree), `footer`/`footerstore`/`paymentpartner` 6, `announcement` (0), `testimonial*`, `themeconfig` (seasonal theme with snowflakes/audio), `widgetorder` (MPTT), `happycardwidget`, `brandskin` 1,211 (card designs per brand), `searchtag` 39, `crosssellbrand*` (0), `upcomingoccasion*` (0), `pressroom` (0), `blog`, `howtouse*`, `pdfsamples`/`pdfworkinfo`, `platformchoice` 4 (platform dimension: web/app…), `whitelabelbrandconfigs` (-1, 8 KB).
Small CMS tables not named above (est rows): `configurations_howtouse` 1, `configurations_howtousebanner` 4, `configurations_testimonial` 1, `configurations_testimonialvideo` 1 + `configurations_testimonialvideo_country` 14, `configurations_testimonialapps` 3, `configurations_testimonialreview` -1, `configurations_testimonialorder` 0, `configurations_downloadapp` 1, `configurations_downloadapptext` 0, `configurations_footer` 2 with `configurations_footer_country` 2, `configurations_footer_payment_partners` 2, `configurations_footer_platform_type` 2, `configurations_footerstore` 14, `configurations_header` 2, `configurations_header_platform_type` 3, `configurations_headertype` 2, `configurations_happycardwidget` -1 + `_platform_type` 16 + `_redeemable_brands` 0, `configurations_homepageslider_platform_type` 141, `configurations_themeconfig` 1 + `_country` -1, `configurations_widgetorder` 4, `configurations_pdfsamples` 2, `configurations_pdfworkinfo` 1. The full list of 134 is in Appendix B.

User-submitted rows in this group:
- `configurations_lastviewedbrand`: **59,921**. Recently viewed brands per user (`username` nullable, `brand_id`, `store_id` nullable, `created_on`, `modified_on`). **The only per-user behavior table.** It has indexes only on `id`, `brand_id` and `store_id`: **no index on `username` and no unique constraint on `(username, brand_id)`** (A7, A3b).
- `configurations_productfeedbackbox`: 106. "Suggest a brand" feedback (`brand_name`, `email_address`, `user_reference`, `extra` jsonb NOT NULL, `platform_id` NOT NULL FK → `configurations_platformchoice`).
- `configurations_emailsubscription`: -1 (32 KB). Newsletter sign-ups (`email_address`, `is_subscribed`, `extra` jsonb NOT NULL, `platform_id` NOT NULL FK → `configurations_platformchoice`). The FK gives an opt-in mix by platform. The `extra` jsonb on both tables is unexplained. It may hold source or campaign attribution, which would be the only attribution data in this DB. Unverified until SELECT is granted.
- `configurations_downloadapprequest`: 0. "SMS me the app link" (`phone_number`, `delivery_status`).

### 6. Reference / geography (`core_*`, `locations_*`)
`core_country` 22 (`code` ISO2 unique, `code_three_letter`, `timezone`, `currency_id`, phone regex), `core_currency` 23 (`code` ISO3 unique), `core_basecurrency` 19, `core_currencyexchangerate` 437 (`buy_rate`, `sell_rate`), `core_language` 2 (EN/AR), `core_unsupportedcountry`, `core_sitemeta` (SEO), `core_siteconfiguration` 1, `core_captchaconfigurations` 3 (per-action reCAPTCHA thresholds), `locations_store` **22** (per-country storefronts: `code` unique, `country_id`, `currency_id`, `visible_to_ecommerce`, `visible_to_atwork`), `locations_store_languages` 23, `core_country_languages` 24, `core_siteconfiguration_platform_type` 1, `locations_state` 171, `locations_city` 386, `locations_community` 1,115.

### 7. AI greetings
`core_aigreetingmessages` 538 (`tone` NOT NULL, `relation`, `occasion`, `note`, `response_content` jsonb, `created_on`). There is no user column. Every one of the four columns has a btree index plus a `varchar_pattern_ops` index, but **only three are ever used as lookup keys**: on the replica `relation_like` has 740 scans, `occasion_like` 701, `tone_like` 434 and `pkey` 3, while **both `note` indexes have 0 scans** (A11, re-run A14). `note` is therefore not a lookup key. Each lookup also matches **dozens of rows, not one**: rows read per scan are tone 71,952/434 ≈ **166**, relation 47,691/740 ≈ **64**, occasion 37,842/701 ≈ **54**, out of 538 (exact counters, derived ratios). The table is also seq-scanned 624 times reading 293,468 tuples (≈470 per scan, near-full scans). Two readings fit this pattern:
- **(a) Response cache keyed by (tone, relation, occasion)**: the app ANDs the three indexes (BitmapAnd) to find a stored answer before calling the LLM. 538 would then be at most the number of cached combinations plus their variants.
- **(b) Pre-generated greeting pool**: several stock greetings per (tone, relation, occasion), from which one is picked. The ~54–166 rows matched per single-column scan fits a pool at least as well as a strict 1:1 cache.
Either way the table is **not an append-only usage log**, and **538 is not a count of greetings generated**. Related tables: `core_aigreetingsparameters` 29 (tone/relation option lists), `core_aigreetingsconfiguration` 1, `core_aigreetingsconfiguration_enabled_countries` 7, `core_aigreetingsconfiguration_enabled_languages` 1.
*Feature funnel proxy (inference from cumulative replica reads, A14):* `core_aigreetingsparameters` has **55,172 seq scans** (tone/relation option lists loaded, i.e. roughly the greeting widget opened) and `core_aigreetingsconfiguration` 1,470, against **1,878 message index lookups** (+624 seq scans, ~2,502 message reads). That is roughly **3–5 message reads per 100 option-list loads**. The ratio is a rough open-to-generate proxy only: one widget open may scan the parameters table more than once, and one generation may do several message scans.

### 8. Notifications / 2FA (consumer or system OTP, unverified)
`notifications_twofactorauth` 10 (`reference_id` unique, `auth_type`, `source`, `requested_attempts`, `code_length`, `validity`, `language`, `phone_number`, `email`), `notifications_twofactorauthverification` 10 (`request_id` unique, `is_valid`, `auth_code`), `notifications_emailtemplateconfiguration` 6 (`email_type`, `template_code`, `to_emails`).
**Who this OTP is for is unverified.** `notifications_twofactorauth.created_by_id` is **NOT NULL and an FK to `users_customuser`** (18 staff/service accounts), and the table has no `username` or `sub` column. Every row therefore has a staff or service-account creator. It may be staff- or system-initiated OTP, or consumer OTP created through a service account. By contrast, `ygag_ecom_users_db` has its own `notifications_twofactorauth` of about 66.8K rows (est). That is the likely consumer OTP store, and the 10 rows here look like a residual or test deployment of the same app.

### 9. Integration / system
`webhooks_webhookmessage` 0 rows (heap 0 KB). Its table columns are `ip_address`, `message` jsonb, `received_at`, `error_message` jsonb and `type`. **The only index is `webhooks_webhookmessage_pkey` (btree on `id`)**, and it accounts for the whole 13,264 KB, about 1,658 pages of 8 KB. *Inference:* a bigint btree holds about 300–370 entries per leaf page, so this index held roughly **500K–600K rows at peak**. That is the peak number retained at one time, **not the lifetime message count**: btree pages freed by deletes are recycled for new entries, so a table that is purged continuously could have received many more messages over its life. Treat it as an order of magnitude, since pages can be partly empty after deletes. The rows were deleted, not truncated, because the file was never shrunk. Other tables: `webhooks_webhookconfig` 1 (`webhook_key` unique, `sender_ip`), `webhooks_remoteurlconfig` 8 (`server`, `url`, `api_key`, `api_secret`, `application_id`: **stored credentials**), `kafka_webstoreskafkadatalog` 0 rows (PK index 192 KB = 24 pages, so *inferred* ~5K–9K rows held at peak), `kafka_giftkafkadatalog` 0. Both Kafka logs have `status`, `error_data`, `start_timestamp`, `completed_timestamp`. Also `django_migrations` -1, `django_content_type` 104, `django_site` 1, `dashboard_userdashboardmodule` -1.

## Relations

All from `pg_constraint` (370 FK + unique constraints). Every table's `created_by_id`/`modified_by_id` → `users_customuser` (staff audit). There are **no FKs to `users_cognitouser`**. Consumer identity links only logically, via `username`.

Core FK graph:
- `brands_brand` → `company_company` (company_id), `locations_store` (store_id), `core_currency` (currency_id, activation_currency_id), `brands_brandcategory` (primary_category_id)
- `brands_branddenomination`, `branddenominationrange`, `brandhandlingfee`, `brandcommission`, `brandimagegallery`, `storelocation`, `brandgenericconfig`, `brandslug`, `offerpromocode`, `plusoffer`, `brandoffer`, `tagbrand`, `hasofferbrands` → `brands_brand`
- `brands_brandcommissiondetail` → `brands_brandcommission`
- `brands_plusoffer` → `core_country`, `brands_brand`. `brands_offerpromocode`, `brands_hasofferbrands`, `brands_plusoffer_happy_cards` and `configurations_brandpagepromotionbanner.plus_offer_id` → `brands_plusoffer`
- `brands_brandoffer` → `brands_productchannel`, `locations_store`, `core_currency` ×3
- `brands_genericbrandslist` → `brands_brandgenericconfig`, `brands_brand`. `configurations_happycardwidget_redeemable_brands` → `brands_genericbrandslist`
- `brands_tag` self-refs (`parent_tag_id`, `redirect_to_tag_id`). `brands_brandcategory`, `brands_occasion` and `configurations_homepageslider.category_id` → `brands_tag`
- `configurations_sliderbrand.brand_id` → **`brands_tagbrand`** (not `brands_brand`: a naming trap)
- `configurations_lastviewedbrand` → `brands_brand`, `locations_store`. `username` → logical key to `users_cognitouser.username` (unindexed on this side)
- `configurations_emailsubscription.platform_id`, `configurations_productfeedbackbox.platform_id` and `configurations_downloadapprequest.platform_id` → `configurations_platformchoice`. These are the **only 3 real FKs** to platformchoice (A15). Newsletter opt-ins, brand suggestions and app-link SMS requests can be split by platform (the last table is empty).
- `notifications_twofactorauth.created_by_id` (NOT NULL) and `modified_by_id` → `users_customuser` (staff/service accounts, not consumers)
- Verified M2M FKs (A3c): `brands_brandoccasion_brands` → `brands_brandoccasion` and `brands_brand`; `configurations_footer_country` → `configurations_footer` and `core_country`; `core_aigreetingsconfiguration_enabled_countries` → config and `core_country`; `core_aigreetingsconfiguration_enabled_languages` → config and `core_language`.
- **Half-constrained M2Ms**, where only one side has an FK: `users_customuser_groups` → `auth_group` only; `users_customuser_user_permissions` → `auth_permission` only; `configurations_testimonialvideo_country` → `core_country` only. **Unconstrained M2Ms**, with no FK at all: `core_country_languages`, `locations_store_languages`, `configurations_footer_payment_partners`, `configurations_footer_platform_type`, `configurations_header_platform_type`, `core_siteconfiguration_platform_type`. Joins through these rely on application integrity.
- `locations_store` → `core_country`, `core_currency`. Geography chain: `locations_community` → `locations_city` → `locations_state` → `core_country`
- `core_country` → `core_currency`, `core_language`. `core_currencyexchangerate` → `core_basecurrency` (base) and `core_currency` (foreign)
- `notifications_twofactorauthverification.reference_id_id` → `notifications_twofactorauth`
- The `*_platform_type` M2M tables have unique (x, platformchoice_id) but **no FK to `configurations_platformchoice`** in the catalog (logical only)

## Lifecycle States

**Value distributions could not be measured (no SELECT privilege).** Enum/state columns found in the catalog:

| Table.column | Type | Likely meaning |
|---|---|---|
| `users_cognitouser.platform` | varchar(10)! | Signup/last platform (web/ios/android) |
| `users_cognitouser.type` | varchar(63) | User type (native/social/federated?) |
| `users_cognitouser` flags | bool | `is_deleted`, `is_enabled`, `is_active`, `is_native_user`, `is_app_user`, `trusted_user`, `email_verified`, `phone_number_verified`: the account lifecycle |
| `brands_brand.redemption_type`, `generic_type`, `classification`, `expiry_type`, `activation_fee_deduct_type` | varchar | Brand behavior |
| `brands_brand` `is_active`, `is_launched`, `is_obsolete`, `date_disabled` | bool/ts | Brand lifecycle (draft → launched → disabled/obsolete) |
| `brands_plusoffer.offer_mode`, `offer_type`, `offer_channel`, `budget_type`, `funding_method`, `funded_by`, `sponsor_payment_threshold_type`, `reason_code`, `has_budget_exceeded` | varchar/bool | Offer campaign lifecycle and budget exhaustion |
| `brands_brandoffer.offer_base`, `offer_type`, `funding_method`, `funded_by`, `has_budget_exceeded` | varchar/bool | Brand offer lifecycle |
| `brands_offerpromocode.status` | varchar(20)! | Promo code state (available/used/expired?) |
| `brands_brandcommission.commission_type`, `gift_type`, `date_type` | varchar | Commission rules |
| `brands_brandhandlingfee.handling_fee_type` | varchar(20)! | Fee type |
| `brands_brandgenericconfig.generic_type`, `process_mode` | varchar(20)! | Generic-card processing |
| `brands_branddenominationrange.range_type` | varchar(25)! | Range kind |
| `brands_tag.tag_type`, `brand_ordering` | varchar(20) | Tag taxonomy |
| `configurations_brandpagepromotionbanner.banner_type`, `purchase_mode` | varchar(100)! | Purchase modes (e.g., buy-for-self / gift / group gift) |
| `configurations_banner.banner_type`, `homepageslider.slider_type`, `widgetorder.widget` | varchar(2) | CMS enums |
| `configurations_downloadapprequest.delivery_status` | varchar | SMS delivery state |
| `notifications_twofactorauth.auth_type`, `source` | varchar(64)! | OTP channel (sms/email) and originating flow |
| `notifications_twofactorauthverification.is_valid` | bool | OTP success/failure |
| `kafka_*datalog.status` | varchar(20)! | Message processing state (with `error_data`) |
| `webhooks_webhookmessage.type` | varchar(20) | Webhook kind |
| `django_admin_log.action_flag` | smallint | 1 = add, 2 = change, 3 = delete (Django standard) |
| `core_captchaconfigurations.action`, `captcha_version` | varchar | reCAPTCHA per action |

## Time Coverage & Trends

**Not measurable.** min/max and monthly counts need SELECT. Main timestamps, for when access is granted:
- `users_cognitouser.date_joined` (signup; **not indexed**, so a monthly trend is a full scan of about 221 MB of heap, acceptable once) and `modified_on`.
- `django_session.expire_date` (indexed). Session creation ≈ `expire_date - SESSION_COOKIE_AGE`.
- `configurations_lastviewedbrand.created_on` / `modified_on` (no index; 60K rows, cheap).
- `core_aigreetingmessages.created_on`, `django_admin_log.action_time`, `brands_brand.created_on` / `date_disabled`, `brands_plusoffer.start_date` / `end_date` (indexed).
- `webhooks_webhookmessage.received_at`, `kafka_*.start_timestamp` / `completed_timestamp` (tables empty).

Proxy for activity from replica counters (cumulative since the replica instance started; that start time was redacted in the output): xact_commit = 384,831,970, tup_returned = 114.9B, tup_fetched = 25.1B (exact counters).

## Behavior Signals

| Signal | Table(s) | Scale | Notes |
|---|---|---|---|
| Consumer signups / account base | `users_cognitouser` | ~980K (est) | `date_joined`, `platform`, `app_version`, `is_app_user`, `country_of_residence`, `language_code`, verification flags. Gives signup cohorts, platform mix, verification funnel and deletion rate. **No activity-recency signal:** there is no `last_login` or last-activity column, and `modified_on` is the only (weak) proxy. Recency and churn should come from `ygag_ecom_users_db.users_user.last_login` (readable, ~976K est). |
| Sessions | `django_session` | ~1.29M (est) | Session volume only; `session_data` is an encoded blob (may hold a basket/user id). No per-event log. |
| Brand views ("recently viewed") | `configurations_lastviewedbrand` | ~60K (est) | username × brand × store with created/modified. A per-user cap is **only a hypothesis**. No uniqueness on (username, brand_id) exists, so repeat-view duplicates are possible. *Inference:* the PK btree is 341 physical pages (2,728 KB) for about 60K rows (~176 per page, against ~345 for a dense bigint btree). That churn is consistent with rows being deleted, as a cap would do. Treat it as a **lower bound** on browsing, not a clickstream. Reads: 4,637 seq scans reading 276,237,053 tuples (≈59.6K per scan = the **whole table every time**) plus 3,251 `store_id` index scans reading 41.9M. |
| AI greetings | `core_aigreetingmessages` | ~538 (est) | **Response cache or pre-generated greeting pool** keyed by tone/relation/occasion (`note` indexes have 0 scans). Replica lookups by value: relation 740, occasion 701, tone 434, pkey 3, with ≈54–166 rows read per scan. **Do not use 538 as a usage count.** Real usage is not recorded here. Widget-open proxy: `core_aigreetingsparameters` 55,172 seq scans vs ~2.5K message reads (see section 7). |
| Brand suggestion feedback | `configurations_productfeedbackbox` | ~106 | Demand signal for missing brands, splittable by `platform_id` (FK to platformchoice). |
| Newsletter subscriptions | `configurations_emailsubscription` | never analyzed (32 KB) | `is_subscribed` opt-in/out by `platform_id`. `extra` jsonb may carry attribution (unverified). |
| OTP / 2FA | `notifications_twofactorauth(+verification)` | ~10 each | Tiny, and the audience is unverified (the creator FK points to staff). Consumer OTP is in `ygag_ecom_users_db.notifications_twofactorauth` (~66.8K est). |
| Referral / campaign attribution | — | none | Catalog search for `referr`, `utm`, `campaign`, `source`, `affiliat`, `medium`, `coupon` (A10) finds **no attribution columns**. The only hit is `notifications_twofactorauth.source` (OTP flow origin). Promo codes exist only as offer definitions (`brands_offerpromocode`, `brands_plusoffer.*promo_code*`). |
| Offer / campaign definitions | `brands_plusoffer`, `brands_brandoffer`, `brands_offerpromocode`, `configurations_brandpagepromotionbanner`, banners/sliders | 378 plus offers, 40 promo codes | Campaign **definitions** (window, budget, funding, sponsor network), not redemptions. Redemption/usage facts must come from orders/checkout DBs. |
| Admin/ops changes | `django_admin_log` | ~13.5K | Catalog/CMS change history (who changed which brand/offer, when). Useful for "what changed before a metric moved". |
| Read-traffic hotness | `pg_stat_all_tables` (replica) | exact counters | `brands_brand` idx_scan 8,456,113,102; `brands_tagbrand` 105.7M; `brands_tag` 44.0M; `core_country` seq 168.6M; `locations_store` seq 97.0M; `brands_plusoffer` idx 3.9M; `users_cognitouser` idx 62,718; `django_session` idx 9,272; `configurations_lastviewedbrand` seq 4,637 / idx 3,251; `core_sitemeta` seq 877,516 (1.99B tuples). The replica clearly serves storefront catalog reads. *Inference (not measured):* the low user and session counters suggest those reads mostly hit the writer. Writer statistics were not available. |

### Per-index usage (replica, `pg_stat_all_indexes`, exact cumulative counters, A11)

| Table | Index | idx_scan | idx_tup_read | Reading |
|---|---|---|---|---|
| `users_cognitouser` | `(username, is_enabled)` | 62,740 | 36,459 | **Every** single-user lookup resolves by username and filters on enabled status. |
| `users_cognitouser` | `username_key`, `email_key`, `phone_number_key`, 3 `_like`, `secondary_emails` GIN | 0 each | 0 | No lookups by email/phone on the replica. These 7 indexes (359,432 KB ≈ 351 MB together, exact sizes) serve only uniqueness checks on the writer. |
| `users_cognitouser` | `pkey` | 7 | 1,972,534 | About 2 full-table sweeps of ~980K rows each. Combined with the table's **24 seq scans reading 7,777,468 tuples** (≈7.9 full-table equivalents, A14), that is **31 bulk scans reading ~9.75M tuples ≈ 10 full-table equivalents**. This looks like a periodic batch export or sync job, not user traffic. |
| `brands_plusoffer` | `brand_id` | 1,744,884 | 2,789,420 | Offer eligibility is resolved **per brand** on page render. |
| `brands_plusoffer` | `pkey` | 1,127,416 | 1,667,988 | Direct offer fetch. |
| `brands_plusoffer` | `start_date` composite | 957,893 | 4,572,869 | Active-window filter (start/end date). |
| `brands_plusoffer` | `offer_type` composite | 61,866 | 4,858,192 | Offer-type listing; ~78 tuples per scan. |
| `brands_plusoffer` | `code_like` | 6,411 | 47,151 | Lookup by offer code. |
| `configurations_lastviewedbrand` | `store_id` | 3,251 | 41,945,899 | ~12.9K tuples read per scan: every row for the store, then filtered by `username` in the heap, because there is no username index. |
| `configurations_lastviewedbrand` | *(seq path, `pg_stat_all_tables`)* | seq_scan 4,637 | seq_tup_read 276,237,053 | **≈59.6K tuples per scan = a full-table scan every time** (59,921 est rows). This path reads **~6.6× more tuples than the index path**, so the dominant inefficiency is the full-table scans, not the store_id scans. Together, "recently viewed" has read ~318M tuples to serve ~7.9K requests. |
| `configurations_lastviewedbrand` | `brand_id`, `pkey` | 0 | 0 | — |
| `core_aigreetingmessages` | `relation_like` / `occasion_like` / `tone_like` / `pkey` | 740 / 701 / 434 / 3 | 47,691 / 37,842 / 71,952 / 300 | Lookup by parameter values, ≈64 / 54 / 166 rows per scan. |
| `core_aigreetingmessages` | `note`, `note_like`, and the plain (non-`_like`) tone/relation/occasion btrees | 0 each | 0 | `note` is never a lookup key. |
| `django_session` | `session_key_like` / `expire_date` / `pkey` | 8,072 / 1,203 / 0 | 2,348 / 1,196 / 0 | Low. Session reads are mostly elsewhere (inference). |

### Per-request CMS config reads (replica seq scans, exact, A6b)

Tiny config tables are seq-scanned tens of millions of times: `configurations_platformchoice` 73.2M (4 rows), `configurations_header_platform_type` 48.1M, `configurations_headertype` 35.6M, `core_language` 32.4M, `locations_store_languages` 28.9M, `configurations_header` 24.3M, `configurations_menuitem` 24.3M (1.60B tuples read), `core_siteconfiguration` 9.95M, `core_siteconfiguration_platform_type` 9.95M, `core_country_languages` 4.67M, `core_captchaconfigurations` 2.55M, `configurations_footerstore` 2.33M. Also `core_country` 168.7M and `locations_store` 97.1M. **System-behavior signal:** the storefront fetches header, menu, site and language config from the DB on every request with no application cache. `siteconfiguration` and `siteconfiguration_platform_type` have identical counts (9,948,717 vs 9,948,701), so they are read as a pair. As a rough proxy, 9.95M is a count of page renders or API boots since the replica started. That start time is unknown. `brands_tagbrand` reads 77.1B tuples across 2.36M seq scans (~32.7K per scan), which amounts to full-table scans of the brand↔tag table. **`core_sitemeta`** is another hot path: **877,516 seq scans reading 1,990,206,288 tuples (≈2,268 rows per scan)**, i.e. a full scan on every SEO-meta lookup to match `url_pattern`. It has **never been analyzed** (`reltuples = -1`), so the planner has no stats on one of the most-read tables in the DB.

### Read-counter traffic proxies (replica, exact counters, A14)

**Caveat:** these are cumulative replica reads since an unknown start time (stats_reset was redacted), and the writer's reads are not included. **Ratios between rows are usable; absolute values are not traffic counts** (not sessions, not users). All interpretations are *inference*.

| Table | Counter | Value | Interpretation (inference) |
|---|---|---|---|
| `core_siteconfiguration` | seq_scan | 9,954,411 | Baseline: ~one read per page render / API boot |
| `core_sitemeta` | seq_scan | 877,516 (1.99B tuples) | SEO landing-page renders (≈8.8% of baseline); full scan each time |
| `configurations_widgetorder` | seq_scan | 655,039 | Homepage layout loads (≈6.6% of baseline) |
| `configurations_homepageslider` | idx_scan | 450,169 | Homepage slider renders |
| `configurations_brandpagepromotionbanner` | seq_scan | 423,007 | Brand-page renders (promo banner check) |
| `brands_branddenomination` | idx_scan | 1,289,367 | Fixed-amount selection / denomination display |
| `brands_branddenominationrange` | idx_scan | 1,324,131 | Open-amount range display |
| `brands_genericbrandslist` | idx_scan | 2,168,518 (154.5M tuples fetched, ≈71 per scan) | Happy Card "redeemable brands" lists |
| `brands_brandimagegallery` | idx_scan | 560,045 | Brand-page image galleries |
| `brands_brandsearchtag` | seq_scan | 6,274 (108,370,520 tuples, ≈17.3K per scan) | Search volume proxy; **full-table scan per search** (16,864 est rows). Plus 846,367 idx scans (tag display). |
| `configurations_searchtag` | seq_scan | 3,991 | Search suggestions shown |
| `core_captchaconfigurations` | seq_scan | 2,546,397 | Plausibly one read per captcha-protected action (login/signup/OTP/checkout): a **bot-defense friction volume proxy** (≈26% of baseline) |
| `core_unsupportedcountry` | seq_scan | 3,185 | Geo-block check. Tiny vs page renders, so likely only on specific flows (signup/checkout) |
| `webhooks_remoteurlconfig` | seq_scan | 15,735 | Outbound third-party calls (credentials fetched per call) |
| `webhooks_webhookconfig` | seq_scan | 3,140 | Inbound webhook auth checks (`webhookmessage` heap is 0, so this is the only surviving evidence of webhook traffic) |

Rough funnel (proxy only): page renders 9.95M → homepage layout 655K / slider 450K → brand-page banner check 423K → amount selection 1.29M–1.32M. Amount-selection reads exceed brand-page reads, so denominations are probably also loaded on listing and card widgets; do not read this as a conversion funnel.

**Dead-feature polling (system behavior):** `configurations_upcomingoccasion` has **89,306 seq scans** and `configurations_announcement` **52,261**, both on **0-row tables**. `configurations_themeconfig` (1 row) is read 187,614 times and `configurations_whitelabelbrandconfigs` (never analyzed) 27,882 times. The storefront keeps polling flags for features that hold no data.

**Zero replica reads:** `brands_brandoffer`, `brands_brandoffer_happy_cards`, `brands_brandcommission`, `brands_brandcommissiondetail`, `brands_brandhandlingfee` and `core_currencyexchangerate` have **0 seq and 0 idx scans** on the replica. Either the storefront does not use them or they are read only on the writer (admin / back-office). This matters for the "two offer systems" point: `brands_plusoffer` is read ~3.9M times, `brands_brandoffer` never, so **brandoffer may be dormant as a storefront offer system**.

**Not captured here:** baskets, orders, payments, gift creation/redemption, referrals, wallets, notifications sent. Look for these in `ygag_ecom_orders_db`, `ygag_ecom_gifts_db`, `ygag_checkout_db`, `ygag_ecom_users_db`, `ygag_ecom_wallet_restored_db`, `ygag_mailengine_aps_db` and `ygag_smsengine_db`.

## Friction & Errors

- **Webhook failures**: `webhooks_webhookmessage.error_message` jsonb exists, but the heap is **0 rows**. The PK index is still 13,264 KB (~1,658 pages), which *by inference* means roughly 500K–600K webhook messages were held at peak (not a lifetime count, since btree pages are recycled after deletes) and then deleted. No webhook error history is retained.
- **Kafka publish failures**: `kafka_webstoreskafkadatalog` and `kafka_giftkafkadatalog` (`status`, `error_data`) are both 0 rows. The webstores PK index is 192 KB (24 pages), so *by inference* it held ~5K–9K rows before being purged.
- **OTP failures**: `notifications_twofactorauthverification.is_valid=false` and `notifications_twofactorauth.requested_attempts`. Only about 10 rows, and the audience is unverified.
- **Slow "recently viewed" reads**: `configurations_lastviewedbrand` does a **full-table scan (~59.6K tuples) on each of 4,637 seq scans** (276.2M tuples) and ~12.9K tuples per `store_id` index scan (41.9M), because there is no username index. This is a latency risk, not a user-visible error.
- **Full-scan search**: `brands_brandsearchtag` reads ≈17.3K tuples (the whole table) per search seq scan; `core_sitemeta` ≈2,268 per SEO lookup.
- **Admin 2FA throttling**: `throttling_failure_count` / `throttling_failure_timestamp` on OTP devices (15 TOTP devices).
- **Bot friction**: `core_captchaconfigurations` (3 rows) defines per-action reCAPTCHA score thresholds. Blocks are not logged here, but its 2,546,397 replica seq scans are *plausibly* one per captcha-protected action, a volume proxy for protected actions (inference).
- **Offer budget exhaustion**: `brands_plusoffer.has_budget_exceeded`, `brands_brandoffer.has_budget_exceeded`. Counts need SELECT.
- **Geo blocking**: `core_unsupportedcountry` (country_code list). Only 3,185 replica seq scans, so it is checked on specific flows only (likely signup/checkout; inference).
- **Account disablement**: `users_cognitouser.is_enabled=false`, `is_deleted`. Rates need SELECT.
- **App-link SMS delivery**: `configurations_downloadapprequest.delivery_status` (0 rows).
- No rate could be measured.

## Cross-DB Keys

Types are from the catalog. Ranges could not be read (sequence `last_value` is NULL and tables are unreadable).

| Column | Type | Likely joins to |
|---|---|---|
| `users_cognitouser.sub` | varchar(150), **nullable, not unique, not indexed** | Cognito subject, and the *candidate* consumer id across ecom_users (`users_user.sub` varchar(150)), orders, gifts, wallet and checkout. **Join risk:** NULLs and duplicates are possible, and every join on it is a full scan of ~221 MB. Validate the null and duplicate rate before using it as a key. |
| `users_cognitouser.username` | varchar(150) NOT NULL unique | **The only indexed unique consumer key**, used by all replica lookups (with `is_enabled`). Also `configurations_lastviewedbrand.username` (nullable, unindexed there). Note `ygag_ecom_users_db.users_user.username` is varchar(36), which suggests UUID-style Cognito usernames. The formats may differ, so verify before joining. |
| `users_cognitouser.id` | bigint | Local surrogate. Probably not shared. |
| `configurations_productfeedbackbox.user_reference` | varchar(255) | Logical user reference (format unknown) |
| `brands_brand.code` | varchar(20) unique | Brand code shared with orders/gifts/emapi_stores/giftshop/merchant console |
| `brands_brand.gencode`, `brands_branddenomination.gencode` | varchar(50) | Product/SKU generation codes, likely a gift-issuance catalog key |
| `brands_brand.slug`, `brands_brand.id` | varchar / bigint | Storefront URL key. id may be referenced as `brand_id` in orders. |
| `company_company.code` (varchar 10), `ref_code` (varchar 20) | varchar | Merchant/company code shared with merchant console / hub |
| `brands_plusoffer.code` | varchar(10) unique | Offer code. Join to `ygag_plusoffers_db` and order promo fields. |
| `brands_offerpromocode.promo_code` | varchar(200) | Promo code value (sensitive), matches order discount code |
| `brands_brandcommission.code`, `brands_brandhandlingfee.code` | varchar | Finance rule codes |
| `locations_store.code` | varchar(50) unique | Per-country store code (e.g., AE/SA storefront). Likely `store` in orders. |
| `core_country.code` (ISO2) / `code_three_letter`; `core_currency.code` (ISO3); `core_language.code` | varchar | Universal reference keys |
| `brands_plusoffer.sponsor_payment_network_code` | varchar(20) | Card network (Visa/Mastercard) sponsor, matching checkout/payment network |
| `notifications_twofactorauth.reference_id` | varchar(32) unique | OTP reference, possibly shared with smsengine |
| `webhooks_webhookconfig.webhook_key` | varchar(32) | Webhook sender identity |

## PII

Column names only. No values were read.
- `users_cognitouser`: `username`, `email`, `secondary_emails`, `phone_number`, `name`, `middle_name`, `nickname`, `birthdate`, `gender`, `location`, `country_of_residence`, `ip_address`, `user_agent`, `sub`, `legacy_auth_code`
- `users_customuser`: `first_name`, `last_name`, `email`, `username`, `password` (hash), `last_login`
- `users_passwordhistory.password_hash`
- `otp_totp_totpdevice.key`, `otp_static_statictoken.token`, `two_factor_phonedevice.number`, `two_factor_phonedevice.key` (**secrets**)
- `notifications_twofactorauth.phone_number`, `email`; `notifications_twofactorauthverification.auth_code` (OTP)
- `configurations_lastviewedbrand.username`
- `configurations_emailsubscription.email_address`, `configurations_productfeedbackbox.email_address`, `user_reference`, `configurations_downloadapprequest.phone_number`
- `configurations_testimonialreview.customer_name`
- `notifications_emailtemplateconfiguration.to_emails`
- `webhooks_webhookmessage.ip_address`, `message` (payload may contain PII); `webhooks_webhookconfig.sender_ip`
- `webhooks_remoteurlconfig.api_key`, `api_secret`, `application_id` (**stored third-party credentials**)
- `django_session.session_data`, `session_key` (session tokens)
- `django_admin_log.object_repr`, `change_message` (may embed names/emails)
- `brands_storelocation.contact_number`, `contact_email`, `address` (business contact, lower sensitivity)
- `brands_offerpromocode.promo_code` (redeemable value)

## Data Quality

- **Access**: the atlas role cannot read any row. This is the primary blocker (see top).
- **Never analyzed on the primary** (`reltuples = -1`, so the planner has no stats): `brands_brandcommission`, `brands_brandcommissiondetail`, `brands_brandoffer`, `brands_brandoffer_happy_cards`, `configurations_blog`, `customcategoryslider`, `emailsubscription`, `happycardwidget`, `homepageslider`, `testimonialreview`, `themeconfig_country`, `whitelabelbrandconfigs`, `core_sitemeta` (1 MB heap), `core_unsupportedcountry`, `users_passwordhistory`, `auth_group_permissions`, `dashboard_userdashboardmodule`, `django_migrations`. All are small, but **`core_sitemeta` is also one of the hottest tables** (877,516 seq scans, 1.99B tuples read), and `configurations_homepageslider` (450K idx scans) and `whitelabelbrandconfigs` (27.9K seq scans) are also read often while unanalyzed.
- **Dead/empty tables (0 heap pages)**: `brands_categorygender`, `configurations_announcement(+_country, _platform_type)`, `crosssellbrand`, `crosssellbrandconfig`, `downloadapprequest`, `downloadapptext`, `happycardwidget_redeemable_brands`, `pressroom`, `testimonialorder`, `upcomingoccasion(+_country)`, `jet_bookmark`, `jet_pinnedapplication`, `kafka_giftkafkadatalog`, `kafka_webstoreskafkadatalog`, `two_factor_phonedevice`, `webhooks_webhookmessage`.
- **Purged logs**: `webhooks_webhookmessage` (13 MB index, 0 heap) and `kafka_webstoreskafkadatalog` (216 KB index, 0 heap). Retention is effectively zero, so these cannot back error-rate metrics.
- **Unused indexes on the replica**: 536 of 632 indexes have `idx_scan = 0` here. Writer usage is unknown.
- **Index-heavy user table**: `users_cognitouser` has 446 MB of indexes on 221 MB of heap (email/phone/username each indexed twice, plus a GIN), and **no `date_joined` index**.
- **Unused unique indexes**: `users_cognitouser` email/phone/username unique and `_like` indexes plus the GIN (~351 MB) have 0 replica scans. The only one used is `(username, is_enabled)`.
- **`configurations_lastviewedbrand` integrity**: there is no index on `username` and no unique constraint on `(username, brand_id)`, and `username` and `store_id` are nullable. Duplicate rows for repeat views are possible, so dedupe on (username, brand_id) before counting "brands viewed per user". The missing index causes full-table seq scans (4,637 × ~59.6K = 276.2M tuples) and ~12.9K tuples per store_id index lookup (41.9M).
- **Polling of empty tables**: `configurations_upcomingoccasion` (89,306 seq scans) and `configurations_announcement` (52,261) are 0-row tables still read by the storefront.
- **Unread on replica**: `brands_brandoffer(+_happy_cards)`, `brands_brandcommission(+detail)`, `brands_brandhandlingfee`, `core_currencyexchangerate` have 0 replica reads; their storefront use is unconfirmed.
- **`users_cognitouser.sub`** is nullable, non-unique and unindexed, so it is a weak join key (see Cross-DB Keys).
- **No activity timestamp** on `users_cognitouser` (no `last_login`).
- **Duplicated concepts**: two user tables (`users_cognitouser` = consumers, `users_customuser` = staff), plus a third, `ygag_ecom_users_db.users_user` (~976K est); two offer systems (`brands_brandoffer` vs `brands_plusoffer`; brandoffer has 0 replica reads vs ~3.9M idx scans on plusoffer, so brandoffer may be dormant on the storefront); two 2FA systems (django-otp/two_factor for staff vs `notifications_twofactorauth`, whose audience is **unverified**: its creator FK is to staff, and consumer OTP volume (~66.8K) sits in ecom_users_db instead); two search-tag concepts (`brands_brandsearchtag` vs `configurations_searchtag`); `brands_brand.is_generic`/`generic_type` vs `brands_brandgenericconfig.generic_type`; `brands_brand.plus_offers_details` jsonb duplicates relational plus-offer links.
- **Naming trap**: `configurations_sliderbrand.brand_id` references `brands_tagbrand`, not `brands_brand`.
- **Weak typing**: `users_cognitouser.birthdate` is varchar(50); `users_cognitouser` has no `created_on` (uses `date_joined`).
- **Missing FKs**: the `*_platform_type` M2M tables lack an FK to `configurations_platformchoice`; `core_country_languages`, `locations_store_languages` and `configurations_footer_payment_partners` have no FKs at all; `users_customuser_groups`, `users_customuser_user_permissions` and `configurations_testimonialvideo_country` are constrained on one side only; `lastviewedbrand.username` has no FK to users. By contrast, `emailsubscription.platform_id`, `productfeedbackbox.platform_id` and `downloadapprequest.platform_id` **do** have real FKs to platformchoice (the only three, A15).
- **Purged logs, sized by inference**: webhook messages ~500K–600K rows at peak (13 MB PK; peak retained, not lifetime), Kafka webstores log ~5K–9K at peak (192 KB PK).

## Open Questions

1. **Grant SELECT to `<emapi_login_role>`** on this DB. Minimum useful set: `users_cognitouser` (ideally a view without email/phone/name/ip), `configurations_lastviewedbrand`, `django_session` (`expire_date` only), all `brands_*`, `company_company`, `locations_*`, `core_*`, `configurations_*` (non-PII), `core_aigreetingmessages`, `django_admin_log`. Explicitly **exclude** `otp_*`, `two_factor_*`, `users_passwordhistory`, `webhooks_remoteurlconfig` (credentials) and `users_customuser.password`. **This is not an isolated miss.** `ygag_emapi_stores_db` (0/84 tables readable) and `ygag_plusoffers_db` (0/49) are blocked the same way, and both matter here: emapi_stores has its own `brands_plusoffer` and `kafka_plusofferkafkadatalog`, and plusoffers is the candidate authority for plus offers. `ygag_ecom_users_db` is readable (40/40). **File one grant request covering all three blocked DBs**, with the same PII and credential exclusions.
2. Is `users_cognitouser` the system of record for consumers, or a cache of `ygag_ecom_users_db.users_user` (~976K est vs ~980K here)? Which key (`sub` or `username`) do orders and gifts use? The `sub` column here is nullable, non-unique and unindexed, and the `username` widths differ (150 here vs 36 in ecom_users). Until the grant lands, profile the consumer base from ecom_users_db (it has `last_login` and `users_cognitoissuedtokens`).
3. What is the retention/purge job for `webhooks_webhookmessage` (~500K–600K rows at peak, inferred from the PK size) and the Kafka datalogs? Can error history be retained or shipped elsewhere?
4. Is `configurations_lastviewedbrand` capped per user (last N)? **Nothing in the schema enforces a cap or uniqueness.** There is no `(username, brand_id)` unique constraint, so repeat views can create duplicate rows, and there is no `username` index, so reads do full-table seq scans (~59.6K rows each) or scan ~12.9K rows per store lookup. The PK-page density (~176 rows per physical page) hints at deletions, consistent with an app-level cap, but that is unverified.
5. What are the value sets of `platform`, `type`, `redemption_type`, `classification`, `offer_mode`, `offer_channel`, `purchase_mode` and `offerpromocode.status`?
6. Is `brands_brand.code` or `gencode` the key used in `ygag_ecom_orders_db` / `ygag_ecom_gifts_db`?
7. Does `brands_plusoffer` duplicate `ygag_plusoffers_db`, and which is authoritative?
8. When did the primary last ANALYZE? `reltuples` values may be stale.
9. Is `core_aigreetingmessages` a response cache keyed by (tone, relation, occasion), or a pre-generated greeting pool (≈54–166 rows matched per lookup)? Where is actual AI-greeting usage logged?
12. Are `brands_brandoffer`, `brands_brandcommission`, `brands_brandhandlingfee` and `core_currencyexchangerate` used by the storefront at all (0 replica reads), or only by writer-side back-office jobs?
13. Can `upcomingoccasion` / `announcement` polling (141K reads of empty tables) and the full-scan paths (`lastviewedbrand`, `brandsearchtag`, `sitemeta`) be fixed with caching or indexes? What is the replica's stats_reset time, so the counters can be turned into rates?
10. Who creates `notifications_twofactorauth` rows here (the creator FK is to staff users)? Is this app's consumer OTP deprecated in favour of ecom_users_db?
11. What do the `extra` jsonb fields on `configurations_emailsubscription` and `configurations_productfeedbackbox` contain (attribution)?

## Appendix: SQL provenance

All queries ran via `atlasq.sh ygag_ecomweb_stores_db`.

**A1. Table inventory, row estimates, sizes** (the source of every "Est. rows" and size figure)
```sql
select n.nspname, c.relname, c.reltuples::bigint est, pg_total_relation_size(c.oid)/1024 kb, s.n_live_tup, s.last_autoanalyze::date
from pg_class c join pg_namespace n on n.oid=c.relnamespace left join pg_stat_user_tables s on s.relid=c.oid
where n.nspname not in ('pg_catalog','information_schema','pg_toast') and c.relkind in ('r','p') order by c.relname;
```
Result: 134 tables in `public`, all with n_live_tup = 0 (replica).

**A2. Columns** (information_schema.columns returned 0 rows due to privileges, so pg_attribute was used)
```sql
select c.relname, a.attname, format_type(a.atttypid,a.atttypmod), a.attnotnull
from pg_attribute a join pg_class c on c.oid=a.attrelid
where c.relnamespace='public'::regnamespace and c.relkind='r' and a.attnum>0 and not a.attisdropped;
```

**A3. FK / unique constraints** (370 rows)
```sql
select conrelid::regclass::text t, contype, string_agg(a.attname, ',') cols, confrelid::regclass::text ref
from pg_constraint c join pg_attribute a on a.attrelid=c.conrelid and a.attnum=any(c.conkey)
where connamespace='public'::regnamespace and contype in ('f','u') group by c.oid, conrelid, contype, confrelid order by 1,2;
```

**A4. Privilege check** (the source of "no SELECT on any table")
```sql
select has_table_privilege(c.oid,'SELECT') ok, count(*) from pg_class c
where relnamespace='public'::regnamespace and relkind='r' group by 1;              -- false: 134
select current_user;                                                                -- <emapi_login_role>
select count(*) from pg_class c where relnamespace='public'::regnamespace and relkind='r'
  and has_any_column_privilege(c.oid,'SELECT');                                     -- 0
select count(*) from users_cognitouser ...;  -- InsufficientPrivilegeError: permission denied for table users_cognitouser
select sequencename, last_value from pg_sequences where schemaname='public';        -- 133 seqs, all last_value NULL
```

**A5. Heap / index / toast split** (the source of the "purged log" and "index-heavy" findings)
```sql
select c.relname, c.relpages, c.reltuples::bigint, pg_relation_size(c.oid)/1024 heap_kb, pg_indexes_size(c.oid)/1024 idx_kb,
       coalesce(pg_relation_size(c.reltoastrelid),0)/1024 toast_kb
from pg_class c where relnamespace='public'::regnamespace and relkind='r'
 and (c.reltuples<=0 or relname in ('users_cognitouser','django_session','webhooks_webhookmessage','kafka_webstoreskafkadatalog',
      'kafka_giftkafkadatalog','configurations_lastviewedbrand','django_admin_log','brands_brand'));
```
Key results: users_cognitouser heap 226,672 KB / idx 456,680 KB; django_session heap 194,920 / idx 228,696; webhooks_webhookmessage heap 0 / idx 13,288; kafka_webstoreskafkadatalog heap 0 / idx 216.

**A6. Replica read counters** (exact, cumulative)
```sql
select relname, seq_scan, idx_scan from pg_stat_all_tables where schemaname='public'
order by coalesce(seq_scan,0)+coalesce(idx_scan,0) desc;
select stats_reset, pg_is_in_recovery(), version(), pg_database_size(current_database())/1024/1024 mb, xact_commit, tup_returned, tup_fetched
from pg_stat_database where datname=current_database();
select count(*) idx, count(*) filter (where s.idx_scan=0) from pg_stat_all_indexes s where schemaname='public';  -- 632 / 536
```

**A7. Indexes on large tables**
```sql
select tablename, indexname, indexdef from pg_indexes
where tablename in ('users_cognitouser','django_session','configurations_lastviewedbrand','webhooks_webhookmessage','kafka_webstoreskafkadatalog','django_admin_log');
```

**A8. Other catalog objects**
```sql
-- views 0, non-internal triggers 0, functions 31 (all pg_trgm), comments 0, CHECK constraints 46 (all ">= 0" on positive ints)
select conrelid::regclass, pg_get_constraintdef(oid) from pg_constraint where connamespace='public'::regnamespace and contype='c';
```

**A2b. Full column list for key tables** (the source of "no last_login", nullability of `sub`/`username`, and the `extra`/`platform_id` columns)
```sql
select c.relname, a.attnum, a.attname, format_type(a.atttypid,a.atttypmod), a.attnotnull
from pg_attribute a join pg_class c on c.oid=a.attrelid
where c.relnamespace='public'::regnamespace and c.relkind='r' and a.attnum>0 and not a.attisdropped
  and c.relname in ('users_cognitouser','notifications_twofactorauth','configurations_emailsubscription',
                    'configurations_productfeedbackbox','configurations_lastviewedbrand','core_aigreetingmessages')
order by 1,2;
```
Result: users_cognitouser has 30 columns, none named last_login/last_*; `sub` attnotnull=false; `username` attnotnull=true. twofactorauth.created_by_id attnotnull=true. emailsubscription/productfeedbackbox: `extra` jsonb NOT NULL, `platform_id` bigint NOT NULL. lastviewedbrand: `username`, `store_id` nullable.

**A3b. Constraints on key tables** (FKs of platform_id and created_by_id; no unique on lastviewedbrand; cognitouser unique = username, email, phone_number only)
```sql
select conrelid::regclass::text, conname, contype, pg_get_constraintdef(oid) from pg_constraint
where conrelid::regclass::text in ('users_cognitouser','notifications_twofactorauth','configurations_emailsubscription',
  'configurations_productfeedbackbox','configurations_lastviewedbrand','core_aigreetingmessages','webhooks_webhookmessage');
```

**A3c. M2M FK verification**
```sql
select conrelid::regclass::text, pg_get_constraintdef(oid) from pg_constraint where contype='f'
 and conrelid::regclass::text in ('users_customuser_groups','users_customuser_user_permissions','core_country_languages',
 'locations_store_languages','core_aigreetingsconfiguration_enabled_languages','core_aigreetingsconfiguration_enabled_countries',
 'brands_brandoccasion_brands','configurations_footer_payment_partners','configurations_footer_country',
 'configurations_footer_platform_type','core_siteconfiguration_platform_type','configurations_testimonialvideo_country',
 'configurations_header_platform_type');
```
Result: 11 FKs. None for core_country_languages, locations_store_languages, footer_payment_partners, footer_platform_type, header_platform_type or siteconfiguration_platform_type. One side only for customuser_groups, customuser_user_permissions and testimonialvideo_country.

**A6b. Hot tables, top 30 by scans** (exact replica counters; the source of the CMS per-request figures)
```sql
select relname, seq_scan, seq_tup_read, idx_scan from pg_stat_all_tables where schemaname='public'
order by coalesce(seq_scan,0)+coalesce(idx_scan,0) desc limit 30;
```
Key results: brands_brand idx 8,462,470,018; core_country seq 168,690,871; brands_tagbrand seq 2,360,800 / seq_tup_read 77,095,611,150 / idx 105,713,353; locations_store seq 97,062,628; configurations_platformchoice seq 73,236,501; configurations_header_platform_type 48,147,624; configurations_headertype 35,623,780; core_language 32,393,045; locations_store_languages 28,909,633; configurations_header 24,299,599; configurations_menuitem 24,277,930 (tup 1,602,343,380); core_siteconfiguration 9,948,717; core_siteconfiguration_platform_type 9,948,701; core_country_languages 4,671,452; core_captchaconfigurations 2,545,900; configurations_footerstore 2,325,020.

**A7b. Indexes on lastviewedbrand / webhookmessage / aigreetingmessages / cognitouser** (A7 re-run with indexdef)
```sql
select tablename, indexname, indexdef from pg_indexes
where tablename in ('configurations_lastviewedbrand','webhooks_webhookmessage','core_aigreetingmessages','users_cognitouser');
```
Result: webhookmessage has only `webhooks_webhookmessage_pkey (id)`; lastviewedbrand has pkey, brand_id and store_id (no username); cognitouser has no index on `sub` or `date_joined`.

**A9. Cross-DB privilege check** (run once per DB)
```sql
select current_database(), count(*) total, count(*) filter (where has_table_privilege(c.oid,'SELECT')) sel_ok
from pg_class c where relnamespace='public'::regnamespace and relkind in ('r','p');
```
Results (exact): ygag_ecomweb_stores_db 134/0; ygag_emapi_stores_db 84/0; ygag_plusoffers_db 49/0; ygag_ecom_users_db 40/40.

**A10. Attribution / status column-name search**
```sql
select c.relname, a.attname, format_type(a.atttypid,a.atttypmod), a.attnotnull
from pg_attribute a join pg_class c on c.oid=a.attrelid
where c.relnamespace='public'::regnamespace and c.relkind='r' and a.attnum>0 and not a.attisdropped
  and a.attname ~* '(referr|utm|campaign|source|coupon|error|status|affiliat|medium|channel|promo|login|last_|activity|seen)';
```
Result: 20 columns. None match referr/utm/campaign/affiliat/medium/coupon. `source` appears only on notifications_twofactorauth. Status/error columns: offerpromocode.status, downloadapprequest.delivery_status, kafka_*.status/error_data, webhookmessage.error_message. `last_login` appears only on users_customuser (staff).

**A11. Per-index usage** (exact replica counters)
```sql
select s.relname, s.indexrelname, s.idx_scan, s.idx_tup_read, s.idx_tup_fetch, pg_relation_size(s.indexrelid)/1024 kb
from pg_stat_all_indexes s where schemaname='public' and relname in ('users_cognitouser','brands_plusoffer',
 'configurations_lastviewedbrand','core_aigreetingmessages','webhooks_webhookmessage','kafka_webstoreskafkadatalog',
 'django_session','notifications_twofactorauth') order by relname, idx_scan desc;
```
Key results: cognitouser (username,is_enabled) 62,740 scans / 36,459 read; pkey 7 / 1,972,534; all other cognitouser indexes 0. plusoffer brand_id 1,744,884; pkey 1,127,416; start_date composite 957,893; offer_type composite 61,866 / 4,858,192 read; code_like 6,411. lastviewedbrand store_id 3,251 / 41,945,899 read (≈12,902 per scan); brand_id and pkey 0. aigreeting relation_like 739, occasion_like 701, tone_like 433, pkey 3 (first run; superseded by A11b: 740 / 701 / 434, note indexes 0). webhookmessage_pkey 13,264 KB, 0 scans. kafka_webstoreskafkadatalog_pkey 192 KB.

**A12. Index page counts** (the input to the purged-row and churn inferences)
```sql
select relname, relpages, pg_relation_size(oid)/1024 kb, current_setting('block_size')
from pg_class where relname in ('webhooks_webhookmessage_pkey','kafka_webstoreskafkadatalog_pkey',
 'users_cognitouser_pkey','configurations_lastviewedbrand_pkey');
```
Result: block 8192. webhook pkey 13,264 KB (= 1,658 pages physical; relpages reads 1, a stale stat); kafka pkey 192 KB (24 pages); cognitouser pkey 2,844 pages for 980,177 est rows (≈345 per page, the dense-btree baseline); lastviewedbrand pkey 2,728 KB = **341 physical pages** (relpages reads 338, slightly stale) for 59,921 rows (≈176 per page). *Inference:* peak retained rows ≈ physical pages × 300–370 (pages are recycled after deletes, so this is not a lifetime count).

**A14. Read counters for traffic proxies, sweeps and dead tables** (exact replica counters, re-run 2026-09-29)
```sql
select s.relname, s.seq_scan, s.seq_tup_read, s.idx_scan, s.idx_tup_fetch, c.reltuples::bigint est
from pg_stat_all_tables s join pg_class c on c.oid=s.relid
where s.schemaname='public' and s.relname in ('configurations_lastviewedbrand','users_cognitouser','core_aigreetingsparameters',
 'core_aigreetingsconfiguration','core_aigreetingmessages','core_captchaconfigurations','core_sitemeta','configurations_widgetorder',
 'configurations_homepageslider','configurations_brandpagepromotionbanner','brands_branddenomination','brands_branddenominationrange',
 'brands_genericbrandslist','brands_brandimagegallery','brands_brandsearchtag','configurations_searchtag','webhooks_remoteurlconfig',
 'webhooks_webhookconfig','webhooks_webhookmessage','configurations_upcomingoccasion','configurations_announcement',
 'configurations_themeconfig','configurations_whitelabelbrandconfigs','brands_brandoffer','brands_brandcommission',
 'brands_brandhandlingfee','core_currencyexchangerate','core_unsupportedcountry','brands_brand','core_siteconfiguration',
 'brands_plusoffer','brands_brandcommissiondetail','brands_brandoffer_happy_cards') order by 1;
```
Key results (seq_scan / seq_tup_read / idx_scan / idx_tup_fetch): lastviewedbrand 4,637 / 276,237,053 / 3,251 / 39,460,106; users_cognitouser 24 / 7,777,468 / 62,779 / 1,607,863; aigreetingsparameters 55,172 / 1,599,988 / 0; aigreetingsconfiguration 1,470; aigreetingmessages 624 / 293,468 / 1,878 / 6,254; captchaconfigurations 2,546,397; sitemeta 877,516 / 1,990,206,288 / 35 (est -1); widgetorder 655,039; homepageslider seq 6,836, idx 450,169 (est -1); brandpagepromotionbanner 423,007; branddenomination idx 1,289,367; branddenominationrange idx 1,324,131; genericbrandslist idx 2,168,518 / fetch 154,475,359; brandimagegallery idx 560,045; brandsearchtag 6,274 / 108,370,520 / idx 846,367; searchtag 3,991; remoteurlconfig 15,735; webhookconfig 3,140; webhookmessage 0/0; upcomingoccasion 89,306 (0 rows); announcement 52,261 (0 rows); themeconfig 187,614; whitelabelbrandconfigs 27,882 (est -1); unsupportedcountry 3,185; siteconfiguration 9,954,411; plusoffer seq 9,206 / idx 3,899,736; brandoffer, brandoffer_happy_cards, brandcommission, brandcommissiondetail, brandhandlingfee, currencyexchangerate all 0 / 0. Derived ratios (per-scan tuples, % of siteconfiguration baseline) are simple divisions of these values. Counters are ~6K higher than in A6b because they were read later on a live replica.

**A11b. Per-index usage for aigreetingmessages / lastviewedbrand / cognitouser** (re-run; exact)
```sql
select s.relname, s.indexrelname, s.idx_scan, s.idx_tup_read, s.idx_tup_fetch
from pg_stat_all_indexes s where schemaname='public'
 and relname in ('core_aigreetingmessages','configurations_lastviewedbrand','users_cognitouser') order by 1, 3 desc;
```
Result: aigreeting relation_like 740 / 47,691; occasion_like 701 / 37,842; tone_like 434 / 71,952; pkey 3 / 300; note, note_like, and plain tone/relation/occasion btrees 0. lastviewedbrand store_id 3,251 / 41,945,899; brand_id, pkey 0. cognitouser (username,is_enabled) 62,772; pkey 7 / 1,972,534; others 0.

**A15. FKs referencing configurations_platformchoice**
```sql
select conrelid::regclass::text, pg_get_constraintdef(oid) from pg_constraint
where contype='f' and confrelid='configurations_platformchoice'::regclass;
```
Result: 3 FKs: configurations_downloadapprequest, configurations_emailsubscription, configurations_productfeedbackbox (all `platform_id`).

**A12b. Physical page counts**
```sql
select relname, relpages, pg_relation_size(oid)/1024 kb, pg_relation_size(oid)/8192 phys_pages from pg_class
where relname in ('configurations_lastviewedbrand_pkey','configurations_lastviewedbrand','webhooks_webhookmessage_pkey');
```
Result: lastviewedbrand_pkey relpages 338, 2,728 KB, 341 physical; lastviewedbrand heap 6,784 KB (848 pages); webhook pkey 13,264 KB, 1,658 physical.

**A13. Alternative consumer source: ygag_ecom_users_db** (catalog only)
```sql
select relname, reltuples::bigint from pg_class where relnamespace='public'::regnamespace and relkind in ('r','p') order by 2 desc limit 40;
select c.relname, a.attname, format_type(a.atttypid,a.atttypmod) from pg_attribute a join pg_class c on c.oid=a.attrelid
where c.relnamespace='public'::regnamespace and c.relkind='r' and a.attnum>0 and not a.attisdropped
  and a.attname ~* '^(sub|username|user_id|cognito.*|date_joined|last_login|platform|is_enabled|is_deleted)$';
```
Results (estimates): users_user 976,104 (has sub varchar(150), username varchar(36), last_login, date_joined, platform, is_enabled, is_deleted); notifications_twofactorauth 66,789; notifications_twofactorauthverification 67,684; users_cognitoissuedtokens 59,582; users_useridentityactivitylog 81,213.

## Appendix B: All 134 tables (reltuples estimate; -1 = never analyzed)
| # | Table | Est. rows |
|---|---|---|
| 1 | `auth_group` | 7 |
| 2 | `auth_group_permissions` | -1 |
| 3 | `auth_permission` | 328 |
| 4 | `brands_brand` | 3,243 |
| 5 | `brands_brand_categories` | 32,218 |
| 6 | `brands_brand_search_tags` | 52,715 |
| 7 | `brands_brandcategory` | 82 |
| 8 | `brands_brandcommission` | -1 |
| 9 | `brands_brandcommissiondetail` | -1 |
| 10 | `brands_branddenomination` | 23,283 |
| 11 | `brands_branddenominationrange` | 11,987 |
| 12 | `brands_brandgenericconfig` | 555 |
| 13 | `brands_brandhandlingfee` | 736 |
| 14 | `brands_brandimagegallery` | 9,648 |
| 15 | `brands_brandoccasion` | 21 |
| 16 | `brands_brandoccasion_brands` | 142 |
| 17 | `brands_brandoffer` | -1 |
| 18 | `brands_brandoffer_happy_cards` | -1 |
| 19 | `brands_brandsearchtag` | 16,864 |
| 20 | `brands_brandslug` | 1 |
| 21 | `brands_categorygender` | 0 |
| 22 | `brands_defaultstorebrandforoffer` | 7 |
| 23 | `brands_genericbrandslist` | 56,857 |
| 24 | `brands_hasofferbrands` | 1,018 |
| 25 | `brands_occasion` | 55 |
| 26 | `brands_offerpromocode` | 40 |
| 27 | `brands_plusoffer` | 378 |
| 28 | `brands_plusoffer_happy_cards` | 14,804 |
| 29 | `brands_productchannel` | 1 |
| 30 | `brands_storelocation` | 3,702 |
| 31 | `brands_tag` | 147 |
| 32 | `brands_tagbrand` | 32,851 |
| 33 | `company_company` | 812 |
| 34 | `configurations_announcement` | 0 |
| 35 | `configurations_announcement_country` | 0 |
| 36 | `configurations_announcement_platform_type` | 0 |
| 37 | `configurations_banner` | 82 |
| 38 | `configurations_banner_country` | 119 |
| 39 | `configurations_banner_platform_type` | 252 |
| 40 | `configurations_bannercategory` | 6 |
| 41 | `configurations_blog` | -1 |
| 42 | `configurations_brandpagepromotionbanner` | 26 |
| 43 | `configurations_brandskin` | 1,211 |
| 44 | `configurations_crosssellbrand` | 0 |
| 45 | `configurations_crosssellbrandconfig` | 0 |
| 46 | `configurations_customcategoryslider` | -1 |
| 47 | `configurations_downloadapp` | 1 |
| 48 | `configurations_downloadapprequest` | 0 |
| 49 | `configurations_downloadapptext` | 0 |
| 50 | `configurations_emailsubscription` | -1 |
| 51 | `configurations_footer` | 2 |
| 52 | `configurations_footer_country` | 2 |
| 53 | `configurations_footer_payment_partners` | 2 |
| 54 | `configurations_footer_platform_type` | 2 |
| 55 | `configurations_footerstore` | 14 |
| 56 | `configurations_happycardwidget` | -1 |
| 57 | `configurations_happycardwidget_platform_type` | 16 |
| 58 | `configurations_happycardwidget_redeemable_brands` | 0 |
| 59 | `configurations_header` | 2 |
| 60 | `configurations_header_platform_type` | 3 |
| 61 | `configurations_headertype` | 2 |
| 62 | `configurations_homepageslider` | -1 |
| 63 | `configurations_homepageslider_platform_type` | 141 |
| 64 | `configurations_howtouse` | 1 |
| 65 | `configurations_howtousebanner` | 4 |
| 66 | `configurations_lastviewedbrand` | 59,921 |
| 67 | `configurations_menuitem` | 64 |
| 68 | `configurations_paymentpartner` | 6 |
| 69 | `configurations_pdfsamples` | 2 |
| 70 | `configurations_pdfworkinfo` | 1 |
| 71 | `configurations_platformchoice` | 4 |
| 72 | `configurations_pressroom` | 0 |
| 73 | `configurations_productfeedbackbox` | 106 |
| 74 | `configurations_searchtag` | 39 |
| 75 | `configurations_sliderbrand` | 292 |
| 76 | `configurations_testimonial` | 1 |
| 77 | `configurations_testimonialapps` | 3 |
| 78 | `configurations_testimonialorder` | 0 |
| 79 | `configurations_testimonialreview` | -1 |
| 80 | `configurations_testimonialvideo` | 1 |
| 81 | `configurations_testimonialvideo_country` | 14 |
| 82 | `configurations_themeconfig` | 1 |
| 83 | `configurations_themeconfig_country` | -1 |
| 84 | `configurations_upcomingoccasion` | 0 |
| 85 | `configurations_upcomingoccasion_country` | 0 |
| 86 | `configurations_whitelabelbrandconfigs` | -1 |
| 87 | `configurations_widgetorder` | 4 |
| 88 | `core_aigreetingmessages` | 538 |
| 89 | `core_aigreetingsconfiguration` | 1 |
| 90 | `core_aigreetingsconfiguration_enabled_countries` | 7 |
| 91 | `core_aigreetingsconfiguration_enabled_languages` | 1 |
| 92 | `core_aigreetingsparameters` | 29 |
| 93 | `core_basecurrency` | 19 |
| 94 | `core_captchaconfigurations` | 3 |
| 95 | `core_country` | 22 |
| 96 | `core_country_languages` | 24 |
| 97 | `core_currency` | 23 |
| 98 | `core_currencyexchangerate` | 437 |
| 99 | `core_language` | 2 |
| 100 | `core_siteconfiguration` | 1 |
| 101 | `core_siteconfiguration_platform_type` | 1 |
| 102 | `core_sitemeta` | -1 |
| 103 | `core_unsupportedcountry` | -1 |
| 104 | `dashboard_userdashboardmodule` | -1 |
| 105 | `django_admin_log` | 13,528 |
| 106 | `django_content_type` | 104 |
| 107 | `django_migrations` | -1 |
| 108 | `django_session` | 1,287,606 |
| 109 | `django_site` | 1 |
| 110 | `jet_bookmark` | 0 |
| 111 | `jet_pinnedapplication` | 0 |
| 112 | `kafka_giftkafkadatalog` | 0 |
| 113 | `kafka_webstoreskafkadatalog` | 0 |
| 114 | `locations_city` | 386 |
| 115 | `locations_community` | 1,115 |
| 116 | `locations_state` | 171 |
| 117 | `locations_store` | 22 |
| 118 | `locations_store_languages` | 23 |
| 119 | `notifications_emailtemplateconfiguration` | 6 |
| 120 | `notifications_twofactorauth` | 10 |
| 121 | `notifications_twofactorauthverification` | 10 |
| 122 | `otp_static_staticdevice` | 1 |
| 123 | `otp_static_statictoken` | 10 |
| 124 | `otp_totp_totpdevice` | 15 |
| 125 | `two_factor_phonedevice` | 0 |
| 126 | `users_cognitouser` | 980,177 |
| 127 | `users_customuser` | 18 |
| 128 | `users_customuser_groups` | 19 |
| 129 | `users_customuser_user_permissions` | 18 |
| 130 | `users_passwordhistory` | -1 |
| 131 | `users_usermetadata` | 11 |
| 132 | `webhooks_remoteurlconfig` | 8 |
| 133 | `webhooks_webhookconfig` | 1 |
| 134 | `webhooks_webhookmessage` | 0 |

Source: A1 (the same query, re-run 2026-09-29).
