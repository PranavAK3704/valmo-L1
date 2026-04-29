"""
SOPStore — ChromaDB-backed knowledge base for SOPs and KT.

Loads all .md files from data/sop_knowledge/.
On each ticket, retrieves the top-k most relevant chunks.

To update KT: just edit or add .md files in data/sop_knowledge/
and call sop_store.reload(). No restart needed.
"""

import os
import logging
from pathlib import Path
from typing import List

import chromadb
from chromadb.utils import embedding_functions

logger = logging.getLogger(__name__)

KNOWLEDGE_DIR = Path(__file__).parent.parent.parent / "data" / "sop_knowledge"
CHROMA_DIR    = Path(__file__).parent.parent.parent / "data" / "chroma_db"
COLLECTION    = "valmo_sop_kt"
CHUNK_SIZE    = 600   # characters per chunk
CHUNK_OVERLAP = 100


def _chunk_text(text: str, source: str) -> List[dict]:
    """Split text into overlapping chunks with metadata."""
    chunks = []
    start = 0
    idx = 0
    while start < len(text):
        end = start + CHUNK_SIZE
        chunk = text[start:end]
        if chunk.strip():
            chunks.append({
                "id":      f"{source}_{idx}",
                "text":    chunk.strip(),
                "source":  source,
            })
        start = end - CHUNK_OVERLAP
        idx += 1
    return chunks


class SOPStore:
    def __init__(self):
        CHROMA_DIR.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        self._ef = embedding_functions.DefaultEmbeddingFunction()
        self._col = self._client.get_or_create_collection(
            name=COLLECTION,
            embedding_function=self._ef,
        )
        if self._col.count() == 0:
            logger.info("[SOPStore] Empty collection — loading knowledge files")
            self.reload()
        else:
            logger.info(f"[SOPStore] Loaded {self._col.count()} chunks from cache")

    def reload(self):
        """Re-read all .md files and rebuild the collection."""
        if not KNOWLEDGE_DIR.exists():
            logger.warning(f"[SOPStore] Knowledge dir not found: {KNOWLEDGE_DIR}")
            return

        all_ids, all_docs, all_metas = [], [], []
        for md_file in KNOWLEDGE_DIR.glob("*.md"):
            text = md_file.read_text(encoding="utf-8")
            for chunk in _chunk_text(text, md_file.stem):
                all_ids.append(chunk["id"])
                all_docs.append(chunk["text"])
                all_metas.append({"source": chunk["source"]})

        if not all_ids:
            logger.warning("[SOPStore] No knowledge files found")
            return

        # Clear and re-add
        try:
            self._client.delete_collection(COLLECTION)
        except Exception:
            pass
        self._col = self._client.get_or_create_collection(
            name=COLLECTION,
            embedding_function=self._ef,
        )
        self._col.add(documents=all_docs, ids=all_ids, metadatas=all_metas)
        logger.info(f"[SOPStore] Indexed {len(all_ids)} chunks from {KNOWLEDGE_DIR}")

    def retrieve(self, query: str, k: int = 4) -> str:
        """Return top-k relevant chunks as a single string for the prompt."""
        if self._col.count() == 0:
            return "(No SOP knowledge loaded)"
        results = self._col.query(query_texts=[query], n_results=min(k, self._col.count()))
        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        parts = []
        for doc, meta in zip(docs, metas):
            parts.append(f"[Source: {meta.get('source', '?')}]\n{doc}")
        return "\n\n---\n\n".join(parts)

    def add_knowledge(self, text: str, source: str):
        """Dynamically add new knowledge (e.g., trainer Q&A answers)."""
        chunks = _chunk_text(text, source)
        if not chunks:
            return
        self._col.add(
            documents=[c["text"] for c in chunks],
            ids=[c["id"] for c in chunks],
            metadatas=[{"source": c["source"]} for c in chunks],
        )
        logger.info(f"[SOPStore] Added {len(chunks)} chunks from source='{source}'")


# Singleton
_store: SOPStore | None = None

def get_sop_store() -> SOPStore:
    global _store
    if _store is None:
        _store = SOPStore()
    return _store

