"""In-memory job manager for async pipeline status tracking."""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Literal, Optional

logger = logging.getLogger(__name__)

JobStatus = Literal["pending", "in_progress", "completed", "failed"]


class Job:
    """Represents a pipeline job."""

    def __init__(self, chat_id_topic: str) -> None:
        self.chat_id_topic = chat_id_topic
        self.status: JobStatus = "pending"
        self.result: Optional[Dict[str, Any]] = None
        self.error: Optional[str] = None
        self.created_at = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chat_id_topic": self.chat_id_topic,
            "status": self.status,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


class JobManager:
    """Thread-safe in-memory job store."""

    def __init__(self) -> None:
        self._jobs: Dict[str, Job] = {}
        self._lock = threading.Lock()

    def create_job(self, chat_id_topic: str) -> Job:
        """Create a new job with pending status."""
        with self._lock:
            if chat_id_topic in self._jobs:
                logger.warning(
                    "Job already exists for chat_id_topic=%s, replacing it",
                    chat_id_topic,
                )
            job = Job(chat_id_topic)
            self._jobs[chat_id_topic] = job
            logger.info("Created job for chat_id_topic=%s", chat_id_topic)
            return job

    def update_job(
        self,
        chat_id_topic: str,
        status: Optional[JobStatus] = None,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> None:
        """Update job status, result, or error."""
        with self._lock:
            job = self._jobs.get(chat_id_topic)
            if not job:
                logger.warning(
                    "Attempted to update non-existent job: chat_id_topic=%s",
                    chat_id_topic,
                )
                return

            if status is not None:
                job.status = status
            if result is not None:
                job.result = result
            if error is not None:
                job.error = error
            job.updated_at = datetime.now(timezone.utc)

            logger.info(
                "Updated job chat_id_topic=%s, status=%s", chat_id_topic, job.status
            )

    def get_job(self, chat_id_topic: str) -> Optional[Job]:
        """Get job by chat_id_topic. Returns None if not found."""
        with self._lock:
            return self._jobs.get(chat_id_topic)

    def delete_job(self, chat_id_topic: str) -> None:
        """Remove job from store."""
        with self._lock:
            if chat_id_topic in self._jobs:
                del self._jobs[chat_id_topic]
                logger.info("Deleted job for chat_id_topic=%s", chat_id_topic)

    def cleanup_old_jobs(self, max_age_hours: int = 1) -> None:
        """Remove jobs older than max_age_hours."""
        now = datetime.now(timezone.utc)
        with self._lock:
            expired = [
                cid
                for cid, job in self._jobs.items()
                if (now - job.created_at).total_seconds() > max_age_hours * 3600
            ]
            for cid in expired:
                del self._jobs[cid]
                logger.info("Cleaned up expired job: chat_id_topic=%s", cid)


# Global singleton
_job_manager = JobManager()


def get_job_manager() -> JobManager:
    """Get the global job manager instance."""
    return _job_manager
