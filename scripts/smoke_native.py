"""Check that a bundled graphical window starts without account access."""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path


executable = Path(sys.argv[1]).resolve()
options = {"start_new_session": True} if os.name != "nt" else {"creationflags": subprocess.CREATE_NO_WINDOW}
process = subprocess.Popen([str(executable), "gui"], **options)
try:
    time.sleep(5)
    if process.poll() is not None:
        raise SystemExit(f"The graphical window exited early ({process.returncode}).")
    print("The packaged graphical window started successfully.")
finally:
    if process.poll() is None:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], check=True, capture_output=True)
        else:
            os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=20)
