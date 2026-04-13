module.exports = {
  apps: [{
    name: 'claudash',
    script: 'python3',
    args: 'cli.py dashboard --skip-init --no-browser',
    cwd: '/root/projects/jk-usage-dashboard',
    watch: false,
    autorestart: true,
    max_restarts: 10,
    min_uptime: '10s',
    restart_delay: 5000,
    error_file: '/tmp/claudash-error.log',
    out_file: '/tmp/claudash-out.log'
  }]
}
