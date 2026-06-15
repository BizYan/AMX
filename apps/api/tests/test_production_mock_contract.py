"""Contracts that keep test-only mock helpers out of production modules."""

from pathlib import Path


def test_production_modules_do_not_import_unittest_mock():
    app_root = Path(__file__).resolve().parents[1] / "app"
    offenders = [
        path.relative_to(app_root).as_posix()
        for path in app_root.rglob("*.py")
        if "unittest.mock" in path.read_text(encoding="utf-8")
    ]

    assert offenders == []
