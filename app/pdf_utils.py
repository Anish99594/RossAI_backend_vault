import fitz  # PyMuPDF
import concurrent.futures


def _read_page(page, mode="text"):
    """Internal: actually read PDF text."""
    return page.get_text(mode) or ""


def read_page_with_timeout(page, timeout=2):
    """
    Run page.get_text in a separate thread
    so timeout does NOT break FastAPI or Pinecone.
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_read_page, page)
        try:
            return future.result(timeout=timeout)
        except Exception:
            # timeout OR PDF extraction failure
            return ""


def iter_pages_text(file_path: str):
    """
    Stream PDF pages safely.
    Each page has a max timeout of 2 seconds.
    """
    doc = fitz.open(file_path)

    for i, page in enumerate(doc, start=1):
        print(f"[PDF] Reading page {i}...")

        text = read_page_with_timeout(page, timeout=2)

        if text:
            print(f"[PDF] Page {i} OK")
        else:
            print(f"[PDF] Page {i} TIMEOUT or ERROR → returning empty text")

        yield i, text

    doc.close()


def chunk_text(text: str, chunk_size: int, overlap: int):
    """
    Chunk generator — yields text chunks with overlap.
    Uses generator to avoid RAM usage.
    """
    start = 0
    length = len(text)

    while start < length:
        end = min(length, start + chunk_size)
        yield text[start:end]
        start = end - overlap
        if start < 0:
            start = 0
