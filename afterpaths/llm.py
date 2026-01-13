"""Multi-provider LLM abstraction for summarization."""

import os
from dataclasses import dataclass
from typing import Literal


@dataclass
class LLMResponse:
    """Response from LLM API with metadata."""

    content: str
    provider: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass
class LLMConfig:
    """Configuration for LLM provider."""

    provider: Literal["anthropic", "openai", "openai-compatible"]
    model: str
    api_key: str
    base_url: str | None = None
    max_tokens: int = 3000


def get_config() -> LLMConfig:
    """Load LLM configuration from environment variables."""
    provider = os.environ.get("AFTERPATHS_LLM_PROVIDER", "anthropic").lower()

    if provider == "anthropic":
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY not set.\n"
                "Set it in .env or environment: export ANTHROPIC_API_KEY='sk-ant-...'"
            )
        model = os.environ.get("AFTERPATHS_MODEL", "claude-sonnet-4-5-20250929")

    elif provider in ("openai", "openai-compatible"):
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise ValueError(
                "OPENAI_API_KEY not set.\n"
                "Set it in .env or environment: export OPENAI_API_KEY='sk-...'"
            )
        model = os.environ.get("AFTERPATHS_MODEL", "gpt-4o")

    else:
        raise ValueError(f"Unknown provider: {provider}. Use: anthropic, openai, openai-compatible")

    base_url = os.environ.get("OPENAI_API_BASE")
    max_tokens = int(os.environ.get("AFTERPATHS_MAX_TOKENS", "3000"))

    return LLMConfig(
        provider=provider,
        model=model,
        api_key=api_key,
        base_url=base_url,
        max_tokens=max_tokens,
    )


def generate(prompt: str, config: LLMConfig | None = None) -> LLMResponse:
    """Generate a response from the configured LLM.

    Args:
        prompt: The prompt to send
        config: Optional config (loads from env if not provided)

    Returns:
        LLMResponse with content and metadata
    """
    if config is None:
        config = get_config()

    if config.provider == "anthropic":
        return _generate_anthropic(prompt, config)
    elif config.provider in ("openai", "openai-compatible"):
        return _generate_openai(prompt, config)
    else:
        raise ValueError(f"Unknown provider: {config.provider}")


def _generate_anthropic(prompt: str, config: LLMConfig) -> LLMResponse:
    """Generate using Anthropic API."""
    try:
        import anthropic
    except ImportError:
        raise ImportError(
            "anthropic package not installed.\n"
            "Install with: pip install afterpaths[summarize]"
        )

    client = anthropic.Anthropic(api_key=config.api_key)

    response = client.messages.create(
        model=config.model,
        max_tokens=config.max_tokens,
        messages=[{"role": "user", "content": prompt}]
    )

    return LLMResponse(
        content=response.content[0].text,
        provider="anthropic",
        model=config.model,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )


def _generate_openai(prompt: str, config: LLMConfig) -> LLMResponse:
    """Generate using OpenAI or OpenAI-compatible API."""
    try:
        import openai
    except ImportError:
        raise ImportError(
            "openai package not installed.\n"
            "Install with: pip install openai"
        )

    client_kwargs = {"api_key": config.api_key}
    if config.base_url:
        client_kwargs["base_url"] = config.base_url

    client = openai.OpenAI(**client_kwargs)

    response = client.chat.completions.create(
        model=config.model,
        max_tokens=config.max_tokens,
        messages=[{"role": "user", "content": prompt}]
    )

    return LLMResponse(
        content=response.choices[0].message.content,
        provider=config.provider,
        model=config.model,
        input_tokens=response.usage.prompt_tokens if response.usage else None,
        output_tokens=response.usage.completion_tokens if response.usage else None,
    )


def get_provider_info() -> str:
    """Get a string describing the current LLM configuration."""
    try:
        config = get_config()
        return f"{config.provider}/{config.model}"
    except ValueError:
        return "not configured"
