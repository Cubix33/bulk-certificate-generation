from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from .models import CertStatus, JobStatus


class RecipientIn(BaseModel):
    """Deliberately loose: per-recipient problems are reported on the job item,
    not by rejecting the whole request (see README)."""
    name: str | None = None
    email: str | None = None


class JobCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    issuer: str = Field(min_length=1, max_length=200)
    issue_date: str = Field(min_length=1, max_length=50)
    recipients: list[RecipientIn] = Field(min_length=1)

    @field_validator("title", "issuer", "issue_date")
    @classmethod
    def not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be blank")
        return v


class CertificateOut(BaseModel):
    id: str
    position: int
    recipient_name: str | None
    recipient_email: str | None
    status: CertStatus
    error: str | None
    download_url: str | None = None

    model_config = {"from_attributes": True}


class JobSummary(BaseModel):
    id: str
    title: str
    status: JobStatus
    total: int
    succeeded: int
    failed: int
    pending: int
    created_at: datetime
    completed_at: datetime | None


class JobDetail(JobSummary):
    certificates: list[CertificateOut]
