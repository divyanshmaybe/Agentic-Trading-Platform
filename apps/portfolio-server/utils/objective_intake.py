"""
Utility functions and Pydantic models for extracting structured investment
objectives from transcripts or pre-structured JSON payloads.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

import aiohttp
from pydantic import BaseModel, Field, ValidationError, field_validator


# LLM Extractor Classes
class ExtractionResult(BaseModel):
    success: bool
    data: Optional[Dict[str, Any]] = None
    missing_fields: List[str] = Field(default_factory=list)
    validation_errors: List[str] = Field(default_factory=list)
    raw_llm_response: Optional[str] = None


class InvestmentObjective(BaseModel):
    investment_amount: Optional[float] = None
    investment_horizon_years: Optional[int] = None
    expected_return_target: Optional[float] = None
    risk_tolerance: Optional[str] = None
    allocation_strategy: Optional[Dict[str, float]] = None
    constraints: Optional[Dict[str, Any]] = None
    generic_notes: Optional[List[str]] = None


class InvestmentObjectiveExtractor:
    def __init__(self, api_key: str, model: str = "llama-3.1-8b-instant"):
        self.api_key = api_key
        self.model = model
        self.api_url = "https://api.groq.com/openai/v1/chat/completions"
    
    def _create_extraction_prompt(self, transcript: str) -> str:
        """Create a few-shot prompt for extracting investment objectives."""
        
        prompt = f"""You are an expert financial data extractor. Your task is to extract investment objectives from a conversation transcript between a user and an investment professional.

Extract the following information and return ONLY a valid JSON object (no markdown, no explanation, no extra text):

Fields to extract (only include if mentioned in transcript):
- investment_amount: Total amount user wants to invest (number)
- investment_horizon_years: Investment duration in years (integer)
- expected_return_target: Expected return as decimal (e.g., 0.25 for 25%)
- risk_tolerance: Must be one of: "low", "medium", or "high"
- allocation_strategy: Object with low_risk, high_risk, alpha, liquid percentages (decimals that sum to 1.0)
- constraints: Object containing investment constraints (min_allocation, max_allocation, max_weight_drift, segment wise constraints)
- generic_notes: Any additional preferences or notes

Keep in mind that the objective might be complex and span multiple parts of the conversation. Synthesize the information to create a coherent investment objective.

IMPORTANT: Do NOT include fields that are not mentioned in the transcript. Only extract what is explicitly stated or clearly implied.


EXAMPLES:

Example 1:
Transcript: "Hi, I'm John. I want to invest 500,000 rupees for my daughter's education in 5 years. I can't afford to lose much, so I prefer safe options."
Output:
{{
  "investment_amount": 500000,
  "investment_horizon_years": 5,
  "risk_tolerance": "low",
  "generic_notes": ["Investment for daughter's education, prefers safe options"]
}}

Example 2:
Transcript: "Professional: How much are you looking to invest? User: Around 2 million. Professional: What's your timeline? User: 10 years, retirement planning. Professional: Risk appetite? User: I'm okay with moderate risk, aiming for 15% annual returns. Professional: Any preferences? User: No tobacco or alcohol companies please."
Output:
{{
  "investment_amount": 2000000,
  "investment_horizon_years": 10,
  "expected_return_target": 0.15,
  "risk_tolerance": "medium",
  "constraints": {{
    "ESG_exclusions": ["tobacco", "alcohol"]
  }},
  "generic_notes": ["Retirement planning, ESG-conscious investor"]
}}

Example 3:
Transcript: "User: I have 10 lakhs. Professional: Timeline? User: 3 years. Professional: Risk level? User: High, I want aggressive growth. Target 30% returns. I want 60% in high-risk stocks, 25% in moderate, 10% in alternatives, 5% cash."
Output:
{{
  "investment_amount": 1000000,
  "investment_horizon_years": 3,
  "expected_return_target": 0.30,
  "risk_tolerance": "high",
  "allocation_strategy": {{
    "low_risk": 0.25,
    "high_risk": 0.60,
    "alpha": 0.10,
    "liquid": 0.05
  }},
  "generic_notes": ["Seeking aggressive growth strategy"]
}}

NOW EXTRACT FROM THIS TRANSCRIPT:

Transcript: "{transcript}"

Return ONLY the JSON object, no other text:"""
        
        return prompt
    
    async def extract_from_transcript(self, transcript: str) -> ExtractionResult:
        try:
            prompt = self._create_extraction_prompt(transcript)

            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "model": self.model,
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a financial data extraction expert. Extract investment information and return ONLY valid JSON with no additional text or markdown."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                "temperature": 0.1,
                "max_tokens": 1024
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.api_url, 
                    headers=headers, 
                    json=payload
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        return ExtractionResult(
                            success=False,
                            validation_errors=[f"API Error {response.status}: {error_text}"]
                        )
                    
                    result = await response.json()
                    llm_response = result["choices"][0]["message"]["content"]
            
            # Parse and validate the response
            return self._parse_and_validate(llm_response)
            
        except Exception as e:
            return ExtractionResult(
                success=False,
                validation_errors=[f"Extraction error: {str(e)}"]
            )
    
    def _parse_and_validate(self, llm_response: str) -> ExtractionResult:
        """
        Parse LLM response and validate against schema
        """
        try:
            cleaned_response = llm_response.strip()
            if cleaned_response.startswith("```"):
                cleaned_response = re.sub(r'^```(?:json)?\n?', '', cleaned_response)
                cleaned_response = re.sub(r'\n?```$', '', cleaned_response)
            

            raw_data = json.loads(cleaned_response)
            investment_obj = InvestmentObjective(**raw_data)
            
            # Identify missing fields
            missing_fields = self._identify_missing_fields(investment_obj)
            
            # Additional validation
            validation_errors = self._additional_validations(investment_obj)
            
            return ExtractionResult(
                success=len(validation_errors) == 0,
                data=investment_obj.model_dump() if investment_obj else None,
                missing_fields=missing_fields,
                validation_errors=validation_errors,
                raw_llm_response=llm_response
            )
            
        except json.JSONDecodeError as e:
            return ExtractionResult(
                success=False,
                validation_errors=[f"JSON parsing error: {str(e)}"],
                raw_llm_response=llm_response
            )
        except ValidationError as e:
            return ExtractionResult(
                success=False,
                validation_errors=[f"Validation error: {str(e)}"],
                raw_llm_response=llm_response
            )
        except Exception as e:
            return ExtractionResult(
                success=False,
                validation_errors=[f"Unknown error: {str(e)}"],
                raw_llm_response=llm_response
            )
    
    def _identify_missing_fields(self, obj: InvestmentObjective) -> List[str]:
        """Identify which critical fields are missing."""
        missing = []
        
        critical_fields = {
            "investment_amount": obj.investment_amount,
            "expected_return_target": obj.expected_return_target,
            "investment_horizon_years": obj.investment_horizon_years,
            "risk_tolerance": obj.risk_tolerance
        }
        
        for field_name, field_value in critical_fields.items():
            if field_value is None:
                missing.append(field_name)
        
        return missing
    
    def _additional_validations(self, obj: InvestmentObjective) -> List[str]:
        """Perform additional business logic validations."""
        errors = []
        
        # Validate allocation strategy sums to 1
        if obj.allocation_strategy:
            total = sum(obj.allocation_strategy.values())
            if abs(total - 1.0) > 0.01:
                errors.append(
                    f"Allocation strategy must sum to 1.0, got {total:.2f}"
                )
        
        # Validate expected return is reasonable
        if obj.expected_return_target and obj.expected_return_target > 1.0:
            errors.append(
                f"Expected return target seems unrealistic: {obj.expected_return_target*100}%"
            )
        
        return errors


def extract_investment_objectives_sync(
    transcript: str, 
    api_key: str,
    model: str = "llama-3.1-8b-instant"
) -> ExtractionResult:
    import asyncio
    
    extractor = InvestmentObjectiveExtractor(api_key, model)

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # If already in async context, create new loop
            import nest_asyncio
            nest_asyncio.apply()
    except RuntimeError:
        pass
    
    return asyncio.run(extractor.extract_from_transcript(transcript))


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
        if not isinstance(v, str):
            raise ValueError("Risk tolerance category must be a string")
        normalised = v.strip().lower()
        if normalised not in ["low", "medium", "high"]:
            raise ValueError(f"Risk tolerance category must be 'low', 'medium', or 'high', got '{normalised}'")
        return normalised


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
    investment_horizon: Union[str, int] = Field(..., description="Investment timeframe (mandatory)")
    target_return: float = Field(..., description="Target annual return percentage (mandatory)")
    risk_tolerance: RiskTolerance = Field(..., description="Risk tolerance (mandatory)")
    liquidity_needs: str = Field(..., description="Liquidity requirements (mandatory)")
    constraints: Constraints = Field(default_factory=Constraints, description="Investment constraints")
    preferences: Preferences = Field(default_factory=Preferences, description="Investment preferences")
    generic_notes: List[str] = Field(default_factory=list, description="Additional notes")

    @field_validator("liquidity_needs")
    def _validate_liquidity(cls, v: str) -> str:
        if not isinstance(v, str):
            raise ValueError("Liquidity needs must be a string")
        valid_options = {"immediate", "3-12 months", "long"}
        if v not in valid_options:
            raise ValueError(f"liquidity_needs must be one of {sorted(valid_options)}, got '{v}'")
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
    """
    Extract investment objectives from transcript using LLM-based extraction.
    Falls back to regex-based extraction if LLM fails or returns invalid data.
    """
    import os
    
    # Try LLM extraction first
    api_key = os.getenv("GROQ_API_KEY")
    if api_key:
        try:
            result = extract_investment_objectives_sync(transcript, api_key)
            if result.success and result.data:
                try:
                    return _map_llm_output_to_system_format(result.data)
                except ValueError as e:
                    # LLM returned data but it was invalid - log and fall back
                    print(f"LLM returned invalid data: {e}")
        except Exception as e:
            # LLM extraction failed completely - log and fall back
            print(f"LLM extraction failed: {e}")
    
    # Fallback to regex-based extraction
    return _extract_from_transcript_regex(transcript)


def _map_llm_output_to_system_format(llm_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Map LLM extractor output to the format expected by the objective intake system.
    Raises ValueError for missing critical fields.
    """
    if not isinstance(llm_data, dict):
        raise ValueError("LLM data must be a dictionary")
    
    extraction: Dict[str, Any] = {
        "risk_tolerance": {},
        "constraints": {"sector_limits": {}, "ESG_exclusions": []},
        "preferences": {},
        "generic_notes": [],
    }
    
    # Critical fields that must be present
    critical_fields = ["investment_amount", "investment_horizon_years", "expected_return_target", "risk_tolerance"]
    missing_critical = []
    
    for field in critical_fields:
        if field not in llm_data or llm_data[field] is None:
            missing_critical.append(field)
    
    if missing_critical:
        raise ValueError(f"Missing critical fields from LLM output: {missing_critical}")
    
    # Map investment amount
    investment_amount = llm_data.get("investment_amount")
    if not isinstance(investment_amount, (int, float)) or investment_amount <= 0:
        raise ValueError(f"Invalid investment_amount: {investment_amount}")
    extraction["investable_amount"] = float(investment_amount)
    
    # Map investment horizon
    horizon_years = llm_data.get("investment_horizon_years")
    if not isinstance(horizon_years, int) or horizon_years <= 0:
        raise ValueError(f"Invalid investment_horizon_years: {horizon_years}")
    
    if horizon_years <= 3:
        extraction["investment_horizon"] = "short"
    elif horizon_years <= 7:
        extraction["investment_horizon"] = "medium"
    else:
        extraction["investment_horizon"] = "long"
    
    # Map expected return target
    expected_return = llm_data.get("expected_return_target")
    if not isinstance(expected_return, (int, float)) or not (0 < expected_return < 1):
        raise ValueError(f"Invalid expected_return_target: {expected_return}. Must be between 0 and 1.")
    extraction["target_return"] = expected_return * 100  # Convert to percentage
    
    # Map risk tolerance
    risk_tolerance = llm_data.get("risk_tolerance")
    if not isinstance(risk_tolerance, str) or risk_tolerance.lower() not in ["low", "medium", "high"]:
        raise ValueError(f"Invalid risk_tolerance: {risk_tolerance}. Must be 'low', 'medium', or 'high'")
    extraction["risk_tolerance"]["category"] = risk_tolerance.lower()
    
    # Map allocation strategy to preferences (if available)
    if "allocation_strategy" in llm_data:
        allocation_strategy = llm_data["allocation_strategy"]
        if isinstance(allocation_strategy, dict):
            # Validate that allocation sums to 1.0
            total = sum(allocation_strategy.values())
            if abs(total - 1.0) > 0.01:
                raise ValueError(f"Allocation strategy must sum to 1.0, got {total}")
            extraction["preferences"]["allocation_strategy"] = allocation_strategy
    
    # Map constraints
    if "constraints" in llm_data:
        llm_constraints = llm_data["constraints"]
        if isinstance(llm_constraints, dict):
            # Map ESG exclusions
            if "ESG_exclusions" in llm_constraints:
                esg_exclusions = llm_constraints["ESG_exclusions"]
                if isinstance(esg_exclusions, list):
                    extraction["constraints"]["ESG_exclusions"] = esg_exclusions
            
            # Map segment_wise constraints (ensure 'cash' is converted to 'liquid')
            if "segment_wise" in llm_constraints:
                segment_wise = llm_constraints["segment_wise"]
                if isinstance(segment_wise, dict):
                    # Convert 'cash' to 'liquid' if present
                    if "cash" in segment_wise:
                        segment_wise["liquid"] = segment_wise.pop("cash")
                    extraction["constraints"]["segment_wise"] = segment_wise
            elif "risk_wise" in llm_constraints:
                # Backward compatibility: map risk_wise to segment_wise
                risk_wise = llm_constraints["risk_wise"]
                if isinstance(risk_wise, dict):
                    if "cash" in risk_wise:
                        risk_wise["liquid"] = risk_wise.pop("cash")
                    extraction["constraints"]["segment_wise"] = risk_wise
            
            # Map other constraints with validation
            for key, value in llm_constraints.items():
                if key not in ["ESG_exclusions", "segment_wise", "risk_wise"]:
                    if isinstance(value, (int, float)):
                        extraction["constraints"][key] = float(value)
                    elif isinstance(value, (list, dict)):
                        extraction["constraints"][key] = value
    
    # Map generic notes
    if "generic_notes" in llm_data:
        generic_notes = llm_data["generic_notes"]
        if isinstance(generic_notes, list):
            extraction["generic_notes"] = generic_notes
        elif isinstance(generic_notes, str):
            extraction["generic_notes"] = [generic_notes]
    
    # Set liquidity needs based on horizon (required field)
    horizon = extraction.get("investment_horizon")
    if horizon == "short":
        extraction["liquidity_needs"] = "3-12 months"
    elif horizon == "medium":
        extraction["liquidity_needs"] = "3-12 months"
    else:
        extraction["liquidity_needs"] = "long"
    
    return extraction


def _extract_from_transcript_regex(transcript: str) -> Dict[str, Any]:
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
        amount_str = amount_match.group(1).replace(",", "").strip()
        if not amount_str:
            # Regex matched but captured empty string - skip
            pass
        else:
            try:
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
            except ValueError:
                # Invalid number format - skip
                pass

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

    # Set liquidity needs based on horizon if not already set
    if not extraction.get("liquidity_needs"):
        horizon = extraction.get("investment_horizon")
        if horizon == "short":
            extraction["liquidity_needs"] = "3-12 months"
        elif horizon == "medium":
            extraction["liquidity_needs"] = "3-12 months"
        else:
            extraction["liquidity_needs"] = "long"

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


