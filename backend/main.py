import io
import logging

from fastapi import FastAPI, File, UploadFile
from pypdf import PdfReader

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()


def extract_pages(content: bytes) -> list[str]:
    reader = PdfReader(io.BytesIO(content))
    pages = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        pages.append(text)
        logger.info("Page %s extracted, length=%s", i + 1, len(text))
    return pages


def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 200) -> list[str]:
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = end - overlap
    return chunks


def create_chunks(pages: list[str]) -> list[dict]:
    chunks = []
    for page_num, text in enumerate(pages, start=1):
        for idx, chunk in enumerate(chunk_text(text)):
            chunks.append({"page": page_num, "chunk_index": idx, "text": chunk})
    return chunks


def create_embeddings(chunks: list[dict]) -> list[list[float]]:
    logger.info("Creating embeddings for %s chunks (placeholder)", len(chunks))
    return [[] for _ in chunks]


@app.post("/upload-pdf")
async def upload_pdf(file: UploadFile = File(...)):
    content = await file.read()
    logger.info("Received PDF: filename=%s size=%s", file.filename, len(content))

    pages = extract_pages(content)
    chunks = create_chunks(pages)

    for chunk in chunks:
        logger.info(
            "Chunk page=%s index=%s length=%s text=%r",
            chunk["page"],
            chunk["chunk_index"],
            len(chunk["text"]),
            chunk["text"][:200],
        )

    embeddings = create_embeddings(chunks)

    return {
        "filename": file.filename,
        "pages": len(pages),
        "chunks": len(chunks),
        "embeddings_created": len(embeddings),
    }
