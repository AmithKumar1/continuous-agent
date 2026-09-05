# 🤖 Continuous Autonomous Discovery Agent

> An autonomous neuro-symbolic discovery system integrating a continuous execution heartbeat, cognitive memory with recursive compaction, RRF hybrid RAG search, multi-island evolutionary search (FunSearch), Counterexample-Guided Inductive Synthesis (CEGIS) with Z3, formal verification via Lean 4, dual-tier WASM/gVisor sandboxing, and automated GitHub GitOps PR publishing.

---

## ⚡ Architectural Overview

```
                           ┌──────────────────────────────────────────────┐
                           │      FastAPI Real-Time Control Deck          │
                           │ (WebSockets, SSE, Telemetry, CEGIS, Lean 4)  │
                           └──────────────────────┬───────────────────────┘
                                                  │
                ┌─────────────────────────────────┴─────────────────────────────────┐
                ▼                                                                   ▼
  ┌───────────────────────────┐                                       ┌───────────────────────────┐
  │  Continuous Agent Loop    │                                       │   Task Scheduler (Cron)   │
  │  - Asynchronous Heartbeat │                                       │   - Live Countdown Deck   │
  │  - Multi-Turn Tools       │                                       │   - Dynamic Croniter      │
  │  - Circuit Breaker        │                                       │   - Nightly Discovery     │
  └─────────────┬─────────────┘                                       └─────────────┬─────────────┘
                │                                                                   │
                ├─────────────────────────────────┬─────────────────────────────────┤
                ▼                                 ▼                                 ▼
  ┌───────────────────────────┐     ┌───────────────────────────┐     ┌───────────────────────────┐
  │     Cognitive Memory      │     │    Evolutionary Engine    │     │  Neuro-Symbolic & CEGIS   │
  │ - Working Scratchpad      │     │ - FunSearch Service       │     │ - AST-to-Z3 Transpiler    │
  │ - Reflexion (Self-Learn)  │     │ - Multi-Island Model      │     │ - Singularity / Monotonic │
  │ - Episodic Compaction     │     │ - Behavioral Probes       │     │ - Dynamic Suite Invariant │
  │ - RRF Hybrid Search       │     │ - Strategy Stagnation     │     │ - Lean 4 Kernel Prover    │
  └───────────────────────────┘     └─────────────┬─────────────┘     └─────────────┬─────────────┘
                                                  │                                 │
                                                  ▼                                 ▼
                                    ┌───────────────────────────┐     ┌───────────────────────────┐
                                    │    Dual-Tier Sandboxing   │     │    GitOps PR Automation   │
                                    │ - WebAssembly (Fuel Cap)  │     │ - Auto Feature Branch     │
                                    │ - 1-Page Linear Memory    │     │ - Code + Lean Certificate │
                                    │ - gVisor (runsc) Fallback │     │ - GitHub REST API PR Open │
                                    └───────────────────────────┘     └───────────────────────────┘
```

---

## ✨ Key Capabilities

- **Continuous Heartbeat Loop (`agent/core.py`)**: Asynchronous evaluate-and-act cycle with circuit breakers, token governors, and multi-turn parallel tool execution.
- **Cognitive Memory & Compactor (`agent/cognitive_memory.py`)**: Hierarchical memory that automatically compacts execution history into semantic summaries, preserving context while eliminating token bloat.
- **Reciprocal Rank Fusion Hybrid Search (`agent/hybrid_search.py`)**: Merges SQLite FTS5 lexical keyword search (BM25) with ChromaDB dense vector embeddings (`text-embedding-3-small`).
- **Evolutionary FunSearch Service (`agent/funsearch_service.py`)**: Multi-island evolutionary algorithm with behavioral fingerprinting, parsimony pressure (favoring shorter solutions), and stagnation-triggered strategy mutations.
- **Counterexample-Guided Inductive Synthesis (`cegis_verifier.py`, `agent/cegis_tracker.py`)**: SMT-driven invariant verification checking mathematical boundary conditions (divide-by-zero, monotonicity), generating adversarial test cases dynamically.
- **Lean 4 Proof Synthesis & Verification (`agent/lean_synthesizer.py`, `agent/formal_verifier.py`)**: Automatically transpiles Python ASTs into Lean 4 theorems and validates them against the official Lean 4 kernel.
- **Dual-Tier Sandboxing (`agent/wasm_sandbox.py`, `sandbox.py`)**:
  - **Tier 1**: Sub-millisecond WebAssembly JIT with instruction fuel limits and 64KB linear memory bounds.
  - **Tier 2**: Hardened container isolation via gVisor (`runsc`) for complex workloads.
- **GitOps Pull Request Automation (`agent/gitops.py`)**: Automatically creates Git branches, commits discovered Python heuristics and Lean 4 certificates, and opens GitHub Pull Requests.
- **Real-Time Operator Dashboard (`dashboard.py`)**: Dark glassmorphism dashboard with WebSocket telemetry, interactive Z3/Lean 4 probes, scheduler countdown, and cognitive scratchpad editor.

---

## 🚀 Quickstart

### 1. Clone & Configure

```bash
git clone https://github.com/AmithKumar1/continuous-agent.git
cd continuous-agent
cp .env.example .env
```

Edit `.env` with your API keys:
- `OPENAI_API_KEY`: Required for LLM generation and embeddings.
- `DASHBOARD_API_KEY`: Passcode for the operator dashboard.
- `GITHUB_TOKEN` & `GITHUB_REPO`: For automated GitOps pull requests.

### 2. Run Pre-Flight Diagnostics

```bash
python preflight.py
```

### 3. Run Locally

```bash
pip install -r requirements.txt
python main.py
```

Open your browser at `http://localhost:8000`.

### 4. Run with Docker Compose

```bash
docker compose up -d --build
```

---

## 🛠️ Testing & Verification

Run the verification suites for the WebAssembly sandbox and Lean 4 formal prover:

```bash
# Test WebAssembly JIT execution & fuel limits
python test_wasm_sandbox.py

# Test Lean 4 proof synthesis
python test_lean_verify.py
```

---

## 📡 API Reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Web operator dashboard UI |
| `GET` | `/api/status` | Current heartbeat iteration and agent state |
| `POST` | `/api/pause` | Pause agent heartbeat loop |
| `POST` | `/api/resume` | Resume agent heartbeat loop |
| `POST` | `/api/trigger` | Trigger immediate single-cycle step |
| `GET` | `/api/memory/core` | Read active working scratchpad |
| `POST` | `/api/memory/core` | Set or update working scratchpad key/value |
| `GET` | `/api/memory/heuristics` | Fetch learned operational rules |
| `GET` | `/api/memory/search?q=...` | Hybrid RRF episodic memory search |
| `POST` | `/api/funsearch/start` | Launch multi-island evolutionary search |
| `GET` | `/api/funsearch/telemetry` | Real-time evolutionary search telemetry |
| `POST` | `/api/cegis/probe` | Run Z3 contract verification on heuristic code |
| `POST` | `/api/verify/lean` | Synthesize and check Lean 4 proof certificate |
| `POST` | `/api/gitops/create-pr` | Open GitHub PR for verified heuristic |
| `GET` | `/api/scheduler/status` | Cron schedule status and live countdown |
| `POST` | `/api/scheduler/update` | Update cron schedule pattern |
| `POST` | `/api/scheduler/trigger-now`| Launch overnight discovery pipeline immediately |
| `WS` | `/ws/telemetry` | Real-time WebSocket event stream |

---

## 🔒 Security Architecture

- **Isolated Storage**: Local SQLite databases (`agent_state.db`) and ChromaDB vector collections (`chroma_data/`) are isolated and omitted from source control.
- **Scope Restriction**: Autonomous security audits enforce explicit host allowlisting (`SECURITY_SCAN_ALLOWED_HOSTS`).
- **Deadlock-Free Lock Ordering**: Distributed tool execution enforces ordered resource locks to prevent concurrency deadlocks.
- **Resource Limits**: WASM execution enforces explicit fuel depletion bounds; gVisor fallback enforces read-only root filesystems and process limits.

---

## 📄 License

MIT License. See [LICENSE](LICENSE) for details.
