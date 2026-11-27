"""Bound computed import targets using immutable syntax, never observed paths."""

import ast

from .attribute_hooks import binding_sites


def _unescaped_loader(tree: ast.Module, expression: ast.expr) -> bool:
    module_alias = isinstance(expression, ast.Attribute)
    name = expression.value if isinstance(expression, ast.Attribute) else expression
    if not isinstance(name, ast.Name):
        return False
    definitions = binding_sites(tree, name.id)
    if len(definitions) != 1 or definitions[0] not in tree.body:
        return False
    definition = definitions[0]
    if module_alias:
        if not (
            isinstance(expression, ast.Attribute)
            and expression.attr == "import_module"
            and isinstance(definition, ast.Import)
            and len(definition.names) == 1
            and definition.names[0].name == "importlib"
        ):
            return False
    elif not (
        isinstance(definition, ast.ImportFrom)
        and definition.module == "importlib"
        and definition.level == 0
        and len(definition.names) == 1
        and definition.names[0].name == "import_module"
    ):
        return False
    # A copied/passed alias could mutate the loader. All references must be
    # direct calls; shadowing, assignments and wildcard imports fail above.
    uses = set()
    for item in ast.walk(tree):
        if not isinstance(item, ast.Call):
            continue
        function = item.func
        if module_alias:
            if not (
                isinstance(function, ast.Attribute) and function.attr == "import_module"
            ):
                continue
            function = function.value
        if isinstance(function, ast.Name) and function.id == name.id:
            uses.add(id(function))
    return all(
        id(item) in uses
        for item in ast.walk(tree)
        if isinstance(item, ast.Name) and item.id == name.id
    )


def finite_import_targets(
    node: ast.Call, tree: ast.Module, local_modules: dict[str, str]
) -> tuple[str, ...]:
    """Return every possible local target of load(('pkg.a', 'pkg.b')[index]).

    This bounds only the import target. Other code, import hooks, plugins and
    environment checks retain their usual gaps and full-suite fallback.
    """
    if len(node.args) != 1 or node.keywords:
        return ()
    argument = node.args[0]
    if not (
        isinstance(argument, ast.Subscript)
        and isinstance(argument.value, ast.Tuple)
        and 1 <= len(argument.value.elts) <= 32
        and (
            isinstance(argument.slice, ast.Name)
            or isinstance(argument.slice, ast.Constant)
            and type(argument.slice.value) is int
        )
    ):
        return ()
    targets = set()
    for value in argument.value.elts:
        if not (
            isinstance(value, ast.Constant)
            and isinstance(value.value, str)
            and 0 < len(value.value) <= 512
            and not value.value.startswith(".")
            and value.value in local_modules
        ):
            return ()
        targets.add(value.value)
    if any(m.split(".")[0] == "importlib" for m in local_modules):
        return ()
    if not _unescaped_loader(tree, node.func):
        return ()
    return tuple(sorted(targets))
