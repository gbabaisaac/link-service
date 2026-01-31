"""Minimal Gemini embedding adapter for LlamaIndex (no extra llama-index-gemini deps).

Uses google-generativeai's text-embedding-004.
"""
from __future__ import annotations

import os
from typing import List

import google.generativeai as genai
from llama_index.core.embeddings import BaseEmbedding


class GeminiEmbedder(BaseEmbedding):
    model_name: str = "text-embedding-004"
    api_key: str | None = None

    def model_post_init(self, __context) -> None:
        key = self.api_key or os.getenv("GOOGLE_API_KEY", "")
        if key:
            genai.configure(api_key=key)

    # LlamaIndex abstract methods (sync + async)
    def _get_query_embedding(self, query: str) -> List[float]:
        return self._embed_one(query)

    def _get_text_embedding(self, text: str) -> List[float]:
        return self._embed_one(text)

    def _get_text_embeddings(self, texts: List[str]) -> List[List[float]]:
        return [self._embed_one(t) for t in texts]

    async def _aget_query_embedding(self, query: str) -> List[float]:
        return self._embed_one(query)

    async def _aget_text_embedding(self, text: str) -> List[float]:
        return self._embed_one(text)

    def _embed_one(self, text: str) -> List[float]:
        try:
            r = genai.embed_content(model=self.model_name, content=text)
            # google-generativeai returns dict with key 'embedding'
            emb = r.get("embedding") if isinstance(r, dict) else getattr(r, "embedding", None)
            if emb:
                return emb
        except Exception:
            pass
        # Fallback to zero vector if embedding fails; dimension commonly 768 for text-embedding-004
        return [0.0] * 768
