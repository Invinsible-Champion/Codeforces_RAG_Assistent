# Codeforces RAG Assistant — Implementation Plan

## Overview

Build a full-stack RAG system that ingests Codeforces problems, stores them with embeddings, and provides an intelligent chat interface for problem discovery, hints, difficulty progression, and explanations — all grounded in real problem data.

### Existing Foundation
- `config.py` — Pydantic settings (DB, OpenAI, FAISS, embedding config)
- `database.py` — Async SQLAlchemy engine, session factory, Base class
- `docker-compose.yml` — PostgreSQL 16 container
- `requirements.txt` — FastAPI, SQLAlchemy, OpenAI, FAISS, httpx, BeautifulSoup

---

## User Review Required

> [!IMPORTANT]
> **LLM Provider**: The config currently uses OpenAI (`gpt-4o-mini` for chat, `text-embedding-3-small` for embeddings). Should I keep OpenAI, or switch to another provider (e.g., Anthropic Claude for chat, keeping OpenAI for embeddings)?

> [!IMPORTANT]
> **FAISS vs Pinecone**: The requirements already include `faiss-cpu`. FAISS is simpler (local, no account needed) but doesn't scale horizontally. Pinecone is managed but requires an API key. I'll proceed with **FAISS** unless you prefer Pinecone.

> [!WARNING]
> **OpenAI API Key Required**: You'll need a valid `OPENAI_API_KEY` in your `.env` file for embeddings and chat to work. The ingestion pipeline will call the embedding API for every chunk.

---

## Proposed Changes

### Phase 1: Data Models & Database Schema

Define SQLAlchemy ORM models for problems, chunks, and conversations.

#### [NEW] [models.py](file:///c:/Users/jalaj/.gemini/antigravity/scratch/codeforces-rag-assistant/backend/app/models.py)

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `problems` | Store problem metadata from CF API | `contest_id`, `index`, `name`, `rating`, `tags` (JSON), `time_limit`, `memory_limit`, `solved_count`, `statement_html`, `statement_text` |
| `problem_chunks` | Semantic chunks of problem text | `problem_id` (FK), `chunk_index`, `chunk_text`, `chunk_type` (statement/input/output/note/example), `embedding_id` (maps to FAISS) |
| `conversations` | Chat history for personalization | `id`, `title`, `created_at` |
| `messages` | Individual messages in a conversation | `conversation_id` (FK), `role`, `content`, `metadata` (JSON) |

---

### Phase 2: Ingestion Pipeline

Fetch problems from Codeforces API, scrape full statements, clean HTML, chunk text, generate embeddings.

#### [NEW] [services/ingestion.py](file:///c:/Users/jalaj/.gemini/antigravity/scratch/codeforces-rag-assistant/backend/app/services/ingestion.py)

- `fetch_problem_list()` — Call `https://codeforces.com/api/problemset.problems`, parse response
- `scrape_problem_statement(contest_id, index)` — GET `https://codeforces.com/problemset/problem/{contest_id}/{index}`, extract `.problem-statement` div
- `clean_html(html)` — Strip tags, normalize whitespace, preserve structure
- `chunk_problem(problem)` — Split statement into semantic sections: title, statement body, input spec, output spec, examples, notes. Each becomes a chunk (~200-500 tokens)
- `ingest_problems(tags=None, rating_min=None, rating_max=None, limit=100)` — Orchestrator: fetch → filter → scrape → chunk → embed → store

#### [NEW] [services/text_processing.py](file:///c:/Users/jalaj/.gemini/antigravity/scratch/codeforces-rag-assistant/backend/app/services/text_processing.py)

- `html_to_clean_text(html)` — BeautifulSoup-based cleaner
- `split_into_chunks(text, max_tokens=400, overlap=50)` — Token-aware splitter using tiktoken
- `extract_problem_sections(soup)` — Parse `.problem-statement` children into structured sections

---

### Phase 3: Vector Store (FAISS)

Manage FAISS index lifecycle: build, add, search, persist.

#### [NEW] [services/vector_store.py](file:///c:/Users/jalaj/.gemini/antigravity/scratch/codeforces-rag-assistant/backend/app/services/vector_store.py)

- `FaissVectorStore` class:
  - `__init__(dim, index_path, id_map_path)` — Load or create FAISS IndexFlatIP (inner product for cosine sim on normalized vectors)
  - `add_vectors(embeddings, chunk_ids)` — Add batch of vectors, update ID map
  - `search(query_embedding, top_k=10)` — Return top-k (chunk_id, score) pairs
  - `save()` / `load()` — Persist index + ID map to disk
  - `remove_vectors(chunk_ids)` — For re-ingestion

---

### Phase 4: Embedding Service

Wrapper around OpenAI embeddings API with batching and caching.

#### [NEW] [services/embeddings.py](file:///c:/Users/jalaj/.gemini/antigravity/scratch/codeforces-rag-assistant/backend/app/services/embeddings.py)

- `get_embedding(text)` — Single text → vector
- `get_embeddings_batch(texts, batch_size=100)` — Batch embedding with rate limiting
- Normalize vectors to unit length (for cosine similarity via inner product)

---

### Phase 5: Retrieval Engine (Hybrid Search)

Combine vector similarity with SQL filtering for precise, relevant retrieval.

#### [NEW] [services/retrieval.py](file:///c:/Users/jalaj/.gemini/antigravity/scratch/codeforces-rag-assistant/backend/app/services/retrieval.py)

- `hybrid_search(query, filters, top_k=10)`:
  1. Embed the query
  2. FAISS similarity search → candidate chunk IDs (fetch more than top_k)
  3. SQL filter on associated problems (by rating range, tags, contest_id)
  4. Re-rank and return top_k results with problem metadata
- `similarity_search(problem_id, top_k=5)` — Find problems most similar to a given one
- `difficulty_progression(tags, current_rating, step=100)` — Return problems ordered by increasing difficulty within the same tag family

---

### Phase 6: LLM Orchestration & Prompt Engineering

#### [NEW] [services/llm.py](file:///c:/Users/jalaj/.gemini/antigravity/scratch/codeforces-rag-assistant/backend/app/services/llm.py)

- `generate_response(query, context_chunks, mode)` — Core LLM call with prompt injection
- Modes with distinct system prompts:
  - **`explain`** — Full explanation of a problem's approach, complexity, key ideas
  - **`hint`** — Progressive hints only, no direct solution
  - **`recommend`** — Suggest problems based on context
  - **`chat`** — General Q&A grounded in retrieved data
- Streaming support via SSE (Server-Sent Events)

#### [NEW] [services/prompts.py](file:///c:/Users/jalaj/.gemini/antigravity/scratch/codeforces-rag-assistant/backend/app/services/prompts.py)

- System prompt templates for each mode
- Context formatting: convert chunks into a structured reference block
- Response constraints: force the LLM to cite problem IDs, stay grounded

---

### Phase 7: FastAPI Backend (Routes & API)

#### [NEW] [main.py](file:///c:/Users/jalaj/.gemini/antigravity/scratch/codeforces-rag-assistant/backend/app/main.py)

- App factory, CORS, lifespan (init DB, load FAISS index)

#### [NEW] [routers/chat.py](file:///c:/Users/jalaj/.gemini/antigravity/scratch/codeforces-rag-assistant/backend/app/routers/chat.py)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/chat` | POST | Send query, get RAG-powered response (SSE stream) |
| `/api/chat/conversations` | GET | List past conversations |
| `/api/chat/conversations/{id}` | GET | Get conversation history |
| `/api/chat/conversations` | POST | Create new conversation |

#### [NEW] [routers/problems.py](file:///c:/Users/jalaj/.gemini/antigravity/scratch/codeforces-rag-assistant/backend/app/routers/problems.py)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/problems` | GET | List problems with filters (tags, rating, search) |
| `/api/problems/{id}` | GET | Get full problem detail |
| `/api/problems/{id}/similar` | GET | Find similar problems |
| `/api/problems/progression` | GET | Difficulty progression for given tags |

#### [NEW] [routers/ingest.py](file:///c:/Users/jalaj/.gemini/antigravity/scratch/codeforces-rag-assistant/backend/app/routers/ingest.py)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/ingest/start` | POST | Trigger ingestion (with filters) |
| `/api/ingest/status` | GET | Check ingestion status |

#### [NEW] [schemas.py](file:///c:/Users/jalaj/.gemini/antigravity/scratch/codeforces-rag-assistant/backend/app/schemas.py)

- Pydantic request/response models for all endpoints

---

### Phase 8: Frontend — Interactive Chat + Problem Explorer

A single-page application with a stunning, premium dark-mode design.

#### [NEW] Frontend files in `frontend/`

| File | Purpose |
|------|---------|
| `index.html` | Main HTML shell |
| `styles.css` | Full design system — dark glassmorphism theme, animations |
| `app.js` | Application core — routing, state management |
| `components/chat.js` | Chat interface with streaming, markdown rendering |
| `components/explorer.js` | Problem explorer with tag filters, rating sliders, search |
| `components/problem-detail.js` | Full problem view with similar problems |
| `components/sidebar.js` | Navigation + conversation history |

**Design Features:**
- Dark mode with glassmorphism cards (frosted glass, blurred backgrounds)
- Gradient accent colors (violet→cyan spectrum)
- Smooth micro-animations on hover, load, and transition
- Responsive layout (sidebar collapses on mobile)
- Code/math rendering in chat using highlight.js and KaTeX
- Streaming chat responses with animated typing indicator
- Tag chips with color coding, rating badges with difficulty colors

---

## Open Questions

> [!IMPORTANT]
> 1. **OpenAI or another LLM?** Currently configured for OpenAI. Want me to switch?
> 2. **Scope of initial ingestion?** Should I ingest all ~10k+ problems or start with a subset (e.g., rating 800–2000, or specific tags)?
> 3. **Authentication?** Should the app have user accounts, or is it a single-user local tool?

---

## Verification Plan

### Automated Tests
1. **Ingestion**: Run ingestion for 5-10 problems, verify DB rows + FAISS vectors
2. **Retrieval**: Query "dp problems around rating 1500" and verify relevant results
3. **API**: Hit all endpoints with httpx/curl, validate response schemas
4. **Frontend**: Browser test — open app, send a chat message, explore problems

### Manual Verification
1. Start PostgreSQL via `docker-compose up`
2. Start backend via `uvicorn app.main:app --reload`
3. Open frontend, trigger ingestion, chat with the system
4. Verify streaming responses, problem filters, similar problems

---

## Phase 9: Async Ingestion Update (Editorial Scraping)

### User Review Required
> [!IMPORTANT]
> - **Semaphore Limit:** Do you have a specific concurrency limit in mind for the `asyncio.Semaphore`? I will default to 5 concurrent requests to balance speed and safety against Codeforces IP-bans.
> - **Chunking Threshold:** Editorials can sometimes be very long. The updated chunker will split them using `tiktoken` into ~400 token blocks. Is this token limit still appropriate for your LLM context?

### Proposed Changes

#### [MODIFY] [models.py](file:///c:/Users/jalaj/.gemini/antigravity/scratch/codeforces-rag-assistant/backend/app/models.py)
- **Problem Model:** Add `editorial_html = Column(Text, nullable=True)` and `editorial_text = Column(Text, nullable=True)`.
- **ProblemChunk Model:** Update the schema documentation to explicitly include `editorial` as a supported `chunk_type` enum value.

#### [MODIFY] [services/ingestion.py](file:///c:/Users/jalaj/.gemini/antigravity/scratch/codeforces-rag-assistant/backend/app/services/ingestion.py)
- **Concurrency Control:** Introduce an `asyncio.Semaphore` and a shared `httpx.AsyncClient` that respects the `SCRAPE_DELAY` environment variable. 
- **New Functions:**
  - `fetch_tutorial_link(client, contest_id, index)`: Scrape the individual problem page (e.g. `.../problem/123/A`) and parse the right-hand sidebar "Materials" box for the exact Tutorial/Editorial link.
  - `fetch_and_extract_editorial(client, tutorial_url, problem_index, problem_name)`: Request the blog URL, locate `<div class="content">`, and use heuristics (like tags containing problem name/index) to extract only the problem's explanation.
- **Orchestrator Refactor (`ingest_problems`)**: 
  - Switch from the sequential `for` loop to an `asyncio.gather` approach. 
  - Create an inner `process_single_problem(semaphore, db, client, prob_data)` coroutine.
  - Ensure missing editorials log a warning and return `NULL` without aborting the batch task.

#### [MODIFY] [services/text_processing.py](file:///c:/Users/jalaj/.gemini/antigravity/scratch/codeforces-rag-assistant/backend/app/services/text_processing.py)
- **HTML Cleaning (`html_to_clean_text`)**: Verify it gracefully strips or formats the Editorial `<div class="content">` HTML structure (Lists, Bold elements).
- **Chunking (`chunk_problem_text`)**: Split the `editorial_text` string into manageable, ~400-token chunks tagged with `chunk_type="editorial"`. (As requested, adapting the current chunker to ensure it maps to the DB chunk types properly).

---

## Phase 10: Stealth Selenium Scraper (Cloudflare Bypass for Editorials)

### User Review Required
> [!IMPORTANT]
> - **Architecture Decision:** Because Selenium uses full browser instances (blocking threads) and requires restarts every ~50 problems, integrating it directly into a FastAPI endpoint (`/api/ingest/start`) would cause heavy timeouts and block the server. I propose building the scraper as a standalone background tool: `backend/scripts/stealth_scraper.py`. It will save data locally to a JSON file (`data/scraped_editorials.json`). We will then update the `ingest_problems` endpoint to simply ingest from this JSON file (if available) instead of doing live HTTP requests. Do you agree with this decoupled approach?
> - **Driver Configuration:** I ran a quick check on your system, and your installed Google Chrome version is `146`. I will explicitly set `version_main=146` for `undetected-chromedriver` to prevent driver mismatch errors.

### Proposed Changes

#### [MODIFY] [backend/requirements.txt](file:///c:/Users/jalaj/.gemini/antigravity/scratch/codeforces-rag-assistant/backend/requirements.txt)
- Add `undetected-chromedriver` to enable Selenium scraping capable of bypassing Cloudflare bot detections.

#### [NEW] [backend/scripts/stealth_scraper.py](file:///c:/Users/jalaj/.gemini/antigravity/scratch/codeforces-rag-assistant/backend/scripts/stealth_scraper.py)
This dedicated script will fulfill all 5 phases outlined in your request:
- **Phase 1 (Browser Config):** Initialize `undetected_chromedriver` with `--disable-gpu`, `--window-size=1280,720`, and `version_main=146`.
- **Phase 2 (2-Step Extract):** Load the problem page, find the Tutorial link in `.roundbox`, navigate, execute `.spoiler-title` clicks via JS, wait 4s, and parse the HTML with BeautifulSoup. Search for the `problem_name`/ID headers and isolate siblings using the dynamic Stop Conditions defined in the prompt.
- **Phase 3 (Cleanup/MathJax):** Strip `<pre>` tags, convert LaTeX `<script type="math/tex">` directly into `$ [text] $` strings, `.decompose()` `.MathJax` visuals, strip "Tutorial is loading..." strings, and format `<p>`, `<h1>`, `<ul>`, `<li>`, and `<br>` elements securely with newlines.
- **Phase 4 (Final Text):** Apply `get_text(separator=' ', strip=True)` to preserve sentence structure with inline math, collapsing multiple spaces to a single space and consecutive newlines to double newlines using regex.
- **Phase 5 (Bulk Safety):** Wrap logic in a continuous `while/for` loop executing over the list of unscraped problems. It will feature real-time JSON checkpointing `data/scraped_editorials.json`, dynamic problem deduplication, `random.uniform(5, 10)` request delays, a built-in memory reset calling `.quit()` every 50 loops, and heavy `try/except` handlers saving error states to JSON.

#### [MODIFY] [backend/app/services/ingestion.py](file:///c:/Users/jalaj/.gemini/antigravity/scratch/codeforces-rag-assistant/backend/app/services/ingestion.py)
- Modify the existing ingest script so it automatically checks for `data/scraped_editorials.json`. If an editorial exists in the local JSON dictionary for a given `contest_id` and `index`, it uses it directly. Otherwise, it logs that the item needs scraping by the standalone scraper.
