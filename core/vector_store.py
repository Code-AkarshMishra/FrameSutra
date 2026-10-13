import hashlib
import re
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document

from core.config import PROJECT_ROOT

CHROMA_DIR = str(PROJECT_ROOT / "vector_db")
COLLECTION_PREFIX = "video_"
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def get_embeddings():
    return HuggingFaceEmbeddings(
        model_name=EMBEDDING_MODEL,
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )


def _collection_for_text(text: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]
    return f"{COLLECTION_PREFIX}{digest}"


def build_vector_store(transcript: str) -> Chroma:
    """Index a transcript in its own deterministic collection to avoid mixing videos."""
    cleaned = transcript.strip()
    if not cleaned:
        raise ValueError("Cannot build a RAG index from an empty transcript.")

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=700,
        chunk_overlap=100,
        add_start_index=True,
    )
    docs = splitter.create_documents([cleaned])
    if not docs:
        raise ValueError("Transcript chunking produced no chunks.")

    transcript_hash = hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:24]
    for i, doc in enumerate(docs):
        start = int(doc.metadata.get("start_index", 0) or 0)
        markers = list(re.finditer(r"\[(?:Approx\. timestamp |VISUAL FRAME )(\d{2}:\d{2}:\d{2})\]", cleaned[:start + 1]))
        timestamp = markers[-1].group(1) if markers else "unknown"
        doc.metadata.update({
            "chunk_index": i,
            "transcript_id": transcript_hash,
            "approx_timestamp": timestamp,
        })
    ids = [f"{transcript_hash}_{i}" for i in range(len(docs))]
    return Chroma.from_documents(
        documents=docs,
        embedding=get_embeddings(),
        ids=ids,
        collection_name=_collection_for_text(cleaned),
        persist_directory=CHROMA_DIR,
    )


def load_vector_store(collection_name: str) -> Chroma:
    """Load a known transcript collection by name."""
    return Chroma(
        collection_name=collection_name,
        embedding_function=get_embeddings(),
        persist_directory=CHROMA_DIR,
    )


def get_retriever(vector_store: Chroma, k: int = 4):
    return vector_store.as_retriever(
        search_type="similarity",
        search_kwargs={"k": k},
    )
