#!/usr/bin/env python3
"""
Celery Worker Health Check Script for Kubernetes

This script checks if Celery workers are healthy by:
1. Connecting to the Celery app
2. Inspecting active workers
3. Checking worker stats

Exit codes:
- 0: Healthy
- 1: Unhealthy (no workers, connection issues, etc.)
"""

import os
import sys
from pathlib import Path

# Add portfolio-server to path
server_root = Path(__file__).resolve().parents[1]
if str(server_root) not in sys.path:
    sys.path.insert(0, str(server_root))

try:
    from celery_app import celery_app
    
    # Ping workers with a short timeout
    # This checks if the worker can respond to control commands
    inspector = celery_app.control.inspect(timeout=5.0)
    
    # Try to get active workers
    stats = inspector.stats()
    
    if stats is None or len(stats) == 0:
        # No workers responding
        print("ERROR: No Celery workers responding", file=sys.stderr)
        sys.exit(1)
    
    # Check if this worker is in the list
    # Get hostname for this pod
    hostname = os.getenv("HOSTNAME", "")
    
    # Worker is healthy if:
    # 1. We can communicate with Celery
    # 2. At least one worker is responding
    print(f"OK: {len(stats)} worker(s) responding")
    sys.exit(0)
    
except Exception as e:
    print(f"ERROR: Health check failed: {e}", file=sys.stderr)
    sys.exit(1)
