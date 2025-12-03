# PostgreSQL Vector Embedding Demo

## Setup

```bash
source venv/bin/activate
```

## Usage

```bash
# Initialize database with sample data
python demo.py setup

# Add your own texts
python demo.py seed

# Compare two texts
python demo.py compare

# Search for similar texts
python demo.py search
```

## Requirements

- PostgreSQL with pgvector extension
- Python 3.7+
