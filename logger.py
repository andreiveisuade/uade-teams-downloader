"""Logging centralizado del pipeline."""

from datetime import datetime

_PREFIX = {
    "INFO": "   ",
    "OK":   " + ",
    "WARN": " ! ",
    "ERR":  "!! ",
    "STEP": ">> ",
}


def log(msg: str, level: str = "INFO"):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}]{_PREFIX.get(level, '   ')} {msg}")


def log_step(msg): log(msg, "STEP")
def log_ok(msg): log(msg, "OK")
def log_warn(msg): log(msg, "WARN")
def log_err(msg): log(msg, "ERR")
