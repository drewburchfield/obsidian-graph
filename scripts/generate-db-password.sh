#!/usr/bin/env bash
#
# Generate secure random database password for Obsidian Graph MCP server
#
# This script:
# 1. Generates a cryptographically random 48-character password
# 2. Updates .env in the project root
# 3. Validates the password was set correctly
#
# Usage:
#   ./scripts/generate-db-password.sh [--force]
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$PROJECT_ROOT/.env"
ENV_EXAMPLE="$PROJECT_ROOT/.env.example"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Generate secure random password (48 chars: alphanumeric)
generate_password() {
    # Use /dev/urandom for cryptographic randomness
    head -c 64 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 48
}

echo "🔐 Obsidian Graph - Database Password Generator"
echo "=============================================="

# Check if password already exists
if [[ -f "$ENV_FILE" ]]; then
    CURRENT_PW=$(grep "^POSTGRES_PASSWORD=" "$ENV_FILE" 2>/dev/null | cut -d'=' -f2)
    if [[ -n "$CURRENT_PW" && "$CURRENT_PW" != "changeme" && "$CURRENT_PW" != "your_secure_password_here" ]]; then
        if [[ "${1:-}" != "--force" ]]; then
            echo -e "${YELLOW}⚠️  Password already exists in $ENV_FILE${NC}"
            echo "Use --force to regenerate (will require container restart)"
            exit 0
        fi
        echo -e "${YELLOW}⚠️  Regenerating password (--force flag detected)${NC}"
    fi
fi

# Generate new password
NEW_PASSWORD=$(generate_password)
echo -e "${GREEN}✓${NC} Generated 48-character password"

# Update or create .env
if [[ ! -f "$ENV_FILE" ]]; then
    # Create from example
    if [[ -f "$ENV_EXAMPLE" ]]; then
        cp "$ENV_EXAMPLE" "$ENV_FILE"
        echo -e "${GREEN}✓${NC} Created $ENV_FILE from .env.example"
    else
        echo -e "${RED}✗${NC} Error: $ENV_EXAMPLE not found"
        exit 1
    fi
fi

# Update password in env file (macOS and Linux compatible)
if [[ "$OSTYPE" == "darwin"* ]]; then
    sed -i '' "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$NEW_PASSWORD/" "$ENV_FILE"
else
    sed -i "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$NEW_PASSWORD/" "$ENV_FILE"
fi

echo -e "${GREEN}✓${NC} Updated $ENV_FILE"

# Verify password was set
echo ""
echo "🔍 Verifying configuration..."

if grep -q "^POSTGRES_PASSWORD=$NEW_PASSWORD" "$ENV_FILE"; then
    echo -e "${GREEN}✓${NC} .env contains new password"
else
    echo -e "${RED}✗${NC} .env not properly updated"
    exit 1
fi

echo ""
echo -e "${GREEN}✅ Password generation complete!${NC}"
echo ""
echo "Next steps:"
echo "  1. Restart containers:"
echo "     docker-compose down && docker-compose up -d"
echo "  2. Verify connection:"
echo "     docker logs obsidian-graph"
echo ""
echo -e "${YELLOW}⚠️  IMPORTANT: Never commit .env to version control!${NC}"
