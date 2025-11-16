#!/usr/bin/env python3
"""Dry run script to validate pipeline components without full execution.

This script checks:
- Environment variables (API keys)
- Kafka connectivity
- Database connectivity
- Pipeline imports
- Basic pipeline structure
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Add project root to path
# Script is at: apps/portfolio-server/scripts/dry_run_pipelines.py
# So parents[2] = portfolio-server, parents[3] = apps, parents[4] = project root
SCRIPT_DIR = Path(__file__).resolve().parent
SERVER_DIR = SCRIPT_DIR.parent  # apps/portfolio-server
PROJECT_ROOT = SERVER_DIR.parent.parent  # project root

# Set up Python path like the actual server does
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "shared" / "py"))
sys.path.insert(0, str(PROJECT_ROOT / "middleware" / "py"))
sys.path.insert(0, str(SERVER_DIR))

from dotenv import load_dotenv

# Load environment
env_path = SERVER_DIR / ".env"
if env_path.exists():
    load_dotenv(env_path, override=False)
else:
    root_env = PROJECT_ROOT / ".env"
    if root_env.exists():
        load_dotenv(root_env, override=False)


def check_env_vars() -> dict[str, bool]:
    """Check if required environment variables are set."""
    print("=" * 60)
    print("Checking Environment Variables...")
    print("=" * 60)
    
    required_vars = {
        "NEWS_ORG_API_KEY": os.getenv("NEWS_ORG_API_KEY"),
        "GEMINI_API_KEY": os.getenv("GEMINI_API_KEY"),
        "REDIS_URL": os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        "DATABASE_URL": os.getenv("DATABASE_URL"),
    }
    
    results = {}
    for var_name, var_value in required_vars.items():
        is_set = var_value is not None and var_value.strip() != ""
        results[var_name] = is_set
        status = "✅" if is_set else "❌"
        if is_set and var_name.endswith("_KEY"):
            print(f"{status} {var_name}: {'*' * min(len(var_value), 20)} (length: {len(var_value)})")
        else:
            print(f"{status} {var_name}: {'Set' if is_set else 'Not Set'}")
    
    print()
    return results


def check_kafka() -> bool:
    """Check Kafka connectivity."""
    print("=" * 60)
    print("Checking Kafka Connectivity...")
    print("=" * 60)
    
    try:
        from kafka_service import default_kafka_bus
        
        kafka_host = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
        print(f"Kafka host: {kafka_host}")
        
        # Try to get the bus (doesn't connect yet, just checks import)
        bus = default_kafka_bus
        print("✅ Kafka service imported successfully")
        print("⚠️  Note: Actual connection test requires Kafka to be running")
        return True
    except Exception as e:
        print(f"❌ Kafka service import failed: {e}")
        return False


def check_database() -> bool:
    """Check database connectivity."""
    print("=" * 60)
    print("Checking Database Connectivity...")
    print("=" * 60)
    
    try:
        # Try importing from the server directory
        import importlib.util
        db_path = SERVER_DIR / "db.py"
        if db_path.exists():
            spec = importlib.util.spec_from_file_location("db", db_path)
            db_module = importlib.util.module_from_spec(spec)
            sys.modules["db"] = db_module
            spec.loader.exec_module(db_module)
            
            db_manager = db_module.get_db_manager()
            print("✅ Database manager imported successfully")
            
            # Try to get a connection (lightweight check)
            try:
                with db_manager.get_session() as session:
                    print("✅ Database connection successful")
                    return True
            except Exception as e:
                print(f"⚠️  Database connection test failed: {e}")
                print("   (This is okay if DB is not running)")
                return False
        else:
            print("⚠️  db.py not found")
            return False
    except Exception as e:
        print(f"⚠️  Database manager import failed: {e}")
        print("   (This is okay if DB is not running)")
        return False


def check_redis() -> bool:
    """Check Redis connectivity."""
    print("=" * 60)
    print("Checking Redis Connectivity...")
    print("=" * 60)
    
    try:
        import redis
        
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        print(f"Redis URL: {redis_url}")
        
        # Try to connect
        r = redis.from_url(redis_url, socket_connect_timeout=2)
        r.ping()
        print("✅ Redis connection successful")
        return True
    except Exception as e:
        print(f"⚠️  Redis connection failed: {e}")
        print("   (This is okay if Redis is not running)")
        return False


def check_pipeline_imports() -> dict[str, bool]:
    """Check if pipeline modules can be imported."""
    print("=" * 60)
    print("Checking Pipeline Imports...")
    print("=" * 60)
    
    results = {}
    
    # Check news pipeline
    try:
        pipelines_dir = SERVER_DIR / "pipelines"
        sys.path.insert(0, str(pipelines_dir))
        from pipelines.news import execute_news_sentiment_pipeline
        print("✅ News sentiment pipeline imported")
        results["news_pipeline"] = True
    except Exception as e:
        print(f"❌ News sentiment pipeline import failed: {e}")
        results["news_pipeline"] = False
    
    # Check NSE pipeline components
    try:
        from pipelines.nse import nse_filings_sentiment
        print("✅ NSE filings sentiment pipeline imported")
        results["nse_pipeline"] = True
    except Exception as e:
        print(f"❌ NSE pipeline import failed: {e}")
        results["nse_pipeline"] = False
    
    # Check research pipeline
    try:
        from pipelines.news.research_pipeline import (
            trading_agent_llm,
            stock_recommender,
            compute_technical_indicators,
        )
        print("✅ Research pipeline utilities imported")
        results["research_pipeline"] = True
    except Exception as e:
        print(f"❌ Research pipeline import failed: {e}")
        results["research_pipeline"] = False
    
    print()
    return results


def check_pipeline_structure() -> dict[str, bool]:
    """Check pipeline file structure."""
    print("=" * 60)
    print("Checking Pipeline File Structure...")
    print("=" * 60)
    
    results = {}
    pipelines_dir = SERVER_DIR / "pipelines"
    
    # Check news pipeline files
    news_dir = pipelines_dir / "news"
    news_files = {
        "news_sentiment_pipeline.py": news_dir / "news_sentiment_pipeline.py",
        "research_pipeline.py": news_dir / "research_pipeline.py",
        "__init__.py": news_dir / "__init__.py",
    }
    
    print("News Pipeline Files:")
    for name, path in news_files.items():
        exists = path.exists()
        results[f"news_{name}"] = exists
        status = "✅" if exists else "❌"
        print(f"  {status} {name}: {path}")
    
    # Check NSE pipeline files
    nse_dir = pipelines_dir / "nse"
    nse_files = {
        "nse_filings_sentiment.py": nse_dir / "nse_filings_sentiment.py",
    }
    
    print("\nNSE Pipeline Files:")
    for name, path in nse_files.items():
        exists = path.exists()
        results[f"nse_{name}"] = exists
        status = "✅" if exists else "❌"
        print(f"  {status} {name}: {path}")
    
    print()
    return results


def check_celery_tasks() -> bool:
    """Check if Celery tasks are properly defined."""
    print("=" * 60)
    print("Checking Celery Tasks...")
    print("=" * 60)
    
    try:
        celery_app_path = SERVER_DIR / "celery_app.py"
        if not celery_app_path.exists():
            print("❌ celery_app.py not found")
            return False
        
        # Import celery app and workers (tasks are registered when workers are imported)
        import importlib.util
        
        # Import celery_app first
        spec = importlib.util.spec_from_file_location("celery_app", celery_app_path)
        celery_module = importlib.util.module_from_spec(spec)
        sys.modules["celery_app"] = celery_module
        spec.loader.exec_module(celery_module)
        
        celery_app = celery_module.celery_app
        
        # Import workers to register tasks
        workers_dir = SERVER_DIR / "workers"
        worker_files = [
            "pipeline_tasks.py",
            "risk_alert_tasks.py",
        ]
        
        for worker_file in worker_files:
            worker_path = workers_dir / worker_file
            if worker_path.exists():
                try:
                    spec = importlib.util.spec_from_file_location(
                        worker_file.replace(".py", ""), worker_path
                    )
                    worker_module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(worker_module)
                except Exception as e:
                    print(f"⚠️  Could not import {worker_file}: {e}")
        
        # Check for required tasks
        required_tasks = [
            "pipeline.start",
            "pipeline.news_sentiment.run",
            "pipeline.risk_monitor.run",
        ]
        
        registered_tasks = list(celery_app.tasks.keys())
        
        print(f"Total registered tasks: {len(registered_tasks)}")
        if registered_tasks:
            print(f"Sample tasks: {', '.join(list(registered_tasks)[:5])}")
        print("\nRequired Pipeline Tasks:")
        all_found = True
        for task_name in required_tasks:
            found = task_name in registered_tasks
            status = "✅" if found else "❌"
            print(f"  {status} {task_name}")
            if not found:
                all_found = False
        
        if all_found:
            print("\n✅ All required Celery tasks are registered")
        else:
            print("\n⚠️  Some required tasks are missing")
            print("   (Tasks may register when Celery worker starts)")
        
        return all_found
    except Exception as e:
        print(f"⚠️  Celery tasks check failed: {e}")
        print("   (This is okay if Celery dependencies aren't installed)")
        import traceback
        traceback.print_exc()
        return False


def check_output_directories() -> bool:
    """Check if output directories exist and are writable."""
    print("=" * 60)
    print("Checking Output Directories...")
    print("=" * 60)
    
    pipelines_dir = SERVER_DIR / "pipelines"
    news_dir = pipelines_dir / "news"
    nse_dir = pipelines_dir / "nse"
    
    directories = {
        "pipelines": pipelines_dir,
        "news": news_dir,
        "nse": nse_dir,
    }
    
    all_ok = True
    for name, path in directories.items():
        exists = path.exists()
        writable = path.exists() and os.access(path, os.W_OK)
        status = "✅" if (exists and writable) else "❌"
        print(f"{status} {name}/: {'exists & writable' if (exists and writable) else 'missing or not writable'}")
        if not (exists and writable):
            all_ok = False
    
    print()
    return all_ok


def main() -> int:
    """Run all dry run checks."""
    print("\n" + "=" * 60)
    print("PIPELINE DRY RUN - Component Validation")
    print("=" * 60 + "\n")
    
    results = {}
    
    # Run all checks
    results["env_vars"] = check_env_vars()
    results["kafka"] = check_kafka()
    results["database"] = check_database()
    results["redis"] = check_redis()
    results["pipeline_imports"] = check_pipeline_imports()
    results["pipeline_structure"] = check_pipeline_structure()
    results["celery_tasks"] = check_celery_tasks()
    results["output_dirs"] = check_output_directories()
    
    # Summary
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    
    all_passed = True
    
    # Environment variables
    env_ok = all(results["env_vars"].values())
    status = "✅" if env_ok else "⚠️ "
    print(f"{status} Environment Variables: {'All set' if env_ok else 'Some missing'}")
    if not env_ok:
        all_passed = False
    
    # Services
    services_ok = results["kafka"] and results["database"] and results["redis"]
    status = "✅" if services_ok else "⚠️ "
    print(f"{status} Services: {'All connected' if services_ok else 'Some unavailable'}")
    
    # Pipeline components
    imports_ok = all(results["pipeline_imports"].values())
    structure_ok = all(results["pipeline_structure"].values())
    status = "✅" if (imports_ok and structure_ok) else "❌"
    print(f"{status} Pipeline Components: {'All OK' if (imports_ok and structure_ok) else 'Issues found'}")
    if not (imports_ok and structure_ok):
        all_passed = False
    
    # Celery
    status = "✅" if results["celery_tasks"] else "❌"
    print(f"{status} Celery Tasks: {'All registered' if results['celery_tasks'] else 'Missing tasks'}")
    if not results["celery_tasks"]:
        all_passed = False
    
    # Output directories
    status = "✅" if results["output_dirs"] else "❌"
    print(f"{status} Output Directories: {'OK' if results['output_dirs'] else 'Issues'}")
    if not results["output_dirs"]:
        all_passed = False
    
    print("\n" + "=" * 60)
    if all_passed:
        print("✅ DRY RUN PASSED - All critical components validated")
        return 0
    else:
        print("⚠️  DRY RUN COMPLETED - Some issues found (see above)")
        print("   Note: Service connection failures are OK if services aren't running")
        return 1


if __name__ == "__main__":
    sys.exit(main())

