#!/usr/bin/env bash
set -e

# Install CPU-only PyTorch first so sentence-transformers doesn't pull the 2 GB GPU build
pip install torch --index-url https://download.pytorch.org/whl/cpu

pip install -e .

# Pre-download embedding models at build time to avoid cold-start latency
python -c "
from sentence_transformers import SentenceTransformer, CrossEncoder
SentenceTransformer('all-MiniLM-L6-v2')
CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')
"
