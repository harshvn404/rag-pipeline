import io
import logging
import os
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel
from pypdf import PdfReader
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PayloadSchemaType, PointStruct, VectorParams

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "pdf_chunks")
EMBEDDING_SIZE = 384

app = FastAPI()

embedding_model = None
qdrant_client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)


def ensure_collection() -> None:
    try:
        collections = [c.name for c in qdrant_client.get_collections().collections]
        if QDRANT_COLLECTION not in collections:
            qdrant_client.create_collection(
                collection_name=QDRANT_COLLECTION,
                vectors_config=VectorParams(size=EMBEDDING_SIZE, distance=Distance.COSINE),
            )
            logger.info("Created Qdrant collection: %s", QDRANT_COLLECTION)

        collection_info = qdrant_client.get_collection(QDRANT_COLLECTION)
        if "filename" not in collection_info.payload_schema:
            qdrant_client.create_payload_index(
                collection_name=QDRANT_COLLECTION,
                field_name="filename",
                field_schema=PayloadSchemaType.KEYWORD,
            )
            logger.info("Created payload index on filename for %s", QDRANT_COLLECTION)
    except Exception as e:
        raise RuntimeError(f"Failed to initialize Qdrant collection '{QDRANT_COLLECTION}': {e}") from e


@app.on_event("startup")
def on_startup() -> None:
    ensure_collection()
    logger.info("Qdrant ready: url=%s collection=%s", QDRANT_URL, QDRANT_COLLECTION)


def get_embedding_model():
    global embedding_model
    if embedding_model is None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as e:
            raise RuntimeError(
                "sentence-transformers is not installed. Install with: pip install -r backend/requirements.txt"
            ) from e

        logger.info("Loading embedding model")
        embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
    return embedding_model


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
    texts = [chunk["text"] for chunk in chunks]
    if not texts:
        return []
    model = get_embedding_model()
    logger.info("Creating embeddings for %s chunks", len(texts))
    embeddings = model.encode(texts, show_progress_bar=False)
    return embeddings.tolist()


def store_vectors(chunks: list[dict], embeddings: list[list[float]], filename: str) -> tuple[str, int]:
    upload_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    points = []
    for chunk, embedding in zip(chunks, embeddings):
        points.append(
            PointStruct(
                id=str(uuid.uuid4()),
                vector=embedding,
                payload={
                    "upload_id": upload_id,
                    "filename": filename,
                    "page": chunk["page"],
                    "chunk_index": chunk["chunk_index"],
                    "text": chunk["text"],
                    "char_count": len(chunk["text"]),
                    "created_at": now,
                },
            )
        )

    try:
        for i in range(0, len(points), 64):
            batch = points[i : i + 64]
            qdrant_client.upsert(collection_name=QDRANT_COLLECTION, points=batch)
        logger.info("Stored %s vectors in %s", len(points), QDRANT_COLLECTION)
    except Exception as e:
        logger.exception("Failed to store vectors in Qdrant")
        raise HTTPException(status_code=500, detail=f"Failed to store vectors in Qdrant: {e}") from e

    return upload_id, len(points)


class SearchRequest(BaseModel):
    query: str
    top_k: int = 5


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
    upload_id, vectors_stored = store_vectors(chunks, embeddings, file.filename or "unknown.pdf")

    return {
        "upload_id": upload_id,
        "filename": file.filename,
        "pages": len(pages),
        "chunks": len(chunks),
        "embeddings_created": len(embeddings),
        "embedding_dimension": len(embeddings[0]) if embeddings else 0,
        "collection": QDRANT_COLLECTION,
        "vectors_stored": vectors_stored,
    }


@app.post("/search")
async def search(request: SearchRequest):
    query = request.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="query must not be empty")
    if request.top_k < 1:
        raise HTTPException(status_code=400, detail="top_k must be >= 1")

    model = get_embedding_model()
    query_vector = model.encode(query, show_progress_bar=False).tolist()

    try:
        results = qdrant_client.query_points(
            collection_name=QDRANT_COLLECTION,
            query=query_vector,
            limit=request.top_k,
            with_payload=True,
        ).points
    except Exception as e:
        logger.exception("Qdrant search failed")
        raise HTTPException(status_code=500, detail=f"Qdrant search failed: {e}") from e

    matches = []
    for point in results:
        payload = point.payload or {}
        matches.append(
            {
                "id": str(point.id),
                "score": point.score,
                "text": payload.get("text"),
                "filename": payload.get("filename"),
                "page": payload.get("page"),
                "chunk_index": payload.get("chunk_index"),
                "upload_id": payload.get("upload_id"),
            }
        )

    return {"query": query, "top_k": request.top_k, "results": matches}
