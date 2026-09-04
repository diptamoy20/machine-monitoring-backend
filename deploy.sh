#!/bin/bash
# ==========================================
# Production deployment script
# Run this ON THE SERVER, from the project root:
#   cd /var/www/stage.beas.in/public_html/machine-monitoring-opencv
#   bash deploy.sh
# ==========================================

set -e

PROJECT_DIR="/var/www/stage.beas.in/public_html/machine-monitoring-opencv"
cd "$PROJECT_DIR"

echo "=== 1. Checking for local uncommitted changes ==="
if [[ -n $(git status --porcelain) ]]; then
    echo "WARNING: You have local uncommitted changes on the server:"
    git status --short
    echo ""
    echo "This script will NOT auto-resolve these."
    echo "Review manually: git diff   /   git status"
    echo "Then either commit, stash, or discard before re-running this script."
    exit 1
fi

echo "=== 2. Pulling latest code from git ==="
git pull origin master

echo "=== 3. Restarting API service (machine-monitoring.service) ==="
sudo systemctl restart machine-monitoring.service
sleep 3

echo "=== 4. Restarting live RTSP pipeline (main-live.service) ==="
sudo systemctl restart main-live.service
sleep 3

echo "=== 5. Checking service health ==="
API_STATUS=$(systemctl is-active machine-monitoring.service)
LIVE_STATUS=$(systemctl is-active main-live.service)

echo "API service:  $API_STATUS"
echo "Live service: $LIVE_STATUS"

if [[ "$API_STATUS" != "active" || "$LIVE_STATUS" != "active" ]]; then
    echo ""
    echo "ERROR: One or both services failed to start. Check logs:"
    echo "  sudo journalctl -u machine-monitoring.service -n 50 --no-pager"
    echo "  sudo journalctl -u main-live.service -n 50 --no-pager"
    exit 1
fi

echo "=== 6. Verifying API responds ==="
sleep 5
HEALTH=$(curl -s http://localhost:8000/health)
echo "Health check: $HEALTH"

if [[ "$HEALTH" != *"ok"* ]]; then
    echo "WARNING: API health check did not return expected response. Investigate manually."
    exit 1
fi

echo ""
echo "=== DEPLOYMENT COMPLETE ==="
echo "Both services running. API healthy."
echo ""
echo "NOTE: This script does NOT sync app/static/images or app/static/videos"
echo "(those are gitignored runtime data). If new evidence files were generated"
echo "locally and need to be on the server, sync them separately via scp."
