import io

import pytest

from environment_store.picker import LevelTree, PickerCancelled, pick_level

LEVELS = {
    (): ["acme", "globex"],
    ("acme",): ["webapp"],
    ("acme", "webapp"): ["dev"],
    ("acme", "webapp", "dev"): ["api"],
}


def load(path):
    return LEVELS.get(path, [])


def names(tree):
    return [node.path[-1] if node.path else "root" for node in tree.visible()]


def test_tree_starts_with_root_and_organisations():
    tree = LevelTree(load)
    assert names(tree) == ["root", "acme", "globex"]
    assert tree.press("enter") == ()


def test_expand_descend_collapse_and_parent():
    tree = LevelTree(load)
    for key in ("down", "right", "right", "right", "right", "right"):
        assert tree.press(key) is None
    assert names(tree) == ["root", "acme", "webapp", "dev", "api", "globex"]
    assert tree.visible()[tree.cursor].path == ("acme", "webapp", "dev")
    tree.press("right")  # descend into api, a service: a leaf
    tree.press("right")
    assert tree.press("enter") == ("acme", "webapp", "dev", "api")
    tree.press("left")  # to parent dev
    tree.press("left")  # collapse dev
    assert names(tree) == ["root", "acme", "webapp", "dev", "globex"]
    tree.press("h")  # to parent webapp
    assert tree.press("enter") == ("acme", "webapp")


def test_levels_without_children_become_leaves():
    tree = LevelTree(load)
    tree.press("end")
    tree.press("right")
    assert names(tree) == ["root", "acme", "globex"]
    assert tree.visible()[tree.cursor].is_leaf


def test_without_root():
    tree = LevelTree(load, allow_root=False)
    assert names(tree) == ["acme", "globex"]
    tree.press("left")  # nothing above an organisation
    tree.press("up")
    assert tree.press("enter") == ("acme",)


def test_cancel_keys():
    for key in ("q", "esc", "ctrl-c"):
        with pytest.raises(PickerCancelled):
            LevelTree(load).press(key)


def test_render_scrolls_to_cursor_and_truncates():
    tree = LevelTree(load)
    tree.press("down")
    tree.press("down")
    lines = tree.render(height=2, width=14)
    assert len(lines) == 2
    assert "globex" in lines[1] and "acme" in lines[0]


def test_pick_level_draws_on_out_and_clears_it():
    out = io.StringIO()
    assert pick_level(load, "Pick:", keys=iter(["down", " ", " ", "enter"]), out=out) == (
        "acme",
    )
    text = out.getvalue()
    assert "Pick:" in text and "globex" in text and text.endswith("\x1b[?25h")


def test_pick_level_cancelled_when_keys_run_out_or_store_empty():
    with pytest.raises(PickerCancelled):
        pick_level(load, "Pick:", keys=iter(["down"]), out=io.StringIO())
    with pytest.raises(PickerCancelled, match="no levels"):
        pick_level(lambda path: [], "Pick:", allow_root=False, keys=iter([]), out=io.StringIO())
