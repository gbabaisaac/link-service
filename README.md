# Link AI Architecture

Link is a campus community AI assistant that uses retrieval-first reasoning, confidence gating, and a consent-aware outreach loop. This README explains how the backend is structured and why it is more than a simple LLM wrapper.

## High-level flow

1) Ingest campus data (profiles, orgs, events, posts, verified facts) from Supabase.
2) Build a semantic index for fast retrieval.
3) Parse intent + entities from each user query.
4) Retrieve and type-gate results based on intent.
5) Compute confidence and decide whether to answer or trigger outreach.
6) Generate grounded responses from retrieved records.
7) If confidence is low, run outreach to collect consented facts and write back to the knowledge base.
8) Update user memory to personalize tone and follow-ups.

## System components

### API layer (FastAPI)
- `main.py` exposes the public endpoints.
- Key routes:
  - `POST /query`: core user question flow.
  - `POST /link/agent`: chat-style agent entrypoint with style memory and citations.
  - `POST /outreach/*`: outreach lifecycle endpoints.

### LLM adapter
- `link_logic.py` provides `llm_json()`, which calls OpenAI or Gemini and enforces JSON outputs.
- The LLM is used for *structured tasks* (intent parsing, response phrasing), not raw free-form answering.

### Retrieval and indexing (RAG)
- `rag_index.py` builds a LlamaIndex `VectorStoreIndex` from multiple campus data types.
- Documents are created for:
  - profiles
  - organizations
  - events
  - forum posts
  - verified facts
- `retrieve()` returns top-k results with metadata and similarity scores.

### Intent routing + type gating
- `link_logic.parse_intent()` classifies intent and extracts entities.
- Results are filtered by intent type to avoid cross-type hallucinations.
  - `find_people` → only profiles/facts
  - `find_org` → only orgs/facts
  - `find_event` → only events/facts

### Confidence gating
- `link_logic.calculate_confidence()` combines:
  - result count (base signal)
  - dual retrieval agreement (consistency)
  - source quality (opt-in facts weighted higher)
- If confidence is below threshold, the system *does not answer* and triggers outreach.

### Outreach loop (human-in-the-loop)
- `outreach_logic.py` selects targets (friends → classmates → interest matches → prior facts).
- Sends consented outreach messages.
- Interprets replies and scores candidates.
- Verified facts are written back to Supabase and used in future retrieval.

### Response generation
- `link_logic.generate_response()` only uses retrieved results.
- If no results are present, it asks a clarifying question instead of inventing content.
- Tone is personalized using user memory.

### Memory and personalization
- User memory tracks interaction count, last intent, entities, and preferences.
- Used to adapt the response tone and follow-up suggestions.

## Why this is not just a GPT wrapper

A GPT wrapper is: user → prompt → LLM → answer.

Link is: user → intent parsing → retrieval → type gating → confidence gating → (answer OR outreach) → writeback.

Key differentiators:
- Retrieval-first design over real campus data.
- Confidence-based decision to *not answer* when evidence is weak.
- Consent-aware outreach loop that collects new facts.
- Typed, grounded responses with strict result filtering.

## Suggested demo narrative

1) Ask: “Know anyone who plays tennis?”
2) Intent = find_people, entity = tennis.
3) Retrieve matching profiles/facts.
4) If confidence is low, Link offers to ask around.
5) Outreach responses become verified facts.
6) Next query uses those facts for a grounded answer.

## Files to know

- `main.py`: API routes and orchestration.
- `link_logic.py`: intent parsing, confidence scoring, response generation.
- `rag_index.py`: LlamaIndex setup and retrieval.
- `outreach_logic.py`: outreach selection + consent processing.
- `supabase_client.py`: data access layer.
- `schemas.py`: request/response models.

