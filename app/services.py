import io
import logging
import zipfile
from datetime import datetime, timezone

from email_validator import EmailNotValidError, validate_email
from sqlalchemy.orm import Session

from . import config, generator
from .database import SessionLocal
from .models import Certificate, CertStatus, Job, JobStatus
from .schemas import JobCreate, RecipientIn

log = logging.getLogger(__name__)

MAX_NAME_LEN = 200


def validate_recipient(r: RecipientIn) -> str | None:
    """Return an error message, or None if the recipient is valid."""
    name = (r.name or "").strip()
    if not name:
        return "name is required"
    if len(name) > MAX_NAME_LEN:
        return f"name must be at most {MAX_NAME_LEN} characters"
    if r.email is not None and r.email.strip():
        try:
            validate_email(r.email.strip(), check_deliverability=False)
        except EmailNotValidError as e:
            return f"invalid email: {e}"
    return None


def create_job(db: Session, data: JobCreate) -> Job:
    """Persist the job; invalid recipients are recorded as failed immediately,
    valid ones are left pending for the background worker."""
    job = Job(title=data.title, issuer=data.issuer, issue_date=data.issue_date)
    for i, r in enumerate(data.recipients):
        error = validate_recipient(r)
        job.certificates.append(
            Certificate(
                position=i,
                recipient_name=(r.name or "").strip() or None,
                recipient_email=(r.email or "").strip() or None,
                status=CertStatus.FAILED if error else CertStatus.PENDING,
                error=error,
            )
        )
    if all(c.status == CertStatus.FAILED for c in job.certificates):
        _finish(job)  # nothing to process
    db.add(job)
    db.commit()
    return job


def _finish(job: Job) -> None:
    ok = sum(c.status == CertStatus.SUCCESS for c in job.certificates)
    if ok == len(job.certificates):
        job.status = JobStatus.COMPLETED
    elif ok == 0:
        job.status = JobStatus.FAILED
    else:
        job.status = JobStatus.COMPLETED_WITH_ERRORS
    job.completed_at = datetime.now(timezone.utc)


def process_job(job_id: str, session_factory=None) -> None:
    """Background worker. Each certificate is isolated: an exception marks only
    that certificate failed and is committed, so progress is visible and a crash
    mid-way loses nothing already generated."""
    db = (session_factory or SessionLocal)()
    try:
        job = db.get(Job, job_id)
        if job is None or job.status not in (JobStatus.PENDING, JobStatus.PROCESSING):
            return
        job.status = JobStatus.PROCESSING
        db.commit()

        out_dir = config.CERT_DIR / job.id
        out_dir.mkdir(parents=True, exist_ok=True)

        for cert in job.certificates:
            if cert.status != CertStatus.PENDING:
                continue
            path = out_dir / f"{cert.id}.pdf"
            try:
                generator.render_certificate(
                    path,
                    recipient_name=cert.recipient_name,
                    title=job.title,
                    issuer=job.issuer,
                    issue_date=job.issue_date,
                )
                cert.status = CertStatus.SUCCESS
                cert.file_path = str(path)
            except Exception as e:  # noqa: BLE001 - isolate per-certificate failures
                log.exception("certificate %s failed", cert.id)
                path.unlink(missing_ok=True)
                cert.status = CertStatus.FAILED
                cert.error = f"generation failed: {e}"
            db.commit()

        _finish(job)
        db.commit()
    except Exception:
        # Unexpected job-level failure: don't leave the job stuck in "processing".
        log.exception("job %s crashed", job_id)
        db.rollback()
        job = db.get(Job, job_id)
        if job is not None:
            job.status = JobStatus.FAILED
            job.completed_at = datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()


def build_zip(job: Job) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for c in job.certificates:
            if c.status == CertStatus.SUCCESS and c.file_path:
                safe = "".join(ch if ch.isalnum() or ch in " -_" else "_" for ch in c.recipient_name)
                z.write(c.file_path, f"{c.position:05d}_{safe}.pdf")
    return buf.getvalue()
