import psycopg2
from sentence_transformers import SentenceTransformer

# Connect to database
conn = psycopg2.connect("postgres://postgres:mysecret@localhost:5432/postgres")
cur = conn.cursor()

# Ensure pgvector extension and table exist
cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
cur.execute("""
    CREATE TABLE IF NOT EXISTS demo (
        id serial PRIMARY KEY,
        content text,
        embedding vector(384)
    );
""")
conn.commit()

# Load model
model = SentenceTransformer('all-MiniLM-L6-v2')

print("Enter texts (one per line, empty line to finish):")
texts = []
while True:
    text = input("> ")
    if not text:
        break
    texts.append(text)

if texts:
    embeddings = model.encode(texts)
    for content, vector in zip(texts, embeddings):
        cur.execute(
            "INSERT INTO demo (content, embedding) VALUES (%s, %s)", 
            (content, vector.tolist())
        )
    conn.commit()
    print(f"✓ Added {len(texts)} demo")
else:
    print("No texts entered")

conn.close()
