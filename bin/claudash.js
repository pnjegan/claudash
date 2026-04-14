#!/usr/bin/env node

const { execSync, spawn } = require('child_process');
const path = require('path');
const fs = require('fs');
const os = require('os');

const { version: VERSION } = require('../package.json');
const REPO = 'https://github.com/pnjegan/claudash';
const INSTALL_DIR = path.join(os.homedir(), '.claudash');

// Parse args FIRST — before any other code runs.
// This prevents macOS `open` from ever receiving --help and misinterpreting it.
const args = process.argv.slice(2);

if (args.includes('--help') || args.includes('-h')) {
  console.log('Claudash v' + VERSION + ' — Claude Code usage intelligence');
  console.log('');
  console.log('Usage: claudash [--port <n>]');
  console.log('');
  console.log('  --port <n>    Port to serve on (default: 8080)');
  console.log('  --no-browser  Skip auto-opening browser');
  console.log('  --help, -h    Show this help');
  console.log('');
  console.log('GitHub: https://github.com/pnjegan/claudash');
  console.log('npm:    npm install -g @jeganwrites/claudash');
  process.exit(0);
}

if (args.includes('--version') || args.includes('-v')) {
  console.log(VERSION);
  process.exit(0);
}

function checkPython() {
  try {
    const ver = execSync('python3 --version 2>&1').toString().trim();
    const match = ver.match(/(\d+)\.(\d+)/);
    if (match && parseInt(match[1]) >= 3 && parseInt(match[2]) >= 8) {
      return true;
    }
    console.error('Python 3.8+ required. Found: ' + ver);
    process.exit(1);
  } catch (e) {
    console.error('Python 3 not found. Install from https://python.org');
    process.exit(1);
  }
}

function checkClaudeData() {
  const candidates = [
    path.join(os.homedir(), '.claude', 'projects'),
    path.join(os.homedir(), 'AppData', 'Roaming', 'Claude', 'projects'),
    path.join(os.homedir(), 'Library', 'Application Support', 'Claude', 'projects'),
  ];
  const found = candidates.filter(p => fs.existsSync(p));
  if (found.length === 0) {
    console.log('Warning: No Claude Code data found.');
    console.log('   Run at least one Claude Code session first.');
    console.log('   Looked in:');
    candidates.forEach(c => console.log('     ' + c));
    console.log('   Starting dashboard anyway — it will show instructions.');
  } else {
    console.log('Found Claude Code data at: ' + found[0]);
  }
  return found;
}

function isPortInUse(port) {
  try {
    execSync(
      'lsof -ti:' + port + ' 2>/dev/null || ' +
      'netstat -an 2>/dev/null | grep ":' + port + ' " | grep LISTEN',
      { stdio: 'pipe' }
    );
    return true;
  } catch (e) {
    return false;
  }
}

function installClaudash() {
  if (fs.existsSync(path.join(INSTALL_DIR, 'cli.py'))) {
    try {
      execSync('git -C "' + INSTALL_DIR + '" pull --quiet 2>/dev/null');
      console.log('Claudash updated');
    } catch (e) {
      // offline or not a git repo — use what we have
    }
    return;
  }

  console.log('Installing Claudash to ' + INSTALL_DIR + '...');
  try {
    execSync('git clone --depth=1 --quiet "' + REPO + '" "' + INSTALL_DIR + '"');
    console.log('Claudash installed');
  } catch (e) {
    console.error('Failed to clone from GitHub: ' + e.message);
    console.error('Check your internet connection or visit: ' + REPO);
    process.exit(1);
  }
}

function openBrowser(port) {
  const url = 'http://localhost:' + port;
  const platform = process.platform;
  setTimeout(() => {
    try {
      if (platform === 'darwin') execSync('open "' + url + '"');
      else if (platform === 'win32') execSync('start "" "' + url + '"');
      else execSync('xdg-open "' + url + '" 2>/dev/null || true');
    } catch (e) { /* headless — no browser */ }
  }, 1500);
}

function main() {
  // Support both --port=N and --port N
  let port = '8080';
  const portEq = args.find(a => a.startsWith('--port='));
  if (portEq) {
    port = portEq.split('=')[1];
  } else {
    const portIdx = args.indexOf('--port');
    if (portIdx !== -1 && args[portIdx + 1]) {
      port = args[portIdx + 1];
    }
  }
  const noBrowser = args.includes('--no-browser');

  console.log('Claudash v' + VERSION);
  console.log('-'.repeat(40));

  checkPython();
  checkClaudeData();
  installClaudash();

  if (isPortInUse(port)) {
    console.log('Port ' + port + ' is already in use.');
    console.log('Try: claudash --port 8081');
    console.log('Or kill the process: lsof -ti:' + port + ' | xargs kill');
    process.exit(1);
  }

  console.log('Starting dashboard on http://localhost:' + port + ' ...');
  if (!noBrowser) {
    openBrowser(port);
  }

  const cliArgs = [path.join(INSTALL_DIR, 'cli.py'), 'dashboard', '--port', port, '--no-browser'];
  const proc = spawn('python3', cliArgs, {
    stdio: 'inherit',
    cwd: INSTALL_DIR,
  });

  proc.on('exit', code => process.exit(code || 0));
  process.on('SIGINT', () => { proc.kill(); process.exit(0); });
}

main();
