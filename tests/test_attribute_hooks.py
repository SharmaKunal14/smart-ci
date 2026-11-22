"""Only closed rejection may remove the opaque attribute-dispatch diagnostic."""

import pytest
from test_discovery import analyse

SOURCE = '''class ReadOnlyError(AttributeError):
    """Mutation is unsupported."""

class Nodes:
    def __getattr__(self, key: str) -> object:
        if key in {"clear", "append", "pop", "insert", "remove", "extend"}:
            raise ReadOnlyError("Use the public mutation API")
        raise AttributeError(key)
'''


def gaps(source):
    return {g.code for g in analyse({"app.py": source}).gaps}


def test_readonly_hook_has_no_loader_and_remains_deterministic():
    files = {
        "app.py": SOURCE,
        "tests/__init__.py": "",
        "tests/test_app.py": "from app import Nodes\n",
    }
    result = analyse(files)
    assert not result.gaps
    assert "app.py" in result.dependencies["tests/test_app.py"]
    repeated = analyse(dict(reversed(list(files.items()))))
    assert result.edges == repeated.edges
    assert result.imports == repeated.imports


@pytest.mark.parametrize(
    "source",
    [
        SOURCE.replace("raise AttributeError(key)", "return load(key)"),
        SOURCE.replace("raise AttributeError(key)", "raise AttributeError(load(key))"),
        SOURCE.replace("raise AttributeError(key)", "raise AttributeError(f'{key}')"),
        SOURCE.replace(
            "raise AttributeError(key)", "raise AttributeError(key) from load(key)"
        ),
        SOURCE.replace(
            'raise ReadOnlyError("Use the public mutation API")',
            "raise ReadOnlyError(key, extra=load(key))",
        ),
        SOURCE.replace(
            'raise ReadOnlyError("Use the public mutation API")',
            "raise ReadOnlyError(*args)",
        ),
        SOURCE.replace(
            'if key in {"clear", "append", "pop", "insert", "remove", "extend"}:',
            "if key in METHODS:",
        ),
        SOURCE.replace('"extend"}', "load(key)}"),
        SOURCE.replace("if key in", "if key not in"),
        SOURCE.replace(
            "        raise AttributeError(key)",
            "        load(key)\n        raise AttributeError(key)",
        ),
        SOURCE.replace(
            "class ReadOnlyError(AttributeError):",
            "@decorate\nclass ReadOnlyError(AttributeError):",
        ),
        SOURCE.replace(
            "class ReadOnlyError(AttributeError):",
            "class ReadOnlyError(AttributeError, metaclass=Factory):",
        ),
        SOURCE.replace(
            "class ReadOnlyError(AttributeError):", "class ReadOnlyError(CustomError):"
        ),
        SOURCE.replace(
            '    """Mutation is unsupported."""',
            "    def __init__(self, key):\n        load(key)",
        ),
        SOURCE.replace('    """Mutation is unsupported."""', "    initialize()"),
        SOURCE.replace("    def __getattr__", "    @decorate\n    def __getattr__"),
        SOURCE.replace("    def __getattr__", "    async def __getattr__"),
        SOURCE.replace("key: str)", "key: str = load())"),
        SOURCE.replace("key: str)", "key: str, *args)"),
        SOURCE.replace("key: str)", "key: str, /)"),
        SOURCE.replace("key: str)", "key: str, *, default=None)"),
        SOURCE.replace("class Nodes:", "class Nodes[ReadOnlyError]:"),
        SOURCE.replace("__getattr__(", "__getattr__[ReadOnlyError]("),
        SOURCE.replace(
            "ReadOnlyError(AttributeError)", "ReadOnlyError[T](AttributeError)"
        ),
        SOURCE + "ReadOnlyError = replacement\n",
        SOURCE + "ReadOnlyError.__init__ = replacement\n",
        SOURCE + "alias = ReadOnlyError\n",
        SOURCE + "def ReadOnlyError(key): return load(key)\n",
        SOURCE + "from external import ReadOnlyError\n",
        SOURCE + "from external import *\n",
        SOURCE + "AttributeError = replacement\n",
        SOURCE + "try: pass\nexcept Exception as ReadOnlyError: pass\n",
        SOURCE + "match value:\n    case ReadOnlyError: pass\n",
        SOURCE + "match value:\n    case [*ReadOnlyError]: pass\n",
        SOURCE + "match value:\n    case {**ReadOnlyError}: pass\n",
        SOURCE + "del ReadOnlyError\n",
    ],
)
def test_unproven_exception_binding_or_behavior_remains_opaque(source):
    assert "DYNAMIC_ATTRIBUTE_HOOK" in gaps(source)


@pytest.mark.parametrize(
    "source",
    [
        "def __getattr__(name):\n    raise AttributeError(name)\n",
        'def __getattr__(name):\n    """No exports."""\n    raise AttributeError("No attributes")\n',
        SOURCE.replace('"""Mutation is unsupported."""', "pass"),
        SOURCE.replace(
            '{"clear", "append", "pop", "insert", "remove", "extend"}',
            '("clear", "pop")',
        ),
        SOURCE.replace(
            '{"clear", "append", "pop", "insert", "remove", "extend"}',
            '["clear", "pop"]',
        ),
    ],
)
def test_supported_rejection_shapes(source):
    assert "DYNAMIC_ATTRIBUTE_HOOK" not in gaps(source)


def test_other_opaque_behavior_is_not_waived():
    result = analyse(
        {"app.py": SOURCE + "\nimport importlib\nimportlib.import_module(name)\n"}
    )
    assert "DYNAMIC_ATTRIBUTE_HOOK" not in {g.code for g in result.gaps}
    assert "DYNAMIC_IMPORT" in {g.code for g in result.gaps}


def test_exception_imports_remain_edges_and_external_constructor_is_opaque():
    result = analyse(
        {
            "app.py": SOURCE.replace(
                'class ReadOnlyError(AttributeError):\n    """Mutation is unsupported."""',
                "from errors import ReadOnlyError",
            ),
            "errors.py": "class ReadOnlyError(AttributeError): pass\n",
        }
    )
    assert "DYNAMIC_ATTRIBUTE_HOOK" in {g.code for g in result.gaps}
    assert "errors.py" in result.dependencies["app.py"]
