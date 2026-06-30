import logging

import chromadb
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

from app.data.faq import FAQ_DATA

logger = logging.getLogger(__name__)

_collection: chromadb.Collection | None = None


def _build_collection(client: chromadb.ClientAPI) -> chromadb.Collection:
    ef = DefaultEmbeddingFunction()
    collection = client.get_or_create_collection(
        name="faq",
        embedding_function=ef,
        metadata={"hnsw:space": "cosine"},
    )

    if collection.count() == 0:
        logger.info("Seeding knowledge base with %d FAQ entries…", len(FAQ_DATA))
        collection.add(
            ids=[str(i) for i in range(len(FAQ_DATA))],
            documents=[
                f"Q: {item['question']}\nA: {item['answer']}" for item in FAQ_DATA
            ],
            metadatas=[
                {"question": item["question"], "answer": item["answer"]}
                for item in FAQ_DATA
            ],
        )
        logger.info("Knowledge base seeded.")

    return collection


def init_knowledge_base(persist_path: str = "./chroma_db") -> None:
    """Call once at application startup to load/seed the vector store."""
    global _collection
    client = chromadb.PersistentClient(path=persist_path)
    _collection = _build_collection(client)


def search_knowledge_base(query: str, n_results: int = 3) -> list[dict]:
    """
    RAG retrieval: return the top-n FAQ entries most relevant to *query*.
    Each result has keys: question, answer, score (0–1, higher = more relevant).
    """
    if _collection is None:
        raise RuntimeError("Knowledge base is not initialised. Call init_knowledge_base() first.")

    results = _collection.query(query_texts=[query], n_results=n_results)

    hits = []
    for i, meta in enumerate(results["metadatas"][0]):
        # ChromaDB cosine space returns distances in [0, 2]; convert to similarity
        distance = results["distances"][0][i]
        score = round(1 - distance / 2, 4)
        hits.append(
            {
                "question": meta["question"],
                "answer": meta["answer"],
                "score": score,
            }
        )

    return hits
