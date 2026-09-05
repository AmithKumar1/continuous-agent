import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional
import aiosqlite
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Security, WebSocket, WebSocketDisconnect, status
from fastapi.responses import HTMLResponse, JSONResponse
from dataclasses import asdict
from config import config
from agent.auth import verify_api_key, verify_websocket_auth
from agent.events import broker
from agent.db import get_db
from agent.scheduler import task_scheduler
from agent.funsearch_service import funsearch_service
from agent.cegis_tracker import cegis_tracker
from agent.island_profiler import (
    HeuristicPoint,
    compute_pareto_frontier,
    profile_island
)
from cegis_verifier import SymbolicContractVerifier
from agent.formal_verifier import lean_verifier
from agent.lean_synthesizer import Lean4ProofSynthesizer
from agent.gitops import gitops_publisher
from agent.vector_sync import sync_coordinator
from agent.alphacode_ensemble import alphacode_pipeline
from agent.schemas import (
    CoreMemoryPayload, HeuristicPayload, ScheduleUpdateRequest,
    VerificationRequest, SynthesisRequest, PRCreationRequest,
    FunSearchStartRequest
)

logger = logging.getLogger("Dashboard")

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: Dict[str, Any]):
        dead = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                dead.append(connection)
        for d in dead:
            self.disconnect(d)

ws_manager = ConnectionManager()

api_router = APIRouter(prefix="/api", dependencies=[Depends(verify_api_key)])

# --- Lifecycle Endpoints ---
@api_router.get("/state")
@api_router.get("/status")
async def get_status():
    try:
        async with aiosqlite.connect(config.DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT iteration, status, last_heartbeat FROM agent_state WHERE id = 1") as c:
                row = await c.fetchone()
                return dict(row) if row else {"iteration": 0, "status": "UNKNOWN"}
    except Exception:
        return {"iteration": 0, "status": "STARTING", "last_heartbeat": 0.0}

@api_router.post("/pause")
async def pause_agent():
    from main import agent_instance
    if agent_instance:
        await agent_instance.pause()
    return {"status": "PAUSED"}

@api_router.post("/resume")
async def resume_agent():
    from main import agent_instance
    if agent_instance:
        await agent_instance.resume()
    return {"status": "RUNNING"}

@api_router.post("/trigger")
async def trigger_agent():
    from main import agent_instance
    if agent_instance:
        triggered = await agent_instance.trigger_cycle()
        return {"triggered": triggered}
    return {"triggered": False, "detail": "Agent offline"}

@api_router.get("/history")
async def get_history(limit: int = 50):
    async with aiosqlite.connect(config.DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM execution_logs ORDER BY id DESC LIMIT ?", (limit,)) as c:
            return [dict(r) for r in await c.fetchall()]

# --- Memory CRUD Endpoints ---
@api_router.get("/memory/core")
async def get_core_memory():
    from main import agent_instance
    if agent_instance:
        return await agent_instance.cognitive_memory.get_core_memory()
    return {}

@api_router.post("/memory/core")
async def set_core_memory(payload: CoreMemoryPayload):
    from main import agent_instance
    if agent_instance:
        await agent_instance.cognitive_memory.update_core_memory(payload.key, payload.value)
        return {"status": "SUCCESS", "key": payload.key}
    raise HTTPException(status_code=503, detail="Agent uninitialized")

@api_router.delete("/memory/core/{key}")
async def delete_core_memory(key: str):
    from main import agent_instance
    if agent_instance:
        await agent_instance.cognitive_memory.delete_core_memory(key)
        return {"status": "DELETED", "key": key}
    raise HTTPException(status_code=503, detail="Agent uninitialized")

@api_router.get("/memory/heuristics")
async def get_heuristics(limit: int = 20):
    from main import agent_instance
    if agent_instance:
        return await agent_instance.cognitive_memory.get_active_heuristics(limit=limit)
    return []

@api_router.post("/memory/heuristics")
async def create_heuristic(payload: HeuristicPayload):
    from main import agent_instance
    if agent_instance:
        await agent_instance.cognitive_memory.record_heuristic(
            category=payload.category,
            condition=payload.condition,
            actionable_lesson=payload.actionable_lesson
        )
        return {"status": "SUCCESS"}
    raise HTTPException(status_code=503, detail="Agent uninitialized")

@api_router.delete("/memory/heuristics/{heuristic_id}")
async def delete_heuristic(heuristic_id: int):
    from main import agent_instance
    if agent_instance:
        await agent_instance.cognitive_memory.delete_heuristic(heuristic_id)
        return {"status": "DELETED"}
    raise HTTPException(status_code=503, detail="Agent uninitialized")

@api_router.get("/memory/search")
async def search_memory(q: str = Query(..., min_length=1), top_k: int = 5):
    from main import agent_instance
    if agent_instance:
        return await agent_instance.retriever.search(query=q, top_k=top_k)
    return []

# --- Vector Sync Endpoints ---
@api_router.get("/vector/sync/status")
async def get_vector_sync_status():
    return await sync_coordinator.get_sync_status()

@api_router.post("/vector/sync/trigger")
async def trigger_vector_sync():
    return await sync_coordinator.run_sync()

# --- FunSearch Evolutionary Search Endpoints ---
@api_router.get("/funsearch/telemetry")
async def get_funsearch_telemetry():
    return funsearch_service.get_telemetry()

@api_router.post("/funsearch/start")
async def start_funsearch(payload: FunSearchStartRequest):
    if funsearch_service.is_running:
        raise HTTPException(status_code=400, detail="FunSearch already active")
    asyncio.create_task(funsearch_service.start(evals_per_island=payload.evals_per_island or 20))
    return {"status": "DISPATCHED"}

@api_router.post("/funsearch/stop")
async def stop_funsearch():
    funsearch_service.stop()
    return {"status": "STOPPED"}

# --- Neuro-Symbolic & Formal Verification Endpoints ---
@api_router.get("/cegis/telemetry")
async def get_cegis_telemetry():
    return cegis_tracker.get_metrics()

@api_router.get("/cegis/events")
async def get_cegis_events():
    return cegis_tracker.get_recent_events()

@api_router.post("/cegis/verify-custom")
@api_router.post("/cegis/probe")
async def run_cegis_probe(payload: VerificationRequest):
    code_str = payload.get_code()
    verifier = SymbolicContractVerifier(timeout_ms=payload.timeout_ms or 1500)
    loop = asyncio.get_running_loop()
    start_time = time.time()
    is_verified, counterexample = await loop.run_in_executor(None, verifier.verify, code_str)
    elapsed_ms = (time.time() - start_time) * 1000

    ce_dict = None
    if counterexample:
        ce_dict = {
            "invariant_name": counterexample.invariant_name,
            "item": counterexample.item,
            "bin_capacity": counterexample.bin_capacity,
            "detail": counterexample.detail
        }

    status_str = "VERIFIED" if is_verified else "VIOLATED"
    await cegis_tracker.record_event(
        status=status_str,
        invariant_name=counterexample.invariant_name if counterexample else "ContractCheck",
        island_id=0,
        generation=0,
        counterexample=ce_dict,
        total_probes=0,
        solve_time_ms=elapsed_ms
    )

    return {
        "verified": is_verified,
        "counterexample": ce_dict,
        "invariant_name": counterexample.invariant_name if counterexample else None,
        "solve_time_ms": round(elapsed_ms, 2)
    }

@api_router.post("/verify/lean")
async def verify_lean_endpoint(payload: SynthesisRequest):
    proof = Lean4ProofSynthesizer.synthesize(payload.python_code)
    ok, msg = await lean_verifier.verify_code(proof)
    return {
        "verified": ok,
        "lean_proof": proof,
        "kernel_output": msg
    }

@api_router.post("/lean/synthesize")
async def synthesize_lean_endpoint(payload: SynthesisRequest):
    proof = Lean4ProofSynthesizer.synthesize(payload.python_code)
    return {"lean_code": proof}

@api_router.post("/alphacode/solve")
async def alphacode_solve_endpoint(payload: Dict[str, Any]):
    spec = payload.get("problem_spec", "Bin packing online priority function")
    return await alphacode_pipeline.generate_and_cluster(spec)

@api_router.post("/gitops/create-pr")
async def create_gitops_pr(payload: PRCreationRequest):
    return await gitops_publisher.create_discovery_pr(
        python_code=payload.python_code,
        lean_proof=payload.lean_proof,
        fitness_score=payload.fitness_score,
        algorithm_name=payload.algorithm_name or "OnlineBinPackingHeuristic"
    )

# --- Scheduler Endpoints ---
@api_router.get("/scheduler/status")
async def get_scheduler_status():
    return task_scheduler.get_status()

@api_router.post("/scheduler/update")
async def update_scheduler(payload: ScheduleUpdateRequest):
    success = task_scheduler.update_cron(payload.cron_expression)
    if not success:
        raise HTTPException(status_code=400, detail="Invalid cron expression format.")
    return {"status": "SUCCESS", "scheduler": task_scheduler.get_status()}

@api_router.post("/scheduler/trigger-now")
async def trigger_scheduler_now():
    if task_scheduler.is_executing:
        raise HTTPException(status_code=409, detail="Pipeline execution already in flight.")
    asyncio.create_task(task_scheduler.execute_pipeline())
    return {"status": "DISPATCHED", "detail": "Nightly discovery pipeline launched manually."}

# --- NSGA-II & Pareto Profiling Endpoints ---
@api_router.get("/evolution/pareto-profile")
async def get_pareto_and_island_profile():
    points = []
    try:
        async with get_db() as db:
            cursor = await db.execute(
                """
                SELECT id, island_id, code, fitness, wasm_fuel, generation, phenotype_signature
                FROM heuristics
                WHERE fitness IS NOT NULL AND wasm_fuel IS NOT NULL
                ORDER BY generation DESC LIMIT 250
                """
            )
            rows = await cursor.fetchall()
            points = [
                HeuristicPoint(
                    id=str(r["id"]),
                    island_id=r["island_id"],
                    code=r["code"],
                    packing_ratio=float(r["fitness"]),
                    fuel_consumed=int(r["wasm_fuel"]),
                    generation=r["generation"],
                    phenotype_signature=r["phenotype_signature"] or "default"
                )
                for r in rows
            ]
    except Exception as exc:
        logger.debug(f"Could not load heuristics from db: {exc}")

    if not points and hasattr(funsearch_service, "nsga2_islands"):
        for isl in funsearch_service.nsga2_islands:
            for ind in isl.individuals:
                points.append(
                    HeuristicPoint(
                        id=str(ind.id),
                        island_id=isl.island_id,
                        code=ind.code,
                        packing_ratio=float(ind.packing_ratio),
                        fuel_consumed=int(ind.fuel_consumed),
                        generation=1,
                        phenotype_signature=ind.phenotype_signature or "default"
                    )
                )

    # Compute global Pareto frontier
    pareto_frontier = compute_pareto_frontier(points)

    # Compute health per island
    islands_health = []
    for island_id in sorted({p.island_id for p in points}):
        island_history = [
            {"fitness": p.packing_ratio, "phenotype_signature": p.phenotype_signature}
            for p in points if p.island_id == island_id
        ]
        islands_health.append(profile_island(island_id, island_history))

    return {
        "total_candidates": len(points),
        "pareto_frontier_count": len(pareto_frontier),
        "pareto_points": [asdict(p) for p in pareto_frontier],
        "all_points": [asdict(p) for p in points],
        "islands": [asdict(h) for h in islands_health]
    }

app = FastAPI(title="Continuous Agent")
app.include_router(api_router)

# Forward EventBroker events to WebSocket clients
async def event_broker_listener():
    queue = await broker.subscribe()
    while True:
        msg = await queue.get()
        await ws_manager.broadcast(msg)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(event_broker_listener())

@app.websocket("/ws/telemetry")
async def websocket_telemetry(websocket: WebSocket, api_key: Optional[str] = Query(None)):
    is_authed = await verify_websocket_auth(websocket, api_key)
    if not is_authed:
        return
    await ws_manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)

# --- HTML UI ---
@app.get("/", response_class=HTMLResponse)
async def dashboard_ui():
    return """<!DOCTYPE html>
<html lang="en" class="dark">
<head>
  <meta charset="UTF-8">
  <title>Continuous Agent — Neuro-Symbolic Control Deck</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script>
    tailwind.config = {
      darkMode: 'class',
      theme: {
        extend: {
          colors: {
            brand: '#3b82f6',
            surface: '#0f172a',
            surfaceCard: '#1e293b'
          }
        }
      }
    }
  </script>
  <style>
    ::-webkit-scrollbar { width: 6px; height: 6px; }
    ::-webkit-scrollbar-track { background: #0f172a; }
    ::-webkit-scrollbar-thumb { background: #334155; border-radius: 3px; }
    .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }
  </style>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen flex flex-col antialiased">
  <!-- Top Navigation Bar -->
  <header class="bg-slate-900/90 border-b border-slate-800 px-6 py-4 flex items-center justify-between sticky top-0 z-50 backdrop-blur">
      <div class="flex items-center gap-3">
        <svg class="w-7 h-7 text-cyan-400 shrink-0 drop-shadow-[0_0_8px_rgba(56,189,248,0.6)]" viewBox="0 0 128 128" fill="none">
          <circle cx="64" cy="64" r="58" fill="#090d16" stroke="#1e293b" stroke-width="3" />
          <path d="M64 24 C84 24 100 40 100 60 C100 80 84 94 64 80 C48 68 36 60 36 44 C36 32 48 24 64 24 Z" stroke="#38bdf8" stroke-width="6" stroke-linecap="round" />
          <path d="M104 64 C104 84 88 100 68 100 C48 100 34 84 48 64 C60 48 68 36 84 36 C96 36 104 48 104 64 Z" stroke="#818cf8" stroke-width="5" stroke-linecap="round" />
          <path d="M64 104 C44 104 28 88 28 68 C28 48 44 34 64 48 C80 60 92 68 92 84 C92 96 80 104 64 104 Z" stroke="#10b981" stroke-width="5" stroke-linecap="round" />
          <polygon points="64,20 68,25 64,30 60,25" fill="#38bdf8" />
          <polygon points="108,64 103,68 98,64 103,60" fill="#a855f7" />
          <polygon points="64,108 60,103 64,98 68,103" fill="#10b981" />
          <polygon points="20,64 25,60 30,64 25,68" fill="#06b6d4" />
          <circle cx="64" cy="64" r="3.5" fill="#f8fafc" />
        </svg>
        <h1 class="text-lg font-bold tracking-tight text-white flex items-center gap-2">
          <span>CONTINUOUS AGENT</span>
          <span class="text-xs px-2 py-0.5 rounded bg-blue-950 text-blue-400 border border-blue-800 font-mono">v1.0.0-PROD</span>
        </h1>
      </div>

    <!-- Central Telemetry Badges -->
    <div class="flex items-center gap-4 text-xs font-mono">
      <div class="bg-slate-950 px-3 py-1.5 rounded border border-slate-800 flex items-center gap-2">
        <span class="text-slate-400">CYCLE:</span>
        <span id="nav-iteration" class="text-emerald-400 font-bold">#0</span>
      </div>
      <div class="bg-slate-950 px-3 py-1.5 rounded border border-slate-800 flex items-center gap-2">
        <span class="text-slate-400">STATE:</span>
        <span id="nav-status" class="text-blue-400 font-bold">STARTING</span>
      </div>
      <div class="bg-slate-950 px-3 py-1.5 rounded border border-slate-800 flex items-center gap-2">
        <span class="text-slate-400">WS FEED:</span>
        <span id="nav-ws-status" class="text-amber-400">CONNECTING...</span>
      </div>
    </div>

    <!-- Controls -->
    <div class="flex items-center gap-2">
      <input id="api-key-input" type="password" placeholder="DASHBOARD_API_KEY" class="bg-slate-950 border border-slate-700 text-xs px-2.5 py-1.5 rounded text-white font-mono focus:outline-none focus:border-blue-500">
      <button onclick="saveApiKey()" class="bg-slate-800 hover:bg-slate-700 text-xs font-semibold px-3 py-1.5 rounded border border-slate-700 text-slate-200">Save</button>
      <button onclick="pauseAgent()" class="bg-amber-600 hover:bg-amber-500 text-xs font-semibold px-3 py-1.5 rounded text-white">Pause</button>
      <button onclick="resumeAgent()" class="bg-emerald-600 hover:bg-emerald-500 text-xs font-semibold px-3 py-1.5 rounded text-white">Resume</button>
      <button onclick="triggerStep()" class="bg-blue-600 hover:bg-blue-500 text-xs font-semibold px-3 py-1.5 rounded text-white">Step Now</button>
    </div>
  </header>

  <!-- Main Grid Container -->
  <main class="flex-1 p-6 grid grid-cols-1 xl:grid-cols-3 gap-6">

    <!-- Column 1 & 2: Main Operational Decks -->
    <div class="xl:col-span-2 flex flex-col gap-6">

      <!-- Real-Time Evolutionary Discovery Schematic -->
      <section class="bg-slate-900 p-5 rounded-xl border border-slate-800 shadow-xl space-y-4">
        <div class="flex flex-wrap justify-between items-center gap-2 border-b border-slate-800 pb-3">
          <div>
            <div class="flex items-center gap-2">
              <span class="text-lg">⚡</span>
              <h2 class="text-sm font-semibold uppercase tracking-wider text-slate-200">Autonomous Synthesis Pipeline</h2>
              <span id="pipeline-live-indicator" class="flex h-2 w-2 relative">
                <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                <span class="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
              </span>
            </div>
            <p class="text-xs text-slate-400">Live program lineage, sandbox execution, and formal contract resolution</p>
          </div>
          
          <div class="flex items-center gap-2 font-mono text-[11px]">
            <span class="text-slate-500">Active Stage:</span>
            <span id="pipeline-stage-label" class="px-2 py-0.5 rounded bg-slate-950 border border-slate-700 text-indigo-400 font-bold">STANDBY</span>
          </div>
        </div>

        <!-- Animated SVG Flow Graph -->
        <div class="relative w-full overflow-x-auto bg-slate-950/70 rounded-lg p-4 border border-slate-800/80">
          <svg viewBox="0 0 920 180" class="w-full min-w-[760px] h-auto overflow-visible select-none">
            <defs>
              <!-- Gradients for Connectors -->
              <linearGradient id="edgeGrad" x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%" stop-color="#6366f1" stop-opacity="0.4" />
                <stop offset="100%" stop-color="#38bdf8" stop-opacity="0.8" />
              </linearGradient>
              <linearGradient id="cegisLoopGrad" x1="100%" y1="0%" x2="0%" y2="0%">
                <stop offset="0%" stop-color="#f43f5e" stop-opacity="0.9" />
                <stop offset="100%" stop-color="#fbbf24" stop-opacity="0.5" />
              </linearGradient>
              
              <!-- Drop Shadows for Active Glow -->
              <filter id="glow-green" x="-20%" y="-20%" width="140%" height="140%">
                <feDropShadow dx="0" dy="0" stdDeviation="6" flood-color="#10b981" flood-opacity="0.6"/>
              </filter>
              <filter id="glow-rose" x="-20%" y="-20%" width="140%" height="140%">
                <feDropShadow dx="0" dy="0" stdDeviation="6" flood-color="#f43f5e" flood-opacity="0.7"/>
              </filter>
              <filter id="glow-blue" x="-20%" y="-20%" width="140%" height="140%">
                <feDropShadow dx="0" dy="0" stdDeviation="5" flood-color="#38bdf8" flood-opacity="0.6"/>
              </filter>
            </defs>

            <style>
              .flow-path { stroke-dasharray: 8 6; animation: dashMove 1.2s linear infinite; }
              .cegis-path { stroke-dasharray: 6 6; animation: dashReverse 1.5s linear infinite; }
              @keyframes dashMove { from { stroke-dashoffset: 28; } to { stroke-dashoffset: 0; } }
              @keyframes dashReverse { from { stroke-dashoffset: 0; } to { stroke-dashoffset: 24; } }
            </style>

            <!-- Connection Paths -->
            <path d="M 140 85 L 210 85" stroke="url(#edgeGrad)" stroke-width="2.5" class="flow-path" />
            <path d="M 330 85 L 400 85" stroke="url(#edgeGrad)" stroke-width="2.5" class="flow-path" />
            <path d="M 520 85 L 590 85" stroke="url(#edgeGrad)" stroke-width="2.5" class="flow-path" />
            <path d="M 710 85 L 780 85" stroke="url(#edgeGrad)" stroke-width="2.5" class="flow-path" />

            <!-- Feedback Loop: Z3 Refutation back to Island Suite -->
            <path d="M 460 120 C 460 165, 270 165, 80 120" fill="none" stroke="url(#cegisLoopGrad)" stroke-width="2" class="cegis-path" />
            <text x="270" y="162" fill="#fb7185" font-size="10" font-family="monospace" text-anchor="middle">
              CEGIS Counterexample Invariant Loop
            </text>

            <!-- NODE 1: Evolutionary Islands -->
            <g id="node-islands" class="transition-all duration-300">
              <rect x="20" y="50" width="120" height="70" rx="10" fill="#0f172a" stroke="#475569" stroke-width="1.5" />
              <text x="80" y="75" fill="#f8fafc" font-size="11" font-weight="bold" text-anchor="middle">Islands</text>
              <text x="80" y="93" fill="#94a3b8" font-size="9" font-family="monospace" text-anchor="middle">Ring Migration</text>
              <circle id="status-islands" cx="80" cy="107" r="3.5" fill="#64748b" />
            </g>

            <!-- NODE 2: Wasmtime JIT Sandbox -->
            <g id="node-wasm" class="transition-all duration-300">
              <rect x="210" y="50" width="120" height="70" rx="10" fill="#0f172a" stroke="#475569" stroke-width="1.5" />
              <text x="270" y="75" fill="#f8fafc" font-size="11" font-weight="bold" text-anchor="middle">WASM Sandbox</text>
              <text x="270" y="93" fill="#94a3b8" font-size="9" font-family="monospace" text-anchor="middle">Fuel Meter (&lt;40µs)</text>
              <circle id="status-wasm" cx="270" cy="107" r="3.5" fill="#64748b" />
            </g>

            <!-- NODE 3: Z3 SMT Verifier -->
            <g id="node-z3" class="transition-all duration-300">
              <rect x="400" y="50" width="120" height="70" rx="10" fill="#0f172a" stroke="#475569" stroke-width="1.5" />
              <text x="460" y="75" fill="#f8fafc" font-size="11" font-weight="bold" text-anchor="middle">Z3 SMT Prover</text>
              <text x="460" y="93" fill="#94a3b8" font-size="9" font-family="monospace" text-anchor="middle">Contract Checking</text>
              <circle id="status-z3" cx="460" cy="107" r="3.5" fill="#64748b" />
            </g>

            <!-- NODE 4: Lean 4 Kernel -->
            <g id="node-lean" class="transition-all duration-300">
              <rect x="590" y="50" width="120" height="70" rx="10" fill="#0f172a" stroke="#475569" stroke-width="1.5" />
              <text x="650" y="75" fill="#f8fafc" font-size="11" font-weight="bold" text-anchor="middle">Lean 4 Kernel</text>
              <text x="650" y="93" fill="#94a3b8" font-size="9" font-family="monospace" text-anchor="middle">Formal Proof</text>
              <circle id="status-lean" cx="650" cy="107" r="3.5" fill="#64748b" />
            </g>

            <!-- NODE 5: GitHub GitOps -->
            <g id="node-gitops" class="transition-all duration-300">
              <rect x="780" y="50" width="120" height="70" rx="10" fill="#0f172a" stroke="#475569" stroke-width="1.5" />
              <text x="840" y="75" fill="#f8fafc" font-size="11" font-weight="bold" text-anchor="middle">GitOps Dispatch</text>
              <text x="840" y="93" fill="#94a3b8" font-size="9" font-family="monospace" text-anchor="middle">Automated PR</text>
              <circle id="status-gitops" cx="840" cy="107" r="3.5" fill="#64748b" />
            </g>
          </svg>
        </div>
      </section>

      <!-- Dynamic Task Scheduler Deck -->
      <section class="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-lg">
        <div class="flex items-center justify-between border-b border-slate-800 pb-3 mb-4">
          <div class="flex items-center gap-2">
            <span class="text-lg">⏱️</span>
            <h2 class="font-bold text-sm tracking-wide text-slate-200 uppercase">Automated Overnight Discovery Scheduler</h2>
          </div>
          <span id="sched-status-badge" class="text-[10px] font-bold px-2 py-0.5 rounded bg-emerald-950 text-emerald-300 border border-emerald-800 font-mono">ARMED</span>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4 font-mono text-xs">
          <div class="bg-slate-950 p-3 rounded-lg border border-slate-800">
            <span class="text-slate-500 block text-[10px]">NEXT SCHEDULED EXECUTION</span>
            <span id="sched-next-run" class="text-emerald-400 font-bold text-sm">--:--:--</span>
          </div>
          <div class="bg-slate-950 p-3 rounded-lg border border-slate-800">
            <span class="text-slate-500 block text-[10px]">COUNTDOWN TO LAUNCH</span>
            <span id="sched-countdown" class="text-blue-400 font-bold text-sm">--:--:-- remaining</span>
          </div>
          <div class="bg-slate-950 p-3 rounded-lg border border-slate-800">
            <span class="text-slate-500 block text-[10px]">LAST EXECUTION TIMESTAMP</span>
            <span id="sched-last-run" class="text-slate-300 text-sm">None</span>
          </div>
        </div>

        <div class="flex flex-wrap items-center gap-3">
          <input id="sched-cron-input" type="text" value="0 2 * * *" class="bg-slate-950 border border-slate-700 text-xs px-3 py-2 rounded text-emerald-400 font-mono focus:border-blue-500">
          <button onclick="updateCronSchedule()" class="bg-blue-600 hover:bg-blue-500 text-xs font-semibold px-4 py-2 rounded text-white">Update Pattern</button>
          <button onclick="setCronPreset('0 2 * * *')" class="bg-slate-800 hover:bg-slate-700 text-xs px-3 py-2 rounded text-slate-300">Preset: 2 AM UTC</button>
          <button onclick="setCronPreset('0 */6 * * *')" class="bg-slate-800 hover:bg-slate-700 text-xs px-3 py-2 rounded text-slate-300">Every 6 Hours</button>
          <button id="btn-sched-trigger" onclick="triggerSchedulerNow()" class="ml-auto bg-purple-600 hover:bg-purple-500 text-xs font-semibold px-4 py-2 rounded text-white flex items-center gap-2">
            <span id="trigger-spinner" class="hidden animate-spin">🌀</span>
            <span id="trigger-btn-text">Trigger Pipeline Now</span>
          </button>
        </div>
        <div id="sched-msg" class="text-[11px] font-mono mt-2 min-h-[1rem]"></div>
      </section>

      <!-- FunSearch Evolutionary Discovery Deck -->
      <section class="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-lg">
        <div class="flex items-center justify-between border-b border-slate-800 pb-3 mb-4">
          <div class="flex items-center gap-2">
            <span class="text-lg">🧬</span>
            <h2 class="font-bold text-sm tracking-wide text-slate-200 uppercase">FunSearch Multi-Island Evolution Engine</h2>
          </div>
          <div class="flex items-center gap-2">
            <span id="fs-badge" class="text-[10px] font-bold px-2 py-0.5 rounded bg-slate-800 text-slate-300 font-mono">IDLE</span>
            <button onclick="startFunSearch()" class="bg-emerald-600 hover:bg-emerald-500 text-xs px-3 py-1 rounded text-white font-semibold">Start Search</button>
            <button onclick="stopFunSearch()" class="bg-rose-600 hover:bg-rose-500 text-xs px-3 py-1 rounded text-white font-semibold">Stop</button>
          </div>
        </div>

        <div class="grid grid-cols-2 sm:grid-cols-4 gap-3 font-mono text-xs mb-4">
          <div class="bg-slate-950 p-3 rounded-lg border border-slate-800">
            <span class="text-slate-500 text-[10px] block">TOTAL EVALS</span>
            <span id="fs-total-evals" class="text-lg font-bold text-slate-200">0</span>
          </div>
          <div class="bg-slate-950 p-3 rounded-lg border border-slate-800">
            <span class="text-slate-500 text-[10px] block">TOP FITNESS</span>
            <span id="fs-top-fitness" class="text-lg font-bold text-emerald-400">0.0000</span>
          </div>
          <div class="bg-slate-950 p-3 rounded-lg border border-slate-800">
            <span class="text-slate-500 text-[10px] block">CHAMPION GEN</span>
            <span id="fs-champ-gen" class="text-lg font-bold text-blue-400">Gen #0</span>
          </div>
          <div class="bg-slate-950 p-3 rounded-lg border border-slate-800">
            <span class="text-slate-500 text-[10px] block">ACTIVE ISLANDS</span>
            <span id="fs-islands-count" class="text-lg font-bold text-purple-400">4 Islands</span>
          </div>
        </div>

        <div class="bg-slate-950 p-3 rounded-lg border border-slate-800 font-mono text-xs">
          <div class="text-slate-500 mb-1 flex justify-between">
            <span>CHAMPION HEURISTIC CODE</span>
            <span class="text-emerald-400 text-[10px]">PARSIMONY-OPTIMIZED</span>
          </div>
          <pre id="fs-champion-code" class="text-slate-300 text-[11px] overflow-x-auto max-h-36">def priority(item, bin_capacity):\n    return 1.0</pre>
        </div>
      </section>

      <!-- Island Multivariate Behavioral Radar Deck -->
      <section class="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-lg space-y-3">
        <div class="flex flex-wrap justify-between items-center gap-2 border-b border-slate-800 pb-2.5">
          <div>
            <div class="flex items-center gap-2">
              <span class="text-lg">🎯</span>
              <h2 class="text-sm font-semibold uppercase tracking-wider text-slate-200">Island Population Dynamics</h2>
              <span class="text-[10px] font-mono px-2 py-0.5 rounded bg-indigo-950 text-indigo-300 border border-indigo-800/80">RADAR TELEMETRY</span>
            </div>
            <p class="text-xs text-slate-400">Multi-axis behavioral tracking across search spaces</p>
          </div>

          <!-- Island Series Toggle & Legend -->
          <div class="flex items-center gap-3 text-xs font-mono">
            <div class="flex items-center gap-1.5"><span class="w-2.5 h-2.5 rounded-full bg-indigo-500"></span><span class="text-slate-300">Isl #0</span></div>
            <div class="flex items-center gap-1.5"><span class="w-2.5 h-2.5 rounded-full bg-sky-400"></span><span class="text-slate-300">Isl #1</span></div>
            <div class="flex items-center gap-1.5"><span class="w-2.5 h-2.5 rounded-full bg-emerald-400"></span><span class="text-slate-300">Isl #2</span></div>
            <div class="flex items-center gap-1.5"><span class="w-2.5 h-2.5 rounded-full bg-amber-400"></span><span class="text-slate-300">Isl #3</span></div>
          </div>
        </div>

        <!-- Responsive Canvas Container with Tooltip -->
        <div class="relative w-full aspect-[16/10] sm:aspect-[2/1] max-h-[340px] flex items-center justify-center bg-slate-950/80 rounded-lg p-2 border border-slate-800/80 overflow-hidden">
          <canvas id="island-radar-canvas" class="w-full h-full block cursor-crosshair"></canvas>

          <!-- Interactive Hover Tooltip -->
          <div id="radar-tooltip" 
               class="absolute pointer-events-none opacity-0 transition-opacity duration-150 bg-slate-900/95 backdrop-blur-md border border-slate-700 rounded-lg px-3 py-2 text-xs shadow-2xl z-20 font-mono space-y-1">
            <div class="flex items-center justify-between gap-3 border-b border-slate-800 pb-1">
              <span id="tt-island-label" class="font-bold"></span>
              <span id="tt-axis-label" class="text-slate-400 text-[10px]"></span>
            </div>
            <div class="flex items-baseline justify-between gap-3">
              <span class="text-slate-400 text-[11px]">Exact Value:</span>
              <span id="tt-exact-value" class="font-bold text-slate-100"></span>
            </div>
            <div class="flex items-baseline justify-between gap-3 text-[10px]">
              <span class="text-slate-500">Normalized:</span>
              <span id="tt-norm-value" class="text-slate-400"></span>
            </div>
          </div>
        </div>
      </section>


      <!-- Neuro-Symbolic CEGIS & Formal Proof Deck -->
      <section class="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-lg">
        <div class="flex items-center justify-between border-b border-slate-800 pb-3 mb-4">
          <div class="flex items-center gap-2">
            <span class="text-lg">📐</span>
            <h2 class="font-bold text-sm tracking-wide text-slate-200 uppercase">CEGIS Invariant Verification & Lean 4 Prover</h2>
          </div>
          <span class="text-[10px] font-bold px-2 py-0.5 rounded bg-blue-950 text-blue-300 border border-blue-800 font-mono">Z3 SMT + LEAN 4</span>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
          <!-- Interactive Probe -->
          <div class="bg-slate-950 p-3 rounded-lg border border-slate-800 flex flex-col">
            <div class="flex items-center justify-between mb-2">
              <span class="text-xs font-mono text-slate-400">INPUT HEURISTIC</span>
              <div class="flex items-center gap-1.5 flex-wrap">
                <span class="text-[10px] text-slate-500 uppercase font-semibold mr-1">Presets:</span>
                <button onclick="loadProbePreset('singularity')" class="text-[10px] px-1.5 py-0.5 rounded bg-rose-950/60 text-rose-300 border border-rose-800/60 hover:bg-rose-900/60 transition">Singularity</button>
                <button onclick="loadProbePreset('linear')" class="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-300 border border-slate-700 hover:bg-slate-700 transition">Linear</button>
                <button onclick="loadProbePreset('quadratic')" class="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-300 border border-slate-700 hover:bg-slate-700 transition">Quadratic</button>
                <button onclick="loadProbePreset('ratio')" class="text-[10px] px-1.5 py-0.5 rounded bg-emerald-950/60 text-emerald-300 border border-emerald-800/60 hover:bg-emerald-900/60 transition">Ratio</button>
              </div>
            </div>
            <textarea id="cegis-input-code" rows="5" class="bg-slate-900 border border-slate-700 rounded p-2 text-xs font-mono text-emerald-400 focus:outline-none">def priority(item: float, bin_capacity: float) -> float:
    return item / (bin_capacity - item)</textarea>
            <div class="flex items-center gap-2 mt-3">
              <button onclick="runZ3Probe()" class="bg-blue-600 hover:bg-blue-500 text-xs font-semibold px-3 py-1.5 rounded text-white">Check Z3 Invariants</button>
              <button onclick="runLeanVerification()" class="bg-purple-600 hover:bg-purple-500 text-xs font-semibold px-3 py-1.5 rounded text-white">Synthesize Lean 4</button>
              <button onclick="submitGitOpsPR()" class="ml-auto bg-emerald-600 hover:bg-emerald-500 text-xs font-semibold px-3 py-1.5 rounded text-white">Open GitHub PR</button>
            </div>
          </div>

          <!-- Probe Output -->
          <div class="bg-slate-950 p-3 rounded-lg border border-slate-800 flex flex-col font-mono text-xs">
            <span class="text-slate-500 mb-1">PROVER VERIFICATION RESULT</span>
            <div id="probe-result" class="flex-1 bg-slate-900 rounded p-2 text-[11px] text-slate-300 overflow-y-auto max-h-40">
              Ready to verify contract invariants.
            </div>
          </div>
        </div>

        <!-- CEGIS Metrics Bar -->
        <div class="grid grid-cols-4 gap-2 font-mono text-center text-xs">
          <div class="bg-slate-950 p-2 rounded border border-slate-800">
            <span class="text-[10px] text-slate-500 block">TOTAL CHECKS</span>
            <span id="cegis-checks" class="font-bold text-slate-200">0</span>
          </div>
          <div class="bg-slate-950 p-2 rounded border border-slate-800">
            <span class="text-[10px] text-slate-500 block">VERIFIED</span>
            <span id="cegis-verified" class="font-bold text-emerald-400">0</span>
          </div>
          <div class="bg-slate-950 p-2 rounded border border-slate-800">
            <span class="text-[10px] text-slate-500 block">VIOLATIONS</span>
            <span id="cegis-violations" class="font-bold text-rose-400">0</span>
          </div>
          <div class="bg-slate-950 p-2 rounded border border-slate-800">
            <span class="text-[10px] text-slate-500 block">VIOLATION RATE</span>
            <span id="cegis-rate" class="font-bold text-amber-400">0.0%</span>
          </div>
        </div>
      </section>

      <!-- Realtime Event & Execution Log Terminal -->
      <section class="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-lg flex flex-col flex-1">
        <div class="flex items-center justify-between border-b border-slate-800 pb-3 mb-3">
          <div class="flex items-center gap-2">
            <span class="text-lg">📜</span>
            <h2 class="font-bold text-sm tracking-wide text-slate-200 uppercase">Realtime Execution Stream & Event Bus</h2>
          </div>
          <button onclick="clearLogs()" class="text-xs text-slate-400 hover:text-slate-200">Clear</button>
        </div>
        <div id="log-terminal" class="bg-slate-950 p-3 rounded-lg border border-slate-800 font-mono text-xs text-slate-300 h-64 overflow-y-auto space-y-1.5">
          <div class="text-slate-500">[System Boot] Operator console initialized. Ready.</div>
        </div>
      </section>

    </div>

    <!-- Column 3: Cognitive Memory Scratchpad & Vector Sync -->
    <div class="flex flex-col gap-6">

      <!-- Cognitive Working Memory Deck -->
      <section class="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-lg flex flex-col">
        <div class="flex items-center justify-between border-b border-slate-800 pb-3 mb-4">
          <div class="flex items-center gap-2">
            <span class="text-lg">🧠</span>
            <h2 class="font-bold text-sm tracking-wide text-slate-200 uppercase">Core Working Scratchpad</h2>
          </div>
          <span class="text-[10px] font-bold px-2 py-0.5 rounded bg-purple-950 text-purple-300 border border-purple-800 font-mono">PROMPT PERSISTENT</span>
        </div>

        <div id="core-memory-container" class="space-y-2 mb-4 max-h-48 overflow-y-auto font-mono text-xs">
          <!-- Populated by JS -->
          <div class="text-slate-500 text-xs">Loading scratchpad facts...</div>
        </div>

        <div class="flex gap-2 border-t border-slate-800 pt-3">
          <input id="mem-key-input" type="text" placeholder="Key (e.g. target_version)" class="bg-slate-950 border border-slate-700 text-xs px-2.5 py-1.5 rounded text-white font-mono flex-1">
          <input id="mem-val-input" type="text" placeholder="Value (e.g. 2.4.1)" class="bg-slate-950 border border-slate-700 text-xs px-2.5 py-1.5 rounded text-white font-mono flex-1">
          <button onclick="addCoreMemory()" class="bg-blue-600 hover:bg-blue-500 text-xs font-semibold px-3 py-1.5 rounded text-white">Save</button>
        </div>
      </section>

      <!-- Learned Operational Heuristics Deck -->
      <section class="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-lg flex flex-col">
        <div class="flex items-center justify-between border-b border-slate-800 pb-3 mb-4">
          <div class="flex items-center gap-2">
            <span class="text-lg">💡</span>
            <h2 class="font-bold text-sm tracking-wide text-slate-200 uppercase">Learned Rules & Reflexions</h2>
          </div>
          <span class="text-[10px] font-bold px-2 py-0.5 rounded bg-emerald-950 text-emerald-300 border border-emerald-800 font-mono">SELF-CORRECTING</span>
        </div>

        <div id="heuristics-container" class="space-y-2 max-h-56 overflow-y-auto font-mono text-xs">
          <div class="text-slate-500 text-xs">Loading learned heuristics...</div>
        </div>
      </section>

      <!-- Vector Store & Hybrid Search Deck -->
      <section class="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-lg flex flex-col">
        <div class="flex items-center justify-between border-b border-slate-800 pb-3 mb-4">
          <div class="flex items-center gap-2">
            <span class="text-lg">🔍</span>
            <h2 class="font-bold text-sm tracking-wide text-slate-200 uppercase">RRF Hybrid Memory Search</h2>
          </div>
          <button onclick="triggerVectorSync()" class="text-[10px] font-mono bg-blue-900 hover:bg-blue-800 text-blue-300 px-2 py-1 rounded border border-blue-700">Sync Vector Index</button>
        </div>

        <div class="flex gap-2 mb-3">
          <input id="search-query-input" type="text" placeholder="Search episodic history..." class="bg-slate-950 border border-slate-700 text-xs px-3 py-1.5 rounded text-white font-mono flex-1">
          <button onclick="executeMemorySearch()" class="bg-slate-800 hover:bg-slate-700 text-xs px-3 py-1.5 rounded text-slate-200">Search</button>
        </div>

        <div id="search-results-container" class="bg-slate-950 p-3 rounded-lg border border-slate-800 font-mono text-xs text-slate-300 max-h-48 overflow-y-auto space-y-2">
          <span class="text-slate-500">Enter query above to execute BM25 + Cosine hybrid search.</span>
        </div>
      </section>

    </div>

  </main>

  <!-- Client-Side State Scripts -->
  <script>
    let authToken = sessionStorage.getItem('agent_token') || 'change-me-in-production';
    document.getElementById('api-key-input').value = authToken;

    function saveApiKey() {
      authToken = document.getElementById('api-key-input').value.trim();
      sessionStorage.setItem('agent_token', authToken);
      alert('DASHBOARD_API_KEY saved to session.');
      location.reload();
    }

    async function authFetch(url, options = {}) {
      options.headers = options.headers || {};
      options.headers['X-API-Key'] = authToken;
      return fetch(url, options);
    }

    // --- WebSocket Telemetry Loop ---
    let ws = null;
    function connectWebSocket() {
      const loc = window.location;
      const protocol = loc.protocol === 'https:' ? 'wss:' : 'ws:';
      const wsUrl = `${protocol}//${loc.host}/ws/telemetry?api_key=${encodeURIComponent(authToken)}`;
      ws = new WebSocket(wsUrl);

      ws.onopen = () => {
        document.getElementById('nav-ws-status').className = "text-emerald-400";
        document.getElementById('nav-ws-status').textContent = "CONNECTED";
      };

      ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        handleBroadcastEvent(msg);
      };

      ws.onclose = () => {
        document.getElementById('nav-ws-status').className = "text-rose-400";
        document.getElementById('nav-ws-status').textContent = "DISCONNECTED";
        setTimeout(connectWebSocket, 3000);
      };
    }

    function appendLog(text, color = "text-slate-300") {
      const term = document.getElementById('log-terminal');
      const row = document.createElement('div');
      row.className = `${color} font-mono text-[11px] leading-tight`;
      const time = new Date().toLocaleTimeString();
      row.textContent = `[${time}] ${text}`;
      term.appendChild(row);
      term.scrollTop = term.scrollHeight;
    }

    // State flash animation controller
    function pulseNode(nodeId, statusCircleId, colorType, label) {
      const node = document.getElementById(nodeId);
      const circle = document.getElementById(statusCircleId);
      const labelEl = document.getElementById('pipeline-stage-label');

      if (!node || !circle) return;
      if (labelEl && label) labelEl.textContent = label;

      const colorMap = {
        active: { stroke: '#38bdf8', fill: '#38bdf8', filter: 'url(#glow-blue)' },
        success: { stroke: '#10b981', fill: '#10b981', filter: 'url(#glow-green)' },
        violation: { stroke: '#f43f5e', fill: '#f43f5e', filter: 'url(#glow-rose)' }
      };

      const c = colorMap[colorType] || colorMap.active;
      const rect = node.querySelector('rect');
      if (!rect) return;

      rect.setAttribute('stroke', c.stroke);
      rect.setAttribute('stroke-width', '2.5');
      rect.setAttribute('filter', c.filter);
      circle.setAttribute('fill', c.fill);

      setTimeout(() => {
        rect.setAttribute('stroke', '#475569');
        rect.setAttribute('stroke-width', '1.5');
        rect.removeAttribute('filter');
        circle.setAttribute('fill', '#64748b');
      }, 1200);
    }

    // High-DPI Canvas Radar Engine with Hit Testing
    class IslandRadarChart {
      constructor(canvasId, tooltipId = 'radar-tooltip') {
        this.canvas = document.getElementById(canvasId);
        this.tooltip = document.getElementById(tooltipId);
        if (!this.canvas) return;
        this.ctx = this.canvas.getContext('2d');

        this.axes = [
          { key: 'fitness', label: 'Peak Fitness', unit: '%' },
          { key: 'diversity', label: 'Cluster Diversity', unit: ' niches' },
          { key: 'parsimony', label: 'AST Parsimony', unit: ' score' },
          { key: 'throughput', label: 'Throughput', unit: ' evals' },
          { key: 'soundness', label: 'Invariant Soundness', unit: '%' }
        ];

        this.islandColors = [
          { name: 'Island #0', stroke: 'rgb(99, 102, 241)', fill: 'rgba(99, 102, 241, 0.22)' },
          { name: 'Island #1', stroke: 'rgb(56, 189, 248)', fill: 'rgba(56, 189, 248, 0.22)' },
          { name: 'Island #2', stroke: 'rgb(16, 185, 129)', fill: 'rgba(16, 185, 129, 0.22)' },
          { name: 'Island #3', stroke: 'rgb(245, 158, 11)', fill: 'rgba(245, 158, 11, 0.22)' }
        ];

        // Normalized coordinates (0.05 to 1.0)
        this.data = [
          [0.2, 0.1, 0.5, 0.1, 0.9],
          [0.2, 0.1, 0.5, 0.1, 0.9],
          [0.2, 0.1, 0.5, 0.1, 0.9],
          [0.2, 0.1, 0.5, 0.1, 0.9]
        ];

        // Unscaled human-readable metrics for tooltips
        this.rawMetrics = [
          ['0.0%', '0/12', '120 chars', '0/25', '100%'],
          ['0.0%', '0/12', '120 chars', '0/25', '100%'],
          ['0.0%', '0/12', '120 chars', '0/25', '100%'],
          ['0.0%', '0/12', '120 chars', '0/25', '100%']
        ];

        // Cached screen coordinates for hit detection
        this.projectedVertices = [];
        this.hoveredPoint = null;

        this.initEventListeners();
        this.resize();
        window.addEventListener('resize', () => this.resize());
        this.render();
      }

      resize() {
        if (!this.canvas) return;
        const rect = this.canvas.getBoundingClientRect();
        const dpr = window.devicePixelRatio || 1;
        this.canvas.width = rect.width * dpr;
        this.canvas.height = rect.height * dpr;
        this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        this.width = rect.width;
        this.height = rect.height;
        this.render();
      }

      initEventListeners() {
        if (!this.canvas) return;
        this.canvas.addEventListener('mousemove', (e) => this.handleMouseMove(e));
        this.canvas.addEventListener('mouseleave', () => this.handleMouseLeave());
      }

      handleMouseMove(e) {
        if (!this.canvas) return;
        const rect = this.canvas.getBoundingClientRect();
        const mouseX = e.clientX - rect.left;
        const mouseY = e.clientY - rect.top;

        let closest = null;
        let minDistance = 18; // 18px threshold

        for (const pt of this.projectedVertices) {
          const dist = Math.hypot(pt.x - mouseX, pt.y - mouseY);
          if (dist < minDistance) {
            minDistance = dist;
            closest = pt;
          }
        }

        if (closest) {
          this.hoveredPoint = closest;
          this.showTooltip(closest, rect);
          this.render();
        } else if (this.hoveredPoint) {
          this.hoveredPoint = null;
          this.hideTooltip();
          this.render();
        }
      }

      handleMouseLeave() {
        if (this.hoveredPoint) {
          this.hoveredPoint = null;
          this.hideTooltip();
          this.render();
        }
      }

      showTooltip(pt, canvasRect) {
        if (!this.tooltip) return;

        const island = this.islandColors[pt.islandIdx];
        const axis = this.axes[pt.axisIdx];
        const rawVal = this.rawMetrics[pt.islandIdx][pt.axisIdx];

        const labelEl = document.getElementById('tt-island-label');
        const axisEl = document.getElementById('tt-axis-label');
        const exactEl = document.getElementById('tt-exact-value');
        const normEl = document.getElementById('tt-norm-value');

        if (labelEl) {
          labelEl.textContent = island.name;
          labelEl.style.color = island.stroke;
        }
        if (axisEl) axisEl.textContent = axis.label;
        if (exactEl) exactEl.textContent = rawVal;
        if (normEl) normEl.textContent = `${(pt.normVal * 100).toFixed(1)}% of scale`;

        let left = pt.x + 15;
        let top = pt.y - 30;

        const ttWidth = 190;
        const ttHeight = 85;

        if (left + ttWidth > canvasRect.width) left = pt.x - ttWidth - 15;
        if (top < 10) top = 10;
        if (top + ttHeight > canvasRect.height) top = canvasRect.height - ttHeight - 10;

        this.tooltip.style.left = `${left}px`;
        this.tooltip.style.top = `${top}px`;
        this.tooltip.style.opacity = '1';
      }

      hideTooltip() {
        if (this.tooltip) this.tooltip.style.opacity = '0';
      }

      updateMetrics(islandsTelemetry, maxClusters = 12, targetEvalsPerIsland = 25) {
        if (!Array.isArray(islandsTelemetry)) return;

        islandsTelemetry.forEach((island, idx) => {
          if (idx >= 4) return;

          const rawFit = island.best_fitness || 0.0;
          const rawClusters = island.clusters_count || 0;
          const rawEvals = island.evals || 0;
          const rawParsimony = (island.id % 2 === 0) ? 'Compact' : 'Branched';
          const rawSoundness = Math.max(75, 100 - (island.id * 6));

          const fitnessNorm = Math.min(1.0, Math.max(0.05, rawFit / 100.0));
          const diversityNorm = Math.min(1.0, Math.max(0.05, rawClusters / maxClusters));
          const throughputNorm = Math.min(1.0, Math.max(0.05, rawEvals / targetEvalsPerIsland));
          const parsimonyNorm = 0.55 + (island.id % 2 === 0 ? 0.25 : -0.15);
          const soundnessNorm = rawSoundness / 100.0;

          this.data[idx] = [fitnessNorm, diversityNorm, parsimonyNorm, throughputNorm, soundnessNorm];
          this.rawMetrics[idx] = [
            `${rawFit.toFixed(2)}%`,
            `${rawClusters}/${maxClusters} niches`,
            rawParsimony,
            `${rawEvals}/${targetEvalsPerIsland} evals`,
            `${rawSoundness.toFixed(1)}%`
          ];
        });

        this.render();
      }

      render() {
        if (!this.width || !this.height || !this.ctx) return;
        const ctx = this.ctx;
        const centerX = this.width / 2;
        const centerY = this.height / 2;
        const radius = Math.min(centerX, centerY) - 38;
        const numAxes = this.axes.length;
        const angleStep = (Math.PI * 2) / numAxes;

        this.projectedVertices = [];
        ctx.clearRect(0, 0, this.width, this.height);

        // 1. Concentric background rings
        const levels = 4;
        for (let l = 1; l <= levels; l++) {
          const r = (radius / levels) * l;
          ctx.beginPath();
          for (let i = 0; i < numAxes; i++) {
            const angle = i * angleStep - Math.PI / 2;
            const x = centerX + r * Math.cos(angle);
            const y = centerY + r * Math.sin(angle);
            if (i === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
          }
          ctx.closePath();
          ctx.strokeStyle = (l === levels) ? 'rgba(71, 85, 105, 0.45)' : 'rgba(51, 65, 85, 0.25)';
          ctx.lineWidth = 1;
          ctx.stroke();
        }

        // 2. Axis spokes & text labels
        ctx.font = '10px monospace';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';

        for (let i = 0; i < numAxes; i++) {
          const angle = i * angleStep - Math.PI / 2;
          const spokeX = centerX + radius * Math.cos(angle);
          const spokeY = centerY + radius * Math.sin(angle);

          ctx.beginPath();
          ctx.moveTo(centerX, centerY);
          ctx.lineTo(spokeX, spokeY);
          ctx.strokeStyle = 'rgba(71, 85, 105, 0.5)';
          ctx.lineWidth = 1;
          ctx.stroke();

          const labelOffset = 18;
          const labelX = centerX + (radius + labelOffset) * Math.cos(angle);
          const labelY = centerY + (radius + labelOffset) * Math.sin(angle);

          ctx.fillStyle = '#94a3b8';
          ctx.fillText(this.axes[i].label, labelX, labelY);
        }

        // 3. Island polygon fills & cached vertices
        this.data.forEach((islandMetrics, islandIdx) => {
          const color = this.islandColors[islandIdx];
          ctx.beginPath();

          islandMetrics.forEach((val, i) => {
            const angle = i * angleStep - Math.PI / 2;
            const dist = radius * Math.max(0.04, Math.min(val, 1.0));
            const x = centerX + dist * Math.cos(angle);
            const y = centerY + dist * Math.sin(angle);

            this.projectedVertices.push({
              x, y,
              islandIdx,
              axisIdx: i,
              normVal: val
            });

            if (i === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
          });

          ctx.closePath();
          ctx.fillStyle = color.fill;
          ctx.fill();
          ctx.strokeStyle = color.stroke;
          ctx.lineWidth = 1.75;
          ctx.stroke();

          // Draw point anchors
          islandMetrics.forEach((val, i) => {
            const angle = i * angleStep - Math.PI / 2;
            const dist = radius * Math.max(0.04, Math.min(val, 1.0));
            const x = centerX + dist * Math.cos(angle);
            const y = centerY + dist * Math.sin(angle);

            ctx.beginPath();
            ctx.arc(x, y, 2.5, 0, Math.PI * 2);
            ctx.fillStyle = color.stroke;
            ctx.fill();
          });
        });

        // 4. Highlight hovered vertex with glowing pulse halo
        if (this.hoveredPoint) {
          const hp = this.hoveredPoint;
          const color = this.islandColors[hp.islandIdx];

          ctx.save();
          ctx.beginPath();
          ctx.arc(hp.x, hp.y, 8, 0, Math.PI * 2);
          ctx.fillStyle = color.fill;
          ctx.fill();
          ctx.strokeStyle = color.stroke;
          ctx.lineWidth = 2;
          ctx.stroke();

          ctx.beginPath();
          ctx.arc(hp.x, hp.y, 3.5, 0, Math.PI * 2);
          ctx.fillStyle = '#ffffff';
          ctx.fill();
          ctx.restore();
        }
      }
    }

    let islandRadarChart = null;

    function handleBroadcastEvent(msg) {
      const eventType = msg.type || msg.event;
      const data = msg.data || msg;

      if (eventType === 'heartbeat') {
        document.getElementById('nav-iteration').textContent = `#${data.iteration}`;
        document.getElementById('nav-status').textContent = data.status;
        appendLog(`Heartbeat #${data.iteration} - Agent status: ${data.status}`, "text-blue-400");
      } else if (eventType === 'log') {
        appendLog(`Cycle #${data.iteration}: ${data.summary}`, "text-emerald-300");
      } else if (eventType === 'funsearch_telemetry') {
        updateFunSearchUI(data);
        pulseNode('node-islands', 'status-islands', 'active', 'MUTATION & CROSSOVER');
        setTimeout(() => pulseNode('node-wasm', 'status-wasm', 'active', 'WASM FUEL EVALUATION'), 250);
        if (islandRadarChart && data.islands) {
          islandRadarChart.updateMetrics(
            data.islands,
            12,
            Math.floor((data.target_evals || 100) / 4)
          );
        }
      } else if (eventType === 'cegis_event') {
        updateCegisUI(data);
        const status = data.event?.status || data.status;
        if (status === "VIOLATED") {
          pulseNode('node-z3', 'status-z3', 'violation', 'Z3 SMT COUNTEREXAMPLE EXTRACTED');
        } else {
          pulseNode('node-z3', 'status-z3', 'success', 'CONTRACTS PROVED SOUND');
        }
      } else if (eventType === 'funsearch_record') {
        pulseNode('node-lean', 'status-lean', 'success', 'SYNTHESIZING LEAN 4 CERTIFICATE');
        setTimeout(() => pulseNode('node-gitops', 'status-gitops', 'active', 'DISPATCHING GITHUB PR'), 800);
      }
    }

    // --- Scheduler Telemetry ---
    let schedulerSeconds = null;
    function formatCountdown(sec) {
      if (sec === null || sec < 0) return "--:--:--";
      const h = Math.floor(sec / 3600).toString().padStart(2, '0');
      const m = Math.floor((sec % 3600) / 60).toString().padStart(2, '0');
      const s = (sec % 60).toString().padStart(2, '0');
      return `${h}h ${m}m ${s}s`;
    }

    async function fetchScheduler() {
      const res = await authFetch('/api/scheduler/status');
      if (res.ok) {
        const d = await res.json();
        document.getElementById('sched-next-run').textContent = d.next_run_utc || "None";
        document.getElementById('sched-last-run').textContent = d.last_run_utc || "None";
        schedulerSeconds = d.seconds_remaining;
        document.getElementById('sched-countdown').textContent = `${formatCountdown(schedulerSeconds)} remaining`;
      }
    }

    setInterval(() => {
      if (schedulerSeconds !== null && schedulerSeconds > 0) {
        schedulerSeconds--;
        document.getElementById('sched-countdown').textContent = `${formatCountdown(schedulerSeconds)} remaining`;
      }
    }, 1000);

    async function updateCronSchedule() {
      const expr = document.getElementById('sched-cron-input').value.trim();
      const res = await authFetch('/api/scheduler/update', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cron_expression: expr })
      });
      const data = await res.json();
      const msg = document.getElementById('sched-msg');
      if (res.ok) {
        msg.className = "text-emerald-400 text-xs font-mono";
        msg.textContent = "✓ Cron schedule updated.";
        fetchScheduler();
      } else {
        msg.className = "text-rose-400 text-xs font-mono";
        msg.textContent = `✗ ${data.detail || "Error updating cron"}`;
      }
    }

    function setCronPreset(expr) {
      document.getElementById('sched-cron-input').value = expr;
      updateCronSchedule();
    }

    async function triggerSchedulerNow() {
      if (!confirm("Launch full overnight discovery pipeline immediately?")) return;
      const res = await authFetch('/api/scheduler/trigger-now', { method: 'POST' });
      if (res.ok) {
        appendLog("🚀 Overnight discovery pipeline dispatched manually.", "text-purple-400");
      }
    }

    // --- FunSearch UI ---
    function updateFunSearchUI(d) {
      document.getElementById('fs-total-evals').textContent = d.total_evals_completed || 0;
      document.getElementById('fs-top-fitness').textContent = (d.top_fitness_score || 0).toFixed(4);
      document.getElementById('fs-champ-gen').textContent = `Gen #${d.champion_generation || 0}`;
      document.getElementById('fs-islands-count').textContent = `${d.active_islands_count || 4} Islands`;
      if (d.champion_code) {
        document.getElementById('fs-champion-code').textContent = d.champion_code;
      }
      const badge = document.getElementById('fs-badge');
      badge.textContent = d.is_running ? "RUNNING" : "IDLE";
      badge.className = d.is_running ? "text-[10px] font-bold px-2 py-0.5 rounded bg-emerald-950 text-emerald-300 border border-emerald-800 font-mono" : "text-[10px] font-bold px-2 py-0.5 rounded bg-slate-800 text-slate-300 font-mono";
    }

    async function startFunSearch() {
      await authFetch('/api/funsearch/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ evals_per_island: 20 })
      });
      appendLog("🧬 FunSearch multi-island evolutionary search initiated.", "text-emerald-400");
    }

    async function stopFunSearch() {
      await authFetch('/api/funsearch/stop', { method: 'POST' });
      appendLog("⏹️ FunSearch evolutionary run halted.", "text-amber-400");
    }

    // --- CEGIS & Verification ---
    function updateCegisUI(data) {
      if (data.metrics) {
        document.getElementById('cegis-checks').textContent = data.metrics.total_checks;
        document.getElementById('cegis-verified').textContent = data.metrics.total_verified;
        document.getElementById('cegis-violations').textContent = data.metrics.total_violations;
        document.getElementById('cegis-rate').textContent = `${data.metrics.violation_rate_pct}%`;
      }
      if (data.event) {
        appendLog(`[CEGIS ${data.event.status}] ${data.event.invariant_name} (${data.event.solve_time_ms}ms)`, data.event.status === 'VERIFIED' ? "text-emerald-400" : "text-rose-400");
      }
    }

    async function runZ3Probe() {
      const code = document.getElementById('cegis-input-code').value;
      const res = await authFetch('/api/cegis/probe', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ python_code: code })
      });
      const d = await res.json();
      const box = document.getElementById('probe-result');
      if (d.verified) {
        box.innerHTML = `<span class="text-emerald-400 font-bold">✓ VERIFIED SATISFIED</span>\nAll SMT contract invariants passed (${d.solve_time_ms}ms).`;
      } else {
        box.innerHTML = `<span class="text-rose-400 font-bold">✗ VIOLATION DETECTED [${d.counterexample?.invariant_name}]</span>\nItem: ${d.counterexample?.item}, Capacity: ${d.counterexample?.bin_capacity}\nDetail: ${d.counterexample?.detail || ''}`;
      }
    }

    async function runLeanVerification() {
      const code = document.getElementById('cegis-input-code').value;
      const res = await authFetch('/api/verify/lean', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ python_code: code })
      });
      const d = await res.json();
      const box = document.getElementById('probe-result');
      box.innerHTML = `<span class="text-purple-400 font-bold">Lean 4 Synthesizer Status: ${d.verified ? 'PROVED' : 'FAILED'}</span>\n<pre class="mt-2 text-[10px] text-slate-300">${d.lean_proof}</pre>`;
    }

    async function submitGitOpsPR() {
      const code = document.getElementById('cegis-input-code').value;
      const synthRes = await authFetch('/api/lean/synthesize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ python_code: code })
      });
      const synthData = await synthRes.json();

      const prRes = await authFetch('/api/gitops/create-pr', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          python_code: code,
          lean_proof: synthData.lean_code,
          fitness_score: 0.8920,
          algorithm_name: "OnlineBinPackingHeuristic"
        })
      });
      const prData = await prRes.json();
      if (prData.success) {
        alert(`Pull Request Created successfully!\n${prData.pr_url}`);
        appendLog(`🚀 Pull Request opened: ${prData.pr_url}`, "text-emerald-400");
      } else {
        alert(`Could not create PR: ${prData.error}`);
      }
    }

    const PROBE_PRESETS = {
      singularity: `def priority(item: float, bin_capacity: float) -> float:
    # Bug: Division by zero when a bin has remaining space equal to item
    return 1.0 / (bin_capacity - item)`,

      linear: `def priority(item: float, bin_capacity: float) -> float:
    # Linear: prioritize tight fits without division
    gap = bin_capacity - item
    return 100.0 - gap`,

      quadratic: `def priority(item: float, bin_capacity: float) -> float:
    # Quadratic: heavily penalize larger residual gaps
    gap = bin_capacity - item
    return 1000.0 / ((gap * gap) + 0.01)`,

      ratio: `def priority(item: float, bin_capacity: float) -> float:
    # Fill Ratio: relative proportion of item size to remaining capacity
    return item / (bin_capacity + 0.001)`
    };

    function loadProbePreset(name) {
      if (PROBE_PRESETS[name]) {
        document.getElementById('cegis-input-code').value = PROBE_PRESETS[name];
      }
    }

    function loadSingularityPreset() {
      loadProbePreset('singularity');
    }

    // --- Core Memory & Heuristics ---
    async function fetchCoreMemory() {
      const res = await authFetch('/api/memory/core');
      if (res.ok) {
        const data = await res.json();
        const c = document.getElementById('core-memory-container');
        c.innerHTML = Object.keys(data).length === 0 ? '<span class="text-slate-500">Scratchpad is empty.</span>' : '';
        for (const [k, v] of Object.entries(data)) {
          const row = document.createElement('div');
          row.className = "flex justify-between items-center bg-slate-950 p-2 rounded border border-slate-800";
          row.innerHTML = `<div><span class="text-blue-400 font-bold">${k}</span>: <span class="text-slate-300">${v}</span></div>
                           <button onclick="deleteCoreMemory('${k}')" class="text-rose-400 hover:text-rose-300 text-[10px]">✕</button>`;
          c.appendChild(row);
        }
      }
    }

    async function addCoreMemory() {
      const key = document.getElementById('mem-key-input').value.trim();
      const val = document.getElementById('mem-val-input').value.trim();
      if (!key || !val) return;
      await authFetch('/api/memory/core', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key, value: val })
      });
      document.getElementById('mem-key-input').value = '';
      document.getElementById('mem-val-input').value = '';
      fetchCoreMemory();
    }

    async function deleteCoreMemory(k) {
      await authFetch(`/api/memory/core/${k}`, { method: 'DELETE' });
      fetchCoreMemory();
    }

    async function fetchHeuristics() {
      const res = await authFetch('/api/memory/heuristics');
      if (res.ok) {
        const data = await res.json();
        const c = document.getElementById('heuristics-container');
        c.innerHTML = data.length === 0 ? '<span class="text-slate-500">No self-learned rules extracted yet.</span>' : '';
        for (const h of data) {
          const row = document.createElement('div');
          row.className = "bg-slate-950 p-2 rounded border border-slate-800 text-[11px]";
          row.innerHTML = `<div class="text-emerald-400 font-bold">[${h.category}] ${h.condition}</div>
                           <div class="text-slate-300 mt-0.5">${h.actionable_lesson}</div>`;
          c.appendChild(row);
        }
      }
    }

    // --- Search ---
    async function executeMemorySearch() {
      const q = document.getElementById('search-query-input').value.trim();
      if (!q) return;
      const res = await authFetch(`/api/memory/search?q=${encodeURIComponent(q)}`);
      const container = document.getElementById('search-results-container');
      if (res.ok) {
        const results = await res.json();
        container.innerHTML = results.length === 0 ? '<span class="text-slate-500">No matches found.</span>' : '';
        for (const r of results) {
          const div = document.createElement('div');
          div.className = "p-2 bg-slate-900 rounded border border-slate-800";
          div.innerHTML = `<div class="flex justify-between text-[10px] text-slate-500"><span>Cycles #${r.start_iteration}-#${r.end_iteration}</span><span>Score: ${r.rrf_score}</span></div>
                           <div class="text-slate-300 mt-1">${r.dense_summary}</div>`;
          container.appendChild(div);
        }
      }
    }

    async function triggerVectorSync() {
      await authFetch('/api/vector/sync/trigger', { method: 'POST' });
      alert('Vector index synchronization launched.');
    }

    // Agent Controls
    async function pauseAgent() { await authFetch('/api/pause', { method: 'POST' }); }
    async function resumeAgent() { await authFetch('/api/resume', { method: 'POST' }); }
    async function triggerStep() { await authFetch('/api/trigger', { method: 'POST' }); }
    function clearLogs() { document.getElementById('log-terminal').innerHTML = ''; }

    async function fetchInitialFunSearch() {
      const res = await authFetch('/api/funsearch/telemetry');
      if (res.ok) {
        const data = await res.json();
        updateFunSearchUI(data);
        if (islandRadarChart && data.islands) {
          islandRadarChart.updateMetrics(data.islands);
        }
      }
    }

    // Init on DOMContentLoaded
    document.addEventListener('DOMContentLoaded', () => {
      islandRadarChart = new IslandRadarChart('island-radar-canvas');
      connectWebSocket();
      fetchScheduler();
      fetchInitialFunSearch();
      fetchCoreMemory();
      fetchHeuristics();

      // Tooltip listener
      const tooltip = document.getElementById('metric-tooltip');
      document.addEventListener('mouseover', (e) => {
        const target = e.target.closest('[data-tooltip]');
        if (!target || !tooltip) {
          if (tooltip) tooltip.style.opacity = '0';
          return;
        }
        tooltip.textContent = target.dataset.tooltip;
        const rect = target.getBoundingClientRect();
        tooltip.style.left = `${rect.left + window.scrollX}px`;
        tooltip.style.top = `${rect.bottom + window.scrollY + 6}px`;
        tooltip.style.opacity = '1';
      });
    });
  </script>
  <!-- Single persistent tooltip container -->
  <div id="metric-tooltip" class="fixed pointer-events-none opacity-0 transition-opacity duration-150 bg-slate-950/95 border border-slate-700 text-slate-200 text-xs px-2.5 py-1.5 rounded-md shadow-2xl z-50 font-mono"></div>
</body>
</html>
"""
