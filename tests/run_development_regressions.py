"""Run the existing non-signing selftest groups without changing trust policy.

Publisher integrity and signed update acceptance remain mandatory separate gates.
This runner never patches verification functions, keys, manifests or assertions.
"""
import ast
import multiprocessing
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import selftest


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    tree = ast.parse((ROOT / "selftest.py").read_text(encoding="utf-8"))
    block = next(node for node in tree.body if isinstance(node, ast.If) and "__name__" in ast.unparse(node.test))
    names = [node.value.func.id for node in block.body
             if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
             and isinstance(node.value.func, ast.Name) and node.value.func.id != "print"]
    gated = {"purple_dragon_security_tests", "purple_dragon_foundation_branding_tests", "update_release_center_tests"}
    passed = 0
    for name in names:
        if name in gated:
            print(f"[SIGNATURE GATE PENDING] {name}", flush=True)
            continue
        print(f"\n== {name} ==", flush=True)
        getattr(selftest, name)()
        passed += 1
    print(f"\n{passed} development regression groups passed; {len(gated)} signed-release groups remain required.")


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
