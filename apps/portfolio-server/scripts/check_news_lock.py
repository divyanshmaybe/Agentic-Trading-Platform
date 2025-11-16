#!/usr/bin/env python3
"""Check and optionally clear the News Sentiment pipeline lock"""
import sys
import os
from pathlib import Path

# Add paths
SCRIPT_DIR = Path(__file__).resolve().parent
SERVER_DIR = SCRIPT_DIR.parent  # apps/portfolio-server
PROJECT_ROOT = SERVER_DIR.parent.parent  # project root

sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "shared" / "py"))
sys.path.insert(0, str(SERVER_DIR))

os.chdir(SERVER_DIR)

from redis import Redis

# Get broker URL from environment or default
BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")

redis_client = Redis.from_url(BROKER_URL)
lock_key = "pipeline:news_sentiment:lock"
pid_key = "pipeline:news_sentiment:pid"
lock = redis_client.get(lock_key)
pid_value = redis_client.get(pid_key)

print(f"News Sentiment pipeline lock exists: {lock is not None}")
if lock:
    print(f"Lock value: {lock.decode()}")
    print(f"Lock TTL: {redis_client.ttl(lock_key)} seconds")
    
    if pid_value:
        try:
            pid = int(pid_value.decode())
            print(f"Stored PID: {pid}")
            
            # Check if process is running
            try:
                import psutil
                if psutil.pid_exists(pid):
                    process = psutil.Process(pid)
                    cmdline = ' '.join(process.cmdline()) if process.cmdline() else ''
                    print(f"✅ Process {pid} is running")
                    print(f"   Command: {cmdline[:100]}...")
                    
                    if 'pipeline' in cmdline.lower() or 'celery' in cmdline.lower():
                        print("   ⚠️  Pipeline process appears to be running")
                    else:
                        print("   ⚠️  Process exists but doesn't look like pipeline - might be stale lock")
                else:
                    print(f"❌ Process {pid} NOT found - STALE LOCK!")
            except ImportError:
                print("   (psutil not available, cannot check if process is running)")
            except Exception as e:
                print(f"   ⚠️  Error checking process: {e}")
        except (ValueError, AttributeError):
            print(f"   ⚠️  Invalid PID: {pid_value}")
    else:
        print("   ⚠️  No PID stored with lock - old format lock")
    
    # Ask if user wants to clear
    if len(sys.argv) > 1 and sys.argv[1] == "--clear":
        redis_client.delete(lock_key)
        if pid_value:
            redis_client.delete(pid_key)
        print("✅ Lock cleared!")
    else:
        print("💡 Run with --clear to remove the lock")
else:
    print("✅ No lock found - pipeline can start")

