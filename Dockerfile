# Hugging Face Spaces — QuarterLens API
# Full monorepo is copied so MCP server paths (packages/mcp-servers/) resolve correctly.

FROM python:3.10-slim

# Build tools needed by some transitive deps
RUN apt-get update && apt-get install -y --no-install-recommends gcc && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /code

# Copy the full monorepo
COPY . .

# Install CPU-only PyTorch first — prevents sentence-transformers from pulling the 2 GB GPU build
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# Install the API package and all its dependencies.
# Pin transformers<4.51: newer versions import torch.float8_e8m0fnu at module load,
# which is not present in CPU-only PyTorch builds.
RUN pip install --no-cache-dir -e apps/api "transformers>=4.41,<4.51"

# Pre-download embedding models at image build time so the first request is fast
ENV HF_HOME=/code/.cache/huggingface
RUN python -c "\
from sentence_transformers import SentenceTransformer, CrossEncoder; \
SentenceTransformer('all-MiniLM-L6-v2'); \
CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')"

# HF Spaces routes external traffic to port 7860
EXPOSE 7860

# Run uvicorn from apps/api so the `app` package is importable
WORKDIR /code/apps/api
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]
