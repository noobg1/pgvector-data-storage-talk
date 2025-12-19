import os
import psycopg2
from sentence_transformers import SentenceTransformer
from dotenv import load_dotenv

load_dotenv()

# Connect to database
conn = psycopg2.connect(os.getenv('DATABASE_URL', 'postgres://postgres:mysecret@localhost:5432/postgres'))
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
count = 0
while True:
    text = input("> ")
    if not text:
        break
    
    embedding = model.encode(text)
    cur.execute(
        "INSERT INTO demo (content, embedding) VALUES (%s, %s)", 
        (text, embedding.tolist())
    )
    conn.commit()
    count += 1
    print(f"✓ Added to DB")

if count > 0:
    print(f"\nTotal: {count} texts added")
else:
    print("No texts entered")

conn.close()
