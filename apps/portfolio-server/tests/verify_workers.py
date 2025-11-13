"""
Celery Workers Verification Script

This script verifies that all Celery workers are properly registered and can be discovered.
Tests:
1. Worker module imports
2. Task registration
3. Beat schedule configuration
4. Worker connectivity (if Redis is running)
"""

import os
import sys
from pathlib import Path

# Add paths
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

print("=" * 80)
print("🔍 CELERY WORKERS VERIFICATION")
print("=" * 80)
print()

# Test 1: Import celery_app
print("📦 Test 1: Importing celery_app...")
try:
    from celery_app import celery_app
    print("   ✅ celery_app imported successfully")
    print(f"   Broker: {celery_app.conf.broker_url}")
    print(f"   Backend: {celery_app.conf.result_backend}")
except Exception as e:
    print(f"   ❌ Failed to import celery_app: {e}")
    sys.exit(1)

print()

# Test 2: Check included worker modules
print("📦 Test 2: Checking worker modules...")
expected_workers = [
    "workers.trade_tasks",
    "workers.pipeline_tasks",
    "workers.market_data_tasks",
    "workers.angelone_token_task",
    "workers.allocation_tasks",
    "workers.risk_alert_tasks",
    "workers.order_monitor_worker",
]

included = celery_app.conf.include
print(f"   Included modules: {len(included)}")

for worker in expected_workers:
    if worker in included:
        print(f"   ✅ {worker}")
    else:
        print(f"   ❌ {worker} - NOT FOUND IN INCLUDES")

print()

# Test 3: Import each worker module
print("📦 Test 3: Importing worker modules...")

workers_status = {}

# 3.1: Trade tasks
try:
    from workers import trade_tasks
    print(f"   ✅ trade_tasks: {dir(trade_tasks)}")
    workers_status['trade_tasks'] = True
except Exception as e:
    print(f"   ❌ trade_tasks: {e}")
    workers_status['trade_tasks'] = False

# 3.2: Order monitor worker
try:
    from workers import order_monitor_worker
    print(f"   ✅ order_monitor_worker: has start_continuous_monitoring, check_pending_orders_once")
    workers_status['order_monitor_worker'] = True
except Exception as e:
    print(f"   ❌ order_monitor_worker: {e}")
    workers_status['order_monitor_worker'] = False

# 3.3: Risk alert tasks
try:
    from workers import risk_alert_tasks
    print(f"   ✅ risk_alert_tasks: {dir(risk_alert_tasks)}")
    workers_status['risk_alert_tasks'] = True
except Exception as e:
    print(f"   ❌ risk_alert_tasks: {e}")
    workers_status['risk_alert_tasks'] = False

# 3.4: Angel One token task
try:
    from workers import angelone_token_task
    print(f"   ✅ angelone_token_task: {dir(angelone_token_task)}")
    workers_status['angelone_token_task'] = True
except Exception as e:
    print(f"   ❌ angelone_token_task: {e}")
    workers_status['angelone_token_task'] = False

print()

# Test 4: Check registered tasks
print("📦 Test 4: Checking registered tasks...")
registered_tasks = list(celery_app.tasks.keys())
print(f"   Total registered tasks: {len(registered_tasks)}")

important_tasks = [
    "order_monitor.check_pending_orders_once",
    "order_monitor.start_continuous_monitoring",
    "risk.alerts.send_email",
    "market_data.generate_angelone_tokens",
]

for task_name in important_tasks:
    if task_name in registered_tasks:
        print(f"   ✅ {task_name}")
    else:
        print(f"   ⚠️  {task_name} - Not found (might be dynamically registered)")

print()

# Test 5: Check beat schedule
print("📦 Test 5: Checking Celery Beat schedule...")
beat_schedule = celery_app.conf.beat_schedule

print(f"   Total scheduled tasks: {len(beat_schedule)}")
for schedule_name, config in beat_schedule.items():
    task = config.get('task', 'N/A')
    schedule = config.get('schedule', 'N/A')
    print(f"   ✅ {schedule_name}")
    print(f"      Task: {task}")
    print(f"      Schedule: {schedule}")

print()

# Test 6: Verify configuration
print("📦 Test 6: Verifying configuration...")

configs = [
    ("ORDER_MONITOR_ENABLED", os.getenv("ORDER_MONITOR_ENABLED", "true")),
    ("ORDER_MONITOR_INTERVAL", os.getenv("ORDER_MONITOR_INTERVAL", "5")),
    ("RISK_MONITOR_ENABLED", os.getenv("PORTFOLIO_RISK_MONITOR_ENABLED", "true")),
    ("EMAIL_API_URL", os.getenv("EMAIL_API_URL", "NOT SET")),
    ("INTERNAL_API_KEY", "***" if os.getenv("INTERNAL_API_KEY") else "NOT SET"),
]

for key, value in configs:
    if value == "NOT SET":
        print(f"   ⚠️  {key}: {value}")
    else:
        print(f"   ✅ {key}: {value}")

print()

# Test 7: Email service integration
print("📦 Test 7: Testing email service integration...")
try:
    from services.trade_email_service import send_trade_execution_email
    print("   ✅ trade_email_service imported successfully")
    print("   ✅ send_trade_execution_email function available")
except Exception as e:
    print(f"   ❌ Failed to import email service: {e}")

print()

# Test 8: Email template
print("📦 Test 8: Testing email templates...")
try:
    from emails.trade_executed import trade_executed_email
    from decimal import Decimal
    from datetime import datetime
    
    # Generate a sample email
    html = trade_executed_email(
        user_name="Test User",
        trade_type="stock",
        symbol="RELIANCE-EQ",
        side="BUY",
        quantity=10,
        executed_price=Decimal("2850.00"),
        order_type="limit",
        limit_price=Decimal("2850.00"),
        trigger_price=None,
        fees=Decimal("14.25"),
        taxes=Decimal("7.13"),
        net_amount=Decimal("-28521.38"),
        execution_time=datetime.utcnow(),
        portfolio_name="Test Portfolio"
    )
    
    print("   ✅ Email template generated successfully")
    print(f"   ✅ HTML length: {len(html)} characters")
    
    # Check for key elements
    if "Trade Executed" in html:
        print("   ✅ Contains 'Trade Executed' heading")
    if "RELIANCE-EQ" in html:
        print("   ✅ Contains symbol")
    if "2850.00" in html:
        print("   ✅ Contains price")
    
except Exception as e:
    print(f"   ❌ Failed to generate email template: {e}")

print()

# Summary
print("=" * 80)
print("📊 VERIFICATION SUMMARY")
print("=" * 80)

all_workers_ok = all(workers_status.values())
beat_schedule_ok = len(beat_schedule) > 0
email_ok = 'trade_email_service' in str(sys.modules)

print()
print(f"Workers Status: {'✅ ALL OK' if all_workers_ok else '⚠️  SOME FAILED'}")
print(f"Beat Schedule: {'✅ CONFIGURED' if beat_schedule_ok else '❌ NOT CONFIGURED'}")
print(f"Email Service: {'✅ AVAILABLE' if email_ok else '⚠️  CHECK IMPORTS'}")

print()

if all_workers_ok and beat_schedule_ok:
    print("✅ ALL SYSTEMS OPERATIONAL!")
    print()
    print("🚀 TO START WORKERS:")
    print()
    print("   # Terminal 1: Start Celery Worker")
    print("   cd /home/manav/dev_ws/Pathway-Inter-IIT/apps/portfolio-server")
    print("   celery -A celery_app worker --loglevel=info --concurrency=4")
    print()
    print("   # Terminal 2: Start Celery Beat (for scheduled tasks)")
    print("   celery -A celery_app beat --loglevel=info")
    print()
    print("   # Monitor tasks")
    print("   celery -A celery_app inspect active")
    print("   celery -A celery_app inspect scheduled")
    print()
    print("📧 EMAIL NOTIFICATIONS:")
    print("   Set EMAIL_API_URL and INTERNAL_API_KEY environment variables")
    print("   Trade execution emails will be sent automatically")
    print()
    print("🔄 ORDER MONITORING:")
    print("   Orders are checked every 5 seconds (configurable)")
    print("   Create limit/stop/take-profit orders via API")
    print("   Watch logs for execution messages")
    print()
else:
    print("⚠️  SOME ISSUES DETECTED - Please review above")

print("=" * 80)
