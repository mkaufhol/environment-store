from collections.abc import Mapping

from hypothesis import given
from hypothesis import strategies as st

from environment_store.core.merge import MergeOrder, merge, merge_with_sources
from tests.support.strategies import store_names, variable_maps

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
