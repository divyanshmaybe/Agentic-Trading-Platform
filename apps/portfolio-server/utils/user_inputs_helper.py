"""
Helper function to create standardized user_inputs matching transcript.py format.

This ensures all user_inputs dictionaries follow the same structure as defined
in transcript.py, which is the single source of truth.
"""

import json
from typing import Any, Dict, Optional


def create_user_inputs(
    *,
    investment_horizon_years: int,
    expected_return_target: float,
    risk_tolerance: str,
    allocation_strategy: Optional[Dict[str, float]] = None,
    constraints: Optional[Dict[str, Any]] = None,
    generic_notes: Optional[str] = None,
    investment_amount: Optional[float] = None,  # Optional, not used by PortfolioManager but kept for consistency
) -> Dict[str, Any]:
    """
    Create standardized user_inputs dictionary matching transcript.py format.
    
    This is the single source of truth format for user_inputs that PortfolioManager expects.
    
    Args:
        investment_horizon_years: Investment duration in years
        expected_return_target: Expected return as decimal (e.g., 0.18 for 18%)
        risk_tolerance: Risk tolerance level ("low", "medium", or "high")
        allocation_strategy: Optional dict with low_risk, high_risk, alpha, liquid percentages
        constraints: Optional dict with segment_wise, max_weight_drift, ESG_exclusions, etc.
        generic_notes: Optional notes string
        investment_amount: Optional investment amount (not used by PortfolioManager but kept for consistency)
    
    Returns:
        Standardized user_inputs dictionary matching transcript.py format
    """
    # Default allocation strategy from transcript.py (single source of truth)
    defaults_from_transcript = {
        "low_risk": 0.6,
        "high_risk": 0.15,
        "alpha": 0.15,
        "liquid": 0.1
    }
    expected_segments = {"low_risk", "high_risk", "alpha", "liquid"}
    
    # Default allocation strategy if not provided or empty
    if allocation_strategy is None or (isinstance(allocation_strategy, dict) and len(allocation_strategy) == 0):
        allocation_strategy = defaults_from_transcript.copy()
    elif isinstance(allocation_strategy, dict):
        # Make a copy to avoid mutating the original
        allocation_strategy = allocation_strategy.copy()
        
        # Ensure 'cash' is converted to 'liquid' for consistency
        if "cash" in allocation_strategy:
            allocation_strategy["liquid"] = allocation_strategy.pop("cash")
        
        # Check if allocation_strategy is incomplete (missing segments or sums incorrectly)
        total = sum(allocation_strategy.values())
        segments = set(allocation_strategy.keys())
        
        # If allocation doesn't sum to 1.0, normalize it
        if abs(total - 1.0) > 0.01 and total > 0:
            allocation_strategy = {k: v/total for k, v in allocation_strategy.items()}
        
        # If allocation is incomplete (missing segments), fill with defaults for missing segments
        if segments != expected_segments:
            # Use defaults for missing segments
            # Keep specified segments, use defaults for missing ones
            for seg in expected_segments:
                if seg not in allocation_strategy:
                    allocation_strategy[seg] = defaults_from_transcript[seg]
            # Normalize to sum to 1.0 after filling missing segments
            total = sum(allocation_strategy.values())
            if abs(total - 1.0) > 0.01 and total > 0:
                allocation_strategy = {k: v/total for k, v in allocation_strategy.items()}
    else:
        # Invalid type - use defaults
        allocation_strategy = defaults_from_transcript.copy()
    
    # Default constraints if not provided
    if constraints is None:
        constraints = {
            "segment_wise": {
                "low_risk": {"min": 0.0, "max": 1.0},
                "high_risk": {"min": 0.0, "max": 1.0},
                "alpha": {"min": 0.0, "max": 1.0},
                "liquid": {"min": 0.0, "max": 1.0}
            },
            "max_weight_drift": 0.15,
            "rebalancing_trigger": 0.15
        }
    else:
        # Ensure segment_wise exists and 'cash' is converted to 'liquid'
        segment_wise = constraints.get("segment_wise", {})
        if "cash" in segment_wise:
            segment_wise["liquid"] = segment_wise.pop("cash")
        if "segment_wise" not in constraints:
            constraints["segment_wise"] = segment_wise
        
        # Ensure max_weight_drift exists
        if "max_weight_drift" not in constraints:
            constraints["max_weight_drift"] = constraints.get("rebalancing_trigger", 0.15)
    
    user_inputs: Dict[str, Any] = {
        "investment_horizon_years": investment_horizon_years,
        "expected_return_target": expected_return_target,
        "risk_tolerance": risk_tolerance.lower(),
        "allocation_strategy": allocation_strategy,
        "constraints": constraints,
    }
    
    # Add optional fields if provided
    if investment_amount is not None:
        user_inputs["investment_amount"] = investment_amount
    
    if generic_notes:
        user_inputs["generic_notes"] = generic_notes
    
    return user_inputs


def extract_user_inputs_from_objective(objective: Any) -> Dict[str, Any]:
    """
    Extract user_inputs from Objective model, converting to transcript.py format.
    
    Args:
        objective: Objective model instance from database
    
    Returns:
        Standardized user_inputs dictionary
    """
    # Get structured payload if available
    structured = objective.structured_payload
    if isinstance(structured, str):
        structured = json.loads(structured)
    elif structured is None:
        structured = {}
    
    # Extract allocation strategy from preferences or structured payload
    # IMPORTANT: If LLM inferred equal weights (0.25 each), create_user_inputs() will detect and replace with defaults
    allocation_strategy = None
    if structured.get("preferences", {}).get("allocation_strategy"):
        allocation_strategy = structured["preferences"]["allocation_strategy"]
        # Make a copy to avoid mutating the original
        if isinstance(allocation_strategy, dict):
            allocation_strategy = allocation_strategy.copy()
    elif objective.preferences:
        prefs = objective.preferences
        if isinstance(prefs, str):
            prefs = json.loads(prefs)
        allocation_strategy = prefs.get("allocation_strategy")
        # Make a copy to avoid mutating the original
        if isinstance(allocation_strategy, dict):
            allocation_strategy = allocation_strategy.copy()
    
    # Extract constraints
    constraints = None
    if objective.constraints:
        constraints = objective.constraints
        if isinstance(constraints, str):
            constraints = json.loads(constraints)
    
    # Get investment_horizon_years
    horizon_years = objective.investment_horizon_years
    if not horizon_years and structured.get("investment_horizon"):
        # Convert horizon label to years if needed
        horizon_label = structured["investment_horizon"]
        if horizon_label == "short":
            horizon_years = 3
        elif horizon_label == "medium":
            horizon_years = 7
        else:
            horizon_years = 15
    
    # Get expected_return_target (convert from percentage if needed)
    expected_return = objective.target_return
    if expected_return:
        expected_return = float(expected_return) / 100.0  # Convert percentage to decimal
    elif structured.get("target_return"):
        expected_return = float(structured["target_return"]) / 100.0
    else:
        expected_return = 0.18  # Default
    
    # Get risk tolerance
    risk_tolerance = objective.risk_tolerance
    if not risk_tolerance and structured.get("risk_tolerance", {}).get("category"):
        risk_tolerance = structured["risk_tolerance"]["category"]
    if not risk_tolerance:
        risk_tolerance = "medium"  # Default
    
    # Get generic notes
    generic_notes = None
    if objective.generic_notes:
        notes = objective.generic_notes
        if isinstance(notes, str):
            try:
                notes = json.loads(notes)
            except:
                notes = [notes]
        if isinstance(notes, list) and notes:
            generic_notes = notes[0] if isinstance(notes[0], str) else str(notes[0])
    
    return create_user_inputs(
        investment_horizon_years=horizon_years or 15,
        expected_return_target=expected_return,
        risk_tolerance=risk_tolerance,
        allocation_strategy=allocation_strategy,
        constraints=constraints,
        generic_notes=generic_notes,
        investment_amount=float(objective.investable_amount) if objective.investable_amount else None,
    )


def extract_user_inputs_from_portfolio(portfolio: Any) -> Dict[str, Any]:
    """
    Extract user_inputs from Portfolio model, converting to transcript.py format.
    
    Args:
        portfolio: Portfolio model instance from database
    
    Returns:
        Standardized user_inputs dictionary
    """
    # Extract allocation strategy from portfolio
    # IMPORTANT: If equal weights (0.25 each) are found, create_user_inputs() will detect and replace with defaults
    allocation_strategy = None
    if portfolio.allocation_strategy:
        alloc = portfolio.allocation_strategy
        if isinstance(alloc, str):
            alloc = json.loads(alloc)
        if isinstance(alloc, dict):
            weights = alloc.get("weights") or alloc
            if isinstance(weights, dict):
                allocation_strategy = {k: float(v) for k, v in weights.items() if isinstance(v, (int, float))}
                # Make a copy to avoid mutating the original
                if allocation_strategy:
                    allocation_strategy = allocation_strategy.copy()
    
    # Extract constraints from portfolio
    constraints = None
    if portfolio.constraints:
        constraints = portfolio.constraints
        if isinstance(constraints, str):
            constraints = json.loads(constraints)
    
    # Get expected_return_target (convert from decimal percentage if needed)
    expected_return = float(portfolio.expected_return_target) if portfolio.expected_return_target else 0.18
    if expected_return > 1.0:
        expected_return = expected_return / 100.0  # Convert percentage to decimal
    
    return create_user_inputs(
        investment_horizon_years=int(portfolio.investment_horizon_years) if portfolio.investment_horizon_years else 15,
        expected_return_target=expected_return,
        risk_tolerance=portfolio.risk_tolerance or "medium",
        allocation_strategy=allocation_strategy,
        constraints=constraints,
        investment_amount=float(portfolio.investment_amount) if portfolio.investment_amount else None,
    )

