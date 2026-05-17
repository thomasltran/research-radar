# Research Radar

Local tool for finding relevant papers, scoring them against your research profile, maintaining a working set, and browsing the results in a web UI.

## Setup

Requirements:

- Python 3.11+
- Node.js/npm
- Ollama running locally for LLM steps
- Optional: Semantic Scholar API key

Install:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cd frontend
npm install
cd ..

cp .env.template .env
```

Edit:

- `.env` for local secrets/runtime overrides
- `config/research_radar.yaml` for research profile, seed papers, thresholds, search tuning, model defaults, and prompt guidance

Keep API keys and machine-local paths in `.env`. Keep scoring thresholds, tags,
topics, seed papers, and prompt guidance in `config/research_radar.yaml`.

## Run The App

For local development, start the frontend with the backend:

```bash
cd frontend
npm run dev
```

The frontend launcher starts the FastAPI backend and waits for `/api/health`.

Backend only:

```bash
python -m src.web_server
```

## First-Time Bootstrap

Bootstrap creates the initial working set from curated seed papers:

```bash
python -m scripts.bootstrap
```

Use this once on an empty database. It fetches seed metadata, builds embeddings/indexes, creates summaries, and initializes the interest vector.

## Pipeline

Run the normal intake pipeline:

```bash
./run.sh manual
```

What it does:

1. Fetches papers from arXiv and/or Semantic Scholar.
2. Deduplicates by DOI, source ID, and fuzzy title match.
3. Embeds every new paper into the local library index.
4. Filters by interest-vector similarity and LLM relevance score.
5. Compresses relevant papers into summaries and tags.
6. Adds score `>= 7` papers to the working set.
7. Runs RAG analysis for novelty, relationships, and `read`/`track`/`ignore`.
8. Verifies high-score papers and writes Markdown notes/digests.

Key thresholds live in `config/research_radar.yaml`.

## Relink vs Reanalyze

Run relink before reanalyze when both are needed.

Relink:

```bash
./run.sh relink
```

Use when your profile, tags, scoring policy, embeddings, or indexes changed. It does not fetch papers. It rescores existing papers, updates working-set membership, rebuilds indexes/clusters, recomputes the interest vector, and refreshes relationship edges.

From the frontend folder, you can also trigger the backend relink endpoint:

```bash
npm run relink
```

Reanalyze:

```bash
./run.sh reanalyze
```

Use when prompts, analysis schema, note output, or recommendation logic changed. It does not fetch papers. It regenerates summaries, RAG analysis, verification, and notes from stored abstracts and embeddings.

Optional reanalysis scopes:

```bash
python -m src.maintenance reanalyze --working-set-only
python -m src.maintenance reanalyze --all-papers
```

Review pending prune suggestions:

```bash
python -m scripts.prune_working_set list
python -m scripts.prune_working_set apply --id <action_id>
python -m scripts.prune_working_set keep --id <action_id>
```

## Data

- SQLite: `data/research.db`
- FAISS indexes: `data/index_all.faiss`, `data/index_ws.faiss`
- Embeddings: `data/embeddings.npz`
- Interest vector: `data/interest_vector.npy`
- Job logs: `data/pipeline_logs/`
- Markdown notes/digests: `output/` or `OUTPUT_DIR`

Generated data, local environment files, dependency installs, and frontend build output are ignored by git. Commit source/config templates, not local `data/`, `.env`, `frontend/node_modules/`, or `frontend/dist/`.
