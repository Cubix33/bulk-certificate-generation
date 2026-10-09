import io
import zipfile

import pytest

from app import generator, services
from app.database import SessionLocal
from app.schemas import JobCreate


def payload(recipients, **kw):
    return {"title": "Python 101", "issuer": "Acme Academy", "issue_date": "2026-01-15",
            "recipients": recipients, **kw}


def good(n=3):
    return [{"name": f"Person {i}", "email": f"p{i}@example.com"} for i in range(n)]


def submit(client, recipients):
    """POST a job and return its final detail (TestClient runs background tasks before returning)."""
    job_id = client.post("/jobs", json=payload(recipients)).json()["id"]
    return client.get(f"/jobs/{job_id}").json()


# --- creating a job -------------------------------------------------------
def test_create_job_returns_202_and_id(client):
    r = client.post("/jobs", json=payload(good(3)))
    assert r.status_code == 202
    body = r.json()
    assert body["id"] and body["total"] == 3


# --- input validation -----------------------------------------------------
@pytest.mark.parametrize("bad", [
    {"recipients": []},
    {"title": ""},
    {"issuer": "   "},
])
def test_request_level_validation_rejected(client, bad):
    r = client.post("/jobs", json={**payload(good(1)), **bad})
    assert r.status_code == 422


def test_missing_field_rejected(client):
    assert client.post("/jobs", json={"title": "x"}).status_code == 422


def test_invalid_recipients_recorded_as_failed_others_succeed(client):
    job = submit(client, [
        {"name": "Good One", "email": "g@example.com"},
        {"name": "", "email": "a@example.com"},
        {"name": "Bad Email", "email": "not-an-email"},
        {"email": "noname@example.com"},
    ])
    assert job["status"] == "completed_with_errors"
    assert (job["succeeded"], job["failed"]) == (1, 3)
    errs = {c["position"]: c["error"] for c in job["certificates"]}
    assert "name is required" in errs[1]
    assert "invalid email" in errs[2]
    assert "name is required" in errs[3]


def test_all_invalid_job_is_failed(client):
    assert submit(client, [{"name": ""}])["status"] == "failed"


def test_too_many_recipients(client, monkeypatch):
    monkeypatch.setattr("app.config.MAX_RECIPIENTS_PER_JOB", 2)
    assert client.post("/jobs", json=payload(good(3))).status_code == 413


# --- certificate generation ----------------------------------------------
def test_generates_certificates(client):
    job = submit(client, good(2))
    assert job["status"] == "completed"
    assert all(c["status"] == "success" and c["download_url"] for c in job["certificates"])


def test_render_certificate_writes_pdf(tmp_path):
    p = tmp_path / "c.pdf"
    generator.render_certificate(p, recipient_name="Jane", title="T", issuer="I", issue_date="D")
    assert p.read_bytes().startswith(b"%PDF")


# --- job status / progress -----------------------------------------------
def test_unknown_job_404(client):
    assert client.get("/jobs/nope").status_code == 404


def test_status_counts_pending_then_completed(client):
    db = SessionLocal()
    job = services.create_job(db, JobCreate(**payload(good(2))))  # worker not run yet
    db.close()
    body = client.get(f"/jobs/{job.id}").json()
    assert body["status"] == "pending"
    assert (body["total"], body["pending"], body["succeeded"]) == (2, 2, 0)

    services.process_job(job.id)
    body = client.get(f"/jobs/{job.id}").json()
    assert body["status"] == "completed"
    assert (body["succeeded"], body["pending"]) == (2, 0)
    assert body["completed_at"] is not None


# --- individual failure ---------------------------------------------------
def test_one_render_failure_does_not_block_others(client, monkeypatch):
    real = generator.render_certificate

    def flaky(path, **kw):
        if kw["recipient_name"] == "Person 1":
            raise RuntimeError("boom")
        real(path, **kw)

    monkeypatch.setattr(generator, "render_certificate", flaky)
    job = submit(client, good(3))
    assert job["status"] == "completed_with_errors"
    assert (job["succeeded"], job["failed"]) == (2, 1)
    failed = [c for c in job["certificates"] if c["status"] == "failed"][0]
    assert failed["recipient_name"] == "Person 1" and "boom" in failed["error"]
    assert failed["download_url"] is None


# --- retrieval -------------------------------------------------------------
def test_download_single_certificate(client):
    cert = submit(client, good(1))["certificates"][0]
    r = client.get(cert["download_url"])
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")


def test_download_failed_or_missing_certificate(client):
    job = submit(client, [{"name": ""}, {"name": "Ok"}])
    failed, ok = job["certificates"]
    assert client.get(f"/jobs/{job['id']}/certificates/{failed['id']}").status_code == 409
    assert client.get(f"/jobs/{job['id']}/certificates/unknown").status_code == 404
    other = submit(client, good(1))
    # a certificate id must not be reachable through a different job
    assert client.get(f"/jobs/{other['id']}/certificates/{ok['id']}").status_code == 404


def test_download_zip_contains_only_successes(client):
    job = submit(client, [{"name": "A"}, {"name": ""}, {"name": "C"}])
    r = client.get(f"/jobs/{job['id']}/download")
    assert r.status_code == 200
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert len(names) == 2 and names[0].startswith("00000_A")


def test_zip_409_when_nothing_generated(client):
    job = submit(client, [{"name": ""}])
    assert client.get(f"/jobs/{job['id']}/download").status_code == 409


# --- frontend ---------------------------------------------------------------
def test_frontend_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Bulk Certificate Generator" in r.text
