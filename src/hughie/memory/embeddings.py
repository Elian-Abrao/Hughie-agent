from google import genai
from google.genai import types as genai_types

from hughie.config import get_settings

_client: genai.Client | None = None

EMBEDDING_MODEL = "gemini-embedding-001"
EMBEDDING_DIM = 768


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        settings = get_settings()
        _client = genai.Client(api_key=settings.google_api_key)
    return _client


def embed_query(text: str) -> list[float]:
    """Embed a query string (for search)."""
    if not text or not text.strip():
        return [0.0] * EMBEDDING_DIM
    client = _get_client()
    result = client.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=text,
        config=genai_types.EmbedContentConfig(
            task_type="RETRIEVAL_QUERY",
            output_dimensionality=EMBEDDING_DIM,
        ),
    )
    return result.embeddings[0].values


def embed_document(text: str) -> list[float]:
    """Embed a document string (for storage)."""
    if not text or not text.strip():
        return [0.0] * EMBEDDING_DIM
    client = _get_client()
    result = client.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=text,
        config=genai_types.EmbedContentConfig(
            task_type="RETRIEVAL_DOCUMENT",
            output_dimensionality=EMBEDDING_DIM,
        ),
    )
    return result.embeddings[0].values
