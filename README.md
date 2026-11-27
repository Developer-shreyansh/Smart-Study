# Smart Study

Smart Study is a local AI-powered study assistant for the browser and Windows desktop. Both modes use the same FastAPI backend and SQLite data store.

## Included

- Data-driven dashboard, document library, PDF text extraction and reading
- AI tutor with optional document context and source pages
- Topic- and PDF-based quizzes with saved scores and answer explanations
- Study planner with completion tracking, overdue counts, filters, and task deletion
- Responsive light/dark design

Quiz generation uses the configured AI provider. PDF reading, greetings, and study planning remain available without an AI connection.

## Setup

Python 3.11–3.13 is recommended. Create an environment, install packages, then copy the environment template:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Set the provider key in `.env` (`GROQ_API_KEY`, `OPENROUTER_API_KEY`, or `GEMINI_API_KEY`) to enable AI. Keys remain on the backend and are never sent to the browser.

## Run

Web: `python main.py`, then visit `http://127.0.0.1:8000`. The browser app is installable as a Progressive Web App in supported browsers; use the **Install app** button when it appears or the browser's install option. The app shell can load offline, while uploads, saved data, and AI features require the backend connection.

Desktop: `python desktop.py`.

## Hosting the web app

Run the FastAPI app with a production ASGI server and bind it to the host-provided port (for example, `uvicorn backend.app:app --host 0.0.0.0 --port 8000`). Set AI provider keys as server-side environment variables; do not put them in frontend files. Public deployments need HTTPS for installation and a persistent data volume for the SQLite database and uploaded PDFs. This build stores data in a local SQLite database and is intended for a single app instance; use appropriate access controls before exposing private study documents publicly.

### Netlify frontend

The `netlify.toml` publishes `frontend/` and generates a same-origin `/api/*` proxy during deployment. Deploy the FastAPI backend first, then set `SMART_STUDY_API_URL` in the Netlify site's build environment to the backend base URL (for example, `https://your-api-host.example`, without a trailing slash). Import the repository into Netlify so its root `netlify.toml` is used. The backend remains a separate Python service; Netlify serves the web app and proxies its API requests.

## Storage and troubleshooting

PDFs live in `data/uploads` and SQLite data in `data/database/smart_study.sqlite3`. If startup fails, activate the environment and reinstall requirements. For Gemini errors, check the key, model, quota, and connection.
