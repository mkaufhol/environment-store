import re
from collections.abc import Mapping

from hypothesis import given
from hypothesis import strategies as st

from environment_store.core.merge import MergeOrder, merge, merge_with_sources, nested_flat_key
from environment_store.core.validation import STORE_NAME_PATTERN
from tests.support.strategies import store_names, variable_maps, variable_names

type Stores = list[tuple[str, Mapping[str, str]]]

_STORES: st.SearchStrategy[Stores] = st.lists(st.tuples(store_names(), variable_maps()), max_size=5)
_DISTINCT_STORES: st.SearchStrategy[Stores] = st.lists(
    st.tuples(store_names(), variable_maps()), max_size=5, unique_by=lambda entry: entry[0]
)


@given(_STORES)
def test_last_wins_equals_applying_the_stores_in_load_order(stores: Stores) -> None:
    expected: dict[str, str] = {}
    for _, variables in stores:
        expected.update(variables)

    assert merge(stores, order=MergeOrder.LAST_WINS) == expected


@given(_STORES)
def test_first_wins_equals_last_wins_over_the_reversed_load_order(stores: Stores) -> None:
    assert merge(stores, order=MergeOrder.FIRST_WINS) == merge(
        stores[::-1], order=MergeOrder.LAST_WINS
    )


@given(_DISTINCT_STORES, st.sampled_from(list(MergeOrder)))
def test_the_winning_store_contains_the_winning_value(stores: Stores, order: MergeOrder) -> None:
    variables_of = dict(stores[::-1]) if order is MergeOrder.FIRST_WINS else dict(stores)

    for name, (value, store) in merge_with_sources(stores, order=order).items():
        assert variables_of[store][name] == value


def _first_appearance_order(stores: Stores) -> list[str]:
    # D52: each store's names in code point order, a repeated name keeps its first position.
    return list(dict.fromkeys(name for _, variables in stores for name in sorted(variables)))


@given(_STORES, st.sampled_from(list(MergeOrder)))
def test_merge_keys_follow_the_load_order_of_the_stores_each_sorted(
    stores: Stores, order: MergeOrder
) -> None:
    assert list(merge(stores, order=order)) == _first_appearance_order(stores)


@given(_STORES, st.sampled_from(list(MergeOrder)))
def test_merge_with_sources_keys_follow_the_same_order_as_merge(
    stores: Stores, order: MergeOrder
) -> None:
    assert list(merge_with_sources(stores, order=order)) == _first_appearance_order(stores)


@given(_STORES)
def test_merge_values_follow_the_merge_order_whatever_the_output_order(stores: Stores) -> None:
    last: dict[str, str] = {}
    first: dict[str, str] = {}
    for _, variables in stores:
        last.update(variables)
        first.update({name: value for name, value in variables.items() if name not in first})

    assert dict(merge(stores, order=MergeOrder.LAST_WINS)) == last
    assert dict(merge(stores, order=MergeOrder.FIRST_WINS)) == first


# POSIX shell variable name, written out independently of the library's own patterns (D40).
_POSIX_SHELL_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@given(st.from_regex(STORE_NAME_PATTERN, fullmatch=True), variable_names())
def test_every_valid_store_name_yields_a_shell_compatible_nested_key(
    store: str, variable: str
) -> None:
    assert _POSIX_SHELL_NAME.fullmatch(nested_flat_key(store, variable))
