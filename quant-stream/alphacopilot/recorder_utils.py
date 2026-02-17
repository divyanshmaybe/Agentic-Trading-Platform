"""Utilities for integrating AlphaCopilot logging with the shared Recorder."""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, UTC
from typing import Any, Iterable, Optional

from quant_stream.recorder import Recorder


def _now_ts() -> str:
    """Return an ISO-like timestamp with millisecond precision."""
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


@dataclass
class RecorderLogger:
    """Lightweight logger that prints to stdout and logs artifacts via Recorder."""

    recorder: Optional[Recorder] = None

    def __post_init__(self) -> None:
        self._tag_stack: list[str] = []
        self._buffers: dict[str, list[str]] = {}
        self._log_counts: dict[str, int] = {}

    # ------------------------------------------------------------------ utils
    def _current_tag(self) -> str:
        return ".".join(self._tag_stack)

    def _buffer_for(self, tag: str) -> list[str]:
        key = tag or "root"
        if key not in self._buffers:
            self._buffers[key] = []
        return self._buffers[key]

    def _render_message(self, message: Any, args: tuple[Any, ...]) -> str:
        base = str(message)
        if not args:
            return base

        try:
            return base % args
        except (TypeError, ValueError):
            try:
                return base.format(*args)
            except Exception:
                joined_args = ", ".join(repr(arg) for arg in args)
                return f"{base} | args={joined_args}"

    def _log(
        self,
        level: str,
        message: Any,
        *args: Any,
        extra_tag: Optional[str] = None,
    ) -> None:
        rendered_message = self._render_message(message, args)
        timestamp = _now_ts()
        tag = ".".join(filter(None, [self._current_tag(), extra_tag]))

        # Console output for immediate feedback
        prefix = f"[{level}]"
        if tag:
            prefix += f"[{tag}]"
        print(f"{prefix} {rendered_message}")

        # Append to buffer for eventual artifact logging
        line = f"{timestamp} | {level:<5} | {rendered_message}"
        self._buffer_for(tag).append(line)

    def _flush_tag(self, tag: str) -> None:
        lines = self._buffers.get(tag or "root")
        if not lines:
            return

        if not (self.recorder and self.recorder.active_run):
            # No recorder available; drop buffered lines
            self._buffers.pop(tag or "root", None)
            return

        if tag:
            parts = tag.split(".")
            if parts and parts[0].startswith("iter_"):
                artifact_dir = os.path.join("alphacopilot", parts[0], "logs", *parts[1:])
            else:
                artifact_dir = os.path.join("alphacopilot", "logs", tag.replace(".", "/"))
        else:
            artifact_dir = os.path.join("alphacopilot", "logs", "root")
        count = self._log_counts.get(tag or "root", 0)
        self._log_counts[tag or "root"] = count + 1

        with tempfile.TemporaryDirectory() as tmpdir:
            file_name = f"{count:03d}.log"
            file_path = os.path.join(tmpdir, file_name)
            with open(file_path, "w") as fh:
                fh.write("\n".join(lines))
            self.recorder.log_artifact(file_path, artifact_path=artifact_dir)

        self._buffers.pop(tag or "root", None)

    # ------------------------------------------------------------------ public
    @contextmanager
    def tag(self, tag: str):  # noqa: D401 - matches previous logger API
        if not tag or not tag.strip():
            raise ValueError("Tag cannot be empty")

        self._tag_stack.append(tag.strip())
        try:
            yield
        finally:
            flushed_tag = self._current_tag()
            self._tag_stack.pop()
            self._flush_tag(flushed_tag)

    def _extract_tag(self, kwargs: dict[str, Any]) -> Optional[str]:
        tag = kwargs.pop("tag", None)
        # Silently swallow logging-style kwargs we do not currently support
        kwargs.pop("exc_info", None)
        kwargs.pop("stack_info", None)
        kwargs.pop("extra", None)
        return tag

    def info(self, message: Any, *args: Any, **kwargs: Any) -> None:
        tag = self._extract_tag(kwargs)
        self._log("INFO", message, *args, extra_tag=tag)

    def warning(self, message: Any, *args: Any, **kwargs: Any) -> None:
        tag = self._extract_tag(kwargs)
        self._log("WARN", message, *args, extra_tag=tag)

    def error(self, message: Any, *args: Any, **kwargs: Any) -> None:
        tag = self._extract_tag(kwargs)
        self._log("ERROR", message, *args, extra_tag=tag)

    def flush(self) -> None:
        for key in list(self._buffers.keys()):
            tag = "" if key == "root" else key
            self._flush_tag(tag)

    # ---------------------------------------------------------------- artifact helpers
    def log_text(self, name: str, content: str, *, artifact_path: Optional[str] = None) -> None:
        if not (self.recorder and self.recorder.active_run):
            return

        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, f"{name}.txt")
            with open(file_path, "w") as fh:
                fh.write(content)
            self.recorder.log_artifact(file_path, artifact_path=artifact_path or "alphacopilot/text")

    def log_json(self, name: str, payload: Any, *, artifact_path: Optional[str] = None) -> None:
        if not (self.recorder and self.recorder.active_run):
            return

        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, f"{name}.json")
            with open(file_path, "w") as fh:
                json.dump(payload, fh, indent=2)
            self.recorder.log_artifact(file_path, artifact_path=artifact_path or "alphacopilot/json")

    def log_lines(self, name: str, lines: Iterable[str], *, artifact_path: Optional[str] = None) -> None:
        self.log_text(name, "\n".join(lines), artifact_path=artifact_path)

    def log_dataframe_csv(self, name: str, df, *, artifact_path: Optional[str] = None) -> None:
        if df is None:
            return
        if not (self.recorder and self.recorder.active_run):
            return
        if hasattr(df, "empty") and df.empty:
            return

        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, f"{name}.csv")
            df.to_csv(file_path, index=False)
            self.recorder.log_artifact(file_path, artifact_path=artifact_path or "alphacopilot/dataframes")


def create_recorder_logger(recorder: Optional[Recorder]) -> RecorderLogger:
    """Factory mirroring the previous get_logger API."""

    return RecorderLogger(recorder=recorder)

