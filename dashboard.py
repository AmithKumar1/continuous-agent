import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional
import aiosqlite
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Security, WebSocket, WebSocketDisconnect, status
from fastapi.responses import HTMLResponse, JSONResponse
from config import config
from agent.auth import verify_api_key, verify_websocket_auth
from agent.events import broker
from agent.scheduler import task_scheduler
from agent.funsearch_service import funsearch_service
from agent.cegis_tracker import cegis_tracker
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
@api_router.get("/status")
async def get_status():
    async with aiosqlite.connect(config.DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT iteration, status, last_heartbeat FROM agent_state WHERE id = 1") as c:
            row = await c.fetchone()
            return dict(row) if row else {"iteration": 0, "status": "UNKNOWN"}

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

@api_router.post("/cegis/probe")
async def run_cegis_probe(payload: VerificationRequest):
    verifier = SymbolicContractVerifier(timeout_ms=payload.timeout_ms or 1500)
    loop = asyncio.get_running_loop()
    start_time = time.time()
    is_verified, counterexample = await loop.run_in_executor(None, verifier.verify, payload.python_code)
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

app = FastAPI(title="Autonomous Continuous Discovery Agent")
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
  <title>Autonomous Discovery Agent — Neuro-Symbolic Control Deck</title>
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
      <div class="w-3 h-3 rounded-full bg-emerald-500 animate-pulse"></div>
      <h1 class="text-lg font-bold tracking-tight text-white flex items-center gap-2">
        <span>CONTINUOUS DISCOVERY AGENT</span>
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
              <button onclick="loadSingularityPreset()" class="text-[10px] text-blue-400 hover:underline">Load Presets</button>
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

    function handleBroadcastEvent(msg) {
      if (msg.type === 'heartbeat') {
        document.getElementById('nav-iteration').textContent = `#${msg.data.iteration}`;
        document.getElementById('nav-status').textContent = msg.data.status;
        appendLog(`Heartbeat #${msg.data.iteration} - Agent status: ${msg.data.status}`, "text-blue-400");
      } else if (msg.type === 'log') {
        appendLog(`Cycle #${msg.data.iteration}: ${msg.data.summary}`, "text-emerald-300");
      } else if (msg.type === 'funsearch_telemetry') {
        updateFunSearchUI(msg.data);
      } else if (msg.type === 'cegis_event') {
        updateCegisUI(msg.data);
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

    function loadSingularityPreset() {
      document.getElementById('cegis-input-code').value = "def priority(item: float, bin_capacity: float) -> float:\n    # First-Fit descending ratio\n    return item / bin_capacity";
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

    // Init
    connectWebSocket();
    fetchScheduler();
    fetchCoreMemory();
    fetchHeuristics();
  </script>
</body>
</html>
"""
