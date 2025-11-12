from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import pathway as pw

from utils.objective_intake import (
    extract_from_transcript,
    merge_structured_payload,
    normalise_structured_payload,
    validate_structured_payload,
)


@dataclass
class ObjectiveIntakePayload:
    """Input payload for the intake pipeline."""

    structured_payload: Optional[Dict[str, Any]] = None  # type: ignore[name-defined]
    transcript: Optional[str] = None
    existing_payload: Optional[Dict[str, Any]] = None  # type: ignore[name-defined]


class ObjectiveIntakeInputSchema(pw.Schema):
    """Schema representing raw payloads passed into the intake pipeline."""

    structured_json: str
    transcript: Optional[str]
    existing_json: str


@dataclass
class ObjectiveIntakeResultRow:
    structured_payload: Dict[str, Any]  # type: ignore[name-defined]
    missing_fields: List[str]
    warnings: List[str]
    status: str


def _json_to_dict(value: Optional[str]) -> Dict[str, Any]:  # type: ignore[name-defined]
    if not value:
        return {}
    try:
        decoded = json.loads(value)
        return decoded if isinstance(decoded, dict) else {}
    except Exception:
        return {}


def run_objective_intake_pipeline(
    payloads: List[ObjectiveIntakePayload],
) -> List[ObjectiveIntakeResultRow]:
    rows = [
        (
            json.dumps(payload.structured_payload or {}, default=str),
            payload.transcript,
            json.dumps(payload.existing_payload or {}, default=str),
        )
        for payload in payloads
    ]

    table = pw.debug.table_from_rows(
        schema=ObjectiveIntakeInputSchema,
        rows=rows,
    )
    df = pw.debug.table_to_pandas(table, include_id=False)

    results: List[ObjectiveIntakeResultRow] = []
    for _, row in df.iterrows():
        structured = _json_to_dict(row["structured_json"])
        existing = _json_to_dict(row["existing_json"])
        transcript = row["transcript"]

        merged = merge_structured_payload(existing, structured)
        if transcript:
            transcript_data = extract_from_transcript(str(transcript))
            merged = merge_structured_payload(merged, transcript_data)

        params, missing_fields, warnings = validate_structured_payload(merged)
        if params:
            payload_dict = normalise_structured_payload(params)
            status = "complete"
            missing = []
            warn_list = warnings
        else:
            payload_dict = merged
            status = "pending"
            missing = missing_fields or []
            warn_list = warnings

        results.append(
            ObjectiveIntakeResultRow(
                structured_payload=payload_dict,
                missing_fields=missing,
                warnings=warn_list,
                status=status,
            )
        )

    return results


