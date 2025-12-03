import psycopg2
from sentence_transformers import SentenceTransformer

model = SentenceTransformer('all-MiniLM-L6-v2')
conn = psycopg2.connect("postgres://postgres:mysecret@localhost:5432/postgres")
cur = conn.cursor()

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
        cur.execute("INSERT INTO documents (content, embedding) VALUES (%s, %s)", (content, vector.tolist()))
    conn.commit()
    print(f"Added {len(texts)} documents")
else:
    print("No texts entered")

conn.close()
