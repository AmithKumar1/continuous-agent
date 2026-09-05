<p align="center">
  <img src="assets/logo.svg" alt="Continuous Agent Logo" width="420" />
</p>

<h1 align="center">Continuous Agent</h1>

<p align="center">
  <b>Autonomous Neuro-Symbolic Research & Algorithmic Discovery Engine</b>
</p>

<p align="center">
  <a href="https://github.com/AmithKumar1/continuous-agent/actions/workflows/ci.yml"><img src="https://github.com/AmithKumar1/continuous-agent/actions/workflows/ci.yml/badge.svg" alt="CI Suite" /></a>
  <a href="https://github.com/AmithKumar1/continuous-agent/releases"><img src="https://img.shields.io/github/v/release/AmithKumar1/continuous-agent?color=blue&logo=github" alt="Latest Release" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/AmithKumar1/continuous-agent?color=emerald" alt="License: MIT" /></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white" alt="Python" /></a>
  <a href="https://lean-lang.org/"><img src="https://img.shields.io/badge/Verified-Lean_4-purple?logo=lean" alt="Lean 4" /></a>
  <a href="https://wasmtime.dev/"><img src="https://img.shields.io/badge/Sandbox-Wasmtime-654FF0?logo=webassembly&logoColor=white" alt="Wasmtime" /></a>
</p>

> An autonomous neuro-symbolic continuous discovery system integrating a continuous execution heartbeat, cognitive memory with recursive compaction, RRF hybrid RAG search, multi-island evolutionary search (FunSearch), Counterexample-Guided Inductive Synthesis (CEGIS) with Z3, formal verification via Lean 4, dual-tier WASM/gVisor sandboxing, and automated GitHub GitOps PR publishing.

---

## ⚡ Architectural Overview

<p align="center">
  <img src="assets/architecture.svg" alt="Continuous Agent Neuro-Symbolic Architecture" width="100%" />
</p>

<details>
<summary><b>🔍 View Interactive Mermaid Topology</b></summary>

```mermaid
flowchart TD
    %% Styling and Themes
    classDef control fill:#0f172a,stroke:#38bdf8,stroke-width:2px,color:#fff;
    classDef loop fill:#0f172a,stroke:#38bdf8,stroke-width:2px,color:#fff;
    classDef sched fill:#0f172a,stroke:#6366f1,stroke-width:2px,color:#fff;
    classDef memory fill:#0f172a,stroke:#38bdf8,stroke-width:2px,color:#fff;
    classDef engine fill:#064e3b,stroke:#10b981,stroke-width:2px,color:#fff;
    classDef prover fill:#581c87,stroke:#a855f7,stroke-width:2px,color:#fff;
    classDef sandbox fill:#0f172a,stroke:#10b981,stroke-width:2px,color:#fff;
    classDef gitops fill:#0f172a,stroke:#a855f7,stroke-width:2px,color:#fff;

    Deck["<b>FastAPI Real-Time Control Deck</b><br/>(WebSockets, SSE, Telemetry, CEGIS, Lean 4)"]:::control

    Loop["<b>Continuous Agent Loop</b><br/>• Asynchronous Heartbeat<br/>• Multi-Turn Tools<br/>• Circuit Breaker"]:::loop
    Sched["<b>Task Scheduler (Cron)</b><br/>• Live Countdown Deck<br/>• Dynamic Croniter<br/>• Nightly Discovery"]:::sched

    Mem["<b>Cognitive Memory</b><br/>• Working Scratchpad<br/>• Reflexion (Self-Learn)<br/>• Episodic Compaction<br/>• RRF Hybrid Search"]:::memory
    Evol["<b>Evolutionary Engine</b><br/>• FunSearch Service<br/>• Multi-Island Model<br/>• Behavioral Probes<br/>• Strategy Stagnation"]:::engine
    Symb["<b>Neuro-Symbolic & CEGIS</b><br/>• AST-to-Z3 Transpiler<br/>• Singularity / Monotonic<br/>• Dynamic Suite Invariant<br/>• Lean 4 Kernel Prover"]:::prover

    Sand["<b>Dual-Tier Sandboxing</b><br/>• WebAssembly (Fuel Cap)<br/>• 1-Page Linear Memory<br/>• gVisor (runsc) Fallback"]:::sandbox
    Git["<b>GitOps PR Automation</b><br/>• Auto Feature Branch<br/>• Code + Lean Certificate<br/>• GitHub REST API PR Open"]:::gitops

    Deck --> Loop
    Deck --> Sched

    Loop --> Mem
    Loop --> Evol

    Sched --> Evol
    Sched --> Symb

    Evol --> Sand
    Symb --> Git
    Symb -. "<b>CEGIS Invariant Feedback Loop</b>" .-> Evol
```
</details>

---

## 📋 Mandatory Prerequisites

| Layer | Dependency | Fallback / Impact If Missing |
|---|---|---|
| **LLM Provider** | `OPENAI_API_KEY` (or Anthropic/Custom) in `.env` | Island mutations and prompt synthesis require an active API key. |
| **SMT & Formal Proofs** | `elan` (Lean 4 compiler) + `z3-solver` | Synthesizes Lean 4 code; verification requires `elan` toolchain on PATH. |
| **Container Sandbox** | Host Docker daemon with `runsc` (gVisor) runtime | **Automatic fallback**: If Docker is offline, system automatically evaluates programs in-process via WebAssembly or local simulation. |
| **WASM Runtime** | `wasmtime` Python wheel | Sub-millisecond in-process evaluations (<40µs). |
| **GitOps (Optional)** | `GITHUB_TOKEN` + `GITHUB_REPO` | Automated branch, commit, and PR creation via GitHub REST API. |

---

## 🚀 Quickstart

Clone the repository and run the automated bootstrap script:

```bash
git clone https://github.com/AmithKumar1/continuous-agent.git
cd continuous-agent
chmod +x setup.sh
./setup.sh
```

*(Windows users can run `.\setup.ps1` in PowerShell)*

### 1. Configure Secrets

Edit the generated `.env` file with your API credentials:

```bash
nano .env  # Add your OPENAI_API_KEY, AGENT_API_TOKEN, etc.
```

### 2. Launch the Discovery Agent

Activate the isolated environment and boot the FastAPI control dashboard:

```bash
source .venv/bin/activate
python main.py
```

Open **`http://localhost:8000`** in your browser to access the live telemetry pipeline, interactive Z3 invariant probe, and evolutionary island controls.

### 3. Alternative: Run via Docker Compose

```bash
docker compose up --build -d
```

---

### Path B: Bare-Metal Local Machine

If running directly on macOS, Linux, or Windows without Docker:

1. **Install Lean 4 via `elan`** (macOS/Linux):
   ```bash
   curl -sSf https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh | sh -s -- -y --default-toolchain leanprover/lean4:stable
   source $HOME/.elan/env
   ```

2. **Install Python requirements**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Run pre-flight verification**:
   ```bash
   python preflight.py
   ```

4. **Start the daemon**:
   ```bash
   python main.py
   ```

---

## 🎨 Interactive Control Deck Components

The FastAPI dashboard (`http://localhost:8000`) provides real-time telemetry over WebSockets:

1. **Dynamic Animated SVG Pipeline Flowchart**:
   - Live visual progression: `Islands` ➔ `WASM Sandbox` ➔ `Z3 SMT Prover` ➔ `Lean 4 Kernel` ➔ `GitOps Dispatch`.
   - Reverse rose-tinted CEGIS counterexample feedback beam on invariant violations.
   - Dynamic stage controller with glowing SVG filters.

2. **High-DPI Canvas Radar Chart (`Island Population Dynamics`)**:
   - Multi-axis behavioral tracking across 5 dimensions: *Peak Fitness*, *Cluster Diversity*, *AST Parsimony*, *Throughput*, and *Invariant Soundness*.
   - Retina-scaled rendering (`devicePixelRatio`).
   - Euclidean distance hit-testing (<18px) with pulsing halos and floating glassmorphic tooltip.

3. **Nightly Discovery Scheduler**:
   - Live countdown display for cron-scheduled discovery runs (default `0 2 * * *`).
   - Preset buttons and manual immediate dispatch trigger.

4. **Neuro-Symbolic CEGIS & Lean 4 Prover**:
   - Interactive heuristic editor with Singularity test presets.
   - Live Z3 SMT contract checking with counterexample extraction.
   - Lean 4 formal proof certificate generation and GitHub PR creation.

---

## 🛠️ Testing & Verification

```bash
# Test WebAssembly JIT execution & fuel limits
python test_wasm_sandbox.py

# Test Lean 4 proof synthesis
python test_lean_verify.py

# Run empirical benchmark suite (Falkenauer U120 + Weibull Burst)
python benchmark_efficacy.py
```

---

## 📊 Empirical Verification & Benchmark Baselines

Continuous Agent is benchmarked against classic online bin packing suites (**Falkenauer U120** and **Weibull Burst** distribution streams) comparing discovered heuristics against established human baselines:

| Algorithm / Heuristic | Benchmark Set | Average Utilization | Optimal Bins Delta | Proof Status |
|---|---|---|---|---|
| **Next Fit (NF)** | Falkenauer U120 | 74.8% | +32.4% bins | Baseline |
| **First Fit (FF)** | Falkenauer U120 | 91.7% | +8.0% bins | Baseline |
| **Best Fit (BF)** | Falkenauer U120 | 92.0% | +7.6% bins | Baseline |
| **Discovered Heuristic #1** | Falkenauer U120 | **92.0%** | **+7.6% bins** | **Lean 4 Verified** |
| **Next Fit (NF)** | Weibull Burst | 80.1% | +22.7% bins | Baseline |
| **First Fit (FF)** | Weibull Burst | 95.1% | +3.3% bins | Baseline |
| **Best Fit (BF)** | Weibull Burst | 95.7% | +2.7% bins | Baseline |
| **Discovered Heuristic #1** | Weibull Burst | **95.7%** | **+2.7% bins** | **Lean 4 Verified** |

---

## ⚡ Token Optimization & Defense-in-Depth

1. **Two-Tier Model Routing (80–90% Cost Reduction)**:
   - Routine island mutations are offloaded to local open-weight coding models (`qwen2.5-coder:7b` via Ollama/vLLM).
   - Frontier models (`gpt-4o-mini`) are reserved exclusively for supervisor reflection and population restarts.
2. **Expression-Only AST Diff Prompting**:
   - Prompting is restricted to mathematical return expressions (`return ...`), avoiding ~350 tokens of repetitive boilerplate per evaluation cycle.
3. **Semantic AST Memoization**:
   - Canonicalizes variable names (`bin_capacity` $\rightarrow c$, `item` $\rightarrow i$) and deduplicates structurally identical heuristics in SQLite before evaluation.
4. **Staged Fail-Fast Pipeline**:
   - Evaluates cheap gates first: `AST Allowlist (<1ms)` $\rightarrow$ `WASM Smoke (<50µs)` $\rightarrow$ `Z3 Probe (<15ms)` $\rightarrow$ `Full Benchmarks (<2ms)` $\rightarrow$ `Lean 4 Proofs`.
5. **Zero-Trust AST Guard**:
   - Pure mathematical allowlist (`agent/ast_guard.py`) strictly blocks `import`, `exec()`, `eval()`, `open()`, loops, and dunder attribute access before code execution.

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
- **Authentication**: REST API and WebSocket channels secured via `X-API-Key` or `Authorization: Bearer <token>`.

---

## 📄 License

MIT License. See [LICENSE](LICENSE) for details.
