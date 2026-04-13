# Contributing to Claudash

## Reporting bugs

Open an issue with:
- Your OS and Python version
- Steps to reproduce
- Expected vs actual behavior

## Known limitations (v1.0)

- Browser tracking: macOS cookie sync only (oauth_sync.py works on all platforms)
- Single-user: no multi-user auth
- Performance: designed for <50K sessions

## Roadmap (v1.1)

- Linux browser tracking
- Performance caching layer
- MCP server (beta to stable)
- Interactive session drilldown

## Development setup

```bash
git clone https://github.com/pnjegan/claudash
cd claudash
python3 cli.py dashboard  # zero deps, just run it
```

## Code style

- Python 3.8+ stdlib only — no pip dependencies
- Type hints encouraged but not required
- Debug logs prefixed with `[module_name]`
