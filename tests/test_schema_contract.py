"""Contract tests between sentinel/database/schema.sql and the Supabase client.

The Postgres schema and the Python repository are maintained separately, so
they drift silently. These tests parse both and assert they agree on tables,
written columns, JSON column types and foreign-key targets.
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
SCHEMA = REPO / "sentinel" / "database" / "schema.sql"
CLIENT = REPO / "sentinel" / "database" / "supabase.py"
LOCAL = REPO / "sentinel" / "database" / "local.py"

WRITE_METHODS = {"_insert", "_batched", "_update", "_insert_ignore"}
JSON_COLUMNS = {
    "raw",
    "meta",
    "attributes",
    "model_scores",
    "evidence",
    "features",
    "composite",
    "sources",
    "citations",
    "context",
}


def schema_bodies() -> dict[str, str]:
    sql = SCHEMA.read_text(encoding="utf-8")
    return {
        match.group(1).lower(): match.group(2)
        for match in re.finditer(
            r"create\s+table\s+(?:if\s+not\s+exists\s+)?public\.(\w+)\s*\((.*?)\n\);",
            sql,
            re.IGNORECASE | re.DOTALL,
        )
    }


def schema_columns() -> dict[str, set[str]]:
    columns: dict[str, set[str]] = {}
    for table, body in schema_bodies().items():
        cols = set()
        for line in body.splitlines():
            line = line.strip()
            if not line or line.startswith("--"):
                continue
            col = re.match(r"^(\w+)\s+[a-z]", line, re.IGNORECASE)
            if col and col.group(1).lower() not in {
                "primary", "foreign", "unique", "constraint", "check", "key",
            }:
                cols.add(col.group(1).lower())
        columns[table] = cols
    return columns


def client_writes() -> tuple[dict[str, set[str]], set[str]]:
    """Return (table -> written columns, all referenced tables) from the AST."""
    tree = ast.parse(CLIENT.read_text(encoding="utf-8"))
    written: dict[str, set[str]] = {}
    referenced: set[str] = set()

    def literal_str(node: ast.AST) -> str | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value.lower()
        return None

    def dict_keys(node: ast.AST) -> set[str]:
        keys: set[str] = set()
        for sub in ast.walk(node):
            if isinstance(sub, ast.Dict):
                keys |= {
                    key.value.lower()
                    for key in sub.keys
                    if isinstance(key, ast.Constant) and isinstance(key.value, str)
                }
        return keys

    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        name = node.func.attr
        if name not in WRITE_METHODS | {"_select", "_delete"} or not node.args:
            continue
        table = literal_str(node.args[0])
        if not table:
            continue
        referenced.add(table)
        if name in WRITE_METHODS:
            target = written.setdefault(table, set())
            for arg in node.args[1:]:
                target |= dict_keys(arg)
            for keyword in node.keywords:
                target |= dict_keys(keyword.value)
    return written, referenced


def test_schema_defines_every_table_the_client_uses() -> None:
    _, referenced = client_writes()
    missing = sorted(referenced - set(schema_columns()))
    assert not missing, f"tables missing from schema.sql: {missing}"


def test_client_writes_only_columns_that_exist() -> None:
    written, _ = client_writes()
    columns = schema_columns()
    problems = {
        table: sorted(cols - columns[table])
        for table, cols in written.items()
        if table in columns and cols - columns[table]
    }
    assert not problems, f"unknown columns written: {problems}"


@pytest.mark.parametrize("name", sorted(JSON_COLUMNS))
def test_json_columns_are_jsonb(name: str) -> None:
    """The client sends dicts/lists, so these must be jsonb rather than text."""
    bodies = schema_bodies()
    found = any(
        re.search(rf"^[ \t]*{name}\s+jsonb\b", body, re.IGNORECASE | re.MULTILINE)
        for body in bodies.values()
    )
    assert found, f"no table declares {name} as jsonb"


def test_anomalies_acknowledged_is_boolean() -> None:
    """The client sends a Python bool, which Postgres would reject for an int."""
    body = schema_bodies()["anomalies"]
    assert re.search(r"acknowledged\s+boolean", body, re.IGNORECASE)


def test_every_foreign_key_points_at_a_real_table() -> None:
    """A typo'd reference passes a column check but breaks the whole migration."""
    bodies = schema_bodies()
    broken = sorted(
        {
            ref.lower()
            for body in bodies.values()
            for ref in re.findall(r"references\s+public\.(\w+)\s*\(", body, re.IGNORECASE)
            if ref.lower() not in bodies
        }
    )
    assert not broken, f"foreign keys point at unknown tables: {broken}"


def test_local_and_sqlite_schemas_cover_the_same_tables() -> None:
    """SQLite is the local fallback and must expose the same logical tables."""
    sqlite = {
        match.group(1).lower()
        for match in re.finditer(
            r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)", LOCAL.read_text(encoding="utf-8")
        )
    }
    postgres = set(schema_columns())
    # schema_meta is a SQLite bookkeeping table with no Postgres equivalent.
    only_postgres = sorted(postgres - sqlite)
    only_sqlite = sorted(sqlite - postgres - {"schema_meta"})
    assert not only_postgres, f"Postgres-only tables: {only_postgres}"
    assert not only_sqlite, f"SQLite-only tables: {only_sqlite}"


def test_rls_is_enabled_on_every_telemetry_table() -> None:
    """RLS is applied through a DO-block loop, not one literal statement."""
    sql = SCHEMA.read_text(encoding="utf-8")

    covered: set[str] = set()
    for block in re.findall(
        r"do\s+\$\$.*?enable\s+row\s+level\s+security.*?\$\$\s*;", sql, re.IGNORECASE | re.DOTALL
    ):
        array = re.search(r"array\[(.*?)\]", block, re.DOTALL)
        if array:
            covered |= {name.lower() for name in re.findall(r"'(\w+)'", array.group(1))}
    # Literal statements outside the loop.
    covered |= {
        name.lower()
        for name in re.findall(
            r"alter\s+table\s+public\.(\w+)\s+enable\s+row\s+level\s+security", sql, re.IGNORECASE
        )
    }

    expected = {
        "devices", "agents", "system_metrics", "network_metrics",
        "process_snapshots", "logs", "anomalies", "alerts", "risk_events",
        "documents", "document_chunks", "rag_queries", "ai_investigations",
        "system_events", "pairing_codes", "users",
    }
    missing = sorted(expected - covered)
    assert not missing, f"row level security is not enabled on: {missing}"


def test_schema_does_not_store_process_command_lines() -> None:
    """Command lines routinely contain tokens and passwords."""
    body = schema_bodies()["process_snapshots"]
    assert "cmdline" not in body.lower()
    assert "command" not in body.lower()
