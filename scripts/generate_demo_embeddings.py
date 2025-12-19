#!/usr/bin/env python3
"""
Generate real embeddings with meaningful text content for pgvector demo.
This creates 50,000 diverse documents with realistic random text.
Uses 1024 dimensions from BGE-large model to demonstrate TOAST behavior.
"""

import psycopg2
from sentence_transformers import SentenceTransformer
import random
import os
from dotenv import load_dotenv
from tqdm import tqdm

# Load environment variables
load_dotenv()

# Import datasets for Wikipedia content
try:
    from datasets import load_dataset
    HAS_DATASETS = True
except ImportError:
    HAS_DATASETS = False
    print("⚠️  datasets not installed. Install with: pip install datasets")
    exit(1)

# Load WikiText dataset
print("Loading WikiText dataset...")
wiki_dataset = load_dataset("wikitext", "wikitext-103-v1", split="train", streaming=True)
wiki_iter = iter(wiki_dataset)

def generate_diverse_text():
    """Get meaningful text from WikiText."""
    global wiki_iter
    while True:
        try:
            article = next(wiki_iter)
            text = article['text'].strip()
            
            # Skip empty or very short entries
            if len(text) < 100:
                continue
            
            # Extract a meaningful chunk (100-300 chars)
            sentences = [s.strip() for s in text.split('.') if s.strip()]
            if not sentences:
                continue
                
            num_sentences = random.randint(1, 3)
            chunk = '. '.join(sentences[:num_sentences])
            
            if len(chunk) > 300:
                chunk = chunk[:300].rsplit('.', 1)[0] + '.'
            if len(chunk) >= 50:
                return chunk
        except:
            wiki_iter = iter(wiki_dataset)
            continue

def main():
    print("🚀 Generating embeddings for pgvector demo...")
    print("=" * 60)
    
    # Get database URL from environment
    db_url = os.getenv('DATABASE_URL', 'postgres://postgres:mysecret@localhost:5432/postgres')
    
    # Connect to database
    print("\n1. Connecting to PostgreSQL...")
    print(f"   Using: {db_url.split('@')[1] if '@' in db_url else 'default connection'}")
    conn = psycopg2.connect(db_url)
    cur = conn.cursor()
    
    # Setup database
    print("2. Setting up database schema...")
    cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    cur.execute("DROP TABLE IF EXISTS docs;")
    cur.execute("""
        CREATE TABLE docs (
            id serial PRIMARY KEY,
            content text,
            embedding vector(1024),
            metadata jsonb DEFAULT '{}'::jsonb
        );
    """)
    conn.commit()
    
    # Load model
    print("3. Loading sentence transformer model (this may take a moment)...")
    print("   Model: BAAI/bge-large-en-v1.5 (1024 dimensions)")
    print("   This model naturally outputs 1024d vectors (>2KB, will be TOASTed)")
    model = SentenceTransformer('BAAI/bge-large-en-v1.5')
    
    # Generate and insert documents
    print("\n4. Generating 50,000 diverse documents with embeddings...")
    print("   This will take 10-15 minutes...")
    print("   ✓ Using WikiText dataset for meaningful content")
    
    batch_size = 100
    total_docs = 50000
    batches = total_docs // batch_size
    
    for batch_num in tqdm(range(batches), desc="Generating embeddings", unit="batch"):
        texts = []
        
        # Generate batch of diverse texts
        for _ in range(batch_size):
            text = generate_diverse_text()
            texts.append(text)
        
        # Generate embeddings for batch (1024 dimensions from model)
        embeddings = model.encode(texts, show_progress_bar=False)
        
        # Insert batch
        for text, embedding in zip(texts, embeddings):
            cur.execute(
                "INSERT INTO docs (content, embedding) VALUES (%s, %s)",
                (text, embedding.tolist())
            )
        
        conn.commit()
    
    print(f"\n✅ Successfully inserted {total_docs:,} documents!")
    
    # Show statistics
    print("\n5. Database statistics:")
    cur.execute("SELECT COUNT(*) FROM docs;")
    count = cur.fetchone()[0]
    print(f"   Total documents: {count:,}")
    
    cur.execute("SELECT pg_size_pretty(pg_total_relation_size('docs'));")
    size = cur.fetchone()[0]
    print(f"   Total table size: {size}")
    
    cur.execute("SELECT pg_size_pretty(pg_relation_size('docs'));")
    heap_size = cur.fetchone()[0]
    print(f"   Heap size: {heap_size}")
    
    # Check TOAST
    cur.execute("""
        SELECT pg_size_pretty(pg_relation_size(
            (SELECT reltoastrelid FROM pg_class WHERE relname = 'docs')
        )) as toast_size;
    """)
    toast_size = cur.fetchone()[0]
    print(f"   TOAST size: {toast_size}")
    
    # Show sample documents
    print("\n6. Sample documents:")
    cur.execute("SELECT id, content, array_length(embedding::float4[], 1) as dims, pg_column_size(embedding) as bytes FROM docs LIMIT 5;")
    for row in cur.fetchall():
        print(f"   [{row[0]}] {row[1][:50]}... ({row[2]} dims, {row[3]} bytes)")
    
    # Show content diversity
    print("\n7. Sample content (showing diversity):")
    cur.execute("SELECT content FROM docs ORDER BY random() LIMIT 5;")
    for i, row in enumerate(cur.fetchall(), 1):
        print(f"   {i}. {row[0][:70]}...")
    
    print("\n" + "=" * 60)
    print("✨ Demo data ready! You can now run the SQL commands from")
    print("   pgvector_deep_dive_demo.md")
    print("\n💡 Key points:")
    print("   - 50,000 diverse documents")
    print("   - 1024 dimensions (~4 KB per vector)")
    print("   - Vectors are TOASTed (> 2KB threshold)")
    print("   - Real WikiText content")
    print("=" * 60)
    
    conn.close()

if __name__ == "__main__":
    main()
