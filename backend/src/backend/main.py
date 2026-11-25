import asyncio
import logging
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import bcrypt
import jwt
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from pypdf import PdfReader
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    Fusion,
    FusionQuery,
    MatchValue,
    Modifier,
    PayloadSchemaType,
    PointStruct,
    Prefetch,
    SparseVector,
    SparseVectorParams,
    VectorParams,
)
from sqlalchemy import Column, DateTime, Integer, String, Text, create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

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
EMBED_BATCH_SIZE = int(os.getenv("EMBED_BATCH_SIZE", "64"))
UPSERT_BATCH_SIZE = int(os.getenv("UPSERT_BATCH_SIZE", "64"))
QUEUE_MAX_SIZE = int(os.getenv("QUEUE_MAX_SIZE", "10"))
MAX_PDF_SIZE_BYTES = int(os.getenv("MAX_PDF_SIZE_MB", "50")) * 1024 * 1024
MAX_PDF_PAGES = int(os.getenv("MAX_PDF_PAGES", "500"))
MAX_CHUNKS_PER_PDF = int(os.getenv("MAX_CHUNKS_PER_PDF", "20000"))

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-env")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./app.db")
BACKEND_DIR = Path(__file__).resolve().parents[2]
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", str(BACKEND_DIR / "uploads"))).resolve()

app = FastAPI()
security = HTTPBearer()

embedding_model = None
bm25_model = None
deepseek_client = None
document_queue: asyncio.Queue[str] | None = None
worker_task: asyncio.Task | None = None
qdrant_client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)


class Document(Base):
    __tablename__ = "documents"

    id = Column(String, primary_key=True, index=True)
    upload_id = Column(String, index=True, nullable=False)
    user_id = Column(String, index=True, nullable=False)
    filename = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    size = Column(Integer, nullable=False)
    status = Column(String, index=True, nullable=False)
    pages = Column(Integer, nullable=True)
    chunks = Column(Integer, nullable=True)
    vectors_stored = Column(Integer, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


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
        payload_schema = collection_info.payload_schema
        if "filename" not in payload_schema:
            qdrant_client.create_payload_index(
                collection_name=QDRANT_COLLECTION,
                field_name="filename",
                field_schema=PayloadSchemaType.KEYWORD,
            )
            logger.info("Created payload index on filename for %s", QDRANT_COLLECTION)
        if "user_id" not in payload_schema:
            qdrant_client.create_payload_index(
                collection_name=QDRANT_COLLECTION,
                field_name="user_id",
                field_schema=PayloadSchemaType.KEYWORD,
            )
            logger.info("Created payload index on user_id for %s", QDRANT_COLLECTION)
        if "document_id" not in payload_schema:
            qdrant_client.create_payload_index(
                collection_name=QDRANT_COLLECTION,
                field_name="document_id",
                field_schema=PayloadSchemaType.KEYWORD,
            )
            logger.info("Created payload index on document_id for %s", QDRANT_COLLECTION)
    except Exception as e:
        raise RuntimeError(f"Failed to initialize Qdrant collection '{QDRANT_COLLECTION}': {e}") from e


@app.on_event("startup")
async def on_startup() -> None:
    global document_queue, worker_task

    Base.metadata.create_all(bind=engine)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    ensure_collection()
    document_queue = asyncio.Queue(maxsize=QUEUE_MAX_SIZE)
    worker_task = asyncio.create_task(document_worker())
    logger.info("Qdrant ready: url=%s collection=%s", QDRANT_URL, QDRANT_COLLECTION)
    logger.info("Upload dir: %s", UPLOAD_DIR)


@app.on_event("shutdown")
async def on_shutdown() -> None:
    if worker_task is not None:
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def create_access_token(user_id: str, username: str) -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": user_id, "username": username, "exp": expires_at}
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")
    except jwt.ExpiredSignatureError as e:
        raise HTTPException(status_code=401, detail="Token expired") from e
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail="Invalid token") from e

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


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


def iter_page_texts(file_path: Path):
    with file_path.open("rb") as source:
        reader = PdfReader(source)
        for page_number, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            logger.info("Page %s extracted, length=%s", page_number, len(text))
            yield page_number, text


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


def create_chunks_for_page(text: str, page_number: int) -> list[dict]:
    return [
        {"page": page_number, "chunk_index": chunk_index, "text": chunk}
        for chunk_index, chunk in enumerate(chunk_text(text))
    ]


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
    user_id: str,
    document_id: str,
) -> int:
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
                    "upload_id": document_id,
                    "document_id": document_id,
                    "user_id": user_id,
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
        for i in range(0, len(points), UPSERT_BATCH_SIZE):
            batch = points[i : i + UPSERT_BATCH_SIZE]
            qdrant_client.upsert(collection_name=QDRANT_COLLECTION, points=batch)
        logger.info("Stored %s vectors in %s", len(points), QDRANT_COLLECTION)
    except Exception as e:
        logger.exception("Failed to store vectors in Qdrant")
        raise RuntimeError(f"Failed to store vectors in Qdrant: {e}") from e

    return len(points)


def flush_batch(document: Document, chunks: list[dict]) -> int:
    if not chunks:
        return 0

    dense_embeddings = create_dense_embeddings(chunks)
    sparse_embeddings = create_sparse_embeddings(chunks)
    stored = store_vectors(
        chunks,
        dense_embeddings,
        sparse_embeddings,
        document.filename,
        document.user_id,
        document.id,
    )
    logger.info("Flushed batch of %s chunks for document %s", len(chunks), document.id)
    return stored


def delete_document_vectors(document_id: str, user_id: str | None = None) -> None:
    conditions = [FieldCondition(key="document_id", match=MatchValue(value=document_id))]
    if user_id:
        conditions.append(FieldCondition(key="user_id", match=MatchValue(value=user_id)))

    try:
        qdrant_client.delete(
            collection_name=QDRANT_COLLECTION,
            points_selector=Filter(must=conditions),
        )
        logger.info("Deleted vectors for document %s", document_id)
    except Exception:
        logger.exception("Failed to delete vectors for document %s", document_id)


class SearchRequest(BaseModel):
    query: str
    top_k: int = 5
    mode: str = "hybrid"  # hybrid | dense | bm25


class AskRequest(BaseModel):
    query: str
    top_k: int = 5
    mode: str = "hybrid"  # hybrid | dense | bm25


class AuthRequest(BaseModel):
    username: str
    password: str


def process_document(document_id: str) -> None:
    db = SessionLocal()
    user_id_for_cleanup = None
    try:
        document = db.query(Document).filter(Document.id == document_id).first()
        if not document:
            raise RuntimeError(f"Document {document_id} not found")

        user_id_for_cleanup = document.user_id
        document.status = "processing"
        document.pages = 0
        document.chunks = 0
        document.vectors_stored = 0
        document.error = None
        document.updated_at = datetime.now(timezone.utc)
        db.commit()

        file_path = Path(document.file_path)
        if not file_path.exists():
            raise RuntimeError(f"PDF file not found: {file_path}")

        pending_chunks: list[dict] = []
        total_pages = 0
        total_chunks = 0
        total_vectors = 0

        def update_progress() -> None:
            document.pages = total_pages
            document.chunks = total_chunks
            document.vectors_stored = total_vectors
            document.updated_at = datetime.now(timezone.utc)
            db.commit()

        for page_number, page_text in iter_page_texts(file_path):
            total_pages += 1
            if total_pages > MAX_PDF_PAGES:
                raise RuntimeError(f"PDF exceeds max page limit of {MAX_PDF_PAGES}")

            for chunk in create_chunks_for_page(page_text, page_number):
                total_chunks += 1
                if total_chunks > MAX_CHUNKS_PER_PDF:
                    raise RuntimeError(f"PDF exceeds max chunk limit of {MAX_CHUNKS_PER_PDF}")
                pending_chunks.append(chunk)

                if len(pending_chunks) >= EMBED_BATCH_SIZE:
                    total_vectors += flush_batch(document, pending_chunks)
                    pending_chunks.clear()
                    update_progress()

        if pending_chunks:
            total_vectors += flush_batch(document, pending_chunks)
            pending_chunks.clear()
            update_progress()

        document.pages = total_pages
        document.chunks = total_chunks
        document.vectors_stored = total_vectors
        document.status = "completed"
        document.error = None
        document.updated_at = datetime.now(timezone.utc)
        db.commit()
        logger.info("Document %s processed: %s vectors", document_id, total_vectors)
    except Exception as e:
        logger.exception("Failed to process document %s", document_id)
        db.rollback()
        delete_document_vectors(document_id, user_id_for_cleanup)
        document = db.query(Document).filter(Document.id == document_id).first()
        if document:
            document.status = "failed"
            document.error = str(e)
            document.updated_at = datetime.now(timezone.utc)
            db.commit()
        raise
    finally:
        db.close()


async def document_worker() -> None:
    while True:
        if document_queue is None:
            await asyncio.sleep(0.1)
            continue
        document_id = await document_queue.get()
        try:
            logger.info("Worker picked up document %s", document_id)
            await asyncio.to_thread(process_document, document_id)
            logger.info("Worker finished document %s", document_id)
        except Exception:
            logger.exception("Worker failed on document %s", document_id)
        finally:
            document_queue.task_done()


@app.post("/auth/register")
def register(request: AuthRequest, db: Session = Depends(get_db)):
    username = request.username.strip()
    password = request.password
    if not username or not password:
        raise HTTPException(status_code=400, detail="username and password are required")
    if len(username) < 3 or len(password) < 6:
        raise HTTPException(status_code=400, detail="username must be >=3 chars and password >=6 chars")

    existing = db.query(User).filter(User.username == username).first()
    if existing:
        raise HTTPException(status_code=409, detail="username already exists")

    user = User(
        id=str(uuid.uuid4()),
        username=username,
        password_hash=hash_password(password),
        created_at=datetime.now(timezone.utc),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token(user.id, user.username)
    return {"access_token": token, "token_type": "bearer", "user": {"id": user.id, "username": user.username}}


@app.post("/auth/login")
def login(request: AuthRequest, db: Session = Depends(get_db)):
    username = request.username.strip()
    password = request.password
    if not username or not password:
        raise HTTPException(status_code=400, detail="username and password are required")

    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="invalid username or password")

    token = create_access_token(user.id, user.username)
    return {"access_token": token, "token_type": "bearer", "user": {"id": user.id, "username": user.username}}


@app.post("/upload-pdf")
async def upload_pdf(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if document_queue is None:
        raise HTTPException(status_code=503, detail="Document worker is not ready")
    if document_queue.full():
        raise HTTPException(status_code=429, detail="Upload queue is full, please retry later")

    filename = file.filename or "unknown.pdf"
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")

    document_id = str(uuid.uuid4())
    upload_id = document_id
    user_dir = UPLOAD_DIR / current_user.id
    user_dir.mkdir(parents=True, exist_ok=True)
    file_path = user_dir / f"{document_id}.pdf"

    size = 0
    too_large = False
    with file_path.open("wb") as out:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_PDF_SIZE_BYTES:
                too_large = True
                break
            out.write(chunk)

    if too_large:
        file_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=413,
            detail=f"PDF exceeds max size of {MAX_PDF_SIZE_BYTES // (1024 * 1024)} MB",
        )

    if size == 0:
        file_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    document = Document(
        id=document_id,
        upload_id=upload_id,
        user_id=current_user.id,
        filename=filename,
        file_path=str(file_path),
        size=size,
        status="queued",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(document)
    db.commit()
    db.refresh(document)

    try:
        document_queue.put_nowait(document_id)
    except asyncio.QueueFull:
        db.delete(document)
        db.commit()
        file_path.unlink(missing_ok=True)
        raise HTTPException(status_code=429, detail="Upload queue is full, please retry later")

    logger.info("Queued document %s: filename=%s size=%s", document_id, filename, size)

    return {
        "document_id": document_id,
        "upload_id": upload_id,
        "filename": filename,
        "size": size,
        "status": "queued",
    }


def retrieve_matches(query: str, top_k: int, mode: str, user_id: str) -> list[dict]:
    dense_vector = None
    sparse_vector = None
    if mode in {"hybrid", "dense"}:
        dense_model = get_embedding_model()
        dense_vector = dense_model.encode(query, show_progress_bar=False).tolist()
    if mode in {"hybrid", "bm25"}:
        bm25_model = get_bm25_model()
        sparse_emb = next(bm25_model.embed([query]))
        sparse_vector = SparseVector(indices=sparse_emb.indices.tolist(), values=sparse_emb.values.tolist())

    user_filter = Filter(must=[FieldCondition(key="user_id", match=MatchValue(value=user_id))])

    try:
        if mode == "dense":
            response = qdrant_client.query_points(
                collection_name=QDRANT_COLLECTION,
                query=dense_vector,
                using=DENSE_VECTOR_NAME,
                query_filter=user_filter,
                limit=top_k,
                with_payload=True,
            )
        elif mode == "bm25":
            response = qdrant_client.query_points(
                collection_name=QDRANT_COLLECTION,
                query=sparse_vector,
                using=BM25_VECTOR_NAME,
                query_filter=user_filter,
                limit=top_k,
                with_payload=True,
            )
        else:
            prefetch_limit = max(top_k * 3, 10)
            response = qdrant_client.query_points(
                collection_name=QDRANT_COLLECTION,
                prefetch=[
                    Prefetch(query=dense_vector, using=DENSE_VECTOR_NAME, limit=prefetch_limit, filter=user_filter),
                    Prefetch(query=sparse_vector, using=BM25_VECTOR_NAME, limit=prefetch_limit, filter=user_filter),
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
                "document_id": payload.get("document_id"),
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
async def search(request: SearchRequest, current_user: User = Depends(get_current_user)):
    query = request.query.strip()
    mode = request.mode.strip().lower()
    if not query:
        raise HTTPException(status_code=400, detail="query must not be empty")
    if request.top_k < 1:
        raise HTTPException(status_code=400, detail="top_k must be >= 1")
    if mode not in {"hybrid", "dense", "bm25"}:
        raise HTTPException(status_code=400, detail="mode must be one of: hybrid, dense, bm25")

    matches = retrieve_matches(query, request.top_k, mode, current_user.id)
    return {"query": query, "top_k": request.top_k, "mode": mode, "results": matches}


@app.post("/ask")
async def ask(request: AskRequest, current_user: User = Depends(get_current_user)):
    query = request.query.strip()
    mode = request.mode.strip().lower()
    if not query:
        raise HTTPException(status_code=400, detail="query must not be empty")
    if request.top_k < 1:
        raise HTTPException(status_code=400, detail="top_k must be >= 1")
    if mode not in {"hybrid", "dense", "bm25"}:
        raise HTTPException(status_code=400, detail="mode must be one of: hybrid, dense, bm25")

    matches = retrieve_matches(query, request.top_k, mode, current_user.id)
    answer = generate_answer(query, matches)
    sources = [
        {
            "filename": m.get("filename"),
            "page": m.get("page"),
            "chunk_index": m.get("chunk_index"),
            "score": m.get("score"),
            "upload_id": m.get("upload_id"),
            "document_id": m.get("document_id"),
        }
        for m in matches
    ]
    return {"query": query, "mode": mode, "top_k": request.top_k, "answer": answer, "sources": sources}

def main():
    import uvicorn

    uvicorn.run("backend.main:app", reload=True)