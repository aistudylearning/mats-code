#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

# Color definitions for output styling
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}====================================================${NC}"
echo -e "${BLUE}    🚀 MATS Backtest Test Suite (All Tests)        ${NC}"
echo -e "${BLUE}====================================================${NC}"

# Ensure we are executing from the root directory where .venv exists
if [ ! -d ".venv" ]; then
    echo -e "${RED}❌ Error: Virtual environment (.venv) not found in the current directory.${NC}"
    echo -e "Please ensure you run this script from the project root."
    exit 1
fi

echo -e "⏳ Executing unit and integration tests via pytest..."
echo ""

# Execute pytest with verbose output
.venv/bin/pytest -v

echo ""
echo -e "${GREEN}✅ Test suite run complete! All tests passed successfully.${NC}"
echo -e "${BLUE}====================================================${NC}"
