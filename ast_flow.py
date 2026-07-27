import ast
from pathlib import Path


def ast_id_factory(module_name: str):
    # raw_pair — это кортеж (node, meta), берем meta под индексом 1 и читаем idx
    return lambda raw_pair: f"{module_name}.{raw_pair[1]['idx']}"


def ast_meta_factory():
    # Извлекаем и возвращаем чистый словарь meta (индекс 1)
    return lambda raw_pair: raw_pair[1]


def ast_body_extractor():
    # Извлекаем и возвращаем чистый сырой узел AST (индекс 0) -> упадет в body!
    return lambda raw_pair: raw_pair[0]


def load(file_path, project_root=None):
    """Деструктурирует файл и сразу возвращает готовый объект StreamPipeline."""
    path_obj = Path(file_path).resolve()
    module_name = path_obj.stem
    root_path = Path(project_root) if project_root else path_obj.parent

    with open(path_obj, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())

    raw_items = []
    atom_counter = 0

    def dfs_walk(node, parent_stack=None):
        nonlocal atom_counter
        if parent_stack is None:
            parent_stack = []

        if isinstance(node, ast.Module):
            for child in ast.iter_child_nodes(node):
                dfs_walk(child, parent_stack=[])
            return

        current_idx = atom_counter
        atom_counter += 1

        meta = {
            "module": module_name,
            "idx": current_idx,
            "preds": list(parent_stack),
            "op_type": type(node).__name__,
        }
        # Упаковываем строго в кортеж (узел, мета)
        raw_items.append((node, meta))

        new_stack = parent_stack + [current_idx]
        for child in ast.iter_child_nodes(node):
            dfs_walk(child, parent_stack=new_stack)

    dfs_walk(tree)

    from pipeline import StreamPipeline
    return StreamPipeline(
        raw_items,
        id_fn=ast_id_factory(module_name),
        meta_fn=ast_meta_factory(),
        body_fn=ast_body_extractor(),
        ctx={"project_root": root_path, "target_file": path_obj}
    )


class AstRouter:
    """Абсолютно ленивый линейный роутер верхнего уровня."""

    def __init__(self):
        pass

    def calculate_next_unit(self, unit, pipeline):
        ordered_units = pipeline.units
        try:
            current_pos = ordered_units.index(pipeline.registry_map[unit.id])
            if current_pos + 1 < len(ordered_units):
                return ordered_units[current_pos + 1]
        except (ValueError, KeyError):
            pass
        return None
from contracts import FlowMapper

class FlowScopeTracker(FlowMapper):
    """Отслеживает области видимости по правилам модулей Python."""

    def __init__(self):
        self.module_globals = {}
        self.local_scopes_stack = []

    def __call__(self, unit: FlowUnit) -> None:
        op = unit.meta["op_type"]
        mod_name = unit.meta["module"]

        if mod_name not in self.module_globals:
            self.module_globals[mod_name] = {}
        current_global = self.module_globals[mod_name]

        if op in ["FunctionDef", "AsyncFunctionDef"]:
            self.local_scopes_stack.append({})
            func_name = unit.body.name
            if len(self.local_scopes_stack) > 1:
                self.local_scopes_stack[-2][func_name] = f"<function {func_name}>"
            else:
                current_global[func_name] = f"<function {func_name}>"

        if op == "Assign":
            for target in unit.body.targets:
                var_name = None
                if isinstance(target, ast.Name):
                    var_name = target.id
                elif isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
                    var_name = f"{target.value.id}.{target.attr}"

                if var_name:
                    if hasattr(builtins, var_name):
                        continue
                    var_expr = ast.unparse(unit.body.value)
                    if self.local_scopes_stack:
                        self.local_scopes_stack[-1][var_name] = var_expr
                    else:
                        current_global[var_name] = var_expr

        available_now = {k: v for k, v in current_global.items()}
        for scope in self.local_scopes_stack:
            for k, v in scope.items():
                available_now[k] = v

        unit.meta["live_variables"] = available_now

        if op == "Return":
            if self.local_scopes_stack:
                self.local_scopes_stack.pop()

