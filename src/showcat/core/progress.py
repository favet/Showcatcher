"""Pipeline progress tracker — writes live JSON to a file for the web dashboard.

The progress file is written to C:\website\showcat\progress.json so it's
instantly accessible via the Caddy web server at /showcat/progress.json.
"""
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


PROGRESS_FILE = Path(os.environ.get("PROGRESS_FILE", "/website_showcat/progress.json"))


@dataclass
class StageProgress:
    name: str
    status: str = "pending"  # pending | running | completed | failed
    total: int = 0
    current: int = 0
    started_at: float = 0.0
    ended_at: float = 0.0
    error: str = ""


@dataclass
class PipelineProgress:
    stages: list[StageProgress] = field(default_factory=list)
    pipeline_started_at: float = 0.0
    pipeline_status: str = "idle"  # idle | running | completed | failed

    def start(self) -> None:
        self.pipeline_started_at = time.time()
        self.pipeline_status = "running"
        self._write()

    def start_stage(self, name: str, total: int = 0) -> StageProgress:
        stage = StageProgress(name=name, status="running", total=total, started_at=time.time())
        self.stages.append(stage)
        self._write()
        return stage

    def update_stage(self, stage: StageProgress, current: int) -> None:
        stage.current = current
        self._write()

    def complete_stage(self, stage: StageProgress, final_count: int) -> None:
        stage.status = "completed"
        stage.current = final_count
        stage.ended_at = time.time()
        self._write()

    def fail_stage(self, stage: StageProgress, error: str) -> None:
        stage.status = "failed"
        stage.error = error
        stage.ended_at = time.time()
        self._write()

    def complete(self) -> None:
        self.pipeline_status = "completed"
        self._write()

    def fail(self, error: str) -> None:
        self.pipeline_status = "failed"
        self._write()

    def to_dict(self) -> dict[str, Any]:
        now = time.time()
        stages_data = []
        for s in self.stages:
            elapsed = (s.ended_at or now) - s.started_at if s.started_at else 0
            eta = None
            if s.status == "running" and s.current > 0 and s.total > 0:
                rate = s.current / elapsed if elapsed > 0 else 0
                remaining = s.total - s.current
                eta = remaining / rate if rate > 0 else None

            stages_data.append({
                "name": s.name,
                "status": s.status,
                "total": s.total,
                "current": s.current,
                "elapsed_seconds": round(elapsed, 1),
                "eta_seconds": round(eta, 1) if eta else None,
                "error": s.error,
                "started_at": s.started_at * 1000 if s.started_at else None,
                "ended_at": s.ended_at * 1000 if s.ended_at else None,
            })

        total_elapsed = now - self.pipeline_started_at if self.pipeline_started_at else 0
        return {
            "pipeline_status": self.pipeline_status,
            "total_elapsed_seconds": round(total_elapsed, 1),
            "pipeline_started_at": self.pipeline_started_at * 1000 if self.pipeline_started_at else None,
            "stages": stages_data,
        }

    def _write(self) -> None:
        try:
            PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
            PROGRESS_FILE.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        except Exception:
            pass  # Never let progress reporting break the pipeline
