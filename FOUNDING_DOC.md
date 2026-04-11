# Claudash — What This Is

## The problem (for someone who just saw Karpathy's tweet and is wondering why any of this matters)

Andrej Karpathy likes to say the thing that separates productive AI-assisted engineers from frustrated ones is *intuition about where the tokens go*. If you code with Claude every day, you are burning millions of tokens a week. Some of those tokens are doing real work. Some are being spent reloading the same `CLAUDE.md` seventeen times because your hook misfired. Some are being spent running Opus on a task Sonnet would have finished in a quarter of the cost.

You cannot feel the difference.

Anthropic gives you a subscription — $20/mo for Pro, $100/mo for Max — and tells you roughly what you're allowed to use inside a 5-hour rolling window. What they do *not* give you is:

- **"How much of my 5-hour window have I already burned, and will I hit the wall if I start this next agent run?"**
- **"Which of my six projects is eating my Opus budget?"**
- **"Is my prompt cache actually saving me money, or is it quietly thrashing?"**
- **"On a $100 subscription, how much would I be paying if I were on the pay-per-token API instead? Am I getting 2x my money? 50x?"**
- **"Is my context auto-compacting, or am I letting agentic loops rot until the quality degrades?"**

These are the questions that separate someone who *knows* their coding workflow from someone who *hopes* their coding workflow is working. This dashboard answers them with numbers.

## Why existing tools fall short

There's a handful of Claude usage trackers floating around — `ccusage`, Paweł Grzybek's `claude-usage`, a few personal scripts in GitHub gists. They all do the same core thing: read the JSONL files under `~/.claude/projects/` and add up the tokens. That's fine as far as it goes, and credit to them for existing. But they stop there.

- They show **cost**. They do not show **value** (no subscription ROI — no "you're getting 59x your $100").
- They show **totals**. They do not show **burn rate against the 5-hour window** — no "223 minutes until you hit the cap at current pace".
- They show **model usage**. They do not tell you **when you're using the wrong model** — no "Opus is overkill for this project, here's $3,019/mo you're leaving on the table".
- They show **tokens in**. They do not show **cache effectiveness** — no "you saved $35,011 last month because your cache hit rate is 100%".
- They are **per-file tools**. No persistence, no trends, no insights, no alerts, no UI, no cross-machine view.
- And critically: none of them track the **other half** of your Claude usage — the stuff happening in `claude.ai` browser tabs, which eats the same 5-hour window without showing up in any JSONL.

Anthropic's own Console works for paid API accounts but is blind to subscription plans. And nothing out there connects Claude Code usage to claude.ai browser usage to give you a unified "how close am I to the wall?" answer.

This dashboard exists in that gap.

## The unique ideas we baked in

### 1. Subscription-aware math (not just API cost)

Every other tool divides usage by API list price and tells you the dollar number. That's cost, not ROI. On a Max plan, the right question is: *"I pay Anthropic $100/mo. If I were on the per-token API, how much would I be paying?"* That ratio is your ROI. If it's 2x, the subscription is a mild win. If it's 57x — as it turned out to be in our data — the subscription is carrying you. You are getting an order of magnitude of value you didn't know about.

The math: for every session, we compute the API-equivalent cost using Anthropic's published per-million-token rates for each model (input, output, cache read, cache write). We sum that across 30 days. We divide by monthly subscription cost. That ratio goes on the dashboard in a single number, and it's the first thing you look at every morning.

### 2. Collector/server architecture

Claude Code JSONL files live on the machine where you do the work. A solo laptop setup would just read them in-place, but real workflows have a VPS doing agent runs, a laptop doing interactive work, maybe a desktop doing long agentic jobs. The right shape for this is **collector → server**: each machine runs a small collector that pushes deltas, and a central server aggregates them.

The current implementation has the server side fully built and the Mac browser collector (`tools/mac-sync.py`) running in production. The JSONL collector for remote machines is still `rsync` in a shell script — a real `pusher.py` is next on the list. But the design is right: the server has no credentials, no scraping logic, no platform assumptions. It just receives and aggregates. Collectors live close to the data and speak HTTP to the server.

### 3. Project-level attribution (not just model)

Your Claude usage isn't one homogeneous pool. It's six projects, and they each have very different cost profiles. One project might be an exploratory research loop that burns a million tokens a day. Another might be a bug-fix stream that runs 30 sessions at 2K tokens each. If you only see the model breakdown, you're looking at the wrong layer — you can't tell which *project* is worth what.

The dashboard walks the JSONL folder path (`/root/.claude/projects/tidify/...`) against a keyword map and attributes every session to a project. Then every metric — cost, cache hit rate, ROI, avg session depth, compaction rate, token velocity, week-over-week change — is computed per project. You find out that one of your six projects is 70% of your Opus bill and decide whether that's justified.

### 4. Intelligence layer (not just a ledger)

A ledger tells you what happened. An intelligence layer tells you what to *do* about it. The dashboard runs 11 insight rules after every scan:

- **MODEL_WASTE** — "Tidify uses Opus but your average response is 197 tokens — Sonnet saves $3,019/mo". Concrete number, concrete fix.
- **CACHE_SPIKE** — "Cache creation is 4x your 7-day average. Did a CLAUDE.md reload hook misfire?"
- **COMPACTION_GAP** — "3 sessions this week hit 80% context with no /compact. Context rot is eating your quality."
- **WINDOW_RISK** — "You'll hit the 5-hour wall in 52 minutes at current burn rate."
- **ROI_MILESTONE** — "Your Max plan just crossed 10x ROI this month. You're getting $1,000+ of API value on your $100 subscription."
- **BEST_WINDOW** — "Your quietest 5-hour block is 18:00–23:00 UTC. Start your autonomous run then."
- **HEAVY_DAY** — "Wednesdays are your Claude-heavy day — 1.8x the daily average. Plan accordingly."
- **COMBINED_WINDOW_RISK** — "Your Claude Code usage (17%) + your claude.ai browser usage (64%) = 81% of window used. Slow down."
- And three more (cost target, session expiry, pro messages low).

Each rule is deduped per project within a 12-hour window so your dashboard doesn't become a wall of repeats. Insights expire after 24 hours so yesterday's alerts don't clutter today's view. The result is a short list of *actionable* items every time you look.

### 5. Cross-platform tracking (Claude Code + browser)

If you use Claude Max, you use Claude in two places: the CLI (Claude Code writing files) and the web (claude.ai browser tabs for planning, research, thinking). Both eat the same 5-hour window. Neither tool surfaces the unified number.

This dashboard does, and it's harder than it sounds. Claude Code logs live in JSONL files — easy to read. Claude.ai usage lives behind an authenticated API that Anthropic doesn't officially expose. The solution is a collector that runs on your Mac, reads your Chrome/Vivaldi cookies out of the keychain (using the Chromium AES-GCM scheme), and calls the undocumented `claude.ai/api/organizations/{org_id}/usage` endpoint. It pushes the result to the VPS, which stores snapshots. Then the insights layer computes `combined_window_pct = code_pct + browser_pct` and fires a warning when it crosses 80%.

It's fragile — any Chromium format change will break it — but when it's working, it's the only view of your total Claude window burn that exists anywhere.

### 6. Cache ROI visibility

Anthropic's prompt caching is a massive economic lever: cache reads are ~10x cheaper than fresh input tokens. If your `CLAUDE.md` is 20KB and you read it 100 times a day, caching saves you real money. But do you know how much? You don't. Your CLI tells you tokens in, tokens out; it doesn't tell you "this month, caching saved you $35,011 vs. paying list price".

The dashboard computes cache savings as:
```
savings = sum(cache_read_tokens * (input_price - cache_read_price) / 1M)
```
across every session. It puts that number on the front page. It also computes cache *hit rate* (`cache_read / (cache_read + input)`), so you can tell when your cache is working (100% means every input is cached) and when it's thrashing (low hit rate, high cache_creation tokens — the "cache spike" insight fires on this).

### 7. Compaction efficiency metric

An agentic loop without compaction is a rotting agentic loop. Quality degrades, tokens balloon, you're paying to watch Claude re-read the same conversation history. The standard fix is `/compact`, but no one remembers to do it. The dashboard detects compactions *automatically*: when a session's input tokens drop by more than 30% between consecutive turns, that's a compaction event. We flag it, count it, and compute the average savings (usually ~70%).

We also detect the *absence* of compaction: sessions that hit 80% of the context window without any compaction detected. Those sessions are where quality is silently rotting. The `COMPACTION_GAP` insight surfaces them.

## How it works (no jargon, plain English)

Every time you use Claude Code, it writes a log file to your home directory — one JSON object per interaction. The dashboard's scanner walks that directory, reads new lines (tracking how far it got last time, so it doesn't re-read everything), parses each interaction, figures out which project and model it was, computes how much it would have cost at pay-per-token rates, and writes a row to a local SQLite database.

A second thread runs every 5 minutes and does the same scan again to pick up new activity. A third thread, on your Mac, reads your Chrome/Vivaldi cookies to get your claude.ai session key, calls the claude.ai usage API, and pushes the result to the same SQLite database on the VPS. A fourth thread runs insight rules over the database every scan — 11 rules that look for waste, risk, milestones, and patterns.

When you type `cli.py dashboard`, a small Python HTTP server starts and serves a single dark-themed HTML page that polls the API every 60 seconds. You see your current window burn, today's cost, per-project breakdown, active insights, a trend chart, and predicted window exhaust time. You SSH-tunnel to the VPS from your laptop and hit `http://localhost:8080`.

No Docker. No Kubernetes. No React. No dependencies. 5,000 lines of Python stdlib.

## What the numbers mean

**ROI (subscription multiplier)** — Your API-equivalent cost over 30 days, divided by what you paid Anthropic. A `59x` ROI on a $100 Max plan means you used $5,900 worth of API calls for $100. The Max plan is doing its job.

**Cache hit rate (%)** — Of all input tokens you sent, what percentage came from the prompt cache instead of being billed at fresh input rates. 100% is ideal. <50% means your prompt prefix is changing enough to thrash the cache.

**Cache ROI ($)** — The actual dollar savings caching bought you this month. Computed by counting cache-read tokens and multiplying by the price difference between fresh input and cache read for each model.

**Window burn (%)** — How much of your current 5-hour window you've consumed. Max plan is 1,000,000 tokens per window; Pro plan is message-based so this shows 0% (it's a known limitation).

**Burn rate (tok/min)** — Tokens per minute in the current window. The dashboard uses this to predict when you'll hit the wall.

**Minutes to limit** — Given current burn rate and remaining window quota, how many minutes until you exhaust. If this is <60, the `WINDOW_RISK` insight fires.

**Sessions today / avg session depth** — How many distinct sessions you've run today, and how many turns the average session contains. A sudden spike in depth usually means you're running an agentic loop without compacting.

**Compaction rate (%)** — Of your sessions this month, what fraction had at least one detected compaction. If this is low and your sessions are deep, you're probably rotting context.

**Model consistency (%)** — For each project, how consistently you're using one model vs. mixing. Low consistency (60% Opus, 40% Sonnet) often means model selection is accidental rather than intentional.

**Week-over-week change (%)** — Cost delta for each project compared to the previous 7 days. Good for spotting runaway experiments.

## Vision: what this becomes with a proper UI

The current HTML dashboards are hand-written vanilla JS — 704 lines for the main view, 713 for the accounts page. They work. They are not the long-term shape.

The next step is a Next.js frontend that consumes the existing API and adds:

- **Real authentication**: a shared admin token + optional OAuth for multi-user
- **Per-project deep-dive pages**: click a project, see every session, every model, every cost spike
- **Time-travel**: scrub a date range and see your usage at any point in the last 90 days
- **Alerts via webhook**: push `WINDOW_RISK` to Slack or Discord
- **Hosted version**: someone else runs the server, you point your `pusher.py` at it, you see your usage. Railway + Supabase is the obvious stack.
- **Team mode**: multiple developers pushing to the same instance, roll-up views, per-developer ROI attribution, cost allocation to projects

None of that requires rewriting the backend. The data model is already right. The API is already shaped for it. The missing piece is the security story (see `END_USER_REVIEW.md`) and a frontend that doesn't look like a 2012 HTML dashboard. Both are feasible in a week of focused work.

## Concepts explained from first principles

### What is a token?

A token is how Claude counts text. Roughly: 1 token = 3–4 characters of English, or about 0.75 of a word. "Hello, world" is 3 tokens. A page of dense code might be 400 tokens. A large `CLAUDE.md` file is 5,000–20,000 tokens. Anthropic charges per million tokens, and every request has three costs: input tokens (what you sent), output tokens (what Claude generated), and cache tokens (a cheaper rate for reused prefix). You don't need to count them — Claude counts them for you and logs the numbers in the JSONL files this dashboard reads.

### What is a 5-hour window?

Anthropic subscription plans (Max, Pro) don't give you unlimited tokens. They give you a rolling 5-hour bucket. For Max, that bucket holds roughly 1,000,000 tokens; for Pro, it's a message count instead. The bucket refills on a rolling basis — 5 hours after your peak usage, that peak ages out and your capacity comes back. The practical effect: if you burn through 800K tokens in the first 2 hours, the next 3 hours of that window are going to be tight. The dashboard tracks where you are in the current window, what your burn rate is, and when you're projected to hit the wall. It's the difference between "I'll start this autonomous 2-hour run now" and "I'll start it after dinner when my window has reset".

### What is prompt caching and why does it matter?

Every time you talk to Claude, you send a prompt. A prompt is usually mostly the same stuff — your system message, your `CLAUDE.md`, your conversation history — plus a small new bit at the end. Prompt caching is Anthropic's feature that notices the unchanging prefix, stores it server-side, and charges you ~10x less when you reuse it. If your `CLAUDE.md` is 10,000 tokens and you send 100 requests per day, without caching you're paying for 1,000,000 tokens just for that file, every day. With caching, you pay for 10,000 tokens once and then the cache-read rate for every subsequent request. The savings are enormous and almost invisible — which is why this dashboard surfaces the dollar amount explicitly. You want to see "caching saved me $35,000 this month" in black and white, because otherwise you'll never appreciate how much work it's doing.

### What is an agentic loop and why does it burn tokens differently?

An "agentic loop" is when Claude isn't answering one question but running a multi-turn process: "read this file, now edit it, now run the tests, now fix the failures, now repeat until green". Each turn sends the *entire* accumulated conversation history to Claude. Turn 1 might be 2K tokens. Turn 20 is 40K tokens just from the history. Turn 50 is hitting context limits. The burn rate grows non-linearly. Agentic loops are where the subscription ROI gets spicy — a Max plan can run agentic loops that would cost hundreds of dollars on pay-per-token. But they're also where context rot happens: quality starts to drop once the context is full of old, irrelevant turns. The dashboard surfaces this via the `avg_session_depth` metric and the compaction insights.

### What is compaction and why should you care?

Compaction is the process of taking a long conversation history and replacing it with a summary. Claude Code has a `/compact` command that does this automatically: "here's everything we did in the last 50 turns, summarized into 2K tokens". After compacting, the next turn uses the summary as context instead of the full history, so your token budget per turn drops back to something sensible. The compaction itself is cheap — it saves roughly 70% of the subsequent turns' token cost.

You should care because *most people forget to compact*. They let agentic loops run until the context window is 80% full and then wonder why Claude is getting confused. The dashboard detects compactions automatically (it notices when a session's input tokens suddenly drop by more than 30% between consecutive turns — that's a compaction event) and flags sessions that *should have* compacted but didn't. The `COMPACTION_GAP` insight is saying: "your context is rotting, please compact".

## Who this is for

- **Solo engineers on Claude Max** who want to see where their $100/mo is going and whether they're extracting 2x or 50x value from it
- **Small teams** paying for multiple subscription seats who want to understand collective usage patterns
- **Agentic loop runners** who care about window burn prediction before starting a 2-hour autonomous job
- **Prompt caching enthusiasts** who want to see the dollar savings number for their `CLAUDE.md` setup
- **Anyone running Claude Code on a VPS** for long jobs while also using claude.ai on their laptop — this is the only tool that combines the two views
- **People who like owning their own data** — everything runs locally, nothing goes to a third party, the database is a SQLite file you can back up with `cp`

## What this is not

- **Not** a billing tool for Anthropic API customers — if you're on pay-per-token API, use the Anthropic Console; this dashboard is for subscription-plan users
- **Not** a production monitoring tool — no Prometheus export, no alerting, no multi-tenant
- **Not** a team collaboration tool — no multi-user auth, no shared views, no RBAC (yet)
- **Not** a cross-platform browser tracker — the claude.ai collector is macOS-only because it relies on Chromium keychain decryption
- **Not** secure-by-default for public exposure — see `END_USER_REVIEW.md` for the full security posture; this is a "behind my firewall" tool right now
- **Not** a replacement for Anthropic's own observability — when Anthropic ships a real subscription usage dashboard, this tool's reason to exist narrows significantly
- **Not** a general-purpose LLM cost tracker — it speaks Claude JSONL and claude.ai only; no OpenAI, no Gemini, no Mistral

This is a **personal tool that does one thing well**: show you, in one dark-themed dashboard, exactly how much of your Claude capacity you've burned, how much value you're extracting from your subscription, and where the waste is. If that's the problem you have, this is the tool you want.
