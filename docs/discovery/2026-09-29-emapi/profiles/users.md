# Profile: `ygag_ecom_users_db` (unit: users)

Profiled 2026-09-29 through `atlasq.sh` (atlas EC2 over SSH → read-only txn on Aurora read replica, PII-redacted).
Labels: **[exact]** = full `count(*)`/aggregate query; **[est]** = `pg_class.reltuples`; **[sample]** = TABLESAMPLE.
Note: the redactor masks digit-heavy strings (ISO dates came back as `<phone>`), so all dates were queried as `to_char(ts,'YYYY Mon DD')`.
**Snapshot rule (v2):** headline row counts come from one query (S1, run 2026-09-29 ~12:00 UTC): users_user **996,210**, users_cognitoissuedtokens **59,862** (54,702 users, 47,328 device signatures), notifications_twofactorauth **68,465** = verification **68,465** (54,780 is_valid=true). Breakdowns were run at other times of the same day on a live replica, so their totals drift by up to ~0.1% from S1 (e.g. users 996,189 → 996,216; OTP 68,407 → 68,468). Drift is labelled where visible; it is not a data error. `max(users_user.id)` was not part of S1 and moves with every signup: 1,411,092 (A3 run), 1,411,103 (B7 run), 1,411,121 at 12:21 UTC (C10, with 996,231 rows). All three are exact at their own run time. The differences are drift.
**v3 (critic round 2):** birthdate reinterpreted as `0000/DD/MM` (a birthday with no year); `type` and social-id columns shown to be dead fields; post-blacklist logins, bulk blacklist imports, new-vs-returning token split, residence-vs-login geography, producer-log reconciliation and multi-accept chains added. New SQL is C1–C10 in the appendix.

## 1. Summary

This is the **identity / auth microservice** DB of the YGG e-commerce stack (Django app; apps `users`, `core`, `notifications`, `kafka_clients`, `two_factor`, `otp_*`). It holds the consumer account master (`users_user`, **996,210 rows [exact, S1]**), secondary (alternate) emails, OTP/2FA requests and their verifications, issued Cognito-style JWTs (login proxy), a cross-service **blacklist/whitelist** (fraud controls fed by and published to Kafka), and ops config (captcha, OTP channel routing per country, email/WhatsApp templates).
It does **not** contain orders, baskets, payments, gifts, referrals or campaigns — only the identity side of those flows (e.g. "secondary email added via gift", blacklist events from `ecom_order`/`ecom_gift`).
Customers are GCC-centric: SA 463,760 and AE 412,917 of 996k users (country_of_residence) [exact]. Signups run ~19–31k/month (last 18 months) [exact]. About 80% of signups are flagged `is_app_user`, but only from **Aug 2024** onward (2023 17%, 2024 44%, 2025 81%, 2026 79% by signup year; monthly: 2024 Jun 18%, Jul 36%, Aug 84%) [exact, C3]. So the 80% figure describes the current regime, not the whole base. `birthdate` holds a **birthday without a year** (`0000/DD/MM`) for about 369k users (37%). That is usable for birthday-gifting triggers, but not for age.
Behavioral depth is limited: `users_user.last_login` is effectively dead since 2024 (938,813 NULL), OTP/2FA tables retain only **~31 days** (2026-08-29 20:05 → 2026-09-29), app tokens start 2026-07-13 and WEB tokens (30-day life) are only visible from 2026-08-29, which is consistent with expired tokens being purged.
`is_valid` on OTP verifications does **not** measure wrong-code failures. A `false` code was usually replaced by a resend (for sign_up, 52% of false codes are followed by a new code to the same recipient within 10 min, against 2% of true codes), or it was never used. A `true` code is almost always the last one in its chain (96%), and 88.5% of final-true sign_up email codes belong to a now-registered email, against 5.6% of final-false ones. The real friction signal is therefore **resend chains**: 7.5% of sign_up chains need 2 or more codes (median gap 104 s, while the code is valid for 5 min), 8.3% of sign_in chains, and **23.5% of 2fa_account_verification chains**. Only **66%** of 2fa chains end with an accepted code, against 90.6% for sign_up.
Other signals: a multi-day acquisition push from 2026-09-22 to 09-25 (signups 1.1–1.6k/day, about 2x baseline), with a resend spike concentrated on Sep 22–23. A **May 2025 cutover in the users_user id sequence**: 37–62% of each month's id range was missing from 2024 Jan to 2025 Apr, and under 1% from 2025 Jun, so signup counts before and after the change are not comparable. 1,298 `ecom_order` Kafka blacklist messages are stuck `in_progress`, and every one of them uses an old payload schema. Finally, 759 active email and 553 active mobile blacklist entries belong to accounts that are still live (903 distinct users), and **12 of those users were issued 18 new login tokens after they were blacklisted**. That is direct evidence that the blacklist does not block login. The two largest blacklist spikes (Jun and Aug 2026) are bulk admin imports, not organic detection. Token volume is mostly signup: 67% of Sep 2026 tokens went to users who had joined less than a day earlier.

## 2. Entities & Tables

40 tables in `public`. Volumes: exact counts unless marked.

| Entity | Table | Rows | Purpose / key columns |
|---|---|---|---|
| **User (account master)** | `users_user` | 996,210 [exact, S1] (reltuples 976,104) | PK `id` bigint (1…~1.41M, moving: 1,411,092 at A3, 1,411,121 at C10); `username` vc36 = UUID (unique, cross-service user reference); `email`, `phone_number` unique; `sub` (cognito sub – only 1 non-null!); `type` (signup method, **populated only until Oct 2023**), `platform`, `is_app_user`, `country_of_residence`, `language_code`, `gender`, `birthdate` (varchar `0000/DD/MM`, a birthday with no year); flags `is_active/is_enabled/is_deleted/is_staff/is_superuser/trusted_user/email_verified/phone_number_verified/is_native_user/enable_webauthn/new_password_policy/has_received_expiry_warning`; `legacy_auth_code[]` (legacy-platform ids); timestamps `date_joined`, `last_login`, `modified_on`, `password_last_changed` |
| User secondary identity | `users_secondaryuseridentity` | 76,175 | alternate email per user; `username` uuid (unique), `alternate_email` unique, `is_active`, `is_deleted`, FK `user_id` |
| Identity activity log (event stream) | `users_useridentityactivitylog` | 83,910 | `activity` (4 values), `timestamp`, `actor_id`, `user_id`, `comment` |
| Issued tokens (login sessions) | `users_cognitoissuedtokens` | 59,862 [exact, S1] | `jti` unique, `token_hash`, `device_signature`, `user_platform`, `request_meta` jsonb (COUNTRY, IP_ADDRESS, OS_TYPE, BROWSER, PLATFORM, IS_BOT, USER_AGENT, TIMESTAMP, TOKEN_DERIVATIVES…), `expires_at`, FK `user_id` |
| Token rotation (one-off) | `users_tokenrotatedusers` | 371 | `user_reference` vc36, `token_rotated`, 2023-07 → 2024-06 |
| Password history | `users_passwordhistory` | 16 | `password_hash`, FK user; new (2026-08-21 →) |
| Legacy migration log | `users_migratedtransactionlog` | 171,232 | `user_reference` (=users_user.username), `creation`, `request_status`, `legacy_auth_code[]`; 2023-05-09 → 2023-10-13 only |
| Legacy auth signature pref | `users_userauthlegacysignaturepreference` | 126,016 | `auth_signature`, `auth_code`, `prompt_migration_pop_up`, `is_valid` — no FK/timestamps |
| WebAuthn/passkeys | `users_webauthncredentialmodel` | 0 | built, unused (`enable_webauthn` true for 0 users) |
| OTP request (2FA) | `notifications_twofactorauth` | 68,465 [exact, S1] (2026-08-29 → 09-29) | `reference_id` unique, `auth_type`, `source` (flow), `email`/`phone_number`, delivery flags, `requested_attempts`, `code_length`, `validity`(min), `language` |
| OTP verification | `notifications_twofactorauthverification` | 68,465 [exact, S1] | 1:1 with request via FK `reference_id_id`; created within 1 s of the request (all but 3 rows); `request_id` unique, `is_valid` (true = the accepted/unsuperseded code; see §7), `auth_code` (always NULL — redacted/cleared) |
| Blacklist | `core_blacklisteduserdetail` | 8,759 | `type` (email/domain/mobile/ip/device_id/sms_country_code), `value` (PII), `source` (originating service), `is_removed`, `is_guest`, `reference_id`, `remarks`; unique (type,value) |
| Whitelist | `core_whitelisteduserdetail` | 119 | same shape, no is_guest |
| Promo domain blacklist | `users_promotionaldomainblacklist` | 7 | domains excluded from promotions (all active) |
| Kafka consumer log (blacklist in) | `kafka_clients_blacklistuserconsumerdatalog` | 5,113 | `service_name`, `data` jsonb (event_type, event_id, data), `status`, `error_data`, `start/completed_timestamp` |
| Kafka producer log (blacklist out) | `kafka_clients_blacklistuserproducerlog` | 14,148 | `event_id` uuid unique, `payload` text (python-repr, not JSON), `status`, `error`. Two message shapes: 7,031 legacy-sync (`fraud_type, fraud_value, is_removed`) and 7,117 blacklist events (`app_device_id, email, is_guest, mark_as_fraud, phone_number, reference_id` ± `domain/ip_address/sms_country_code`); see §7 |
| Kafka consumer log (re-fetch) | `kafka_clients_serviceinternalrefetchconsumerdatalog` | 113 | `SERVICE_INTERNAL_RE_FETCH` from `YouGiftAPI`, 2025-10 → |
| OTP channel config | `notifications_communicationchannelconfig` (4), `notifications_communicationcountries` (2), `notifications_communicationcountryconfigs` (14; reltuples said 0) | config | per message_type × channel (sms/whatsapp/email) routing; whatsapp 93 countries, sms 92 |
| Templates | `notifications_emailtemplateconfiguration` (7), `notifications_whatsapptemplateconfiguration` (2) | config | email_type: twofactor_emails, sec_identity_added, sec_identity_removed, password_expiry_warning; WA: account_verification |
| Core config | `core_captchaconfigurations` (5), `core_remoteurlconfig` (7), `core_siteconfiguration` (1, jsonb), `core_language` (2: EN default, AR) | config | captcha actions `signin_signup`, `update_phone_number` (threshold 0.5; V3 + ENTERPRISE enabled); remote servers SMS_ENGINE, GENERATE_OTP, RESEND_OTP, VERIFY_OTP, WHATSAPP, YOUPAY, MAIL_ENGINE; site config keys: secondary_identity, voice_alert_config, automation_accounts, drm_dashboard_state, update_phone_number, disposable_usercheck, webauthn_authentication, disposable_email_manager, dynamic_throttle_manager |
| Staff auth / RBAC | `auth_group` (4), `auth_group_permissions` (152 est), `auth_permission` (136 est), `users_user_groups` (33), `users_user_user_permissions` (17), `otp_totp_totpdevice` (19), `otp_static_*` (0), `two_factor_phonedevice` (0) | admin | groups: cs team write access (14), cs team read access (15), admin (1), Sensitive Data Visibility (3) |
| Django infra | `django_admin_log` (4,931), `django_session` (1,825; 19 live), `django_content_type` (34), `django_migrations` (108), `django_site` (1) | infra | admin log = CS/back-office audit trail |

## 3. Relations

Declared FKs (all DEFERRABLE):
- `users_user.id` ← `users_secondaryuseridentity.user_id`, `users_useridentityactivitylog.user_id/actor_id`, `users_cognitoissuedtokens.user_id`, `users_passwordhistory.user_id`, `users_webauthncredentialmodel.user_id`, `otp_totp_totpdevice.user_id`, `otp_static_staticdevice.user_id`, `two_factor_phonedevice.user_id`, `users_user_groups.user_id`, `users_user_user_permissions.user_id`, `django_admin_log.user_id`, and `created_by_id/modified_by_id` on every config/blacklist/whitelist/2FA table (and self-FK on users_user).
- `notifications_twofactorauthverification.reference_id_id` → `notifications_twofactorauth.id` (1:1 in practice: 68,465 each at S1).
- `notifications_emailtemplateconfiguration.language_id` → `core_language.id`.
- `otp_static_statictoken.device_id` → `otp_static_staticdevice.id`; auth_* standard Django.

Logical (undeclared) keys:
- `users_migratedtransactionlog.user_reference` = `users_user.username` (171,232/171,232 matched [exact]).
- `users_tokenrotatedusers.user_reference` ≈ `users_user.username` (vc36).
- `core_blacklisteduserdetail.reference_id` → id in originating service (`source` = ecom_gifts/ecom_orders/ecom_groupgift/atwork/ecom_legacy).
- `notifications_twofactorauth` has **no user FK** — only recipient email/phone (created_by is a single service account). Joining OTP to users requires matching on email/phone (PII join; do in-DB only).
- `kafka_*.data->>'event_id'` ↔ producer `event_id` in other services.

## 4. Lifecycle States

- `users_user.type` (signup method, **populated only until Oct 2023**): conventional_user 977,264; google_user 11,798; apple_user 6,413; facebook_user 713; other 2 [exact]. Every signup from Nov 2023 on is `conventional_user` (2024 all 269,064; 2025 all 281,274; 2026 all 208,609) [exact, C2], so the overall 98% conventional share is an artefact. See the per-year table in §6.
- `users_user.platform`: other 938,843; ios 36,058; android 17,058; web 2,867; mweb 1,364 [exact]. Every user since 2024 is `other` (platform no longer populated).
- `users_user` flags (is_active, is_enabled, is_deleted): (T,T,F) 974,051; (T,T,T) 22,101; (T,F,F) 35; (F,F,F) 4; (T,F,T) 4; (F,T,T) 3; (F,T,F) 3 [exact]. **Soft-delete = `is_deleted`** (22,108 total); is_active/is_enabled are near-constant.
- `users_user` other: is_app_user 554,846; email_verified 996,155; phone_number_verified 996,156; trusted_user 862; is_native_user 30; new_password_policy 38,120; is_staff 42; is_superuser 16; has_received_expiry_warning 16; enable_webauthn 0 [exact].
- `users_useridentityactivitylog.activity`: secondary_email_added_via_gift 59,585; secondary_email_added 16,590; updated_phone_number 3,912; secondary_email_removed 3,823 [exact].
- `users_secondaryuseridentity` (is_active,is_deleted): (T,F) 72,637; (T,T) 3,538 [exact]; max 1 live alternate email per user.
- `notifications_twofactorauth` source × auth_type (31-day window) [exact]: sign_up/whatsappsms 27,231; sign_up/email 22,923; sign_in/email 11,985; 2fa_account_verification/email 4,933; account_verification_for_change_phone_number/emailsms 472; sign_in/whatsapp 307; sign_in/sms 295; change_phone_number/whatsappsms 176; sign_up/whatsapp 87; account_verification_for_change_phone_number/email 4; change_phone_number/whatsapp 2. Constants: requested_attempts=3, code_length=6, validity=5 (min). language en 53,683 / ar 14,732.
- `notifications_twofactorauthverification.is_valid`: true 54,780; false 13,688 [exact, drift +3 vs S1]. Semantics: true is the code that was accepted and not superseded. false means the code was superseded by a resend or never used. It is **not** a wrong-code counter (§7).
- `notifications_twofactorauth` delivery flags (auth_type → email/sms/whatsapp_delivery) [exact]: email → (T,F,F) 39,877; whatsappsms → (F,T,F) 27,434; emailsms → (T,T,F) 473; sms → (F,T,F) 295; **whatsapp → (F,F,F) 397**. `whatsapp_delivery` is never true on any row.
- `users_cognitoissuedtokens.user_platform`: app-ios 32,121; app-android 16,785; WEB 10,796; UNACCOUNTED 167 [exact, 59,869 total, drift vs S1]. Token lifetime is fixed per platform: app/UNACCOUNTED **548 d**, WEB **30 d** in every month. request_meta IS_BOT: false 59,679; null 157.
- `core_blacklisteduserdetail.type` (total/active): user_email 3,775/3,491; user_domain 3,678/3,655; user_mobile_no 718/588; user_ip 305/79; user_device_id 166/117; sms_country_code 117/101 → 8,759/8,031; is_guest 6,542 [exact].
- blacklist `source` (total/active): ecom_users 7,087/6,908; ecom_legacy 807/424; ecom_gifts 695/609; ecom_orders 71/12; ecom_groupgift 70/50; atwork 29/28 [exact].
- `kafka_clients_blacklistuserconsumerdatalog` event_type/service/status: blacklist_user_event ecom_gift completed 1,807; blacklist_user_event ecom_order **in_progress 1,298** (all with payload keys `email,guest_id,is_guest,phone_number`, whereas all 650 completed ecom_order rows have `app_device_id,email,is_guest,mark_as_fraud,phone_number,reference_id`); fraud_data_sync ecom_legacy_fraud_event completed 920; blacklist_user_event ecom_order completed 650; ecomgroupgift completed 398; atwork completed 40 [exact].
- `kafka_clients_blacklistuserproducerlog.status`: completed 14,148 (100%, 0 errors) [exact]. By shape and flag [exact, C7]: legacy-sync domain 3,746 add / 129 remove; email_address 2,567 / 99; phone 344 / 38; ip_address 24 / 84 (6,681 adds, 350 removals). Blacklist events: mark_as_fraud=True 6,722 (guest 5,400, non-guest 1,321, null 1); mark_as_fraud=False 395.
- `users_migratedtransactionlog` (creation, request_status): (T,F) 111,347; (T,T) 57,344; (F,F) 2,119; (F,T) 422 [exact].
- `users_userauthlegacysignaturepreference` (prompt_migration_pop_up, is_valid): (T,T) 103,126; (F,T) 17,419; (F,F) 5,466; (T,F) 5 [exact].
- `django_admin_log` action_flag (1=add,2=change,3=delete) by model: add blacklist 1,697; **delete users.user 1,459**; change blacklist 637; change users.user 336; change siteconfiguration 297; change whitelist 165; add whitelist 122; … 23 distinct admins since 2023-03-31 [exact]. User hard deletes by year: 2023 688, 2024 225, 2025 215, 2026 331 (11/9/11/11 distinct admins) [exact].
- `users_user.gender` [exact]: male 607,843; female 165,016; NULL 131,692; '' 91,664; other 1.

## 5. Time Coverage & Trends

| Table.column | min | max |
|---|---|---|
| users_user.date_joined | 2012 Dec 03 | 2026 Sep 29 |
| users_user.last_login | 2014 Apr 11 | 2026 Sep 29 (but 938,813 NULL; 42,156 in 2023, 3/4/20 in 2024/25/26) |
| users_user.modified_on | 2023 May 09 | 2026 Sep 29 |
| users_user.password_last_changed | 2026 May 29 | 2026 Sep 23 (42 non-null) |
| users_useridentityactivitylog.timestamp | 2024 Jul 29 | 2026 Sep 29 |
| users_secondaryuseridentity.created_on | 2024 Jul 29 | 2026 Sep 29 |
| users_cognitoissuedtokens.created_on | 2026 Jul 13 (app) / 2026 Aug 29 20h (WEB) | 2026 Sep 29 (expires_at to 2028 Mar 30; life 548 d app, 30 d WEB) |
| notifications_twofactorauth.created_on | 2026 Aug 29 | 2026 Sep 29 (rolling ~31-day retention) |
| core_blacklisteduserdetail.created_on | 2023 May 13 | 2026 Sep 29 |
| kafka blacklist consumer start_timestamp | 2024 Apr 15 | 2026 Sep 29 |
| kafka refetch consumer | 2025 Oct 21 | 2026 Sep 28 |
| users_migratedtransactionlog.created_on | 2023 May 09 | 2023 Oct 13 |
| django_admin_log.action_time | 2023 Mar 31 | 2026 Sep 29 |

Signups by year [exact]: 2012–2022 total 19,152 (legacy migrated users keep original dates); 2023 218,130 (new platform go-live + migration); 2024 269,064; 2025 281,274; 2026 YTD 208,593.
**Year buckets overlap in id space.** Pre-2023-dated users hold ids 32–189,396, and 2023 Jan–May joiners hold ids 1–189,338. Both are the legacy-migration block. The new platform's clean sequence starts at id 62,586 (2023 Jun).

**Id-sequence gaps by join month** (gap = max−min+1−rows) [exact]. The gap is not spread across years. It follows a regime that ends in **May 2025**:

| Period | Gap % of id range | Example months |
|---|---|---|
| 2023 Jun – 2023 Dec | 0.5–27% (volatile) | Jun 0.5%, Aug 27.3%, Oct 1.1% |
| **2024 Jan – 2025 Apr** | **37–62% every month** | 2024 Jan 42.1% (17,278), 2024 May 62.5% (35,138), 2025 Jan 60.8% (32,708), 2025 Apr 38.7% (14,107) |
| **2025 May (cutover)** | 6.9% (1,866) | — |
| 2025 Jun – 2026 Sep | 0–11% | 2025 Jun 0.1% (17), Jul 0.1% (12), Oct 10.9% (2,687), 2026 Feb 0.0% (1), 2026 Sep 0.7% (166) |

That is 378,955 missing ids in 2024 Jan–2025 Apr. Admin hard deletes (`django_admin_log`: 225 in 2024, 215 in 2025) explain almost none of it. The likely causes are a periodic purge of unverified or incomplete signups, or an insert-then-rollback signup flow that was changed in May 2025. **Do not compare signup counts across May 2025 directly.** Before the cutover, surviving rows are roughly 40–60% of id allocations. After it, nearly all allocations survive. Part of the apparent 2025→2026 growth may be a definitional artefact of that change.

Monthly signups (date_joined) [exact]:

| Month | Signups | is_app_user | since soft-deleted | Soft deletions that month (modified_on) |
|---|---|---|---|---|
| 2025 Mar | 31,182 | 26,714 | 699 | 626 |
| 2025 Apr | 22,384 | 18,930 | 517 | 598 |
| 2025 May | 25,192 | 21,917 | 545 | 577 |
| 2025 Jun | 25,239 | 19,982 | 691 | 758 |
| 2025 Jul | 18,963 | 15,589 | 436 | 518 |
| 2025 Aug | 18,936 | 14,727 | 344 | 430 |
| 2025 Sep | 21,014 | 16,289 | 291 | 388 |
| 2025 Oct | 21,925 | 17,409 | 292 | 369 |
| 2025 Nov | 24,649 | 19,400 | 306 | 378 |
| 2025 Dec | 28,186 | 21,761 | 409 | 493 |
| 2026 Jan | 22,862 | 18,021 | 315 | 405 |
| 2026 Feb | 22,918 | 18,094 | 351 | 449 |
| 2026 Mar | 29,608 | 24,164 | 432 | 606 |
| 2026 Apr | 23,266 | 18,050 | 358 | 500 |
| 2026 May | 22,707 | 17,522 | 290 | 447 |
| 2026 Jun | 24,405 | 17,769 | 328 | 496 |
| 2026 Jul | 20,161 | 16,698 | 238 | 417 |
| 2026 Aug | 18,857 | 15,629 | 268 | 417 |
| 2026 Sep (to 29th) | 23,785 | 19,238 | 295 | 492 |

Seasonality: peaks Mar (Ramadan/Eid), Dec; troughs Jul–Aug. Soft-deletion month uses `modified_on` as a proxy (no deleted_at column).

Token issuance by month [exact]: 2026 Jul 782 (from 13th; app only), Aug 22,387 (529 WEB), Sep 36,699 (10,267 WEB).
**Tokens mostly measure first logins** [exact, C4]. Token count by month and platform, split by whether the user joined at most 1 day before the token was issued:

| Month | Platform | Tokens | New user (≤1 d) | Returning (>1 d) | Returning users |
|---|---|---|---|---|---|
| 2026 Aug | app-ios | 14,119 | 10,222 | 3,897 | 3,725 |
| 2026 Aug | app-android | 7,678 | 4,889 | 2,789 | 2,665 |
| 2026 Aug | WEB | 529 | 297 | 232 | 221 |
| 2026 Sep | app-ios | 17,508 | 12,970 | 4,538 | 4,314 |
| 2026 Sep | app-android | 8,835 | 5,876 | 2,959 | 2,784 |
| 2026 Sep | WEB | 10,275 | 5,677 | 4,598 | 4,200 |
| 2026 Sep | UNACCOUNTED | 106 | 44 | 62 | 60 |

Sep 2026 total: 36,724 tokens, of which 24,567 (**66.9%**) were new-user logins and 12,157 returning (Aug: 69%). Token volume is therefore a signup proxy, not an engagement measure. Returning-login volume is about 12k per month, and for app it is also capped by the 548-day token life (a logged-in app user never needs a new token). Web is the only platform where returning logins are the larger share (45%). Average lifetime by month (548 → 536 → 403 d) falls only because of the **mix**: every app token lives 548 d and every WEB token 30 d. WEB tokens appear only from 2026-08-29 20h, the same boundary as the OTP retention window, which is consistent with a purge of expired WEB tokens. Monthly token counts before Aug 29 therefore exclude web logins. This is not a policy change.

## 6. Behavior Signals

- **Account creation**: `users_user.date_joined` (+ country, is_app_user). ~23k/month. Trends crossing May 2025 are distorted by the id-gap cutover (§5). **Signup method cannot be measured from `type`**: it was last populated in Oct 2023. The social-IdP id columns are a better proxy, but they also stop in Nov 2024 [exact, C2/C3]:

  | Signup year | Users | type ≠ conventional | google_id | apple_id | facebook_id | any social id | is_app_user |
  |---|---|---|---|---|---|---|---|
  | pre-2023 | 19,152 | 4,538 | 2,231 | 2,314 | 927 | 5,255 (27%) | 4,732 (25%) |
  | 2023 | 218,130 | 14,388 | 51,141 | 27,492 | 3,034 | 80,638 (37%) | 37,441 (17%) |
  | 2024 | 269,064 | 0 | 60,949 | 35,514 | 999 | 97,236 (**36%**) | 118,621 (44%) |
  | 2025 | 281,274 | 0 | 0 | 0 | 0 | 0 | 228,869 (81%) |
  | 2026 | 208,609 | 0 | 0 | 0 | 0 | 0 | 165,217 (79%) |

  Monthly, the social-id share runs about 35–50% from 2023 Jun through 2024 Oct (Sep 8,686 of 17,624), drops to 1,603 in Nov 2024, and is 0 from Dec 2024. `type` social values last appear in Oct 2023 (458), then 0. Social login was therefore about **36–37% of signups in 2023–24** and is **unrecorded since Dec 2024**, which is not the same as zero. The earlier "98% conventional / social 1.9%" figure was an artefact and is withdrawn. `is_app_user` jumps from 18% (2024 Jun) to 36% (Jul) to 84% (Aug 2024) and stays around 80% after that. The jump is in Aug 2024, not at the May 2025 id cutover, so it is a separate definition or flow change.
- **Demographics** [exact]: gender male 607,843 (61%), female 165,016 (17%), unknown 223,357 (NULL 131,692 + '' 91,664), other 1. `birthdate` is **varchar**: '' 494,137, NULL 132,525, and 369,553 values shaped `NNNN/NN/NN` [exact, C1]. The format is **`0000/DD/MM`, a birthday with no year**. Field 1 is `0000` in every row. Field 2 is a day: values 1–31 cover all but 18 rows, with 29, 30 and 31 lower as expected (9,403 / 10,124 / 6,519). Field 3 is a month: values 1–12 cover 369,436 rows (99.97%). **369,420 users (37%) have a valid day+month, 360,918 of them not deleted.** **No age bands are possible**, but birthday-month and birthday-day triggers are. That matters for a gifting business (birthday reminders, "gift yourself" offers, gifting prompts to contacts). Birth-month distribution (field 3) [exact]: Jan 37,496; Feb 27,443; Mar 30,109; Apr 29,092; May 33,734; Jun 29,114; Jul 29,249; Aug 30,277; Sep 29,420; Oct 32,552; Nov 30,266; Dec 30,684. There are default-value spikes: day 1 is 27,205, about 2.5x a typical day, and exactly `0000/01/01` is 9,940. Treat 01/01 as a probable default, not a birthday. Coverage by signup year: pre-2023 9,883 (52%), 2023 88,458 (41%), 2024 99,100 (37%), 2025 64,451 (23%), 2026 107,528 (52%). `custom_profile_img` true for 1,807.
- **Sign-in / sessions**: `users_cognitoissuedtokens` has one row per issued token: 59,862 tokens / 54,702 users / 47,328 distinct device signatures [exact, S1]. Per user: 50,551 users with 1 token, 3,950 with 2–3, 169 with 4–10, 10 with more than 10 [exact]. Platform mix: iOS 54%, Android 28%, Web 18% (web visible only from Aug 29). Geo (request_meta.COUNTRY): Saudi Arabia 28,956; UAE 22,159; Qatar 1,289; India 948; Kuwait 873 [exact]. App tokens live 548 d, so this measures new logins, not DAU. About 67% of those logins are the first login right after signup (§5 table).
- **Residence vs login country (travel / VPN risk signal)** [exact, C5/C6]: `users_user.country_of_residence` compared with token `request_meta->>'COUNTRY'`. Tokens from outside the GCC: **AE residents 1,424 of 23,446 (6.1%)** and **SA residents 1,094 of 30,019 (3.6%)**. Other-GCC logins are small (AE 106, SA 104). About half of these out-of-GCC tokens are signup-day logins (AE 725, SA 690), which means the account was created from abroad or behind a VPN. Web accounts for 366 of the AE cases and 161 of the SA cases. Top mismatched pairs (tokens / users): SA→United States 209/198, SA→Spain 189/183, SA→UK 105/100, SA→India 89/84, SA→Egypt 78/68; AE→United States 207/199, AE→India 204/197, AE→UK 185/176, AE→Brazil 91/90, AE→Germany 64/53, AE→Romania 53/49. Two pairs stand out because their tokens-to-users ratio is about 1: SA→Spain and AE→Brazil. Many distinct users logging in once from an unexpected country fits VPN exit nodes or bulk signups better than travel. The unusual RU→Germany pair (70 tokens, 70 users) also fits. This is a candidate fraud feature. It is not proof.
- **OS / browser (request_meta)** [exact]: OS_TYPE iOS 38,214 (35,329 users); Linux (Android UA) 18,575; Windows 1,928; Macintosh 883; NULL 256; ChromeOS 7; Windows Phone 1. BROWSER is overwhelmingly Safari (26.x builds lead: 26.6.1 10,721; 26.6 7,030; 26.5.2 5,675), then Chrome 150–154 (152: 4,469; 151: 4,239; 143: 3,895; 153: 3,306). PLATFORM top values: iOS 18.7 33,675; Android 10 17,839 (UA-frozen versions).
- **Device sharing (multi-account signal)** [exact]. Device signatures are present only on app tokens (all 10,796 WEB and 167 UNACCOUNTED tokens have none). Of 47,332 app devices, 47,213 map to 1 user. **117 devices are shared by 2–3 users** (236 users, 313 tokens) and **2 devices by 4–10 users** (12 users, 19 tokens). These are candidates for fraud or multi-account review, and could be cross-checked against `core_blacklisteduserdetail` type `user_device_id`.
- **OTP funnels** (31 days): sign_up OTPs 50,243 to 42,919 distinct recipients; sign_in 12,587 / 9,913; 2fa_account_verification 4,933 / 3,165; change-phone flows 654 [exact, earlier run]. Resend chains (codes to the same recipient+flow at most 10 min apart) [exact]: sign_up 44,743 chains, 90.6% ending in an accepted code; sign_in 11,402 chains, 88.3%; 2fa 3,555 chains, **66.0%**.
- **OTP hour of day (Asia/Dubai)** [exact]: sign_up peaks at 17h (3,477) and bottoms at 05h (590), a 5.9x swing. All flows peak 15–18h (total 17h 4,769; trough 05h 753). 2fa_account_verification peaks 17h (465).
- **OTP recipient country (phone prefix)** [exact, 28,599 phone OTPs]: SA +966 15,387 (14,443 distinct numbers); AE +971 9,246 (8,797); QA 613; KW 499; GB 405; IN 399; EG 340; US/CA 329; OM 294; BH 201; PK 74; JO 52; PH 34; other 726. About 97% of phone OTPs are sign_up. Email OTPs (39,877 email-only) have no country.
- **Channel mix**: sign_up is delivered via WhatsApp+SMS (27,231) and email (22,923). sign_in is mostly email (11,985), with 602 via WhatsApp/SMS.
- **Identity changes** [exact]: secondary email added via gift 59,587 (strong gifting link: a recipient claims a gift to an alternate email); self-added 16,591; removed 3,823 (89 by a different actor, i.e. CS); phone number updated 3,912, **with actor_id NULL on all 3,912** (actor not recorded). Gift-driven adds run about 1.6–3.6k per month (peaks Mar, Dec, Jun).
- **CS / back-office actions**: `django_admin_log` shows 1,459 user hard deletes (2023 688, 2024 225, 2025 215, 2026 331; 18 distinct admins overall), 336 user edits, and 2,334 blacklist adds and edits. `users_user.modified_by_id` is set on 256 rows and differs from the user's own id on 253 (21 of those are soft-deleted). That is the CS edit footprint on the user table.
- **Blacklist vs live accounts (fraud-control gap)** [exact]: **759 of 3,491 active user_email** entries match a users_user email (752 fully live: active, enabled, not deleted; 0 soft-deleted; 0 trusted). **553 of 588 active user_mobile_no** entries match a live user phone (all fully live). Together these are **903 distinct live users** (409 match on both email and mobile) [exact, C8]. **Observed evidence that blacklisted users keep logging in** [exact, C8]: 48 of the 903 hold tokens (63 tokens). **18 tokens for 12 users were issued after that user's earliest active blacklist entry was created**: 17 app and 1 WEB, 3 of them in Sep 2026. The 14 + 13 tokens-after-blacklist figure you get from the email and mobile joins separately double-counts users matched both ways. By source (email match / mobile match, tokens after blacklist): ecom_users 7 / 9, ecom_gifts 4 / 4, ecom_legacy 3 / 0. Blacklisting does not disable the account or block login here. Enforcement, if any, must happen at action time in downstream services (verify). Domain overlap [sample 5%]: 127 of 47,547 sampled users (0.27%, about 2.7k users extrapolated) have an email on an actively blacklisted domain, all not deleted. An earlier critic sample gave 0.4%, so treat ~0.3–0.4% as the range.
- Not present here: views, baskets, orders, payments, gifts, redemptions, referrals, campaigns, offers, notifications-sent history (only config + OTP).

## 7. Friction & Errors

- **What `is_valid` means** (resolves the earlier open question). Test: `lead()` over the same recipient and flow [exact]:
  | flow | is_valid | rows | next code ≤10 min | next code later | last in sequence |
  |---|---|---|---|---|---|
  | sign_up | false | 8,832 | **4,553 (51.6%)** | 1,153 | 3,126 |
  | sign_up | true | 41,449 | 986 (2.4%) | 633 | **39,830 (96.1%)** |
  | 2fa_account_verification | false | 2,580 | **1,372 (53.2%)** | 369 | 839 |
  | 2fa_account_verification | true | 2,357 | 10 (0.4%) | 17 | 2,330 (98.9%) |
  | sign_in | false | 2,103 | 723 | 352 | 1,028 |
  | sign_in | true | 10,493 | 472 | 1,130 | 8,891 |

  Outcome check on the final sign_up **email** code per recipient: 13,156 of 14,861 final-true codes (88.5%) belong to an email that is now a registered user, against 114 of 2,042 final-false codes (5.6%) [exact]. So `is_valid=true` marks the code that was accepted and not superseded. `is_valid=false` means the code was superseded by a resend, or was never used and expired or was abandoned. The earlier "validity rates" (sign_up email 71%, 2fa 47.7%, 13% on Sep 22) **measured resend and abandonment, not failed verification**, and have been withdrawn as success metrics.
  **Caveat: a resend does not always invalidate the earlier code** [exact, C9]. Some multi-code chains contain 2 or more `is_valid=true` codes. sign_up: 726 of 3,362 multi-code chains (21.6%), and in 627 of them every code is true. sign_in: 369 of 944 (39%), all true in 331. 2fa_account_verification: only 10 of 835. account_verification_for_change_phone_number: 15 of 55. Chains where an accepted code is not the last code: sign_up 61, sign_in 49, change-phone verification 8. So for sign_up and sign_in, `true` means "not invalidated", and a completed verification followed by a fresh request (re-entry, or a double submit) can leave several trues. "true = final accepted code" holds for most chains (sign_up: 41,415 of 44,777 chains have a single code) but not all. Count chains, not true rows, when measuring success. 2fa behaves strictly: its resends do invalidate the earlier code.
- **Resend-chain friction** (chain = codes to the same recipient and flow at most 10 min apart) [exact]:
  | flow | chains | ≥2 codes | ≥3 | ≥5 | avg codes | chains with no accepted code | median gap between codes (p25–p75) |
  |---|---|---|---|---|---|---|---|
  | sign_up | 44,743 | 3,360 (7.5%) | 996 | 264 | 1.12 | 4,215 (9.4%) | 104 s (68–191) |
  | sign_in | 11,402 | 944 (8.3%) | 179 | 14 | 1.10 | 1,332 (11.7%) | 129 s (65–257) |
  | 2fa_account_verification | 3,555 | **835 (23.5%)** | 313 | 67 | 1.39 | **1,208 (34.0%)** | 77 s (40–145) |
  | account_verification_for_change_phone_number | 410 | 55 (13.4%) | 11 | 0 | 1.16 | 91 (22.2%) | 53 s |
  | change_phone_number | 174 | 3 (1.7%) | 1 | 0 | 1.02 | 27 (15.5%) | 199 s |

  Median resends come at 1–2 min, well inside the 5-min code validity. Users are not waiting for expiry, so a code not arriving (delivery latency) is the likely cause. 2fa_account_verification is the worst flow: 1 in 4 chains needs a resend and 1 in 3 never ends with an accepted code. Repeat recipients across the whole 31 days (not chained) [exact, earlier run]: sign_up has 39,253 once, 2,433 twice, 936 3–5x, 215 6–10x, and 82 more than 10x.
- **Acquisition push 2026-09-22 → 09-25 with a resend spike on Sep 22–23** [exact]. Daily signups: Sep 19–21 576/573/858; **Sep 22 1,640, Sep 23 1,484, Sep 24 1,637, Sep 25 1,129**; then back to 844–1,012. sign_up resend share: Sep 22 25.6% (1,154/4,513), Sep 23 20.0% (706/3,533), then **Sep 24 7.1%** (215/3,038; is_valid 86.9%) against a 7–12% baseline. 2fa_account_verification: Sep 22 1,060 requests with 475 resends (44.8%), Sep 23 553/211 (38.2%), Sep 24 214/46 (21.5%), against about 80–145 requests per day with 12–23% resends before. This reads as a sustained multi-day acquisition push (campaign) plus one to two days of OTP delivery degradation or retry storms, not a single-day incident.
- **Kafka stuck messages**: 1,298 `ecom_order` blacklist_user_events are stuck `in_progress` (983 from 2024, 257 from 2025, 58 from 2026), 67% of all ecom_order events [exact]. **Root-cause signal**: every stuck row carries the old payload schema `{email, guest_id, is_guest, phone_number}`, while every completed ecom_order row carries `{app_device_id, email, is_guest, mark_as_fraud, phone_number, reference_id}`. The consumer most likely fails on the missing `reference_id`/`mark_as_fraud` without recording an error. Stuck rows have NULL `completed_timestamp`, and `error_data` is empty on every row. Completed-job latency is negligible: ecom_gift avg 0.059 s (p95 0.165, max 3.574); ecom_order avg 0.066 s (max 1.773); legacy fraud avg 0.080 s; refetch consumer avg 0.919 s (max 1.285) [exact]. The producer log is 100% completed with 0 errors.
- **Producer log reconciled against the blacklist** [exact, C7]. The 14,148 producer events are not one per blacklist row. Every blacklist **change originating in ecom_users** is published twice:
  1. A **legacy-sync** message (`fraud_type, fraud_value, is_removed`). There are 7,031: 6,681 adds and 350 removals (2024 272, 2025 3,110, 2026 3,649).
  2. A **blacklist event** for downstream ecom services (`app_device_id, email, is_guest, mark_as_fraud, phone_number, reference_id` ± `domain/ip_address/sms_country_code`). There are 7,117: mark_as_fraud True 6,722, False 395 (2024 274, 2025 2,907, 2026 3,936).

  Both streams start on 2024 Apr 15–19. In the blacklist table, ecom_users rows created since 2024-04-15 number 6,882, of which 164 are now removed. 6,882 adds plus 164 removals is 7,046, which is within 0.2% of the 7,031 legacy-sync messages. Removal messages (350) outnumber currently-removed rows, which is consistent with entries being toggled more than once. The 1,672 entries whose source is another service (ecom_gifts 695, ecom_legacy 807, ecom_orders 71, groupgift 70, atwork 29) arrive through the consumer log and are **not re-published**. The 205 ecom_users entries from before 2024-04-15 predate the producer. So 14,148 ≈ 2 × ~7.05k ecom_users changes. False `mark_as_fraud` (395) is the removal/unflag counterpart in the event stream.
- **Blacklist growth**: monthly adds were 99–641 through 2025, then spiked in Jun 2026 (845) and **Aug 2026 (1,445)** [exact]. **Both spikes are bulk admin imports, not organic fraud detection** [exact, C6b]:
  - **Jun 2026**: ecom_users `user_domain` 508 of 845 (505 guest). 393 of these came on Jun 23–24 (Jun 24: 291 rows, 2 remark texts). The rest: ecom_users user_email 165, ecom_legacy user_email 43, ecom_users mobile 31, ecom_legacy ip 24, ecom_gifts mobile 20 / email 18.
  - **Aug 2026**: ecom_users `user_email` 1,181 of 1,445 (1,145 guest). **797 of these were added on Aug 25 inside 38 distinct minutes, all with a single remark text**, which is a spreadsheet upload. There were also 85 on Aug 11 and 85 on Aug 13. The rest: ecom_users domain 117, mobile 60, ecom_legacy email 24.

  Organic, service-originated adds (ecom_gifts, ecom_orders, groupgift) stay flat at about 14–46 per month in May–Sep 2026. Do not read the spikes as a fraud wave. 6,542 of 8,759 entries are guest (non-registered) identities, and user_ip entries are mostly removed (79 of 305 active). Remarks [exact]: only **65 distinct remark texts**. 4 templated texts cover 4,900 rows (bulk admin imports: 2,752 remarks mention bulk/list/upload/sheet and 439 mention domain). 3,638 are empty (every entry from ecom_gifts, groupgift, orders and legacy). Keyword classes: promo/referral abuse 65, fraud/chargeback 45, suspicious 44, bot/spam 11, disposable 2, ticket reference 10.
- **Blacklisted identities on live accounts**: 752 email and 553 mobile blacklist entries point at fully live accounts (903 distinct non-deleted users, §6). **12 of those users were issued 18 login tokens after being blacklisted** [exact, C8], so login is not blocked. Unless downstream services check the blacklist at every order or gift, these accounts are un-blocked.
- **User id sequence gaps**: see §5. 378,955 missing ids from 2024 Jan to 2025 Apr (37–62% per month), then a cutover to under 1% from 2025 Jun. Admin hard deletes (~440 in 2024–25) are negligible.
- **Soft deletions**: ~370–760 accounts per month flagged is_deleted; 22,108 total (2.2%).
- Captcha on signin_signup and update_phone_number (score threshold 0.5); scores are not logged here.

## 8. Cross-DB Keys

| Column | Type | Range / format | Likely shared with |
|---|---|---|---|
| `users_user.id` | bigint | 1 … ~1.41M, moving (1,411,092 at A3, 1,411,103 at B7, 1,411,121 at C10; 996,210 rows at S1) | FK target in other ecom DBs as `user_id` (orders, gifts, wallet) — to verify |
| `users_user.username` | varchar(36) | UUID for 996,206 rows + 4 non-UUID legacy rows (len 11/17/18) = 996,210 [exact, same query as S1] | **primary cross-service user reference** ("user_reference"); used by migration + token-rotation logs; likely Cognito username |
| `users_user.sub` | varchar | only 1 non-null | Cognito sub — effectively unused; don't join on it |
| `users_user.legacy_auth_code` | varchar[] | 57,746 users with 1 code, 11 with 2 | legacy YouGotaGift platform user ids (pre-2023) |
| `users_user.google_id/apple_id/facebook_id` | varchar | 114,321 / 65,320 / 59,977 non-null (A3, count() includes ''); non-empty 114,321 / 65,320 / 4,960 (C2); none for signups after Nov 2024 | social IdP ids (PII-ish) |
| `users_secondaryuseridentity.username` | uuid | unique | alternate identity reference |
| `users_migratedtransactionlog.user_reference` | varchar(36) UUID | 171,232 rows, 100% match users_user.username | legacy migration |
| `core_blacklisteduserdetail.reference_id` | varchar | set mostly for ecom_gifts/orders/groupgift/atwork/legacy sources | ids in those services |
| `core_blacklisteduserdetail.source` | varchar | ecom_users, ecom_legacy, ecom_gifts, ecom_orders, ecom_groupgift, atwork | service names = other DBs |
| `kafka_*.data->>'event_id'`, producer `event_id` uuid | uuid | — | Kafka events shared with ecom_order/ecom_gift/groupgift/atwork/legacy |
| `users_cognitoissuedtokens.jti`, `device_signature` | varchar/text | device_signature only on app tokens | token/device ids (sensitive); device_signature may match `user_device_id` blacklist values / app_device_id in ecom_order Kafka payloads |
| `country_of_residence` | ISO-2 | SA, AE, QA, KW, IN, … (`OT` = other) | dimension join |

## 9. PII (column names only)

- `users_user`: password, username (pseudonymous UUID), email, phone_number, name, middle_name, nickname, birthdate, gender, ip_address, location, picture, facebook_id, apple_id, google_id, sub, device, legacy_auth_code, country_of_residence (quasi).
- `users_secondaryuseridentity`: alternate_email, username.
- `users_passwordhistory.password_hash`; `users_userauthlegacysignaturepreference.auth_signature, auth_code`.
- `users_cognitoissuedtokens`: jti, token_hash, device_signature, request_meta (IP_ADDRESS, USER_AGENT, TOKEN_DERIVATIVES).
- `users_tokenrotatedusers.device_signature`, `users_migratedtransactionlog.legacy_auth_code`.
- `notifications_twofactorauth`: email, phone_number; `notifications_twofactorauthverification.auth_code`.
- `core_blacklisteduserdetail.value, remarks`; `core_whitelisteduserdetail.value`.
- `kafka_clients_*.data/payload` (contain blacklisted identifiers).
- `otp_totp_totpdevice.key`, `otp_static_statictoken.token`, `two_factor_phonedevice.number,key`, `users_webauthncredentialmodel.public_key,credential_id`.
- `core_remoteurlconfig.api_key, api_secret, url` (secrets); `core_siteconfiguration.config` (may hold automation accounts); `django_session.session_data`; `django_admin_log.object_repr, change_message`.

## 10. Data Quality

- `users_user.last_login` is abandoned (94% NULL, only 27 values after 2023) — use `users_cognitoissuedtokens` for login activity.
- `users_user.platform` stuck at `other` for all users since 2024; `language_code` 94% NULL; `device` constant empty string; `app_version` 100% NULL; `ip_address` only populated for legacy/2023 users.
- `users_user.sub` 1 non-null — Cognito sub not stored; `username` is the join key.
- `date_joined` for 2023 includes ~169k legacy-migrated accounts (migration May–Oct 2023), inflating 2023 "signups".
- `gender`: NULL 131,692 + empty string 91,664 (two null encodings) + 1 'other'.
- `birthdate` is varchar with two null encodings ('' 494,137, NULL 132,525). The 369,553 well-formed values are `0000/DD/MM`, a birthday with no year: 369,420 have a valid day+month. Usable for birthday month and day, **not for age**. Beware the default-looking spike at `0000/01/01` (9,940) and the elevated day 1 (27,205). The unusual order (day before month) must be parsed explicitly. Do not cast the value to date.
- **`users_user.type` is a dead field after Oct 2023.** Every signup from Nov 2023 is `conventional_user` (2024 269,064/269,064; 2025 281,274/281,274; 2026 208,609/208,609) [exact, C2]. It follows the same failure pattern as `platform = 'other'`.
- **Social IdP ids stopped being written in Nov 2024.** `google_id`, `apple_id` and `facebook_id` are empty for every signup from Dec 2024: 2025 0/0/0, 2026 0/0/0, against 2024 60,949 / 35,514 / 999 [exact, C2/C3]. Social-login share is therefore unmeasurable since Dec 2024. `facebook_id` also carries empty strings: 59,977 non-null but only 4,960 non-empty.
- **`is_app_user` changed definition or flow in Aug 2024** (18% of Jun 2024 signups, 84% of Aug 2024 signups) [exact, C3]. Do not trend it across that month.
- `is_active`/`is_enabled` near-constant; the real state is `is_deleted`. No deleted_at timestamp (modified_on as proxy).
- OTP tables purged to ~31 days — no history for trend metrics; must snapshot daily if needed.
- `notifications_twofactorauthverification.modified_on` differs from `created_on` on **every** row (13,688 false / 54,780 true), but always by **less than 1 s** (max 0.011 s, avg 0.00003 s). The two stamps are two `now()` calls at insert. `is_valid` is flipped later without bumping `modified_on` (consistent with `queryset.update()`), and `auth_code` is always NULL, so **verification time is unobservable**. Use the next request's `created_on` for resend timing.
- `whatsapp_delivery` is never true: all 397 `whatsapp` requests have all three delivery flags false, and all 27,434 `whatsappsms` requests have only `sms_delivery`=true. WhatsApp delivery is not tracked by any flag.
- `users_useridentityactivitylog.actor_id` is NULL on all 3,912 `updated_phone_number` rows (actor never recorded). The other activities always have an actor.
- `users_cognitoissuedtokens`: WEB tokens (30-day life) exist only from 2026-08-29 20h, which is likely an expiry purge, so web login history is limited to ~30 days. `device_signature` is NULL for all WEB and UNACCOUNTED tokens.
- `users_user.id` gaps: 37–62% of ids missing per month in 2024 Jan–2025 Apr, near 0 after 2025 Jun (§5). Row counts are not comparable across that cutover.
- Kafka ecom_order consumer: stuck rows use the old payload schema and have NULL completed_timestamp; errors are not captured.
- `kafka_clients_blacklistuserproducerlog.payload` is Python-repr text, not JSON (cast fails).
- Kafka consumer `error_data` empty even for stuck rows — errors not captured.
- reltuples stale/-1 for several tables (users_migratedtransactionlog, users_passwordhistory, users_tokenrotatedusers, django_migrations, two_factor_phonedevice); `notifications_communicationcountryconfigs` reltuples 0 but has 14 rows. pg_stat n_live_tup 0 everywhere (replica stats).
- Dead / empty tables: `users_webauthncredentialmodel`, `otp_static_staticdevice`, `otp_static_statictoken`, `two_factor_phonedevice` (0 rows); frozen: `users_migratedtransactionlog` (2023), `users_tokenrotatedusers` (2023–24), `users_userauthlegacysignaturepreference` (no timestamps).
- Minor integrity: 9 tokens belong to soft-deleted users; 9 active secondary identities on deleted users; 0 orphaned activity-log rows.
- Snapshot drift: live replica counts moved during profiling (users 996,189 → 996,216; tokens 59,828 → 59,869; OTP 68,407 → 68,468). Headline numbers use S1.
- Duplicated concepts: blacklist (`core_blacklisteduserdetail`) vs `users_promotionaldomainblacklist`; captcha config exists as `core.captchav3configurations` in admin history (renamed model).

## 11. Open Questions

1. ~~Semantics of `is_valid`~~ **Resolved (§7)**: true is the accepted, unsuperseded code; false is superseded by a resend or unused. Still open: is there a separate wrong-code attempt counter (e.g. in the VERIFY_OTP service)? `requested_attempts` is always 3 (config, not observed).
2. Why do 2fa_account_verification chains fail 34% of the time and resend at a median of 77 s? Delivery latency on the email provider, or UX (auto-resend)? Delivery receipts would need MAIL_ENGINE or SMS_ENGINE logs.
3. What changed in the signup flow in **May 2025** that ended the 37–62% id-sequence loss? A purge job for unverified signups, or a change in transaction/rollback handling? This is needed to normalise signup trends.
4. The 1,298 stuck `ecom_order` Kafka events all have the old payload schema (`guest_id`, no `reference_id`/`mark_as_fraud`). Can they be replayed or migrated, and were those identities ever blacklisted?
5. What drove the 2026-09-22 → 25 acquisition push, and why did OTP resends spike only on Sep 22–23 (a provider incident or bot traffic)?
6. Which column do other YGG DBs use as the user key: numeric `id` or UUID `username`?
7. Is `is_app_user` the "signed up from app" flag or "ever used app"? It covers about 80% of signups, but only since Aug 2024 (18% → 84% between Jun and Aug 2024). What changed then? A related question: where is signup method recorded now that `type` (dead since Nov 2023) and the social ids (dead since Dec 2024) are no longer written? Probably Cognito or the IdP side.
8. Where are logins recorded before 2026-07-13 (app) / 2026-08-29 (web)? Are expired WEB tokens purged, and on what schedule?
9. What does `is_guest` mean on blacklist entries originating from `ecom_users` (blacklisted before account creation)?
10. Is the blacklist enforced at action time downstream? 752 email and 553 mobile blacklist entries belong to fully live accounts here (903 users). **Login is demonstrably not blocked**: 12 of those users received 18 tokens after being blacklisted. Do ecom_order and ecom_gift check at checkout? This needs a cross-DB check of orders placed by these users after their blacklist date.
11. `birthdate` is `0000/DD/MM` (a birthday with no year). Is the year deliberately not collected (a privacy choice), or stripped? Is `0000/01/01` a UI default? Is the field used anywhere for birthday campaigns today?
12. Are the Jun 23–24 and Aug 25 2026 bulk blacklist imports (domain list, email list) a one-off clean-up or a recurring process? Who owns the source lists?
13. Residence-vs-login mismatches (for example 183 SA residents logging in from Spain, 90 AE residents from Brazil, mostly one token each): VPN, bulk account farming, or travel? Worth cross-checking against orders and gift redemptions downstream.
14. The legacy-sync producer stream (7,031 messages) still publishes to the legacy platform in 2026. Is the legacy consumer still live?

## Appendix: SQL provenance

All run via `atlasq.sh ygag_ecom_users_db <rows>` on 2026-09-29.

```sql
-- A1 table volumes [est]
select c.relname, c.reltuples::bigint est, pg_total_relation_size(c.oid) bytes from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname='public' and c.relkind='r' order by 1;

-- A2 exact counts (one union query)
select 'blacklist',count(*) from core_blacklisteduserdetail union all select '2fa',count(*) from notifications_twofactorauth union all select 'cognito_tokens',count(*) from users_cognitoissuedtokens union all select 'secondary_identity',count(*) from users_secondaryuseridentity union all select 'activitylog',count(*) from users_useridentityactivitylog union all select 'migratedtxlog',count(*) from users_migratedtransactionlog /* … same pattern for every small table */;

-- A3 users_user totals & flags [exact]
select count(*) n, min(id), max(id), count(*) filter (where is_active) active, count(*) filter (where is_deleted) deleted, count(*) filter (where is_app_user) app, count(*) filter (where email_verified) ev, count(sub) sub_nn, count(last_login) ll_nn, count(apple_id), count(google_id), count(facebook_id), count(*) filter (where cardinality(legacy_auth_code)>0) legacy_nn from users_user;

-- A4 time ranges
select to_char(min(date_joined),'YYYY Mon DD'), to_char(max(date_joined),'YYYY Mon DD'), to_char(min(last_login),'YYYY Mon DD'), to_char(max(last_login),'YYYY Mon DD HH24') from users_user;

-- A5 monthly signups
select to_char(date_trunc('month',date_joined),'YYYY Mon') m, count(*) signups, count(*) filter (where is_app_user) app, count(*) filter (where is_deleted) deleted from users_user where date_joined >= '2025-03-01' group by date_trunc('month',date_joined) order by date_trunc('month',date_joined);
select extract(year from date_joined)::int y, count(*) from users_user group by 1 order by 1;

-- A6 monthly soft deletions (proxy)
select to_char(date_trunc('month',modified_on),'YYYY Mon') m, count(*) from users_user where is_deleted and modified_on>='2025-03-01' group by date_trunc('month',modified_on) order by date_trunc('month',modified_on);

-- A7 categoricals
select type, count(*) from users_user group by 1 order by 2 desc;
select platform, count(*) from users_user group by 1 order by 2 desc;
select country_of_residence, count(*) from users_user group by 1 order by 2 desc limit 25;
select extract(year from last_login)::int y, count(*) from users_user group by 1 order by 1;
select is_active, is_enabled, is_deleted, count(*) from users_user group by 1,2,3 order by 4 desc;

-- A8 identity activity
select activity, count(*), count(actor_id), count(*) filter (where actor_id=user_id) self, to_char(min(timestamp),'YYYY Mon DD'), to_char(max(timestamp),'YYYY Mon DD') from users_useridentityactivitylog group by 1 order by 2 desc;

-- A9 OTP flows & validity
select auth_type, source, count(*) from notifications_twofactorauth group by 1,2 order by 3 desc;
select t.source, t.auth_type, count(*) n, count(*) filter (where v.is_valid) valid_now from notifications_twofactorauth t join notifications_twofactorauthverification v on v.reference_id_id=t.id group by 1,2 order by 3 desc;
select is_valid, count(*) from notifications_twofactorauthverification group by 1;

-- A10 OTP repeat requesters (aggregate only)
with r as (select coalesce(email,'')||'|'||coalesce(phone_number,'') k, source, count(*) c from notifications_twofactorauth group by 1,2)
select source, case when c=1 then '1' when c=2 then '2' when c<=5 then '3-5' when c<=10 then '6-10' else '>10' end b, count(*) from r group by 1,2;
select source, count(*) n, count(distinct coalesce(email,'')||'|'||coalesce(phone_number,'')) recipients from notifications_twofactorauth group by 1;

-- A11 OTP daily + incident
select to_char(date_trunc('day',created_on),'Mon DD') d, count(*) from notifications_twofactorauth group by date_trunc('day',created_on) order by date_trunc('day',created_on);
select to_char(date_trunc('day',t.created_on),'Mon DD') d, t.source, count(*), count(*) filter (where v.is_valid) from notifications_twofactorauth t join notifications_twofactorauthverification v on v.reference_id_id=t.id where t.created_on >= '2026-09-19' group by date_trunc('day',t.created_on),2 order by 1,2;
select count(*) from users_user where date_joined >= (select min(created_on) from notifications_twofactorauth);

-- A12 tokens
select user_platform, count(*), count(distinct user_id) from users_cognitoissuedtokens group by 1;
select count(distinct user_id), count(*), count(distinct device_signature) from users_cognitoissuedtokens;
select to_char(date_trunc('month',created_on),'YYYY Mon'), count(*) from users_cognitoissuedtokens group by date_trunc('month',created_on) order by date_trunc('month',created_on);
select request_meta->>'COUNTRY', count(*) from users_cognitoissuedtokens group by 1 order by 2 desc limit 15;
with u as (select user_id, count(*) c from users_cognitoissuedtokens group by 1) select case when c=1 then '1' when c<=3 then '2-3' when c<=10 then '4-10' else '>10' end, count(*) from u group by 1;

-- A13 blacklist
select type, count(*), count(*) filter (where not is_removed), count(*) filter (where is_guest) from core_blacklisteduserdetail group by rollup(1);
select source, count(*), count(*) filter (where not is_removed) from core_blacklisteduserdetail group by 1;
select to_char(date_trunc('month',created_on),'YYYY Mon'), count(*) from core_blacklisteduserdetail where created_on>='2025-03-01' group by date_trunc('month',created_on) order by date_trunc('month',created_on);

-- A14 kafka
select data->>'event_type', service_name, status, count(*) from kafka_clients_blacklistuserconsumerdatalog group by 1,2,3;
select extract(year from start_timestamp)::int, status, count(*) from kafka_clients_blacklistuserconsumerdatalog where service_name='ecom_order' group by 1,2;
select status, count(*), count(error) from kafka_clients_blacklistuserproducerlog group by 1;

-- A15 migration & id gaps
select m.creation, m.request_status, count(*), count(u.id) matched from users_migratedtransactionlog m left join users_user u on u.username=m.user_reference group by 1,2;
select extract(year from date_joined)::int y, min(id), max(id), count(*), max(id)-min(id)+1-count(*) gap from users_user group by 1 order by 1;
select (username ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'), length(username), count(*) from users_user group by 1,2;

-- A16 admin log
select action_flag, ct.app_label||'.'||ct.model, count(*) from django_admin_log a left join django_content_type ct on ct.id=a.content_type_id group by 1,2 order by 3 desc;

-- A17 integrity
select count(*), count(*) filter (where u.is_deleted) from users_cognitoissuedtokens t join users_user u on u.id=t.user_id;
select count(*) filter (where s.is_deleted=false and u.is_deleted) from users_secondaryuseridentity s join users_user u on u.id=s.user_id;

-- ===== v2 additions (critic round 1), all run 2026-09-29 =====

-- S1 single-snapshot headline counts [exact]
select (select count(*) from users_user) users, (select count(*) from users_cognitoissuedtokens) tokens, (select count(*) from notifications_twofactorauth) otp, (select count(*) from notifications_twofactorauthverification) verif, (select count(*) filter (where is_valid) from notifications_twofactorauthverification) valid, (select count(*) filter (where username ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$') from users_user) uuid_users, (select count(*) filter (where username !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$') from users_user) non_uuid, (select count(distinct user_id) from users_cognitoissuedtokens), (select count(distinct device_signature) from users_cognitoissuedtokens);

-- B1 verification timestamps (modified_on vs created_on)
select v.is_valid, count(*), count(*) filter (where v.modified_on<>v.created_on) diff, count(*) filter (where v.modified_on-v.created_on >= interval '1 second') ge1s, max(extract(epoch from v.modified_on-v.created_on)), avg(extract(epoch from v.modified_on-v.created_on)), count(*) filter (where v.created_on - t.created_on > interval '1 second') from notifications_twofactorauthverification v join notifications_twofactorauth t on t.id=v.reference_id_id group by 1;

-- B2 is_valid lead() test
with r as (select t.source, v.is_valid, t.created_on, lead(t.created_on) over (partition by coalesce(t.email,'')||'|'||coalesce(t.phone_number,''), t.source order by t.created_on, t.id) nxt from notifications_twofactorauth t join notifications_twofactorauthverification v on v.reference_id_id=t.id)
select source, is_valid, count(*), count(*) filter (where nxt is null) last_in_seq, count(*) filter (where nxt - created_on <= interval '10 minutes') next_10m, count(*) filter (where nxt - created_on > interval '10 minutes') next_later from r group by 1,2;

-- B3 final sign_up email code vs registration (in-DB PII join, aggregate only)
with r as (select t.email, t.created_on, v.is_valid, lead(t.id) over (partition by t.email order by t.created_on, t.id) nxt from notifications_twofactorauth t join notifications_twofactorauthverification v on v.reference_id_id=t.id where t.source='sign_up' and t.auth_type='email' and t.email is not null)
select r.is_valid, count(*), count(u.id) now_registered from r left join users_user u on lower(u.email)=lower(r.email) where nxt is null group by 1;

-- B4 resend gaps
with r as (select t.source, t.created_on, lag(t.created_on) over (partition by coalesce(t.email,'')||'|'||coalesce(t.phone_number,''), t.source order by t.created_on, t.id) prv from notifications_twofactorauth t)
select source, count(*) filter (where prv is not null), count(*) filter (where created_on-prv<=interval '10 minutes'), percentile_cont(0.5) within group (order by extract(epoch from created_on-prv)) filter (where created_on-prv<=interval '10 minutes'), percentile_cont(0.25) within group (order by extract(epoch from created_on-prv)) filter (where created_on-prv<=interval '10 minutes'), percentile_cont(0.75) within group (order by extract(epoch from created_on-prv)) filter (where created_on-prv<=interval '10 minutes') from r group by 1;

-- B5 resend chains (gap <=10 min)
with r as (select t.source, coalesce(t.email,'')||'|'||coalesce(t.phone_number,'') k, t.created_on, v.is_valid, case when t.created_on - lag(t.created_on) over (partition by coalesce(t.email,'')||'|'||coalesce(t.phone_number,''), t.source order by t.created_on, t.id) <= interval '10 minutes' then 0 else 1 end newc from notifications_twofactorauth t join notifications_twofactorauthverification v on v.reference_id_id=t.id),
c as (select *, sum(newc) over (partition by k, source order by created_on rows unbounded preceding) cid from r),
ch as (select source, k, cid, count(*) codes, bool_or(is_valid) any_valid, extract(epoch from max(created_on)-min(created_on)) span from c group by 1,2,3)
select source, count(*), count(*) filter (where codes>=2), count(*) filter (where codes>=3), count(*) filter (where codes>=5), avg(codes), percentile_cont(0.5) within group (order by span) filter (where codes>=2), count(*) filter (where not any_valid) from ch group by 1;

-- B6 daily signups + daily OTP resends around Sep 22
select to_char(date_trunc('day',date_joined),'Mon DD'), count(*) from users_user where date_joined>='2026-09-15' group by date_trunc('day',date_joined) order by date_trunc('day',date_joined);
with r as (select t.source, t.created_on, v.is_valid, case when t.created_on - lag(t.created_on) over (partition by coalesce(t.email,'')||'|'||coalesce(t.phone_number,''), t.source order by t.created_on, t.id) <= interval '10 minutes' then 1 else 0 end is_resend from notifications_twofactorauth t join notifications_twofactorauthverification v on v.reference_id_id=t.id)
select to_char(date_trunc('day',created_on),'Mon DD'), source, count(*), sum(is_resend), count(*) filter (where is_valid) from r where created_on>='2026-09-15' and source in ('sign_up','2fa_account_verification','sign_in') group by date_trunc('day',created_on),2 order by date_trunc('day',created_on),2;

-- B7 id gaps by join month
select to_char(date_trunc('month',date_joined),'YYYY Mon'), min(id), max(id), count(*), max(id)-min(id)+1-count(*) gap, round(100.0*(max(id)-min(id)+1-count(*))/(max(id)-min(id)+1),1) from users_user where date_joined>='2023-01-01' group by date_trunc('month',date_joined) order by date_trunc('month',date_joined);
select case when date_joined<'2023-01-01' then 'pre2023' else extract(year from date_joined)::text end, min(id), max(id), count(*) from users_user group by 1;
select extract(year from action_time)::int, count(*) filter (where a.action_flag=3 and ct.app_label='users' and ct.model='user'), count(distinct a.user_id) filter (where a.action_flag=3 and ct.app_label='users' and ct.model='user') from django_admin_log a left join django_content_type ct on ct.id=a.content_type_id group by 1;
select count(*), count(distinct a.user_id) from django_admin_log a join django_content_type ct on ct.id=a.content_type_id where a.action_flag=3 and ct.app_label='users' and ct.model='user';

-- B8 OTP delivery flags
select auth_type, email_delivery, sms_delivery, whatsapp_delivery, count(*) from notifications_twofactorauth group by 1,2,3,4;

-- B9 OTP hour of day (Asia/Dubai)
select extract(hour from created_on at time zone 'Asia/Dubai')::int, count(*) filter (where source='sign_up'), count(*) filter (where source='sign_in'), count(*) filter (where source='2fa_account_verification'), count(*) from notifications_twofactorauth group by 1 order by 1;

-- B10 OTP recipient country prefix (aggregated CASE on prefix; no raw numbers returned)
select case when phone_number like '+966%' then 'SA' when phone_number like '+971%' then 'AE' when phone_number like '+974%' then 'QA' when phone_number like '+965%' then 'KW' when phone_number like '+973%' then 'BH' when phone_number like '+968%' then 'OM' when phone_number like '+91%' then 'IN' when phone_number like '+20%' then 'EG' when phone_number like '+962%' then 'JO' when phone_number like '+44%' then 'GB' when phone_number like '+1%' then 'US/CA' when phone_number like '+92%' then 'PK' when phone_number like '+63%' then 'PH' when phone_number like '+%' then 'other' else 'no-plus' end, count(*), count(distinct phone_number), count(*) filter (where source='sign_up') from notifications_twofactorauth where phone_number is not null and phone_number<>'' group by 1;

-- B11 tokens: device sharing, OS, browser, platform, lifetime
with d as (select device_signature, count(distinct user_id) u, count(*) t from users_cognitoissuedtokens where device_signature is not null and device_signature<>'' group by 1) select case when u=1 then '1' when u<=3 then '2-3' when u<=10 then '4-10' else '>10' end, count(*), sum(t), sum(u) from d group by 1;
select user_platform, count(*) filter (where device_signature is null or device_signature=''), count(*) from users_cognitoissuedtokens group by 1;
select request_meta->>'OS_TYPE', count(*), count(distinct user_id) from users_cognitoissuedtokens group by 1 order by 2 desc;
select request_meta->>'BROWSER', count(*) from users_cognitoissuedtokens group by 1 order by 2 desc limit 20;
select request_meta->>'PLATFORM', request_meta->>'IS_BOT', count(*) from users_cognitoissuedtokens group by 1,2 order by 3 desc;
select to_char(date_trunc('month',created_on),'YYYY Mon'), count(*), round(avg(extract(epoch from expires_at-created_on))/86400,1), round(min(extract(epoch from expires_at-created_on))/86400,1), round(max(extract(epoch from expires_at-created_on))/86400,1) from users_cognitoissuedtokens group by date_trunc('month',created_on);
select to_char(date_trunc('month',created_on),'YYYY Mon'), user_platform, round(extract(epoch from expires_at-created_on)/86400), count(*) from users_cognitoissuedtokens group by 1,2,3;
select to_char(min(created_on) filter (where round(extract(epoch from expires_at-created_on)/86400)=30),'YYYY Mon DD HH24'), count(*) filter (where round(extract(epoch from expires_at-created_on)/86400)=30) from users_cognitoissuedtokens;

-- B12 blacklist overlap with registered accounts (in-DB joins, aggregate only)
select b.is_removed, count(*), count(u.id), count(u.id) filter (where u.is_deleted), count(u.id) filter (where u.date_joined > b.created_on) from core_blacklisteduserdetail b left join users_user u on lower(u.email)=lower(b.value) where b.type='user_email' group by 1;
select b.is_removed, count(*), count(u.id), count(u.id) filter (where u.is_deleted) from core_blacklisteduserdetail b left join users_user u on u.phone_number=b.value where b.type='user_mobile_no' group by 1;
select 'email', count(u.id), count(u.id) filter (where u.is_active and u.is_enabled and not u.is_deleted), count(u.id) filter (where u.trusted_user) from core_blacklisteduserdetail b join users_user u on lower(u.email)=lower(b.value) where not b.is_removed and b.type='user_email'
union all select 'mobile', count(u.id), count(u.id) filter (where u.is_active and u.is_enabled and not u.is_deleted), count(u.id) filter (where u.trusted_user) from core_blacklisteduserdetail b join users_user u on u.phone_number=b.value where not b.is_removed and b.type='user_mobile_no';
-- [sample 5%]
with u as (select id, lower(split_part(email,'@',2)) dom, is_deleted from users_user tablesample system (5) where email like '%@%'), b as (select distinct lower(value) dom from core_blacklisteduserdetail where type='user_domain' and not is_removed)
select count(*), count(*) filter (where u.dom in (select dom from b)), count(*) filter (where u.dom in (select dom from b) and not u.is_deleted) from u;

-- B13 demographics
select gender, count(*) from users_user group by 1;
select case when birthdate is null then 'null' when birthdate='' then 'empty' when birthdate ~ '^\d{4}-\d{2}-\d{2}$' then 'iso' else 'other len '||length(birthdate) end, count(*) from users_user group by 1;
select translate(birthdate,'0123456789','NNNNNNNNNN'), count(*) from users_user where length(birthdate)=10 group by 1;
select 'p1', min(substr(birthdate,1,4)::int), max(substr(birthdate,1,4)::int), count(distinct substr(birthdate,1,4)) from users_user where birthdate ~ '^\d{4}/\d{2}/\d{2}$' /* + same for substr(6,2), substr(9,2) */;  -- superseded by C1 (field-level distributions)
select count(*) filter (where custom_profile_img) from users_user;

-- B14 identity activity actors; CS edits on users_user
select activity, count(*), count(actor_id), count(*) filter (where actor_id=user_id), count(*) filter (where actor_id<>user_id) from users_useridentityactivitylog group by 1;
select count(*) filter (where modified_by_id is not null), count(*) filter (where modified_by_id<>id), count(*) filter (where created_by_id<>id), count(*) filter (where modified_by_id<>id and is_deleted) from users_user;

-- B15 kafka latency + stuck payload schema
select service_name, status, count(*), count(completed_timestamp), avg(extract(epoch from completed_timestamp-start_timestamp)), max(extract(epoch from completed_timestamp-start_timestamp)), percentile_cont(0.95) within group (order by extract(epoch from completed_timestamp-start_timestamp)) from kafka_clients_blacklistuserconsumerdatalog group by 1,2;
select status, count(*), count(completed_timestamp), avg(extract(epoch from completed_timestamp-start_timestamp)), max(extract(epoch from completed_timestamp-start_timestamp)) from kafka_clients_serviceinternalrefetchconsumerdatalog group by 1;
select status, (select string_agg(k,',' order by k) from jsonb_object_keys(data->'data') k), count(*) from kafka_clients_blacklistuserconsumerdatalog where service_name='ecom_order' group by 1,2;

-- B16 blacklist remarks classes (keyword counts only; no text returned)
select case when remarks is null or btrim(remarks)='' then 'empty' when remarks ~* 'disposable|temp' then 'disposable' when remarks ~* 'fraud|scam|stolen|chargeback|cbk' then 'fraud' when remarks ~* 'abus|misuse|multiple|promo|referral|coupon' then 'abuse' when remarks ~* 'bot|spam|attack' then 'bot/spam' else 'other' end, count(*), round(avg(length(remarks))) from core_blacklisteduserdetail group by 1;
select count(distinct remarks), count(*) filter (where remarks ~* 'request|ticket|jira|zendesk|freshdesk'), count(*) filter (where remarks ~* 'bulk|upload|sheet|csv|list'), count(*) filter (where remarks ~* 'domain'), count(*) filter (where remarks ~* 'suspicious|suspect|risk') from core_blacklisteduserdetail where remarks is not null and btrim(remarks)<>'';
with r as (select remarks, count(*) c from core_blacklisteduserdetail where remarks is not null and btrim(remarks)<>'' group by 1) select case when c=1 then '1' when c<=10 then '2-10' when c<=100 then '11-100' else '>100' end, count(*), sum(c) from r group by 1;

-- ===== v3 additions (critic round 2), all run 2026-09-29 =====

-- C1 birthdate field distributions ('0000/DD/MM') [exact]
select substr(birthdate,6,2)::int f2_day, count(*) from users_user where birthdate ~ '^\d{4}/\d{2}/\d{2}$' group by 1 order by 1;
select substr(birthdate,9,2)::int f3_month, count(*) from users_user where birthdate ~ '^\d{4}/\d{2}/\d{2}$' group by 1 order by 1;
select case when date_joined<'2023-01-01' then 'pre2023' else extract(year from date_joined)::text end y, count(*) n,
 count(*) filter (where birthdate ~ '^\d{4}/\d{2}/\d{2}$') wf,
 count(*) filter (where birthdate ~ '^\d{4}/\d{2}/\d{2}$' and substr(birthdate,9,2)::int between 1 and 12 and substr(birthdate,6,2)::int between 1 and 31) valid_md,
 count(*) filter (where birthdate ~ '^\d{4}/\d{2}/\d{2}$' and substr(birthdate,9,2)::int between 1 and 12 and substr(birthdate,6,2)::int between 1 and 31 and not is_deleted) valid_live,
 count(*) filter (where birthdate = '0000/01/01') jan1,
 count(*) filter (where substr(birthdate,1,4)<>'0000' and birthdate ~ '^\d{4}/\d{2}/\d{2}$') nonzero_year
from users_user group by rollup(1) order by 1;

-- C2 signup type and social ids by signup year [exact]
select case when date_joined<'2023-01-01' then 'pre2023' else extract(year from date_joined)::text end y, count(*) n, count(nullif(google_id,'')) g, count(nullif(apple_id,'')) a, count(nullif(facebook_id,'')) f,
 count(*) filter (where coalesce(nullif(google_id,''),nullif(apple_id,''),nullif(facebook_id,'')) is not null) any_social, count(*) filter (where is_app_user) app
from users_user group by 1 order by 1;
select case when date_joined<'2023-01-01' then 'pre2023' else extract(year from date_joined)::text end y, type, count(*) from users_user group by 1,2 order by 1,3 desc;

-- C3 monthly social-id / is_app_user / type share (2023 Jan – 2025 Jun, two runs split at 2024-09-01)
select to_char(date_trunc('month',date_joined),'YYYY Mon') m, count(*) n, count(*) filter (where coalesce(nullif(google_id,''),nullif(apple_id,''),nullif(facebook_id,'')) is not null) social, count(*) filter (where is_app_user) app, count(*) filter (where type<>'conventional_user') type_social
from users_user where date_joined>='2023-01-01' and date_joined<'2025-07-01' group by date_trunc('month',date_joined) order by date_trunc('month',date_joined);

-- C4 token issuance: new-user (joined <=1 day before) vs returning [exact]
select to_char(date_trunc('month',t.created_on),'YYYY Mon') m, t.user_platform, count(*) toks,
 count(*) filter (where t.created_on - u.date_joined <= interval '1 day') new_1d,
 count(*) filter (where t.created_on - u.date_joined > interval '1 day') ret_toks,
 count(distinct t.user_id) filter (where t.created_on - u.date_joined > interval '1 day') ret_users,
 count(*) filter (where u.id is null) nouser
from users_cognitoissuedtokens t left join users_user u on u.id=t.user_id
group by date_trunc('month',t.created_on), 2 order by date_trunc('month',t.created_on), 2;

-- C5 residence vs login country pairs (aggregate; countries only) [exact]
select u.country_of_residence res, t.request_meta->>'COUNTRY' login_c, count(*) toks, count(distinct t.user_id) users
from users_cognitoissuedtokens t join users_user u on u.id=t.user_id group by 1,2 having count(*)>=40 order by 3 desc;

-- C6 residence mismatch rates for SA/AE [exact]
with x as (select u.country_of_residence res, t.request_meta->>'COUNTRY' c, t.user_platform p, (t.created_on-u.date_joined<=interval '1 day') is_new
 from users_cognitoissuedtokens t join users_user u on u.id=t.user_id where u.country_of_residence in ('SA','AE'))
select res, count(*) toks,
 count(*) filter (where c=case res when 'SA' then 'Saudi Arabia' else 'United Arab Emirates' end) home,
 count(*) filter (where c in ('Saudi Arabia','United Arab Emirates','Qatar','Kuwait','Oman','Bahrain') and c<>case res when 'SA' then 'Saudi Arabia' else 'United Arab Emirates' end) other_gcc,
 count(*) filter (where c is not null and c not in ('Saudi Arabia','United Arab Emirates','Qatar','Kuwait','Oman','Bahrain')) out_gcc,
 count(*) filter (where c is null) nullc,
 count(*) filter (where c is not null and c not in ('Saudi Arabia','United Arab Emirates','Qatar','Kuwait','Oman','Bahrain') and is_new) out_gcc_new,
 count(*) filter (where c is not null and c not in ('Saudi Arabia','United Arab Emirates','Qatar','Kuwait','Oman','Bahrain') and p='WEB') out_gcc_web
from x group by 1;

-- C6b blacklist spikes: month x source x type, and bulk-import days [exact]
select to_char(date_trunc('month',created_on),'YYYY Mon') m, source, type, count(*), count(*) filter (where is_guest) guest, count(distinct date_trunc('day',created_on)) days, count(distinct created_by_id) creators, max(cnt_day) maxday
from (select *, count(*) over (partition by date_trunc('day',created_on), source, type) cnt_day from core_blacklisteduserdetail where created_on>='2026-05-01') x
group by date_trunc('month',created_on),2,3 order by date_trunc('month',created_on),4 desc;
select to_char(date_trunc('day',created_on),'YYYY Mon DD') d, source, type, count(*), count(distinct date_trunc('minute',created_on)) minutes, count(*) filter (where remarks is null or btrim(remarks)='') empty_rem, count(distinct remarks) distinct_rem
from core_blacklisteduserdetail where created_on>='2026-06-01' and created_on<'2026-09-01' and source='ecom_users' group by date_trunc('day',created_on),2,3 having count(*)>=40 order by 4 desc;

-- C7 producer log: payload shape / flags (regex on python-repr text; categorical keys and flags only) + reconciliation
select (select string_agg(m[1],',' order by m[1]) from regexp_matches(payload, '''([a-z_]+)'':', 'g') m) keys, count(*) from kafka_clients_blacklistuserproducerlog group by 1 order by 2 desc;
select case when payload like '%''fraud_type''%' then 'legacy_sync' else 'blacklist_event' end shape,
 substring(payload from '''fraud_type'': ''([a-z_]+)''') ftype, substring(payload from '''is_removed'': (True|False)') is_rem,
 substring(payload from '''mark_as_fraud'': (True|False)') maf, substring(payload from '''is_guest'': (True|False)') guest,
 count(*), to_char(min(created_on),'YYYY Mon DD'), to_char(max(created_on),'YYYY Mon DD')
from kafka_clients_blacklistuserproducerlog group by 1,2,3,4,5 order by 6 desc;
select case when payload like '%''fraud_type''%' then 'legacy_sync' else 'blacklist_event' end shape, extract(year from created_on)::int y, count(*) from kafka_clients_blacklistuserproducerlog group by 1,2;
select source, count(*) total, count(*) filter (where created_on>='2024-04-15') since_apr24, count(*) filter (where created_on>='2024-04-15' and is_removed) removed_since from core_blacklisteduserdetail group by rollup(1);

-- C8 tokens issued after blacklist entry (UNION of email and mobile joins; a single OR join times out) [exact]
with m as (
 select 'email' k, b.source, b.id bid, b.created_on bc, u.id uid from core_blacklisteduserdetail b join users_user u on lower(u.email)=lower(b.value) where b.type='user_email' and not b.is_removed and not u.is_deleted
 union all
 select 'mobile', b.source, b.id, b.created_on, u.id from core_blacklisteduserdetail b join users_user u on u.phone_number=b.value where b.type='user_mobile_no' and not b.is_removed and not u.is_deleted)
select m.k, m.source, count(distinct m.uid), count(distinct t.user_id), count(t.id), count(t.id) filter (where t.created_on>m.bc), count(distinct t.user_id) filter (where t.created_on>m.bc)
from m left join users_cognitoissuedtokens t on t.user_id=m.uid group by rollup(1,2);
-- deduplicated per user (earliest active blacklist entry)
with m as (/* same union, selecting bc, uid */ select b.created_on bc, u.id uid from core_blacklisteduserdetail b join users_user u on lower(u.email)=lower(b.value) where b.type='user_email' and not b.is_removed and not u.is_deleted
 union all select b.created_on, u.id from core_blacklisteduserdetail b join users_user u on u.phone_number=b.value where b.type='user_mobile_no' and not b.is_removed and not u.is_deleted),
mm as (select uid, min(bc) first_bl from m group by 1)
select count(distinct mm.uid), count(distinct t.user_id), count(distinct t.id), count(distinct t.id) filter (where t.created_on>mm.first_bl), count(distinct t.user_id) filter (where t.created_on>mm.first_bl),
 count(distinct t.id) filter (where t.created_on>mm.first_bl and t.user_platform='WEB'), count(distinct t.id) filter (where t.created_on>mm.first_bl and t.user_platform like 'app%'), count(distinct t.id) filter (where t.created_on>mm.first_bl and t.created_on>='2026-09-01')
from mm left join users_cognitoissuedtokens t on t.user_id=mm.uid;

-- C9 resend chains with >=2 accepted codes [exact]
with r as (select t.source, coalesce(t.email,'')||'|'||coalesce(t.phone_number,'') k, t.created_on, t.id, v.is_valid, case when t.created_on - lag(t.created_on) over (partition by coalesce(t.email,'')||'|'||coalesce(t.phone_number,''), t.source order by t.created_on, t.id) <= interval '10 minutes' then 0 else 1 end newc from notifications_twofactorauth t join notifications_twofactorauthverification v on v.reference_id_id=t.id),
c as (select *, sum(newc) over (partition by k, source order by created_on, id rows unbounded preceding) cid from r),
ch as (select source, k, cid, count(*) codes, count(*) filter (where is_valid) nvalid, (array_agg(is_valid order by created_on desc, id desc))[1] last_valid from c group by 1,2,3)
select source, count(*) chains, count(*) filter (where codes>=2) multi, count(*) filter (where nvalid>=2) ge2_valid, count(*) filter (where codes>=2 and nvalid>=1 and not last_valid) valid_not_last, count(*) filter (where nvalid=codes and codes>=2) all_valid from ch group by 1;

-- C10 users_user id range at a point in time (explains 1,411,092 vs 1,411,103 drift)
select count(*) n, min(id), max(id), to_char(max(date_joined),'YYYY Mon DD HH24:MI'), to_char(now(),'YYYY Mon DD HH24:MI') from users_user;
```
