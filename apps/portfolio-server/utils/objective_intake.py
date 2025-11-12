"""
Utility functions and Pydantic models for extracting structured investment
objectives from transcripts or pre-structured JSON payloads.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

from pydantic import BaseModel, Field, ValidationError, field_validator


MANDATORY_FIELDS = [
    "investable_amount",
    "investment_horizon",
    "target_return",
    "risk_tolerance.category",
    "liquidity_needs",
]


def _normalise_units_to_days(value: float, unit: str) -> float:
    unit = unit.lower()
    if unit in {"day", "days"}:
        return value
    if unit in {"week", "weeks"}:
        return value * 7
    if unit in {"month", "months"}:
        return value * 30
    if unit in {"year", "years"}:
        return value * 365
    return value


def normalise_time_period(value: float, unit: str) -> str:
    total_days = _normalise_units_to_days(value, unit)
    if total_days < 365:
        return "short"
    if total_days < 1095:
        return "medium"
    if total_days < 1825:
        return "long"
    years = int(total_days / 365)
    return f"{years} years"


class RiskTolerance(BaseModel):
    category: str = Field(..., description="Risk category: low/medium/high")
    risk_aversion_lambda: Optional[float] = Field(
        None, description="Numerical risk aversion score"
    )

    @field_validator("category")
    def _normalise_category(cls, v: str) -> str:
        return v.strip().lower()


class Constraints(BaseModel):
    sector_limits: Dict[str, float] = Field(default_factory=dict)
    min_allocation: Optional[float] = None
    max_allocation: Optional[float] = None
    ESG_exclusions: List[str] = Field(default_factory=list)
    no_leverage: Optional[bool] = None
    max_smallcap: Optional[float] = None


class Preferences(BaseModel):
    diversification_priority: Optional[str] = None
    rebalancing_frequency: Optional[str] = None
    automation_mode: Optional[str] = None


class InvestmentParameters(BaseModel):
    investable_amount: float = Field(..., description="Capital to allocate (mandatory)")
    investment_horizon: Union[str, int] = Field(
        ..., description="Investment timeframe (mandatory)"
    )
    target_return: float = Field(..., description="Target annual return percentage")
    risk_tolerance: RiskTolerance = Field(..., description="Risk tolerance (mandatory)")
    liquidity_needs: str = Field(..., description="Liquidity requirements (mandatory)")
    constraints: Constraints = Field(default_factory=Constraints)
    preferences: Preferences = Field(default_factory=Preferences)
    generic_notes: List[str] = Field(default_factory=list)

    @field_validator("liquidity_needs")
    def _validate_liquidity(cls, v: str) -> str:
        valid_options = {"immediate", "3-12 months", "long"}
        if v not in valid_options:
            raise ValueError(f"liquidity_needs must be one of {sorted(valid_options)}")
        return v


class ExtractionResult(BaseModel):
    extracted_parameters: Dict[str, Any] = Field(default_factory=dict)
    missing_fields: List[str] = Field(default_factory=list)
    completion_status: str = "pending"
    warnings: List[str] = Field(default_factory=list)
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")


def _merge_nested_dict(base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
    merged: Dict[str, Any] = dict(base)
    for key, value in overlay.items():
        if (
            key in merged
            and isinstance(merged[key], dict)
            and isinstance(value, dict)
        ):
            merged[key] = _merge_nested_dict(merged[key], value)
        else:
            merged[key] = value
    return merged


def _extract_user_statements(transcript: str) -> Tuple[str, str]:
    user_lines: List[str] = []
    for line in transcript.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("user:"):
            user_lines.append(stripped[5:].strip())
    return " ".join(user_lines).lower(), "\n".join(user_lines)


def _search_first(patterns: Iterable[str], text: str) -> Optional[re.Match[str]]:
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match
    return None


def extract_from_transcript(transcript: str) -> Dict[str, Any]:
    extraction: Dict[str, Any] = {
        "risk_tolerance": {},
        "constraints": {"sector_limits": {}, "ESG_exclusions": []},
        "preferences": {},
        "generic_notes": [],
    }

    user_text, original_user_text = _extract_user_statements(transcript)

    amount_patterns = [
        r"(?:invest|capital|amount|budget|got|have|set aside).*?(?:is|of|around|approximately)?\s*(?:rs\.?|inr|₹)?\s*([\d,]+)\s*(?:lakh|lakhs|cr|crore|crores|k|thousand|million)?",
        r"(?:rs\.?|inr|₹)\s*([\d,]+)\s*(?:lakh|lakhs|cr|crore|crores|k|thousand|million)?",
        r"([\d,]+)\s*(?:lakh|lakhs|cr|crore|crores|rupees)",
    ]
    if amount_match := _search_first(amount_patterns, user_text):
        amount_str = amount_match.group(1).replace(",", "")
        base_amount = float(amount_str)
        context = user_text[
            max(0, amount_match.start() - 50) : amount_match.end() + 10
        ]
        if "lakh" in context:
            extraction["investable_amount"] = base_amount * 100_000
        elif "cr" in context or "crore" in context:
            extraction["investable_amount"] = base_amount * 10_000_000
        elif "thousand" in context:
            extraction["investable_amount"] = base_amount * 1_000
        elif "hundred" in context:
            extraction["investable_amount"] = base_amount * 100
        elif "million" in context:
            extraction["investable_amount"] = base_amount * 1_000_000
        else:
            extraction["investable_amount"] = base_amount

    horizon_patterns = {
        "short": [
            "short term",
            "short-term",
            "short_term",
            "1 year",
            "6 months",
            "few months",
        ],
        "medium": [
            "medium term",
            "medium-term",
            "medium_term",
            "2 years",
            "3 years",
            "2-3 years",
        ],
        "long": [
            "long term",
            "long-term",
            "long_term",
            "5 years",
            "10 years",
            "5+ years",
            "retirement",
            "decade",
        ],
    }
    for label, keywords in horizon_patterns.items():
        if any(kw in user_text for kw in keywords):
            extraction["investment_horizon"] = label
            break

    if "investment_horizon" not in extraction:
        time_patterns = [
            r"(?:planning for|invest for|horizon of|period of|around|about|next|for)\s*(\d+)\s*(day|days|week|weeks|month|months|year|years)",
            r"(\d+)\s*(day|days|week|weeks|month|months|year|years).*?(?:horizon|period|timeframe|plan)",
        ]
        for pattern in time_patterns:
            if match := re.search(pattern, user_text):
                extraction["investment_horizon"] = normalise_time_period(
                    float(match.group(1)), match.group(2)
                )
                break

    return_patterns = [
        r"(?:return|returns?|expecting|expect|target|looking for|hoping for).*?(\d+(?:\.\d+)?)\s*%",
        r"(?:at least|minimum|min|around)\s*(\d+(?:\.\d+)?)\s*%",
        r"(\d+(?:\.\d+)?)\s*%.*?(?:return|returns?)",
    ]
    if return_match := _search_first(return_patterns, user_text):
        extraction["target_return"] = float(return_match.group(1))

    risk_keywords = {
        "low": [
            "low risk",
            "conservative",
            "risk-averse",
            "safe",
            "minimal risk",
            "very safe",
            "cautious",
        ],
        "medium": [
            "moderate risk",
            "medium risk",
            "balanced",
            "moderate",
            "okay with moderate",
        ],
        "high": [
            "high risk",
            "aggressive",
            "growth",
            "risk-taking",
            "very aggressive",
            "comfortable with high risk",
            "pretty aggressive",
        ],
    }
    for risk_level, keywords in risk_keywords.items():
        if any(keyword in user_text for keyword in keywords):
            extraction["risk_tolerance"]["category"] = risk_level
            break

    if lambda_match := re.search(
        r"risk.*?(?:level|score|rating|is).*?(\d+(?:\.\d+)?)", user_text
    ):
        extraction["risk_tolerance"]["risk_aversion_lambda"] = float(
            lambda_match.group(1)
        )

    liquidity_keywords = {
        "3-12 months": [
            "within a few months",
            "within few months",
            "few months",
            "6 months",
            "3 months",
            "9 months",
            "quarterly access",
            "short-term access",
            "within a year",
            "within the year",
        ],
        "immediate": [
            "immediate",
            "immediately",
            "right away",
            "right now",
            "liquid",
            "emergency fund",
            "emergency",
        ],
        "long": [
            "long term",
            "long-term",
            "no immediate need",
            "locked in",
            "don't need soon",
            "not needed soon",
            "anytime soon",
            "years away",
            "several years",
            "locked for years",
        ],
    }
    for label, keywords in liquidity_keywords.items():
        if any(keyword in user_text for keyword in keywords):
            extraction["liquidity_needs"] = label
            break

    sector_patterns = [
        r"(?:limit|max|maximum|cap|exposure to).*?(it|tech|technology|banking|bank|finance|financial|pharma|pharmaceutical|auto|automobile|fmcg|healthcare|energy).*?(?:to|at|is)?\s*(?:a\s+)?(?:max(?:imum)?\s+of\s+)?(\d+)\s*%",
        r"(it|tech|technology|banking|bank|finance|financial|pharma|pharmaceutical|auto|automobile|fmcg|healthcare|energy).*?(?:limit|max|maximum|cap).*?(\d+)\s*%",
    ]
    sector_mapping = {
        "it": "IT",
        "tech": "IT",
        "technology": "IT",
        "banking": "Banking",
        "bank": "Banking",
        "finance": "Banking",
        "financial": "Banking",
        "pharma": "Pharma",
        "pharmaceutical": "Pharma",
        "auto": "Auto",
        "automobile": "Auto",
        "fmcg": "FMCG",
        "healthcare": "Healthcare",
        "energy": "Energy",
    }
    for pattern in sector_patterns:
        for match in re.finditer(pattern, user_text):
            sector_key = match.group(1)
            limit_value = match.group(2)
            sector = sector_mapping.get(sector_key, sector_key.upper())
            extraction["constraints"]["sector_limits"][sector] = float(limit_value) / 100

    if min_alloc := re.search(r"minimum.*?allocation.*?(\d+)\s*%", user_text):
        extraction["constraints"]["min_allocation"] = float(min_alloc.group(1)) / 100
    if max_alloc := re.search(r"maximum.*?allocation.*?(\d+)\s*%", user_text):
        extraction["constraints"]["max_allocation"] = float(max_alloc.group(1)) / 100

    smallcap_patterns = [
        r"(?:small-cap|small cap|smallcap).*?(?:max|maximum|limit).*?(\d+)\s*%",
        r"(?:max|maximum|limit).*?(\d+)\s*%.*?(?:small-cap|small cap|smallcap)",
    ]
    for pattern in smallcap_patterns:
        if smallcap := re.search(pattern, user_text):
            extraction["constraints"]["max_smallcap"] = float(smallcap.group(1)) / 100
            break

    esg_keywords = [
        "tobacco",
        "alcohol",
        "gambling",
        "weapons",
        "fossil fuel",
        "coal",
        "arms",
        "sin stocks",
    ]
    for keyword in esg_keywords:
        patterns = [
            f"no {keyword}",
            f"avoid {keyword}",
            f"exclude {keyword}",
            f"excluding {keyword}",
            f"not {keyword}",
            f"don't want {keyword}",
            f"not comfortable with {keyword}",
            f"please exclude {keyword}",
        ]
        if any(pat in user_text for pat in patterns):
            if keyword == "sin stocks":
                extraction["constraints"]["ESG_exclusions"].extend(
                    ["tobacco", "gambling", "alcohol"]
                )
            else:
                extraction["constraints"]["ESG_exclusions"].append(keyword)
    extraction["constraints"]["ESG_exclusions"] = list(
        dict.fromkeys(extraction["constraints"]["ESG_exclusions"])
    )

    if any(
        phrase in user_text
        for phrase in [
            "no leverage",
            "avoid leverage",
            "without leverage",
            "absolutely no leverage",
        ]
    ):
        extraction["constraints"]["no_leverage"] = True
    elif any(
        phrase in user_text
        for phrase in ["leverage ok", "allow leverage", "leverage is fine"]
    ):
        extraction["constraints"]["no_leverage"] = False

    if "diversify across" in user_text and "market cap" in user_text:
        extraction["preferences"]["diversification_priority"] = "cap"
    elif "sector" in user_text and "divers" in user_text:
        extraction["preferences"]["diversification_priority"] = "sector"
    elif ("market cap" in user_text or "cap" in user_text) and "divers" in user_text:
        extraction["preferences"]["diversification_priority"] = "cap"
    elif "factor" in user_text and "divers" in user_text:
        extraction["preferences"]["diversification_priority"] = "factor"

    rebalance_keywords = {
        "monthly": ["monthly", "every month", "once a month", "each month"],
        "quarterly": ["quarterly", "every quarter", "once a quarter", "each quarter"],
        "annually": ["annually", "yearly", "once a year", "each year", "annual"],
    }
    for freq, keywords in rebalance_keywords.items():
        if any(keyword in user_text for keyword in keywords):
            extraction["preferences"]["rebalancing_frequency"] = freq
            break

    if any(
        phrase in user_text
        for phrase in [
            "require my approval",
            "require approval",
            "manual approval",
            "review any trades",
        ]
    ):
        extraction["preferences"]["automation_mode"] = "analyst_approval"
    elif "automatic" in user_text or ("auto" in user_text and "execution" in user_text):
        extraction["preferences"]["automation_mode"] = "auto"

    for line in original_user_text.splitlines():
        if len(line.strip()) <= 20:
            continue
        lower_line = line.lower()
        if any(
            keyword in lower_line
            for keyword in [
                "prefer",
                "like",
                "want",
                "looking for",
                "interested in",
                "note",
                "important",
                "also",
                "very important",
            ]
        ):
            if not any(re.search(pattern, lower_line) for pattern in amount_patterns):
                extraction["generic_notes"].append(line.strip())

    return extraction


def identify_missing_fields(extraction: Dict[str, Any]) -> List[str]:
    missing: List[str] = []
    if not extraction.get("investable_amount"):
        missing.append("investable_amount")
    if not extraction.get("investment_horizon"):
        missing.append("investment_horizon")
    if not extraction.get("target_return"):
        missing.append("target_return")
    risk = extraction.get("risk_tolerance", {})
    if not isinstance(risk, dict) or not risk.get("category"):
        missing.append("risk_tolerance.category")
    if not extraction.get("liquidity_needs"):
        missing.append("liquidity_needs")
    return missing


def merge_structured_payload(
    base: Optional[Dict[str, Any]], overlay: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    if not base and not overlay:
        return {}
    if not base:
        return dict(overlay or {})
    if not overlay:
        return dict(base)
    return _merge_nested_dict(base, overlay)


def validate_structured_payload(
    data: Dict[str, Any]
) -> Tuple[Optional[InvestmentParameters], List[str], List[str]]:
    try:
        params = InvestmentParameters.model_validate(data)
        return params, [], []
    except ValidationError as exc:
        missing = identify_missing_fields(data)
        warnings: List[str] = []

        for err in exc.errors():
            loc_parts = [str(part) for part in err.get("loc", ())]
            field_path = ".".join(loc_parts)
            warnings.append(err.get("msg", ""))

            if field_path == "liquidity_needs" and "liquidity_needs" not in missing:
                missing.append("liquidity_needs")
            elif field_path.startswith("risk_tolerance") and "risk_tolerance.category" not in missing:
                missing.append("risk_tolerance.category")

        # Ensure deterministic ordering for testing/logs
        missing = list(dict.fromkeys(missing))
        warnings = [w for w in warnings if w]

        return None, missing, warnings


def normalise_structured_payload(params: InvestmentParameters) -> Dict[str, Any]:
    payload = params.model_dump()
    return payload


def summarise_extraction(
    structured_payload: Dict[str, Any], missing_fields: List[str], warnings: List[str]
) -> ExtractionResult:
    status = "complete" if not missing_fields else "pending"
    return ExtractionResult(
        extracted_parameters=structured_payload,
        missing_fields=missing_fields,
        completion_status=status,
        warnings=warnings,
    )


