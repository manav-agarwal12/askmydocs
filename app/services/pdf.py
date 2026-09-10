from dataclasses import dataclass
from pathlib import Path

# PyMuPDF renamed its import from "fitz" to "pymupdf". Try the new name
# first so we don't get a deprecation warning on newer versions.
try:
    import pymupdf as fitz
except ImportError:
    import fitz

from app.core.constants import CHUNK_OVERLAP_WORDS, CHUNK_SIZE_WORDS


class PdfExtractionError(Exception):
    """The PDF cannot be read, or contains no text we can use."""


@dataclass
class PageText:
    page_number: int   # 1-based, so it matches what the user sees
    text: str


@dataclass
class TextChunk:
    chunk_index: int
    page_number: int
    text: str
    word_count: int


def normalise_whitespace(text: str) -> str:
    """Collapse all runs of whitespace into single spaces.

    PDF text arrives full of stray newlines from the page layout. Those
    carry no meaning for us and would waste tokens later.
    """
    return " ".join(text.split())


def extract_pages(stored_path: str) -> tuple[list[PageText], int]:
    """Read a PDF and return (pages with text, total page count).

    Pages with no extractable text are skipped, but still counted in the
    page total.
    """
    if not Path(stored_path).exists():
        raise PdfExtractionError(f"File not found on disk: {stored_path}")

    try:
        doc = fitz.open(stored_path)
    except Exception as exc:
        raise PdfExtractionError(f"Could not open PDF: {exc}") from exc

    try:
        if doc.needs_pass:
            raise PdfExtractionError("PDF is password protected")

        total_pages = doc.page_count
        pages: list[PageText] = []

        for index in range(total_pages):
            raw = doc.load_page(index).get_text("text")
            cleaned = normalise_whitespace(raw)
            if cleaned:
                pages.append(PageText(page_number=index + 1, text=cleaned))
    finally:
        doc.close()   # always release the file handle, even on error

    if not pages:
        raise PdfExtractionError(
            "No extractable text found. The PDF is probably a scan and "
            "would need OCR."
        )

    return pages, total_pages


def chunk_pages(
    pages: list[PageText],
    size_words: int = CHUNK_SIZE_WORDS,
    overlap_words: int = CHUNK_OVERLAP_WORDS,
) -> list[TextChunk]:
    """Split page text into overlapping chunks, one page at a time.

    Chunks never cross a page boundary, so every chunk has exactly one
    correct page number. That is what makes citations possible.
    """
    if overlap_words >= size_words:
        raise ValueError("overlap_words must be smaller than size_words")

    step = size_words - overlap_words
    chunks: list[TextChunk] = []

    for page in pages:
        words = page.text.split()
        if not words:
            continue

        start = 0
        while start < len(words):
            window = words[start:start + size_words]

            chunks.append(
                TextChunk(
                    chunk_index=len(chunks),   # global, across the document
                    page_number=page.page_number,
                    text=" ".join(window),
                    word_count=len(window),
                )
            )

            # Stop once this window reached the end, otherwise the next
            # window would be nothing but overlap.
            if start + size_words >= len(words):
                break

            start += step

    return chunks