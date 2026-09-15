"""Stop orphaned research processes when their supervisor lease expires."""
import json
import os
import threading
import time
from pathlib import Path


def monitor_lease():
    filename = os.environ.get('WORKBENCH_SUPERVISOR_FILE')
    token = os.environ.get('WORKBENCH_SUPERVISOR_TOKEN')
    if not filename or not token:
        return

    def monitor():
        while True:
            time.sleep(.5)
            try:
                path = Path(filename)
                if time.time() - path.stat().st_mtime > 15 or json.loads(path.read_text())['token'] != token:
                    os._exit(75)
            except (OSError, ValueError, KeyError):
                # A heartbeat file can be briefly empty during a write.
                time.sleep(.1)
                if not Path(filename).exists():
                    os._exit(75)
    threading.Thread(target=monitor, daemon=True).start()
