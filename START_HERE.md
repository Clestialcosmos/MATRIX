# MATRIX — start here

This is the integrated MATRIX starter bundle. It contains `MATRIX_Backend`, `MATRIX_Frontend`, and a read-only copy of the supplied n8n workflow export in `reference/`.

## 1. Configure backend

Open `MATRIX_Backend/.env.example`, copy it to `MATRIX_Backend/.env`, and fill all existing Supabase/JWT/admin settings plus the existing n8n webhook URL and Header Auth header name/value. Add Resend settings only if your current activation email flow uses Resend.

## 2. Configure frontend

Open `MATRIX_Frontend/.env.example`, copy it to `MATRIX_Frontend/.env`, and fill only the Supabase project URL, public anon/publishable key, and FastAPI base URL. Never place service-role, n8n, or Resend secrets in frontend variables.

## 3. Run

Backend:

```bash
cd MATRIX_Backend
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Frontend in another terminal:

```bash
cd MATRIX_Frontend
npm install
npm run dev
```

Open the Vite URL (normally `http://localhost:5173`). See each folder's README for the detailed setup and test flow.

## Important before live Agent Layer testing

The supplied workflow export is inactive. This package does not activate or modify it. The existing workflow must be activated in n8n by you when ready; then use its production webhook URL and exact Header Auth credential in backend `.env`. A live assessment may consume Gemini and Brave Search credits. Start with one deliberate test only. A timeout leaves the assessment pending; check history before any resubmission.

The backend's local tests passed (76). The frontend production build could not be run in the packaging environment because npm dependency installation timed out; run `npm install` and `npm run build` locally before live testing.

No real `.env` files or secrets are included. No Supabase schema/policies or n8n workflow were changed. The older Colab ML model is not called.
