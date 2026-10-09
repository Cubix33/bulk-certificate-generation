import os
from pathlib import Path

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./certificates.db")
CERT_DIR = Path(os.getenv("CERT_DIR", "./certificates"))
MAX_RECIPIENTS_PER_JOB = int(os.getenv("MAX_RECIPIENTS_PER_JOB", "5000"))
