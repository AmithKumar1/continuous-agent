#!/usr/bin/env bash
# ==============================================================================
# Continuous Agent Automated Setup Script
# Supported: Ubuntu/Debian, Fedora, Arch, macOS
# ==============================================================================

set -eo pipefail

BOLD='\033[1m'
GREEN='\033[0;32m'
SKY='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()    { echo -e "${SKY}${BOLD}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}${BOLD}[SUCCESS]${NC} $1"; }
warn()    { echo -e "${YELLOW}${BOLD}[WARN]${NC} $1"; }
error()   { echo -e "${RED}${BOLD}[ERROR]${NC} $1"; exit 1; }

echo -e "${BOLD}"
echo "=========================================================="
echo "    Continuous Agent Environment Bootstrap & Toolchain   "
echo "=========================================================="
echo -e "${NC}"

# 1. System Architecture & Python Version Check
OS_TYPE="$(uname -s)"
info "Detected Operating System: ${OS_TYPE} ($(uname -m))"

if ! command -v python3 &>/dev/null; then
  error "Python 3 is not installed. Please install Python 3.10+ before running."
fi

PY_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$(echo "${PY_VERSION}" | cut -d'.' -f1)
PY_MINOR=$(echo "${PY_VERSION}" | cut -d'.' -f2)

if [ "${PY_MAJOR}" -ne 3 ] || [ "${PY_MINOR}" -lt 10 ]; then
  error "Python 3.10+ required. Found Python ${PY_VERSION}"
fi
success "Python version compatible: ${PY_VERSION}"

# 2. Package Manager & System Dependencies
info "Checking foundational build utilities (curl, git)..."
for cmd in curl git; do
  if ! command -v "$cmd" &>/dev/null; then
    error "Missing core tool: $cmd. Install it using your OS package manager."
  fi
done

# 3. Lean 4 & Lake Toolchain (via elan)
info "Checking Lean 4 theorem proving environment..."
if ! command -v elan &>/dev/null && [ ! -f "$HOME/.elan/bin/lean" ]; then
  warn "Lean 4 version manager (elan) not detected. Commencing installation..."
  curl -sSf https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh | sh -s -- -y --default-toolchain leanprover/lean4:stable
  # Export for current shell
  export PATH="$HOME/.elan/bin:$PATH"
fi

if [ -f "$HOME/.elan/bin/lean" ]; then
  export PATH="$HOME/.elan/bin:$PATH"
fi

if command -v lean &>/dev/null; then
  LEAN_VER=$(lean --version)
  success "Lean 4 verified: ${LEAN_VER}"
else
  warn "Lean 4 binary not resolved on PATH. Ensure '$HOME/.elan/bin' is added to your shell profile."
fi

# 4. Virtual Environment & Python Dependencies
if [ ! -d ".venv" ]; then
  info "Creating Python virtual environment in .venv/..."
  python3 -m venv .venv
fi

info "Activating virtual environment..."
source .venv/bin/activate

info "Upgrading pip and wheel..."
pip install --upgrade pip wheel setuptools --quiet

if [ -f "requirements.txt" ]; then
  info "Installing Python dependencies (Wasmtime, Z3, FastAPI, Croniter)..."
  pip install -r requirements.txt --quiet
  success "Python packages installed."
else
  error "requirements.txt not found in project root."
fi

# 5. Environment Template Initialization
if [ ! -f ".env" ]; then
  if [ -f ".env.example" ]; then
    info "No .env found. Copying from .env.example..."
    cp .env.example .env
    warn "Generated new .env file. Update it with your OPENAI_API_KEY and tokens."
  else
    touch .env
    warn "Created empty .env file. Please populate required variables."
  fi
else
  success "Existing .env file detected."
fi

# 6. Docker Sandbox Image Check (Optional Fallback Layer)
info "Validating container sandbox subsystem..."
if command -v docker &>/dev/null && docker info &>/dev/null; then
  if [ -f "Dockerfile.evaluator" ]; then
    info "Docker daemon reachable. Building 'algo-sandbox:latest' for gVisor fallback..."
    docker build -t algo-sandbox:latest -f Dockerfile.evaluator . --quiet || warn "Docker sandbox build skipped. In-process WASM will remain primary."
    success "Container sandbox image built."
  fi
else
  warn "Docker is offline or not installed. Fallback container isolation disabled (In-process WASM will handle all evaluations)."
fi

# 7. Execute Pre-Flight Health Checks
echo ""
info "Executing pre-flight diagnostic suite..."
if [ -f "preflight.py" ]; then
  python preflight.py || warn "Some preflight checks did not pass. Check diagnostics above."
else
  warn "preflight.py not found. Skipping automated sanity verification."
fi

# 8. Finished
echo ""
echo -e "${GREEN}${BOLD}==========================================================${NC}"
echo -e "${GREEN}${BOLD}             SETUP COMPLETED SUCCESSFULLY!                ${NC}"
echo -e "${GREEN}${BOLD}==========================================================${NC}"
echo ""
echo "To activate your environment and launch the agent:"
echo -e "  ${SKY}source .venv/bin/activate${NC}"
echo -e "  ${SKY}python main.py${NC}"
echo ""
echo "To run with Docker Compose instead:"
echo -e "  ${SKY}docker compose up --build -d${NC}"
echo ""
