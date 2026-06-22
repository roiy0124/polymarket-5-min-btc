"""Supervisor — keep the collectors and viewer running until interrupted.

Launches each child process and restarts any that exits (with capped
exponential backoff so a crash-loop can't spin). This is the reliable
"run until interrupted" guarantee on top of each process's own resilience.

    python supervisor.py            # starts + supervises everything

Stop it by either:
  * pressing Ctrl-C (if running in a foreground terminal), or
  * creating an empty file named STOP in this folder, or
  * Stop-Process on the supervisor PID.

Each child's stdout/stderr is appended to <name>.out.log / <name>.err.log.
"""

import os
import sys
import time
import signal
import subprocess

import coins

HERE = os.path.dirname(os.path.abspath(__file__))
STOP_FILE = os.path.join(HERE, "STOP")
PY = sys.executable

# One REST + one WebSocket collector per enabled coin (each writes its own
# data/<coin>/live.db and its own <name>.out.log / .err.log), plus the shared
# BTC-focused viewer + chart_capture. Trim coins.ENABLED to collect fewer.
CHILDREN = []
for _c in coins.ENABLED:
    CHILDREN.append((f"collector_{_c}",    [PY, "-u", "collector.py", "--coin", _c]))
    CHILDREN.append((f"ws_collector_{_c}", [PY, "-u", "ws_collector.py", "--coin", _c]))
CHILDREN.append(("viewer",        [PY, "-u", "viewer.py", "8765"]))
CHILDREN.append(("chart_capture", [PY, "-u", "chart_capture.py"]))

CHECK_INTERVAL = 3.0
BACKOFF_START = 2.0
BACKOFF_MAX = 60.0
HEALTHY_AFTER = 60.0   # alive this long => reset backoff


def _ts():
    return time.strftime("%Y-%m-%d %H:%M:%S")


class Child:
    def __init__(self, name, cmd):
        self.name = name
        self.cmd = cmd
        self.proc = None
        self.backoff = BACKOFF_START
        self.next_start = 0.0
        self.started_at = 0.0
        self.restarts = 0
        self.out = open(os.path.join(HERE, f"{name}.out.log"), "a", buffering=1, encoding="utf-8")
        self.err = open(os.path.join(HERE, f"{name}.err.log"), "a", buffering=1, encoding="utf-8")

    def start(self):
        self.out.write(f"\n--- supervisor start {_ts()} ---\n")
        self.proc = subprocess.Popen(self.cmd, cwd=HERE, stdout=self.out, stderr=self.err)
        self.started_at = time.time()
        print(f"[{_ts()}] started {self.name} pid={self.proc.pid}", flush=True)

    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def stop(self):
        if self.alive():
            try:
                self.proc.terminate()
            except Exception:
                pass


_running = True


def _stop(*_):
    global _running
    _running = False


def main():
    signal.signal(signal.SIGINT, _stop)
    try:
        signal.signal(signal.SIGTERM, _stop)
    except (ValueError, AttributeError):
        pass

    # clear a stale STOP file from a previous run
    if os.path.exists(STOP_FILE):
        try:
            os.remove(STOP_FILE)
        except OSError:
            pass

    children = [Child(n, c) for n, c in CHILDREN]
    for ch in children:
        ch.start()
    print(f"[{_ts()}] supervisor up — managing {len(children)} processes "
          f"(Ctrl-C or create STOP file to stop)", flush=True)

    while _running:
        try:
            if os.path.exists(STOP_FILE):
                print(f"[{_ts()}] STOP file found -> shutting down", flush=True)
                break
            now = time.time()
            for ch in children:
                if ch.alive():
                    if now - ch.started_at > HEALTHY_AFTER:
                        ch.backoff = BACKOFF_START
                elif now >= ch.next_start:
                    code = ch.proc.returncode if ch.proc else "?"
                    ch.restarts += 1
                    print(f"[{_ts()}] {ch.name} exited (code={code}); "
                          f"restart #{ch.restarts}, next backoff {ch.backoff:.0f}s", flush=True)
                    ch.start()
                    ch.next_start = time.time() + ch.backoff
                    ch.backoff = min(BACKOFF_MAX, ch.backoff * 2)
        except Exception as e:
            # the supervisor must never die on a stray error
            print(f"[{_ts()}] supervisor loop error (continuing): {e!r}", flush=True)
        time.sleep(CHECK_INTERVAL)

    # graceful shutdown of the whole tree
    print(f"[{_ts()}] stopping children...", flush=True)
    for ch in children:
        ch.stop()
    time.sleep(2.0)
    for ch in children:
        if ch.alive():
            try:
                ch.proc.kill()
            except Exception:
                pass
    print(f"[{_ts()}] supervisor stopped.", flush=True)


if __name__ == "__main__":
    main()
