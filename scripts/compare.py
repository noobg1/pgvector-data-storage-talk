from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity

print("Loading model...")
model = SentenceTransformer('all-MiniLM-L6-v2')

while True:
    text1 = input("\nText 1 (or 'q' to quit): ")
    if text1.lower() == 'q':
        break
    text2 = input("Text 2: ")
    
    embeddings = model.encode([text1, text2])
    score = cosine_similarity([embeddings[0]], [embeddings[1]])[0][0]
    
    print(f"\nText 1 embedding: {embeddings[0][:5]}... (384 dims)")
    print(f"Text 2 embedding: {embeddings[1][:5]}... (384 dims)")
    print(f"\nSimilarity score: {score:.4f}")
