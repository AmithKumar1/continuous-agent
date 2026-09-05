# Contributing to Continuous Agent

Thank you for your interest in contributing to **Continuous Agent**! We welcome contributions ranging from algorithm heuristics and formal proof tactics to sandboxing improvements and documentation.

---

## 🛠️ Development Setup

1. **Clone the repository**:
   ```bash
   git clone https://github.com/AmithKumar1/continuous-agent.git
   cd continuous-agent
   ```

2. **Run the automated bootstrapper**:
   - **Linux / macOS**:
     ```bash
     chmod +x setup.sh
     ./setup.sh
     ```
   - **Windows (PowerShell)**:
     ```powershell
     .\setup.ps1
     ```

3. **Verify your local toolchain**:
   ```bash
   python preflight.py
   python test_wasm_sandbox.py
   python -m pytest
   ```

---

## 🔬 Neuro-Symbolic & Formal Prover Contributions

- **Python Heuristics**: Added to `heuristics/` under their respective problem domain.
- **Lean 4 Proofs**: Stored in `theorems/` and managed via Lake dependencies declared in `lakefile.lean`.
- **Z3 Invariants**: Defined in `agent/cegis_verifier.py`.

---

## 📋 Pull Request Process

1. Create a feature branch (`git checkout -b feature/your-feature-name`).
2. Implement your changes and add test coverage under `tests/`.
3. Ensure all tests pass: `python -m pytest`.
4. Submit a Pull Request following the PR template.
