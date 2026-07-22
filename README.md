# Smart Automator

AI-powered browser automation tool using Playwright. Inspired by nanobrowser.

## Features

- Multi-agent system (Planner + Navigator) with nanobrowser-parity orchestration
- Groq and Ollama LLM support
- Rich terminal UI and web dashboard
- DOM analysis with hierarchical element tree and highlighting
- 20 actions including tab management and cache_content
- Message history with guardrails for prompt injection defense
- URL firewall support

## Setup

```bash
# Install dependencies
uv sync

# Install Playwright browser
uv run playwright install chromium

# Copy and configure .env
cp .env.example .env
# Edit .env with your API keys
```

## Usage

### CLI

```bash
uv run smart-automator
```

Or:

```bash
uv run python -m smart_automator.main
```

### Web UI

Start the API and Vite dev server together:

```bash
cd ui && npm install && npm run dev:all
```

Or run them separately:

```bash
# Terminal 1 — API on http://127.0.0.1:8400
uv run smart-automator-api

# Terminal 2 — UI on http://127.0.0.1:5173
cd ui && npm install && npm run dev
```

Open http://127.0.0.1:5173 to start runs, watch live steps, manage websites, and configure LLM settings.

For production, build the UI and let the API serve it:

```bash
cd ui && npm run build
uv run smart-automator-api
# Open http://127.0.0.1:8400
```

## Configuration (.env)

Active LLM provider and model are set in `.env`:

```env
LLM_PROVIDER=groq  # groq, google, ollama, or ollama-cloud
GROQ_API_KEY=gsk_...
GROQ_MODEL=llama-3.3-70b-versatile

# Google Gemini
GOOGLE_API_KEY=
GOOGLE_MODEL=gemini-2.5-flash

# Ollama (local)
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2

# Ollama Cloud
OLLAMA_CLOUD_BASE_URL=https://ollama.com
OLLAMA_CLOUD_MODEL=gemma4:31b-cloud
OLLAMA_CLOUD_API_KEY=

HEADLESS=false
MAX_STEPS=100
PLANNING_INTERVAL=3
MAX_ACTIONS_PER_STEP=10
MAX_FAILURES=3
MAX_INPUT_TOKENS=128000
```

Runtime data (websites, LLM provider catalog, pricing, screenshots) is stored in the project root:

- `websites.json`
- `llm_settings.json` — per-provider base URLs and saved model lists (not the active selection)
- `pricing.json`
- `data/screenshots/`

## Example Tasks

- "Go to Google and search for Python tutorials"
- "Find the weather in New York on weather.com"
- "Go to GitHub and find trending Python repositories"

## Tests

```bash
uv run python -m unittest discover -s tests
```
