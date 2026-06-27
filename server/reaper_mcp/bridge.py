"""File-based transport between the MCP server and the Reaper Lua bridge.

Contract (must match bridge/reaper_mcp_bridge.lua):
  - We write  <bridge_dir>/<id>.req.json   (atomic: tmp + os.replace)
  - Lua writes <bridge_dir>/<id>.resp.json (atomic) and consumes the request
  - Lua touches <bridge_dir>/heartbeat every ~1s while alive

Request : {"id": str, "calls": [{"fn": str, "args": list}, ...]}
Response: {"id": str, "ok": bool, "results": [[...], ...], "error": str | None}
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path


DEFAULT_TIMEOUT = 5.0          # seconds to wait for a response file
HEARTBEAT_MAX_AGE = 3.0        # heartbeat older than this => bridge considered down
POLL_INTERVAL = 0.005          # response-file poll cadence (~5ms)


class BridgeError(RuntimeError):
    """Raised when the bridge is unreachable, times out, or a call fails."""


class BridgeFrozenError(BridgeError):
    """The request was sent but the bridge's heartbeat went stale mid-flight.

    Almost always means Reaper is showing a modal dialog (which freezes the GUI
    thread and the defer loop). A human must dismiss it before the bridge resumes.
    """


def default_bridge_dir() -> Path:
    """Resolve the bridge data dir inside Reaper's resource path (macOS default).

    Override with the REAPER_MCP_BRIDGE_DIR environment variable.
    """
    env = os.environ.get("REAPER_MCP_BRIDGE_DIR")
    if env:
        return Path(env).expanduser()
    return (
        Path.home()
        / "Library"
        / "Application Support"
        / "REAPER"
        / "Scripts"
        / "mcp_bridge"
    )


@dataclass
class Call:
    """A single ReaScript function invocation."""

    fn: str
    args: list | None = None

    def to_dict(self) -> dict:
        return {"fn": self.fn, "args": self.args or []}


class ReaperBridge:
    """Synchronous file-transport client for the Reaper Lua bridge."""

    def __init__(
        self,
        bridge_dir: Path | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.bridge_dir = bridge_dir or default_bridge_dir()
        self.timeout = timeout

    # -- liveness -----------------------------------------------------------

    def heartbeat_age(self) -> float | None:
        """Seconds since the bridge last touched the heartbeat, or None if absent."""
        hb = self.bridge_dir / "heartbeat"
        try:
            mtime = hb.stat().st_mtime
        except FileNotFoundError:
            return None
        return time.time() - mtime

    def is_alive(self) -> bool:
        age = self.heartbeat_age()
        return age is not None and age <= HEARTBEAT_MAX_AGE

    def _require_alive(self) -> None:
        if not self.bridge_dir.exists():
            raise BridgeError(
                f"Bridge directory not found: {self.bridge_dir}. "
                "Is Reaper running and reaper_mcp_bridge.lua loaded?"
            )
        age = self.heartbeat_age()
        if age is None:
            raise BridgeError(
                "Reaper bridge is not running (no heartbeat). "
                "Load reaper_mcp_bridge.lua in Reaper (Actions > Load ReaScript)."
            )
        if age > HEARTBEAT_MAX_AGE:
            raise BridgeError(
                f"Reaper bridge heartbeat is stale ({age:.1f}s old); the bridge "
                "script may have been terminated or Reaper is frozen."
            )

    # -- transport ----------------------------------------------------------

    def _write_request_atomic(self, req_id: str, payload: dict) -> None:
        target = self.bridge_dir / f"{req_id}.req.json"
        tmp = self.bridge_dir / f"{req_id}.req.json.tmp"
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp, target)  # atomic on same filesystem

    def _await_response(self, req_id: str) -> dict:
        resp_path = self.bridge_dir / f"{req_id}.resp.json"
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            if resp_path.exists():
                try:
                    raw = resp_path.read_text(encoding="utf-8")
                    data = json.loads(raw)
                except (OSError, json.JSONDecodeError):
                    # Mid-write race is unlikely (Lua uses atomic rename), but
                    # if we catch a transient read, retry until the deadline.
                    time.sleep(POLL_INTERVAL)
                    continue
                resp_path.unlink(missing_ok=True)
                return data
            # Watchdog: if the heartbeat goes stale while we wait, the defer loop
            # has stopped ticking — almost always a modal dialog froze the GUI
            # thread. Fail fast with an actionable message instead of waiting out
            # the full timeout, and don't delete the request (it'll be processed
            # once the dialog is dismissed).
            age = self.heartbeat_age()
            if age is not None and age > HEARTBEAT_MAX_AGE:
                raise BridgeFrozenError(
                    f"Reaper stopped responding mid-call (heartbeat {age:.1f}s "
                    "stale). It is most likely showing a modal dialog that froze "
                    "the bridge — dismiss the dialog in Reaper to resume. Prefer "
                    "dialog-free tools for project/render operations."
                )
            time.sleep(POLL_INTERVAL)
        # Clean up our request if it was never consumed, to avoid orphans.
        (self.bridge_dir / f"{req_id}.req.json").unlink(missing_ok=True)
        raise BridgeError(
            f"Timed out after {self.timeout:.1f}s waiting for Reaper to respond. "
            "The bridge may be overloaded or Reaper is busy."
        )

    # -- public API ---------------------------------------------------------

    def call_many(self, calls: list[Call]) -> list:
        """Execute a batch of calls in one round-trip. Returns the results list.

        Each element is the list of all Lua return values for that call.
        Raises BridgeError if the batch reported an error.
        """
        self._require_alive()
        req_id = uuid.uuid4().hex
        payload = {"id": req_id, "calls": [c.to_dict() for c in calls]}
        self._write_request_atomic(req_id, payload)
        resp = self._await_response(req_id)

        if not resp.get("ok", False):
            raise BridgeError(resp.get("error") or "Reaper bridge reported an error")
        return resp.get("results", [])

    def call(self, fn: str, *args) -> list:
        """Execute a single ReaScript function. Returns its list of return values."""
        results = self.call_many([Call(fn=fn, args=list(args))])
        return results[0] if results else []
