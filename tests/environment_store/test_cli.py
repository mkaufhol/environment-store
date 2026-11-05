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


def _seed(store):
    store("set", "ROOT", "r")
    store("set", "A", "1", "-o", "acme")
    store("set", "B", "2", "-o", "acme", "-p", "web")
    store("set", "C", "3", "-o", "acme", "-p", "web", "-e", "dev")


def test_delete_level_requires_confirm_when_not_interactive(store, capsys, monkeypatch):
    import io

    _seed(store)
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    assert store("delete-level", "-o", "acme") == 1
    assert "--confirm acme" in capsys.readouterr().err
    assert store("delete-level", "-o", "acme", "--confirm", "nope") == 1
    assert "exact name" in capsys.readouterr().err
    store("children", "--format", "json")
    assert json.loads(capsys.readouterr().out) == ["acme"]


def test_delete_level_dry_run_and_delete(store, capsys):
    _seed(store)
    capsys.readouterr()
    assert store("delete-level", "-o", "acme", "-p", "web", "--dry-run") == 0
    assert "1 level(s) below it, 2 variable(s)" in capsys.readouterr().err
    store("children", "-o", "acme")
    assert capsys.readouterr().out == "web\n"
    assert store("delete-level", "-o", "acme", "-p", "web", "--confirm", "web") == 0
    assert "2 variable(s)" in capsys.readouterr().err
    store("children", "-o", "acme")
    assert capsys.readouterr().out == ""
    store("get", "A", "-o", "acme")
    assert capsys.readouterr().out == "1\n"


def test_delete_level_refuses_root_and_skipped_levels(store, capsys):
    assert store("delete-level", "--confirm", "x") == 1
    assert "root level" in capsys.readouterr().err
    assert store("delete-level", "-p", "web", "--confirm", "web") == 2
    assert "requires organisation" in capsys.readouterr().err


@pytest.fixture
def two_stores(tmp_path):
    source, dest = str(tmp_path / "source.json"), str(tmp_path / "dest.json")

    def run(*args: str, source_args=("--backend", "json", "--json-file")) -> int:
        return main([*source_args, source, *args])

    def dest_run(*args: str) -> int:
        return main(["--backend", "json", "--json-file", dest, *args])

    return run, dest_run, source, dest


def _transfer(run, dest, *args):
    return run("transfer", "--dest-backend", "json", "--dest-json-file", dest, *args)


def test_transfer_copies_store(two_stores, capsys):
    run, dest_run, _, dest = two_stores
    _seed(run)
    capsys.readouterr()
    assert _transfer(run, dest) == 0
    assert "4 created" in capsys.readouterr().err
    dest_run("list", "-o", "acme", "-p", "web", "-e", "dev", "--resolved", "--format", "json")
    assert json.loads(capsys.readouterr().out) == {"ROOT": "r", "A": "1", "B": "2", "C": "3"}
    run("children")  # source unchanged
    assert capsys.readouterr().out == "acme\n"


def test_transfer_dry_run_subtree_and_json(two_stores, capsys):
    run, dest_run, _, dest = two_stores
    _seed(run)
    capsys.readouterr()
    assert _transfer(run, dest, "-o", "acme", "-p", "web", "--dry-run", "--format", "json") == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["created"] == 2
    assert "Would transfer" in captured.err
    dest_run("children")
    assert capsys.readouterr().out == ""


def test_transfer_conflicts_exit_3_until_overwrite(two_stores, capsys):
    run, dest_run, _, dest = two_stores
    _seed(run)
    dest_run("set", "A", "different", "-o", "acme")
    capsys.readouterr()
    assert _transfer(run, dest) == 3
    err = capsys.readouterr().err
    assert "conflict: A at acme" in err and "--overwrite" in err
    dest_run("get", "A", "-o", "acme")
    assert capsys.readouterr().out == "different\n"
    assert _transfer(run, dest, "--overwrite") == 0
    dest_run("get", "A", "-o", "acme")
    assert capsys.readouterr().out == "1\n"


def test_transfer_rejects_same_store_and_missing_destination(two_stores, capsys, monkeypatch):
    run, _, source, _ = two_stores
    monkeypatch.delenv("ENVIRONMENT_STORE_DEST_BACKEND", raising=False)
    assert run("transfer", "--dest-backend", "json", "--dest-json-file", source) == 1
    assert "same store" in capsys.readouterr().err
    assert run("transfer") == 1
    assert "--dest-backend" in capsys.readouterr().err


def test_transfer_to_aws_parameter_store(two_stores, capsys):
    boto3 = pytest.importorskip("boto3")
    moto = pytest.importorskip("moto")
    run, _, _, _ = two_stores
    _seed(run)
    capsys.readouterr()
    with moto.mock_aws():
        code = run(
            "transfer",
            "--dest-backend",
            "ssm",
            "--dest-region",
            "eu-central-1",
            "--dest-prefix",
            "app",
        )
        assert code == 0
        ssm = boto3.client("ssm", region_name="eu-central-1")
        names = sorted(
            p["Name"]
            for p in ssm.get_parameters_by_path(Path="/", Recursive=True)["Parameters"]
        )
        assert "/app/acme/web/dev/C" in names
        assert len(names) == 4


def test_export_prints_resolved_shell_code(store, capsys):
    store("set", "A", "root")
    store("set", "B", "it's here", "-o", "acme")
    store("set", "A", "child", "-o", "acme", "-p", "web")
    capsys.readouterr()
    assert store("export", "-o", "acme", "-p", "web") == 0
    assert capsys.readouterr().out == "export A=child\nexport B='it'\"'\"'s here'\n"


def test_export_unset(store, capsys):
    store("set", "A", "1")
    store("set", "B", "2", "-o", "acme")
    capsys.readouterr()
    assert store("export", "-o", "acme", "--unset") == 0
    assert capsys.readouterr().out == "unset A\nunset B\n"


def test_export_rejects_invalid_shell_names(store, capsys):
    store("set", "BAD-NAME", "1")
    capsys.readouterr()
    assert store("export") == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "BAD-NAME" in captured.err


def test_export_dotenv_writes_resolved_file_in_cwd(store, tmp_path, monkeypatch):
    import os
    import stat

    monkeypatch.chdir(tmp_path)
    store("set", "A", "root")
    store("set", "B", "two words", "-o", "acme")
    store("set", "A", "child", "-o", "acme", "-p", "web")
    assert store("export-dotenv", "-o", "acme", "-p", "web") == 0
    env_file = tmp_path / ".env"
    assert env_file.read_text() == 'A=child\nB="two words"\n'
    assert parse_dotenv(env_file.read_text()) == {"A": "child", "B": "two words"}
    if os.name == "posix":
        assert stat.S_IMODE(env_file.stat().st_mode) == 0o600


def test_export_dotenv_custom_file_and_directory(store, tmp_path):
    store("set", "A", "1")
    target = tmp_path / "prod.env"
    assert store("export-dotenv", "--file", str(target)) == 0
    assert target.read_text() == "A=1\n"
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    assert store("export-dotenv", "-f", str(out_dir)) == 0
    assert (out_dir / ".env").read_text() == "A=1\n"


def test_export_dotenv_refuses_overwrite_without_force(store, tmp_path, capsys):
    store("set", "A", "new")
    target = tmp_path / "x.env"
    target.write_text("A=old\n")
    capsys.readouterr()
    assert store("export-dotenv", "-f", str(target)) == 1
    assert "--force" in capsys.readouterr().err
    assert target.read_text() == "A=old\n"
    assert store("export-dotenv", "-f", str(target), "--force") == 0
    assert target.read_text() == "A=new\n"


def test_export_dotenv_rejects_invalid_names(store, tmp_path, capsys):
    store("set", "BAD-NAME", "1")
    target = tmp_path / "x.env"
    capsys.readouterr()
    assert store("export-dotenv", "-f", str(target)) == 1
    assert "BAD-NAME" in capsys.readouterr().err
    assert not target.exists()


@pytest.fixture
def tree_store(store, capsys):
    store("set", "R", "root")
    store("set", "A", "1", "-o", "acme", "-p", "webapp", "-e", "dev", "-s", "api")
    store("set", "B", "2", "-o", "acme", "-p", "webapp", "-e", "prod")
    store("set", "C", "3", "-o", "globex")
    capsys.readouterr()
    return store


def test_levels_tree(tree_store, capsys):
    assert tree_store("levels") == 0
    assert capsys.readouterr().out == (
        "root\n"
        "├── acme (organisation)\n"
        "│   └── webapp (project)\n"
        "│       ├── dev (environment)\n"
        "│       │   └── api (service)\n"
        "│       └── prod (environment)\n"
        "└── globex (organisation)\n"
    )


def test_levels_subtree_depth_and_formats(tree_store, capsys):
    assert tree_store("tree", "-o", "acme", "--depth", "2") == 0
    assert capsys.readouterr().out == (
        "acme (organisation)\n"
        "└── webapp (project)\n"
        "    ├── dev (environment)\n"
        "    └── prod (environment)\n"
    )
    tree_store("levels", "-o", "acme", "-p", "webapp", "--format", "paths")
    assert (
        capsys.readouterr().out
        == "acme / webapp / dev\nacme / webapp / dev / api\nacme / webapp / prod\n"
    )
    tree_store("levels", "--format", "json")
    assert json.loads(capsys.readouterr().out) == {
        "acme": {"webapp": {"dev": {"api": {}}, "prod": {}}},
        "globex": {},
    }


def test_no_level_options_open_the_picker_on_a_terminal(
    tree_store, capsys, monkeypatch, tmp_path
):
    calls = []

    def fake_pick(load, title, allow_root=True):
        calls.append((title, allow_root, load(()), load(("acme",))))
        return ("acme", "webapp", "dev", "api")

    monkeypatch.setattr("environment_store.cli._interactive", lambda: True)
    monkeypatch.setattr("environment_store.cli.pick_level", fake_pick)
    target = tmp_path / "out.env"
    assert tree_store("export-dotenv", "-f", str(target)) == 0
    assert calls == [
        ("Choose the level for export-dotenv:", True, ["acme", "globex"], ["webapp"])
    ]
    assert "Level: acme / webapp / dev / api (service)" in capsys.readouterr().err
    assert target.read_text() == "A=1\nR=root\n"


def test_picker_is_skipped_with_options_root_flag_or_without_terminal(
    tree_store, capsys, monkeypatch
):
    def fail(*args, **kwargs):
        raise AssertionError("picker opened")

    monkeypatch.setattr("environment_store.cli.pick_level", fail)
    assert tree_store("get", "R") == 0  # no terminal under pytest
    monkeypatch.setattr("environment_store.cli._interactive", lambda: True)
    assert tree_store("get", "R", "--root") == 0
    assert tree_store("get", "C", "-o", "globex") == 0
    assert tree_store("children") == 0
    assert capsys.readouterr().out == "root\nroot\n3\nacme\nglobex\n"


def test_root_flag_conflicts_with_level_options(tree_store, capsys):
    assert tree_store("get", "C", "-o", "globex", "--root") == 1
    assert "--root cannot be combined" in capsys.readouterr().err


def test_picker_cancel_and_delete_level_hides_root(tree_store, capsys, monkeypatch):
    from environment_store.picker import PickerCancelled

    seen = []

    def cancel(load, title, allow_root=True):
        seen.append(allow_root)
        raise PickerCancelled

    monkeypatch.setattr("environment_store.cli._interactive", lambda: True)
    monkeypatch.setattr("environment_store.cli.pick_level", cancel)
    assert tree_store("delete-level") == 1
    assert seen == [False]
    assert "Aborted." in capsys.readouterr().err


def test_picker_skipped_when_only_root_exists(store, capsys, monkeypatch):
    monkeypatch.setattr("environment_store.cli._interactive", lambda: True)
    monkeypatch.setattr("environment_store.cli.pick_level", None)
    assert store("list") == 0


@pytest.mark.parametrize(
    "argv",
    [
        ("--no-interaction", "get", "R"),
        ("get", "R", "--no-interaction"),
    ],
)
def test_no_interaction_skips_the_picker(tree_store, capsys, monkeypatch, tmp_path, argv):
    def fail(*args, **kwargs):
        raise AssertionError("picker opened")

    monkeypatch.setattr("environment_store.cli._interactive", lambda: True)
    monkeypatch.setattr("environment_store.cli.pick_level", fail)
    path = str(tmp_path / "store.json")
    assert main(["--backend", "json", "--json-file", path, "set", "R", "root", "--root"]) == 0
    assert main(["--backend", "json", "--json-file", path, *argv]) == 0
    assert capsys.readouterr().out == "root\n"


def test_no_interaction_from_environment(capsys, monkeypatch, tmp_path):
    monkeypatch.setenv("ENVIRONMENT_STORE_NO_INTERACTION", "1")
    monkeypatch.setattr("environment_store.cli._interactive", lambda: True)
    monkeypatch.setattr("environment_store.cli.pick_level", None)
    path = str(tmp_path / "store.json")
    main(["--backend", "json", "--json-file", path, "set", "A", "1", "-o", "acme"])
    assert main(["--backend", "json", "--json-file", path, "list"]) == 0


def test_no_interaction_never_prompts_for_delete_level(store, capsys, monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True, raising=False)
    monkeypatch.setattr("builtins.input", None)
    store("set", "A", "1", "-o", "acme")
    capsys.readouterr()
    assert store("--no-interaction", "delete-level", "-o", "acme") == 1
    assert "--confirm acme" in capsys.readouterr().err
