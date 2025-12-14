---
title: "Inside pgvector"
sub_title: "How PostgreSQL Stores, Indexes & Manages High-Dimensional Data"
author: "Narrated by: Jeevan"
date: "December 19, 2025"
---

# Our Journey Today

<!-- column_layout: [1, 1] -->

<!-- column: 0 -->

## 1. Embeddings & Distance
- What are embeddings?
- How to compare vectors?
- Distance operators

## 2. Storage Deep Dive
- Where vectors live in Postgres
- TOAST behavior (1536d = 6KB!)
- Why size matters

## 3. Search Without Indexes
- Semantic search basics
- Sequential scan performance
- The O(N) problem

<!-- column: 1 -->

## 4. ANN Indexes
- IVFFlat: k-means clustering
- HNSW: hierarchical graphs
- 63-70x speedup!

## 5. Production Reality
- MVCC bloat problem
- Separate embedding tables
- Index strategy & tuning
- Best practices for scale

<!-- end_slide -->

# Chapter 1: What's an Embedding?

**Text → Numbers that capture meaning**

```
"I love pizza"     → [0.2, 0.8, 0.1, ... 384 numbers]
"Pizza is great"   → [0.3, 0.7, 0.2, ... 384 numbers]
"The sky is blue"  → [0.9, 0.1, 0.8, ... 384 numbers]
```

<!-- pause -->

**Key insight:** Similar meanings → Similar numbers!

<!-- end_slide -->

# 🎯 Let's See It In Action

```bash
python scripts/demo.py compare
```

<!-- end_slide -->

# Now Let's Store Embeddings in Postgres

```bash
python scripts/demo.py seed
```

<!-- end_slide -->

# Inspect the Data in psql

```sql
-- See all documents
SELECT id, content FROM documents;

-- Check embedding dimensions
SELECT id, content, 
       array_length(embedding::float4[], 1) AS dimensions
FROM documents LIMIT 3;

-- Peek at first 5 numbers of embedding
SELECT id, content,
       (embedding::float4[])[1:5] AS first_5_values
FROM documents LIMIT 3;
```

<!-- pause -->

**What did we do?** Text → embeddings → PostgreSQL


<!-- end_slide -->

# Chapter 2: How Do We Compare Vectors?

**Now that we have embeddings stored, how do we find similar ones?**

<!-- pause -->

**We need distance functions!**

<!-- end_slide -->

# Three Distance Operators

| Operator | Name | Formula | Interpretation |
|----------|------|---------|----------------|
| `<->` | L2 (Euclidean) | √(Σ(a-b)²) | Lower = closer |
| `<=>` | Cosine | 1 - (a·b)/(‖a‖‖b‖) | Lower = more similar |
| `<#>` | Inner Product | -(a·b) | Lower = better aligned |

<!-- pause -->

**Simple analogies:**
- **L2:** Two people in a city - how many blocks apart?
- **Cosine:** Two people facing directions - how similar?
- **Inner Product:** Two arrows - how aligned?

<!-- pause -->

**Most common:** Cosine `<=>` (works best for embeddings)

<!-- end_slide -->

# Example: Finding Similar Documents

```sql
-- Find similar docs using cosine distance
SELECT 
  content,
  embedding <=> 
    (SELECT embedding FROM documents WHERE id = 1) 
  AS distance
FROM documents
ORDER BY distance
LIMIT 5;
```

<!-- pause -->

**Remember:** Lower distance = more similar!

<!-- end_slide -->

# Chapter 3: How Are Vectors Stored in Postgres?

**We know how to compare vectors, but where does Postgres actually store them?**

<!-- pause -->

**Let's explore step by step...**

<!-- end_slide -->

# Step 1: Create the Table

```sql


CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS docs (
    id serial PRIMARY KEY,
    content text,
    embedding vector(1536)
);
```

<!-- pause -->

**Note:** 1536 dimensions to demonstrate TOAST behavior (embeddings > 2KB)

<!-- end_slide -->

# Step 2: Load Demo Data

```bash
# Generate 50,000 documents with embeddings
python generate_demo_embeddings.py
```

<!-- pause -->

**This will:**
- Generate realistic random text using Faker
- Create 1536-dimensional embeddings (to demonstrate TOAST!)
- Insert 50k rows into `docs` table
- Takes ~10-15 minutes

<!-- pause -->

**Or use existing data if already loaded!**

<!-- end_slide -->

# Step 3: Inspect the Data

```sql
-- How many documents?
SELECT COUNT(*) FROM docs;
-- Expected: 50000

-- See sample content
SELECT id, content FROM docs LIMIT 3;

-- Check embedding size
SELECT 
    id, 
    content,
    pg_column_size(embedding) AS embedding_bytes,
    array_length(embedding::float4[], 1) AS dimensions
FROM docs LIMIT 3;
```

<!-- pause -->

**Expected:** ~6 KB per 1536-dim embedding

<!-- end_slide -->

# Step 4: Where Is the Data Stored?

```sql
-- Check storage breakdown
SELECT 
    pg_size_pretty(pg_relation_size('docs')) AS heap_size,
    pg_size_pretty(pg_total_relation_size('docs')) AS total_size;

-- Check TOAST table size
SELECT 
    pg_size_pretty(pg_relation_size(reltoastrelid)) AS toast_size
FROM pg_class 
WHERE relname = 'docs';
```

<!-- pause -->

**Expected results (50k docs with 1536d):**
- Heap size: ~100 MB (metadata, small values)
- TOAST size: ~300 MB (most embeddings here!)
- Total: ~400 MB

<!-- pause -->

**Key insight:** 1536d embeddings go to TOAST (> 2KB threshold) ✗

<!-- end_slide -->

# Chapter 4: What About Larger Embeddings?

**We saw TOAST in action with 1536d. But what if we used smaller embeddings?**

<!-- pause -->

**Let's compare different embedding sizes...**

<!-- column_layout: [1, 1] -->

<!-- column: 0 -->

**Our deep dive demo (50k docs, 1536d):**
```
Heap:  ███░░░░░░░░░ ~100 MB
TOAST: █████████░░░ ~300 MB
```
✗ Most embeddings in TOAST (demonstrates the problem!)

**If we used 384d instead:**
```
Heap:  ████████████ ~100 MB
TOAST: ░░░░░░░░░░░░  ~8 KB
```
✓ Embeddings stay in heap (much faster!)

<!-- column: 1 -->

**Why does this matter?**

TOAST = extra I/O
- Every query reads from 2 places
- More disk seeks
- Slower performance

<!-- pause -->

**Recommendation:**
Use smaller models when possible!
- 384d: MiniLM, E5-small
- 768d: MPNet, E5-base
- Avoid 1536d unless necessary

<!-- end_slide -->

# What is TOAST?

```
TOAST = "The Oversized-Attribute Storage Technique"
```

<!-- pause -->

**Analogy:**
```
Main table = Your desk
TOAST = Filing cabinet in another room

Small items (384d) → Stay on desk
Large items (1536d) → Go to filing cabinet
```

<!-- pause -->

**Impact:** TOAST = extra I/O on every read!

<!-- end_slide -->

# TOAST Storage Check

```sql
SELECT 
  pg_column_size(embedding) AS bytes,
  CASE 
    WHEN pg_column_size(embedding) > 2000 
    THEN 'TOASTed ✓' 
    ELSE 'Inline' 
  END AS storage
FROM docs LIMIT 1;
```

<!-- pause -->

**The Problem:**
- Postgres moves values > 2 KB to TOAST tables
- Our 1536d vectors = ~6 KB each
- **Result:** 80%+ of data in TOAST
- **Impact:** Extra I/O on every read

<!-- end_slide -->

# Chapter 5: The Baseline - Search Without Indexes

**Now we understand storage. Let's actually search for similar documents!**

<!-- pause -->

**First, let's see how it works WITHOUT any indexes...**

```sql
-- Find similar documents to doc #1
SELECT id, content,
       embedding <-> (
         SELECT embedding FROM docs WHERE id = 1
       ) AS distance
FROM docs
ORDER BY distance
LIMIT 5;
```

<!-- pause -->

**Notice:** Results are semantically similar! But how fast is it?

<!-- end_slide -->

# Chapter 6: The Problem - Sequential Scan Performance

**The search works, but is it fast? Let's measure...**

<!-- pause -->

```sql
EXPLAIN ANALYZE
SELECT id, content,
       embedding <-> (
         SELECT embedding FROM docs WHERE id = 1
       ) AS distance
FROM docs
ORDER BY distance
LIMIT 5;
```

<!-- end_slide -->

# The Problem

<!-- column_layout: [1, 1] -->

<!-- column: 0 -->

**Observe:**
- Seq Scan on docs
- Reads all 50,000 rows
- ~500-2000ms query time
- 300,000+ buffer reads (TOAST!)

<!-- column: 1 -->

**Without indexes:**
- Calculates distance for all 50k vectors
- Reads from TOAST for each
- O(N × dimensions) complexity

<!-- reset_layout -->

<!-- pause -->

**We need indexes! Like ANN (Approximate Nearest Neighbor)**

Why Approximate? Because exact search is too slow!


<!-- end_slide -->

# Chapter 7: IVFFlat Index

**Sequential scan is too slow. We need indexes!**

<!-- pause -->

**But how do you index high-dimensional vectors?**

<!-- pause -->

Let's understand search methods first...

<!-- end_slide -->

# IVFFlat - Inverted File Index with Flat Storage

**The name tells the story:**
- **Inverted File:** Like a book index - points to where things are
- **Flat:** Vectors stored as-is (no compression)

<!-- pause -->

**Let's see how different search methods work...**

<!-- end_slide -->

# Sequential Scan (Brute Force)

**Query:** "machine learning algorithms"

To find semantic documents similar to this query

```
SAMPLE DOCUMENTS
================
Doc1: "The cat sat on the mat"
Doc2: "Dogs are loyal pets"
Doc3: "Cats and dogs are animals"
Doc4: "Machine learning uses neural networks"
Doc5: "Deep learning is a subset of machine learning"
Doc6: "Neural networks process data"
┌─────────────────────────────────────┐
│ Scan EVERY document:                │
├─────────────────────────────────────┤
│ Doc1: "cat sat mat"           ✗     │
│ Doc2: "dogs loyal pets"       ✗     │
│ Doc3: "cats dogs animals"     ✗     │
│ Doc4: "machine learning..."   ✓     │
│ Doc5: "deep learning..."      ✓     │
│ Doc6: "neural networks..."    ✗     │
└─────────────────────────────────────┘
```

Checked: **6/6 docs (100%)**

<!-- pause -->

**Problem:** Must check EVERY document!

<!-- end_slide -->

# Inverted Index (TF-IDF)

**Analogy from Elasticsearch's TF-IDF:**

<!-- column_layout: [1, 1] -->

<!-- column: 0 -->

```
Pre-built index:
┌──────────────────────────────┐
│ "machine"  → [Doc4, Doc5]    │
│ "learning" → [Doc4, Doc5]    │
│ "neural"   → [Doc4, Doc6]    │
│ "cat"      → [Doc1, Doc3]    │
│ "dog"      → [Doc2, Doc3]    │
└──────────────────────────────┘
```

<!-- column: 1 -->

```
Query: "machine learning algorithms"
  ↓
Lookup: "machine" → [Doc4, Doc5]
Lookup: "learning" → [Doc4, Doc5]
Lookup: "algorithms" → []
  ↓
Intersect & rank: [Doc4, Doc5]
```

<!-- reset_layout -->

Checked: **2/6 docs (33%)**

<!-- end_slide -->

# IVFFlat (Vector Embeddings)

**How it works:**
1. Documents converted to vectors
2. K-means clustering groups similar vectors
3. Query searches only nearest cluster(s)

<!-- end_slide -->

# IVFFlat Clustering Visualization

![IVFFlat Clustering](images/ivfflat.png)

**Key insight:** Don't search everything, just search the right neighborhood!

<!-- end_slide -->

# IVFFlat Search Process

```
Query: "machine learning algorithms"
  → Embedding: [0.72, 0.82, 0.08]
  ↓
1. Find nearest centroid(s):
   Distance to A: 0.95  ✗
   Distance to B: 0.03  ✓ (nprobe=1)
  ↓
2. Scan ONLY Centroid B cluster:
   Doc4: distance 0.02  ✓
   Doc5: distance 0.04  ✓
   Doc6: distance 0.08  ✗
```

Checked: **3/6 docs (50%)**

<!-- end_slide -->

# Search Methods Summary

```
Sequential Scan:  Check everything
                  ████████████████████ 100%

TF-IDF:          Jump to exact matches
                  ████████░░░░░░░░░░░░ 33%

IVFFlat:         Jump to similar clusters
                  ██████████░░░░░░░░░░ 50%
                  (trades accuracy for speed)
```

<!-- end_slide -->

# Lets see IVFFlat Index in action

```sql
SET maintenance_work_mem = '256MB';

CREATE INDEX docs_ivfflat_idx 
ON docs USING ivfflat (embedding vector_l2_ops)
WITH (lists = 100);

ANALYZE docs;
```

<!-- pause -->

**How it works:**
- k-means clustering
- Creates 100 clusters (lists = sqrt(50k) ≈ 100)
- Query searches nearest cluster(s)

<!-- end_slide -->

# IVFFlat Performance

```sql
SET enable_seqscan = off;
SET ivfflat.probes = 1;

EXPLAIN (ANALYZE, BUFFERS)
SELECT id, content,
       embedding <-> (
         SELECT embedding FROM docs WHERE id = 1
       ) AS distance
FROM docs
ORDER BY distance
LIMIT 5;
```

<!-- pause -->

**Result:**
- Index Scan using docs_ivfflat_idx
- ~1-2ms (vs 100ms!)
- 241 buffers (vs 60,000!)
- **63x faster**

<!-- end_slide -->

# Chapter 8: HNSW Index

**IVFFlat is fast, but...**
- Can miss good results (lower recall)
- Depends on good clustering
- Needs tuning (probes parameter)

<!-- pause -->

**Can we do better? Enter HNSW!**

Hierarchical Navigable Small World

<!-- end_slide -->

# HNSW Graph Structure

![HNSW Graph Structure](images/hnsw.png)

<!-- end_slide -->

# HNSW: Key Differences

**Key differences from IVFFlat:**
- Hierarchical graph with multiple layers
- Navigates from sparse (top) to dense (bottom) layers
- Higher recall (~99% vs ~95%)
- More consistent performance

<!-- end_slide -->

# HNSW Search Process - Layer 2

Query: "machine learning algorithms" → [0.72, 0.82, 0.08]

```
Step 1: Enter at LAYER 2 (random entry point)
┌─────────────────────────────────────────┐
│ Layer 2:                                │
│                                         │
│     [START] Doc4 ═══════════ Doc5       │
│              ↓                          │
│         dist: 0.02                      │
│                                         │
│ Greedy search: Doc4 is closest          │
│ Check neighbor Doc5: 0.04 (worse)       │
│ → Stay at Doc4                          │
└─────────────────────────────────────────┘
```

<!-- end_slide -->

# HNSW Search Process - Layer 1

```
Step 2: Drop to LAYER 1 (from Doc4)
┌─────────────────────────────────────────┐
│ Layer 1:                                │
│                                         │
│   Doc1 ──── Doc3                        │
│                                         │
│   [Doc4] ──── Doc5 ──── Doc6            │
│     ↓          ↓         ↓              │
│   0.02       0.04      0.10             │
│                                         │
│ Check Doc4's neighbors: Doc5, Doc6      │
│ → Doc4 still closest                    │
└─────────────────────────────────────────┘
```

<!-- end_slide -->

# HNSW Search Process - Layer 0

```
Step 3: Drop to LAYER 0 (from Doc4)
┌─────────────────────────────────────────┐
│ Layer 0:                                │
│                                         │
│   Doc1 ──── Doc2 ──── Doc3              │
│     │                   │               │
│   [Doc4] ──── Doc5 ──── Doc6            │
│     ↓          ↓         ↓              │
│   0.02       0.04      0.10             │
│                                         │
│ Check all Doc4's neighbors              │
│ Expand to Doc5's neighbors              │
│ → Final: [Doc4, Doc5]                   │
└─────────────────────────────────────────┘
```

<!-- end_slide -->

# HNSW Path Visualization

```
Query [0.72, 0.82, 0.08]
  │
  │ Layer 2: Express Highway
  ├──→ Doc4 ══════════ Doc5
  │     ✓ (closest)
  │
  │ Layer 1: Main Roads  
  ├──→ Doc4 ──── Doc5 ──── Doc6
  │     ✓       check    check
  │
  │ Layer 0: All Streets
  └──→ Doc4 ──── Doc5 ──── Doc6
        ✓✓      ✓✓       ✗
```

**Analogy:** Like GPS navigation - use highways first, then local roads

<!-- end_slide -->

# Restaurant Analogy

<!-- column_layout: [1, 1] -->

<!-- column: 0 -->

**Sequential Scan:**
```
Walk every street, check every building
🚶 → 🏠 → 🏠 → 🏠 → 🏠 → 🏠 → 🍽️

"Is this Italian? No. 
 Is this Italian? No..."
Check ALL restaurants one by one
```

**TF-IDF:**
```
Look up in phone book
📖 "Italian" → [Addr1, Addr2, Addr3]
🚗 → 🍽️ (direct jump)

Only visit restaurants 
labeled "Italian"
```

<!-- column: 1 -->

**IVFFlat:**
```
Jump to right neighborhood
🚁 → [Downtown] → 🏠 → 🏠 → 🍽️

Fly to Italian district
Search every restaurant in area
(even non-Italian)
```

**HNSW:**
```
Highway → Avenue → Street
🛫 → 🚗 → 🚶 → 🍽️
(L2)  (L1)  (L0)

Start at landmark restaurant
Follow signs to closer ones
```

<!-- end_slide -->

# Create HNSW Index

```sql
DROP INDEX docs_ivfflat_idx;

CREATE INDEX docs_hnsw_idx 
ON docs USING hnsw (embedding vector_l2_ops)
WITH (m = 16, ef_construction = 200);
```

<!-- end_slide -->

# Performance Comparison

| Method   | Time  | Buffers | Speedup | Accuracy    |
|----------|-------|---------|---------|-------------|
| Seq Scan | 101ms | 60,205  | 1x      | Perfect     |
| IVFFlat  | 1.6ms | 241     | 63x     | Approximate |
| HNSW     | 1-2ms | ~200    | 70x     | High        |

<!-- pause -->

**Key:** 250x less I/O with indexes!

<!-- end_slide -->

# Chapter 9: Production Challenges

**HNSW gives us great performance, but what about updates?**

<!-- pause -->

**Let's talk about MVCC bloat...**

<!-- end_slide -->

# MVCC Bloat - The Problem

**What is MVCC?**
Multi-Version Concurrency Control - Postgres's way of handling concurrent transactions

<!-- pause -->

**How it works:**
- UPDATE doesn't modify rows in-place
- Creates a NEW version, marks OLD version as dead
- Old versions stay until VACUUM cleans them up

<!-- pause -->

**Why it matters for vectors:**
```
UPDATE docs SET metadata = '{"views": 100}' WHERE id = 1;
```
- Postgres copies the ENTIRE row (including 6KB embedding!)
- Old 6KB embedding becomes "dead tuple" in TOAST
- Do this 1000 times = 6 GB of dead data

<!-- pause -->

**Let's see it in action...**

<!-- end_slide -->

# MVCC Bloat - Demonstration

<!-- column_layout: [1, 1] -->

<!-- column: 0 -->

```sql
-- Check size BEFORE update
SELECT 
  pg_size_pretty(pg_total_relation_size('docs')) 
  AS total_size;
-- Expected: ~400 MB

-- Updates create dead tuples
UPDATE docs 
SET embedding = embedding 
WHERE id <= 5000;

-- Check size AFTER update
SELECT 
  pg_size_pretty(pg_total_relation_size('docs')) 
  AS total_size;
-- Expected: ~460 MB (10% of data updated!)
```

<!-- column: 1 -->

```sql
-- Check bloat details
SELECT 
  n_live_tup, 
  n_dead_tup,
  round(100.0 * n_dead_tup / 
    NULLIF(n_live_tup + n_dead_tup, 0), 1) 
    AS dead_pct
FROM pg_stat_user_tables 
WHERE relname = 'docs';

-- Expected:
-- live: 50000, dead: 5000, dead_pct: 10%

-- Clean up
VACUUM docs;

-- Check size after VACUUM
SELECT 
  pg_size_pretty(pg_total_relation_size('docs')) 
  AS total_size;
-- Back to ~400 MB
```

<!-- reset_layout -->

<!-- pause -->

**Problem:** Each update duplicates ~6KB in TOAST

<!-- end_slide -->

# Production Tips

**Now that we understand the challenges, how do we build production-ready systems?**

<!-- pause -->

**Let's go through 6 essential tips...**

<!-- end_slide -->

# Production Tips #1

**Separate embedding table**

**The Problem:** Updating document metadata duplicates 6KB embeddings!

```sql
CREATE TABLE documents (
  id serial, 
  title text,
  content text,
  metadata jsonb
);

CREATE TABLE embeddings (
  doc_id int REFERENCES documents(id),
  embedding vector(1536),
  content_hash text
);

-- Update metadata only
UPDATE documents 
SET metadata = '{"views": 100}' 
WHERE id = 1;
```
✅ No embedding duplication
✅ Less TOAST bloat
✅ Re-embed only when content changes

<!-- end_slide -->

# Production Tips #2-3

**We've separated tables. What about the embeddings themselves?**

<!-- column_layout: [1, 1] -->

<!-- column: 0 -->

**Use smaller models**

- 384d = 1.5 KB (stays inline!)
- 768d = 3 KB (TOASTed)
- 1536d = 6 KB (TOASTed)

**Smaller = less TOAST, faster queries**

<!-- column: 1 -->

**Increase maintenance_work_mem**

```sql
-- In postgresql.conf
maintenance_work_mem = 256MB
```

**Why:** Vector indexes need memory to build

<!-- end_slide -->

# Production Tips #4-5

**Smaller embeddings help, but what about indexing strategy?**

<!-- column_layout: [1, 1] -->

<!-- column: 0 -->

**Always ANALYZE after bulk inserts**

```sql
ANALYZE docs;
```

**Why:** IVFFlat needs statistics for clustering

<!-- column: 1 -->

**Create indexes AFTER bulk loading**

```sql
-- Bad: index exists during inserts
CREATE INDEX FIRST;
INSERT lots of data; -- Slow!

-- Good:
INSERT lots of data; -- Fast!
CREATE INDEX AFTER; -- One-time cost
```

<!-- pause -->

**Why?**
- **IVFFlat:** Incremental inserts can create poor clusters (local minima)
- **HNSW:** Each insert requires graph traversal and rebalancing (slow)

<!-- pause -->

**Best practice:** Bulk load first, then index!

<!-- end_slide -->

# Production Tips #6

**One more critical detail about vector queries...**

<!-- pause -->

**Use LIMIT for ANN - It's Different!**

<!-- column_layout: [1, 1] -->

<!-- column: 0 -->

**Classical SQL:**
```sql
-- LIMIT = "stop after N rows"
SELECT * FROM users 
ORDER BY created_at 
LIMIT 10;
```
1. Scan all rows
2. Sort all results
3. Return top 10

<!-- column: 1 -->

**Vector Search:**
```sql
-- LIMIT = "use ANN index!"
SELECT * FROM docs 
ORDER BY embedding <-> '[...]' 
LIMIT 10;
```

<!-- reset_layout -->

<!-- pause -->

| Method | The Analogy | How LIMIT Works |
|--------|-------------|-----------------|
| **Normal Query** (No Index) | **The Teacher:** Must grade every exam in the pile (1,000 papers), sort them all by score, then pick top 10 | **The Filter:** LIMIT applied at the end. Saves zero work - distance calculation happens for every row first |
| **IVFFlat** (Clusters) | **The Berry Picker:** Sweeps specific rows. Must check every berry in those rows, carries a small basket (10 berries) | **The Basket:** LIMIT restricts memory. Still reads thousands of items in selected clusters, keeps top 10 in RAM |
| **HNSW** (Graph) | **The Trick-or-Treater:** Runs house to house. Stops as soon as bag has 10 good pieces | **The Stop Sign:** LIMIT reduces computation. Algorithm stops searching graph early. Lower limit = fewer nodes visited |

<!-- end_slide -->

# When to Use What?

<!-- column_layout: [1, 1] -->

<!-- column: 0 -->

**Use IVFFlat when:**
- ✅ Batch/analytics workloads
- ✅ Can tolerate ~95% recall
- ✅ Faster index build needed
- ✅ Memory constrained (smaller index)
- ✅ Dataset changes frequently (rebuild is cheap)

**Example use cases:**
- Nightly batch similarity jobs
- Data exploration/analysis
- Development/testing environments

<!-- column: 1 -->

**Use HNSW when:**
- ✅ Low-latency queries required
- ✅ Need high recall (~99%)
- ✅ Production user-facing apps
- ✅ Stable dataset (infrequent rebuilds)
- ✅ Can afford larger index size

**Example use cases:**
- Real-time search APIs
- Recommendation systems
- Chatbot/RAG applications
- Production semantic search

<!-- reset_layout -->

<!-- pause -->

**TL;DR:** HNSW for production, IVFFlat for batch/dev

<!-- end_slide -->

# Key Takeaways

✅ Vectors > 2KB go to TOAST (extra I/O)

✅ ANN indexes give 50-100x speedup

✅ HNSW is best for production

✅ Smaller embeddings = better performance

✅ Separate tables for frequent updates

✅ Always use EXPLAIN ANALYZE

<!-- end_slide -->

# The End

**Postgres can handle semantic search at scale!**

Questions?

<!-- end_slide -->

# Appendix

IVFFlat & HNSW Build Process Details

<!-- end_slide -->

# IVFFlat Step 0: Raw Data

```
Doc1: "The cat sat on the mat"        → [0.1, 0.2, 0.9]
Doc2: "Dogs are loyal pets"           → [0.2, 0.3, 0.8]
Doc3: "Cats and dogs are animals"     → [0.15, 0.25, 0.85]
Doc4: "Machine learning neural nets"  → [0.7, 0.8, 0.1]
Doc5: "Deep learning subset"          → [0.75, 0.85, 0.05]
Doc6: "Neural networks process data"  → [0.65, 0.75, 0.15]
```

⚠️  **CRITICAL:** Must load ALL vectors into memory first!

<!-- end_slide -->

# IVFFlat Step 1: Initialize Centroids

Randomly pick K=2 initial centroids:

```
Vector Space (2D projection):
    1.0 │
        │  ●Doc1
    0.8 │  ●Doc2              ●Doc5
        │   ●Doc3            ●Doc4
    0.6 │                   ●Doc6
        │
    0.4 │  C1 (random)
        │
    0.2 │              C2 (random)
        │
    0.0 └─────────────────────────────
        0.0   0.2   0.4   0.6   0.8

Initial Centroids:
  C1 = [0.2, 0.3, 0.8]  (random pick)
  C2 = [0.7, 0.8, 0.1]  (random pick)
```

<!-- end_slide -->

# IVFFlat Step 2: Assign to Clusters (1/2)

Calculate distance from each vector to each centroid:

```
Doc1 [0.1, 0.2, 0.9]:
  → distance to C1: 0.14  ✓ (closer)
  → distance to C2: 0.95
  → Assign to Cluster 1

Doc2 [0.2, 0.3, 0.8]:
  → distance to C1: 0.00  ✓ (exact match!)
  → distance to C2: 0.85
  → Assign to Cluster 1

Doc3 [0.15, 0.25, 0.85]:
  → distance to C1: 0.08  ✓
  → distance to C2: 0.90
  → Assign to Cluster 1
```

<!-- end_slide -->

# IVFFlat Step 2: Assign to Clusters (2/2)

```
Doc4 [0.7, 0.8, 0.1]:
  → distance to C1: 0.85
  → distance to C2: 0.00  ✓ (exact match!)
  → Assign to Cluster 2

Doc5 [0.75, 0.85, 0.05]:
  → distance to C1: 0.92
  → distance to C2: 0.08  ✓
  → Assign to Cluster 2

Doc6 [0.65, 0.75, 0.15]:
  → distance to C1: 0.78
  → distance to C2: 0.08  ✓
  → Assign to Cluster 2
```

<!-- end_slide -->

# IVFFlat Voronoi Diagram

```
Voronoi Diagram (Iteration 1):
    1.0 │
        │  ●Doc1
    0.8 │  ●Doc2              ●Doc5
        │   ●Doc3            ●Doc4
    0.6 │                   ●Doc6
        │  ╔═══════╗ ║ ╔═══════╗
    0.4 │  ║   C1  ║ ║ ║   C2  ║
        │  ║Cluster║ ║ ║Cluster║
    0.2 │  ║   1   ║ ║ ║   2   ║
        │  ╚═══════╝ ║ ╚═══════╝
    0.0 └──────────────────────────
              BOUNDARY
```

<!-- end_slide -->

# IVFFlat Step 3: Recalculate Centroids

```
Cluster 1: [Doc1, Doc2, Doc3]
  New C1 = mean([0.1, 0.2, 0.9], 
                [0.2, 0.3, 0.8], 
                [0.15, 0.25, 0.85])
  New C1 = [0.15, 0.25, 0.85]  ← MOVED!

Cluster 2: [Doc4, Doc5, Doc6]
  New C2 = mean([0.7, 0.8, 0.1], 
                [0.75, 0.85, 0.05], 
                [0.65, 0.75, 0.15])
  New C2 = [0.70, 0.80, 0.10]  ← MOVED!
```

<!-- end_slide -->

# IVFFlat Centroids Moved

```
    1.0 │
        │  ●Doc1
    0.8 │  ●Doc2              ●Doc5
        │   ●Doc3  ⭐C1      ●Doc4  ⭐C2
    0.6 │                   ●Doc6
        │
        │  (Centroids moved to cluster centers)
```

<!-- end_slide -->

# IVFFlat Step 4: Iterate Until Convergence

```
Repeat Steps 2-3 until centroids stop moving:

Iteration 2:
  - Recalculate distances
  - Reassign vectors
  - Update centroids
  
Iteration 3:
  - Recalculate distances
  - Reassign vectors
  - Update centroids

... CONVERGED! (centroids don't move)
```

<!-- end_slide -->

# IVFFlat Final Structure

```
┌─────────────────────────────────────┐
│ Centroid 1: [0.15, 0.25, 0.85]      │
│   ├─ Doc1 [0.1, 0.2, 0.9]           │
│   ├─ Doc2 [0.2, 0.3, 0.8]           │
│   └─ Doc3 [0.15, 0.25, 0.85]        │
│                                     │
│ Centroid 2: [0.70, 0.80, 0.10]      │
│   ├─ Doc4 [0.7, 0.8, 0.1]           │
│   ├─ Doc5 [0.75, 0.85, 0.05]        │
│   └─ Doc6 [0.65, 0.75, 0.15]        │
└─────────────────────────────────────┘
```

<!-- end_slide -->

# HNSW Step 0: Start Empty

```
Doc1: "The cat sat on the mat"        → [0.1, 0.2, 0.9]
Doc2: "Dogs are loyal pets"           → [0.2, 0.3, 0.8]
Doc3: "Cats and dogs are animals"     → [0.15, 0.25, 0.85]
Doc4: "Machine learning neural nets"  → [0.7, 0.8, 0.1]
Doc5: "Deep learning subset"          → [0.75, 0.85, 0.05]
Doc6: "Neural networks process data"  → [0.65, 0.75, 0.15]
```

✓ NO need to load all data at once!
✓ Can insert one vector at a time

<!-- end_slide -->

# HNSW Parameters

```
M = 2        (max connections per layer)
efConstruction = 3  (search width during build)
mL = 1/ln(2) (layer probability multiplier)
```

<!-- end_slide -->

# HNSW Insert Doc1

```
Step 1: Determine max layer
  Random: level = floor(-ln(random()) × mL) = 2

Step 2: Insert into all layers (0 to 2)

Layer 2:
  [Doc1]  ← First node, no connections

Layer 1:
  [Doc1]  ← First node, no connections

Layer 0:
  [Doc1]  ← First node, no connections

Current Index:
┌─────────────────────┐
│ Layer 2: Doc1       │
│          │          │
│ Layer 1: Doc1       │
│          │          │
│ Layer 0: Doc1       │
└─────────────────────┘
```

<!-- end_slide -->

# HNSW Insert Doc2

```
Step 1: Determine max layer
  Random: level = 0 (most nodes go to layer 0 only)

Step 2: Search for nearest neighbors
  Start at top layer with entry point Doc1
  
  Layer 2: Doc1 (entry point, skip - Doc2 not here)
  Layer 1: Doc1 (skip - Doc2 not here)
  Layer 0: Find nearest to Doc2
    → Doc1 distance: 0.14

Step 3: Connect Doc2 to M=2 nearest neighbors
  Layer 0: Doc2 ←→ Doc1
```

<!-- end_slide -->

# HNSW After Doc2

```
Current Index:
┌─────────────────────┐
│ Layer 2: Doc1       │
│          │          │
│ Layer 1: Doc1       │
│          │          │
│ Layer 0: Doc1 ←→ Doc2│
└─────────────────────┘
```

<!-- end_slide -->

# HNSW Layer Assignment

```
Each node gets random layer based on exponential decay:

Layer 0: ████████████████████ 100% (all nodes)
Layer 1: ████████░░░░░░░░░░░░  50% (half)
Layer 2: ████░░░░░░░░░░░░░░░░  25% (quarter)
Layer 3: ██░░░░░░░░░░░░░░░░░░  12.5%
Layer 4: █░░░░░░░░░░░░░░░░░░░   6.25%

Formula: P(layer ≥ L) = (1/2)^L
```

Creates a skip-list structure!

<!-- end_slide -->

# HNSW Final Structure

```
┌──────────────────────────────┐
│ Layer 2: Doc1 ═══════ Doc4   │
│          ║           ║       │
│ Layer 1: Doc1 ──── Doc3      │
│          ║           ║       │
│         Doc4 ──── Doc6       │
│          ║           ║       │
│ Layer 0: Doc1 ──── Doc2      │
│          │ ╲       │         │
│         Doc3 ──────┘         │
│                              │
│         Doc4 ──── Doc5       │
│          │ ╲       │         │
│         Doc6 ──────┘         │
└──────────────────────────────┘
```

<!-- end_slide -->

# HNSW Connection Rules

**During insertion:**

1. **Search Phase:**
   - Start at top layer
   - Greedy search: move to closer neighbor
   - Drop layer when stuck

2. **Connection Phase:**
   - Find M nearest neighbors
   - Connect to them
   - Prune to maintain M max

<!-- end_slide -->

# HNSW Incremental Build

```
Insert Order: Doc1 → Doc2 → Doc3 → Doc4 → Doc5 → Doc6

After Doc1:
  [Doc1]

After Doc2:
  [Doc1]──[Doc2]

After Doc3:
  [Doc1]──[Doc2]
    ╲      ╱
     [Doc3]

After Doc4 (new cluster!):
  [Doc1]──[Doc2]    [Doc4]
    ╲      ╱
     [Doc3]

After Doc5:
  [Doc1]──[Doc2]    [Doc4]──[Doc5]
    ╲      ╱
     [Doc3]

After Doc6:
  [Doc1]──[Doc2]    [Doc4]──[Doc5]
    ╲      ╱          ╲      ╱
     [Doc3]            [Doc6]
```

<!-- end_slide -->

<!-- end_slide -->

# HNSW Tuning

<!-- column_layout: [1, 1] -->

<!-- column: 0 -->

```sql
-- Higher ef_search = 
-- better recall, slower

SET hnsw.ef_search = 40;  
-- Good default

SET hnsw.ef_search = 100; 
-- Higher accuracy
```

<!-- column: 1 -->

**Build parameters:**
- `m = 16` 
  max connections per node
- `ef_construction = 200` 
  build quality


