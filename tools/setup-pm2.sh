#!/bin/bash
# Sets up Claudash as a PM2 managed process
# PM2 auto-restarts on crash, survives VPS reboots

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "Setting up Claudash with PM2..."

# Install PM2 if not present
which pm2 >/dev/null 2>&1 || npm install -g pm2

# Create PM2 ecosystem file
cat > "$SCRIPT_DIR/ecosystem.config.js" << 'PMEOF'
module.exports = {
  apps: [{
    name: 'claudash',
    script: 'cli.py',
    interpreter: 'python3',
    args: 'dashboard --skip-init --no-browser',
    cwd: __dirname,
    watch: false,
    autorestart: true,
    max_restarts: 10,
    min_uptime: '10s',
    restart_delay: 5000,
    error_file: '/tmp/claudash-error.log',
    out_file: '/tmp/claudash-out.log',
    log_date_format: 'YYYY-MM-DD HH:mm:ss',
    env: {
      PORT: 8080
    }
  }]
}
PMEOF

# Start with PM2
cd "$SCRIPT_DIR"
pm2 start ecosystem.config.js
pm2 save
pm2 startup || true

echo ""
echo "Claudash is now managed by PM2."
echo "Commands:"
echo "  pm2 status         — see if running"
echo "  pm2 logs claudash  — see logs"
echo "  pm2 restart claudash — restart"
echo "  pm2 stop claudash  — stop"
echo ""
echo "Dashboard: http://localhost:8080"
echo "On VPS: ssh -L 8080:localhost:8080 your-server"
