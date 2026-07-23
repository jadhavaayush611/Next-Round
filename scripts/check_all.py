import os
import subprocess
import sys
from pathlib import Path

# Color helpers
GREEN = "\033[92m"
RED = "\033[91m"
BLUE = "\033[94m"
RESET = "\033[0m"

ROOT_DIR = Path(__file__).resolve().parent.parent


if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def run_step(name: str, cmd: list[str], cwd: Path) -> bool:
    """Execute a shell command, print progress, and return success state."""
    print(f"{BLUE}:: Running {name}...{RESET}")
    print(f"   Command: {' '.join(cmd)}")
    try:
        # Use shell=True on Windows to support executables in virtualenv or PATH
        res = subprocess.run(cmd, cwd=cwd, shell=sys.platform == "win32")
        if res.returncode == 0:
            print(f"{GREEN}[OK] {name} passed.{RESET}\n")
            return True
        else:
            print(f"{RED}[FAIL] {name} failed with exit code {res.returncode}.{RESET}\n")
            return False
    except Exception as exc:
        print(f"{RED}[FAIL] {name} execution failed: {str(exc)}{RESET}\n")
        return False


def main() -> None:
    success = True

    # --- Backend Checks ---
    backend_dir = ROOT_DIR / "backend"
    py_exec = sys.executable
    print(f"{BLUE}======================================={RESET}")
    print(f"{BLUE}   Running Backend Formatting & Lints  {RESET}")
    print(f"{BLUE}======================================={RESET}\n")

    # 1. Black formatter check
    if not run_step(
        "Backend Formatter (Black)", [py_exec, "-m", "black", "--check", "app", "tests"], backend_dir
    ):
        success = False

    # 2. Ruff linter check
    if not run_step(
        "Backend Linter (Ruff)", [py_exec, "-m", "ruff", "check", "app", "tests"], backend_dir
    ):
        success = False

    # 3. Mypy type validation check
    if not run_step("Backend Type Checker (Mypy)", [py_exec, "-m", "mypy", "app"], backend_dir):
        success = False

    # 4. Pytest unit tests execution
    if not run_step("Backend Unit Tests (Pytest)", [py_exec, "-m", "pytest", "tests"], backend_dir):
        success = False

    # --- Frontend Checks ---
    frontend_dir = ROOT_DIR / "frontend"
    print(f"{BLUE}======================================={RESET}")
    print(f"{BLUE}   Running Frontend Formatting & Lints {RESET}")
    print(f"{BLUE}======================================={RESET}\n")

    # 1. Prettier formatter check
    if not run_step(
        "Frontend Formatter (Prettier)", ["npm", "run", "format:check"], frontend_dir
    ):
        success = False

    # 2. ESLint checks
    if not run_step("Frontend Linter (ESLint)", ["npm", "run", "lint"], frontend_dir):
        success = False

    # 3. TypeScript typecheck
    if not run_step(
        "Frontend Type Checker (TypeScript)", ["npm", "run", "typecheck"], frontend_dir
    ):
        success = False

    # --- Summary ---
    print(f"{BLUE}======================================={RESET}")
    if success:
        print(f"{GREEN}[OK] ALL MONOREPO CHECKS PASSED SUCCESSFULLY.{RESET}")
        sys.exit(0)
    else:
        print(f"{RED}[FAIL] SOME MONOREPO CHECKS FAILED. SEE DETAILS ABOVE.{RESET}")
        sys.exit(1)


if __name__ == "__main__":
    main()
