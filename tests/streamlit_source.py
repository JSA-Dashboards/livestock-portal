"""
Lift functions out of a Streamlit page without importing it.

A page under apps/ is a SCRIPT: importing it runs the whole dashboard and
hits the USDA API, so a unit test cannot just import the function it wants.

AND IT HAS TO BE ast, NOT A REGEX. Pulling `NAME = (...)` with a regex broke
the moment a comment inside the tuple contained a bracket, and eleven tests
then failed on the extraction rather than on the thing under test. Matching
prose instead of code is the mistake this repo keeps making -- a denylist
stem, a `<body>` inside a CSS comment, a test asserting against its own
docstring. Parsing the module removes the whole class of it.
"""
from __future__ import annotations

import ast
from pathlib import Path


def load_from_app(path: Path, *names: str, consts: tuple = (),
                  globals_: dict | None = None) -> object:
    """
    Exec the named top-level functions (and constants) from `path`.

    Returns the single function when one name is given, otherwise the
    namespace dict. Raises if anything named is missing, so a rename is a
    loud failure rather than a silently skipped test.
    """
    src = Path(path).read_text(encoding="utf-8")
    tree = ast.parse(src)

    chunks: list[str] = []
    found: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name) \
                and node.targets[0].id in consts:
            chunks.append(ast.get_source_segment(src, node))
            found.add(node.targets[0].id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name in names:
            chunks.append(ast.get_source_segment(src, node))
            found.add(node.name)

    missing = (set(consts) | set(names)) - found
    assert not missing, f"not found at module level in {Path(path).name}: {sorted(missing)}"

    ns = dict(globals_ or {})
    exec("\n\n".join(chunks), ns)
    return ns[names[0]] if len(names) == 1 else ns
