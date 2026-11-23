# MATRIX Backend — Phase 2B Integration Design (Final Audit Reconciliation)

**Status:** Design/audit only. No application implementation, Supabase operation, or database change was performed.  
**Evidence basis:** Supabase dashboard findings supplied by the user on 2026-11-20, plus the local Phase 1 backend and Phase 2A audit. The remote dashboard was not independently accessed in this task.  
**Compatibility requirement:** Preserve existing Supabase users and UUIDs, profiles, tables, functions, triggers, and RLS policies. MATRIX access is global; this design has no product-specific entitlements or separate Premium/ML Pro activation state.

## 1. Findings: supplied verified information and remaining unknowns

### Dashboard findings supplied as verified

| Area | Finding |
|---|---|
| Auth signup | Enabled. |
| Email confirmation | Enabled. |
| Anonymous sign-in | Disabled. |
| Manual account linking | Disabled. |
| Site URL / redirect allowlist | Site URL is `http://localhost:3000`; no redirect URLs are configured. |
| Existing accounts | Four Auth users exist. No user identifiers or personal records are included here. |
| Existing profiles | Four profiles have `access_status = approved`; two have non-null `activation_completed_at`. |
| Auth profile trigger | `auth.users` has an AFTER INSERT trigger named `on_auth_user_created` that calls `handle_new_user()`. |
| Profile protection triggers | `profiles` has BEFORE INSERT and BEFORE UPDATE triggers calling `protect_profile_access_fields()`. |
| Code consumption | `consume_activation_code(p_user_id uuid, p_code_hash text)` returns boolean; it is SECURITY DEFINER; checks approved profile state; validates user-bound code expiry, revocation, and usage; consumes the code; and updates `profiles.activation_completed_at`. |
| Function execution access | The consume function permits `service_role` or the authenticated user matching `p_user_id`. |
| Existing user role claims | `raw_app_meta_data.role` is not set for all four existing Auth users. Do not use that claim as a universal admin source. |
| Approval schema | No dedicated `access_requests` table appeared in the inspected public schema. |

These findings are the supplied dashboard evidence, not fresh observations from this session. The count of users/profiles is summarized only; this report does not access or reproduce user records.

### Remaining unknowns that block implementation

- Exact `profiles` primary key and its relationship to `auth.users.id` / token `sub`.
- All allowed `profiles.access_status` values, transition rules, and whether `approved` is the authoritative approval state in all cases.
- RLS policies, grants, and the exact permitted actor/path for changing `access_status`.
- Whether `protect_profile_access_fields()` permits the intended trusted approval update; its full behavior, ownership, `search_path`, and trigger coverage still need review.
- `activation_codes` columns, constraints, issuance/rotation semantics, hash algorithm/encoding, and how code delivery is performed. **Code issuance has not been confirmed. No issuance function or API is assumed.**
- Whether the boolean result from `consume_activation_code` is sufficient to distinguish safe outcomes, its concurrency behavior, and how failures are surfaced. The supplied summary confirms its checks and update behavior, but its full definition and grants still need review before implementation.
- JWT issuer, audience, signing algorithm/key mode, JWKS URL/key rotation, relevant verified claims, and how email confirmation is represented in this project's access token/user response.
- Exact allowed redirect URL setup needed for the current frontend/deployment. With no redirect URLs configured, the intended frontend callback may not be accepted; the Site URL currently points to port 3000.
- Existing SMTP/email provider, verification and recovery templates, delivery ownership, and any current activation-code delivery channel.
- A trusted admin identity. No role is confirmed; `raw_app_meta_data.role` is absent for some existing accounts. The proposed `MATRIX_ADMIN_USER_ID` option below is pending security/operational verification.
- Whether an existing access approval process exists outside the inspected public schema. No access request table was observed; do not presume an alternative request object or workflow.

## 2. Final proposed minimal architecture

1. **Supabase Auth owns identity and credentials.** The frontend continues to use the existing Supabase Auth project for registration, sign-in, email confirmation, and password reset. Passwords do not pass through FastAPI. Anonymous sign-in and manual account linking remain disabled as currently configured.
2. **FastAPI verifies every protected bearer JWT.** It validates signature, issuer, audience, expiry, and subject and derives the caller's UUID from verified `sub`. A UUID supplied in a request body never establishes identity.
3. **Existing trigger provisions profiles.** Rely on `on_auth_user_created` → `handle_new_user()` for automatic profile provisioning; do not duplicate profile creation in the API.
4. **Approval is one global profile state.** Treat `profiles.access_status = approved` as the likely approval state, pending verification of its allowed values and update permissions. No `access_requests` table is presumed or proposed.
5. **Single-admin configuration is a candidate, not yet approved.** Evaluate a backend-only `MATRIX_ADMIN_USER_ID` setting containing one UUID. A server dependency would compare it with the verified JWT `sub`. This is not a database role and must not be exposed to the frontend. Its suitability, bootstrap, UUID mapping, rotation, and operational owner require verification before it can be enabled. Do not assume any admin role exists or fall back to email checks.
6. **Activation consumption uses only the existing function.** Call `consume_activation_code` with the authenticated user UUID derived from the token and a hash generated exactly as the existing function expects. It already performs the described approval/code checks, consumes the code, and updates `profiles.activation_completed_at`; do not duplicate or bypass those checks or the profile protection trigger.
7. **Global access derives from persisted state.** Protected MATRIX endpoints check the verified user's existing profile and activation timestamp server-side. A non-null `profiles.activation_completed_at` is the activation indicator specified by the confirmed flow. No per-product entitlement or activation flag is introduced.
8. **Activation-code issuance/delivery remains unresolved.** Do not implement an approval-to-code-issuance step until the existing mechanism and delivery path are verified. Do not invent an issuance function, write directly to `activation_codes` using guessed columns, or return a code to the approving admin.

For `consume_activation_code`, prefer a request executed as the authenticated user with their verified bearer token, so the existing `authenticated` identity match is applied. The exact call mechanism must be checked against its execute grants and RLS/security configuration. Do not use `service_role` by default. If it is strictly required, keep it server-only, use it only after independent authorization, and preserve the function's own user-binding checks.

## 3. Auth flow and callback configuration

- Registration/sign-in/email verification/password reset remain Supabase Auth operations. FastAPI has no password registration or login endpoint.
- The confirmation requirement means unconfirmed accounts must not be treated as ready for approval or activation. Confirm how the project exposes verification state and ensure API checks use verified Auth context, not a client boolean.
- The current Site URL is `http://localhost:3000` and no redirect URLs are configured. Before wiring the frontend callback, an authorized project operator must decide and configure the exact development/production redirect URLs through the normal approved settings process. This design does not change Auth settings.
- Supabase Auth creates the profile via the existing AFTER INSERT trigger. The API should tolerate a brief profile-not-ready condition with a retryable response; it must not insert a second profile.

## 4. FastAPI JWT verification design

A shared dependency should fail closed unless it can:

- Verify the token signature against the existing project's verified public key/JWKS or the project's secure signing-key mechanism, using an explicit supported algorithm allowlist.
- Validate exact issuer, audience, expiry, and not-before where present.
- Validate `sub` as a UUID and bind every user-level database operation to it.
- Safely cache public keys and refresh once for an unknown `kid`; fail closed on key retrieval/verification errors.
- Return generic `401` for missing/invalid/expired credentials and avoid logging token contents or sensitive claims.

No role claim should be trusted for admin access. Since the supplied findings say `raw_app_meta_data.role` is missing on some existing Auth users, it cannot currently be assumed to authorize every admin operation. Confirm whether the project uses another trusted admin mechanism. `MATRIX_ADMIN_USER_ID` is evaluated in section 7, pending verification.

## 5. Existing profile/activation objects to preserve

- `auth.users` AFTER INSERT trigger `on_auth_user_created` calls `handle_new_user()`.
- `profiles` BEFORE INSERT and BEFORE UPDATE triggers call `protect_profile_access_fields()`.
- `profiles.access_status` is the likely approval state, but allowed values and who may update it remain unverified.
- `profiles.activation_completed_at` is the confirmed global activation field.
- `activation_codes` is the existing code storage object.
- `consume_activation_code(p_user_id uuid, p_code_hash text)` is the existing boolean-returning SECURITY DEFINER function described above.

The consume function is the only approved code-consumption path in this design. Do not write activation state directly, query/update activation-code rows directly, change function behavior, disable a trigger, or bypass RLS. Even though the supplied findings state that the function updates the timestamp, inspect the full function and trigger behavior before implementation to confirm the trusted update is permitted and remains atomic.

## 6. Admin authorization and approval design

### Candidate admin authorization

A minimal option for a single designated administrator is a server-only `MATRIX_ADMIN_USER_ID` environment setting. If approved after verification, the admin dependency would:

1. Verify the bearer JWT normally.
2. Compare verified `sub` to the configured UUID using a strict UUID comparison.
3. Deny access if the setting is missing, malformed, or does not match; no email, browser role, `user_metadata`, or unverified claim fallback.
4. Keep the value out of frontend configuration and responses; protect and audit deployment changes to it.

This is **pending verification**, not a claim that admin authorization already exists. Confirm that the selected UUID belongs to the intended existing account, that it remains stable, who can change the deployment setting, and how access can be revoked. If multi-admin support or database-managed roles is required, stop for a separately approved design; do not create a role table here.

### Approval operation

No `access_requests` table appeared in the inspected public schema, so the earlier `/admin/access-requests/{request_id}/approve` proposal is withdrawn. Do not implement that route against a nonexistent/unverified request model.

If `profiles.access_status` and its permission model are confirmed, the minimal candidate is:

`POST /api/v1/admin/profiles/{user_id}/approve`

It would require the server-side admin dependency, validate that the target profile exists and is in an allowed pre-approval state, and make only the existing approved transition using the already-permitted database path. It must preserve the target user's Auth UUID/profile relationship and existing profile. The endpoint must not create an access request or activation code. If existing policies/trigger protections do not permit this transition through an approved path, stop; no RLS/trigger bypass or database change is authorized.

Do not expose whether another user's profile exists to an unauthorized caller. Return a safe state/conflict for repeated approval according to the verified status lifecycle.

## 7. Activation-code issuance, consumption, and delivery

### Issuance blocker

The existing `activation_codes` table and consume function are confirmed, but **issuance is not confirmed**. The inspected information does not establish who creates codes, their storage/hash format, or how they are delivered. Therefore:

- No issuance endpoint is included in the minimal API plan.
- Approval must not claim that a code was generated or delivered.
- Do not invent a function, table column, direct insert, code hash algorithm, email provider, or delivery job.
- Before implementation, inspect the existing issuance and delivery path. If none exists, stop and request a separately approved design decision; do not create schema or objects under this task.

### Consumption endpoint

`POST /api/v1/activation/consume` accepts a code from the signed-in user. The backend hashes it only using the exact established algorithm/encoding, then invokes `consume_activation_code(p_user_id, p_code_hash)`. The user ID is always the verified JWT `sub`; any body `user_id` field is forbidden/ignored. The database function remains responsible for checking approved profile state, user-bound code, expiry, revocation, prior use, consuming the code, and updating `profiles.activation_completed_at`.

Because its return is boolean, `true` can map to activation success. `false` should map to a generic invalid/unavailable code response that does not disclose which check failed. Database errors should fail closed. Rate-limit attempts and never log the code or its hash. Verify concurrency and idempotency behavior from the function definition before release.

## 8. Minimal API endpoint plan

Only the following FastAPI routes are proposed. Phase 1 currently implements health routes only; none of these business routes exist yet.

| Route | Authentication | Contract / caveat |
|---|---|---|
| `GET /api/v1/me/access` | Valid user JWT | Reads the caller's existing profile state and returns global access state. Never accepts user ID from the caller. |
| `POST /api/v1/admin/profiles/{user_id}/approve` | Valid JWT plus candidate server-side `MATRIX_ADMIN_USER_ID` check | Conditional on verifying `profiles.access_status` values, UUID relationship, RLS, grants, and trigger behavior. Does not issue a code. Route is not ready to implement until those blockers are resolved. |
| `POST /api/v1/activation/consume` | Valid user JWT | Accepts `{ "activation_code": "<code>" }`; hashes to the verified existing format and calls `consume_activation_code` with JWT `sub`. |

Supabase Auth handles signup, sign-in, email verification, and password reset directly; no FastAPI equivalents are proposed. No request-submission or code-issuance endpoint is specified because no verified existing contract/mechanism is available.

### Response shape proposals

`GET /api/v1/me/access`:

```json
{
  "user_id": "<verified-auth-uuid>",
  "email_verified": true,
  "profile_ready": true,
  "access_status": "approved",
  "activation_completed": true,
  "access": "granted"
}
```

The actual `access_status` values and how to obtain email verification from trusted Auth context must be verified. Do not return invented defaults as facts. If a profile is temporarily unavailable, return a safe pending/retryable state without creating a profile.

Approval response, only after successful existing-state transition:

```json
{
  "user_id": "<target-auth-uuid>",
  "access_status": "approved"
}
```

Do not include an activation code or make any claim about code issuance or delivery. Approval does not prove that a code was issued.

Activation request:

```json
{
  "activation_code": "<user-entered-code>"
}
```

Activation success:

```json
{
  "activation_completed": true,
  "access": "granted"
}
```

Use the Phase 1 error envelope `{ "error": { "code", "message", "details?" }, "request_id" }` with generic code failure messages.

## 9. Configuration plan

Existing backend settings are reserved in `app/core/config.py`; do not add or configure them until their exact values/need is verified. Values belong in a secure deployment secret manager or local environment, never in source control, frontend `VITE_` variables, logs, or chat.

| Variable | Intended use | State |
|---|---|---|
| `SUPABASE_URL` | Existing project API URL if server-side calls require it | Needed value/usage to confirm. |
| `SUPABASE_ANON_KEY` | Project public key for user-scoped server calls if selected | Need and secure usage pattern to confirm. Never substitute service-role key. |
| `SUPABASE_SERVICE_ROLE_KEY` | Privileged server operations only if unavoidable | Avoid if possible; server-only; never frontend. Consume function accepts authenticated matching user, so user-scoped invocation should be evaluated first. |
| `SUPABASE_JWT_ISSUER` | Expected JWT issuer | Exact value pending verification. |
| `SUPABASE_JWKS_URL` | Public signing key retrieval | Exact value/key mode pending verification. |
| `FRONTEND_ORIGINS` | Exact CORS allowlist | Set to approved development/production origins; no credentialed wildcard. |
| `MATRIX_ADMIN_USER_ID` | Optional single-admin allowlist UUID checked against verified JWT `sub` | Candidate only; pending explicit operational/security verification before use. No default or email fallback. |
| Email provider settings | Existing activation-code delivery if available | Provider and configuration unknown; do not invent. |

Also verify JWT audience, algorithms/key rotation, email verification claim availability, and expected frontend callback URL. The current Supabase Site URL is `http://localhost:3000` with no redirect URLs configured; align only through a separately authorized settings change, not this design task.

## 10. Error handling and security requirements

- Keep the Phase 1 JSON error envelope and request IDs.
- Suggested status handling: `401` invalid/missing JWT; `403` not configured as admin; `404` or safe unavailable state where revealing target existence is inappropriate; `409` invalid state/repeated transition where safe; `422` malformed request; `429` throttled; `502/503` Auth/JWKS/database dependency unavailable; `500` generic internal error.
- Never log passwords, bearer tokens, activation code/hash, verification/reset links, service-role key, or unnecessary personal data.
- Require TLS; use strict CORS origins, request size limits, and attempt/admin rate limits.
- Do not trust browser-supplied user IDs, roles, email verification, approval, or activation booleans.
- Do not disable RLS or alter/bypass `protect_profile_access_fields` or `consume_activation_code`. Review the security-definer function's owner, safe `search_path`, execute grants, and identity checks.
- Global access is granted only from server-verified persisted profile state. No Premium/ML Pro-specific entitlement model is allowed.

## 11. Safe implementation order

This order is for a future implementation phase; no step is authorized or performed by this document.

1. **Read-only contract confirmation:** inspect current table columns/keys, policies/grants, trigger and function definitions, Auth settings, JWT configuration, and code issuance/delivery mechanism. Verify `auth.users.id` to profile key mapping and allowed `access_status` transitions.
2. **Resolve blockers:** obtain the exact JWT issuer/audience/key verification details; establish redirect allowlist requirements; verify the admin identity and decide whether `MATRIX_ADMIN_USER_ID` is acceptable; establish whether an existing safe code issuance/delivery path exists. If approval/code issuance requires new schema or policy, stop for explicit approval.
3. **Specify API schemas:** finalize only `/me/access`, conditional admin profile approval, and activation consumption using actual verified status values and function signatures. Do not add request or issuance endpoints without verified mechanisms.
4. **Implement JWT verification first:** add shared validation and negative tests; ensure failure closed before enabling protected routes.
5. **Implement read-only access status:** resolve the caller profile by verified `sub` and return global approval/activation status under existing access policies.
6. **Implement admin authorization and approval only if supported:** enforce verified admin UUID server-side, then perform only the permitted status transition. No code issuance claim or automatic insert.
7. **Implement activation consumption:** pass JWT `sub` and correctly derived `p_code_hash` to the preserved function through the permitted authenticated path; never write activation timestamp directly.
8. **Integrate email delivery only after confirming existing ownership/mechanism:** do not create a new sender or code issuance design implicitly.
9. **Test in a controlled non-production project:** JWT, permission, profile-trigger preservation, status transitions, code expiry/revocation/replay/concurrency, generic failures, and atomic timestamp update. Avoid consuming or altering production users/codes for tests.
10. **Review deployment config and monitoring:** secrets only in backend secret storage; no sensitive tokens/codes in logs; exact CORS and Auth redirects reviewed by the project owner.

## 12. Tests planned for implementation phase

No tests were added or run for this design-only task. Future tests should cover:

- JWT signature, issuer, audience, expiry, not-before, missing/invalid UUID subject, key rotation, and fail-closed JWKS errors.
- Admin allowlist absent/malformed/matching/nonmatching; forged frontend roles never grant access; ensure configured admin ID matches verified identity only.
- Existing profile relationship and `handle_new_user()` idempotency without duplicate profiles or UUID changes, in a safe non-production environment.
- `access_status` permitted transitions, RLS/grants, and `protect_profile_access_fields()` behavior.
- `consume_activation_code` with true/false outcomes, wrong user, unapproved profile, expired/revoked/used code, replay and concurrent calls, confirming it alone updates `activation_completed_at`.
- API responses and logs do not expose codes, hashes, tokens, or unnecessary user details.
- Global access only when the authoritative profile activation state is non-null; no product-specific flags.

## 13. Phase boundary and change log

This remains a design/audit task. This reconciliation updates only `docs/PHASE_2B_INTEGRATION_DESIGN.md`. No application code, tests, environment files, frontend, n8n, database schema, policies, functions, triggers, Auth settings, users, or profiles were changed. No Supabase API calls or migrations were run.


## 14. Final source review and dashboard reconciliation

This section adds the requested local source review and supersedes any earlier wording that implied a verified admin role, approval-request table, code issuance path, or existing FastAPI integration. Supabase dashboard details below are those supplied by the user; no live connection was made for this review.

### 14.1 Admin authorization: source review and recommendation

**No admin authorization mechanism is verified in the available source.** The FastAPI project has only health routes, no auth dependency, repository, admin check, or database client. The frontend `/admin` page is explicitly a development preview: its controls are behind a `?preview=admin` query flag in development, and its approval actions update sample component state that resets on reload. That flag and UI are not security controls. The frontend sends no verified admin identity or role to a backend. The supplied dashboard finding that `raw_app_meta_data.role` is unset on some existing users means that claim cannot be assumed as the current universal admin mechanism.

**Recommendation:** for a single designated admin, use a backend-only `MATRIX_ADMIN_USER_ID` environment setting as an allowlist of one existing Auth UUID. Do not put a value in source, documentation, frontend variables, or this report; do not hardcode an email or UUID. The admin dependency must first verify the Supabase JWT and then compare its verified `sub` UUID to the configured value. If the setting is absent or invalid, admin endpoints fail closed. Verify out of band who owns this deployment setting, how the UUID is matched to the intended existing Auth account, and how it is rotated/revoked. This is the minimal candidate recommendation, not a claim that a role already exists or that the value has been approved. Do not create a role table under this design.

### 14.2 Approval: can `profiles.access_status` support it?

The supplied dashboard findings show four profiles with `access_status = approved`, but do not establish the full set of allowed values, whether any pending state exists, or the intended transition rules. This field is a plausible existing approval mechanism, not yet a verified complete approval workflow. No `access_requests` table was observed. The user-reported profile counts do not establish how a new, unapproved user is represented or whether an approval request is persisted.

Before implementation, verify all of the following:

1. The profile key maps to the existing Auth UUID (`auth.users.id` / verified JWT `sub`) and the operation targets that exact profile without creating or changing identity records.
2. The allowed values and transition semantics for `profiles.access_status`, including the state a newly registered/unapproved account has and whether transition to `approved` is valid and sufficient.
3. The applicable RLS `SELECT`/`UPDATE` policies and SQL grants for the actual database role used. Determine whether the authenticated user's existing policies permit the admin update. Do not assume they do, especially without a verified role claim.
4. The exact intended database operation: a narrowly scoped update of only the target profile's `access_status`, guarded by the verified admin authorization and expected prior status, using an already-authorized database path. Confirm whether an existing service-role backend call is required and that its DB privileges permit the update. Service role bypasses RLS; if considered, authorization must occur independently in FastAPI before the operation, and the key remains server-only.
5. Whether the `BEFORE UPDATE` `protect_profile_access_fields()` trigger allows this actor/path to change `access_status` and preserves all protected fields. Do not disable or bypass it. Confirm whether the update can be safely conditional/atomic and how repeated approval is handled.
6. Whether approval by itself is sufficient to start any existing activation-code issue/delivery flow. It is not safe to assume so.

If current profile status values do not represent an unapproved/pending state or no existing permitted update path exists, the current schema cannot yet be confirmed to support the requested admin approval workflow. Stop for an explicit design decision; do not add status values, tables, policies, or functions in this phase.

### 14.3 Activation-code issuance and email delivery: source review

A search of the available backend and relevant frontend source found **no existing code-generation, code-hashing issuance, or email-delivery implementation**. Phase 1 backend dependencies and routes contain no mail or activation service. The frontend activation screen is a nonfunctional visual preview; its input remains local to the component and is cleared after submission. The admin page shows demo-only request rows/actions. These UI elements do not generate, persist, send, or validate real codes. `activation_codes` and the verified consume function establish storage/consumption, not issuance.

Consequently, there is currently no verified mechanism connecting an approval to a new code and delivery to a user. Do not add an issuance endpoint or claim that approval queues/sends a code. First inspect the existing database/code/email systems for a pre-existing issuance path, its exact hash algorithm, persistence constraints, expiry/revocation semantics, and delivery provider. If none exists, issuance and delivery are a blocker requiring a separately approved design. Do not invent a function, mutate `activation_codes` directly using guessed columns, or change `consume_activation_code`.

The existing `consume_activation_code(p_user_id uuid, p_code_hash text)` remains the only code-consumption route. FastAPI must derive `p_user_id` from verified JWT `sub`, calculate `p_code_hash` only with the confirmed existing algorithm, and invoke the preserved function. The function's boolean return maps to success/failure; `false` must become a generic unavailable/invalid code response. It is SECURITY DEFINER and must remain unchanged. Confirm its owner, safe `search_path`, execute grants, RLS context, and concurrency behavior before integration. Prefer invocation under the user's JWT because the function permits the authenticated user matching `p_user_id`; do not use service role by default.

### 14.4 JWT verification configuration

Phase 1 `app/core/config.py` only reserves `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_JWT_ISSUER`, and `SUPABASE_JWKS_URL`; none is used by the current backend. The `.env.example` values are placeholders. The backend has no JWT verification code or JWT library dependency today.

Before implementation, read the project's signing configuration and verify:

- Exact JWT issuer (`iss`) and expected audience (`aud`). Add a backend-only audience setting such as `SUPABASE_JWT_AUDIENCE` if required by the verified project contract; do not guess its value.
- Signing mode and algorithms. For asymmetric signing, validate against the project's HTTPS JWKS URL (`SUPABASE_JWKS_URL`) with a strict algorithm allowlist and safe `kid` refresh/rotation behavior. For legacy symmetric signing, use the project-supported secure verification method and store any required signing secret only in backend secret storage; never ask for or print it here.
- Required claims and validation behavior: signature, exact issuer/audience, `exp`, `nbf` when present, and UUID `sub`. Reject missing/malformed identity and unsupported algorithms; fail closed if key retrieval/verification fails. Do not trust a decoded but unverified JWT.
- How email confirmation is reliably represented/enforced for this project; do not rely on a frontend boolean or assume a claim exists without checking the actual token/Auth contract.
- Secure JWKS caching, unknown-key refresh behavior, clock tolerance, and dependency/library selection. A suitable verified implementation must pin permitted algorithms and validate all required claims.

`SUPABASE_URL` and the public anon key may be needed for user-scoped RPC/REST calls; determine that from the chosen integration. `SUPABASE_SERVICE_ROLE_KEY` is not needed for JWT verification and must not be sent to the browser. If a server DB operation requires it, use only after independent admin authorization and keep it inaccessible to logs, responses, OpenAPI, and frontend builds. Never request/display any secret.

### 14.5 Frontend routes/screens that need later integration

The route inventory below comes from `src/app/App.tsx`; the Auth UI is in `src/features/auth/AuthPages.tsx`, access previews in `src/features/access/AccessPages.tsx`, and admin preview in `src/features/admin/AdminPage.tsx`. These files were inspected but not modified.

| Existing route | Existing screen | Later integration requirement / current limitation |
|---|---|---|
| `/register` | `AuthPage` in register mode | Call existing Supabase Auth signup; preserve email confirmation and existing account identity. Current submit is preview-only. Callback cannot be finalized until the project's redirect allowlist is configured through authorized settings. |
| `/login` | `AuthPage` in login mode | Supabase Auth sign-in; send resulting access JWT to FastAPI. Current submit is preview-only. |
| `/verify-email` | `VerifyEmailPage` | Handle the Supabase confirmation callback/state and resend only through the established Auth flow. Current screen is preview-only. No redirect URLs are presently configured; callback URL is a blocker. |
| `/forgot-password` | `ForgotPasswordPage` | Use the existing Supabase Auth recovery flow and approved redirect/template; current form does not send email. |
| `/request-access` | `AccessRequestPage` | Current UI requests **MATRIX Premium** product access and explicitly does not submit/store a request. This is inconsistent with the confirmed single global MATRIX activation model. There is no observed `access_requests` table or verified request persistence contract, so do not wire it to a guessed endpoint. Any UI alignment requires a later authorized frontend task. |
| `/access-status` | `AccessStatusPage` | Replace preview states later with server-confirmed global `access_status` and `activation_completed_at`, once profile mapping/read permissions are verified. |
| `/activate` | `ActivationCodePage` | Current screen says Premium-specific and is nonfunctional. Later integration must submit the user's code to the global consume endpoint and show only server-confirmed outcome; no code is generated/sent by this screen. UI alignment requires a later authorized frontend task. |
| `/admin` | `AdminPage` | Replace development `?preview=admin` gating and demo-only state with server-enforced admin check and verified approval operation. The UI flag cannot authorize access. No issuance action should be connected until a real issuance/delivery mechanism is established. |
| `/dashboard` | `DashboardPage` behind a constant-false preview guard | Ask backend for global access status; enforce data access in FastAPI, not the React guard. |
| `/premium`, `/premium/reports`, `/reports` | Product/report screens behind constant-false preview guards | These remain protected by the same one global MATRIX activation decision; do not create separate product entitlements. |
| `/account` | `AccountPage` | Integrate account/session display and Supabase sign-out using verified session state; no admin/access authority should come from local state. |

The frontend package includes `@supabase/supabase-js`, but the inspected Auth submit handlers are local preview interactions; the dependency alone does not mean Auth is connected. FastAPI currently exposes only `/health`, `/api/v1/health`, and infrastructure routes; all business endpoints below are proposals.

### 14.6 Minimal endpoint plan after blockers are cleared

1. `GET /api/v1/me/access` — requires a valid user JWT; resolves the profile using verified `sub` and returns the global verified access state.
2. `POST /api/v1/admin/profiles/{user_id}/approve` — candidate only; valid JWT plus server-side `MATRIX_ADMIN_USER_ID`; permitted only after confirming status values, key relationship, RLS/grants, update path, and protection trigger. It performs only the allowed transition to `approved`; no request row or code is created by assumption.
3. `POST /api/v1/activation/consume` — valid user JWT; accepts the code; derives user ID from `sub`; hashes with the verified existing format; calls the unchanged `consume_activation_code`; returns generic failure for false.

Supabase Auth handles register/login/verify/recovery directly; no password endpoints in FastAPI. No code issuance/delivery route is proposed until an existing mechanism is found. No request-submission route is proposed because no persistent request object/contract is verified.

### 14.7 Exact implementation blockers and safe order

**Blockers before implementation:**

1. Profile/Auth UUID mapping and complete profile schema/read path.
2. `access_status` allowed values, initial unapproved state, transition semantics, relevant RLS policies and DB grants.
3. Exact approved DB update path and proof that `protect_profile_access_fields()` permits it without bypass; determine whether user-scoped policy suffices or tightly controlled server-side service-role access is necessary.
4. Validate `MATRIX_ADMIN_USER_ID` as an operationally acceptable single-admin mechanism and verify selected admin identity out of band. If not, obtain an approved existing alternative; do not create a role table.
5. Existing code issuance/hash and email delivery path. None was found in available app source. If no existing path, stop for separate approval.
6. JWT issuer, audience, signing mode/algorithm/JWKS or secure symmetric verification method, claims, and email-confirmation enforcement.
7. Approved frontend redirect URLs: current Site URL is `http://localhost:3000` and redirect allowlist is empty.

**Safe implementation order:**

1. Complete read-only verification of the blockers above; do not query user records beyond the already supplied summarized counts unless necessary and authorized.
2. Confirm and document database permission model for status approval and function invocation. If it requires a schema/policy/function change, stop for explicit approval.
3. Finalize schemas against actual claims/columns/status values; keep the three candidate APIs minimal and omit unverified request/issuance routes.
4. Implement and test strict JWT verification first, failing closed.
5. Implement read-only `/me/access` and server-side global access enforcement.
6. Implement admin ID authorization and only the verified, permitted `access_status` update.
7. Implement code consumption via the existing function, never direct code/profile writes.
8. Integrate code issuance/delivery only if an existing approved mechanism is found; otherwise remain blocked pending a separate design approval.
9. Integrate the listed frontend routes only in a later authorized frontend phase, using configured callback URLs and the same global access state.
10. Test in a controlled non-production environment without modifying existing production users, policies, or objects.

## 15. Change boundary

This review updates only this design document. No application code or tests were added, no Supabase/database operation was executed, and no frontend, n8n, Auth settings, users, profiles, tables, functions, triggers, or policies were changed.
