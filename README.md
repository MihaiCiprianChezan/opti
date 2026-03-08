![Opti](./Images/Opti.jpg)

# AgentOPTI v2

A voice-driven AI assistant with a visual interface. Speak to it, it speaks back — powered by swappable AI backends (local LLMs, Claude, OpenAI, CLI agents) and an animated Energy Star ball that reflects the agent's state through color and motion.

## What It Does

OPTI listens for speech via offline ASR (Vosk), routes it to the active AI backend, streams the response through text cleaning, and speaks it back via TTS — all while an animated ball visualizes what's happening (thinking, speaking, calling tools, idle). You can interrupt the agent mid-sentence by speaking over it.

## Architecture

```mermaid
graph TB
    subgraph Qt Main Thread
        Star["Energy Star<br/>(animated ball + color overlay)"]
        Bridge["UIBridge"]
    end

    subgraph Shell Thread
        Shell["AgentShell<br/>(orchestrator)"]
        Voice["VoiceIO<br/>ASR + TTS"]
        Adapter["Adapter<br/>(pluggable)"]
    end

    subgraph Backends
        Local["Local LLM"]
        Claude["Claude API"]
        OpenAI["OpenAI API"]
        CLI["Claude CLI"]
        Copilot["Copilot CLI"]
        Auggie["Auggie CLI"]
    end

    Voice -- "user_speech" --> Shell
    Shell -- "agent_response" --> Voice
    Shell <--> Adapter
    Adapter --- Local & Claude & OpenAI & CLI & Copilot & Auggie

    Shell -- "SynchronousEventBus" --> Bridge
    Bridge -- "Qt signals" --> Star
```

### Modules

| Directory | Purpose |
|-----------|---------|
| `src/core/` | Config, EventBus, AgentShell orchestrator |
| `src/adapter/` | AgentAdapter ABC + backends (local LLM, Claude API, OpenAI, Claude CLI, Copilot CLI, Auggie CLI) |
| `src/voice/` | VoiceIO — ASR (Vosk) + TTS (pyttsx3/pygame) with interruptible playback |
| `src/speech/` | ASRx worker and SpeechRecognizer |
| `src/energy/` | Energy Star ball UI — Qt widget, video player, color overlay, animations |
| `src/ui/` | UIBridge — event bus to Qt signal adapter |
| `src/llm/` | LlamaCppServer + inference manager for local models |
| `src/utils/` | AppLogger, TextCleaner, Folders, WorkerThread |
| `src/constants/` | Precompiled regex patterns |

## Adapters

Backends are pluggable via the `AgentAdapter` ABC. Each implements `send()` (streaming generator), `stop()` (interrupt), and `is_available()` (health check). Available adapters:

| Adapter | Backend | Requires |
|---------|---------|----------|
| `local_llm` | Local llama.cpp model | Model files on disk |
| `claude` | Claude API | `anthropic` package + API key |
| `openai` | OpenAI API | `openai` package + API key |
| `claude_cli` | Claude Code CLI | `claude` on PATH + `claude-agent-sdk` |
| `copilot_cli` | GitHub Copilot CLI | `copilot` on PATH + SDK |
| `auggie_cli` | Auggie CLI | `auggie` on PATH + SDK |

The active adapter can be switched at runtime via the event bus.

## Setup

### Prerequisites

- **Python 3.12** (exact major version required)
- **A microphone** for speech input
- **Windows** (tested on Windows 11 — uses SAPI5 for TTS voices)

### Installation

```bash
git clone https://github.com/your-org/opti.git
cd opti

python -m venv .venv
.venv\Scripts\activate

# Core dependencies
pip install -e .

# Optional: cloud API adapters
pip install -e ".[cloud]"
```

### Vosk ASR Model

Download the Vosk model and place it under `models/`:

```bash
mkdir models
# Download from https://alphacephei.com/vosk/models
# Extract so the path is: models/vosk-model-small-en-us-0.15/
```

### Backend Configuration

**Local LLM** — place a GGUF model in `models/` and adjust `InferenceConfig.model_name` in `src/core/config.py`.

**Claude API** — set `ANTHROPIC_API_KEY` in your environment, or fill `CloudConfig.anthropic_api_key` in config.

**OpenAI API** — set `OPENAI_API_KEY` in your environment, or fill `CloudConfig.openai_api_key` in config.

**Claude CLI** — install [Claude Code](https://docs.anthropic.com/en/docs/claude-code) (`claude` on PATH) and `pip install claude-agent-sdk`.

Select the active adapter in `src/core/config.py`:

```python
active_adapter: str = "claude_cli"  # "local_llm", "claude", "openai", "claude_cli", "copilot_cli", "auggie_cli"
```

## Running

```bash
python src/main.py
```

## Key Design Decisions

- **Engine-per-utterance TTS** — fresh pyttsx3 engine per text to avoid the Windows SAPI5 hang bug
- **save_to_file + pygame** — TTS renders to file, pygame plays it back so the user can interrupt by speaking over the agent
- **SynchronousEventBus** — pure threaded pub/sub, callbacks execute in the publisher's thread
- **Qt aboutToQuit** — background threads stop before Qt destroys widgets, preventing crash-on-exit
- **TextCleaner pipeline** — markdown → HTML → text → emojis → whitespace (mistune + bs4)
- **Async task cancellation** — CLI adapters use `asyncio.Task.cancel()` across threads for clean interruption of SDK async generators (avoids anyio cancel scope errors)
