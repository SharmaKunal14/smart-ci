"""Standalone stdlib-only probe run in the target interpreter, without imports of project code."""

import hashlib
import importlib.machinery
import importlib.metadata
import json
import platform
import sys
import sysconfig
from pathlib import Path


def main() -> None:
    root = Path(sys.argv[1]).resolve()
    names: list[str] = json.loads(sys.argv[2])
    native_roots: dict[str, str | None] = {}
    available = []
    for name in names:
        # PathFinder locates top-level modules without importing their initializers.
        spec = importlib.machinery.PathFinder.find_spec(name, [str(root), *sys.path])
        if spec is not None:
            available.append(name)
        origin = Path(spec.origin).resolve() if spec and spec.origin else None
        native_roots[name] = (
            origin.relative_to(root).as_posix()
            if origin is not None and origin.is_relative_to(root)
            else None
        )
    distributions = {
        d.metadata["Name"].lower(): d.version
        for d in importlib.metadata.distributions()
        if d.metadata["Name"]
    }
    observer = importlib.machinery.PathFinder.find_spec("smartci")
    if observer is None or not observer.origin:
        raise ValueError("Smart CI observation plugin unavailable")
    observer_path = Path(observer.origin).parent / "adapters" / "pytest_plugin.py"
    with observer_path.open("rb") as stream:
        observer_source = stream.read(1024 * 1024 + 1)
    if len(observer_source) > 1024 * 1024:
        raise ValueError("observation plugin exceeds limit")
    hooks = {}
    for hook in sys.meta_path:
        module = getattr(hook, "__module__", type(hook).__module__)
        source = getattr(sys.modules.get(module), "__file__", None)
        if source and module not in {"_frozen_importlib", "_frozen_importlib_external"}:
            with Path(source).open("rb") as stream:
                raw = stream.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise ValueError("import hook exceeds size limit")
            hooks[module] = hashlib.sha256(raw).hexdigest()
    data = {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": platform.system(),
        "machine": platform.machine(),
        "abi": str(sysconfig.get_config_var("SOABI")),
        "observer_digest": hashlib.sha256(observer_source).hexdigest(),
        "distributions": dict(sorted(distributions.items())),
        "external_modules": sorted(importlib.metadata.packages_distributions()),
        "available_modules": sorted(available),
        "stdlib": sorted(sys.stdlib_module_names),
        "native_roots": native_roots,
        "import_hooks": sorted(
            f"{getattr(h, '__module__', type(h).__module__)}.{getattr(h, '__name__', type(h).__name__)}"
            for h in sys.meta_path
        ),
        "hook_hashes": hooks,
        "ambient": {},
        "configuration": {},
    }
    Path(sys.argv[3]).write_text(json.dumps(data, sort_keys=True))


if __name__ == "__main__":
    main()
