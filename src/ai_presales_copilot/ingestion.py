"""Safe, reproducible knowledge ingestion primitives.

This is intentionally a small Phase 2 subset rather than a crawler platform:
only registered/allow-listed sources can be fetched, every artifact receives a
content hash and license metadata, and chunks are emitted as JSONL for the
PostgreSQL pgvector/tsvector index.
"""

from __future__ import annotations

import hashlib
import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from .security import inspect_sensitive_data, inspect_untrusted_input


class IngestionRejected(ValueError):
    """Raised when a source violates the ingestion boundary."""


@dataclass(frozen=True)
class SourceSpec:
    source_id: str
    title: str
    license: str
    tenant_id: str = "public"
    acl: tuple[str, ...] = ()
    allowed_domains: tuple[str, ...] = ()
    source_url: str | None = None
    local_path: str | None = None
    version: str | None = None
    effective_from: str | None = None
    effective_to: str | None = None
    retrieval_only: bool = True
    training_allowed: bool = False

    def __post_init__(self) -> None:
        if bool(self.source_url) == bool(self.local_path):
            raise ValueError("exactly one of source_url or local_path is required")
        if self.source_url:
            assert_allowed_url(self.source_url, self.allowed_domains)


@dataclass(frozen=True)
class ChunkRecord:
    evidence_id: str
    source_id: str
    source_url: str | None
    source_path: str | None
    title: str
    version: str
    license: str
    text: str
    page: int | None
    heading: str | None
    start_offset: int
    end_offset: int
    content_hash: str
    fetched_at: str
    tenant_id: str
    acl: tuple[str, ...] = ()
    effective_from: str | None = None
    effective_to: str | None = None
    retrieval_only: bool = True
    training_allowed: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["acl"] = list(self.acl)
        payload["excerpt"] = payload.pop("text")
        payload["locator"] = _locator(self.page, self.heading, self.start_offset, self.end_offset)
        return payload


@dataclass(frozen=True)
class IngestedSource:
    spec: SourceSpec
    content_hash: str
    fetched_at: str
    media_type: str
    chunks: tuple[ChunkRecord, ...]
    warnings: tuple[str, ...] = ()

    def manifest(self) -> dict[str, Any]:
        return {
            "source": asdict(self.spec),
            "source_content_hash": self.content_hash,
            "fetched_at": self.fetched_at,
            "media_type": self.media_type,
            "chunk_count": len(self.chunks),
            "warnings": list(self.warnings),
        }


class SourceRegistry:
    """Load source registrations; callers never supply arbitrary URLs."""

    def __init__(self, specs: Iterable[SourceSpec] = ()):
        self._specs = {item.source_id: item for item in specs}

    @classmethod
    def from_json(cls, path: str | Path) -> SourceRegistry:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise TypeError("source registry must be a JSON array")
        return cls(SourceSpec(**item) for item in payload)

    def get(self, source_id: str) -> SourceSpec:
        try:
            return self._specs[source_id]
        except KeyError as exc:
            raise IngestionRejected(f"source_id is not registered: {source_id}") from exc

    def all(self) -> list[SourceSpec]:
        return list(self._specs.values())


def assert_allowed_url(url: str, allowed_domains: Iterable[str]) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise IngestionRejected("only HTTPS URLs with a hostname are allowed")
    if parsed.username or parsed.password:
        raise IngestionRejected("URLs with embedded credentials are forbidden")
    hostname = parsed.hostname.rstrip(".").lower()
    domains = tuple(item.lower().lstrip(".") for item in allowed_domains if item)
    if not domains or not any(hostname == domain or hostname.endswith("." + domain) for domain in domains):
        raise IngestionRejected(f"URL host is not on the allow-list: {hostname}")
    # Resolve before fetching and reject loopback/private/link-local targets.
    # This closes the common DNS-rebinding/SSRF path for a small local crawler.
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)}
    except OSError as exc:
        raise IngestionRejected(f"could not resolve source host: {hostname}") from exc
    import ipaddress

    if any(
        ipaddress.ip_address(address).is_private
        or ipaddress.ip_address(address).is_loopback
        or ipaddress.ip_address(address).is_link_local
        or ipaddress.ip_address(address).is_reserved
        for address in addresses
    ):
        raise IngestionRejected("source host resolves to a private or reserved address")


def fetch_registered_url(
    spec: SourceSpec,
    *,
    timeout_s: float = 15,
    max_bytes: int = 20_000_000,
    user_agent: str = "ai-presales-copilot-ingester/1.0",
) -> tuple[bytes, str]:
    if not spec.source_url:
        raise IngestionRejected("source has no URL")
    assert_allowed_url(spec.source_url, spec.allowed_domains)
    parsed = urllib.parse.urlparse(spec.source_url)
    robots_url = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, "/robots.txt", "", "", ""))
    robots = urllib.robotparser.RobotFileParser(robots_url)
    try:
        robots.read()
    except (OSError, urllib.error.URLError):
        raise IngestionRejected("robots.txt could not be checked; refusing remote fetch")
    if not robots.can_fetch(user_agent, spec.source_url):
        raise IngestionRejected("robots.txt does not allow this user agent")
    request = urllib.request.Request(spec.source_url, headers={"User-Agent": user_agent})
    opener = urllib.request.build_opener(_AllowlistedRedirectHandler(spec.allowed_domains))
    try:
        with opener.open(request, timeout=timeout_s) as response:
            content_type = response.headers.get_content_type()
            body = response.read(max_bytes + 1)
    except (urllib.error.URLError, TimeoutError) as exc:
        raise IngestionRejected(f"source fetch failed: {exc}") from exc
    if len(body) > max_bytes:
        raise IngestionRejected("source exceeds the configured size limit")
    return body, content_type


class _AllowlistedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Re-apply the source boundary to every HTTP redirect target."""

    def __init__(self, allowed_domains: Iterable[str]):
        super().__init__()
        self.allowed_domains = tuple(allowed_domains)

    def redirect_request(self, req, fp, code, msg, newurl, headers, method=None):
        assert_allowed_url(newurl, self.allowed_domains)
        return super().redirect_request(req, fp, code, msg, newurl, headers, method)


def ingest_source(
    spec: SourceSpec,
    *,
    root: str | Path = ".",
    chunk_size: int = 1_200,
    overlap: int = 160,
    allow_sensitive: bool = False,
) -> IngestedSource:
    if spec.local_path:
        root_path = Path(root).resolve()
        path = (root_path / spec.local_path).resolve()
        if root_path not in path.parents:
            raise IngestionRejected("local source must stay under the configured ingestion root")
        if not path.is_file():
            raise IngestionRejected(f"local source does not exist: {spec.local_path}")
        raw = path.read_bytes()
        media_type = _media_type(path.suffix)
        source_path = str(path)
    else:
        raw, media_type = fetch_registered_url(spec)
        source_path = None
    content_hash = hashlib.sha256(raw).hexdigest()
    text, pages = extract_text(raw, media_type, source_path)
    findings = inspect_sensitive_data(text).matches + inspect_untrusted_input(text).matches
    if findings and not allow_sensitive:
        raise IngestionRejected("source contains PII or instruction-like text; quarantine it before indexing")
    version = spec.version or content_hash[:16]
    fetched_at = _utc_now()
    chunks = tuple(
        make_chunks(
            text,
            source=spec,
            version=version,
            content_hash=content_hash,
            fetched_at=fetched_at,
            source_path=source_path,
            pages=pages,
            chunk_size=chunk_size,
            overlap=overlap,
        )
    )
    return IngestedSource(
        spec=spec,
        content_hash=content_hash,
        fetched_at=fetched_at,
        media_type=media_type,
        chunks=chunks,
        warnings=tuple("sensitive_or_instruction_like_content_detected" for _ in [1] if findings),
    )


def extract_text(raw: bytes, media_type: str, source_path: str | None = None) -> tuple[str, list[tuple[int, str]]]:
    suffix = Path(source_path or "").suffix.lower()
    if media_type in {"text/html", "application/xhtml+xml"} or suffix in {".html", ".htm"}:
        return _HtmlTextParser().parse(raw.decode("utf-8", errors="replace")), []
    if media_type == "application/pdf" or suffix == ".pdf":
        try:
            import pymupdf  # type: ignore[import-not-found]
        except ImportError as exc:
            raise IngestionRejected("PDF ingestion requires PyMuPDF") from exc
        document = pymupdf.open(stream=raw, filetype="pdf")
        pages = [(index + 1, page.get_text("text")) for index, page in enumerate(document)]
        return "\n\n".join(text for _, text in pages), pages
    if (
        media_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        or suffix == ".docx"
    ):
        try:
            from docx import Document as WordDocument  # type: ignore[import-not-found]
        except ImportError as exc:
            raise IngestionRejected("DOCX ingestion requires python-docx") from exc
        import io

        document = WordDocument(io.BytesIO(raw))
        return "\n\n".join(item.text for item in document.paragraphs), []
    return raw.decode("utf-8", errors="replace"), []


def make_chunks(
    text: str,
    *,
    source: SourceSpec,
    version: str,
    content_hash: str,
    fetched_at: str,
    source_path: str | None,
    pages: list[tuple[int, str]],
    chunk_size: int,
    overlap: int,
) -> list[ChunkRecord]:
    if chunk_size <= 0 or overlap < 0 or overlap >= chunk_size:
        raise ValueError("chunk_size must be positive and overlap must be smaller")
    cleaned = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not cleaned:
        return []
    chunks: list[ChunkRecord] = []
    start = 0
    index = 1
    while start < len(cleaned):
        end = min(len(cleaned), start + chunk_size)
        if end < len(cleaned):
            boundary = max(cleaned.rfind("\n\n", start, end), cleaned.rfind("。", start, end))
            if boundary > start + chunk_size // 2:
                end = boundary + (2 if cleaned[boundary:boundary + 2] == "\n\n" else 1)
        excerpt = cleaned[start:end].strip()
        if excerpt:
            page = _page_for_offset(cleaned, start, pages)
            heading = _nearest_heading(cleaned, start)
            if heading is None:
                match = re.match(r"#{1,6}\s+(.+?)\s*(?:\n|$)", excerpt)
                heading = match.group(1).strip() if match else None
            evidence_id = f"{source.source_id}:{version}:c{index:04d}"
            chunks.append(
                ChunkRecord(
                    evidence_id=evidence_id,
                    source_id=source.source_id,
                    source_url=source.source_url,
                    source_path=source_path or source.local_path,
                    title=source.title,
                    version=version,
                    license=source.license,
                    text=excerpt,
                    fetched_at=fetched_at,
                    page=page,
                    heading=heading,
                    start_offset=start,
                    end_offset=end,
                    content_hash=content_hash,
                    tenant_id=source.tenant_id,
                    acl=source.acl,
                    effective_from=source.effective_from,
                    effective_to=source.effective_to,
                    retrieval_only=source.retrieval_only,
                    training_allowed=source.training_allowed,
                )
            )
        if end == len(cleaned):
            break
        start = max(end - overlap, start + 1)
        index += 1
    return chunks


def write_jsonl(sources: Iterable[IngestedSource], chunks_path: str | Path, manifest_path: str | Path) -> None:
    chunks_target = Path(chunks_path)
    manifest_target = Path(manifest_path)
    chunks_target.parent.mkdir(parents=True, exist_ok=True)
    manifest_target.parent.mkdir(parents=True, exist_ok=True)
    with chunks_target.open("w", encoding="utf-8") as chunks_handle:
        for source in sources:
            for chunk in source.chunks:
                chunks_handle.write(json.dumps(chunk.to_dict(), ensure_ascii=False) + "\n")
    with manifest_target.open("w", encoding="utf-8") as manifest_handle:
        for source in sources:
            manifest_handle.write(json.dumps(source.manifest(), ensure_ascii=False) + "\n")


class _HtmlTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._hidden = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"}:
            self._hidden += 1
        elif tag.lower() in {"p", "li", "h1", "h2", "h3", "h4", "br"} and self._hidden == 0:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"} and self._hidden:
            self._hidden -= 1
        elif tag.lower() in {"p", "li", "h1", "h2", "h3", "h4"} and self._hidden == 0:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._hidden == 0:
            self.parts.append(data)

    def parse(self, text: str) -> str:
        self.feed(text)
        return re.sub(r"[ \t]+", " ", "".join(self.parts)).strip()


def _media_type(suffix: str) -> str:
    return {
        ".html": "text/html",
        ".htm": "text/html",
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".md": "text/markdown",
    }.get(suffix.lower(), "text/plain")


def _locator(page: int | None, heading: str | None, start: int, end: int) -> str:
    pieces = []
    if page is not None:
        pieces.append(f"page={page}")
    if heading:
        pieces.append(f"heading={heading}")
    pieces.append(f"offset={start}:{end}")
    return ";".join(pieces)


def _page_for_offset(text: str, offset: int, pages: list[tuple[int, str]]) -> int | None:
    if not pages:
        return None
    position = 0
    for page, page_text in pages:
        position += len(page_text) + 2
        if offset < position:
            return page
    return pages[-1][0]


def _nearest_heading(text: str, offset: int) -> str | None:
    prefix = text[:offset]
    matches = re.findall(r"(?m)^#{1,6}\s+(.+?)\s*$", prefix)
    return matches[-1].strip() if matches else None


def _utc_now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()
