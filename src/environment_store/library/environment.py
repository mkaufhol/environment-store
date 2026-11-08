"""The result of loading stores: merge, apply to an environment, export.

Merged variables come in the core's output order: stores in load order, each
store's variables sorted by name, a shared variable at its first position. Nested output keeps
the load order of the stores, each store's variables sorted by name.
"""

import os
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

from environment_store.core.errors import ValidationError
from environment_store.core.merge import MergeOrder, merge, merge_with_sources, nested, nested_flat
from environment_store.core.validation import validate_store_name, validate_variables
from environment_store.formats import dotenv, json_format, toml_format
from environment_store.formats.infer import Format, infer_format
from environment_store.library.files import write_output_file

__all__ = ["Environment"]


@dataclass(frozen=True, slots=True, kw_only=True)
class Environment:
    """Loaded stores in load order, with the merge order to combine them.

    Attributes:
        stores: `(store name, variables)` pairs in load order (read-only copies).
        order: Which store wins for a variable present in several stores.
    """

    # Values may be secrets.
    stores: tuple[tuple[str, Mapping[str, str]], ...] = field(repr=False)
    order: MergeOrder

    def __post_init__(self) -> None:
        """Validate and freeze the stores.

        Raises:
            ValidationError: An invalid store name, variable name or value, or an unknown order.
        """
        if not isinstance(self.order, MergeOrder):
            message = f"order must be a MergeOrder, got {self.order!r}"
            raise ValidationError(message)
        frozen = tuple(
            (validate_store_name(name), MappingProxyType(validate_variables(variables)))
            for name, variables in self.stores
        )
        object.__setattr__(self, "stores", frozen)

    def variables(self) -> dict[str, str]:
        """Merge the stores.

        Returns:
            Variable name → winning value, in output order.
        """
        return merge(self.stores, order=self.order)

    def with_sources(self) -> dict[str, tuple[str, str]]:
        """Merge the stores and name the store each value comes from.

        Returns:
            Variable name → `(value, winning store)`, in output order.
        """
        return merge_with_sources(self.stores, order=self.order)

    def nested(self) -> dict[str, dict[str, str]]:
        """Keep each store in its own namespace (`--nested`).

        Returns:
            Store name → its variables sorted by name, in load order.

        Raises:
            ValidationError: A store is loaded more than once.
        """
        return {
            store: dict(sorted(variables.items()))
            for store, variables in nested(self.stores).items()
        }

    def nested_flat(self) -> dict[str, str]:
        """Prefix each variable with its store name in SCREAMING_SNAKE_CASE.

        Returns:
            Flat key → value; stores in load order, variables sorted by name.

        Raises:
            ValidationError: A store is loaded more than once, or two flat keys collide.
        """
        return nested_flat(list(self.nested().items()))

    def apply(
        self,
        *,
        overwrite: bool = False,
        nested: bool = False,
        environ: MutableMapping[str, str] | None = None,
    ) -> dict[str, str]:
        """Write the variables into an environment.

        Args:
            overwrite: Replace variables that are already set; otherwise they are kept.
            nested: Use the prefixed names of nested mode instead of merging.
            environ: The target; `None` for `os.environ`.

        Returns:
            The variables that were set.
        """
        target = os.environ if environ is None else environ
        values = self.nested_flat() if nested else self.variables()
        applied = {name: value for name, value in values.items() if overwrite or name not in target}
        target.update(applied)
        return applied

    def dumps(self, fmt: Format | str, *, nested: bool = False) -> str:
        """Serialize the variables.

        Args:
            fmt: `dotenv`, `json` or `toml`.
            nested: One namespace per store instead of merging.

        Returns:
            The document.

        Raises:
            ValidationError: Unknown format, a nested collision, or a value dotenv cannot hold.
        """
        resolved = _format(fmt)
        if resolved is Format.DOTENV:
            return dotenv.dumps(self.nested_flat() if nested else self.variables())
        module = json_format if resolved is Format.JSON else toml_format
        return module.dumps_nested(self.nested()) if nested else module.dumps(self.variables())

    def to_file(
        self,
        path: Path | str | os.PathLike[str],
        *,
        fmt: Format | str | None = None,
        nested: bool = False,
        force: bool = False,
    ) -> None:
        """Export the variables to a file with mode `0600`, as it holds decrypted secrets.

        The document is built before the file is opened, so a refused value leaves no file.

        Args:
            path: The output file.
            fmt: The format; `None` infers it from the file name.
            nested: One namespace per store instead of merging.
            force: Replace an existing file (atomically).

        Raises:
            ValidationError: No format given or inferable, a refused value, or an existing file
                without `force`.
            BackendError: The file cannot be written.
        """
        target = Path(path)
        resolved = infer_format(target) if fmt is None else _format(fmt)
        if resolved is None:
            message = f"cannot infer the format of '{target}' from its name"
            raise ValidationError(message, hint="pass fmt='dotenv', fmt='json' or fmt='toml'")
        write_output_file(target, self.dumps(resolved, nested=nested), force=force)


def _format(fmt: Format | str) -> Format:
    try:
        return Format(fmt)
    except ValueError as err:
        choices = ", ".join(member.value for member in Format)
        message = f"unknown format {fmt!r}: use one of {choices}"
        raise ValidationError(message) from err
