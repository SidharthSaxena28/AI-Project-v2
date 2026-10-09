"""Start / stop the three mock company portals as subprocesses (used by CLI, UI and evals)."""
import os
import subprocess
import sys
import time

import httpx

from .context.registry import ROOT

PORTALS = {"expense_portal": 8001, "hr_portal": 8002, "ticketing": 8003}


class PortalSet:
    def __init__(self, faults: str = ""):
        self.faults, self.procs = faults, []

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *a):
        self.stop()

    def start(self):
        env = {**os.environ, "FAULTS": self.faults}
        for name, port in PORTALS.items():
            self.procs.append(subprocess.Popen(
                [sys.executable, "-m", "uvicorn", f"company_env.{name}.app:app", "--port", str(port), "--log-level", "warning"],
                cwd=ROOT, env=env))
        for port in PORTALS.values():
            for _ in range(60):
                try:
                    httpx.get(f"http://localhost:{port}/health", timeout=1)
                    break
                except Exception:
                    time.sleep(0.25)
            else:
                raise RuntimeError(f"portal on :{port} did not start")

    def stop(self):
        for p in self.procs:
            p.terminate()
        for p in self.procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
        self.procs = []


if __name__ == "__main__":
    with PortalSet(os.environ.get("FAULTS", "")):
        print("portals up on", PORTALS, "- Ctrl+C to stop")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
