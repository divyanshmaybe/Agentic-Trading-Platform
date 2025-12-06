#!/bin/bash

################################################################################
# Fresh Start Cleanup Script
# 
# This script removes all generated data, cache files, pipeline outputs, and
# runtime artifacts to prepare the system for a fresh deployment.
#
# Usage:
#   ./cleanup-fresh-start.sh [--dry-run]
#
# Options:
#   --dry-run    Show what would be deleted without actually deleting
################################################################################

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

DRY_RUN=false
if [[ "$1" == "--dry-run" ]]; then
    DRY_RUN=true
    echo -e "${YELLOW}🔍 DRY RUN MODE - No files will be deleted${NC}\n"
fi

# Counter for deleted items
DELETED_COUNT=0

################################################################################
# Helper Functions
################################################################################

delete_file() {
    local file="$1"
    if [ -f "$file" ]; then
        if [ "$DRY_RUN" = true ]; then
            echo -e "${YELLOW}Would delete file:${NC} $file"
        else
            rm -f "$file"
            echo -e "${GREEN}✓ Deleted file:${NC} $file"
        fi
        DELETED_COUNT=$((DELETED_COUNT + 1))
    fi
}

delete_directory() {
    local dir="$1"
    if [ -d "$dir" ]; then
        if [ "$DRY_RUN" = true ]; then
            echo -e "${YELLOW}Would delete directory:${NC} $dir"
        else
            rm -rf "$dir"
            echo -e "${GREEN}✓ Deleted directory:${NC} $dir"
        fi
        DELETED_COUNT=$((DELETED_COUNT + 1))
    fi
}

delete_pattern() {
    local pattern="$1"
    local description="$2"
    local found_count=0
    
    if [ "$DRY_RUN" = true ]; then
        echo -e "${YELLOW}Would delete $description:${NC}"
        while IFS= read -r file; do
            echo "  - $file"
            found_count=$((found_count + 1))
        done < <(find . -path "$pattern" -type f 2>/dev/null)
        DELETED_COUNT=$((DELETED_COUNT + found_count))
    else
        while IFS= read -r file; do
            rm -f "$file"
            found_count=$((found_count + 1))
        done < <(find . -path "$pattern" -type f 2>/dev/null)
        if [ $found_count -gt 0 ]; then
            echo -e "${GREEN}✓ Deleted $found_count $description${NC}"
            DELETED_COUNT=$((DELETED_COUNT + found_count))
        fi
    fi
}

################################################################################
# Main Cleanup
################################################################################

echo -e "${BLUE}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║         Starting Fresh Start Cleanup                          ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════════╝${NC}\n"

# =============================================================================
# 1. Portfolio Server - Pipeline Outputs
# =============================================================================
echo -e "${BLUE}[1/9] Cleaning Portfolio Server Pipeline Outputs...${NC}"

# NSE Pipeline outputs
delete_file "apps/portfolio-server/pipelines/nse/trading_signals.jsonl"
delete_file "apps/portfolio-server/pipelines/nse/processed_announcements.json"

# News Pipeline outputs
delete_file "apps/portfolio-server/pipelines/news/stock_recommendations.json"
delete_file "apps/portfolio-server/pipelines/news/sector_analysis.json"
delete_file "apps/portfolio-server/pipelines/news/sentiment_articles.jsonl"
delete_file "apps/portfolio-server/pipelines/news/news_pipeline_summary.json"

# Pipeline status files
delete_file "apps/portfolio-server/pipeline_status.json"
delete_file "apps/portfolio-server/news_pipeline_status.json"

echo ""

# =============================================================================
# 2. Portfolio Server - Data Directory
# =============================================================================
echo -e "${BLUE}[2/9] Cleaning Portfolio Server Data Directory...${NC}"

# Economic indicators
delete_directory "apps/portfolio-server/data/economic_indicators"

# Financial statements
delete_directory "apps/portfolio-server/data/financial_statements"

# Market data cache
delete_directory "apps/portfolio-server/data/market_data"

# Pipeline runtime data
delete_directory "apps/portfolio-server/data/pipeline"

# Fundamental metrics (generated file)
delete_file "apps/portfolio-server/data/fundamental_metrics_nifty500.csv"

echo ""

# =============================================================================
# 3. AlphaCopilot Server - MLflow Runs
# =============================================================================
echo -e "${BLUE}[3/9] Cleaning AlphaCopilot MLflow Data...${NC}"

delete_directory "apps/alphacopilot-server/mlruns"
delete_file "apps/alphacopilot-server/mlruns.db"

echo ""

# =============================================================================
# 4. Python Cache Files
# =============================================================================
echo -e "${BLUE}[4/9] Cleaning Python Cache Files...${NC}"

delete_pattern "*/__pycache__" "Python __pycache__ directories"
delete_pattern "*/.pytest_cache" "Pytest cache directories"
delete_pattern "*.pyc" "Python bytecode files"
delete_pattern "*.pyo" "Python optimized bytecode files"

echo ""

# =============================================================================
# 5. Node.js Cache Files
# =============================================================================
echo -e "${BLUE}[5/9] Cleaning Node.js Cache Files...${NC}"

delete_directory "apps/auth_server/.turbo"
delete_directory "apps/frontend/.turbo"
delete_directory "apps/notification_server/.turbo"
delete_directory "apps/portfolio-server/.turbo"
delete_directory ".turbo"

echo ""

# =============================================================================
# 6. Docker Volumes Data (if running locally)
# =============================================================================
echo -e "${BLUE}[6/9] Cleaning Local Docker Persistent Data...${NC}"

if [ "$DRY_RUN" = true ]; then
    echo -e "${YELLOW}Would clean Docker volumes (run manually):${NC}"
    echo "  docker-compose down -v"
else
    echo -e "${YELLOW}⚠ Skipping Docker volumes cleanup${NC}"
    echo "  Run manually: ${GREEN}docker-compose down -v${NC}"
fi

echo ""

# =============================================================================
# 7. Log Files
# =============================================================================
echo -e "${BLUE}[7/9] Cleaning Log Files...${NC}"

delete_pattern "*/logs/*.log" "application log files"
delete_pattern "*/*.log" "root log files"

echo ""

# =============================================================================
# 8. Temporary Files
# =============================================================================
echo -e "${BLUE}[8/9] Cleaning Temporary Files...${NC}"

delete_pattern "*/.env.local" ".env.local files"
delete_pattern "*/tmp/*" "temporary files"
delete_pattern "*/*.tmp" "temp files"
delete_pattern "*/temp_pdfs/*" "temporary PDF files"

# Clean scripts temp PDFs
delete_directory "scripts/temp_pdfs"

echo ""

# =============================================================================
# 9. Build Artifacts (Optional - commented out by default)
# =============================================================================
echo -e "${BLUE}[9/9] Cleaning Build Artifacts (Optional)...${NC}"

# Uncomment these if you want to clean build artifacts too
# delete_directory "apps/frontend/.next"
# delete_directory "apps/frontend/out"
# delete_directory "apps/auth_server/dist"
# delete_directory "apps/notification_server/dist"

echo -e "${YELLOW}⚠ Build artifacts (.next, dist) kept - uncomment in script to remove${NC}"

echo ""

# =============================================================================
# Summary
# =============================================================================
echo -e "${BLUE}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║         Cleanup Summary                                        ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════════╝${NC}\n"

if [ "$DRY_RUN" = true ]; then
    echo -e "${YELLOW}📊 Dry run completed${NC}"
    echo -e "   Would delete approximately ${DELETED_COUNT} items"
    echo -e "\n${GREEN}💡 Run without --dry-run to actually delete files${NC}"
else
    echo -e "${GREEN}✅ Cleanup completed successfully!${NC}"
    echo -e "   Deleted ${DELETED_COUNT} items"
fi

echo ""
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}Next Steps for Fresh Start:${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo ""
echo "1. Clean Docker volumes (if needed):"
echo -e "   ${GREEN}docker-compose down -v${NC}"
echo ""
echo "2. Reset databases:"
echo -e "   ${GREEN}docker-compose up -d postgres portfolio_postgres${NC}"
echo -e "   ${GREEN}# Wait for databases to be ready${NC}"
echo ""
echo "3. Run Prisma migrations:"
echo -e "   ${GREEN}cd apps/auth_server && pnpm prisma db push${NC}"
echo -e "   ${GREEN}cd apps/portfolio-server && python -m prisma db push${NC}"
echo ""
echo "4. Start all services:"
echo -e "   ${GREEN}docker-compose up -d${NC}"
echo ""
echo "5. (Optional) For Kubernetes deployment:"
echo -e "   ${GREEN}./devops/kubernetes/create-secrets.sh${NC}"
echo -e "   ${GREEN}./devops/kubernetes/start.sh${NC}"
echo ""
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
