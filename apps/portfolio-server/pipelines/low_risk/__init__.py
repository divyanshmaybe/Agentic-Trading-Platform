"""
Low-risk economic indicators scrapers
"""

from .india_economic_scraper import IndiaEconomicScraper
from .cpi_scraper import CPIScraperFixed
from .fundamental_analyzer_pipeline import (
	FundamentalAnalyzer,
	FundamentalAnalyzerPipeline,
	PipelineResult,
)

__all__ = [
	"IndiaEconomicScraper",
	"CPIScraperFixed",
	"FundamentalAnalyzer",
	"FundamentalAnalyzerPipeline",
	"PipelineResult",
]

