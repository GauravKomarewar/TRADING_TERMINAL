import os
import sys
import json
from typing import Optional
import signal
import subprocess
import tempfile
from pathlib import Path
import logging

logger = logging.getLogger("DASHBOARD.SUPERVISOR")

# PID store dir
PID_DIR = Path(tempfile.gettempdir()) / "shoonya_dashboard_supervisor"
PID_DIR.mkdir(parents=True, exist_ok=True)


class SupervisorService:
    """Lightweight strategy supervisor.

    - start(config_path): Launches in-process strategy runner entrypoint
    - stop(pid or config_path): Attempts graceful stop via SIGTERM, then SIGKILL
    """

    def __init__(self):
        self.pid_dir = PID_DIR

    def _pidfile_for(self, config_path: str) -> Path:
        name = config_path.replace(".", "_")
        return self.pid_dir / f"{name}.pid"

    def start(self, config_path: str) -> dict:
        raise RuntimeError(
            "SupervisorService subprocess mode is retired. "
            "Use /dashboard/runner/start or /dashboard/strategy/{name}/start-execution."
        )

    def stop(self, config_path: Optional[str] = None, pid: Optional[int] = None) -> dict:
        if config_path:
            pidfile = self._pidfile_for(config_path)
            if not pidfile.exists():
                raise RuntimeError("PID file not found for config: %s" % config_path)
            with pidfile.open() as f:
                data = json.load(f)
                pid = data.get("pid")
        if not pid:
            raise RuntimeError("No pid specified")

        try:
            logger.info("Stopping pid=%s", pid)
            os.kill(pid, signal.SIGTERM)
        except Exception as e:
            logger.warning("SIGTERM failed: %s", e)
            # Try SIGKILL if available (POSIX). On Windows, fall back to taskkill.
            sigkill = getattr(signal, "SIGKILL", None)
            if sigkill is not None:
                try:
                    os.kill(pid, sigkill)
                except Exception:
                    logger.exception("Failed to kill process %s with SIGKILL", pid)
                    raise
            else:
                # Windows: attempt taskkill; tolerate failures
                try:
                    subprocess.run(["taskkill", "/F", "/PID", str(pid)], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except Exception:
                    logger.exception("Failed to taskkill process %s", pid)
                    raise

        # remove pidfiles referencing this pid
        for pf in self.pid_dir.glob("*.pid"):
            try:
                with pf.open() as f:
                    data = json.load(f)
                    if data.get("pid") == pid:
                        pf.unlink()
            except Exception:
                continue

        return {"stopped_pid": pid}

    def list(self) -> list:
        out = []
        for pf in self.pid_dir.glob("*.pid"):
            try:
                with pf.open() as f:
                    data = json.load(f)
                    out.append({"pidfile": str(pf), "pid": data.get("pid")})
            except Exception:
                continue
        return out
