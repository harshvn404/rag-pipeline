import io
import logging
import os
import re
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel
from pypdf import PdfReader
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    Fusion,
    FusionQuery,
    Modifier,
    PayloadSchemaType,
    PointStruct,
    Prefetch,
    SparseVector,
    SparseVectorParams,
    VectorParams,
)

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "pdf_chunks")
EMBEDDING_SIZE = 384
DENSE_VECTOR_NAME = "dense"
BM25_VECTOR_NAME = "bm25"
BM25_MODEL_NAME = "Qdrant/bm25"

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

app = FastAPI()

embedding_model = None
bm25_model = None
deepseek_client = None
qdrant_client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)


def ensure_collection() -> None:
    try:
        collections = [c.name for c in qdrant_client.get_collections().collections]
        if QDRANT_COLLECTION not in collections:
            qdrant_client.create_collection(
                collection_name=QDRANT_COLLECTION,
                vectors_config={
                    DENSE_VECTOR_NAME: VectorParams(size=EMBEDDING_SIZE, distance=Distance.COSINE),
                },
                sparse_vectors_config={
                    BM25_VECTOR_NAME: SparseVectorParams(modifier=Modifier.IDF),
                },
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


def get_bm25_model():
    global bm25_model
    if bm25_model is None:
        try:
            from fastembed import SparseTextEmbedding
        except ImportError as e:
            raise RuntimeError(
                "fastembed is not installed. Install with: pip install -r backend/requirements.txt"
            ) from e

        logger.info("Loading BM25 sparse model")
        bm25_model = SparseTextEmbedding(BM25_MODEL_NAME)
    return bm25_model


def get_deepseek_client():
    global deepseek_client
    if not DEEPSEEK_API_KEY:
        raise HTTPException(status_code=500, detail="DEEPSEEK_API_KEY is not set")
    if deepseek_client is None:
        try:
            from openai import OpenAI
        except ImportError as e:
            raise RuntimeError(
                "openai is not installed. Install with: pip install -r backend/requirements.txt"
            ) from e
        deepseek_client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
    return deepseek_client


def extract_pages(content: bytes) -> list[str]:
    reader = PdfReader(io.BytesIO(content))
    pages = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        pages.append(text)
        logger.info("Page %s extracted, length=%s", i + 1, len(text))
    return pages


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'])", text.strip())
    return [p.strip() for p in parts if p and p.strip()]


def split_long_text(text: str, max_size: int) -> list[str]:
    sentences = split_sentences(text)
    if len(sentences) <= 1:
        return [text[i : i + max_size].strip() for i in range(0, len(text), max_size) if text[i : i + max_size].strip()]

    units: list[str] = []
    current = ""
    for sentence in sentences:
        if len(sentence) > max_size:
            if current:
                units.append(current.strip())
                current = ""
            units.extend(split_long_text(sentence, max_size))
            continue
        candidate = f"{current} {sentence}".strip() if current else sentence
        if len(candidate) <= max_size:
            current = candidate
        else:
            if current:
                units.append(current.strip())
            current = sentence
    if current:
        units.append(current.strip())
    return units


def split_into_units(text: str, max_size: int) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    units: list[str] = []
    for paragraph in paragraphs:
        if len(paragraph) <= max_size:
            units.append(paragraph)
        else:
            units.extend(split_long_text(paragraph, max_size))
    return units


def get_overlap_units(chunks: list[str], overlap: int) -> str:
    if overlap <= 0 or not chunks:
        return ""
    selected: list[str] = []
    size = 0
    for chunk in reversed(chunks):
        chunk_len = len(chunk) + (2 if selected else 0)
        if selected and size + chunk_len > overlap:
            break
        selected.insert(0, chunk)
        size += chunk_len
        if size >= overlap:
            break
    overlap_text = "\n\n".join(selected).strip()
    if len(overlap_text) > overlap:
        overlap_text = overlap_text[-overlap:].strip()
    return overlap_text


def chunk_text(text: str, chunk_size: int = 1200, overlap: int = 200) -> list[str]:
    normalized = normalize_text(text)
    if not normalized:
        return []

    units = split_into_units(normalized, chunk_size)
    if not units:
        return []

    overlap = max(0, min(overlap, chunk_size - 1))
    chunks: list[str] = []
    current = ""
    current_units: list[str] = []

    for unit in units:
        candidate = f"{current}\n\n{unit}".strip() if current else unit
        if len(candidate) <= chunk_size:
            current = candidate
            current_units.append(unit)
            continue

        if current:
            chunks.append(current.strip())
            overlap_text = get_overlap_units(current_units, overlap)
            current = f"{overlap_text}\n\n{unit}".strip() if overlap_text else unit
            current_units = [overlap_text, unit] if overlap_text else [unit]
            while len(current) > chunk_size and current_units:
                if len(current_units) == 1:
                    for part in split_long_text(current_units[0], chunk_size):
                        chunks.append(part.strip())
                    current = ""
                    current_units = []
                    break
                # drop oldest overlap unit to fit
                current_units.pop(0)
                current = "\n\n".join(u for u in current_units if u).strip()
        else:
            for part in split_long_text(unit, chunk_size):
                chunks.append(part.strip())
            current = ""
            current_units = []

    if current:
        chunks.append(current.strip())

    deduped: list[str] = []
    for chunk in chunks:
        if chunk and (not deduped or chunk != deduped[-1]):
            deduped.append(chunk)
    return deduped


def create_chunks(pages: list[str]) -> list[dict]:
    chunks = []
    for page_num, text in enumerate(pages, start=1):
        for idx, chunk in enumerate(chunk_text(text)):
            chunks.append({"page": page_num, "chunk_index": idx, "text": chunk})
    return chunks


def create_dense_embeddings(chunks: list[dict]) -> list[list[float]]:
    texts = [chunk["text"] for chunk in chunks]
    if not texts:
        return []
    model = get_embedding_model()
    logger.info("Creating dense embeddings for %s chunks", len(texts))
    embeddings = model.encode(texts, show_progress_bar=False)
    return embeddings.tolist()


def create_sparse_embeddings(chunks: list[dict]) -> list[SparseVector]:
    texts = [chunk["text"] for chunk in chunks]
    if not texts:
        return []
    model = get_bm25_model()
    logger.info("Creating BM25 sparse embeddings for %s chunks", len(texts))
    embeddings = list(model.embed(texts))
    return [
        SparseVector(indices=emb.indices.tolist(), values=emb.values.tolist())
        for emb in embeddings
    ]


def store_vectors(
    chunks: list[dict],
    dense_embeddings: list[list[float]],
    sparse_embeddings: list[SparseVector],
    filename: str,
) -> tuple[str, int]:
    upload_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    points = []
    for chunk, dense_embedding, sparse_embedding in zip(chunks, dense_embeddings, sparse_embeddings):
        points.append(
            PointStruct(
                id=str(uuid.uuid4()),
                vector={
                    DENSE_VECTOR_NAME: dense_embedding,
                    BM25_VECTOR_NAME: sparse_embedding,
                },
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
    mode: str = "hybrid"  # hybrid | dense | bm25


class AskRequest(BaseModel):
    query: str
    top_k: int = 5
    mode: str = "hybrid"  # hybrid | dense | bm25


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

    dense_embeddings = create_dense_embeddings(chunks)
    sparse_embeddings = create_sparse_embeddings(chunks)
    upload_id, vectors_stored = store_vectors(
        chunks, dense_embeddings, sparse_embeddings, file.filename or "unknown.pdf"
    )

    return {
        "upload_id": upload_id,
        "filename": file.filename,
        "pages": len(pages),
        "chunks": len(chunks),
        "embeddings_created": len(dense_embeddings),
        "embedding_dimension": len(dense_embeddings[0]) if dense_embeddings else 0,
        "collection": QDRANT_COLLECTION,
        "vectors_stored": vectors_stored,
    }


def retrieve_matches(query: str, top_k: int, mode: str) -> list[dict]:
    dense_vector = None
    sparse_vector = None
    if mode in {"hybrid", "dense"}:
        dense_model = get_embedding_model()
        dense_vector = dense_model.encode(query, show_progress_bar=False).tolist()
    if mode in {"hybrid", "bm25"}:
        bm25_model = get_bm25_model()
        sparse_emb = next(bm25_model.embed([query]))
        sparse_vector = SparseVector(indices=sparse_emb.indices.tolist(), values=sparse_emb.values.tolist())

    try:
        if mode == "dense":
            response = qdrant_client.query_points(
                collection_name=QDRANT_COLLECTION,
                query=dense_vector,
                using=DENSE_VECTOR_NAME,
                limit=top_k,
                with_payload=True,
            )
        elif mode == "bm25":
            response = qdrant_client.query_points(
                collection_name=QDRANT_COLLECTION,
                query=sparse_vector,
                using=BM25_VECTOR_NAME,
                limit=top_k,
                with_payload=True,
            )
        else:
            prefetch_limit = max(top_k * 3, 10)
            response = qdrant_client.query_points(
                collection_name=QDRANT_COLLECTION,
                prefetch=[
                    Prefetch(query=dense_vector, using=DENSE_VECTOR_NAME, limit=prefetch_limit),
                    Prefetch(query=sparse_vector, using=BM25_VECTOR_NAME, limit=prefetch_limit),
                ],
                query=FusionQuery(fusion=Fusion.RRF),
                limit=top_k,
                with_payload=True,
            )
        results = response.points
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
    return matches


def build_context(matches: list[dict], max_chars: int = 12000) -> str:
    parts = []
    total = 0
    for i, m in enumerate(matches, start=1):
        text = (m.get("text") or "").strip()
        snippet = (
            f"[Source {i} | file={m.get('filename')} | page={m.get('page')} | score={m.get('score')}]\n"
            f"{text}"
        )
        if total + len(snippet) > max_chars and parts:
            break
        parts.append(snippet)
        total += len(snippet)
    return "\n\n".join(parts)


def generate_answer(query: str, matches: list[dict]) -> str:
    context = build_context(matches)
    if not context:
        return "I don't know from the provided documents."

    client = get_deepseek_client()
    system_prompt = (
        "You are a helpful assistant for document Q&A. "
        "Answer only using the provided context. "
        "If the answer is not in the context, say you don't know from the provided documents. "
        "Cite sources by filename and page when relevant."
    )
    user_prompt = f"Question:\n{query}\n\nContext:\n{context}"

    try:
        completion = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            stream=False,
        )
    except Exception as e:
        logger.exception("DeepSeek request failed")
        raise HTTPException(status_code=502, detail=f"DeepSeek request failed: {e}") from e

    answer = completion.choices[0].message.content if completion.choices else ""
    return (answer or "").strip()


@app.post("/search")
async def search(request: SearchRequest):
    query = request.query.strip()
    mode = request.mode.strip().lower()
    if not query:
        raise HTTPException(status_code=400, detail="query must not be empty")
    if request.top_k < 1:
        raise HTTPException(status_code=400, detail="top_k must be >= 1")
    if mode not in {"hybrid", "dense", "bm25"}:
        raise HTTPException(status_code=400, detail="mode must be one of: hybrid, dense, bm25")

    matches = retrieve_matches(query, request.top_k, mode)
    return {"query": query, "top_k": request.top_k, "mode": mode, "results": matches}


@app.post("/ask")
async def ask(request: AskRequest):
    query = request.query.strip()
    mode = request.mode.strip().lower()
    if not query:
        raise HTTPException(status_code=400, detail="query must not be empty")
    if request.top_k < 1:
        raise HTTPException(status_code=400, detail="top_k must be >= 1")
    if mode not in {"hybrid", "dense", "bm25"}:
        raise HTTPException(status_code=400, detail="mode must be one of: hybrid, dense, bm25")

    matches = retrieve_matches(query, request.top_k, mode)
    answer = generate_answer(query, matches)
    sources = [
        {
            "filename": m.get("filename"),
            "page": m.get("page"),
            "chunk_index": m.get("chunk_index"),
            "score": m.get("score"),
            "upload_id": m.get("upload_id"),
        }
        for m in matches
    ]
    return {"query": query, "mode": mode, "top_k": request.top_k, "answer": answer, "sources": sources}
