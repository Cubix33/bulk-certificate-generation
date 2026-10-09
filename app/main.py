from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import config, services
from .database import Base, engine, get_db
from .models import Certificate, CertStatus, Job
from .schemas import CertificateOut, JobCreate, JobDetail, JobSummary

app = FastAPI(title="Bulk Certificate Generator")
Base.metadata.create_all(engine)


def _counts(db: Session, job_id: str) -> dict:
    rows = db.execute(
        select(Certificate.status, func.count())
        .where(Certificate.job_id == job_id)
        .group_by(Certificate.status)
    ).all()
    by = {s: n for s, n in rows}
    succeeded = by.get(CertStatus.SUCCESS, 0)
    failed = by.get(CertStatus.FAILED, 0)
    pending = by.get(CertStatus.PENDING, 0)
    return dict(total=succeeded + failed + pending, succeeded=succeeded, failed=failed, pending=pending)


def _summary(db: Session, job: Job) -> dict:
    return dict(
        id=job.id, title=job.title, status=job.status,
        created_at=job.created_at, completed_at=job.completed_at,
        **_counts(db, job.id),
    )


def _get_job(db: Session, job_id: str) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return job


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.post("/jobs", response_model=JobSummary, status_code=202)
def create_job(data: JobCreate, background: BackgroundTasks, db: Session = Depends(get_db)):
    if len(data.recipients) > config.MAX_RECIPIENTS_PER_JOB:
        raise HTTPException(413, f"At most {config.MAX_RECIPIENTS_PER_JOB} recipients per job")
    job = services.create_job(db, data)
    background.add_task(services.process_job, job.id)
    return _summary(db, job)


@app.get("/jobs/{job_id}", response_model=JobDetail)
def get_job(job_id: str, db: Session = Depends(get_db)):
    job = _get_job(db, job_id)
    certs = [
        CertificateOut(
            id=c.id, position=c.position, recipient_name=c.recipient_name,
            recipient_email=c.recipient_email, status=c.status, error=c.error,
            download_url=f"/jobs/{job.id}/certificates/{c.id}" if c.status == CertStatus.SUCCESS else None,
        )
        for c in job.certificates
    ]
    return JobDetail(**_summary(db, job), certificates=certs)


@app.get("/jobs/{job_id}/certificates/{cert_id}")
def download_certificate(job_id: str, cert_id: str, db: Session = Depends(get_db)):
    cert = db.get(Certificate, cert_id)
    if cert is None or cert.job_id != job_id:
        raise HTTPException(404, "Certificate not found")
    if cert.status != CertStatus.SUCCESS or not cert.file_path:
        raise HTTPException(409, f"Certificate is not available (status: {cert.status.value})")
    return FileResponse(cert.file_path, media_type="application/pdf",
                        filename=f"certificate_{cert.position:05d}.pdf")


@app.get("/jobs/{job_id}/download")
def download_all(job_id: str, db: Session = Depends(get_db)):
    job = _get_job(db, job_id)
    if not any(c.status == CertStatus.SUCCESS for c in job.certificates):
        raise HTTPException(409, "No certificates available yet")
    return Response(services.build_zip(job), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="job_{job.id}.zip"'})
