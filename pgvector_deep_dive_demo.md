# pgvector Deep Dive Demo: From Sequential Scans to ANN Indexes

Hands-on SQL walkthrough of PostgreSQL vector search performance, from brute force to optimized ANN indexes.

## Prerequisites

- PostgreSQL with pgvector extension installed
- Database configured in `.env` file
- Demo data generated (see Step 3)

---

## 🔥 Section 1 — Setup: Enable pgvector & Load Data

**Goal**: Set up pgvector and load 50,000 documents with 1024-dimensional embeddings to demonstrate TOAST behavior and performance.

### Step 1: Enable pgvector extension

```sql
-- Enable the pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Verify installation
SELECT extname, extversion
FROM pg_extension 
WHERE extname = 'vector';

-- Check available vector operators
SELECT oprname AS operator, oprcode AS function
FROM pg_operator
WHERE oprname IN ('<->', '<=>', '<#>')
ORDER BY oprname;
```

**What we get**:
- `<->` = L2 distance (Euclidean)
- `<=>` = Cosine distance  
- `<#>` = Inner product

**When to use each metric:**

| Metric | Operator | Use When | Example Use Case |
|--------|----------|----------|------------------|
| L2 (Euclidean) | `<->` | Absolute distance matters | Image embeddings, spatial data |
| Cosine | `<=>` | Direction matters (most common) | Text embeddings, normalized vectors |
| Inner Product | `<#>` | Pre-normalized vectors | Optimized text search, dot product similarity |

**Important**: Lower distance = more similar for all metrics!

### Step 2: Create table with vector type

```sql
-- Create table with native vector type
CREATE TABLE docs (
    id serial PRIMARY KEY,
    content text,
    embedding vector(1024)
);
```

**Key point**: `vector(1024)` enables optimized storage, distance operators, and ANN index support.

### Step 3: Load 50,000 documents with embeddings

```bash
python scripts/generate_demo_embeddings.py
```

This will:
- Generate 50,000 documents with diverse content
- Create 1024-dimensional embeddings (padded from BGE model)
- Takes ~10-15 minutes

### Step 4: Verify data and check storage

```sql
-- Check row count
SELECT COUNT(*) FROM docs;

-- Sample documents
SELECT 
    id, 
    content,
    (embedding::float4[])[1:5] AS first_5_dims,
    pg_column_size(embedding) AS embedding_bytes
FROM docs 
LIMIT 5;

-- Check total table size
SELECT 
    pg_size_pretty(pg_total_relation_size('docs')) AS total_size,
    pg_size_pretty(pg_relation_size('docs')) AS heap_size,
    pg_size_pretty(pg_total_relation_size('docs') - pg_relation_size('docs')) AS toast_indexes_size;
```

**Storage facts**:
- Our 1024-dim vector(1024) = ~4 KB per row (goes to TOAST!)
- TOAST threshold: ~2 KB
- 50k × 1024d ≈ 200 MB of embeddings
- Most data will be in TOAST tables (out-of-line storage)

---

## 🐌 Section 2 — Baseline: Sequential Scan (No Index)

**Goal**: Show how expensive semantic search is WITHOUT indexes - every query scans all 50k rows plus TOAST overhead.

**⚠️ CRITICAL: Always use LIMIT with vector queries!**

```sql
-- BAD: No LIMIT = Postgres won't use ANN indexes (even if they exist!)
SELECT * FROM docs ORDER BY embedding <-> '[...]';

-- GOOD: LIMIT tells Postgres to use ANN index
SELECT * FROM docs ORDER BY embedding <-> '[...]' LIMIT 10;
```

**Why this matters**: Without LIMIT, Postgres must sort ALL results, so it can't use approximate indexes. LIMIT enables the query planner to use ANN indexes for top-K search.

### Step 1: First, see what content we have

```sql
-- Look at a sample document
SELECT id, content FROM docs WHERE id = 1;

-- Find documents about a specific topic (e.g., "artificial intelligence")
SELECT id, content 
FROM docs 
WHERE content ILIKE '%artificial intelligence%' 
LIMIT 3;
```

### Step 2: Run similarity search without any index

```sql
-- Search for documents similar to document #1
-- This will do a FULL TABLE SCAN
EXPLAIN ANALYZE
SELECT 
    id,
    content,
    embedding <-> (SELECT embedding FROM docs WHERE id = 1) AS distance
FROM docs
ORDER BY embedding <-> (SELECT embedding FROM docs WHERE id = 1)
LIMIT 5;
```

**Expected Observation**:
- ✅ **Seq Scan** on docs
- ✅ Every row read (all 50,000 rows)
- ✅ TOAST tables accessed for each embedding (extra I/O!)
- ✅ Distance calculated for every single row
- ✅ Query time: **500ms - 2000ms+**
- ✅ Cost: thousands
- ✅ Buffers: many pages read from heap + TOAST

### Step 3: See the semantic similarity in action

```sql
-- Get the content of document #1 first
SELECT id, content FROM docs WHERE id = 1;

-- Now find similar documents (without EXPLAIN to see actual results)
SELECT 
    id,
    content,
    embedding <-> (SELECT embedding FROM docs WHERE id = 1) AS distance
FROM docs
ORDER BY embedding <-> (SELECT embedding FROM docs WHERE id = 1)
LIMIT 10;
```

**Notice**: The results are semantically similar even if they use different words! This is the power of embeddings.

### Step 4: Try searching by content topic

```sql
-- Find a document about a specific topic
SELECT id, content 
FROM docs 
WHERE content ILIKE '%machine learning%' 
LIMIT 1;

-- Let's say it returns id = 42, now search for similar documents
SELECT 
    id,
    content,
    embedding <-> (SELECT embedding FROM docs WHERE id = 94) AS distance
FROM docs
WHERE content != (SELECT content FROM docs WHERE id = 94)
ORDER BY embedding <-> (SELECT embedding FROM docs WHERE id = 94)
LIMIT 10;
```

**Observe**: You'll get documents about AI, technology, data science - semantically related topics!

### Step 5: Performance check with EXPLAIN

```sql
-- Same query but with EXPLAIN to see the execution plan
EXPLAIN ANALYZE
SELECT 
    id,
    content,
    embedding <-> (SELECT embedding FROM docs WHERE id = 42) AS distance
FROM docs
ORDER BY embedding <-> (SELECT embedding FROM docs WHERE id = 42)
LIMIT 10;
```

**Same result**: Sequential scan, slow performance (~500ms+).

### Step 6: Test different distance metrics

```sql
-- L2 distance (Euclidean) - measures absolute distance
SELECT id, content, embedding <-> (SELECT embedding FROM docs WHERE id = 1) AS l2_dist
FROM docs ORDER BY embedding <-> (SELECT embedding FROM docs WHERE id = 1) LIMIT 5;

-- Cosine distance (most common for embeddings) - measures angle/direction
SELECT id, content, embedding <=> (SELECT embedding FROM docs WHERE id = 1) AS cosine_dist
FROM docs ORDER BY embedding <=> (SELECT embedding FROM docs WHERE id = 1) LIMIT 5;

-- Inner product - for normalized vectors
SELECT id, content, embedding <#> (SELECT embedding FROM docs WHERE id = 1) AS ip_dist
FROM docs ORDER BY embedding <#> (SELECT embedding FROM docs WHERE id = 1) LIMIT 5;
```

**Compare the results**: Different metrics may return slightly different rankings, but all are semantically similar!

**Performance check**:
```sql
-- All three use sequential scans without indexes
EXPLAIN ANALYZE
SELECT id, content, embedding <=> (SELECT embedding FROM docs WHERE id = 1) AS cosine_dist
FROM docs ORDER BY embedding <=> (SELECT embedding FROM docs WHERE id = 1) LIMIT 5;
```

**All use sequential scans** - no index to help yet!

**Takeaway**: *"Without indexes, Postgres must scan every row and calculate distance for each. This is O(N × dim) complexity. Now let's fix this with ANN indexes."*

---

## 🏗 Section 3 — Understanding Storage: varlena, TOAST, and Vector Size Impact

**Goal**: Understand how Postgres stores vectors and why size matters.

**Key finding**: Our 1024d vectors (~4 KB) go to TOAST, demonstrating the I/O overhead of large embeddings. This is realistic for BGE-large and similar models.

### Demonstrate TOAST behavior

```sql
-- Check TOAST usage for our docs table
SELECT
    c.relname AS table_name,
    pg_size_pretty(pg_relation_size(c.oid)) AS heap_size,
    pg_size_pretty(pg_relation_size(c.reltoastrelid)) AS toast_size,
    pg_size_pretty(pg_total_relation_size(c.oid)) AS total_size,
    round(100.0 * pg_relation_size(c.reltoastrelid) / 
          NULLIF(pg_total_relation_size(c.oid), 0), 1) AS toast_pct
FROM pg_class c
WHERE c.relname = 'docs';
```

**What you'll see**:
- Heap size: ~50-60 MB (just row headers and small data)
- TOAST size: ~180-200 MB (most embedding data is here!)
- TOAST percentage: ~75-80% of total data
- **Why?** 1024-dim vectors (~4 KB) exceed the 2 KB TOAST threshold



**Another view - See actual TOAST table name**:
```sql
-- See TOAST table name and details
SELECT 
    t.relname AS toast_table,
    pg_size_pretty(pg_relation_size(t.oid)) AS toast_size,
    (SELECT relname FROM pg_class WHERE oid = c.oid) AS main_table
FROM pg_class c
JOIN pg_class t ON c.reltoastrelid = t.oid
WHERE c.relname = 'docs';
```

**TOAST threshold**: Postgres moves data to TOAST when:
- Single value > ~2 KB (after compression attempt)
- Row size approaches page size (8 KB)

### Verify TOAST is being used

```sql
-- Check if our vectors are TOASTed
SELECT 
    pg_column_size(embedding) AS bytes_1024d,
    CASE 
        WHEN pg_column_size(embedding) > 2000 THEN 'TOASTed ✓'
        ELSE 'Inline'
    END AS storage_location
FROM docs 
LIMIT 1;

-- Compare different sizes:
-- 384d  ≈ 1.5 KB → Stays inline
-- 768d  ≈ 3 KB   → TOASTed
-- 1024d ≈ 4 KB   → TOASTed ✓ (our demo)
-- 1536d ≈ 6 KB   → TOASTed
-- 3072d ≈ 12 KB  → TOASTed
```

**Key insight**: Our 1024d embeddings are TOASTed, so we'll see the I/O overhead in action. This is realistic for BGE-large embeddings!

### Show impact of updates (MVCC bloat)

```sql
-- Check current size
SELECT pg_size_pretty(pg_total_relation_size('docs')) AS size_before;

-- Update 5,000 embeddings (creates new row versions due to MVCC)
UPDATE docs 
SET embedding = embedding 
WHERE id <= 5000;

-- Check size after updates
SELECT pg_size_pretty(pg_total_relation_size('docs')) AS size_after;

-- See dead tuples
SELECT 
    n_live_tup AS live_rows,
    n_dead_tup AS dead_rows,
    round(100.0 * n_dead_tup / NULLIF(n_live_tup + n_dead_tup, 0), 2) AS dead_pct
FROM pg_stat_user_tables
WHERE relname = 'docs';
```

**What you'll observe**:
- Size increases from ~250 MB to ~275 MB (10% of data updated)
- Dead tuples: 5,000 (the old versions are marked dead but not removed)
- Dead percentage: ~9% of total rows
- **Key point**: Dead tuples waste space and slow down scans!

```sql
-- Clean up dead tuples (marks space as reusable)
VACUUM docs;

-- Check dead tuples after VACUUM
SELECT 
    n_live_tup AS live_rows,
    n_dead_tup AS dead_rows
FROM pg_stat_user_tables 
WHERE relname = 'docs';

-- Size may not shrink much with regular VACUUM
SELECT pg_size_pretty(pg_total_relation_size('docs')) AS size_after_vacuum;

-- For aggressive cleanup (locks table, actually reclaims disk space):
VACUUM FULL docs;

-- Now check size - should be smaller
SELECT pg_size_pretty(pg_total_relation_size('docs')) AS size_after_full_vacuum;
```

**Alternative view - Main table vs TOAST breakdown**:
```sql
-- Clear breakdown of main table vs TOAST + indexes
SELECT
    relname AS table_name,
    pg_size_pretty(pg_relation_size(C.oid)) AS main_table_size,
    pg_size_pretty(pg_total_relation_size(C.oid) - pg_relation_size(C.oid)) AS toast_and_index_size,
    pg_size_pretty(pg_total_relation_size(C.oid)) AS total_size
FROM pg_class C
LEFT JOIN pg_namespace N ON (N.oid = C.relnamespace)
WHERE nspname NOT IN ('pg_catalog', 'information_schema')
    AND relname = 'docs';
```

**Takeaway**: 
- Updates create dead tuples (MVCC)
- Dead tuples waste space and slow sequential scans
- Regular VACUUM marks space as reusable (doesn't shrink file)
- VACUUM FULL actually reclaims disk space (but locks table)
- With TOASTed vectors, each update duplicates ~6KB in TOAST
- Consider separate embedding table if you update content frequently

---

## 🚀 Section 4 — ANN Index 1: IVFFlat Mechanism

**Key Concept**: IVFFlat creates clusters of vector space using k-means. Query searches nearest cluster(s). Fast but approximate.

**Important note**: With only 10k rows, Postgres may prefer sequential scans over the index. This is actually correct behavior - for small datasets, brute force can be faster! In production with 100k+ rows, indexes become essential. For this demo, we'll use `SET enable_seqscan = off` to force index usage and see how it works.

### Step 1: Create IVFFlat index

```sql
-- First, increase maintenance_work_mem for index creation
-- IVFFlat needs memory for k-means clustering
SET maintenance_work_mem = '512MB';

-- Create IVFFlat index with 200 lists (clusters)
-- Rule of thumb: lists = sqrt(rows) (for 50k rows, sqrt(50000) ≈ 224, using 200)
CREATE INDEX docs_ivfflat_idx 
ON docs 
USING ivfflat (embedding vector_l2_ops)
WITH (lists = 200);
```

**If you get "memory required" error:**
```sql
-- Error: memory required exceeds maintenance_work_mem
-- Solution: Increase maintenance_work_mem temporarily
SET maintenance_work_mem = '512MB';

-- Or use fewer lists (less memory needed)
CREATE INDEX docs_ivfflat_idx 
ON docs 
USING ivfflat (embedding vector_l2_ops)
WITH (lists = 100);
```

**Why this happens:**
- IVFFlat uses k-means clustering during index creation
- Needs to load vectors into memory for clustering
- 1024-dim vectors × 50k rows = significant memory
- `maintenance_work_mem` controls memory for index operations
- Default is often 64MB, but vector indexes need more

-- Check index size
SELECT 
    indexrelname AS index_name,
    pg_size_pretty(pg_relation_size(indexrelid)) AS index_size
FROM pg_stat_user_indexes
WHERE indexrelname = 'docs_ivfflat_idx';
```

### Step 2: Analyze the table (REQUIRED for IVFFlat)

```sql
-- IVFFlat needs statistics to work properly
ANALYZE docs;
```

**What ANALYZE does (core PostgreSQL command):**
- Collects statistics about table data distribution
- Updates `pg_statistics` system catalog
- Used by query planner to choose optimal execution plans
- Samples rows to understand data patterns
- **Not specific to pgvector** - works for all data types

**Why IVFFlat specifically needs ANALYZE:**
- IVFFlat uses k-means clustering during index creation
- It needs to sample the data to find good cluster centroids
- Relies on PostgreSQL's statistics to efficiently sample vectors
- Without ANALYZE, clustering quality suffers → poor query performance
- **Always run ANALYZE after bulk inserts before creating IVFFlat index**

**Note**: HNSW doesn't require ANALYZE because it builds the graph structure directly from the actual data without needing statistical sampling.

### Step 3: Run a query with IVFFlat

```sql
-- Search with IVFFlat (using document #1 as query)
EXPLAIN ANALYZE
SELECT 
    id, 
    content,
    embedding <-> (SELECT embedding FROM docs WHERE id = 1) AS distance
FROM docs
ORDER BY embedding <-> (SELECT embedding FROM docs WHERE id = 1)
LIMIT 5;
```

**What you'll likely see:**
- Seq Scan on docs (500-2000ms execution time)
- Postgres may choose brute force for small result sets

**Force index usage to see the difference:**

```sql
-- Disable sequential scans temporarily to force index usage
SET enable_seqscan = off;

-- Now try the query again
EXPLAIN ANALYZE
SELECT 
    id, 
    content,
    embedding <-> (SELECT embedding FROM docs WHERE id = 1) AS distance
FROM docs
ORDER BY embedding <-> (SELECT embedding FROM docs WHERE id = 1)
LIMIT 5;
```

**Now observe:**
- ✅ **Index Scan using docs_ivfflat_idx**
- ✅ Execution time: **~10-20ms** (vs 500-2000ms with seq scan!)
- ✅ Order By: (embedding <-> $0) - using index for ordering
- ✅ **50-100x faster** with the index!

**Understanding the plan:**
- `rows=50000` is the planner's estimate (not actual rows scanned)
- `actual ... rows=5` shows only 5 rows returned (due to LIMIT)
- IVFFlat scans only the nearest cluster(s), not all 50k rows
- With `probes=1` (default), it checks ~250 rows (50k/200 lists = 250 per list)
- The speedup comes from checking fewer vectors

```sql
-- See more detailed statistics with BUFFERS
EXPLAIN (ANALYZE, BUFFERS)
SELECT 
    id, 
    content,
    embedding <-> (SELECT embedding FROM docs WHERE id = 1) AS distance
FROM docs
ORDER BY embedding <-> (SELECT embedding FROM docs WHERE id = 1)
LIMIT 5;

-- Re-enable sequential scans
SET enable_seqscan = on;
```

**Compare the I/O (this is the key insight!):**

| Method | Execution Time | Shared Buffers Hit | Speedup |
|--------|---------------|-------------------|---------|
| Sequential Scan | ~500-2000ms | ~300,000 blocks | baseline |
| IVFFlat Index | ~10-20ms | ~1,000 blocks | **50-100x faster!** |

**What this shows:**
- Seq scan reads **~300,000 blocks** (all TOAST data for all 50k vectors)
- IVFFlat reads only **~1,000 blocks** (just the nearest cluster)
- **300x less I/O** with the index!
- This is the power of ANN indexes - avoid reading unnecessary data
- Each block is 8KB, so seq scan = ~2.3 GB vs IVFFlat = ~8 MB of data read

**Note on timing variability:**
- First query run is often slower (cold cache - loading from disk)
- Subsequent runs are faster (warm cache - data in shared_buffers)
- The buffer hit counts show data was in cache (not physical reads)
- Production systems typically have warm caches

**Why seq scan might be chosen initially:**
- For very small result sets (LIMIT 5), Postgres may calculate seq scan cost as competitive
- IVFFlat has overhead (probing lists, checking centroids)
- With 50k+ rows, index is usually chosen automatically for larger result sets
- This demonstrates Postgres's smart query planning!

### Step 4: Tune IVFFlat probes (if index is being used)

```sql
-- Default probes = 1 (searches 1 cluster)
-- Increase for better recall at cost of speed
SET ivfflat.probes = 10;

-- Disable seq scan to see the effect
SET enable_seqscan = off;

-- Re-run query
EXPLAIN ANALYZE
SELECT 
    id, 
    content,
    embedding <-> (SELECT embedding FROM docs WHERE id = 1) AS distance
FROM docs
ORDER BY embedding <-> (SELECT embedding FROM docs WHERE id = 1)
LIMIT 5;

-- Try different probe values to see the trade-off
SET ivfflat.probes = 3;
EXPLAIN ANALYZE
SELECT id, content, embedding <-> (SELECT embedding FROM docs WHERE id = 1) AS distance
FROM docs ORDER BY embedding <-> (SELECT embedding FROM docs WHERE id = 1) LIMIT 5;

-- Reset
SET enable_seqscan = on;
SET ivfflat.probes = 1;
```

**IVFFlat Probes Comparison:**

| Probes | Clusters Searched | Execution Time | vs Seq Scan | Accuracy |
|--------|------------------|----------------|-------------|----------|
| 1 | 1/200 (0.5%) | ~10-20ms | **50-100x faster** | Lower (may miss neighbors) |
| 3 | 3/200 (1.5%) | ~30-50ms | ~20-40x faster | Better |
| 10 | 10/200 (5%) | ~100-200ms | ~5-10x faster | Higher |
| 20 | 20/200 (10%) | ~300-500ms | ~2-4x faster | Very High |
| - | Sequential Scan | ~500-2000ms | baseline | Perfect (checks all) |

**Recommendation**: Use probes=1-3 for production. Only increase if you need higher accuracy and can accept slower queries.

**Note**: To measure actual recall, you'd need to compare results against sequential scan (ground truth) and calculate what percentage of true nearest neighbors were found.

**Observe the trade-off:**
- `probes = 1`: ~10-20ms execution time (searches 1 cluster)
- `probes = 10`: ~100-200ms execution time (searches 10 clusters)
- **10x slower** but checks more candidates!

**Probes parameter explained:**
- `probes = 1`: Search only the nearest cluster (fastest)
- `probes = 10`: Search 10 nearest clusters (slower, more thorough)
- More probes = more vectors checked = slower but higher chance of finding true nearest neighbors
- With 200 lists total, probes=10 checks ~5% of all data
- Trade-off between speed and accuracy
- Typical production values: 1-5 for speed, 10-20 for accuracy

**Key insight**: Even with probes=10 (100-200ms), it's still 5-10x faster than seq scan (500-2000ms), but the sweet spot is probes=1-3 for most use cases.

**Takeaway**: *"IVFFlat is fast and approximate. It can miss good neighbors if your centroids are bad or lists are small. Great for batch workloads."*

---

## 🚀 Section 5 — ANN Index 2: HNSW (Hierarchical Navigable Small World Graph)

**Goal**: Demonstrate HNSW - the gold standard for high-recall, low-latency vector search.

**Key Concept**:
- Nodes = vector points
- Edges = "neighbor links"
- Navigable graph with hierarchical layers
- Search descends from upper sparse layer to lower dense layer
- High recall, excellent performance
- More expensive to build than IVFFlat

### Step 1: Create HNSW index

```sql
-- Drop IVFFlat to compare fairly
DROP INDEX IF EXISTS docs_ivfflat_idx;

-- Ensure enough memory for index creation
SET maintenance_work_mem = '512MB';

-- Time the index build
\timing on

-- Create HNSW index
-- m = max connections per node (16 is good default)
-- ef_construction = size of dynamic candidate list (higher = better quality, slower build)
CREATE INDEX docs_hnsw_idx 
ON docs 
USING hnsw (embedding vector_l2_ops)
WITH (m = 16, ef_construction = 200);

\timing off
-- Expected build time: 2-5 minutes for 50k rows with 1024d

-- Check index size (HNSW is typically larger)
SELECT 
    indexrelname AS index_name,
    pg_size_pretty(pg_relation_size(indexrelid)) AS index_size
FROM pg_stat_user_indexes
WHERE indexrelname = 'docs_hnsw_idx';
```

**Index Build Time Comparison (50k rows, 1024d):**

| Index Type | Build Time | Index Size | Memory Required |
|------------|------------|------------|-----------------|
| IVFFlat (lists=200) | ~30-60 seconds | ~20-30 MB | 512 MB |
| HNSW (m=16, ef=200) | ~2-5 minutes | ~50-80 MB | 512 MB |

**Trade-off**: HNSW takes longer to build but provides better query performance and recall.

### Step 2: Run a query with HNSW

```sql
-- Set search quality parameter
-- ef_search = size of dynamic candidate list during search
-- Higher = better accuracy, slower search
SET hnsw.ef_search = 40;

-- First query (cold cache)
EXPLAIN ANALYZE
SELECT 
    id, 
    content,
    embedding <-> (SELECT embedding FROM docs WHERE id = 1) AS distance
FROM docs
ORDER BY embedding <-> (SELECT embedding FROM docs WHERE id = 1)
LIMIT 5;

-- Run the same query again (warm cache)
EXPLAIN ANALYZE
SELECT 
    id, 
    content,
    embedding <-> (SELECT embedding FROM docs WHERE id = 1) AS distance
FROM docs
ORDER BY embedding <-> (SELECT embedding FROM docs WHERE id = 1)
LIMIT 5;
```

**Observe cold vs warm cache:**
- First run: ~3-5ms (cold cache - data loaded from disk/TOAST)
- Second run: ~1-2ms (warm cache - data already in memory)
- This is normal PostgreSQL behavior - shared_buffers cache
- Production systems have warm caches most of the time

**Observe**:
- ✅ Index Scan using docs_hnsw_idx
- ✅ Lower latency than IVFFlat
- ✅ High recall
- ✅ No centroid filtering (graph traversal)

### Step 3: Tune HNSW search quality

```sql
-- Increase ef_search for better recall
SET hnsw.ef_search = 100;

EXPLAIN ANALYZE
SELECT 
    id, 
    content,
    embedding <-> (SELECT embedding FROM docs WHERE id = 1) AS distance
FROM docs
ORDER BY embedding <-> (SELECT embedding FROM docs WHERE id = 1)
LIMIT 5;
```

**Takeaway**: *"HNSW gives great recall and speed but is heavier to build and heavier on writes."*

---

## 🔬 Section 6 — Query Plan Comparisons (Side-by-Side)

**Goal**: Compare all three approaches directly to see the performance difference.

### Comparison 1: Sequential Scan (No Index)

```sql
-- Disable indexes to force sequential scan
SET enable_indexscan = off;

EXPLAIN (ANALYZE, BUFFERS, TIMING)
SELECT 
    id, 
    content,
    embedding <-> (SELECT embedding FROM docs WHERE id = 1) AS distance
FROM docs
ORDER BY embedding <-> (SELECT embedding FROM docs WHERE id = 1)
LIMIT 5;

-- Re-enable indexes
SET enable_indexscan = on;
```

**Expected**: Seq Scan, ~500-2000ms, high buffer reads

### Comparison 2: IVFFlat Index

```sql
-- Ensure only IVFFlat exists
DROP INDEX IF EXISTS docs_hnsw_idx;
DROP INDEX IF EXISTS docs_ivfflat_idx;

CREATE INDEX docs_ivfflat_idx 
ON docs 
USING ivfflat (embedding vector_l2_ops) 
WITH (lists = 200);

ANALYZE docs;
SET ivfflat.probes = 1;

EXPLAIN (ANALYZE, BUFFERS, TIMING)
SELECT 
    id, 
    content,
    embedding <-> (SELECT embedding FROM docs WHERE id = 1) AS distance
FROM docs
ORDER BY embedding <-> (SELECT embedding FROM docs WHERE id = 1)
LIMIT 5;
```

**Expected**: Index Scan using ivfflat, ~10-20ms, fewer buffers

### Comparison 3: HNSW Index

```sql
-- Switch to HNSW
DROP INDEX docs_ivfflat_idx;

CREATE INDEX docs_hnsw_idx 
ON docs 
USING hnsw (embedding vector_l2_ops) 
WITH (m = 16, ef_construction = 200);

SET hnsw.ef_search = 40;

EXPLAIN (ANALYZE, BUFFERS, TIMING)
SELECT 
    id, 
    content,
    embedding <-> (SELECT embedding FROM docs WHERE id = 1) AS distance
FROM docs
ORDER BY embedding <-> (SELECT embedding FROM docs WHERE id = 1)
LIMIT 5;
```

**Expected**: Index Scan using hnsw, ~5-15ms, minimal buffers

### Summary Table

| Approach | Scan Type | Time | Buffers Read | Speedup | Accuracy |
|----------|-----------|------|--------------|---------|----------|
| No Index | Sequential + TOAST | ~500-2000ms | ~300,000 blocks | baseline | Perfect |
| IVFFlat (probes=1) | Index Scan | ~10-20ms | ~1,000 blocks | **50-100x** | Approximate |
| HNSW | Index Scan | ~5-15ms | ~500 blocks | **70-150x** | High Approximate |

**Key insight**: The speedup comes from reading 300x less data (~1,000 blocks vs ~300,000 blocks)!

**Note**: ANN indexes trade perfect accuracy for speed. They find approximate nearest neighbors, not guaranteed exact matches. For most applications, this trade-off is worth it.

**Takeaway**: *"HNSW gives the best balance of speed and recall. IVFFlat is faster to build but less accurate. Sequential scan is only for tiny datasets."*

---

## 🧱 Section 7 — Data Modelling Choices

### Option 1: Inline embeddings table (current approach)

```sql
-- Good for: read-heavy, few updates
CREATE TABLE docs (
    id serial PRIMARY KEY,
    content text,
    embedding vector(1024)
);
```

### Option 2: Separate embedding table

```sql
-- Good for: frequent content updates, versioning, partitioning
CREATE TABLE documents (
    id serial PRIMARY KEY,
    content text,
    created_at timestamp DEFAULT now()
);

CREATE TABLE document_embeddings (
    id serial PRIMARY KEY,
    document_id int REFERENCES documents(id),
    embedding vector(1024),  -- Match your model's dimensions
    model_version text,
    created_at timestamp DEFAULT now()
);

CREATE INDEX doc_emb_hnsw_idx 
ON document_embeddings 
USING hnsw (embedding vector_l2_ops);
```

### Option 3: Smaller embeddings

```sql
-- Use 384d or 768d models (MiniLM, Instructor, etc.)
-- Better caching, less TOAST pressure

-- Compare our 1024d embeddings with smaller alternatives
SELECT 
    pg_column_size(embedding) AS actual_bytes_1024d,
    pg_column_size(embedding) / 2 AS estimated_bytes_512d,
    pg_column_size(embedding) / 3 AS estimated_bytes_384d
FROM docs LIMIT 1;

-- Our demo: 1024d ≈ 4 KB (TOASTed, like BGE-large)
-- Medium models: 512d ≈ 2 KB (borderline TOAST)
-- Small models: 384d ≈ 1.5 KB (stays inline!)
-- Smaller = less TOAST, less I/O, faster queries!
```

### Option 4: Cluster tables for better locality

```sql
-- Cluster table by HNSW index to improve locality
-- This physically reorders rows so similar vectors are stored near each other
CLUSTER docs USING docs_hnsw_idx;

-- Benefit: When searching for similar vectors, they're physically close
-- This improves cache locality and reduces random I/O

-- Example: Search for similar vectors
EXPLAIN (ANALYZE, BUFFERS)
SELECT 
    id, 
    content,
    embedding <-> (SELECT embedding FROM docs WHERE id = 1) AS distance
FROM docs
ORDER BY embedding <-> (SELECT embedding FROM docs WHERE id = 1)
LIMIT 20;

-- After clustering, you may see:
-- - Better buffer hit ratios
-- - Fewer random page accesses
-- - Slightly faster queries for larger result sets
```

**When to use CLUSTER:**
- After bulk loading data
- When you have a primary search pattern
- For read-heavy workloads
- **Caution**: CLUSTER locks the table and needs to rewrite it
- **Caution**: Updates/inserts don't maintain clustering - need to re-cluster periodically

**Takeaway**: *"Good modelling matters before indexing. The database pays for every decision you make."*

---

## 📉 Section 8 — Performance Pitfalls (Practical Warnings)

### Pitfall 1: Updating embeddings creates MVCC bloat

```sql
-- Update embeddings (creates TOAST bloat)
UPDATE docs SET embedding = embedding WHERE id <= 1000;

-- Check bloat
SELECT 
    pg_size_pretty(pg_total_relation_size('docs')) AS total_size;

-- Fix with VACUUM
VACUUM FULL docs;
```

### Pitfall 2: Large vectors bloat TOAST tables

```sql
-- Compare TOAST usage
SELECT 
    c.relname,
    pg_size_pretty(pg_total_relation_size(c.oid)) AS size
FROM pg_class c
WHERE c.relname LIKE '%toast%'
ORDER BY pg_total_relation_size(c.oid) DESC
LIMIT 5;
```

### Pitfall 2b: Index updates are expensive (especially HNSW)

```sql
-- Measure insert performance WITH and WITHOUT indexes
-- First, without any index
DROP INDEX IF EXISTS docs_hnsw_idx;
DROP INDEX IF EXISTS docs_ivfflat_idx;

\timing on
INSERT INTO docs (content, embedding) 
SELECT 'test', embedding FROM docs WHERE id = 1;
-- Expected: ~1-2ms per insert

-- Now with HNSW index
CREATE INDEX docs_hnsw_idx ON docs USING hnsw (embedding vector_l2_ops);

INSERT INTO docs (content, embedding) 
SELECT 'test', embedding FROM docs WHERE id = 1;
-- Expected: ~10-50ms per insert (10-50x slower!)

-- With IVFFlat index
DROP INDEX docs_hnsw_idx;
CREATE INDEX docs_ivfflat_idx ON docs USING ivfflat (embedding vector_l2_ops) WITH (lists = 200);

INSERT INTO docs (content, embedding) 
SELECT 'test', embedding FROM docs WHERE id = 1;
-- Expected: ~2-10ms per insert (2-10x slower)

\timing off
```

**Write Performance Impact:**

| Scenario | Insert Time | Slowdown |
|----------|-------------|----------|
| No index | ~1-2ms | baseline |
| IVFFlat | ~2-10ms | 2-10x slower |
| HNSW | ~10-50ms | 10-50x slower |

**Key insight**: HNSW has significant write overhead due to graph maintenance. For write-heavy workloads, consider:
- Batch inserts without index, then rebuild
- Use IVFFlat instead
- Separate embedding table to avoid index updates on content changes

### Pitfall 3: IVFFlat requires ANALYZE

```sql
-- Without ANALYZE, IVFFlat may not work properly
-- Always run after bulk inserts
ANALYZE docs;
```

### Pitfall 4: Insufficient maintenance_work_mem

```sql
-- Check current setting
SHOW maintenance_work_mem;

-- If you get "memory required" errors during index creation:
SET maintenance_work_mem = '512MB';  -- Or higher for large datasets

-- For permanent change, edit postgresql.conf:
-- maintenance_work_mem = 512MB
```

**Why this matters:**
- Vector indexes need memory for construction
- IVFFlat: k-means clustering loads vectors into memory
- HNSW: graph construction needs memory for candidates
- Default 64MB is often too small for vector workloads
- For 50k rows with 1024d: Recommend 512MB-1GB
- Recommendation: 256MB-1GB for vector indexes

### Pitfall 5: HNSW index build is slow for bulk loads

```sql
-- For bulk inserts, create index AFTER loading data
-- Not during inserts

-- Bad: index exists during inserts (slow)
-- Good: 
-- 1. Load data
-- 2. Then create index
```

### Pitfall 6: Wrong distance metric breaks quality

```sql
-- L2 distance (Euclidean)
CREATE INDEX idx_l2 ON docs USING hnsw (embedding vector_l2_ops);

-- Inner product (for normalized vectors)
CREATE INDEX idx_ip ON docs USING hnsw (embedding vector_ip_ops);

-- Cosine distance (most common for embeddings)
CREATE INDEX idx_cosine ON docs USING hnsw (embedding vector_cosine_ops);

-- Use the RIGHT metric for your model!
```

### Pitfall 7: Missing LIMIT = no ANN usage

```sql
-- BAD: No LIMIT means full scan
SELECT * FROM docs 
ORDER BY embedding <-> '[...]';

-- GOOD: LIMIT triggers ANN index
SELECT * FROM docs 
ORDER BY embedding <-> '[...]'
LIMIT 10;
```

---

## 🎁 Section 9 — Final Summary / Takeaways

✅ **pgvector uses varlena → TOAST impacts performance**
- Vectors > 2KB stored out-of-line in TOAST
- Every access requires extra I/O to TOAST tables
- Updates duplicate TOAST rows (bloat)

✅ **Bigger vectors hurt reads, writes, bloat**
- Our demo uses 1024d = ~4KB per vector (realistic for BGE-large)
- Smaller models: 384d = ~1.5KB (stays inline!)
- Consider smaller models when possible (384d, 512d) for better performance

✅ **IVFFlat → fast, approximate, good for large batches**
- Requires ANALYZE
- Tune with `ivfflat.probes`
- Use lists = sqrt(rows)

✅ **HNSW → high recall, great latency, slower writes**
- Best for production
- Tune with `hnsw.ef_search`
- Higher build cost but better query performance

✅ **Data modelling matters more than the index**
- Separate tables for versioning
- Cluster for locality
- Choose right dimensions

✅ **Always use LIMIT with vector queries**
- Without LIMIT, ANN indexes won't be used
- LIMIT enables top-K search optimization

✅ **Use EXPLAIN ANALYZE — it will tell you everything**

✅ **Postgres is absolutely capable of semantic search at production scale**

---

## 📋 Production Checklist

Before deploying pgvector to production, verify:

**Index Strategy:**
- [ ] Use HNSW for user-facing queries (low latency, high recall)
- [ ] Use IVFFlat for batch/analytics workloads (faster build, lower memory)
- [ ] Create indexes AFTER bulk loading data (not during inserts)
- [ ] Run ANALYZE after bulk inserts (required for IVFFlat)

**Configuration:**
- [ ] Set `maintenance_work_mem = 512MB` or higher (for index builds)
- [ ] Set `shared_buffers` appropriately (25% of RAM is common)
- [ ] Configure connection pooling (pgBouncer recommended)

**Data Modeling:**
- [ ] Separate embedding table if content updates frequently
- [ ] Use smaller embedding models when possible (384d, 512d)
- [ ] Add content_hash column to avoid re-embedding unchanged content
- [ ] Consider partitioning for very large datasets (>10M rows)

**Monitoring:**
- [ ] Monitor TOAST bloat: `pg_stat_user_tables` (n_dead_tup)
- [ ] Set up regular VACUUM schedule (autovacuum may not be enough)
- [ ] Track query performance: `pg_stat_statements`
- [ ] Monitor index usage: `pg_stat_user_indexes`

**Query Patterns:**
- [ ] Always use LIMIT with vector queries
- [ ] Use appropriate distance metric (cosine for text, L2 for images)
- [ ] Tune probes/ef_search based on recall requirements
- [ ] Cache frequently accessed embeddings in application layer

**Backup & Recovery:**
- [ ] Regular backups (pg_dump or physical backups)
- [ ] Test restore procedures
- [ ] Document index rebuild procedures (can take hours for large datasets)

---

## 🧨 Optional: Inspect the HNSW Graph

```sql
-- View index metadata
SELECT 
    indexrelid::regclass AS index_name,
    indrelid::regclass AS table_name,
    pg_size_pretty(pg_relation_size(indexrelid)) AS index_size
FROM pg_index 
WHERE indexrelid = 'docs_hnsw_idx'::regclass;

-- Force index usage
SET enable_seqscan = off;

EXPLAIN (ANALYZE, BUFFERS, VERBOSE)
SELECT 
    id, 
    content,
    embedding <-> (SELECT embedding FROM docs WHERE id = 1) AS distance
FROM docs
ORDER BY embedding <-> (SELECT embedding FROM docs WHERE id = 1)
LIMIT 5;

-- Reset
SET enable_seqscan = on;
```

---

## Running the Complete Demo

```bash
# 1. Generate embeddings with real text content
python generate_demo_embeddings.py

# 2. Open psql
psql postgres://postgres:mysecret@localhost:5432/postgres

# 3. Follow sections 1-9 in order
# Copy-paste SQL commands from each section
```
