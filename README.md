# Bulk Certificate Generator

A FastAPI backend that accepts a list of recipients in one request, generates a PDF certificate for each from a single predefined template, tracks progress per job, and lets clients retrieve the results.

**Stack:** Python 3.10+, FastAPI, SQLAlchemy 2 (SQLite by default), ReportLab (PDF), pytest.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Run

```bash
uvicorn app.main:app --reload
```

Web UI: http://127.0.0.1:8000/ (single static page, no build step)

Interactive API docs: http://127.0.0.1:8000/docs

Configuration (environment variables, all optional):

| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./certificates.db` | Any SQLAlchemy URL (e.g. PostgreSQL) |
| `CERT_DIR` | `./certificates` | Where generated PDFs are stored |
| `MAX_RECIPIENTS_PER_JOB` | `5000` | Larger requests get HTTP 413 |

## Tests

```bash
python -m pytest
```

## API

### Submit a job — `POST /jobs`

```bash
curl -X POST http://127.0.0.1:8000/jobs -H "Content-Type: application/json" -d '{
  "title": "Python 101",
  "issuer": "Acme Academy",
  "issue_date": "2026-01-15",
  "recipients": [
    {"name": "Asha Rao", "email": "asha@example.com"},
    {"name": "Ben Lee"},
    {"name": "", "email": "broken"}
  ]
}'
```

Returns **202 Accepted** immediately with the job summary (`id`, `status`, counts). Certificates are generated in the background.

### Check progress — `GET /jobs/{id}`

Returns the job `status`, counts (`total`, `succeeded`, `failed`, `pending`) and one entry per recipient with its `status`, `error` (if failed) and `download_url` (if succeeded).

Job statuses: `pending` → `processing` → `completed` (all ok) / `completed_with_errors` (some failed) / `failed` (none succeeded).

### Retrieve certificates

- One certificate (PDF): `GET /jobs/{id}/certificates/{certificate_id}` (the `download_url` from the status response)
- All successful certificates as a ZIP: `GET /jobs/{id}/download`

```bash
curl -o all.zip http://127.0.0.1:8000/jobs/<job_id>/download
```

### Error responses

| Code | When |
|---|---|
| 422 | Malformed request: missing/blank `title`, `issuer`, `issue_date`, or empty `recipients` |
| 413 | More than `MAX_RECIPIENTS_PER_JOB` recipients |
| 404 | Unknown job or certificate |
| 409 | Certificate failed/not ready, or ZIP requested with nothing generated |

## Design decisions

**Asynchronous processing (FastAPI `BackgroundTasks`).** A job can contain thousands of recipients, so generating inline would hold the HTTP request open and risk client/proxy timeouts. `POST /jobs` validates, persists the job, returns 202 and a job id, and the client polls `GET /jobs/{id}`. I chose `BackgroundTasks` over Celery/RQ to keep the project runnable with zero extra infrastructure. The trade-off: if the server process dies mid-job, the job stays in `processing` and is not auto-resumed, and work runs in the API process. `services.process_job(job_id)` is a plain function of a job id, so moving it to a real queue is a small change (enqueue the id instead of `add_task`) and it is idempotent—it only processes certificates still `pending`.

**Two levels of validation.**
- *Request level* (422): the job itself is unusable (no title, no recipients). Nothing is stored.
- *Recipient level*: a bad recipient (missing name, malformed email, over-long name) does **not** reject the request. It is stored as a `failed` certificate with a clear `error`, so one typo in a 1,000-row list doesn't force the client to resubmit everything, and the client sees exactly which rows failed. This happens synchronously at submit time, so the first status response already shows validation failures.

**Failure isolation.** Each certificate is rendered inside its own `try/except` and committed individually. A rendering failure marks only that certificate `failed` (partial file removed) and the job continues. Committing per certificate also makes progress visible while the job runs and means a crash doesn't lose finished work. An unexpected job-level exception sets the job to `failed` rather than leaving it stuck.

**Template.** One hard-coded landscape A4 PDF layout in `app/generator.py` (ReportLab, pure Python, no system dependencies). Recipient name, course/event title, issuer and date are filled in.

**Storage.** PDFs are written to `CERT_DIR/<job_id>/<certificate_id>.pdf`; the database stores metadata and the path. Certificate IDs are UUIDs, and the download endpoint checks the certificate belongs to the job in the URL.

**Database.** Two tables, `jobs` and `certificates` (one row per recipient, with `position` preserving submission order). Counts are computed with a `GROUP BY` on certificate status, so they can never drift from the rows. SQLite by default; change `DATABASE_URL` for another database.

**Known limitations / next steps.** No authentication; no job resumption after a crash; no pagination of the per-recipient list in `GET /jobs/{id}` (large jobs return large responses); no duplicate detection; no schema migrations (tables are created on startup). A real queue (Celery/RQ), pagination, auth, and S3-style storage would be the natural next steps.

## Layout

```
app/
  main.py        routes
  static/        index.html (basic frontend)
  services.py    validation, job creation, background worker, zip
  generator.py   PDF template
  models.py      Job, Certificate
  schemas.py     request/response models
  database.py    engine/session
  config.py      env config
tests/           pytest suite (18 tests)
```
