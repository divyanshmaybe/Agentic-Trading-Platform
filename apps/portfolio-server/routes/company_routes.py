"""Company report routes for fetching company analysis and reports."""

from __future__ import annotations

import sys
import os
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, HTTPException, status

# Add shared path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
shared_py_path = os.path.join(project_root, "shared/py")
sys.path.insert(0, shared_py_path)

from company_report_service import CompanyReportService
from utils.auth import get_authenticated_user

router = APIRouter(prefix="/company", tags=["Company"])


async def get_company_report_service() -> CompanyReportService:
    """Dependency to get initialized CompanyReportService instance."""
    service = CompanyReportService.get_instance()
    if not service._initialized:
        await service.initialize()
    return service


@router.get("/reports")
async def get_company_reports(
    ticker: List[str] = Query(..., description="Stock ticker symbol(s) (e.g., RELIANCE, TCS)"),
    _: dict = Depends(get_authenticated_user),
    service: CompanyReportService = Depends(get_company_report_service),
) -> dict:
    """
    Get company reports for one or more ticker symbols.
    
    Protected route requiring authentication.
    
    Args:
        ticker: List of stock ticker symbols (query parameter, can be repeated)
        
    Returns:
        Dictionary with reports array containing company report data
        
    Example:
        GET /company/reports?ticker=RELIANCE&ticker=TCS
        
        Response:
        {
            "success": true,
            "count": 2,
            "reports": [
                {
                    "ticker": "RELIANCE",
                    "company_name": "Reliance Industries",
                    ...
                },
                {
                    "ticker": "TCS",
                    "company_name": "Tata Consultancy Services",
                    ...
                }
            ]
        }
    """
    if not ticker:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one ticker symbol is required"
        )
    
    try:
        # Handle single ticker case
        if len(ticker) == 1:
            report = await service.get_report_by_ticker(ticker[0])
            reports = [report] if report else []
        else:
            # Handle multiple tickers case
            reports_dict = await service.get_reports_by_tickers(ticker)
            # Convert to array, filtering out None values
            reports = [
                report for report in reports_dict.values() 
                if report is not None
            ]
        
        return {
            "success": True,
            "count": len(reports),
            "reports": reports,
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch company reports: {str(e)}"
        )
