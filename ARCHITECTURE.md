# Link AI: Federated Vault + Runner Architecture (Updated Plan)

This plan aligns the implementation with the **Dual Brain** model:
**Brain A = Vault (private)**, **Brain B = Runner (public)**.

## Core Model (Correct Roles)

### 🔒 Brain A: The Private Vault
- **Role:** Personal memory + confidential data.
- **Data:** link_memory, link_life_events, user context, private chat logs, vibe profile.
- **Security:** Air-gapped by policy. Only Vault creates **sanitized work orders**.
- **Encryption:** link_memory uses AES-256. Loss of the user key means data loss by design.

### 🏃 Brain B: The Public Runner
- **Role:** Stateless worker that fulfills **anonymous work orders**.
- **Data:** Only sees public tags + anonymous work orders.
- **Logic:** Selects targets, sends anonymous outreach, records replies.
- **Isolation:** Runner JWT + RLS; no service key; memory wiped after each job.

---

## Flow Summary (High-Level)
1. **User asks for help** → Vault classifies intent.
2. Vault **sanitizes** message and writes to `link_work_orders`.
3. Runner picks up pending orders and sends anonymous outreach.
4. Targets respond; Runner records outcomes.
5. Vault reads results via the mapping table and completes consent flow.

---

## Phase 1: Vault & Scoped Instance
**Goal:** Ensure per-user isolation and prevent cross-user data access.

**Vault responsibilities**
- Intent classification + state machine.
- Read/write to private data tables only.
- Produce sanitized work orders for Runner.

**Key modules**
- `link_instance.py`: Scoped per-user instance.
- `link_state_manager.py`: Strict mode transitions.
- `sanitizer_logic.py`: PII stripping.
- `vault_service.py`: Writes to `link_work_orders` + `link_work_order_map`.

---

## Phase 2: Memory & Social Intelligence
**Goal:** Make Link feel personal without exposing PII.

**Key modules**
- `link_memory.py`: AES-256 encryption (Vault-only).
- `memory_manager.py`: Extract & store facts.
- `life_event_detector.py`: Detects events, schedules check-ins.
- `link_scheduler.py`: Adds randomized latency jitter (±45 minutes).
- `vibe_matcher.py`: Style inference for tone.

---

## Phase 3: Consent & Relay (Handshake)
**Goal:** Two-sided consent before any personal sharing.

**Key modules**
- `link_relay_*` tables and consent flow in orchestrator.
- **Social buffer:** if declined → neutral refusal message (polite lie).

---

## Phase 4: Distributed Knowledge (Work Orders)
**Goal:** Crowdsource answers without leaking identities.

**Key tables**
- `link_work_orders` (public, anonymized)
- `link_work_order_results` (target responses)
- `link_work_order_map` (private mapping to requester)

**Key modules**
- `runner_service.py`: Pulls pending work orders, selects targets, sends outreach.
- `main.py` endpoints:
  - `/link/work_orders/start`
  - `/link/work_orders/collect`
  - `/link/work_orders/reply`

---

## Phase 5: Security Hardening
**Goal:** Prevent probing, leakage, and timing attacks.

**Controls**
- **Probing detector:** rate-limit repeated “Where is X?” queries.
- **Sensitive content guard:** block health/financial/identity requests from distribution.
- **Randomized latency jitter** in scheduler.
- **Memory wipe** in Runner after each job.

---

## RLS Model (Enforced Boundaries)
**Vault**
- Uses service role to access private data.
**Runner**
- Uses anon key + `LINK_RUNNER_JWT` with `{ "runner": "true" }`.
- Can only read:
  - `profiles` (public fields only)
  - `link_system_profile`
  - `link_work_orders` / `link_work_order_results`

---

## Verification Plan
**Automated**
- RLS breach test: runner cannot read private tables.
- Encryption test: link_memory unreadable without key.
- Guardrail test: probing detector triggers on repeated location queries.

**Manual**
- Consent flow: request → deny → requester gets neutral response.
- Vibe matching: slang input → slang output.

---

## Deployment (Production)
**Service A: Vault**
- FastAPI app.
- Service role key.

**Service B: Runner**
- Runs `runner_service.py`.
- Uses `LINK_RUNNER_JWT`.
- No service key.

---

## Remaining Work (if desired)
1. Runner RLS for messaging tables (so Runner never uses service key).
2. Sensitive content guard integration in Vault.
3. Work-order → consent flow automation.
