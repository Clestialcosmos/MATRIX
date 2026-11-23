# MATRIX Backend

FastAPI backend for the existing Supabase authentication/activation flow and the synchronous MATRIX Agent Layer integration.

## Configure

Copy `.env.example` to `.env` and fill the values for the existing Supabase project, designated administrator, and existing n8n Header Auth credential. Do not commit `.env`.

- `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_JWT_ISSUER`, `SUPABASE_JWKS_URL`, `SUPABASE_JWT_AUDIENCE`: existing Supabase project and JWT configuration.
- `SUPABASE_PROFILE_USER_ID_COLUMN=id`: verified `profiles.id` identity column.
- `SUPABASE_SERVICE_ROLE_KEY`: backend-only key for server-side persistence and private report storage. Never expose to the browser.
- `N8N_WEBHOOK_URL`: existing production webhook URL for `matrix-agent-layer`.
- `N8N_AUTH_HEADER_NAME` and `N8N_AUTH_HEADER_VALUE`: exact header configured by the existing n8n Header Auth credential.
- `FRONTEND_ORIGINS`: comma-separated exact frontend origins.
- `MATRIX_ADMIN_USER_ID`: designated administrator Auth UUID.

The existing n8n export supplied with the project is inactive. This backend does not activate or alter it. The production webhook requires that existing workflow to be active before requests can succeed.

## Run locally

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Open `http://127.0.0.1:8000/docs` for API documentation.

## Added endpoints

- `POST /api/v1/assessments`
- `GET /api/v1/assessments`
- `GET /api/v1/assessments/{assessment_id}`
- `GET /api/v1/reports`
- `GET /api/v1/reports/{report_id}/url`

All endpoints require a verified Supabase bearer JWT and active global MATRIX access. The user UUID is derived from the JWT. Read operations filter by the authenticated owner. The n8n request is server-to-server and synchronous.

A workflow timeout leaves the analysis in `pending` because n8n may still be running. The API does not automatically retry. A successful AI result remains `completed` even if PDF generation/storage fails.

No Colab ML model is called. No Supabase schema, policy, trigger, function, or n8n workflow is created or modified by this code.

## Supabase Storage setup

Create a **private** bucket named `matrix-reports` in your Supabase Storage dashboard before running assessments (Dashboard → Storage → New Bucket → name: `matrix-reports`, toggle Public OFF). The backend uploads signed private PDFs to this bucket; it **must not** be public. The bucket name must match `MATRIX_REPORT_BUCKET` in `.env` (default: `matrix-reports`).

## Tests

```bash
pytest -q
```

Current handoff result: 76 passed. Tests use local/mocked behavior; no live Supabase, n8n, Gemini, Brave Search, or email requests were made.


## Agent Layer response and report persistence

The assessment endpoint accepts the existing structured `{"status":"success", ...}` response and common n8n report outputs such as `{"output":"<report markdown>"}` or `[{"output":"<report markdown>"}]`. A successful plain-text/Markdown report is normalized, saved as the assessment result, rendered into a PDF, uploaded to the private `MATRIX_REPORT_BUCKET`, and inserted into the existing `reports` table.

If the assessment completes but the report does not appear, check the backend terminal for `report_generation_or_upload_failed`. The exception identifies whether the configured Storage bucket, upload, or `reports` table insert failed. The backend does not create or alter Supabase schema, buckets, policies, or the n8n workflow.
