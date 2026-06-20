"""menu.py — the OPERATOR: interactive control menu for the BTC up/down project.

One place to run everything: inspect data, generate the exit maps and round charts,
run the analyses, paper-trade, and start/stop the collectors. Pure stdlib; it just
shells out to the project's own scripts.

    python menu.py

(Named menu.py, not operator.py, because a file named operator.py would shadow
Python's standard-library `operator` module and break every script in this folder.)
"""

import os
import sys
import json
import time
import shutil
import sqlite3
import subprocess
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
DB = os.path.join(HERE, "btc_updown.db")
SIGNALS = os.path.join(HERE, "signals.json")
OLD_DBS = os.path.join(HERE, "old_dbs")
STOP = os.path.join(HERE, "STOP")
DASH = "http://127.0.0.1:8765"
SIGNALS_FRESH_MIN = 20      # bot startup: re-evaluate signals older than this


def run(cmd, pause=True, env_extra=None):
    print(f"\n$ {' '.join(str(c) for c in cmd)}\n" + "-" * 64)
    env = {**os.environ, **env_extra} if env_extra else None
    try:
        subprocess.run([str(c) for c in cmd], cwd=HERE, env=env)
    except KeyboardInterrupt:
        print("\n(interrupted)")
    except Exception as e:
        print(f"error: {e!r}")
    if pause:
        input("\n[Enter] to return to the menu ")


def ask(prompt, default):
    v = input(f"  {prompt} [{default}]: ").strip()
    return v or str(default)


def ask_scope(unit="days"):
    """Return env for the analysis subprocess: current fresh DB, or the last X
    days/hours (merging old_dbs/). None = current only. `unit` only changes the
    prompt wording/granularity; the env var is always BTC_ANALYSIS_DAYS (fractional
    days are fine, so hours convert cleanly)."""
    span = "last X hours" if unit == "hours" else "last X days"
    print(f"\n  data scope:  [1] current fresh DB   [2] {span} (incl. old_dbs)")
    if (input("  scope [1]: ").strip() or "1") != "2":
        return None
    if unit == "hours":
        try:
            days = float(ask("how many hours", 24)) / 24.0
        except ValueError:
            days = 1.0
        return {"BTC_ANALYSIS_DAYS": f"{days:.6f}"}
    return {"BTC_ANALYSIS_DAYS": ask("how many days", 7)}


def _launch_supervisor():
    flags = 0
    if os.name == "nt":
        flags = (subprocess.CREATE_NEW_PROCESS_GROUP |
                 getattr(subprocess, "DETACHED_PROCESS", 0x00000008))
    subprocess.Popen([PY, "supervisor.py"], cwd=HERE, creationflags=flags,
                     stdout=open(os.path.join(HERE, "supervisor.out.log"), "a"),
                     stderr=open(os.path.join(HERE, "supervisor.err.log"), "a"))


def is_live():
    try:
        c = sqlite3.connect(DB)
        last = c.execute("SELECT MAX(ts) FROM snapshots").fetchone()[0]
        c.close()
        return bool(last) and (time.time() - last) < 12
    except Exception:
        return False


# ---- actions ----------------------------------------------------------------

def a_status():
    print(f"\n  collectors: {'LIVE' if is_live() else 'NOT writing (stopped?)'}")
    run([PY, "-m", "analysis.data_quality"])


def a_peek():         run([PY, "peek.py"])
def a_peek_windows(): run([PY, "peek.py", "windows"])
def a_round_charts(): run([PY, "chart_capture.py", "--once"])
def a_selftest():     run([PY, "-m", "exec_engine.selftest"])


def a_exit_maps():
    run([PY, "-m", "analysis.exit_maps"], env_extra=ask_scope())


def a_calibration():
    scope = ask_scope()
    h = ask("horizon seconds (time-left)", 240)
    run([PY, "-m", "analysis.calibration_test", "--horizon", h], env_extra=scope)


def a_fairvalue():
    scope = ask_scope()
    h = ask("horizon seconds (time-left)", 240)
    run([PY, "-m", "analysis.fair_vs_market", "--horizon", h], env_extra=scope)


def a_reversion():
    scope = ask_scope()
    dip = ask("dip price", 0.25)
    rec = ask("recover price", 0.33)
    run([PY, "-m", "analysis.reversion", "--dip", dip, "--recover", rec], env_extra=scope)


def a_combo_ev():
    scope = ask_scope()
    n = ask("min samples per combo", 12)
    fee = ask("round-trip fee fraction", 0.0)
    run([PY, "-m", "analysis.combo_ev", "--min-n", n, "--fee", fee], env_extra=scope)


def a_signals():
    scope = ask_scope()
    win = ask("min win-rate (e.g. 0.70)", 0.70)
    roi = ask("min ROI (e.g. 0.50)", 0.50)
    usd = ask("bet USD per trade", 2)
    entry = ask("min entry price", 0.10)
    ev = ask("min EV per $1 (0 = must be profitable)", 0.0)
    frac = ask("min window dot-share (0.20 = 20%, anti-cherry-pick)", 0.20)
    run([PY, "-m", "analysis.signals", "--min-win", win, "--min-roi", roi,
         "--usd", usd, "--min-entry", entry, "--min-ev", ev, "--min-frac", frac],
        env_extra=scope)


def _signals_meta():
    """Load signals.json (dict) or None if missing/unreadable."""
    try:
        with open(SIGNALS) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _run_finder(meta, scope=None, pause=False):
    """Re-evaluate signals over the chosen data scope. With meta, reuse the prior
    floors (automatic re-eval); without, prompt for them (first-time generate)."""
    if meta:
        win, roi = meta.get("min_win", 0.70), meta.get("min_roi", 0.50)
        usd, entry = meta.get("usd", 2), meta.get("min_entry", 0.10)
        fev = meta.get("min_ev", 0.0)
        dots, frac = meta.get("min_dots", 8), meta.get("min_frac", 0.20)
        print(f"  reusing prior floors: win>= {float(win):.0%}  ROI>= {float(roi):+.0%}"
              f"  EV> {fev}  density>= {dots} & {float(frac):.0%}  bet ${usd}  entry>= {entry}")
    else:
        win = ask("min win-rate (e.g. 0.70)", 0.70)
        roi = ask("min ROI (e.g. 0.50)", 0.50)
        usd = ask("bet USD per trade", 2)
        entry = ask("min entry price", 0.10)
        fev = ask("finder min EV per $1 (0 = must be profitable)", 0.0)
        dots, frac = 8, ask("min window dot-share (0.20 = 20%)", 0.20)
    run([PY, "-m", "analysis.signals", "--min-win", win, "--min-roi", roi,
         "--usd", usd, "--min-entry", entry, "--min-ev", fev, "--min-dots", dots,
         "--min-frac", frac], pause=pause, env_extra=scope)


def a_phase2():
    """Bot startup: ensure signals are fresh (<=20 min) -- showing them if so,
    re-evaluating on live data if not -- then choose the EV floor and launch the
    paper executor."""
    meta = _signals_meta()
    gen = meta.get("generated") if meta else None
    age = (time.time() - gen) / 60.0 if gen else None

    if meta is None or age is None or age > SIGNALS_FRESH_MIN:
        if meta is None:
            print("\n  no signals.json yet -- generating fresh signals first.")
        else:
            shown = f"{age:.0f}" if age is not None else "?"
            print(f"\n  signals are {shown} min old (> {SIGNALS_FRESH_MIN}) -- re-evaluating...")
        scope = ask_scope(unit="hours")     # which data window to build signals from
        _run_finder(meta, scope, pause=False)
    else:
        print(f"\n  signals are {age:.0f} min old (<= {SIGNALS_FRESH_MIN}) -- using them:")
        run([PY, "-m", "analysis.signals", "--show"], pause=False)

    if not os.path.exists(SIGNALS):
        print("\n  no signals to trade -- aborting startup.")
        input("\n[Enter] ")
        return
    ev = ask("\n  min EV per $1 to TRADE (e.g. 0.5)", 0.5)
    print("  (PAPER forward-test of signals.json -- watches live rounds, nothing real")
    print("   is traded; appends paper_trades.csv. Ctrl-C to stop and return.)")
    run([PY, "phase2.py", "--min-ev", ev])


def a_paper_ledger():
    n = ask("min attempts per signal to show", 1)
    run([PY, "-m", "analysis.paper_ledger", "--min-n", n])


def a_round_review():
    n = ask("how many recent rounds to render", 20)
    run([PY, "-m", "analysis.round_review", "--last", n])


def a_paper():
    o = ask("outcome (up/down)", "down")
    p = ask("entry price", 0.22)
    s = ask("size (shares)", 30)
    x = ask("exit/target price", 0.33)
    print("  (paper only -- Ctrl-C to stop and return to the menu)")
    run([PY, "paper_trade.py", "--outcome", o, "--price", p, "--size", s, "--exit", x])


def a_dashboard():
    print(f"\n  opening {DASH} ...")
    try:
        webbrowser.open(DASH)
    except Exception as e:
        print(f"  couldn't open browser: {e!r} -- visit {DASH} manually")
    input("\n[Enter] ")


def a_start():
    if is_live():
        print("\n  collectors already running (data is live).")
    else:
        try:
            _launch_supervisor()
            print("\n  started supervisor: collector + ws_collector + viewer + chart_capture.")
        except Exception as e:
            print(f"\n  failed to start: {e!r}")
    input("\n[Enter] ")


def a_new_database():
    print("\n  This archives the CURRENT database into old_dbs/ and starts a FRESH,")
    print("  empty one. The old data stays available to 'last X days' analysis.")
    if input("  proceed? (y/N): ").strip().lower() != "y":
        return
    os.makedirs(OLD_DBS, exist_ok=True)
    # stop the collectors so the DB file handle is released
    open(STOP, "w").close()
    print("  stopping collectors (~12s)...")
    time.sleep(12)
    ts = time.strftime("%Y%m%d-%H%M%S")
    moved = 0
    for ext in ("", "-wal", "-shm"):
        src = DB + ext
        if os.path.exists(src):
            try:
                shutil.move(src, os.path.join(OLD_DBS, f"btc_updown_{ts}.db{ext}"))
                moved += 1
            except Exception as e:
                print(f"  could NOT move {os.path.basename(src)}: {e!r}")
                print("  (a collector may still hold it — try again in a few seconds)")
    print(f"  archived {moved} file(s) -> old_dbs/btc_updown_{ts}.db")
    try:
        os.remove(STOP)
    except OSError:
        pass
    try:
        _launch_supervisor()
        print("  restarted collectors -> a fresh database is being created now.")
    except Exception as e:
        print(f"  failed to restart collectors: {e!r}")
    input("\n[Enter] ")


def a_stop():
    if input("\n  stop ALL collectors? (y/N): ").strip().lower() == "y":
        open(STOP, "w").close()
        print("  STOP file created -- the supervisor shuts the tree down within ~10s.")
    input("\n[Enter] ")


# ---- menu --------------------------------------------------------------------

MENU = [
    ("INSPECT", None),
    ("1", "Status / health (data quality audit)", a_status),
    ("2", "Peek -- summary", a_peek),
    ("3", "Peek -- windows table", a_peek_windows),
    ("4", "Open live dashboard (browser)", a_dashboard),
    ("VISUALS", None),
    ("5", "Generate exit maps (per entry price)", a_exit_maps),
    ("6", "Generate round charts (backfill)", a_round_charts),
    ("ANALYSIS", None),
    ("7", "Phase-1 SIGNAL FINDER (win/ROI floors -> signals.json)", a_signals),
    ("8", "Calibration test (price vs outcome)", a_calibration),
    ("9", "Fair-value vs market (underreaction)", a_fairvalue),
    ("10", "Reversion screen (dip -> recover)", a_reversion),
    ("11", "Combo EV scan", a_combo_ev),
    ("EXECUTION (paper)", None),
    ("12", "PHASE 2 -- paper executor (live forward-test of signals.json)", a_phase2),
    ("13", "Paper ledger summary (realized vs predicted EV)", a_paper_ledger),
    ("14", "Round reviews (per-round charts of paper games)", a_round_review),
    ("15", "Paper-trade a single limit order", a_paper),
    ("16", "Execution engine self-test", a_selftest),
    ("SERVICES", None),
    ("17", "Start collectors", a_start),
    ("18", "Stop collectors", a_stop),
    ("19", "Create NEW database (archive current -> old_dbs/)", a_new_database),
]
ACTIONS = {row[0]: row[2] for row in MENU if row[1] is not None}


def show_menu():
    print("\n" + "=" * 64)
    print(f"  BTC UP/DOWN -- OPERATOR    [{'LIVE' if is_live() else 'stopped'}]")
    print("=" * 64)
    for row in MENU:
        if row[1] is None:
            print(f"\n  -- {row[0]} --")
        else:
            print(f"   {row[0]:>2}) {row[1]}")
    print("\n    q) quit")


def main():
    while True:
        show_menu()
        try:
            choice = input("\n  select: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if choice in ("q", "quit", "exit", "0"):
            break
        fn = ACTIONS.get(choice)
        if fn:
            try:
                fn()
            except KeyboardInterrupt:
                print("\n(back to menu)")
        else:
            print("  invalid choice")
    print("bye.")


if __name__ == "__main__":
    main()
