import psycopg2
from sentence_transformers import SentenceTransformer

model = SentenceTransformer('all-MiniLM-L6-v2')
conn = psycopg2.connect("postgres://postgres:mysecret@localhost:5432/postgres")
cur = conn.cursor()

query = input("Search query: ")
query_embedding = model.encode(query).tolist()

cur.execute("""
    SELECT content, 1 - (embedding <=> %s::vector) as similarity
    FROM documents
    ORDER BY embedding <=> %s::vector
    LIMIT 5
""", (query_embedding, query_embedding))

print("\nTop matches:")
for content, similarity in cur.fetchall():
    print(f"{similarity:.4f} - {content}")

conn.close()
