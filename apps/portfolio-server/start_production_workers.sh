#!/bin/bash
#
# Production Worker Startup Script
# ==================================
# Starts all required workers for production trading system with minimal latency.
#
# Architecture:
# 1. NSE Pipeline Worker (1 worker, pipelines queue) - Polls NSE filings every minute
# 2. Trading Workers (4 workers, trading queue) - Executes trades with TP/SL orders
# 3. Celery Beat (1 process) - Schedules auto-sell, risk monitor, market close
# 4. Order Monitor (separate process) - Real-time order monitoring via Pathway streaming
#
# Usage:
#   ./start_production_workers.sh        # Start all workers
#   ./start_production_workers.sh stop   # Stop all workers
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Log directory
LOG_DIR="/tmp"
mkdir -p "$LOG_DIR"

# PID directory
PID_DIR="$SCRIPT_DIR/pids"
mkdir -p "$PID_DIR"

# Environment setup
export CELERY_WORKER_RUNNING=1
export PYTHONPATH="$SCRIPT_DIR:$SCRIPT_DIR/../..:$SCRIPT_DIR/../../shared/py"

# Function to stop all workers
stop_workers() {
    echo -e "${YELLOW}Stopping all workers...${NC}"
    
    # Kill celery workers
    if ps aux | grep -E "celery.*worker" | grep -v grep > /dev/null; then
        echo "Killing Celery workers..."
        pkill -9 -f "celery.*worker" || true
    fi
    
    # Kill celery beat
    if ps aux | grep -E "celery.*beat" | grep -v grep > /dev/null; then
        echo "Killing Celery beat..."
        pkill -9 -f "celery.*beat" || true
    fi
    
    # Kill order monitor
    if ps aux | grep -E "streaming_order_monitor" | grep -v grep > /dev/null; then
        echo "Killing order monitor..."
        pkill -9 -f "streaming_order_monitor" || true
    fi
    
    # Kill any orphaned Prisma query engines
    pkill -9 -f "prisma.*query-engine" 2>/dev/null || true
    
    # Clean PID files
    rm -f "$PID_DIR"/*.pid
    
    echo -e "${GREEN}✓ All workers stopped${NC}"
    sleep 2
}

# Function to check if process is running
is_running() {
    local pid_file=$1
    if [ -f "$pid_file" ]; then
        local pid=$(cat "$pid_file")
        if ps -p "$pid" > /dev/null 2>&1; then
            return 0
        fi
    fi
    return 1
}

# Function to start workers
start_workers() {
    echo -e "${GREEN}Starting production workers...${NC}\n"
    
    # Purge all queues to clear old stale tasks
    echo -e "${YELLOW}[0/5] Purging stale tasks from queues...${NC}"
    redis-cli -n 0 DEL pipelines trading orders risk allocations 2>/dev/null || true
    echo -e "  └─ ${GREEN}✓ Queues purged${NC}\n"
    
    # 1. Start NSE Pipeline Worker (1 worker on pipelines queue)
    echo -e "${YELLOW}[1/5] Starting NSE Pipeline Worker...${NC}"
    if is_running "$PID_DIR/nse_pipeline.pid"; then
        echo "  └─ Already running (PID: $(cat $PID_DIR/nse_pipeline.pid))"
    else
        nohup celery -A celery_app worker \
            -Q pipelines \
            --concurrency=1 \
            --loglevel=info \
            --logfile="$LOG_DIR/celery_nse_pipeline.log" \
            --pidfile="$PID_DIR/nse_pipeline.pid" \
            > /dev/null 2>&1 &
        sleep 3
        if [ -f "$PID_DIR/nse_pipeline.pid" ]; then
            echo -e "  └─ ${GREEN}✓ Started${NC} (PID: $(cat $PID_DIR/nse_pipeline.pid), Log: $LOG_DIR/celery_nse_pipeline.log)"
        else
            echo -e "  └─ ${GREEN}✓ Started${NC} (Log: $LOG_DIR/celery_nse_pipeline.log)"
        fi
    fi
    
    # 2. Start Trading Workers (4 workers on trading queue for low latency)
    echo -e "${YELLOW}[2/5] Starting Trading Workers (4 workers)...${NC}"
    if is_running "$PID_DIR/trading.pid"; then
        echo "  └─ Already running (PID: $(cat $PID_DIR/trading.pid))"
    else
        nohup celery -A celery_app worker \
            -Q trading \
            --concurrency=4 \
            --loglevel=info \
            --logfile="$LOG_DIR/celery_trading.log" \
            --pidfile="$PID_DIR/trading.pid" \
            > /dev/null 2>&1 &
        sleep 3
        if [ -f "$PID_DIR/trading.pid" ]; then
            echo -e "  └─ ${GREEN}✓ Started${NC} (PID: $(cat $PID_DIR/trading.pid), Log: $LOG_DIR/celery_trading.log)"
        else
            echo -e "  └─ ${GREEN}✓ Started${NC} (Log: $LOG_DIR/celery_trading.log)"
        fi
    fi
    
    # 3. Start Celery Beat (scheduler for auto-sell, risk monitor, etc.)
    echo -e "${YELLOW}[3/5] Starting Celery Beat (scheduler)...${NC}"
    if is_running "$PID_DIR/celery_beat.pid"; then
        echo "  └─ Already running (PID: $(cat $PID_DIR/celery_beat.pid))"
    else
        nohup celery -A celery_app beat \
            --loglevel=info \
            --logfile="$LOG_DIR/celery_beat.log" \
            --pidfile="$PID_DIR/celery_beat.pid" \
            > /dev/null 2>&1 &
        sleep 3
        if [ -f "$PID_DIR/celery_beat.pid" ]; then
            echo -e "  └─ ${GREEN}✓ Started${NC} (PID: $(cat $PID_DIR/celery_beat.pid), Log: $LOG_DIR/celery_beat.log)"
        else
            echo -e "  └─ ${GREEN}✓ Started${NC} (Log: $LOG_DIR/celery_beat.log)"
        fi
    fi
    
    # 4. Start Order Monitor (Pathway streaming, separate process)
    echo -e "${YELLOW}[4/5] Starting Order Monitor (Pathway streaming)...${NC}"
    if ps aux | grep -E "streaming_order_monitor" | grep -v grep > /dev/null; then
        echo "  └─ Already running"
    else
        nohup python3 -m workers.streaming_order_monitor \
            > "$LOG_DIR/order_monitor.log" 2>&1 &
        local monitor_pid=$!
        echo "$monitor_pid" > "$PID_DIR/order_monitor.pid"
        sleep 2
        echo -e "  └─ ${GREEN}✓ Started${NC} (PID: $monitor_pid, Log: $LOG_DIR/order_monitor.log)"
    fi
    
    # 5. Verify all workers are running
    echo -e "\n${YELLOW}[5/5] Verifying worker status...${NC}"
    
    local all_good=true
    
    if is_running "$PID_DIR/nse_pipeline.pid"; then
        echo -e "  ✓ NSE Pipeline Worker: ${GREEN}RUNNING${NC}"
    else
        echo -e "  ✗ NSE Pipeline Worker: ${RED}NOT RUNNING${NC}"
        all_good=false
    fi
    
    if is_running "$PID_DIR/trading.pid"; then
        echo -e "  ✓ Trading Workers: ${GREEN}RUNNING${NC}"
    else
        echo -e "  ✗ Trading Workers: ${RED}NOT RUNNING${NC}"
        all_good=false
    fi
    
    if is_running "$PID_DIR/celery_beat.pid"; then
        echo -e "  ✓ Celery Beat: ${GREEN}RUNNING${NC}"
    else
        echo -e "  ✗ Celery Beat: ${RED}NOT RUNNING${NC}"
        all_good=false
    fi
    
    if is_running "$PID_DIR/order_monitor.pid"; then
        echo -e "  ✓ Order Monitor: ${GREEN}RUNNING${NC}"
    else
        echo -e "  ✗ Order Monitor: ${RED}NOT RUNNING${NC}"
        all_good=false
    fi
    
    echo ""
    if [ "$all_good" = true ]; then
        echo -e "${GREEN}═══════════════════════════════════════════════════════${NC}"
        echo -e "${GREEN}  ✓ All workers started successfully!${NC}"
        echo -e "${GREEN}═══════════════════════════════════════════════════════${NC}"
        echo ""
        echo "Logs:"
        echo "  NSE Pipeline:  tail -f $LOG_DIR/celery_nse_pipeline.log"
        echo "  Trading:       tail -f $LOG_DIR/celery_trading.log"
        echo "  Beat:          tail -f $LOG_DIR/celery_beat.log"
        echo "  Order Monitor: tail -f $LOG_DIR/order_monitor.log"
        echo ""
        echo "To send test signal:"
        echo "  python3 pipelines/nse/push_fake_signal.py --symbol RELIANCE --signal 1 --confidence 0.9"
        echo ""
        echo "To stop all workers:"
        echo "  $0 stop"
    else
        echo -e "${RED}═══════════════════════════════════════════════════════${NC}"
        echo -e "${RED}  ✗ Some workers failed to start!${NC}"
        echo -e "${RED}═══════════════════════════════════════════════════════${NC}"
        echo "Check logs for errors"
        exit 1
    fi
}

# Main script
case "${1:-start}" in
    start)
        stop_workers
        start_workers
        ;;
    stop)
        stop_workers
        ;;
    restart)
        stop_workers
        start_workers
        ;;
    status)
        echo "Worker Status:"
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        if is_running "$PID_DIR/nse_pipeline.pid"; then
            echo -e "NSE Pipeline:  ${GREEN}RUNNING${NC} (PID: $(cat $PID_DIR/nse_pipeline.pid))"
        else
            echo -e "NSE Pipeline:  ${RED}STOPPED${NC}"
        fi
        if is_running "$PID_DIR/trading.pid"; then
            echo -e "Trading:       ${GREEN}RUNNING${NC} (PID: $(cat $PID_DIR/trading.pid))"
        else
            echo -e "Trading:       ${RED}STOPPED${NC}"
        fi
        if is_running "$PID_DIR/celery_beat.pid"; then
            echo -e "Celery Beat:   ${GREEN}RUNNING${NC} (PID: $(cat $PID_DIR/celery_beat.pid))"
        else
            echo -e "Celery Beat:   ${RED}STOPPED${NC}"
        fi
        if is_running "$PID_DIR/order_monitor.pid"; then
            echo -e "Order Monitor: ${GREEN}RUNNING${NC} (PID: $(cat $PID_DIR/order_monitor.pid))"
        else
            echo -e "Order Monitor: ${RED}STOPPED${NC}"
        fi
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status}"
        exit 1
        ;;
esac
