"""Configuration schema for the dashboard UI."""

from __future__ import annotations

from dashboard.config_definitions import BASE_CONFIG_SCHEMA, CONFIG_CATEGORIES


CONFIG_SCHEMA = {
    **BASE_CONFIG_SCHEMA,
    "assistant_model": {
        "type": "select",
        "label": "AI Model",
        "description": "The language model used for chat responses.",
        "options": [
            {"value": "gpt-3.5-turbo", "label": "GPT-3.5 Turbo"},
            {"value": "gpt-4", "label": "GPT-4"},
            {"value": "gpt-4-turbo", "label": "GPT-4 Turbo"},
            {"value": "gpt-4o", "label": "GPT-4o"},
            {"value": "gpt-4o-mini", "label": "GPT-4o Mini"},
            {"value": "claude-3-haiku", "label": "Claude 3 Haiku"},
            {"value": "claude-3-sonnet", "label": "Claude 3 Sonnet"},
            {"value": "claude-3-opus", "label": "Claude 3 Opus"},
        ],
        "default": "gpt-3.5-turbo",
    },
    "assistant_embedding_model": {
        "type": "select",
        "label": "Embedding Model",
        "description": "Model used for RAG embeddings and semantic search.",
        "options": [
            {"value": "text-embedding-3-small", "label": "text-embedding-3-small"},
            {"value": "text-embedding-3-large", "label": "text-embedding-3-large"},
            {"value": "text-embedding-ada-002", "label": "text-embedding-ada-002"},
        ],
        "default": "text-embedding-3-small",
    },
    "assistant_image_model": {
        "type": "select",
        "label": "Image Generation Model",
        "description": "Model used for image generation commands.",
        "options": [
            {"value": "dall-e-3", "label": "DALL-E 3"},
            {"value": "dall-e-2", "label": "DALL-E 2"},
            {"value": "stable-diffusion", "label": "Stable Diffusion"},
        ],
        "default": "dall-e-3",
    },
}


def get_config_categories() -> dict[str, list[str]]:
    """Group configuration keys by category for better organization."""
    return CONFIG_CATEGORIES


def get_all_config_keys() -> list[str]:
    """Get a list of all valid configuration keys."""
    return list(CONFIG_SCHEMA.keys())
