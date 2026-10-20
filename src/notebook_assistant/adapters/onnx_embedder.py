"""Embeddings on the CPU with ONNX Runtime (docs/architecture.md §4.3): an int8 model downloaded
once from Hugging Face into this PC's cache folder, never into the vault.

``onnxruntime``, ``tokenizers`` and ``huggingface-hub`` are the optional ``embeddings`` extra, so
they're imported only when a model is used; without them :class:`EmbedderError` says how to
install them.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from notebook_assistant.ports.embedder import EmbedderError

BATCH = 16  # passages per model call: small enough for a laptop's memory


@dataclass(frozen=True)
class ModelSpec:
    repo: str
    file: str  # the ONNX file in the repo
    query_prefix: str  # e5 is trained with these prefixes; bge-m3 uses none
    passage_prefix: str
    pooling: str  # "mean" over tokens, or "cls" (the first token)
    max_tokens: int


MODELS: dict[str, ModelSpec] = {
    "e5-small": ModelSpec(
        "Xenova/multilingual-e5-small", "onnx/model_int8.onnx", "query: ", "passage: ", "mean", 512
    ),
    "bge-m3": ModelSpec("Xenova/bge-m3", "onnx/model_int8.onnx", "", "", "cls", 512),
}


class OnnxEmbedder:
    def __init__(self, model: str, cache: Path) -> None:
        if model not in MODELS:
            raise EmbedderError(f"unknown embedding model {model!r}; one of {', '.join(MODELS)}")
        self._key = model
        self._spec = MODELS[model]
        self._cache = cache
        self._loaded: tuple[Any, Any] | None = None  # (session, tokenizer), loaded on first use

    @property
    def name(self) -> str:
        return self._key

    def _load(self) -> tuple[Any, Any]:
        if self._loaded is not None:
            return self._loaded
        try:
            import onnxruntime
            from huggingface_hub import hf_hub_download
            from tokenizers import Tokenizer
        except ImportError as exc:
            raise EmbedderError(
                "embeddings need the optional extra: pip install 'notebook-assistant[embeddings]'"
            ) from exc
        spec = self._spec
        try:
            model_file = hf_hub_download(spec.repo, spec.file, cache_dir=self._cache)
            tokenizer_file = hf_hub_download(spec.repo, "tokenizer.json", cache_dir=self._cache)
        except Exception as exc:  # network, disk, or a moved file: all mean "not available"
            raise EmbedderError(f"can't download {spec.repo}: {exc}") from exc
        tokenizer = Tokenizer.from_file(tokenizer_file)
        tokenizer.enable_truncation(spec.max_tokens)
        tokenizer.enable_padding()
        options = onnxruntime.SessionOptions()
        session = onnxruntime.InferenceSession(
            model_file, options, providers=["CPUExecutionProvider"]
        )
        self._loaded = (session, tokenizer)
        return self._loaded

    def embed(self, texts: Sequence[str], *, query: bool) -> list[list[float]]:
        import numpy as np

        session, tokenizer = self._load()
        prefix = self._spec.query_prefix if query else self._spec.passage_prefix
        names = {i.name for i in session.get_inputs()}
        out: list[list[float]] = []
        for start in range(0, len(texts), BATCH):
            encoded = tokenizer.encode_batch([prefix + t for t in texts[start : start + BATCH]])
            ids = np.array([e.ids for e in encoded], dtype=np.int64)
            mask = np.array([e.attention_mask for e in encoded], dtype=np.int64)
            feed = {"input_ids": ids, "attention_mask": mask}
            if "token_type_ids" in names:
                feed["token_type_ids"] = np.zeros_like(ids)
            hidden = session.run(None, feed)[0]
            if self._spec.pooling == "cls":
                pooled = hidden[:, 0]
            else:
                weights = mask[..., None].astype(np.float32)
                pooled = (hidden * weights).sum(axis=1) / np.clip(weights.sum(axis=1), 1e-9, None)
            norms = np.linalg.norm(pooled, axis=1, keepdims=True)
            out += (pooled / np.clip(norms, 1e-12, None)).astype(float).tolist()
        return out
