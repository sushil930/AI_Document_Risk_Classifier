# DocuGuard AI

DocuGuard AI is a shared, full-stack document review workspace with no sign-in or user accounts. It extracts text from PDF, DOCX, and TXT uploads and classifies documents locally. LLM reviews are optional; the Ask AI tab can answer questions about a stored document or general topics using Gemini, with configured Groq Cloud fallback.

Analysis results are AI generated review recommendations. They are not legal advice, a calibrated probability of harm, or a compliance certification. A human should verify every finding against the source document.

## Architecture

- `backend/`: Django 5, Django REST Framework, SQLite locally or PostgreSQL via `DATABASE_URL`, private media storage, document extraction, Gemini/Groq analysis, and an offline-trained classifier service. The API has no login or user access controls.
- `frontend/`: React, Vite, TypeScript, Tailwind CSS, React Router, TanStack Query, Recharts, and Lucide icons.
- `docker-compose.yml`: local Postgres, Django API, and Vite development server.

## Features

- Shared workspace for PDF, DOCX, and TXT uploads with extraction preview, extension/size checks, and server-side parsing.
- No account creation, login, logout, sessions, or CSRF flow.
- Optional Ask AI workspace for document-grounded or general questions; no conversation is persisted. Configurable Gemini and Groq model selection, automatic Groq fallback when Gemini reports an unavailable model or HTTP 5xx response, structured JSON output validation, one repair attempt for invalid model output, long-document sequential chunk review, and explicit unable-to-assess results for empty/scanned content.
- TF-IDF word/character risk classification with persisted class scores, model version, and manual-review reasons. High and uncertain predictions are routed to review; showcase candidate predictions always require human review.
- A filterable manual-review queue stores reviewer state, human-assessed class, and notes separately from immutable model predictions. The dashboard shows current classifier counts and review decisions; a performance page displays the latest sealed evaluation and release gate. The shared no-login app does not verify reviewer identity.
- Evidence, recommended actions, limitations, dashboard statistics from stored records, history search and filters, deletion, JSON/PDF report downloads, and light/dark preferences.
- Health endpoint at `/api/health/`.

## Requirements

- Python 3.11 or newer (tested with Python 3.12)
- Node.js 20 or newer and npm
- A Gemini API key and/or Groq Cloud API key only for optional Ask AI and LLM review; local classification and uploads work without provider keys
- Docker Desktop is optional

## Local setup (Windows PowerShell)

From the project root:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend\requirements.txt
Copy-Item backend\.env.example backend\.env
```

Edit `backend/.env`, set a long random `DJANGO_SECRET_KEY`, and add `GEMINI_API_KEY` and `GROQ_API_KEY`. Either provider can be configured alone. Keys stay on the Django server and must never be placed in a `VITE_` variable. Gemini model IDs and the Groq fallback model are configurable. Gemini model-not-found and server errors (HTTP 5xx) trigger a Groq fallback when its key and model are configured; quota, authentication, network, and malformed-response errors do not trigger a silent provider switch. The report records the model that completed an opted-in LLM review; ordinary classification does not send text to a provider.

To enable the showcase classifier, first train its calibrated candidate as described in [classifier training](docs/classifier/training.md), then set `CLASSIFIER_MODEL_PATH` to that artifact's `model.joblib` path and `CLASSIFIER_ALLOW_CANDIDATE=true` in `backend/.env`. Candidate predictions are persisted but always require human review. Leave the path empty to run without classifier predictions.

In a backend terminal:

```powershell
cd backend
..\.venv\Scripts\python.exe manage.py migrate
..\.venv\Scripts\python.exe manage.py runserver
```

In a frontend terminal:

```powershell
cd frontend
npm install
Copy-Item .env.example .env
npm run dev
```

Open [http://localhost:5173](http://localhost:5173). API defaults to [http://localhost:8000/api](http://localhost:8000/api). For Linux/macOS, create the venv with `python3 -m venv .venv`, activate with `source .venv/bin/activate`, and use `python manage.py ...` from `backend/`.

## Docker Compose

Copy `backend/.env.example` to `backend/.env`, set secrets, then run `docker compose up --build`. The compose profile starts PostgreSQL, Django, and Vite. The local compose database password is only for development; replace it and use production-grade secrets before deployment.

## AI providers

Create a Gemini API key in [Google AI Studio](https://aistudio.google.com/apikey) and/or a Groq Cloud API key in [Groq Console](https://console.groq.com/keys), then set `GEMINI_API_KEY` and/or `GROQ_API_KEY` in `backend/.env`. Gemini uses Google's `google-genai` SDK. Groq uses the OpenAI-compatible Python SDK at `https://api.groq.com/openai/v1`. Configure `GEMINI_DEFAULT_MODEL`, `GEMINI_MODELS`, `GROQ_DEFAULT_MODEL`, `GROQ_MODELS`, and `GROQ_FALLBACK_MODEL` as needed. The default Groq fallback is `openai/gpt-oss-120b`; check current model availability and account access in your provider consoles.

If a Gemini model is not found (HTTP 404) or Gemini returns an HTTP 5xx response, the backend retries the full analysis with the configured Groq fallback model. It does not switch providers for rate limits, authentication failures, timeouts, connectivity errors, or malformed output. Settings show whether each server-side key is present without exposing its value, and results record the provider/model that produced the report. Automated tests mock both providers and do not make paid API calls.

The analyzer labels source page or paragraph markers where available. Documents are processed sequentially in chunks so the full extracted text up to `MAX_DOCUMENT_CHARS` is considered; documents exceeding that explicit processing limit return an error instead of silently truncating the analysis. Scanned PDFs without extractable text return `unable_to_assess`; OCR is not included.

The classifier runs locally on extracted text and returns class scores rather than probabilities of harm. Its showcase artifact was trained from AI-assisted labels accepted by the project owner in aggregate; it is not independently dual-human reviewed, calibrated for production, or promoted. Candidate predictions require manual review.

## API

All workspace API endpoints are public and shared. No authentication or CSRF cookie is used. LLM calls are opt-in from the app; `/api/ask-ai/` accepts a question and an optional stored document ID. Anyone who can reach the backend can view, upload, analyze, export, and delete workspace records.

| Method      | Endpoint                            | Purpose                                                           |
| ----------- | ----------------------------------- | ----------------------------------------------------------------- |
| GET         | `/api/health/`                    | Health check                                                      |
| GET         | `/api/dashboard/`                 | Database-backed metrics and recent activity                       |
| GET         | `/api/model-performance/`         | Latest sealed evaluation and release-gate report                  |
| GET         | `/api/reviews/`                   | Paginated manual-review queue (`status`, `priority`, `score_band`, `reason`, `start`, `end`, `ordering`) |
| POST        | `/api/reviews/{classification_id}/decision/` | Save review status, human-assessed class, and optional note; model prediction is unchanged |
| POST, GET   | `/api/documents/`                 | Upload and list shared documents                                   |
| GET, DELETE | `/api/documents/{id}/`            | Read or delete shared document                                     |
| POST        | `/api/documents/{id}/analyze/`    | Classify locally; optionally set `include_ai: true` and select an LLM model |
| POST        | `/api/ask-ai/`                    | Ask an optional question with optional `document_id`, `model`, and conversation history |
| GET         | `/api/analyses/`                  | Paginated history (`search`, `priority`, `type`, `model`) |
| GET         | `/api/analyses/{id}/`             | Analysis result                                                   |
| GET         | `/api/analyses/{id}/export/json/` | JSON report                                                       |
| GET         | `/api/analyses/{id}/export/pdf/`  | PDF report                                                        |

Review decisions are stored separately from classifier predictions. This workspace has no accounts, so it does not verify reviewer identity. The final class and note are shared workspace records and must not be treated as independently attributable sign-off.
| GET, PATCH  | `/api/settings/`                  | Workspace preferences and provider configured status                |

## Tests and builds

```powershell
.\.venv\Scripts\python.exe -m pytest backend
```

```powershell
cd frontend
npm test
npm run build
npm run lint
```

The backend suite covers no-login public access, extraction for supported formats, empty/scanned input, provider unconfigured and mocked analysis paths, output validation, shared history, dashboard metrics, report exports, classifier provenance, and review routing. A live provider integration test is not enabled by default.

## Security and data handling

- Uploaded files are stored under backend media storage and are not served as public URLs. The API itself has no authentication or per-user access control: anyone who can reach it can read and delete workspace records. Keep the app on a trusted local/private network; do not expose it directly to the internet.
- Files and extracted text are retained until a document or analysis is deleted (analysis deletion also removes its associated document and file). Automated retention expiry is not implemented yet.
- A provider receives document text only when you opt into LLM review or submit a question in Ask AI. Review provider account terms before sending sensitive material.
- Do not commit `.env` files. The no-login API is intended for a trusted local/private network and is not suitable for public internet deployment without an access-control layer. Production must set a unique `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=false`, restrictive `DJANGO_ALLOWED_HOSTS`, HTTPS, and a protected PostgreSQL/file-storage service.
- Django static collection is configured at `backend/staticfiles`; configure a production static server and private object/file storage as part of deployment.

## Current limitations

- OCR and automatic retention expiry are not implemented.
- Live Gemini and Groq generation access depends on keys configured in the local backend environment. The Settings page reports whether each server-side key is present, but does not verify live model generation.
- Provider configuration and selected model availability depend on the account and models enabled there.
- The showcase classifier uses a small, synthetic-heavy, AI-labeled corpus with no real-source High examples. Its reported evaluation is demonstration-only, and every candidate prediction requires manual review.
- Deployment configuration is provided as a starting point; production deployment has not been performed or verified.
