# MATRIX Backend — Phase 2A Supabase Read-Only Audit

**Audit date:** 2026-11-20  
**Status:** Local workspace inspection completed; remote Supabase project inspection unavailable.  
**Scope:** Read-only discovery only. No Supabase or application configuration was changed.

## Executive summary

The current session had no Supabase connector, database connection, management API session, or project credentials available for read-only inspection. No credentials were requested. The local backend contains only Phase 1 configuration placeholders and health infrastructure; it has no Supabase client, repositories, auth integration, schema snapshot, or migrations. The frontend contains a Supabase JS package dependency and clearly labels account/access pages as visual previews; local UI does not establish the existing remote project architecture.

Therefore, this audit **cannot verify any remote Auth setting, table, column, key, relationship, policy, function, trigger, email setting, user/profile relationship, or access-management structure**. Those items are recorded as unknown, not absent. No table inventory or relationship has been inferred.

## Read-only methods and boundaries

Inspected local file names and selected configuration, documentation, and auth UI source. Checked whether backend/frontend `.env` files and local SQL or Supabase project configuration artifacts are present; only `MATRIX_Backend/.env.example` was found among the checked project files. Checked environment variable **names only** for Supabase/database-related variables; none were present. No `.env` contents, credentials, user records, or database rows were read.

No remote Supabase endpoint could be reached through an available read-only tool in this session. No SQL, HTTP request to the project, CLI command, migration, auth-admin operation, or write operation was performed.

## Existing local architecture overview

- `MATRIX_Backend` is a separate FastAPI Phase 1 project with settings, health routes, error schemas, logging, and test files. It has no database integration.
- `app/core/config.py` reserves settings for `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_JWT_ISSUER`, and `SUPABASE_JWKS_URL`. These are placeholders/reserved settings; the audit found no local `.env` and no configured values. Phase 1 code does not use them to connect to Supabase.
- The frontend package manifest lists `@supabase/supabase-js`, but inspection of the auth source and the frontend README identifies login, registration, recovery, verification, product access, and admin preview actions as unconnected visual previews. A package dependency alone does not demonstrate a configured or functioning Supabase integration.
- The local frontend README says integration must wait for the existing project URL/auth configuration, existing user/profile/role relationships, trusted FastAPI contracts, admin authorization, email responsibilities, and CORS origins to be established. This is local documentation, not evidence of remote project state.

## Findings by requested audit area

| Area | Finding | Evidence / confidence |
|---|---|---|
| Supabase Auth configuration and methods | **Not inspected remotely.** Enabled providers, password policy, redirect URLs, session settings, MFA, OAuth providers, and signup behavior are unknown. | No connected Supabase management/read-only tool or project connection available. |
| Public schema tables and columns | **Unknown.** No remote catalog was queried; no table/column inventory can be reported. | No local schema export, migration, or SQL artifact was found in the checked workspace paths. |
| Primary keys, foreign keys, unique constraints, indexes | **Unknown.** | No remote metadata or local schema snapshot available. |
| User/profile relationship | **Unknown.** Do not assume a profile table, user key, or one-to-one relationship. | No database metadata available. Frontend preview copy is not proof. |
| Roles and admin authorization | **Unknown.** No verified role table, JWT claim convention, custom access token hook, RLS-based role check, or admin identity mechanism. | No remote metadata or code integration available. |
| RLS enabled status and policies | **Unknown for every remote table.** No policy definitions were retrieved. | No remote catalog access. |
| Functions and triggers | **Unknown.** No function definitions or trigger bindings were retrieved. | No remote catalog access. |
| Product access, approval, activation codes, entitlements | **Unknown remotely.** No verified tables, relationships, statuses, code storage, expiration, or enforcement mechanism. | Frontend contains preview-only access and admin screens; they do not establish actual database implementation. |
| Email verification and password reset | **Not inspected remotely.** Provider, templates, SMTP configuration, expiry/rate limits, redirect allowlists, and delivery ownership are unknown. | No Auth settings access. Frontend recovery/verification pages explicitly say no email is sent. |

### Local schema/artifact search

Within the checked `MATRIX_Backend` and frontend project paths, no `.sql` file, Supabase `config.toml`, migration directory, seed file, or schema export was found. This is limited to the checked workspace; it does not establish that no schema artifacts exist elsewhere or in the remote project.

### Local authentication and authorization behavior

The frontend `AuthPages.tsx` provides display-only login, registration, forgot-password, and email-verification screens. Its README explicitly states that those screens do not call an authentication service or send email. `App.tsx` has visual preview routes and guarded/locked product pages. The frontend README describes admin actions as in-memory sample interactions and warns that client-side flags are not security boundaries. None of this authenticates a user, verifies an admin, or proves how the existing Supabase project is configured.

## Existing access-management implementation

No actual Supabase-backed product access, approval, activation-code, or entitlement implementation was found in the checked local frontend/backend source. The frontend provides preview states and mock/sample controls, explicitly labeled as such in its README. The remote implementation remains **unknown** because the project was not accessible.

## Missing information required before Phase 2B

1. A safe, authorized read-only way to inspect the existing project's Auth and database metadata. Do not send secrets in chat. Use an approved connected read-only integration or a locally stored credential with narrowly scoped read-only access.
2. Remote metadata inventory: public tables/columns, constraints, indexes, RLS flags and policy expressions, relevant functions/triggers, and Auth provider/email settings.
3. Verified user/profile/role/admin relationship and the authoritative source for identity and authorization.
4. Verified product-entitlement, request/approval, activation-code, and email-delivery lifecycle, including ownership and status meanings.
5. Existing FastAPI/OpenAPI contract and frontend/backend origin requirements. Do not infer endpoints from preview screens.

## Risks and compatibility concerns

- Guessing table names, profile identifiers, role sources, or entitlement state could break existing relationships or grant/revoke access incorrectly.
- A browser-supplied role or entitlement flag must not be treated as authorization. Admin and product access require server-side verification against the existing trusted mechanism.
- JWT verification must use verified project issuer/JWKS settings and correct audience/claims; do not disable verification or invent claim semantics.
- The service-role key is privileged and must remain server-side. It must not enter browser code, `VITE_` variables, logs, or this report.
- Signup, email verification, password reset, redirect URLs, and provider configuration may be relied on by existing users. They must be documented before any changes are considered.
- Keep ML Pro and MATRIX Premium entitlement checks independent while retaining the existing shared identity, once the actual model is verified.
- Current UI previews are not a substitute for backend contracts or live authorization.

## Recommended integration plan (future work; not performed)

1. Obtain read-only access to project metadata through an approved mechanism and complete the unknown findings above. Do not query user records when catalog metadata is sufficient.
2. Review the existing FastAPI contract and identify the authoritative auth/token validation model and service boundaries.
3. Document verified identity, role, product-access, activation, and email lifecycle semantics, including UUID preservation requirements.
4. Propose an implementation mapping to the verified schema and contracts for review before adding repositories or auth dependencies.
5. Only after the integration design is reviewed, implement server-side JWT verification and narrowly scoped repositories. Keep privileged keys server-side and do not migrate or alter existing data structures without a separately authorized phase.

## Exact local files and configuration for a later Phase 2B

### Inspected local files

- Backend: `MATRIX_Backend/.env.example`, `MATRIX_Backend/app/core/config.py`, `MATRIX_Backend/app/main.py`, `MATRIX_Backend/app/api/v1/health.py`, `MATRIX_Backend/app/schemas/errors.py`, `MATRIX_Backend/app/schemas/health.py`, `MATRIX_Backend/requirements.txt`, `MATRIX_Backend/README.md`.
- Frontend: `n/package.json`, `n/README.md`, `n/src/app/App.tsx`, `n/src/features/auth/AuthPages.tsx`, `n/src/features/access/AccessPages.tsx`, `n/src/features/admin/AdminPage.tsx`, `n/src/features/products/ProductPages.tsx`.
- Inventory search covered local project file names for SQL files, Supabase config/migration/seed artifacts, and dotenv files. No frontend or backend `.env` file was present; backend `.env.example` is placeholders only.

### Existing backend configuration names reserved for integration

- `SUPABASE_URL`
- `SUPABASE_ANON_KEY`
- `SUPABASE_SERVICE_ROLE_KEY`
- `SUPABASE_JWT_ISSUER`
- `SUPABASE_JWKS_URL`
- `FRONTEND_ORIGINS`

These are configuration **names only**. No actual values were available or included. Phase 2B should obtain values through a secure local secret manager/environment process, never by pasting credentials into chat. The service-role key should only be used server-side if a verified requirement exists; it must never be exposed to the frontend. No claim is made that all these values will be needed by the final design.

## Change and access log

- **Remote Supabase:** not connected; no requests or database operations performed.
- **Database/Auth settings/schema/policies/functions/triggers:** unchanged; not accessed.
- **Frontend and n8n:** unchanged.
- **Backend application source/configuration:** unchanged.
- **Created:** this audit report only, at `MATRIX_Backend/docs/PHASE_2A_SUPABASE_AUDIT.md`.

## Final assessment

The requested audit is complete to the extent possible without remote access. It is **not a verified inventory of the existing Supabase project**. All remote architecture details remain unknown until read-only access is made available. No credentials or personal records were disclosed, and no database or existing application changes were made.
