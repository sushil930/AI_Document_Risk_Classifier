# DocuGuard AI

DocuGuard AI is a browser-local document triage and review app. It accepts PDF, DOCX, and TXT files, extracts text and runs a configured classifier through Django, then saves the file copy, extracted text, analysis report, and review decisions in the current browser profile using IndexedDB. The server does not create a document-history record for new uploads.

This is a showcase project, not a legal adviser, compliance certification tool, calibrated measure of harm, or production-ready multi-user service. Verify model output against the source document.

## What it does

- Upload and preview PDF, DOCX, and TXT files, with server-side type and size validation.
- Classify extracted text into Low, Medium, or High review priority when a classifier artifact is configured.
- Show class scores, influential terms, and similar training examples as model explanations. These are signals, not evidence or probabilities of harm.
- Route high-priority, uncertain, and showcase-candidate predictions to a manual-review queue.
- Optionally request a structured LLM document review with evidence excerpts, explanations, recommended actions, and limitations.
- Use **Ask AI** for an on-demand conversation with optional context from a document in this browser. Replies support Markdown.
- View dashboard metrics, history, review decisions, and the configured classifier evaluation report. Document-derived dashboard and history data come from this browser's IndexedDB.
- Export reports as JSON or PDF; switch between light and dark themes.

## Data flow and architecture

```mermaid
flowchart LR
    Person[Reviewer]
    subgraph Browser[This browser profile]
        UI[React app]
        IDB[(IndexedDB: files, extracted text, reports, review decisions)]
        Prefs[Local preferences]
        UI <--> IDB
        UI <--> Prefs
    end
    subgraph API[Django API: request processing]
        Routes[Validation and API routes]
        Extract[PDF DOCX TXT extraction]
        Classifier[Local TF-IDF classifier]
        LLM[Optional LLM analysis and Q and A]
        Routes --> Extract --> Classifier
        Extract --> LLM
    end
    Artifact[(Classifier artifact)]
    Gemini[Google Gemini]
    Groq[Groq Cloud fallback]
    Person --> UI
    UI -->|temporary upload or text request| Routes
    Classifier --> Artifact
    LLM --> Gemini
    Gemini -. configured fallback .-> Groq
```

The browser never receives provider API keys. New document analysis requests are handled in memory by the API: the server validates and extracts the upload, runs the classifier, and returns the result without creating a document, analysis, or uploaded-file record in the server database or file storage. The frontend then saves the file copy and report in IndexedDB on that browser profile. Ask AI and optional LLM analysis send text to the configured provider only when requested. Provider retention follows that provider's terms.

### Main document workflow

```mermaid
sequenceDiagram
    actor User
    participant UI as React app
    participant Local as Browser IndexedDB
    participant API as Django API
    participant Extract as Text extraction
    participant Classifier as Local classifier
    participant LLM as Optional Gemini or Groq
    User->>UI: Choose PDF, DOCX, or TXT
    UI->>API: POST /documents/preview/ for preview
    API->>Extract: Validate and extract temporarily
    Extract-->>UI: Preview text
    User->>UI: Submit analysis
    UI->>API: POST /documents/analyze-local/ (multipart)
    API->>Extract: Validate and extract in request
    Extract->>Classifier: Classify extracted text
    opt User enabled optional AI review
        Extract->>LLM: Send text for structured review
        LLM-->>Extract: Findings and limitations
    end
    API-->>UI: Return analysis; do not create history records
    UI->>Local: Save file, text, result, and review state
    User->>Local: Search, review, export, or delete local history
```

### Ask AI workflow

1. Open **Ask AI** and optionally select a document saved in this browser.
2. Submit a question. The selected document text is sent in that API request and is not looked up from a server-side history record.
3. The API calls the selected provider and returns the answer and actual model used.
4. Conversation turns remain in the current page view and are not persisted.

### Local history and review

History, dashboard document metrics, analysis results, review decisions, and saved file copies belong to the current browser profile. They do not sync across browsers or devices and are not visible to other visitors. Clearing the site's browser storage removes them. Browser storage limits apply. Deleting a document from History removes its local file copy, extracted text, and associated analysis records.

The current release stops serving legacy shared document and analysis records through the API. It does not automatically delete records or files created by older versions from the deployed database/storage; those older records require a separate cleanup decision.

## Technology and project layout

- **Frontend:** React, Vite, TypeScript, Tailwind CSS, React Router, TanStack Query, Recharts, Lucide, `react-markdown`, and `remark-gfm`.
- **Backend:** Django, Django REST Framework, Django ORM, SQLite by default, PostgreSQL through `DATABASE_URL`.
- **Extraction:** PyMuPDF for PDF, `python-docx` for DOCX, Python's standard library for TXT.
- **AI providers:** Google Gemini SDK and the OpenAI-compatible Python client for Groq Cloud.
- **Classifier:** scikit-learn TF-IDF features and a trained classifier artifact loaded by the Django service.

```text
.
??? backend/
?   ??? apps/core/                 # Models, serializers, API views, extraction, AI, classifier
?   ??? config/                    # Django settings and URL configuration
?   ??? model_artifacts/           # Local generated artifacts; ignored by Git
?   ??? private_uploads/           # Local uploaded files; ignored by Git
?   ??? manage.py
?   ??? requirements.txt
?   ??? .env.example
??? data/
?   ??? docuguard_corpus_v0.1/     # Showcase corpus, manifests, and original formats
?   ??? classifier_corpus/         # Training instructions, template, draft examples
??? docs/classifier/               # Rubric, training guide, candidate evaluation report
??? frontend/src/                  # React pages, API client, components, and styles
??? docker-compose.yml              # Optional local PostgreSQL/Django/Vite environment
??? README.md
??? UPGRADE_PLAN.md                 # Classifier upgrade phases and status
```

The workspace navigation includes **Overview**, **New analysis**, **Ask AI**, **Document history**, **Flagged review**, **Model performance**, and **Settings**. Classification is the standard local workflow; LLM use is a user action rather than a prerequisite.

The main backend responsibilities are `apps/core/views.py` (REST workflows), `serializers.py` (API representation), `models.py` (documents, analyses, classifier outputs, and review decisions), `extraction.py` (file parsing), `classifier_service.py` (artifact loading and inference), `classifier_training.py` (candidate training and evaluation), and `services.py` (Gemini/Groq calls and structured LLM reports). On the frontend, `src/api.ts` is the fetch boundary, `src/App.tsx` owns routes and workspace pages, and `src/pages/` and `src/components/` contain feature views and reusable UI.

## Requirements

- Python 3.11 or newer; the project has been run with Python 3.12.
- Node.js 20 or newer and npm.
- Gemini and/or Groq API credentials only if you want to use Ask AI or request an LLM document review. Upload and local classification do not require provider credentials.
- Docker Desktop only if you want the optional Docker Compose setup.

## Run locally

### Windows PowerShell

From the repository root, create a virtual environment and install Python dependencies:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend\requirements.txt
Copy-Item backend\.env.example backend\.env
Copy-Item frontend\.env.example frontend\.env
```

Edit `backend/.env` before starting the server:

- Set a unique `DJANGO_SECRET_KEY` for your local environment.
- Configure one or both AI provider keys if you intend to use LLM features. If you want local-only use, leave `GEMINI_API_KEY` and `GROQ_API_KEY` blank instead of keeping the example placeholder values.
- Set `CLASSIFIER_MODEL_PATH` and `CLASSIFIER_ALLOW_CANDIDATE=true` if you have trained and want to load the showcase classifier artifact.

Start Django in one terminal:

```powershell
Set-Location backend
..\.venv\Scripts\python.exe manage.py migrate
..\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

Start Vite in another terminal:

```powershell
Set-Location frontend
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173). The Vite API URL defaults to `http://localhost:8000/api` in `frontend/.env.example`.

If port 8000 is occupied on your machine, run Django on another port and point Vite at it. For example, from the `backend` directory:

```powershell
..\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8001
```

Then set the public frontend setting in `frontend/.env` and restart Vite:

```env
VITE_API_URL=http://localhost:8001/api
```

Do not put provider keys in frontend environment variables. Anything prefixed with `VITE_` is public browser configuration.

### Linux and macOS

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.txt
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env
```

Configure `backend/.env`, then run Django from `backend/`:

```bash
cd backend
../.venv/bin/python manage.py migrate
../.venv/bin/python manage.py runserver 127.0.0.1:8000
```

In a second terminal, run the frontend:

```bash
cd frontend
npm install
npm run dev
```

### Optional Docker Compose

Docker Compose starts PostgreSQL, Django, and Vite. It is not required for local development.

```powershell
Copy-Item backend\.env.example backend\.env
# Edit backend/.env and set DJANGO_SECRET_KEY and any provider keys.
docker compose up --build
```

The Compose database password is a development-only value. Do not reuse it in a deployment. Stop the services with `Ctrl+C`; `docker compose down` stops the stack, while `docker compose down -v` also deletes its database and upload volumes.

## Environment configuration

`backend/.env.example` documents the backend settings:

| Setting | Purpose |
| --- | --- |
| `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS` | Django environment and host settings |
| `DATABASE_URL` | Database connection; defaults in the Django settings to local SQLite when omitted |
| `FRONTEND_ORIGIN` | Allowed browser origin for CORS, normally `http://localhost:5173` |
| `MAX_UPLOAD_MB` | Maximum upload size; default is 20 MB |
| `MAX_DOCUMENT_CHARS` | Maximum extracted document length accepted by the LLM analysis service; default is 500,000 characters |
| `GEMINI_API_KEY`, `GEMINI_DEFAULT_MODEL`, `GEMINI_MODELS`, `GEMINI_TIMEOUT_SECONDS` | Gemini credentials, allowed models, and timeout |
| `GROQ_API_KEY`, `GROQ_BASE_URL`, `GROQ_DEFAULT_MODEL`, `GROQ_MODELS`, `GROQ_FALLBACK_MODEL`, `GROQ_TIMEOUT_SECONDS` | Groq Cloud credentials, OpenAI-compatible API URL, models, and fallback |
| `CLASSIFIER_MODEL_PATH` | Path to a trained local `model.joblib`; blank disables local predictions |
| `CLASSIFIER_ALLOW_CANDIDATE` | Explicitly permits a non-approved showcase candidate to serve predictions |
| `CLASSIFIER_MIN_WORDS` | Minimum extracted words required for classifier inference |

`frontend/.env.example` contains only `VITE_API_URL`, the public base URL for the Django API. Never add secrets to frontend configuration.

### Configure a provider

Create a key in [Google AI Studio](https://aistudio.google.com/apikey) and/or [Groq Console](https://console.groq.com/keys). Add it to `backend/.env` and restart Django. The Settings page reports whether a key is configured without returning its value; it does not test live model availability. Model IDs and access depend on your provider account. The Groq API uses `https://api.groq.com/openai/v1` by default.

The selected model is not silently replaced after ordinary errors. Gemini model-not-found and server errors can use the configured Groq fallback. If the fallback is not configured or also fails, the API returns an actionable error and does not fabricate an analysis.

### Train and enable the showcase classifier

The checked-in showcase data is AI-assisted and owner-approved in aggregate. It is not independently dual-human reviewed, production approved, or suitable for production performance claims. Training produces a candidate; it does not promote a production model. Read [the classifier training guide](docs/classifier/training.md) and [the candidate report](docs/classifier/showcase_candidate_report.md) before training or enabling it.

```mermaid
flowchart LR
    Corpus[Reviewed manifest and text corpus] --> Train[train_classifier command]
    Train --> Artifact[Versioned local candidate artifact]
    Artifact --> Eval[Sealed test report and promotion gate]
    Artifact --> Config[CLASSIFIER_MODEL_PATH plus explicit candidate opt-in]
    Config --> Runtime[Local document classification]
    Eval --> Human[Human assesses whether candidate is useful]
    Human -. no automatic promotion .-> Config
```

From the repository root in PowerShell:

```powershell
.\.venv\Scripts\python.exe backend\manage.py train_classifier `
  --manifest data\docuguard_corpus_v0.1\manifest_showcase_approved.csv `
  --output-dir backend\model_artifacts\candidates `
  --code-version showcase-local `
  --allow-showcase-owner-approval `
  --calibrate-for-review
```

Set `CLASSIFIER_MODEL_PATH` to the resulting `model.joblib` path in `backend/.env` and explicitly set `CLASSIFIER_ALLOW_CANDIDATE=true`. Restart Django after changing the artifact path. Candidate predictions are sent to manual review. The generated artifacts are ignored by Git and are not included when someone clones the repository.

## API overview

All routes are mounted below `/api/`. The app has no accounts. New document history is stored in browser IndexedDB; the backend endpoints below process requests without adding document-history rows.

| Method | Endpoint | Description |
| --- | --- | --- |
| `GET` | `/api/health/` | Health check (`{"status":"ok"}`) |
| `GET` | `/api/settings/` | Configured model IDs, provider-key presence, upload limit, and classifier status; never returns keys |
| `GET` | `/api/model-performance/` | Evaluation and promotion-gate information for the configured artifact |
| `POST` | `/api/documents/preview/` | Validate and extract a temporary upload preview (multipart field `file`) |
| `POST` | `/api/documents/analyze-local/` | Analyze a temporary upload (multipart fields `file`, optional `include_ai`, and `model`); returns a report without saving server history |
| `POST` | `/api/ask-ai/` | Ask a question with `question`, optional browser-supplied `document_text` and `document_name`, configured `model`, and short `history` |
| `POST` | `/api/export/pdf-local/` | Render a report supplied by the browser as a PDF without looking up a stored analysis |

Legacy document, analysis, review, dashboard, and settings-write endpoints are not used for browser history. The old document-history APIs return no shared history or reject persistence.

Example Ask AI request:

```json
{
  "question": "When can either party terminate this agreement?",
  "document_name": "agreement.txt",
  "document_text": "...text extracted from the browser's local document...",
  "model": "gemini-3.8-flash",
  "history": []
}
```

The response contains the answer, actual model used (including fallback), and document name. Ask AI conversation history is not persisted.

## Tests and builds

Run the backend tests from `backend/`:

```powershell
..\.venv\Scripts\python.exe -m pytest
```

Or on Linux/macOS:

```bash
../.venv/bin/python -m pytest
```

Run frontend tests, type-check/build, and lint from `frontend/`:

```bash
npm test
npm run build
npm run lint
```

Provider calls are mocked in automated tests; the normal test suite does not need paid provider access. Do not put live provider keys in test fixtures.

## Security, privacy, and data retention

- **Browser-local history:** New uploads, extracted text, reports, and review decisions are saved in IndexedDB in the browser profile that created them. They are not added to shared server history or synced to other devices. Clearing site data removes the local history; browser storage quotas apply.
- **Transient server processing:** The Django API receives upload bytes to validate, extract text, and run the classifier, then returns a response without creating document-history or uploaded-file records. As with any hosted API, infrastructure may process request data in memory and retain operational logs according to its hosting configuration.
- **Provider privacy:** The classifier runs locally on the API server. An LLM receives document text only when optional AI review is enabled or when a user submits Ask AI with document context. Check provider terms before sending sensitive material.
- **Legacy server data:** This version disables serving old shared history and does not write new history, but it does not purge database rows or files created by earlier app versions. Those older records remain until separately deleted from the deployment.
- **Secrets:** `.env` files are ignored by Git. Keep provider keys server-side and use a unique Django secret outside local development.
- **Untrusted model output:** LLM findings are validated before returning and rendered as text/Markdown. The Ask AI Markdown renderer does not enable raw HTML. Treat all model output as unverified.

For a real deployment, add authentication, per-user access control, HTTPS, restrictive `DJANGO_ALLOWED_HOSTS` and `FRONTEND_ORIGIN`, managed PostgreSQL, and protected file storage for any other server-side data. `collectstatic` writes to `backend/staticfiles/`. Deployment has not been performed or verified.

## Known limitations

- OCR is not included. Scanned PDFs without extractable text return unable-to-assess rather than an invented priority.
- LLM analysis accepts extracted text up to `MAX_DOCUMENT_CHARS`; it processes long inputs sequentially in chunks and consolidates the section reports. Inputs over the configured limit fail explicitly instead of silently analyzing only a prefix.
- Ask AI sends the selected document's extracted text as context. Very long text may exceed the selected provider's context limits; the API reports provider errors rather than silently truncating it.
- Classifier scores are model scores, not calibrated harm probabilities. The showcase corpus is synthetic-heavy and AI-assisted, and its evaluation currently fails the conservative release gate. Candidate results require human review.
- Browser-local history is isolated by browser profile, not by a user login. Anyone using the same browser profile can access its saved history.
- Current Docker Compose configuration is for local development. No production deployment or production security review has been completed.
