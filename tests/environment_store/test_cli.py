import json

import pytest

from environment_store.cli import main, parse_dotenv


@pytest.fixture
def store(tmp_path):
    path = str(tmp_path / "store.json")

    def run(*args: str) -> int:
        return main(["--backend", "json", "--json-file", path, *args])

    return run


def test_set_and_get_root(store, capsys):
    assert store("set", "A", "1") == 0
    capsys.readouterr()
    assert store("get", "A") == 0
    assert capsys.readouterr().out == "1\n"


def test_get_missing_exits_nonzero(store, capsys):
    assert store("get", "NOPE") == 1
    assert "not found" in capsys.readouterr().err


def test_set_from_stdin_strips_one_newline(store, capsys, monkeypatch):
    import io

    monkeypatch.setattr("sys.stdin", io.StringIO("secret\n"))
    assert store("set", "S", "--stdin", "-o", "acme") == 0
    capsys.readouterr()
    store("get", "S", "-o", "acme", "--raw")
    assert capsys.readouterr().out == "secret"


def test_set_requires_exactly_one_value_source(store, capsys):
    assert store("set", "A") == 1
    assert "exactly one" in capsys.readouterr().err


def test_hierarchy_validation(store, capsys):
    assert store("set", "A", "1", "-p", "proj") == 2
    assert "requires organisation" in capsys.readouterr().err


def test_list_resolved_overrides_parent(store, capsys):
    store("set", "A", "root")
    store("set", "B", "root")
    store("set", "A", "org", "-o", "acme")
    capsys.readouterr()
    assert store("list", "-o", "acme", "--resolved", "--format", "json") == 0
    assert json.loads(capsys.readouterr().out) == {"A": "org", "B": "root"}
    assert store("list", "-o", "acme", "--format", "json") == 0
    assert json.loads(capsys.readouterr().out) == {"A": "org"}


def test_list_formats_and_mask(store, capsys):
    store("set", "GREETING", "hello world")
    capsys.readouterr()
    store("list")
    assert capsys.readouterr().out == 'GREETING="hello world"\n'
    store("list", "--format", "export")
    assert capsys.readouterr().out == "export GREETING='hello world'\n"
    store("list", "--mask")
    assert capsys.readouterr().out == "GREETING=***\n"
    store("list", "--names-only")
    assert capsys.readouterr().out == "GREETING\n"


def test_delete(store, capsys):
    store("set", "A", "1")
    store("set", "B", "2")
    assert store("delete", "A", "B", "--yes") == 0
    capsys.readouterr()
    store("list")
    assert capsys.readouterr().out == ""


def test_import_dotenv_and_children(store, tmp_path, capsys):
    env_file = tmp_path / ".env"
    env_file.write_text("# c\nexport A=1\nB=\"two words\"\nC='x # y'\nD=val # note\n")
    assert store("import", str(env_file), "-o", "acme", "-p", "web", "-e", "dev") == 0
    capsys.readouterr()
    store("list", "-o", "acme", "-p", "web", "-e", "dev", "--format", "json")
    assert json.loads(capsys.readouterr().out) == {
        "A": "1",
        "B": "two words",
        "C": "x # y",
        "D": "val",
    }
    store("children", "--format", "json")
    assert json.loads(capsys.readouterr().out) == ["acme"]
    store("children", "-o", "acme", "-p", "web")
    assert capsys.readouterr().out == "dev\n"


def test_import_dry_run_writes_nothing(store, tmp_path, capsys):
    f = tmp_path / "v.json"
    f.write_text('{"A": 1, "B": true}')
    assert store("import", str(f), "--dry-run") == 0
    capsys.readouterr()
    store("list")
    assert capsys.readouterr().out == ""


def test_missing_backend(monkeypatch, capsys):
    monkeypatch.delenv("ENVIRONMENT_STORE_BACKEND", raising=False)
    assert main(["list"]) == 1
    assert "No backend" in capsys.readouterr().err


def test_parse_dotenv_rejects_garbage():
    with pytest.raises(Exception, match="Invalid dotenv"):
        parse_dotenv("not a pair")


def test_migrate_requires_postgres_backend(capsys):
    assert main(["--backend", "json", "--json-file", "x.json", "migrate"]) == 1
    assert "only available for the postgres backend" in capsys.readouterr().err


def test_migrate_requires_database_url(monkeypatch, capsys):
    monkeypatch.delenv("ENVIRONMENT_STORE_DATABASE_URL", raising=False)
    assert main(["--backend", "postgres", "migrate"]) == 1
    assert "--database-url" in capsys.readouterr().err


def test_migrate_applies_and_reports(monkeypatch, capsys):
    pytest.importorskip("yoyo")
    calls = []
    monkeypatch.setattr(
        "environment_store.adapters.postgresql.apply_migrations",
        lambda url: calls.append(url) or ["m1", "m2"],
    )
    monkeypatch.setattr(
        "environment_store.adapters.postgresql.pending_migrations", lambda url: ["m3"]
    )
    base = ["--backend", "postgres", "--database-url", "postgresql+psycopg://u@h/db"]
    assert main([*base, "migrate"]) == 0
    captured = capsys.readouterr()
    assert captured.out == "m1\nm2\n"
    assert calls == ["postgresql+psycopg://u@h/db"]
    assert main([*base, "migrate", "--status"]) == 0
    assert capsys.readouterr().out == "m3\n"
    assert len(calls) == 1
