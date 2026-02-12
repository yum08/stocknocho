"""
Vector Store - ChromaDB-based vector database for RAG retrieval.
==================================================================

Why Vector DB + SQLite (not just one)?
- SQLite (Level 1 & 2): Structured queries — "show me all RELIANCE mentions 
  from last 7 days sorted by date" → fast, indexed, relational
- ChromaDB (Vector): Semantic queries — "what are people saying about banking 
  sector outlook" → embedding similarity search

Together they form a powerful hybrid:
  1. SQLite filters and stores structured data
  2. ChromaDB enables semantic search for RAG retrieval
  3. The RAG pipeline queries ChromaDB, retrieves context, feeds to LLM
"""

import os
from datetime import datetime
from typing import List, Dict, Optional, Tuple

try:
    import chromadb
    from chromadb.config import Settings
    HAS_CHROMADB = True
except ImportError:
    HAS_CHROMADB = False
    print("⚠ chromadb not installed. Install with: pip install chromadb")

from .database import Database, RawPost, Platform


# ──────────────────────────────────────────────────────────────────────
# VECTOR STORE
# ──────────────────────────────────────────────────────────────────────

class VectorStore:
    """
    ChromaDB-based vector store for stock market social media posts.
    
    ChromaDB handles:
    - Embedding generation (default: all-MiniLM-L6-v2 via sentence-transformers)
    - Vector storage and indexing
    - Similarity search
    - Metadata filtering
    
    You can also use OpenAI/Gemini embeddings for better quality.
    """

    COLLECTION_NAME = "stock_posts"

    def __init__(self, persist_dir: str = "./chroma_db"):
        if not HAS_CHROMADB:
            raise ImportError("chromadb is required. Install: pip install chromadb")
        
        self.persist_dir = persist_dir
        self.client = chromadb.PersistentClient(path=persist_dir)
        self.collection = self.client.get_or_create_collection(
            name=self.COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"}  # cosine similarity
        )

    def add_posts(self, posts: List[Dict]) -> int:
        """
        Add posts to vector store.
        Each post dict should have: id, text, platform, posted_at, stock_symbols, etc.
        """
        if not posts:
            return 0

        ids = []
        documents = []
        metadatas = []

        for post in posts:
            post_id = str(post.get('id', ''))
            text = post.get('text_clean') or post.get('text', '')
            
            if not text or not post_id:
                continue

            # Skip very short texts
            if len(text.strip()) < 10:
                continue

            ids.append(f"post_{post_id}")
            documents.append(text[:2000])  # ChromaDB has token limits
            
            meta = {
                "platform": post.get('platform', 'unknown'),
                "author": str(post.get('author', ''))[:100],
                "posted_at": str(post.get('posted_at', '')),
                "source_id": str(post.get('source_id', '')),
                "views": int(post.get('views', 0)),
                "likes": int(post.get('likes', 0)),
            }
            # Add stock symbols if available
            if post.get('stock_symbols'):
                meta['stock_symbols'] = ','.join(post['stock_symbols'])
            
            metadatas.append(meta)

        if not ids:
            return 0

        # Upsert (add or update)
        self.collection.upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
        )
        return len(ids)

    def search(self, query: str, n_results: int = 10,
               platform: Optional[str] = None,
               stock_symbol: Optional[str] = None) -> List[Dict]:
        """
        Semantic search for relevant posts.
        
        Args:
            query: Natural language query
            n_results: Number of results to return
            platform: Filter by platform (telegram, x, linkedin)
            stock_symbol: Filter by stock symbol
        
        Returns:
            List of {id, text, metadata, distance} dicts
        """
        where_filter = {}
        if platform:
            where_filter["platform"] = platform
        if stock_symbol:
            where_filter["stock_symbols"] = {"$contains": stock_symbol}

        kwargs = {
            "query_texts": [query],
            "n_results": n_results,
        }
        if where_filter:
            kwargs["where"] = where_filter

        results = self.collection.query(**kwargs)

        output = []
        if results and results['documents']:
            for i, doc in enumerate(results['documents'][0]):
                output.append({
                    'id': results['ids'][0][i] if results['ids'] else None,
                    'text': doc,
                    'metadata': results['metadatas'][0][i] if results['metadatas'] else {},
                    'distance': results['distances'][0][i] if results['distances'] else None,
                })

        return output

    def sync_from_db(self, db: Database, batch_size: int = 500) -> int:
        """
        Sync posts from SQLite to ChromaDB vector store.
        Only syncs stock-relevant, processed posts.
        """
        session = db.get_session()
        try:
            # Get stock-relevant posts not yet in vector store
            posts = session.query(RawPost).filter(
                RawPost.is_processed == True,
                RawPost.is_stock_relevant == True,
            ).limit(batch_size).all()

            post_dicts = []
            for p in posts:
                # Check if already in ChromaDB
                try:
                    existing = self.collection.get(ids=[f"post_{p.id}"])
                    if existing and existing['ids']:
                        continue
                except Exception:
                    pass

                post_dicts.append({
                    'id': p.id,
                    'text': p.text,
                    'text_clean': p.text_clean,
                    'platform': p.platform.value if p.platform else 'unknown',
                    'author': p.author,
                    'posted_at': str(p.posted_at) if p.posted_at else '',
                    'source_id': p.source_id,
                    'views': p.views or 0,
                    'likes': p.likes or 0,
                })

            return self.add_posts(post_dicts)
        finally:
            session.close()

    def get_stats(self) -> dict:
        """Get vector store statistics."""
        return {
            "total_documents": self.collection.count(),
            "persist_dir": self.persist_dir,
        }
