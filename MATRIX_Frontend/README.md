# MATRIX — integrated starter

This package connects the MATRIX React frontend to the existing FastAPI backend, Supabase Auth/profile activation, the existing synchronous n8n Agent Layer webhook, and private PDF report storage.

## Before first run

1. Keep the supplied n8n workflow unchanged. Confirm its existing Header Auth credential matches the backend-only `N8N_AUTH_HEADER_NAME` and `N8N_AUTH_HEADER_VALUE` values.
2. The supplied workflow export is inactive. Its production webhook will not accept requests until you activate that existing workflow in n8n. Do this only when you are ready to begin controlled testing; this code does not activate or modify it.
3. The Supabase service-role key is required by the backend for the existing `products`, `analyses`, `reports` tables and private `matrix-reports` bucket. It is never used by the browser. Keep it secret.
4. The code does not create or modify Supabase tables, columns, policies, triggers, RPCs, or buckets. It expects the existing schema described in `MATRIX_Backend/docs/PHASE_2A_SUPABASE_AUDIT.md`.

## Configure environment

### Backend

```bash
cd MATRIX_Backend
cp .env.example .env
```

Fill the existing Supabase values:

- `SUPABASE_URL`: existing project URL
- `SUPABASE_ANON_KEY`: existing public anon/publishable key
- `SUPABASE_SERVICE_ROLE_KEY`: existing service-role key (backend only)
- `SUPABASE_JWT_ISSUER`: `https://YOUR_PROJECT_REF.supabase.co/auth/v1`
- `SUPABASE_JWKS_URL`: `https://YOUR_PROJECT_REF.supabase.co/auth/v1/.well-known/jwks.json`
- `SUPABASE_JWT_AUDIENCE`: the audience configured for your Supabase JWTs (commonly `authenticated`; verify your project)
- `SUPABASE_PROFILE_USER_ID_COLUMN`: `id` for the verified `profiles.id` UUID
- `MATRIX_ADMIN_USER_ID`: the designated admin Auth UUID
- `N8N_WEBHOOK_URL`: the existing active production webhook URL ending in `/webhook/matrix-agent-layer`
- `N8N_AUTH_HEADER_NAME` / `N8N_AUTH_HEADER_VALUE`: exact header name/value configured by the existing n8n Header Auth credential

`RESEND_API_KEY` and `MATRIX_EMAIL_FROM` are needed only if your existing admin activation-code email flow uses Resend.

Install and run:

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Frontend

```bash
cd MATRIX_Final_Frontend
cp .env.example .env
```

Fill only browser-safe values:

- `VITE_SUPABASE_URL`
- `VITE_SUPABASE_ANON_KEY`
- `VITE_FASTAPI_BASE_URL` (for local use `http://127.0.0.1:8000`)

Never put the service-role key, n8n credentials, Resend key, or other private keys in frontend `.env` or any `VITE_` variable.

```bash
npm install
npm run dev
```

For a production frontend build: `npm run build`.

## First controlled test

1. Start FastAPI and Vite.
2. Register and verify an account using the Supabase email link.
3. Sign in.
4. Complete the existing admin approval and activation-code process; enter the code at `/activate`.
5. Confirm `/api/v1/me/access` returns `has_matrix_access: true`.
6. Confirm the n8n workflow is active and the backend webhook URL/header are correct.
7. Submit one small, deliberate pre-launch assessment. **Each real submission can consume Gemini and Brave Search credits.** Do not use repeated test submissions. A timeout leaves the record pending because n8n may still be executing; check the assessment history before considering another run.

## API endpoints added

- `POST /api/v1/assessments` — authenticated, activated user; synchronous n8n execution
- `GET /api/v1/assessments` and `GET /api/v1/assessments/{id}` — caller-owned history/details
- `GET /api/v1/reports` — caller-owned report list
- `GET /api/v1/reports/{id}/url` — short-lived signed URL after ownership check

Assessment payload must match the current workflow contract: `product_name`, `target_market`, `decision_type`, `currency`, `product_category`, `launch_stage=pre_launch`, `planned_selling_price`, `expected_sales_quantity`, `estimated_unit_cost`, `planned_marketing_budget`, and optional `intended_launch_period`.

The older Colab ML model is not called. The Agent Layer remains independent.

## Validation performed for this handoff

- Backend Python compilation passed.
- Backend test suite: 76 passed.
- No live Supabase, n8n, Gemini, Brave Search, or email requests were made.
- Frontend production build could not be verified in this environment because dependency installation timed out; run `npm install` and `npm run build` locally before live testing.


### Admin portal

The Admin Portal navigation is shown only after the backend accepts the signed-in user at `GET /api/v1/admin/profiles/pending`. Set `MATRIX_ADMIN_USER_ID` in the backend `.env` to the same signed-in Supabase Auth user UUID, restart the backend, and sign in again. The portal uses the existing protected endpoints to approve pending profiles and send activation-code emails. It does not manage demo Premium requests.
