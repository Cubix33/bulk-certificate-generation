import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class JobStatus(str, enum.Enum):
    PENDING = "pending"                # accepted, not started
    PROCESSING = "processing"          # worker is generating
    COMPLETED = "completed"            # every certificate succeeded
    COMPLETED_WITH_ERRORS = "completed_with_errors"  # mix of success/failure
    FAILED = "failed"                  # nothing succeeded


class CertStatus(str, enum.Enum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String(200))  # e.g. course / event name
    issuer: Mapped[str] = mapped_column(String(200))
    issue_date: Mapped[str] = mapped_column(String(50))
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), default=JobStatus.PENDING)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    certificates: Mapped[list["Certificate"]] = relationship(
        back_populates="job", cascade="all, delete-orphan", order_by="Certificate.position"
    )


class Certificate(Base):
    __tablename__ = "certificates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)  # index in the submitted list
    recipient_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    recipient_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    status: Mapped[CertStatus] = mapped_column(Enum(CertStatus), default=CertStatus.PENDING)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)

    job: Mapped[Job] = relationship(back_populates="certificates")
