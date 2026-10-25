import hashlib
import re
from functools import lru_cache
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document

from core.config import PROJECT_ROOT

CHROMA_DIR = str(PROJECT_ROOT / "vector_db")
COLLECTION_PREFIX = "video_"
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


@lru_cache(maxsize=1)
def get_embeddings():
    """Load the embedding model once per process instead of reloading for each video."""
    print(f"[RAG] Loading embedding model: {EMBEDDING_MODEL}")
    embeddings = HuggingFaceEmbeddings(
        model_name=EMBEDDING_MODEL,
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True, "batch_size": 32},
        show_progress=True,
    )
    print("[RAG] Embedding model ready.")
    return embeddings


def _collection_for_text(text: str) -> str:
    # The schema tag forces existing jobs onto the timestamp-aware chunk layout.
    digest = hashlib.sha256(("timestamped-chunks-v2|" + text).encode("utf-8")).hexdigest()[:24]
    return f"{COLLECTION_PREFIX}{digest}"


def collection_for_text(text: str) -> str:
    """Return the deterministic collection id for a transcript/RAG corpus."""
    return _collection_for_text(text)


def build_vector_store(transcript: str) -> Chroma:
    """Index a transcript in its own deterministic collection to avoid mixing videos."""
    cleaned = transcript.strip()
    if not cleaned:
        raise ValueError("Cannot build a RAG index from an empty transcript.")

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=700,
        chunk_overlap=100,
    )
    marker_pattern = re.compile(r"\[(?:Speech timestamp |Approx\. timestamp |VISUAL FRAME )(\d{2}:\d{2}:\d{2})\]")
    markers = list(marker_pattern.finditer(cleaned))
    sections: list[tuple[str, str]] = []
    if markers:
        prefix = cleaned[:markers[0].start()].strip()
        if prefix and prefix.lower() != "visual evidence":
            sections.append(("unknown", prefix))
        for index, marker in enumerate(markers):
            end = markers[index + 1].start() if index + 1 < len(markers) else len(cleaned)
            body = cleaned[marker.end():end].strip()
            if body:
                sections.append((marker.group(1), body))
    else:
        sections = [("unknown", cleaned)]

    docs = []
    buffered_text: list[str] = []
    buffered_size = 0
    buffered_timestamp = "unknown"
    buffered_window = -1

    def flush_buffer() -> None:
        nonlocal buffered_text, buffered_size, buffered_timestamp, buffered_window
        if buffered_text:
            docs.append(Document(page_content="\n".join(buffered_text).strip(), metadata={"approx_timestamp": buffered_timestamp}))
        buffered_text = []
        buffered_size = 0
        buffered_timestamp = "unknown"
        buffered_window = -1

    for timestamp, section in sections:
        if timestamp == "unknown":
            window = -1
        else:
            hours, minutes, seconds = (int(part) for part in timestamp.split(":"))
            window = (hours * 3600 + minutes * 60 + seconds) // 600
        if buffered_text and (window != buffered_window or buffered_size + len(section) > 900):
            flush_buffer()
        if len(section) > 900:
            flush_buffer()
            for piece in splitter.split_text(section):
                if piece.strip():
                    docs.append(Document(page_content=piece.strip(), metadata={"approx_timestamp": timestamp}))
            continue
        if not buffered_text:
            buffered_timestamp = timestamp
            buffered_window = window
        buffered_text.append(section)
        buffered_size += len(section)
    flush_buffer()
    if not docs:
        raise ValueError("Transcript chunking produced no chunks.")

    transcript_hash = hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:24]
    for i, doc in enumerate(docs):
        doc.metadata.update({
            "chunk_index": i,
            "transcript_id": transcript_hash,
        })
    ids = [f"{transcript_hash}_{i}" for i in range(len(docs))]
    collection_name = _collection_for_text(cleaned)
    print(f"[RAG] Indexing transcript: {len(docs)} chunks; collection={collection_name}")
    # Reuse the deterministic collection if it already exists. This avoids
    # re-embedding the same transcript after a Streamlit rerun/retry.
    try:
        existing = Chroma(
            collection_name=collection_name,
            embedding_function=get_embeddings(),
            persist_directory=CHROMA_DIR,
        )
        if existing._collection.count() >= len(docs):
            print(f"[RAG] Reusing existing index ({existing._collection.count()} chunks).")
            return existing
    except Exception as exc:
        print(f"[RAG] Existing index unavailable; rebuilding ({exc}).")

    return Chroma.from_documents(
        documents=docs,
        embedding=get_embeddings(),
        ids=ids,
        collection_name=collection_name,
        persist_directory=CHROMA_DIR,
    )


def load_vector_store(collection_name: str) -> Chroma:
    """Load a known transcript collection by name."""
    return Chroma(
        collection_name=collection_name,
        embedding_function=get_embeddings(),
        persist_directory=CHROMA_DIR,
    )


def search_documents(vector_store: Chroma, query: str, vector_k: int = 16) -> list[Document]:
    """Combine semantic candidates with lightweight lexical search over the same corpus."""
    collection = vector_store._collection
    stored = collection.get(include=["documents", "metadatas"])
    documents = stored.get("documents") or []
    metadatas = stored.get("metadatas") or []
    ids = stored.get("ids") or []
    candidates: dict[str, Document] = {}

    # Lexical matching catches exact names, acronyms, and phrases that embeddings
    # can rank below conceptually similar but less useful chunks.
    query_terms = set(re.findall(r"[a-z0-9]+", query.lower()))
    stop_words = {"what", "when", "where", "which", "who", "why", "how", "does", "did", "is", "are", "was", "were", "the", "a", "an", "of", "in", "on", "to", "for", "and", "or", "it", "this", "that", "tell", "me", "about", "explain", "please", "full", "form"}
    query_terms -= stop_words
    definition_intent = bool(re.search(r"\b(full form|stand for|stands for|meaning|expand|expanded)\b", query, re.I))
    acronyms = [token.lower() for token in re.findall(r"\b[A-Z]{2,8}\b", query)]
    if definition_intent and not acronyms:
        acronyms = [token for token in query_terms if 2 <= len(token) <= 8]
    if query_terms:
        for i, text in enumerate(documents):
            lowered = (text or "").lower()
            matched = sum(1 for term in query_terms if term in lowered)
            if matched:
                key = str((metadatas[i] or {}).get("chunk_index", ids[i] if i < len(ids) else i))
                candidates[key] = Document(page_content=text, metadata=metadatas[i] or {})

    try:
        for doc in vector_store.similarity_search(query, k=max(1, vector_k)):
            key = str(doc.metadata.get("chunk_index", doc.page_content[:80]))
            candidates.setdefault(key, doc)
    except Exception:
        # Lexical hits still provide useful grounding if vector search is unavailable.
        pass

    def lexical_score(doc: Document) -> tuple[float, int]:
        lowered = doc.page_content.lower()
        hits = sum(1 for term in query_terms if term in lowered)
        phrase = int(bool(query.strip()) and query.strip().lower() in lowered)
        definition = 0
        if definition_intent and any(
            re.search(rf"\b{re.escape(acronym)}\b.{{0,100}}\b(?:means|stands for|is short for|expands to)\b", lowered)
            for acronym in acronyms
        ):
            definition = 4
        return (hits + phrase * 2 + definition, phrase + definition)

    ranked = sorted(candidates.values(), key=lexical_score, reverse=True)
    if len(ranked) < 4:
        try:
            for doc in vector_store.similarity_search(query, k=8):
                if all(doc.page_content != old.page_content for old in ranked):
                    ranked.append(doc)
        except Exception:
            pass
    return ranked[:8]


def delete_vector_store(collection_name: str) -> None:
    """Delete one app-owned collection from the persistent Chroma client."""
    from chromadb import PersistentClient
    client = PersistentClient(path=CHROMA_DIR)
    names = [item.name if hasattr(item, "name") else str(item) for item in client.list_collections()]
    if collection_name in names and collection_name.startswith(COLLECTION_PREFIX):
        client.delete_collection(collection_name)


def get_retriever(vector_store: Chroma, k: int = 4):
    return vector_store.as_retriever(
        search_type="similarity",
        search_kwargs={"k": k},
    )
