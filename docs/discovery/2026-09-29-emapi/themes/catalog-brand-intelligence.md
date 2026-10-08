# Theme: Catalog, brand & merchandising intelligence

Written 2026-09-29 by the analytics strategist for ygg-atlas. Inputs: the seven critiqued profiles (`cross-db.md`, `users.md`, `emapi-stores.md`, `ecomweb-stores.md`, `orders-customer-catalog.md`, read in full; `orders-funnel.md`, `orders-integrations.md`, skimmed for catalog content), plus new queries N1–N12 (appendix). All queries went through `atlasq.sh` (read-only transaction on the Aurora read replica, PII-redacted).

**Evidence labels.** **VALIDATED** = a data query ran (only possible in `ygag_ecom_users_db`). **STRUCTURAL** = schema, constraints, `reltuples` estimates, sizes or replica read counters. **NEEDS-GRANT** = needs rows from a table this role cannot read; the table and columns are named.

**Why this theme is mostly STRUCTURAL.** Every catalog, merchandising, browse and order table sits in `ygag_emapi_stores_db`, `ygag_ecomweb_stores_db` or `ygag_ecom_orders_db`. The role has SELECT on 0 tables in all three. The only readable DB (users) holds no brand data. The demand side that *can* be measured (markets, seasonality, language, birthdays) is VALIDATED below. The supply and merchandising side is STRUCTURAL, and turning it into metrics needs the grants in section 5.

---

## 0. Headline

Supply is well structured and the catalog is ready for governed metrics once granted. It has three copies: the emapi master (6,610 brand rows), the web storefront (3,243) and orders (3,442). Brands have one store each, with denominations, ranges, tags, search keywords, occasions, multi-brand "generic" cards, shop-category layouts and ranked offer placements. The replica's read counters show that **web discovery is led by tags and categories, not search**: 28.1M tag landing lookups against 1.47M brand-page slug lookups and about 36k search-keyword lookups over 35.5 days (STRUCTURAL). Two demand facts are VALIDATED and should shape merchandising now. First, **39.1% of Saudi OTP recipients use Arabic, against 0.4% in the UAE**. Second, **gift-claim volume peaks in December and March** (5,042 in Dec 2024; 3,621 in Mar 2025; 2,624 in Mar 2026). The biggest merchandising question is whether tag and shop-category position, offer placement and Arabic content actually move sales. It cannot be answered until order lines can be joined to brands (grant G-C1/G-O1) and a brand crosswalk (orders `upc` to stores `code`) is verified.

---

## 1. Insights

### 1.1 Supply structure (catalog)

**I1. Three catalog copies of different sizes. emapi is the master, and a brand row belongs to exactly one store.** [STRUCTURAL]
- emapi `brands_brand` 6,610 est; ecomweb `brands_brand` 3,243 est; orders `catalogue_product` 3,442 est (PK index 3,168). All three have 22 stores (`locations_store` / `catalogue_store`) [profiles; X4/X8 in cross-db].
- In every DB, the only brand-to-country link is `brands_brand.store_id` (a single, nullable FK), or `catalogue_product.store_id` in orders. A catalog-wide search for tables that carry both a brand and a store/country key finds only offers, promo banners, tip configs and `configurations_lastviewedbrand` (N9). No brand↔country M2M exists.
- **Implication:** the same retail brand sold in AE and SA is **two brand rows**. "Brand availability by country" means grouping rows by a cross-store identity, and none is declared. Candidates are `reference_name`, `gencode` and `company_id`/`retailer`. Counting rows gives listings, not brands. Averages: about 300 listings per store in emapi (6,610 / 22) and about 147 in ecomweb (3,243 / 22) [STRUCTURAL arithmetic on estimates].

**I2. Price-point structure: about 6.5–7 fixed denominations and about 3.5 open ranges per listing.** [STRUCTURAL]
- emapi: 44,317 denominations and 24,273 ranges over 6,610 brands, i.e. 6.7 and 3.7 per brand. ecomweb: 23,283 / 11,987 over 3,243 (7.2 / 3.7). orders: 22,404 / 11,376 over 3,442 (6.5 / 3.3).
- Orders `catalogue_productdenomination.is_default` marks the pre-selected value per product and currency [orders-funnel P36].
- The chosen gift value is stored per basket line in `basket_basketquantitydetail.denomination` numeric(20,6), 1.78M est rows (N11). So the **default-anchoring effect** and "custom amount versus preset" behaviour can be measured once granted [NEEDS-GRANT].

**I3. Taxonomy is broad and weakly discriminating.** [STRUCTURAL]
- Category links per brand: ecomweb 32,218 / 3,243 ≈ **9.9**, orders 31,311 / 3,442 ≈ 9.1, emapi 37,811 / 6,610 ≈ 5.7.
- Tags: 147 in both stores DBs, with 32,851 (ecomweb) and 41,405 (emapi) tag-brand links, about **223–282 brands per tag**.
- Shop categories (app): 16 `configurations_shopcategory` rows carry 6,186 brand links, **about 387 brands per shop category**. The older `myshopcategory` has 9 rows and 2,436 links.
- Search keywords: 52,715 brand-keyword links in ecomweb (≈16 per brand) and 63,720 in emapi (≈9.6).
- **Implication:** a category or tag is closer to a curated shelf than a classifier. Brand-level affinity has to come from co-purchase and co-view, not from shared categories.

**I4. Multi-brand "generic" (Happy Card style) cards are a very large hidden catalog.** [STRUCTURAL]
- emapi `brands_generic_brand_item` 533,305 est rows over 3,381 configs, about 158 rows per config. ecomweb `brands_genericbrandslist` 56,857 over 555 configs, about 102.
- The emapi table has no UNIQUE(config, brand), both keys are nullable, and its pkey is about 2x the expected size, which fits `auto_brand_sync` rebuilds.
- ecomweb reads these lists heavily: 2.17M index scans on `brands_genericbrandslist`, and 228.6M tuples read through `generic_config_id`, ≈315 per scan (N8, N10).
- **Implication:** "breadth of choice" inside a generic card is a merchandising lever. Duplicates would inflate any rows-based count.

**I5. Channel exposure is flag-driven and differs by DB.** [STRUCTURAL]
- emapi `brands_brand` has 12 `visible_to_*` flags (ecommerce, ecommerce_app, android, ios, at_work, corporate, corporate_api, specific_corporate, credit, gift_shop, mpos, sendatip).
- ecomweb has 6, and names them differently (`visible_to_android_app` / `visible_to_ios_app` against emapi `visible_to_android` / `visible_to_ios`) (N9).
- In ecomweb, `visible_to_ecommerce`, `is_launched`, `visible_to_*_app` and `visible_to_at_work` are **nullable**. In emapi most are NOT NULL (N9).
- **Implication:** "is this brand live on the iOS app in SA" is a three-valued question on web data. Treat NULL explicitly, and never coalesce it silently to false or true.

### 1.2 Discovery and browsing (web storefront, replica read counters)

All of 1.2 is STRUCTURAL. The counters are **cumulative over the replica's 35.54-day uptime** (N12; `stats_reset` is null, so they count from postmaster start). They include **reader traffic only**, not the writer's. They show relative intensity, not users or sessions.

**I6. Web discovery is led by tags and categories. Search is a minor path.** (N8, N10)

| Path (ecomweb) | Counter | 35.5 days | ≈ per day |
|---|---|---|---|
| Tag landing / menu, by SEO name | `brands_tag_seo_name_like` idx_scan | 28,119,010 | ≈791k |
| Tag↔brand listing, by brand | `brands_tagbrand_brand_id` idx_scan | 51,487,700 | ≈1.45M |
| Tag↔brand listing, full-table scans | `brands_tagbrand` seq_scan / seq_tup_read | 2,381,186 / 77.8B tuples | — |
| Brand page by slug | `brands_brand_slug_like` idx_scan | 1,465,334 | ≈41k |
| Brand by code | `brands_brand_code_like` idx_scan | 2,040,678 | ≈57k |
| Category lookup | `brands_brandcategory_pkey` idx_scan | 802,978 | ≈23k |
| Search keyword lookup by name | `brands_brandsearchtag_name_like` idx_scan | 36,012 | ≈1.0k |
| Search suggestions list | `configurations_searchtag` seq_scan | 4,020 | ≈113 |
| Occasions | `brands_occasion` idx 8,542; `brands_brandoccasion_brands` seq 104,137 | — | — |
| Home slider brands | `configurations_sliderbrand_brand_id` idx_scan | 13,761 | ≈387 |

- Tag and category lookups outnumber keyword lookups by about 780x (28.1M vs 36k). Brand-slug lookups (a brand-page proxy) outnumber keyword lookups by about 40x.
- **Caveat:** menus and headers may resolve tags on every render, so tag counts overstate *intentional* tag browsing.
- **Implication:** tag and shop-category order is the main merchandising surface. `brands_tagbrand.order_number`, `configurations_shopcategorybrand.order_number`, `brands_brand.list_order_number` and `order_number` are the levers that matter [STRUCTURAL; effect NEEDS-GRANT].

**I7. The single hottest object is the brand row itself.** `brands_brand_pkey` has **8.52B index scans** (≈240M per day) on the reader, against 622 seq scans (N8, N10). Brand data is fetched by id on every listing tile, with no application cache [STRUCTURAL]. Operational note: any atlas brand query must never add load here. Read from a governed extract, not live.

**I8. "Recently viewed brands" is the only per-user browse signal, and it is a capped lower bound.** [STRUCTURAL]
- ecomweb `configurations_lastviewedbrand`: 59,921 est rows; columns `username` vc255 (nullable), `brand_id` (NOT NULL), `store_id` (nullable), `created_on`, `modified_on` (N9).
- No index on `username`, and no UNIQUE(username, brand_id).
- The PK density (about 176 entries per page against about 345 dense) suggests rows are deleted, which fits a per-user cap [ecomweb A12].
- Replica reads: 4,649 seq scans reading 277.0M tuples, i.e. a full scan per read (N10).
- **Implication:** it can seed "viewed but not bought" retargeting and brand-interest segments. It cannot measure view volume. `modified_on > created_on` may mark a re-view [NEEDS-GRANT].

**I9. App-side browse intent is favourites only.** [STRUCTURAL]
- emapi `brands_favouritebrand`: 19,821 est rows, UNIQUE(user_id, brand_id), timestamps and no audit actor. That is at most ~2% of 992k app users.
- The emapi replica is effectively idle for app traffic: 408 `xact_commit` over 35.5 days (N12). The app reads the writer, so **emapi replica counters cannot proxy app browsing** at all.

**I10. There is no supply-side "demand capture" beyond a tiny feedback box.** [STRUCTURAL]
- ecomweb `configurations_productfeedbackbox` ("suggest a brand") has 106 est rows. `configurations_crosssellbrand` is empty (0 pages), and `configurations_upcomingoccasion` is empty but polled 89,453 times (N10).
- Orders `analytics_recommendedbrand` (86 est rows: `region` vc4, `product` vc64 as **text**, `count`, `date_placed`) is a precomputed per-region bestseller list, scanned 6,037 times (N11).
- **Implication:** cross-sell and "upcoming occasion" surfaces exist in schema but are unpopulated. Atlas-computed affinity could fill them (a "wow" opportunity).

### 1.3 Demand side (VALIDATED, users DB)

**I11. Demand is concentrated in SA and AE, with a real cross-border tail and some suspicious residence clusters.** [VALIDATED, N1/N2]
- Live users by `country_of_residence`: SA 453,137, AE 404,404, QA 26,375, KW 14,094, IN 13,229, EG 10,062, GB 8,975, OM 7,006, BH 6,821, US 3,015.
- Joined in the last 12 months and still live: SA 138,572, AE 107,940, QA 7,962, **GB 3,471, IN 4,255, EG 2,463, US 1,132**. Non-GCC residents (diaspora and expats) are an active acquisition stream. What they buy (home-country brands or GCC brands for recipients in the GCC) is a supply question [NEEDS-GRANT, H12].
- **Anomalies (a risk for any market dimension):**
  - **AM (Armenia) 2,439 signups in 2024 on just 13 days, max 298 in one day, 0 joined in the last 12 months.**
  - **CH 2,890 in 2025 over 88 days, max 193 a day, 71 in the last 12 months.**
  - MX 818 in 2024 over 22 days (max 100 a day).
  - These are bulk or farmed cohorts, not markets. Exclude or flag them before any "demand by country versus supply" comparison.

**I12. Language demand splits sharply by market: Saudi recipients are 39% Arabic, UAE recipients under 1%.** [VALIDATED, N4; 31-day OTP window]
- OTP `language` by recipient phone prefix: SA 6,036 of 15,432 Arabic (**39.1%**); AE 35 of 9,279 (**0.4%**); KW 10.0%; QA 4.1%; email-only recipients 21.3%.
- **Implication:** Arabic brand content (`name_ar`, `receiver_redemption_details_ar`, `short_redemption_details_ar`, `title_ar` on shop categories, tag `seo_name`) is a conversion factor mainly in the **SA store**. A brand missing Arabic recipient instructions hurts Saudi gifting far more than Emirati gifting [hypothesis H2; content coverage NEEDS-GRANT].

**I13. Gifting has a strong seasonal shape: December and March (Ramadan/Eid) peaks, July–August troughs.** [VALIDATED, N3]
- Gift claims (`secondary_email_added_via_gift`, one per recipient claim into an account):
  - 2024: Dec **5,042**, Nov 2,869
  - 2025: Mar **3,621**, Dec 2,757; troughs Jul 1,839 and Aug 1,536
  - 2026: Mar 2,624, then 1,618–2,366 per month
- The Dec 2024 spike is 1.8x Dec 2025. Year on year, claims fell (Aug–Sep 2026 is about 1.75–1.84k a month against 1.9k in Aug–Sep 2024).
- **Caveat:** this is claims into a *registered* account by a *new* alternate email, so it is a proxy for gift receipt, not for sales.
- **Implication:** occasion tags, slider brands and denominations should be re-ranked 2–3 weeks before the Dec and Ramadan peaks. An atlas "occasion calendar" metric can be built now [VALIDATED data].

**I14. Birthdays: a year-round, addressable self-gifting and occasion segment of about 27–33k live users per month.** [VALIDATED, N5]
- Live users with a valid `0000/DD/MM` birthday, excluding the `0000/01/01` default: Jan 26,964; Feb 26,790; Mar 29,384; Apr 28,401; **May 32,959**; Jun 28,465; Jul 28,594; Aug 29,588; Sep 28,801; **Oct 31,790** (SA 14,021 / AE 13,197); Nov 29,558; Dec 30,021.
- **Implication:** combine this with `brands_brand.buy_for_yourself` (a self-purchase-enabled brand flag) to merchandise "treat yourself" brands in the birthday month [catalog side NEEDS-GRANT].

### 1.4 Offers as merchandising

**I15. Offers are resolved per brand on every web page render. Offer placement is a ranked merchandising surface.** [STRUCTURAL]
- ecomweb `brands_plusoffer.brand_id` index: 1.74M scans. `brands_hasofferbrands` has 2.09M index scans (N10), so the "brand has offer" badge is checked on listings.
- Orders `offer_plusoffer_happy_cards` has 3.28M index scans (N11).
- Placement columns are `featured_order`, `brand_tile_order_number` and `offer_order_number`, all NOT NULL.
- The eligibility gate is `catalogue_product.is_discountable` [orders-customer-catalog].
- emapi `brands_hasofferbrands` has no UNIQUE and churns by about 20% between analyses [emapi Q31], so badge counts from it can double-count.

**I16. Order lines carry their own brand key, and the product FK is optional.** [STRUCTURAL, N11]
- `order_line.upc` varchar(128) is **NOT NULL**, while `order_line.product_id` is **nullable**. `basket_line.product_id` is NOT NULL.
- UPC is also the dominant catalog lookup on orders (`upc_like` 13.45M of 29.07M `catalogue_product` index scans) [orders-customer-catalog Q33].
- **Implication:** brand-level sales must key on `order_line.upc`, then join to `catalogue_product.upc`, then (after V3) to the stores' `brands_brand.code`. Keying on `product_id` risks silently dropping lines.
- `basket_line.purchase_origin` and `order_line.purchase_origin` (varchar(20), N11) are the most promising **surface-attribution** columns in scope: which surface (slider, search, offer page, and so on) a line came from [semantics NEEDS-GRANT].

---

## 2. Hypotheses (testable, for marketers, growth, product and ops)

| id | Statement | Audience | Test | Data needed | Evidence |
|---|---|---|---|---|---|
| H1 | Brands in the top 12 positions of a tag landing page (`brands_tagbrand.order_number`) earn ≥2x the order lines per listing-day of the same brands at positions 25+, controlling for brand fixed effects | Merchandising, growth | Panel regression of daily order lines per brand on tag position, with brand and store fixed effects. Then a randomized re-rank of 20 mid-tier brands in 3 tags for 4 weeks (A/B by store) | ecomweb `brands_tagbrand(brand_id, tag_id, order_number, is_active, modified_on)`, `django_admin_log` (history of reorders); orders `order_line(upc, created_on, quantity)` + `order_orderlinequantitydetail` amounts; brand crosswalk V3 | NEEDS-GRANT |
| H2 | In the SA store, active brands with no Arabic recipient redemption instructions convert ≥20% worse (views to orders) than comparable brands with Arabic text; the gap is under 5% in AE | Product, content | Compare conversion by `receiver_redemption_details_ar` present or absent, cut by store; then backfill Arabic on 30 brands and diff-in-diff against untouched controls | emapi or ecomweb `brands_brand(receiver_redemption_details_ar IS NULL/blank flag, store_id, is_active, is_launched)`; ecomweb `configurations_lastviewedbrand`; orders `order_line`. The demand side (SA 39.1% Arabic) is VALIDATED | NEEDS-GRANT (the demand premise is VALIDATED) |
| H3 | Users who viewed a brand 2 or more times (`lastviewedbrand.modified_on > created_on`, or duplicate rows) without buying within 7 days buy that brand within 30 days at ≥3x the base rate when shown a same-brand offer or reminder | Growth / CRM | Build the "viewed-not-bought" segment; holdout test (50/50) of a reminder push or email | ecomweb `configurations_lastviewedbrand(md5(username), brand_id, store_id, created_on, modified_on)`; identity chain `cognitouser.username` → orders `userprofile.cognito_id` (G1/G3); orders `order_line` + `order_order.user_id` | NEEDS-GRANT |
| H4 | App users who favourited a brand buy it within 14 days of that brand entering an active Plus Offer at ≥4x the rate of favouriters with no offer | Growth, offers | Event study around `brands_plusoffer.start_date` for brands in `plusoffer_happy_cards`, split by favouriter vs non-favouriter | emapi `brands_favouritebrand(user_id, brand_id, created_on)`, `brands_plusoffer(start_date, end_date, is_active)`, `brands_plusoffer_happy_cards`; users `username` crosswalk (G4); orders `order_line.offer_code, upc` | NEEDS-GRANT |
| H5 | For brands with a pre-selected default denomination, ≥50% of basket lines use exactly the default. Raising the default one step raises average line value by ≥10% with under 3% conversion loss | Merchandising, revenue | Measure the share at the default; then A/B the default on 10 brands by store | orders `catalogue_productdenomination(product_id, amount, is_default, currency_id)`, `basket_basketquantitydetail(denomination, denomination_currency_id, line_id)`, `basket_line(product_id)`, `order_line` | NEEDS-GRANT |
| H6 | Birthday-month users (27–33k live per month, VALIDATED) shown `buy_for_yourself` brands in their birthday week self-purchase at ≥2x their non-birthday-month rate | CRM | Holdout experiment on the October cohort (31,790 live users; SA 14,021, AE 13,197) | users `birthdate` (ready); emapi `brands_brand.buy_for_yourself`; orders `basket_basketquantitydetail.is_buy_for_self` + `order_order.user_id` (G1/G9) | STRUCTURAL (segment VALIDATED; outcome NEEDS-GRANT) |
| H7 | At least 5% of active search keywords in a store map to 0 active, launched brands in that store (dead-end searches). These keywords overlap with `productfeedbackbox` suggestions | Merchandising, supply / BD | Anti-join keyword → brand → store; rank by keyword read frequency; compare with feedback-box brand names | ecomweb `brands_brandsearchtag(id, name, is_active)`, `brands_brand_search_tags`, `brands_brand(store_id, is_active, is_launched, is_obsolete)`, `configurations_productfeedbackbox(brand_name, platform_id, created_on)` (email excluded) | NEEDS-GRANT |
| H8 | Generic (multi-brand) cards with ≥100 active redeemable brands sell ≥30% more per listing than those with under 30, within the same classification | Merchandising, product | Cross-sectional comparison of distinct active redeemable brands (dedupe on (config, brand)) against orders per generic listing | emapi `brands_generic_brand_item(generic_config_id, brand_id, is_active)`, `brands_generic_brand_config(brand_id, generic_type)`; orders `order_line.upc` | NEEDS-GRANT |
| H9 | Order lines whose `purchase_origin` is an offer or slider surface have higher average line value but lower repeat purchase than lines from tag or category browsing | Growth, product | Breakdown of lines, AOV and 60-day repeat by `purchase_origin` | orders `order_line(purchase_origin, upc, created_on)`, `order_orderlinequantitydetail` reporting-currency amounts, `order_order.user_id` | NEEDS-GRANT |
| H10 | A brand's first Plus Offer week lifts that brand's order lines by ≥25% against matched non-offer brands, with no net loss to the brand's category | Offers, finance | Diff-in-diff on brand-days; check cannibalization inside the tag or category | orders `offer_plusoffer(start_date, end_date, brand_id, funded_by)`, `offer_plusoffer_happy_cards`, `order_line(upc, is_offer_applied, offer_code)`, `catalogue_product.is_discountable` | NEEDS-GRANT |
| H11 | Re-ranking occasion tags and denominations 3 weeks before Ramadan and December (the VALIDATED claim peaks) captures more of the peak than re-ranking 1 week before | Merchandising | Staggered-timing test by store (SA re-ranks early, AE late, then swap next season); outcome is peak-window order lines and gift claims | users `users_useridentityactivitylog` (ready); ecomweb `brands_tagbrand`, `brands_occasion`, `django_admin_log`; orders `order_orderlinepersonalisedetail.occasion_code`, `order_line` | STRUCTURAL (seasonality VALIDATED) |
| H12 | Non-GCC residents (IN, EG, GB, US; 11.3k live signups in the last 12 months, VALIDATED) buy into AE and SA stores at a higher average value and a different brand mix (grocery and retail rather than entertainment) than GCC residents | Growth (diaspora campaigns) | Brand-mix and AOV breakdown by buyer residence × `order_order.region_id` | users `country_of_residence` (ready); orders `order_order(user_id, region_id)`, `users_userprofile(cognito_id)` hashed (G1), `order_line.upc` | NEEDS-GRANT |
| H13 | Listings that are active but not launched, obsolete but still visible, or visible with 0 active denominations and 0 ranges generate zero-conversion brand-page views (dead ends). There are ≥50 such listings across stores | Ops, merchandising | Catalog-health snapshot joined with `lastviewedbrand` and `order_line` | ecomweb/emapi `brands_brand` flags, `brands_branddenomination(is_active)`, `…range(is_active)`; `configurations_lastviewedbrand` | NEEDS-GRANT |
| H14 | Buyers of brand A in category X buy a second, specific brand B at ≥5x the base rate within 90 days (strong pairwise affinity exists and is stable across quarters), so it can populate the empty `configurations_crosssellbrand` | Product (recommendations) | Lift and Jaccard co-purchase matrix on hashed user × brand; test stability quarter over quarter; then A/B a cross-sell rail | orders `order_line(upc)` + `order_order(user_id or guest_id, date_placed)` as a hashed extract | NEEDS-GRANT |

---

## 3. Atlas features

Plugin names used below: **`catalog`** (emapi master + ecomweb storefront catalog/merch), **`orders`** (ygag_ecom_orders_db), **`users`** (ygag_ecom_users_db, live today).

| id | Name | Type | What it does | Backing plugin / tables | Readiness | Effort | Impact |
|---|---|---|---|---|---|---|---|
| F1 | Gifting seasonality calendar | metric (range) + dashboard | Monthly and weekly gift claims (`secondary_email_added_via_gift`) and self-added alternate emails, with YoY and peak flags for Ramadan and December; the "when to merchandise" clock | users: `users_useridentityactivitylog` | ready-now | S | 4 |
| F2 | Birthday-month segment | segment | Live users whose birthday falls in a window (excludes `0000/01/01`), by residence and app flag; exportable as hashed ids for CRM | users: `users_user(birthdate, is_deleted, country_of_residence, is_app_user)` | ready-now | S | 4 |
| F3 | Market demand vs language map | breakdown | Live users and 12-month signups by residence country, with farmed-cohort flags (AM/CH/MX pattern) and Arabic-share per market from OTP language | users: `users_user`, `notifications_twofactorauth(language, phone prefix bucket)` | ready-now | S | 3 |
| F4 | Catalog health snapshot | metric (snapshot) + alert | Per store × channel: listings active / launched / visible / obsolete-but-visible, active-not-launched, with 0 active denominations and 0 ranges, missing EN/AR recipient instructions, no category, no search tag. Daily diff alert on regressions | catalog: emapi + ecomweb `brands_brand`, `brands_brand_denomination(_range)`/`brands_branddenomination(range)`, `brands_brand_categories`, `brands_brand_search_tags` | needs-grant | S | 5 |
| F5 | Brand availability matrix | dashboard | Brand identity (reference_name/gencode/company) × 22 stores × 12 channel flags; shows "sold in AE but not SA" gaps and NULL-visibility listings | catalog: `brands_brand(code, reference_name, gencode, company_id, store_id, visible_to_*)`, `locations_store`, `brands_retailers`/`company_company` | needs-grant | M | 4 |
| F6 | Brand performance with top-N | metric (range, top-N breakdown) | Order lines, units and GMV (reporting currency) per brand per store, with offer-applied share; brand keyed by `order_line.upc` with crosswalk provenance | orders: `order_line(upc, product_id, quantity, is_offer_applied, offer_code, purchase_origin, created_on)`, `order_orderlinequantitydetail` reporting-currency amounts, `catalogue_product`, `catalogue_store` | needs-grant | M | 5 |
| F7 | Supply–demand gap finder | agentic_analysis | Multi-step sandbox run: demand signals (search keyword read frequency, lastviewed brands, feedback-box suggestions, residence markets, VALIDATED seasonality) vs supply (active listings per store/category/price band); outputs a ranked list of "missing brand / missing denomination / missing store" with evidence and sizing | catalog + orders + users | needs-grant | L | 5 |
| F8 | Brand affinity and cross-sell recommender | agentic_analysis | Lift and Jaccard co-purchase and co-view matrix over a hashed user × brand extract; stable pairs published as a governed "affinity" dimension to fill `crosssellbrand` or email rails, with per-pair support counts as provenance | orders `order_line`, `order_order(user_id)`; catalog `lastviewedbrand`, `favouritebrand` | needs-grant | L | 5 |
| F9 | Merchandising placement effectiveness | breakdown | Sales per listing-day by tag position, shop-category position, slider presence and offer `featured_order`/`brand_tile_order_number`; controls for brand | catalog `brands_tagbrand`, `configurations_shopcategorybrand`, `configurations_sliderbrand`→`brands_tagbrand`, `brands_plusoffer` placement cols; orders `order_line` | needs-grant | M | 5 |
| F10 | "What changed?" merchandising log + alert | alert_trigger | When a brand's daily sales move by more than k sigma, surface the admin changes to that brand, its tags, categories, denominations and offers in the prior 7 days (who / what model / when; no change text) | catalog `django_admin_log(action_time, action_flag, content_type_id, object_id)` + `django_content_type`; orders `order_line`; emapi `django_admin_log` (42,347 est) | needs-grant | M | 4 |
| F11 | Browse-to-buy funnel per brand | funnel | lastviewed / favourite → basket line → order line → gift claim, per brand and store; guest vs registered | catalog `lastviewedbrand`, `favouritebrand`; orders `basket_line`, `order_line`, `order_order`; users `useridentityactivitylog` | needs-grant | L | 4 |
| F12 | Viewed-not-bought segment | segment | Users who viewed brand X (≥2 views or recent) and did not buy X within N days, with store and language; feeds CRM | catalog `configurations_lastviewedbrand` (hashed username); orders `order_line`, `order_order`; identity crosswalk | needs-grant | M | 5 |
| F13 | Denomination mix and default anchoring | breakdown | Per brand: share of lines at the default, at other presets and at custom (range) amounts; median chosen value vs default; out-of-range attempts | orders `catalogue_productdenomination(is_default)`, `…range`, `basket_basketquantitydetail.denomination`, `basket_line.product_id` | needs-grant | M | 4 |
| F14 | Arabic content gap alert | alert_trigger | Fires when an active SA listing (or any listing whose store's Arabic share is over 20%, per F3) lacks Arabic name, recipient instructions or short instructions; ranked by the brand's SA sales | catalog `brands_brand(*_ar null/blank flags, store_id)`; users OTP language share (ready); orders `order_line` | needs-grant | S | 4 |
| F15 | Offer coverage and badge integrity | metric (snapshot) | Brands with an active in-window offer per store; eligible (`is_discountable`) vs ineligible; `hasofferbrands` duplicate count and drift vs `plusoffer_happy_cards` | catalog + orders `offer_plusoffer`, `*_happy_cards`, `brands_hasofferbrands`, `catalogue_product.is_discountable` | needs-grant | S | 3 |
| F16 | Generic-card breadth | metric (snapshot) | Distinct active redeemable brands per generic config (deduped), trend of `auto_brand_sync` churn | catalog emapi `brands_generic_brand_item`, `brands_generic_brand_config`; ecomweb `brands_genericbrandslist` | needs-grant | S | 3 |
| F17 | Brand record drill-down | record_drilldown | One brand: listings per store, channel flags, denominations, tags and positions, offers, favourites count, lastviewed count, 90-day sales, recent admin changes | all three plugins | needs-grant | M | 4 |
| F18 | Brand crosswalk entity (prerequisite) | metric (snapshot) | Governed `brand_key` mapping orders `catalogue_product.upc` ↔ stores `brands_brand.code`, with a match-rate metric and unmatched list; every brand metric carries its crosswalk version in provenance | orders `catalogue_product(id, upc, reference_name)`; emapi/ecomweb `brands_brand(id, code, reference_name, gencode)` | needs-grant | M | 5 |
| F19 | Surface attribution by `purchase_origin` | breakdown | Lines, AOV and repeat by origin surface; the first per-surface attribution in scope | orders `basket_line.purchase_origin`, `order_line.purchase_origin` | needs-grant | S | 4 |
| F20 | Merchandising calendar playbook | dashboard | F1 seasonality + F2 birthdays + occasion codes (`order_orderlinepersonalisedetail.occasion_code`) + current tag/slider layout, telling the merchandiser what to re-rank this week | users (ready) + catalog + orders | needs-grant (partially ready) | M | 4 |

---

## 4. Plugin notes

### 4.1 `catalog` plugin (new)
One plugin with two connectors: `emapi` (master, all channels, app merchandising) and `ecomweb` (web storefront merchandising and browse). Both are read-only and use per-table allowlists.

**Entities**
- `brand` (canonical, keyed by the F18 `brand_key`)
- `brand_listing` (one row per `brands_brand` row, i.e. per store)
- `store` (22; `code`, ISO-2 country, currency)
- `denomination` and `denomination_range`
- `category`
- `tag` (hierarchical, with `seo_name`)
- `search_keyword`
- `occasion`
- `generic_card` and its items
- `shop_category` (app; flags `is_interest`, `is_slider`, `is_horizontal_scroll`, rows × cols)
- `merch_slot` (tagbrand / shopcategorybrand / sliderbrand / homepageslider positions)
- `offer` (plus offer, keyed by `code`)
- `brand_interest_event` (lastviewed, favourite)
- `admin_change` (django_admin_log without text)

**Allowlist, emapi.** `brands_brand` (all columns except free-text redemption bodies, which are exposed only as null/blank flags), `brands_brand_denomination`, `brands_brand_denomination_range`, `brands_category`, `brands_brand_categories`, `brands_tag`, `brands_tag_brand`, `brands_brand_search_tag`, `brands_brand_search_tags`, `brands_occasion`, `brands_retailers`, `brands_generic_brand_config`, `brands_generic_brand_item`, `brands_plusoffer`, `brands_plusoffer_happy_cards`, `brands_hasofferbrands`, `configurations_*` (sliders, carousel, banners, shopcategory(+brand), myshopcategory(+brand), platform, color), `locations_store`, `core_country`, `core_currency`, `brands_favouritebrand` (via a view), `django_content_type`, `atlas_django_admin_log` view.

**Allowlist, ecomweb.** Same catalog set with ecomweb names (`brands_branddenomination(range)`, `brands_brandcategory`, `brands_tagbrand`, `brands_brandsearchtag`, `brands_brandoccasion(_brands)`, `brands_brandgenericconfig`, `brands_genericbrandslist`, `brands_brandimagegallery` (count only), `configurations_sliderbrand`, `configurations_brandskin`, `configurations_searchtag`, `configurations_homepageslider(_platform_type)`, `configurations_customcategoryslider`, `configurations_brandpagepromotionbanner`, `company_company`), plus views over `configurations_lastviewedbrand` and `configurations_productfeedbackbox`.

**PII exclusions**
- `brands_storelocation.contact_number`, `contact_email`, `address*`
- `brands_offerpromocode.promo_code` (redeemable secret; use a `promo_code_md5` view)
- `configurations_lastviewedbrand.username` (hash only)
- `configurations_productfeedbackbox.email_address`, `user_reference` (hash only), `extra` (keys only)
- `configurations_emailsubscription.email_address`
- `notifications_emailtemplateconfiguration.to_emails`
- `remote_url_config_*` / `webhooks_remoteurlconfig` credentials
- all `users_*` tables in these DBs (identity belongs to the users plugin)

**Derived views (the DBA creates them in an `atlas_ro` schema)**
- `atlas_brand_listing`: id, code, slug, reference_name, gencode, company/retailer id, store_id, currency_id, primary_category_id, classification, redemption_type, generic_type, is_generic, is_active, is_launched, is_obsolete, buy_for_yourself, can_be_swapped, non_expirable, validity_months, validity_days, all `visible_to_*` (NULL kept), `order_number`, `list_order_number`/`ecom_order_number`, `has_receiver_instr_en`, `has_receiver_instr_ar`, `has_name_ar`, created_on, modified_on.
- `atlas_lastviewedbrand`: id, `md5(username)`, brand_id, store_id, created_on, modified_on.
- `atlas_favouritebrand`: id, user_id (joined to the users plugin only through `md5(emapi users_user.username)`, never raw), brand_id, created_on.
- `atlas_productfeedback`: id, `brand_name_normalized` (lower/trim, still free text: review before granting, or expose only a matched-to-brand flag), platform_id, created_on.
- `atlas_admin_change`: id, action_time, action_flag, content_type_id, object_id, user_id (staff id only).

**Metric definitions to ship first:** F4 catalog health (snapshot), F15 offer coverage (snapshot), F16 generic breadth (snapshot). All three are catalog-only and PII-free.

**Load rule.** The ecomweb reader serves 8.5B brand-pkey lookups per 35.5 days (I7). Atlas must read a **daily governed extract**: small tables in full, and `lastviewedbrand` in full since it is 60k rows. It must never run live, unindexed queries on the storefront's hot path.

### 4.2 `orders` plugin (catalog slice)
- **Entities:** `order_line` (brand-bearing fact), `basket_line`, `line_money` (`order_orderlinequantitydetail`, strictly 1:1 with `order_line`, so it can be modelled as an extension), `line_personalisation` (occasion, greeting, delivery type), `catalogue_product` (orders-local brand), `catalogue_store`, `catalogue_productdenomination(range)`, `offer_plusoffer`, `analytics_recommendedbrand`.
- **Brand key:** `order_line.upc` (NOT NULL) → `catalogue_product.upc` (UNIQUE) → F18 crosswalk. Never `order_line.product_id` alone (nullable).
- **Exclusions:** `order_line.partner_line_reference`, `partner_line_notes`; recipient phone and email on `*personalisedetail`; `basket_basketquantitydetail.sender_name`, `personal_data_ref`; all `order_order` PII columns as listed in orders-customer-catalog.

### 4.3 `users` plugin (demand slice, live today)
Add a registered dimension `market` (residence country with a `farmed_cohort` flag), a `birthday_month` derived field (parsed from `0000/DD/MM`, default excluded) and an `otp_language_share` metric by phone-prefix bucket. None of these exposes raw birthdate, phone or email.

---

## 5. Grants needed (catalog theme; references cross-db §8 where it overlaps)

| # | DB.table | Columns (as a view) | PII-safe note |
|---|---|---|---|
| G-C1 | emapi `brands_brand` | id, code, slug, reference_name, gencode, company_id, store_id, currency_id, primary_category_id, classification, redemption_type, generic_type, is_generic, is_active, is_launched, is_obsolete, buy_for_yourself, can_be_swapped, can_be_split, require_mobile_verification, has_code, has_pin, has_redeem_url, non_expirable, validity_months, validity_days, 12 `visible_to_*`, order_number, ecom_order_number, created_on, modified_on; derived `has_receiver_instr_en/_ar`, `has_short_instr_en/_ar`, `has_name_ar` | No PII. Free-text instruction bodies exposed only as null/blank flags |
| G-C2 | emapi `brands_brand_denomination`, `brands_brand_denomination_range`, `brands_category`, `brands_brand_categories`, `brands_tag`, `brands_tag_brand`, `brands_brand_search_tag`, `brands_brand_search_tags`, `brands_occasion`, `brands_generic_brand_config`, `brands_generic_brand_item`, `brands_retailers`, `locations_store`, `core_country`, `core_currency` | all columns | No PII |
| G-C3 | emapi `configurations_shopcategory`, `configurations_shopcategorybrand`, `configurations_myshopcategory(+brand, +platforms)`, `configurations_homepageslider(+item, +platform_type)`, `configurations_carouselitem`, `configurations_banneritem`, `configurations_platform` | all columns | No PII (banner `config` jsonb: keys only if in doubt) |
| G-C4 | emapi `brands_plusoffer`, `brands_plusoffer_happy_cards`, `brands_hasofferbrands` | all except trilingual T&C text | Promo codes via `atlas_offerpromocode` (`promo_code_md5`) only |
| G-C5 | emapi `brands_favouritebrand` | id, user_id, brand_id, created_on, modified_on | Joined to users only through `md5(users_user.username)` from G4 in cross-db §8 |
| G-C6 | emapi / ecomweb `django_admin_log` + `django_content_type` | id, action_time, action_flag, content_type_id, object_id, user_id | Exclude `object_repr`, `change_message` |
| G-W1 | ecomweb `brands_brand` | same as G-C1 (ecomweb column names), plus is_whitelabel, is_default_brand, is_preview_brand, date_disabled, list_order_number | No PII |
| G-W2 | ecomweb `brands_branddenomination(range)`, `brands_brandcategory`, `brands_brand_categories`, `brands_tag`, `brands_tagbrand`, `brands_brandsearchtag`, `brands_brand_search_tags`, `brands_occasion`, `brands_brandoccasion(_brands)`, `brands_brandgenericconfig`, `brands_genericbrandslist`, `company_company`, `locations_store`, `configurations_sliderbrand`, `configurations_homepageslider*`, `configurations_customcategoryslider`, `configurations_brandpagepromotionbanner`, `configurations_brandskin`, `configurations_searchtag` | all columns | No PII |
| G-W3 | ecomweb `configurations_lastviewedbrand` | id, `md5(username)`, brand_id, store_id, created_on, modified_on | Raw username never granted |
| G-W4 | ecomweb `configurations_productfeedbackbox` | id, platform_id, created_on, `brand_name` (lower/trim) **or** a `matched_brand_id` resolved by the DBA | Exclude `email_address`, raw `user_reference`, `extra` values |
| G-O1 | orders `order_line` | id, order_id, product_id, upc, partner_id, quantity, status, is_offer_applied, offer_code, purchase_origin, is_white_label, is_instant_activated, created_on | Exclude `partner_line_reference`, `partner_line_notes`, `partner_sku` if sensitive |
| G-O2 | orders `order_orderlinequantitydetail` | line_id, reporting-currency price/tax/fee columns, is_buy_for_self, delivery_method, brand_skin | Exclude `sender_name`, `personal_data_ref` |
| G-O3 | orders `basket_line` + `basket_basketquantitydetail` | basket_line: id, basket_id, product_id, quantity, purchase_origin, date_created; quantitydetail: line_id, denomination, denomination_currency_id, is_buy_for_self, delivery_method | Exclude `sender_name`, `personal_data_ref` |
| G-O4 | orders `order_orderlinepersonalisedetail` / `basket_basketpersonalisedetail` | line_id, occasion_code, greeting_code, delivery_type, is_reminder_added, delivery_date (day bucket) | Exclude recipient `phone_number`, `email_address` |
| G-O5 | orders `catalogue_product`, `catalogue_productdenomination(range)`, `catalogue_productcategory`, `catalogue_category`, `catalogue_store`, `offer_plusoffer(+happy_cards)`, `analytics_recommendedbrand` | all columns | No PII |
| G-O6 | orders `order_order` | id, user_id, guest_id, region_id, platform, status, date_placed | Identity via G1 hashed `cognito_id` only (cross-db §8) |

**Minimum viable grant for the theme:** G-C1, G-C2, G-W1, G-W2 (catalog health and availability, no PII); then G-O1, G-O5 and cross-db G1/G3/G4 (brand sales and identity); then G-W3 and G-C5 (browse intent).

---

## 6. Risks and data-quality traps

1. **"Brand" is three different things.** It is an emapi listing (6,610), an ecomweb listing (3,243) and an orders `catalogue_product` (3,442; PK index 3,168). Code widths differ (vc16 / vc20; orders has no `code`, only `upc` vc64). Until V3 (upc ↔ code) runs, every brand metric must stay local to one DB and say so in provenance.
2. **A listing is not a brand.** One row per store. Counting `brands_brand` rows overstates distinct brands by up to the number of stores a brand is sold in. Group on a verified identity (reference_name / gencode / company), not raw rows.
3. **`order_line.product_id` is nullable, `upc` is NOT NULL** (N11). Joining on product_id silently drops lines.
4. **NULL visibility flags on ecomweb** (`visible_to_ecommerce`, `is_launched`, app flags nullable, N9) versus NOT NULL on emapi. Coalescing NULL to false or true shifts availability counts.
5. **Missing uniqueness inflates counts:** `brands_hasofferbrands` (no UNIQUE, about 20% reltuples swing), `brands_generic_brand_item` (no UNIQUE, nullable keys, pkey about 2x), `configurations_lastviewedbrand` (no UNIQUE(username, brand)). Always dedupe on the natural pair.
6. **Two parallel taxonomies per concept:** `shopcategory` vs `myshopcategory` (app); `brands_tag` vs `brands_brandsearchtag` vs `configurations_searchtag`; `brands_plusoffer` vs `brands_offer`/`brandoffer` (the latter has 0 replica reads). Pick one per metric and name it.
7. **Naming trap:** ecomweb `configurations_sliderbrand.brand_id` references **`brands_tagbrand`**, not `brands_brand`.
8. **Replica read counters are not traffic.** They are reader-only and cumulative over 35.54 days. Menus may resolve tags per render. emapi's replica is idle (408 commits), so app behaviour is invisible there. Use them for relative intensity only, labelled STRUCTURAL.
9. **Browse data is capped and sparse.** `lastviewedbrand` (≈60k rows, probably per-user capped) and `favouritebrand` (≈20k) are lower bounds. Never report them as view or interest volume. Clickstream, impressions and search queries are not in Postgres at all (the Oscar `analytics_*` tables are empty).
10. **Demand-by-country traps:** farmed cohorts (AM 2,439 in 13 days of 2024; CH 2,890 in 2025; MX 818 in 2024, N2); the May 2025 id-sequence cutover distorts signup trends; `is_app_user` changed meaning in Aug 2024; `country_of_residence` includes `OT`.
11. **Gift-claim seasonality is a proxy.** It covers claims into registered accounts to a new alternate email only, not all gift receipts or sales. The 1.8x Dec 2024 vs Dec 2025 gap may reflect flow changes, not demand.
12. **Birthday field defaults:** `0000/01/01` (9,940) and an inflated day 1 are defaults. They are excluded in N5 and must stay excluded in F2.
13. **OTP language is a 31-day rolling window** (the table purges at about 31 days). F3 must snapshot daily to trend it.
14. **Stale `reltuples`:** several catalog tables are never analyzed (`brands_offer`, `brands_occasion`, `configurations_homepageslider`, `core_sitemeta`). Row counts in this file are estimates and must be replaced by exact counts once granted.
15. **Catalog churn from sync jobs** (`auto_brand_sync`, offer Kafka re-publishes of about 534 messages per offer) means point-in-time snapshots differ intraday. Snapshot metrics need an as-of timestamp, and history has to be kept by atlas: the source keeps only current state (no brand, price or position history except `django_admin_log`).
16. **`analytics_recommendedbrand.product` is a text key** (vc64), not an FK. Match on upc or title explicitly, and report the match rate.

---

## Appendix: SQL provenance (new queries for this theme, run 2026-09-29)

Figures quoted from profiles cite their own appendices (users S1/C1/C3; cross-db X4/X8/X25/X34; emapi Q14/Q15/Q28/Q31; ecomweb A1/A11/A12/A14; orders-customer-catalog Q33/Q40/Q46; orders-funnel P36).

**N1: residence country, live and recent** (users) [VALIDATED exact]
```sql
select country_of_residence c, count(*) n, count(*) filter (where not is_deleted) live,
 count(*) filter (where not is_deleted and date_joined >= '2025-09-29') live_joined_12m,
 count(*) filter (where not is_deleted and is_app_user) live_app
from users_user group by 1 order by 2 desc limit 25;
-- SA 463,805/453,137/138,572; AE 412,960/404,404/107,940; QA 27,083/26,375/7,962; KW 14,391/14,094/4,281; IN 13,848/13,229/4,255;
-- EG 10,300/10,062/2,463; GB 9,135/8,975/3,471; OM 7,131/7,006/2,287; BH 6,960/6,821/2,042; US 3,087/3,015/1,132; CH 3,021/3,017/71; AM 2,443/2,442/0; MX 843/842/0
```
**N2: anomalous residence cohorts** (users) [VALIDATED exact]
```sql
select country_of_residence c, to_char(date_trunc('year',date_joined),'YYYY') y, count(*) n,
 count(distinct to_char(date_joined,'YYYY MM DD')) days, max(cnt) max_day
from (select *, count(*) over (partition by country_of_residence, date_trunc('day',date_joined)) cnt
      from users_user where country_of_residence in ('CH','AM','MX','OT')) x group by 1,2 order by 1,2;
-- AM 2024: 2,439 over 13 days, max 298/day; CH 2025: 2,890 over 88 days, max 193/day; MX 2024: 818 over 22 days, max 100/day
```
**N3: monthly gift claims** (users) [VALIDATED exact]
```sql
select to_char(date_trunc('month',"timestamp"),'YYYY "m" MM') m,
 count(*) filter (where activity='secondary_email_added_via_gift') via_gift,
 count(distinct user_id) filter (where activity='secondary_email_added_via_gift') via_gift_users,
 count(*) filter (where activity='secondary_email_added') self_added
from users_useridentityactivitylog group by date_trunc('month',"timestamp") order by date_trunc('month',"timestamp");
-- 2024-12 5,042; 2025-03 3,621; 2025-12 2,757; 2026-03 2,624; troughs 2025-07 1,839, 2025-08 1,536; 2026-09 1,746 (to 29th)
```
**N4: OTP language by recipient market** (users; 31-day rolling window) [VALIDATED exact]
```sql
select case when phone_number like '+966%' then 'SA' when phone_number like '+971%' then 'AE' when phone_number like '+974%' then 'QA'
 when phone_number like '+965%' then 'KW' when phone_number like '+968%' then 'OM' when phone_number like '+973%' then 'BH'
 when phone_number is null or phone_number='' then 'email_only' else 'other' end mkt,
 count(*) n, count(*) filter (where language='ar') ar, round(100.0*count(*) filter (where language='ar')/count(*),1) ar_pct
from notifications_twofactorauth group by 1 order by 2 desc;
-- email_only 39,993/8,499/21.3; SA 15,432/6,036/39.1; AE 9,279/35/0.4; other 2,390/110/4.6; QA 613/25/4.1; KW 502/50/10.0; OM 294/7/2.4; BH 202/9/4.5
```
**N5: live users by birthday month, default excluded** (users) [VALIDATED exact]
```sql
with b as (select substr(birthdate,9,2)::int mo, substr(birthdate,6,2)::int dy, country_of_residence c
 from users_user where not is_deleted and birthdate ~ '^\d{4}/\d{2}/\d{2}$' and birthdate <> '0000/01/01')
select mo, count(*) n, count(*) filter (where c='SA') sa, count(*) filter (where c='AE') ae
from b where mo between 1 and 12 and dy between 1 and 31 group by 1 order by 1;
-- 1: 26,964 | 2: 26,790 | 3: 29,384 | 4: 28,401 | 5: 32,959 | 6: 28,465 | 7: 28,594 | 8: 29,588 | 9: 28,801 | 10: 31,790 (SA 14,021, AE 13,197) | 11: 29,558 | 12: 30,021
```
**N8: per-index usage, ecomweb catalog tables** (ecomweb; replica counters) [STRUCTURAL exact]
```sql
select s.relname, s.indexrelname, s.idx_scan, s.idx_tup_read, s.idx_tup_fetch from pg_stat_all_indexes s
where s.schemaname='public' and s.relname in ('brands_brand','brands_tagbrand','brands_tag','brands_brandsearchtag','brands_brand_search_tags',
 'brands_brand_categories','brands_brandcategory','brands_branddenomination','brands_branddenominationrange','brands_genericbrandslist',
 'brands_brandoccasion','brands_brandoccasion_brands','brands_occasion','configurations_sliderbrand','configurations_brandskin',
 'configurations_searchtag','configurations_customcategoryslider','configurations_homepageslider') and s.idx_scan > 0 order by s.relname, s.idx_scan desc;
-- brands_brand_pkey 8,522,861,264; code_like 2,040,678; slug_like 1,465,334; brands_tag seo_name_like 28,119,010, pkey 15,950,402;
-- brands_tagbrand brand_id 51,487,700, (tag,brand) uniq 42,342,249, tag_id 12,028,940; brands_brandsearchtag name_like 36,012, pkey 809,441;
-- brands_brandcategory pkey 802,978; genericbrandslist brand_id 1,449,066, generic_config_id 724,857 (228,645,673 read); sliderbrand brand_id 13,761; occasion pkey 8,542
```
**N9: brand/store/search/merch columns** (ecomweb and emapi; catalog) [STRUCTURAL exact]
```sql
select c.relname, a.attname, format_type(a.atttypid,a.atttypmod) t, a.attnotnull nn
from pg_class c join pg_attribute a on a.attrelid=c.oid and a.attnum>0 and not a.attisdropped
where c.relnamespace='public'::regnamespace and c.relkind='r' and (
 (c.relname='brands_brand' and a.attname ~ '(store|country|currency|visible|reference_name|gencode|order|is_|priority|rank|popular|featured|sort)')
 or c.relname in ('configurations_lastviewedbrand','brands_brandsearchtag','brands_brand_search_tag','configurations_searchtag',
  'configurations_shopcategory','configurations_shopcategorybrand','brands_tagbrand','brands_tag_brand','brands_favouritebrand'))
 and a.attname not in ('created_by_id','modified_by_id') order by 1, a.attnum;
-- ecomweb brands_brand: store_id nullable; visible_to_ecommerce/_ecommerce_app/_android_app/_ios_app/_at_work and is_launched nullable; list_order_number NOT NULL
-- emapi brands_brand: 12 visible_to_* (at_work nullable, others NOT NULL); ecom_order_number; lastviewedbrand: username vc255 null, brand_id NOT NULL, store_id null
-- plus: brand↔store/country tables per DB
select current_database() db, c.relname, c.reltuples::bigint est,
 string_agg(a.attname, ',' order by a.attnum) filter (where a.attname ~ '(brand_id|product_id|store_id|country_id|region|country)') keys
from pg_class c join pg_attribute a on a.attrelid=c.oid and a.attnum>0 and not a.attisdropped
where c.relnamespace='public'::regnamespace and c.relkind='r' group by 1,2,3
having bool_or(a.attname in ('brand_id','product_id')) and bool_or(a.attname ~ '(store_id|country_id|region)') order by 2;
-- ecomweb: brandoffer, plusoffer, brandpagepromotionbanner, lastviewedbrand; emapi: brands_offer, brands_plusoffer; orders: offer_plusoffer, offer_productoffer, user_tip_tipbrand*
-- => no brand↔country M2M anywhere; availability = brands_brand.store_id
```
**N10: table read counters, ecomweb catalog** (ecomweb; replica counters) [STRUCTURAL exact]
```sql
select s.relname, s.seq_scan, s.seq_tup_read, s.idx_scan, c.reltuples::bigint est, c.relpages
from pg_stat_all_tables s join pg_class c on c.oid=s.relid where s.schemaname='public' and (s.relname like 'brands_%' or s.relname in
 ('configurations_sliderbrand','configurations_brandskin','configurations_searchtag','configurations_customcategoryslider','configurations_homepageslider',
  'configurations_lastviewedbrand','configurations_productfeedbackbox','configurations_crosssellbrand','configurations_upcomingoccasion','company_company'))
order by coalesce(s.seq_scan,0)+coalesce(s.idx_scan,0) desc;
-- brands_brand idx 8,526,786,080 / seq 622; brands_tagbrand seq 2,381,186 (77,765,311,636 tuples) / idx 106,134,225; brands_tag seq 4,857,534 / idx 44,245,631;
-- genericbrandslist idx 2,173,936; hasofferbrands idx 2,085,822 (est 1,050); brandsearchtag seq 6,306 / idx 849,315; lastviewedbrand seq 4,649 (276,962,304) / idx 3,261;
-- brandoccasion_brands seq 104,137; upcomingoccasion seq 89,453 (0 rows); productfeedbackbox 0/0; crosssellbrand 0/0 (0 pages); brandoffer/brandcommission/handlingfee 0/0
```
**N11: orders catalog/merch columns and read counters** (orders; catalog) [STRUCTURAL exact]
```sql
select c.relname, a.attname, format_type(a.atttypid,a.atttypmod) t, a.attnotnull nn, c.reltuples::bigint est
from pg_class c join pg_attribute a on a.attrelid=c.oid and a.attnum>0 and not a.attisdropped
where c.relnamespace='public'::regnamespace and (c.relname='analytics_recommendedbrand'
 or (c.relname in ('basket_line','order_line') and a.attname in ('purchase_origin','is_white_label','upc','product_id','record_type'))
 or (c.relname in ('basket_basketquantitydetail','order_orderlinequantitydetail') and a.attname in ('denomination','is_buy_for_self','brand_skin','delivery_method'))
 or (c.relname in ('basket_basketpersonalisedetail','order_orderlinepersonalisedetail') and a.attname in ('occasion_code','greeting_code','delivery_type')))
order by 1, a.attnum;
-- order_line.upc vc128 NOT NULL; order_line.product_id NULLABLE; basket_line.product_id NOT NULL; purchase_origin vc20 on both;
-- basket_basketquantitydetail.denomination numeric(20,6) NOT NULL; analytics_recommendedbrand(region vc4, product vc64, count int, date_placed) 86 est
select relname, seq_scan, seq_tup_read, idx_scan from pg_stat_all_tables where schemaname='public' and relname in
 ('analytics_recommendedbrand','catalogue_product','catalogue_productcategory','catalogue_category','catalogue_productdenomination','catalogue_productdenominationrange','offer_plusoffer_happy_cards');
-- catalogue_product idx 29,073,518; offer_plusoffer_happy_cards idx 3,280,713; analytics_recommendedbrand seq 6,037; category/productcategory/denomination(range) 0
```
**N12: counter window per blocked DB** [STRUCTURAL exact]
```sql
select current_database(), round(extract(epoch from now()-stats_reset)/86400,2) stats_days,
 round(extract(epoch from now()-pg_postmaster_start_time())/86400,2) up_days, xact_commit
from pg_stat_database where datname=current_database();
-- ecomweb: stats_reset null, up 35.54 d, xact_commit 387,150,087; emapi: null, 35.54 d, 408; orders: null, 35.54 d, 10,431,910
```
(N6 and N7 were not used; numbering kept stable.)
