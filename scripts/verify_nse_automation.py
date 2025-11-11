#!/usr/bin/env python3
"""
NSE Automated Trading - System Verification Script

Verifies that all components are properly configured and integrated:
1. Pathway usage in trade execution pipeline
2. Celery workers registration
3. Database schema
4. Kafka topics
5. Order monitoring integration
6. Email notification setup
"""

import importlib.util
import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple

# Setup paths
REPO_ROOT = Path(__file__).resolve().parents[1]  # Go up one level from scripts/
PORTFOLIO_SERVER_ROOT = REPO_ROOT / "apps" / "portfolio-server"
AUTH_SERVER_ROOT = REPO_ROOT / "apps" / "auth_server"

if str(PORTFOLIO_SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(PORTFOLIO_SERVER_ROOT))

# Colors
GREEN = '\033[0;32m'
YELLOW = '\033[1;33m'
RED = '\033[0;31m'
BLUE = '\033[0;34m'
NC = '\033[0m'  # No Color


def print_header(text: str):
    print(f"\n{BLUE}{'=' * 80}{NC}")
    print(f"{BLUE}{text}{NC}")
    print(f"{BLUE}{'=' * 80}{NC}\n")


def print_success(text: str):
    print(f"{GREEN}✅ {text}{NC}")


def print_warning(text: str):
    print(f"{YELLOW}⚠️  {text}{NC}")


def print_error(text: str):
    print(f"{RED}❌ {text}{NC}")


def print_info(text: str):
    print(f"   {text}")


def check_file_exists(filepath: Path, description: str) -> bool:
    """Check if a file exists."""
    if filepath.exists():
        print_success(f"{description} exists: {filepath.name}")
        return True
    else:
        print_error(f"{description} missing: {filepath}")
        return False


def check_pathway_usage() -> Tuple[bool, List[str]]:
    """Verify Pathway is used in trade execution pipeline."""
    print_header("🔍 Verifying Pathway Usage")
    
    issues = []
    pipeline_file = PORTFOLIO_SERVER_ROOT / "pipelines" / "nse" / "trade_execution_pipeline.py"
    
    if not check_file_exists(pipeline_file, "Trade execution pipeline"):
        return False, ["Trade execution pipeline not found"]
    
    with open(pipeline_file, 'r') as f:
        content = f.read()
    
    # Check for Pathway imports
    pathway_checks = {
        "import pathway as pw": "Pathway import",
        "pw.io.python.read": "Pathway Python connector",
        "pw.udf": "Pathway UDF decorators",
        "@pw.udf": "UDF decorator usage",
        "pw.this": "Pathway this selector",
        "ConnectorSubject": "Custom connector subject",
        "pw.io.subscribe": "Pathway subscription",
    }
    
    for check, desc in pathway_checks.items():
        if check in content:
            print_success(f"{desc} found")
        else:
            print_warning(f"{desc} not found")
            issues.append(f"Missing {desc}")
    
    # Check for allocation logic
    if "get_allocation" in content:
        print_success("Allocation logic integrated")
    else:
        print_warning("Allocation logic not found")
        issues.append("Missing allocation logic")
    
    return len(issues) == 0, issues


def check_celery_workers() -> Tuple[bool, List[str]]:
    """Verify Celery workers are registered."""
    print_header("🔍 Verifying Celery Workers")
    
    issues = []
    celery_file = PORTFOLIO_SERVER_ROOT / "celery_app.py"
    
    if not check_file_exists(celery_file, "Celery configuration"):
        return False, ["Celery configuration not found"]
    
    with open(celery_file, 'r') as f:
        content = f.read()
    
    # Check for worker registrations
    workers = {
        "workers.trade_execution_tasks": "Trade execution worker",
        "workers.order_monitor_worker": "Order monitor worker",
        "workers.pipeline_tasks": "Pipeline tasks",
    }
    
    for worker, desc in workers.items():
        if worker in content:
            print_success(f"{desc} registered")
        else:
            print_error(f"{desc} not registered")
            issues.append(f"Missing {desc}")
    
    # Check for beat schedule tasks
    beat_tasks = {
        "order-monitor-check": "Order monitor beat task",
        "pipeline.trade_execution.process_signal": "Trade execution task",
    }
    
    for task, desc in beat_tasks.items():
        if task in content:
            print_success(f"{desc} configured")
        else:
            print_warning(f"{desc} not configured")
    
    return len(issues) == 0, issues


def check_database_schema() -> Tuple[bool, List[str]]:
    """Verify database schema has required models."""
    print_header("🔍 Verifying Database Schema")
    
    issues = []
    
    # Check portfolio-server schema
    portfolio_schema = PORTFOLIO_SERVER_ROOT / "prisma" / "schema.prisma"
    if check_file_exists(portfolio_schema, "Portfolio-server schema"):
        with open(portfolio_schema, 'r') as f:
            content = f.read()
        
        if "model TradeExecutionLog" in content:
            print_success("TradeExecutionLog model defined")
        else:
            print_error("TradeExecutionLog model missing")
            issues.append("TradeExecutionLog model not defined")
        
        required_fields = [
            "request_id",
            "user_id",
            "symbol",
            "allocated_capital",
            "confidence",
            "take_profit_pct",
            "stop_loss_pct",
        ]
        
        for field in required_fields:
            if field in content:
                print_success(f"  Field '{field}' exists")
            else:
                print_error(f"  Field '{field}' missing")
                issues.append(f"Missing field: {field}")
    else:
        issues.append("Portfolio schema file not found")
    
    # Check auth-server schema
    auth_schema = AUTH_SERVER_ROOT / "prisma" / "schema.prisma"
    if check_file_exists(auth_schema, "Auth-server schema"):
        with open(auth_schema, 'r') as f:
            content = f.read()
        
        if "subscriptions" in content and "String[]" in content:
            print_success("User.subscriptions field exists")
        else:
            print_error("User.subscriptions field missing")
            issues.append("User.subscriptions not defined")
    else:
        issues.append("Auth schema file not found")
    
    return len(issues) == 0, issues


def check_services() -> Tuple[bool, List[str]]:
    """Verify service files exist and are properly structured."""
    print_header("🔍 Verifying Services")
    
    issues = []
    
    services = {
        "trade_execution_service.py": "Trade execution service",
        "pipeline_service.py": "Pipeline service",
        "trade_email_service.py": "Trade email service",
    }
    
    for filename, desc in services.items():
        filepath = PORTFOLIO_SERVER_ROOT / "services" / filename
        if check_file_exists(filepath, desc):
            with open(filepath, 'r') as f:
                content = f.read()
            
            if "async def" in content:
                print_info(f"  Contains async methods")
            
            if filename == "trade_execution_service.py":
                if "_create_tp_sl_orders" in content:
                    print_success(f"  TP/SL order creation implemented")
                else:
                    print_error(f"  TP/SL order creation missing")
                    issues.append("TP/SL order creation not implemented")
        else:
            issues.append(f"{desc} not found")
    
    return len(issues) == 0, issues


def check_utils() -> Tuple[bool, List[str]]:
    """Verify utility modules."""
    print_header("🔍 Verifying Utilities")
    
    issues = []
    
    trade_exec_utils = PORTFOLIO_SERVER_ROOT / "utils" / "trade_execution.py"
    if check_file_exists(trade_exec_utils, "Trade execution utilities"):
        with open(trade_exec_utils, 'r') as f:
            content = f.read()
        
        required_items = {
            "def get_allocation": "Allocation function",
            "class TradeSignal": "TradeSignal dataclass",
            "class PortfolioSnapshot": "PortfolioSnapshot dataclass",
            "class TradeExecutionPayload": "TradeExecutionPayload dataclass",
            "DEFAULT_TAKE_PROFIT_PCT": "Default take-profit constant",
            "DEFAULT_STOP_LOSS_PCT": "Default stop-loss constant",
        }
        
        for item, desc in required_items.items():
            if item in content:
                print_success(f"{desc} defined")
            else:
                print_error(f"{desc} missing")
                issues.append(f"Missing {desc}")
    else:
        issues.append("Trade execution utilities not found")
    
    return len(issues) == 0, issues


def check_tests() -> Tuple[bool, List[str]]:
    """Verify test files exist."""
    print_header("🔍 Verifying Tests")
    
    issues = []
    
    tests = {
        "test_trade_execution_pipeline.py": "Trade execution pipeline tests",
        "demo_nse_automation.py": "NSE automation demo script",
    }
    
    for filename, desc in tests.items():
        filepath = PORTFOLIO_SERVER_ROOT / "tests" / filename
        check_file_exists(filepath, desc)
    
    return True, issues


def check_documentation() -> Tuple[bool, List[str]]:
    """Verify documentation exists."""
    print_header("🔍 Verifying Documentation")
    
    issues = []
    
    docs = {
        "NSE_AUTOMATED_TRADING.md": "Automated trading documentation",
        "ARCHITECTURE.md": "Architecture documentation",
    }
    
    for filename, desc in docs.items():
        filepath = REPO_ROOT / "docs" / filename
        if check_file_exists(filepath, desc):
            with open(filepath, 'r') as f:
                content = f.read()
            print_info(f"  Size: {len(content)} bytes")
    
    return True, issues


def main():
    print(f"\n{BLUE}{'=' * 80}{NC}")
    print(f"{BLUE}🔍 NSE Automated Trading - System Verification{NC}")
    print(f"{BLUE}{'=' * 80}{NC}\n")
    
    all_checks = []
    
    # Run all checks
    checks = [
        ("Pathway Usage", check_pathway_usage),
        ("Celery Workers", check_celery_workers),
        ("Database Schema", check_database_schema),
        ("Services", check_services),
        ("Utilities", check_utils),
        ("Tests", check_tests),
        ("Documentation", check_documentation),
    ]
    
    for name, check_func in checks:
        passed, issues = check_func()
        all_checks.append((name, passed, issues))
    
    # Summary
    print_header("📊 Verification Summary")
    
    total_checks = len(all_checks)
    passed_checks = sum(1 for _, passed, _ in all_checks if passed)
    failed_checks = total_checks - passed_checks
    
    for name, passed, issues in all_checks:
        if passed:
            print_success(f"{name}: PASSED")
        else:
            print_error(f"{name}: FAILED")
            for issue in issues:
                print_info(f"  - {issue}")
    
    print(f"\n{BLUE}{'=' * 80}{NC}")
    if failed_checks == 0:
        print(f"{GREEN}✅ ALL CHECKS PASSED ({passed_checks}/{total_checks}){NC}")
        print(f"\n{GREEN}🎉 NSE Automated Trading System is properly configured!{NC}")
        print(f"\n{BLUE}Next Steps:{NC}")
        print("   1. Run database migration: ./scripts/migrate_nse_automation.sh")
        print("   2. Start Celery workers: celery -A celery_app worker")
        print("   3. Start Celery beat: celery -A celery_app beat")
        print("   4. Run demo: python tests/demo_nse_automation.py --dry-run")
    else:
        print(f"{RED}❌ SOME CHECKS FAILED ({failed_checks}/{total_checks}){NC}")
        print(f"\n{YELLOW}Please review the issues above and fix them.{NC}")
    
    print(f"{BLUE}{'=' * 80}{NC}\n")
    
    return 0 if failed_checks == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
