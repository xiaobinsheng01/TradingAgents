"""Model name validators for each provider."""

from .model_catalog import get_known_models

# Providers whose model names are user-defined (local servers, relays, hosted
# OpenAI-compatible endpoints serving many models), so any model string is
# accepted without warning.
_ANY_MODEL_PROVIDERS = (
    "ollama", "openrouter", "openai_compatible",
    "mistral", "kimi", "groq", "nvidia", "bedrock",
    # Ark production traffic often uses inference endpoint IDs (ep-...), not
    # the catalog aliases, so any model string is accepted.
    "doubao",
)

VALID_MODELS = {
    provider: models
    for provider, models in get_known_models().items()
    if provider not in _ANY_MODEL_PROVIDERS
}


def validate_model(provider: str, model: str) -> bool:
    """Check if model name is valid for the given provider.

    For ollama, openrouter, openai_compatible, doubao, and other
    user-specified-ID providers, any model is accepted.
    """
    provider_lower = provider.lower()

    if provider_lower in _ANY_MODEL_PROVIDERS:
        return True

    if provider_lower not in VALID_MODELS:
        return True

    return model in VALID_MODELS[provider_lower]
