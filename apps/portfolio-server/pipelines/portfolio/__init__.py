"""
Portfolio allocation pipelines.

This package exposes utilities to build and execute the portfolio allocation
pipeline powered by Pathway. The pipeline ingests allocation requests,
performs adaptive optimisation and emits allocation recommendations for each
user.
"""

from .allocation_pipeline import (
    PortfolioAllocationRequest,
    build_portfolio_allocation_pipeline,
    run_portfolio_allocation_requests,
)

__all__ = [
    "PortfolioAllocationRequest",
    "build_portfolio_allocation_pipeline",
    "run_portfolio_allocation_requests",
]

