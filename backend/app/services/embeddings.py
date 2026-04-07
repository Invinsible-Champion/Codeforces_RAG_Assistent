"""
OpenAI embedding service with batching and normalization.
"""
import numpy as np
from openai import AsyncOpenAI
from app.config import get_settings

settings = get_settings()
client = AsyncOpenAI(api_key=settings.openai_api_key)


async def get_embedding(text: str) -> np.ndarray:
    """Get embedding for a single text. Returns normalized vector."""
    text = text.replace("\n", " ").strip()
    if not text:
        return np.zeros(settings.embedding_dim, dtype=np.float32)

    response = await client.embeddings.create(
        input=[text],
        model=settings.embedding_model,
    )
    vec = np.array(response.data[0].embedding, dtype=np.float32)
    # Normalize for cosine similarity via inner product
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec = vec / norm
    return vec


async def get_embeddings_batch(
    texts: list[str],
    batch_size: int = 50,
) -> list[np.ndarray]:
    """
    Get embeddings for a batch of texts.
    Splits into sub-batches to respect API limits.
    Returns list of normalized vectors.
    """
    all_embeddings = []

    for i in range(0, len(texts), batch_size):
        batch = [t.replace("\n", " ").strip() for t in texts[i:i + batch_size]]
        # Filter empty strings
        batch = [t if t else "empty" for t in batch]

        response = await client.embeddings.create(
            input=batch,
            model=settings.embedding_model,
        )

        for item in response.data:
            vec = np.array(item.embedding, dtype=np.float32)
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec = vec / norm
            all_embeddings.append(vec)

    return all_embeddings
