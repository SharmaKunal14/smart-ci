"""Recognize attribute rejection without executing repository code."""

import ast


def _bindings(tree: ast.Module, name: str) -> list[ast.AST]:
    """Overapproximate bindings, including scopes the hook may not use."""
    found: list[ast.AST] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == name:
            if isinstance(node.ctx, (ast.Store, ast.Del)):
                found.append(node)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name == name:
                found.append(node)
        elif isinstance(node, ast.arg) and node.arg == name:
            found.append(node)
        elif isinstance(node, ast.Import):
            if any((a.asname or a.name.split(".")[0]) == name for a in node.names):
                found.append(node)
        elif isinstance(node, ast.ImportFrom):
            if any(a.name == "*" or (a.asname or a.name) == name for a in node.names):
                found.append(node)
        elif (
            isinstance(
                node,
                (
                    ast.ExceptHandler,
                    ast.MatchAs,
                    ast.MatchStar,
                    ast.TypeVar,
                    ast.ParamSpec,
                    ast.TypeVarTuple,
                ),
            )
            and node.name == name
            or isinstance(node, ast.MatchMapping)
            and node.rest == name
        ):
            found.append(node)
    return found


def _without_docstring(body: list[ast.stmt]) -> list[ast.stmt]:
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        return body[1:]
    return body


def _plain_exception(tree: ast.Module, name: str, uses: set[int]) -> bool:
    if _bindings(tree, "AttributeError"):
        return False
    if name == "AttributeError":
        return True
    definitions = _bindings(tree, name)
    if len(definitions) != 1:
        return False
    definition = definitions[0]
    if not (
        isinstance(definition, ast.ClassDef)
        and definition in tree.body
        and not definition.decorator_list
        and not definition.keywords
        and not definition.type_params
        and len(definition.bases) == 1
        and isinstance(definition.bases[0], ast.Name)
        and definition.bases[0].id == "AttributeError"
        and all(isinstance(s, ast.Pass) for s in _without_docstring(definition.body))
    ):
        return False
    # An alias could mutate the exception constructor. Only the recognized
    # raise sites may use this local class; otherwise retain the original gap.
    return all(
        id(node) in uses
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and node.id == name
    )


def rejecting_attribute_hook(node: ast.FunctionDef, tree: ast.Module) -> bool:
    """A finite name-membership guard followed by unconditional rejection.

    No returned values, loaders, mutations, formatting calls or custom exception
    constructors are supported. The normal visitor still examines the whole
    module and retains all other unsupported-behavior diagnostics.
    """
    args = node.args
    if (
        node.name != "__getattr__"
        or node.decorator_list
        or node.type_params
        or args.posonlyargs
        or len(args.args) not in {1, 2}
        or args.kwonlyargs
        or args.vararg
        or args.kwarg
        or args.defaults
    ):
        return False
    name = args.args[-1].arg
    body = _without_docstring(node.body)
    if not body or not isinstance(body[-1], ast.Raise):
        return False
    raises = [body[-1]]
    for statement in body[:-1]:
        if not isinstance(statement, ast.If) or statement.orelse:
            return False
        test = statement.test
        if not (
            isinstance(test, ast.Compare)
            and isinstance(test.left, ast.Name)
            and test.left.id == name
            and len(test.ops) == len(test.comparators) == 1
            and isinstance(test.ops[0], ast.In)
            and isinstance(test.comparators[0], (ast.Set, ast.Tuple, ast.List))
            and test.comparators[0].elts
            and all(
                isinstance(item, ast.Constant) and isinstance(item.value, str)
                for item in test.comparators[0].elts
            )
            and len(statement.body) == 1
            and isinstance(statement.body[0], ast.Raise)
        ):
            return False
        raises.append(statement.body[0])
    constructors: dict[str, set[int]] = {}
    for statement in raises:
        exc = statement.exc
        if not (
            statement.cause is None
            and isinstance(exc, ast.Call)
            and isinstance(exc.func, ast.Name)
            and not exc.keywords
            and len(exc.args) == 1
            and (
                isinstance(exc.args[0], ast.Constant)
                and isinstance(exc.args[0].value, str)
                or isinstance(exc.args[0], ast.Name)
                and exc.args[0].id == name
            )
        ):
            return False
        constructors.setdefault(exc.func.id, set()).add(id(exc.func))
    return all(_plain_exception(tree, key, uses) for key, uses in constructors.items())
