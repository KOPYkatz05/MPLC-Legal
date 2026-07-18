import ast
import sys
from pathlib import Path
from types import SimpleNamespace

from client_bootstrap import run_client_bootstrap


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_main_runs_client_bootstrap_before_normal_startup_imports():
    tree = ast.parse((PROJECT_ROOT / "main.py").read_text(encoding="utf-8"))

    assert isinstance(tree.body[0], ast.ImportFrom)
    assert tree.body[0].module == "client_bootstrap"
    assert [alias.name for alias in tree.body[0].names] == [
        "run_client_bootstrap"
    ]

    bootstrap_call = tree.body[1]
    assert isinstance(bootstrap_call, ast.Expr)
    assert isinstance(bootstrap_call.value, ast.Call)
    assert isinstance(bootstrap_call.value.func, ast.Name)
    assert bootstrap_call.value.func.id == "run_client_bootstrap"

    later_imports = set()
    for node in tree.body[2:]:
        if isinstance(node, ast.ImportFrom):
            later_imports.add(node.module)
        elif isinstance(node, ast.Import):
            later_imports.update(alias.name for alias in node.names)
    assert "utils.pycache_cleanup" in later_imports
    assert "utils.runtime_paths" in later_imports


def test_frozen_client_bootstrap_runs_velopack_once_before_returning(monkeypatch):
    events = []

    class FakeVelopackApp:
        def set_auto_apply_on_startup(self, enabled):
            events.append(("auto-apply", enabled))
            return self

        def run(self):
            events.append(("run", None))

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delenv("MISSION_LEGAL_SKIP_VELOPACK_BOOTSTRAP", raising=False)
    monkeypatch.setitem(
        sys.modules,
        "velopack",
        SimpleNamespace(App=FakeVelopackApp),
    )

    assert run_client_bootstrap() is True
    assert events == [("auto-apply", False), ("run", None)]


def test_source_client_bootstrap_does_not_import_velopack(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.delenv("MISSION_LEGAL_SKIP_VELOPACK_BOOTSTRAP", raising=False)
    monkeypatch.delitem(sys.modules, "velopack", raising=False)

    assert run_client_bootstrap() is False
    assert "velopack" not in sys.modules
