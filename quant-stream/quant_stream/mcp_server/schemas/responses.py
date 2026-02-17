"""Response schemas for MCP tools."""

from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field


class CalculateFactorResponse(BaseModel):
    """Response schema for calculate_factor tool."""
    
    success: bool = Field(description="Whether calculation succeeded")
    factor_name: str = Field(description="Name of calculated factor")
    num_samples: int = Field(description="Number of data samples")
    data: Optional[List[Dict[str, Any]]] = Field(None, description="Factor data (optional)")
    error: Optional[str] = Field(None, description="Error message if failed")


class RunWorkflowResponse(BaseModel):
    """Response schema for run_workflow tool."""
    
    success: bool = Field(description="Whether workflow succeeded")
    metrics: Dict[str, float] = Field(description="Performance metrics")
    run_info: Dict[str, Any] = Field(description="MLflow run information")
    error: Optional[str] = Field(None, description="Error message if failed")

