"""
Centralized configuration for AgentOPTI v2.
"""
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class VoiceConfig:
    """Voice I/O settings."""
    tts_voice: str = "Microsoft Sonia (Natural) - English (United Kingdom)"
    tts_rate: int = 190
    tts_language: str = "en"
    asr_enabled: bool = True


@dataclass
class UIConfig:
    """Energy Star UI settings."""
    use_hardware_acceleration: bool = True
    initial_zoom: float = 1.0
    video_path: str | None = None  # None = use default


@dataclass
class InferenceConfig:
    """Local LLM inference settings."""
    model_name: str = "Qwen3-0.6B-abliterated-Q4_K_S"
    host: str = "127.0.0.1"
    port: int = 8080
    silent: bool = True


@dataclass
class CloudConfig:
    """Cloud API settings."""
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    default_claude_model: str = "claude-sonnet-4-20250514"
    default_openai_model: str = "gpt-4o"


@dataclass
class CLIConfig:
    """CLI agent adapter settings."""
    claude_cli_enabled: bool = True
    copilot_cli_enabled: bool = True
    auggie_cli_enabled: bool = True
    cli_cwd: str = ""  # shared working directory, empty = os.getcwd()


@dataclass
class Config:
    """Root configuration."""
    active_adapter: str = "auggie_cli" # "local_llm", "claude_cli", "auggie_cli" or "copilot_cli"
    voice: VoiceConfig = field(default_factory=VoiceConfig)
    ui: UIConfig = field(default_factory=UIConfig)
    inference: InferenceConfig = field(default_factory=InferenceConfig)
    cloud: CloudConfig = field(default_factory=CloudConfig)
    cli: CLIConfig = field(default_factory=CLIConfig)

    # Paths
    root: Path = field(default_factory=lambda: Path(__file__).parent.parent.parent)

    @property
    def models_dir(self) -> Path:
        return self.root / "models"

    @property
    def log_dir(self) -> Path:
        return self.root / "log"

    @property
    def temp_dir(self) -> Path:
        return self.root / "temp"
