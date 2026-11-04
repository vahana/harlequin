from typing import Iterator, Sequence, Type

import pytest
from textual.pilot import Pilot
from textual.widgets import Input
from textual.widgets._tree import TreeNode

from harlequin import Harlequin
from harlequin.catalog import Catalog, CatalogItem
from harlequin.components.data_catalog.database_tree import DatabaseTree
from harlequin_duckdb.adapter import DuckDbAdapter
from tests.functional_tests.helpers import wait_for_catalog_tree, wait_for_editor
from tests.waiting import settle_app, wait_for

KEY_NAMES = {".": "full_stop", "_": "underscore"}


def item(
    identifier: str,
    label: str,
    type_label: str,
    children: Sequence[CatalogItem] = (),
) -> CatalogItem:
    return CatalogItem(
        qualified_identifier=identifier,
        query_name=identifier,
        label=label,
        type_label=type_label,
        children=list(children),
    )


def database(name: str, schemas: dict[str, list[str]]) -> CatalogItem:
    return item(
        name,
        name,
        "db",
        [
            item(
                f"{name}.{schema_name}",
                schema_name,
                "s",
                [
                    item(f"{name}.{schema_name}.{table_name}", table_name, "t")
                    for table_name in table_names
                ],
            )
            for schema_name, table_names in schemas.items()
        ],
    )


def build_catalog() -> Catalog:
    return Catalog(
        items=[
            database(
                "sales_db",
                {
                    "main": ["orders", "customers"],
                    "archive": ["order_items", "invoices"],
                },
            ),
            database("hr_db", {"main": ["orders", "employees"]}),
        ]
    )


def built_paths(tree: DatabaseTree) -> list[str]:
    def walk(node: TreeNode[CatalogItem], prefix: str) -> Iterator[str]:
        for child in node.children:
            assert child.data is not None
            path = f"{prefix}{child.data.label}"
            yield path
            yield from walk(child, f"{path}/")

    return list(walk(tree.root, ""))


async def start_filter(pilot: Pilot, app: Harlequin) -> DatabaseTree:
    await wait_for_editor(pilot, app)
    tree = await wait_for_catalog_tree(pilot, app)
    tree.catalog = build_catalog()
    await wait_for(
        pilot,
        lambda: not tree.loading and "sales_db" in built_paths(tree),
        description="the test catalog to render",
    )
    tree.focus()
    await settle_app(pilot)
    return tree


async def filter_to(
    pilot: Pilot, app: Harlequin, tree: DatabaseTree, text: str
) -> None:
    await pilot.press("slash")
    await settle_app(pilot)
    assert app.data_catalog.query_one("#catalog-filter", Input).has_focus
    await pilot.press(*[KEY_NAMES.get(character, character) for character in text])
    await wait_for(
        pilot,
        lambda: tree._filter_text == text.casefold(),
        description="the filter to be applied",
    )
    await settle_app(pilot)


def make_app(duckdb_adapter: Type[DuckDbAdapter]) -> Harlequin:
    return Harlequin(duckdb_adapter((":memory:",)), connection_hash="catalog_filter")


@pytest.mark.asyncio
async def test_slash_filters_catalog_to_matching_items(
    duckdb_adapter: Type[DuckDbAdapter],
) -> None:
    app = make_app(duckdb_adapter)
    async with app.run_test(size=(120, 36)) as pilot:
        tree = await start_filter(pilot, app)
        await filter_to(pilot, app, tree, "ord")

        paths = built_paths(tree)
        assert "sales_db/main/orders" in paths
        assert "sales_db/archive/order_items" in paths
        assert "hr_db/main/orders" in paths
        assert "sales_db/main/customers" not in paths
        assert "sales_db/archive/invoices" not in paths
        assert "hr_db/main/employees" not in paths

        await pilot.press("escape")
        await wait_for(
            pilot,
            lambda: built_paths(tree) == ["hr_db", "sales_db"],
            description="the filter to clear and the tree to collapse again",
        )
        assert not app.data_catalog.query("#catalog-filter")
        assert tree.has_focus


@pytest.mark.asyncio
async def test_dot_scopes_the_table_to_a_database(
    duckdb_adapter: Type[DuckDbAdapter],
) -> None:
    app = make_app(duckdb_adapter)
    async with app.run_test(size=(120, 36)) as pilot:
        tree = await start_filter(pilot, app)
        await filter_to(pilot, app, tree, "sales.ord")

        paths = built_paths(tree)
        assert "sales_db/main/orders" in paths
        assert "sales_db/archive/order_items" in paths
        assert "hr_db/main/orders" not in paths
        assert "hr_db" not in paths
        assert "sales_db/main/customers" not in paths


@pytest.mark.asyncio
async def test_dot_matches_adjacent_levels(
    duckdb_adapter: Type[DuckDbAdapter],
) -> None:
    app = make_app(duckdb_adapter)
    async with app.run_test(size=(120, 36)) as pilot:
        tree = await start_filter(pilot, app)
        await filter_to(pilot, app, tree, "archive.inv")

        paths = built_paths(tree)
        assert "sales_db/archive/invoices" in paths
        assert "sales_db/archive/order_items" not in paths
        assert "hr_db" not in paths


@pytest.mark.asyncio
async def test_trailing_dot_shows_everything_under_a_match(
    duckdb_adapter: Type[DuckDbAdapter],
) -> None:
    app = make_app(duckdb_adapter)
    async with app.run_test(size=(120, 36)) as pilot:
        tree = await start_filter(pilot, app)
        await filter_to(pilot, app, tree, "hr_db.")

        paths = built_paths(tree)
        assert "hr_db/main" in paths
        assert "sales_db" not in paths


@pytest.mark.asyncio
async def test_filter_is_case_insensitive_and_enter_keeps_it(
    duckdb_adapter: Type[DuckDbAdapter],
) -> None:
    app = make_app(duckdb_adapter)
    async with app.run_test(size=(120, 36)) as pilot:
        tree = await start_filter(pilot, app)
        await filter_to(pilot, app, tree, "INVOICE")
        assert "sales_db/archive/invoices" in built_paths(tree)
        assert "sales_db/main/orders" not in built_paths(tree)

        await pilot.press("enter")
        await settle_app(pilot)
        assert tree.has_focus
        assert app.data_catalog.query_one("#catalog-filter", Input).value == "INVOICE"
        assert "sales_db/main/orders" not in built_paths(tree)


@pytest.mark.asyncio
async def test_filter_with_no_matches_empties_the_tree_until_cleared(
    duckdb_adapter: Type[DuckDbAdapter],
) -> None:
    app = make_app(duckdb_adapter)
    async with app.run_test(size=(120, 36)) as pilot:
        tree = await start_filter(pilot, app)
        await filter_to(pilot, app, tree, "zzz")
        assert built_paths(tree) == []

        await pilot.press("escape")
        await wait_for(
            pilot,
            lambda: built_paths(tree) == ["hr_db", "sales_db"],
            description="the filter to clear and the tree to collapse again",
        )
