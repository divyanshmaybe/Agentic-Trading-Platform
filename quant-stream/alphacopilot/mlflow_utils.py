"""Utility helpers for logging AlphaCopilot artifacts to MLflow."""

from __future__ import annotations

import json
import os
import tempfile
from typing import Any, Mapping, Sequence



def _message_to_dict(message: Any) -> dict[str, Any]:
    """Convert a LangChain message object to a serializable dict."""
    msg_type = getattr(message, "type", None) or message.__class__.__name__
    content = getattr(message, "content", None)
    if content is None:
        content = str(message)
    return {
        "type": msg_type,
        "content": content,
    }


def log_llm_interaction_to_mlflow(
    recorder: Any,
    node_tag: str,
    request_messages: Sequence[Any],
    response_content: str,
    step: int | None = None,
) -> None:
    """Log LLM interaction payload to MLflow as a JSON artifact.

    Args:
        recorder: Recorder instance with an active MLflow run.
        node_tag: Identifier for the workflow node (e.g., "01_factor_propose").
        request_messages: Sequence of message objects sent to the LLM.
        response_content: Raw response text from the LLM.
        step: Optional step index for associated metrics logging.
    """
    if recorder is None:
        return

    active_run = getattr(recorder, "active_run", None)
    if active_run is None:
        return

    request_payload = [_message_to_dict(msg) for msg in request_messages]
    payload = {
        "node": node_tag,
        "request": request_payload,
        "response": response_content,
    }

    if step is not None:
        artifact_dir = f"alphacopilot/iter_{step}/llm/{node_tag}"
    else:
        artifact_dir = f"alphacopilot/llm/{node_tag}"
    file_name = "interaction.json"

    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = os.path.join(tmpdir, file_name)
        with open(file_path, "w") as fh:
            json.dump(payload, fh, indent=2)
        recorder.log_artifact(file_path, artifact_path=artifact_dir)



def log_generated_factors_to_mlflow(
    recorder: Any,
    node_tag: str,
    factors: Sequence[Any],
    *,
    step: int | None = None,
) -> None:
    """Persist generated factors (name, expression, metadata) to MLflow."""

    if recorder is None or getattr(recorder, "active_run", None) is None:
        return

    entries: list[dict[str, Any]] = []
    for factor in factors:
        if factor is None:
            continue
        entries.append(
            {
                "name": getattr(factor, "name", None),
                "description": getattr(factor, "description", None),
                "formulation": getattr(factor, "formulation", None),
                "expression": getattr(factor, "expression", None),
                "variables": getattr(factor, "variables", None),
            }
        )

    if not entries:
        return

    if step is not None:
        artifact_dir = f"alphacopilot/iter_{step}"
        file_name = "factors.json"
    else:
        artifact_dir = "alphacopilot"
        file_name = f"{node_tag}_factors.json"

    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = os.path.join(tmpdir, file_name)
        with open(file_path, "w") as fh:
            json.dump(entries, fh, indent=2)
        recorder.log_artifact(file_path, artifact_path=artifact_dir)


def log_workflow_config_to_mlflow(
    recorder: Any,
    config: Mapping[str, Any],
    *,
    artifact_name: str = "workflow_config",
    step: int | None = None,
) -> None:
    """Persist workflow configuration dictionary to MLflow."""

    if recorder is None or getattr(recorder, "active_run", None) is None or not config:
        return

    if step is not None:
        artifact_dir = f"alphacopilot/iter_{step}"
        file_name = "config.json"
    else:
        artifact_dir = "alphacopilot"
        file_name = f"{artifact_name}.json"

    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = os.path.join(tmpdir, file_name)
        with open(file_path, "w") as fh:
            json.dump(config, fh, indent=2)
        recorder.log_artifact(file_path, artifact_path=artifact_dir)

