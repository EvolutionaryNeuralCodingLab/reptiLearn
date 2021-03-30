import importlib
from pathlib import Path
import inspect


def instantiate_class(class_name, *args, **kwargs):
    module_name, class_name = class_name.rsplit(".", 1)
    ClassObject = getattr(importlib.import_module(module_name), class_name)
    return ClassObject(*args, **kwargs)


def load_module(path: Path, package):
    spec = importlib.util.spec_from_file_location(
        package + "." + path.stem, path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, spec


def reload_module(spec):
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def find_subclass(module, parent):
    classes = inspect.getmembers(module, inspect.isclass)
    for name, c in classes:
        if issubclass(c, parent):
            return c
    return None
