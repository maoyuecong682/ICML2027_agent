from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Config:
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-flash"
    suite_version: str = "v1.2"
    seed: int = 20261028
    sample_size: int = 3
    max_model_calls: int = 36
    max_output_tokens: int = 4096
    timeout_seconds: float = 90

    def public(self):
        return {**asdict(self), "thinking": "disabled", "provider": "DeepSeek"}
