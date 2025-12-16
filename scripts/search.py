import os
import psycopg2
from sentence_transformers import SentenceTransformer
from dotenv import load_dotenv

load_dotenv()

print("Loading model...")
model = SentenceTransformer('all-MiniLM-L6-v2')
conn = psycopg2.connect(os.getenv('DATABASE_URL', 'postgres://postgres:mysecret@localhost:5432/postgres'))
cur = conn.cursor()

while True:
    query = input("\nSearch query (or 'q' to quit): ")
    if query.lower() == 'q':
        break
    
    query_embedding = model.encode(query).tolist()
    
    cur.execute("""
        SELECT content, 1 - (embedding <=> %s::vector) as similarity
        FROM demo
        ORDER BY embedding <=> %s::vector
        LIMIT 5
    """, (query_embedding, query_embedding))
    
    print("\nTop matches:")
    for content, similarity in cur.fetchall():
        print(f"  {similarity:.4f} - {content}")

conn.close()
