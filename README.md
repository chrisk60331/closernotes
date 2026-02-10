# CloserNotes

Voice and AI-powered CRM built on [Backboard.io](https://backboard.io). Paste a meeting transcript or record audio directly in the browser — CloserNotes extracts customers, contacts, opportunities, action items, and follow-ups automatically, then keeps everything organized so you can focus on closing.

## What It Is

CloserNotes turns raw meeting notes into structured CRM data. Instead of manually updating a CRM after every call, you drop in a transcript (or hit record) and the system does the rest:

- **Transcript ingestion** — paste text or record audio; the app extracts entities, routes them to the right customer, and creates CRM records.
- **Multi-customer brain dumps** — a single rambling transcript that mentions several customers gets split and processed per-company automatically.
- **Customer & contact management** — companies and contacts are created on the fly from extracted entities; duplicates are normalized.
- **Opportunity tracking** — sales opportunities with stage, value, confidence, and competitor info are pulled from deal signals in your notes.
- **Action items & follow-ups** — important to-dos are promoted to standalone items with due dates; follow-up reminders are calculated and surfaced on the dashboard.
- **Teammate detection** — internal team members are filtered out of contact creation so only external stakeholders end up in your CRM.
- **Voice transcription** — local speech-to-text via [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (no audio leaves your machine).
- **Bulk CSV import** — seed opportunities from a spreadsheet.
- **Follow-up email generation** — optional AI-drafted follow-up emails via a Newsboard assistant.

The UI is a Flask + Tailwind CSS web app with dark mode, a command palette (Cmd+K), voice recording, and the full Glengarry Glen Ross theme — because coffee is for closers.

## How It Uses Backboard

Backboard.io is the **only** storage and LLM backend. There is no local database, no filesystem persistence — every piece of CRM data lives in Backboard as assistant memories.

### Hierarchical Assistant Architecture

| Assistant | Purpose |
|-----------|---------|
| **Orchestrator** | Routes transcripts, extracts entities, maintains a customer registry (company name → assistant ID). |
| **Per-Customer** | One assistant per company. Stores that company's customer record, contacts, opportunities, activities, meeting summaries, and action items as individual memories. |
| **Users** | Stores user accounts (email, password hash, role) for session-based authentication. |
| **Cache** | Holds denormalized customer summaries for fast dashboard loads. |
| **Newsboard** *(optional)* | Generates follow-up email drafts. |

### Storage Pattern

Each CRM entity (customer, contact, opportunity, activity, action item) is a Pydantic model serialized to JSON and stored as a **Backboard memory** on the appropriate assistant. Retrieval scans all memories on an assistant and parses them back into typed models.

### LLM Usage

Transcript processing, entity extraction, meeting summarization, and email generation all go through Backboard's `send_message` API, which routes to OpenAI (GPT-4o by default). The orchestrator uses LLM calls with `memory="off"` for stateless extraction, while customer assistants use `memory="Auto"` so context accumulates over time.

## How to Run

### Prerequisites

- Python 3.11+
- A [Backboard.io](https://backboard.io) API key
- A virtual environment (the startup script expects `.venv/`)

### 1. Clone and create a virtualenv

```bash
git clone <repo-url> closernotes
cd closernotes
python -m venv .venv
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and set at minimum:

```
BACKBOARD_API_KEY=your_backboard_api_key_here
```

Assistant IDs are **optional** — if omitted, CloserNotes auto-creates a shared assistant on first startup. See `.env.example` for the full list of options (LLM provider, Whisper model size, Flask secret key, etc.).

### 3. Start

```bash
./start.sh
```

This script:
1. Activates the virtualenv and installs `uv`
2. Syncs dependencies from `pyproject.toml`
3. Validates that `.env` and `BACKBOARD_API_KEY` exist
4. Downloads the Whisper speech model if not already cached
5. Downloads the Tailwind CSS standalone CLI and builds styles
6. Starts Flask on **http://localhost:5002** with hot-reload

### Docker

```bash
docker build -t closernotes .
docker run -p 5000:5000 -e BACKBOARD_API_KEY=... closernotes
```

Production runs via Gunicorn on port 5000 (configurable with `PORT`).

### Infrastructure

Terraform configs in `terraform/` deploy to AWS App Runner with ECR for container images. Environment-specific variable files live in `terraform/envs/`.

## Tech Stack

| Layer | Tech |
|-------|------|
| Backend | Flask 3, Python 3.11+, Pydantic 2 |
| Storage & LLM | Backboard.io (`backboard-sdk`) |
| Transcription | faster-whisper (local, CPU) |
| Frontend | Tailwind CSS 3.4, vanilla JS, Jinja2 |
| Production | Gunicorn, Docker, AWS App Runner |
| Dev tools | uv, ruff, pytest |
