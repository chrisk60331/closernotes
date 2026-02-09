#!/bin/bash
set -e

# CloserNotes startup script
# Clears local state and starts with current code

echo "=== CloserNotes Startup ==="
source .venv/bin/activate
python -m ensurepip
python -m pip install uv


# Activate and sync dependencies
echo "Syncing dependencies..."
source .venv/bin/activate
uv pip sync <(uv pip compile pyproject.toml)

# Check for required environment variables
if [ ! -f ".env" ]; then
    echo "ERROR: .env file not found. Copy .env.example and configure."
    exit 1
fi

source .env

if [ -z "$BACKBOARD_API_KEY" ]; then
    echo "ERROR: BACKBOARD_API_KEY not set in .env"
    exit 1
fi

# Assistant IDs are optional — the app auto-creates a shared assistant
# on Backboard if any of ORCHESTRATOR/USERS/CACHE_ASSISTANT_ID are missing.
if [ -z "$ORCHESTRATOR_ASSISTANT_ID" ] || [ -z "$USERS_ASSISTANT_ID" ] || [ -z "$CACHE_ASSISTANT_ID" ]; then
    echo "One or more assistant IDs not set — will auto-create on startup."
fi

# Download Whisper model if not cached
# Models are cached in ~/.cache/huggingface/hub/
WHISPER_MODEL="${WHISPER_MODEL:-base}"
echo "Checking Whisper model ($WHISPER_MODEL)..."
python -c "
from faster_whisper import WhisperModel
import sys
try:
    # This will download if not cached
    model = WhisperModel('$WHISPER_MODEL', device='cpu', compute_type='int8')
    print('Whisper model ready')
except Exception as e:
    print(f'Warning: Could not load Whisper model: {e}', file=sys.stderr)
    print('Transcription will attempt to load model on first use', file=sys.stderr)
"

# Build Tailwind CSS using standalone CLI (v3.4.x for compatibility)
if [ -f "tailwind.config.js" ]; then
    echo "Building Tailwind CSS..."
    TAILWIND_BIN="./.tailwindcss"
    TAILWIND_VERSION="v3.4.17"
    
    # Download standalone Tailwind CLI if not present
    if [ ! -f "$TAILWIND_BIN" ]; then
        echo "Downloading Tailwind CSS standalone CLI ($TAILWIND_VERSION)..."
        ARCH=$(uname -m)
        OS=$(uname -s | tr '[:upper:]' '[:lower:]')
        
        if [ "$OS" = "darwin" ]; then
            if [ "$ARCH" = "arm64" ]; then
                TAILWIND_URL="https://github.com/tailwindlabs/tailwindcss/releases/download/${TAILWIND_VERSION}/tailwindcss-macos-arm64"
            else
                TAILWIND_URL="https://github.com/tailwindlabs/tailwindcss/releases/download/${TAILWIND_VERSION}/tailwindcss-macos-x64"
            fi
        else
            if [ "$ARCH" = "aarch64" ] || [ "$ARCH" = "arm64" ]; then
                TAILWIND_URL="https://github.com/tailwindlabs/tailwindcss/releases/download/${TAILWIND_VERSION}/tailwindcss-linux-arm64"
            else
                TAILWIND_URL="https://github.com/tailwindlabs/tailwindcss/releases/download/${TAILWIND_VERSION}/tailwindcss-linux-x64"
            fi
        fi
        
        curl -sLO "$TAILWIND_URL"
        mv "$(basename $TAILWIND_URL)" "$TAILWIND_BIN"
        chmod +x "$TAILWIND_BIN"
    fi
    
    "$TAILWIND_BIN" -i ./app/static/css/input.css -o ./app/static/css/output.css --minify
fi

# Start Flask development server
echo "Starting CloserNotes..."
export FLASK_APP=app.main:create_app
export FLASK_ENV=development

python -m flask run --host=0.0.0.0 --port=5002 --reload
