"""Small local retriever used for offline tests and the llama.cpp integration demo."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

from .schemas import Evidence


@dataclass(frozen=True)
class Document:
    evidence_id: str
    title: str
    path: Path
    text: str


def _terms(text: str) -> list[str]:
    """Use words plus Chinese character bigrams so no tokenizer is required."""

    normalized = re.sub(r"\s+", " ", text.lower())
    words = re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]", normalized)
    bigrams = [
        normalized[i : i + 2] for i in range(len(normalized) - 1) if not normalized[i].isspace()
    ]
    return words + bigrams


class KnowledgeBase:
    """A transparent term-frequency retriever for a small portfolio corpus."""

    def __init__(self, directory: str | Path):
        self.directory = Path(directory)
        self.documents = self._load_documents()

    def _load_documents(self) -> list[Document]:
        documents: list[Document] = []
        content_paths = [
            path for path in sorted(self.directory.glob("*.md")) if path.name.lower() != "readme.md"
        ]
        for index, path in enumerate(content_paths, start=1):
            text = path.read_text(encoding="utf-8")
            title = next(
                (line.lstrip("# ").strip() for line in text.splitlines() if line.startswith("#")),
                path.stem,
            )
            documents.append(Document(f"KB-{index:03d}", title, path, text))
        return documents

    def search(self, query: str, top_k: int = 3, min_score: float = 0.1) -> list[Evidence]:
        query_terms = _terms(query)
        if not query_terms:
            return []
        query_counts = {term: query_terms.count(term) for term in set(query_terms)}
        ranked: list[tuple[float, Document]] = []
        for document in self.documents:
            document_terms = _terms(document.text)
            if not document_terms:
                continue
            doc_counts = {term: document_terms.count(term) for term in set(document_terms)}
            numerator = sum(
                query_counts.get(term, 0) * doc_counts.get(term, 0) for term in query_counts
            )
            query_norm = math.sqrt(sum(value * value for value in query_counts.values()))
            doc_norm = math.sqrt(sum(value * value for value in doc_counts.values()))
            score = numerator / (query_norm * doc_norm) if query_norm and doc_norm else 0.0
            if score >= min_score:
                ranked.append((score, document))
        ranked.sort(key=lambda item: item[0], reverse=True)
        results: list[Evidence] = []
        for score, document in ranked[:top_k]:
            excerpt = _excerpt(document.text, query_terms)
            try:
                source_path = str(document.path.relative_to(self.directory.parent.parent))
            except ValueError:
                source_path = document.path.name
            results.append(
                Evidence(
                    document.evidence_id, document.title, excerpt, source_path, round(score, 4)
                )
            )
        return results


def _excerpt(text: str, query_terms: list[str], width: int = 300) -> str:
    lines = [
        line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")
    ]
    if not lines:
        return text[:width]
    best = max(lines, key=lambda line: sum(line.lower().count(term) for term in query_terms))
    return best[:width]
