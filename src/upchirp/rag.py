"""Document search with pgvector, embeddings from a local Ollama model.

Docs are split into chunks of whole paragraphs (about 800 characters), embedded
with nomic-embed-text (768 dimensions) and stored in doc_chunks. Retrieved text
is data for the agent, never instructions (step 5 tests this with planted text).
"""

import os
from pathlib import Path
from typing import Any

import httpx
import psycopg

EMBED_MODEL = "nomic-embed-text"
CHUNK_CHARS = 800


def _ollama() -> str:
    return os.environ.get("OLLAMA_HOST", "http://localhost:11434")


def embed(texts: list[str], kind: str) -> list[list[float]]:
    """kind is 'search_document' or 'search_query' (nomic-embed-text task prefixes)."""
    resp = httpx.post(f"{_ollama()}/api/embed", timeout=120,
                      json={"model": EMBED_MODEL, "input": [f"{kind}: {t}" for t in texts]})
    resp.raise_for_status()
    vectors: list[list[float]] = resp.json()["embeddings"]
    return vectors


def chunk(text: str, size: int = CHUNK_CHARS) -> list[str]:
    out: list[str] = []
    current = ""
    for para in (p.strip() for p in text.split("\n\n")):
        if not para:
            continue
        if current and len(current) + len(para) > size:
            out.append(current)
            current = ""
        current = f"{current}\n\n{para}" if current else para
    if current:
        out.append(current)
    return out


def _vec(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"


def index_docs(conn: psycopg.Connection[Any], docs_dir: Path) -> int:
    """Replace the index with every Markdown file under docs_dir. Returns chunk count."""
    rows = [(path.relative_to(docs_dir).as_posix(), c)
            for path in sorted(docs_dir.rglob("*.md"))
            for c in chunk(path.read_text(encoding="utf-8"))]
    vectors = embed([c for _, c in rows], "search_document") if rows else []
    with conn.transaction(), conn.cursor() as cur:
        cur.execute("DELETE FROM doc_chunks")
        cur.executemany(
            "INSERT INTO doc_chunks (doc, chunk, embedding) VALUES (%s, %s, %s::vector)",
            [(doc, c, _vec(v)) for (doc, c), v in zip(rows, vectors, strict=True)],
        )
    return len(rows)


def search(conn: psycopg.Connection[Any], query: str, limit: int = 4) -> list[dict[str, Any]]:
    (q,) = embed([query], "search_query")
    rows = conn.execute(
        "SELECT doc, chunk, 1 - (embedding <=> %s::vector) AS score FROM doc_chunks "
        "ORDER BY embedding <=> %s::vector LIMIT %s", (_vec(q), _vec(q), limit)).fetchall()
    return [{"doc": r["doc"], "text": r["chunk"], "score": round(float(r["score"]), 3)}
            for r in rows]
