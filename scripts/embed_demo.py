import psycopg2
from sentence_transformers import SentenceTransformer

# 1. Setup DB Connection
conn = psycopg2.connect("postgres://postgres:mysecret@localhost:5432/postgres")
cur = conn.cursor()

# 2. Reset the Table
cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
cur.execute("DROP TABLE IF EXISTS documents;")
# Note: '384' is the specific dimension size of the 'all-MiniLM-L6-v2' model
cur.execute("CREATE TABLE documents (id serial PRIMARY KEY, content text, embedding vector(384));")

# 3. Load a small, open-source AI model
print("Loading AI Model...")
model = SentenceTransformer('all-MiniLM-L6-v2')

# 4. Define our data (Some similar, some different)
sentences = [
    "The cat sits on the mat",       # Animal / Pet
    "A dog runs on the grass",       # Animal / Pet (Semantically close to cat)
    "I love eating pizza",           # Food
    "The pepperoni slice was tasty", # Food (Semantically close to pizza)
    "Stock market crashed today",    # Finance
    "Investment banking is hard",    # Finance
    "Planets orbit the sun"          # Space (Unrelated to all above)
]

# 5. Generate Embeddings & Insert
print("Generating vectors and inserting...")
embeddings = model.encode(sentences)

for content, vector in zip(sentences, embeddings):
    # Convert numpy array to standard list for Postgres
    cur.execute("INSERT INTO documents (content, embedding) VALUES (%s, %s)", (content, vector.tolist()))

conn.commit()
print("Done! Data is in Postgres.")
