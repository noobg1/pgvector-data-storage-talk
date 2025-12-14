# pgvector Deep Dive

PostgreSQL's pgvector extension deep dive: storage internals, indexing strategies, and production best practices.

## 🚀 Quick Start

```bash
# Setup
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # Edit with your PostgreSQL credentials

# Generate demo data (50k docs, 1024d embeddings, ~10-15 min)
python scripts/generate_demo_embeddings.py

# Run presentation
presenterm pgvector_presentation.md
```

## 📁 Structure

```
├── images/                          # Presentation images
├── scripts/                         # Python scripts
│   └── generate_demo_embeddings.py  # Main data generator
├── pgvector_presentation.md         # Presentation (presenterm)
├── pgvector_deep_dive_demo.md       # SQL walkthrough
└── .env.example                     # DB config template
```

## 🔧 Configuration

Create `.env` file:
```bash
DATABASE_URL=postgres://user:password@localhost:5432/dbname
```
