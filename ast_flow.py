import ast
import builtins
from pathlib import Path
from contracts import FlowUnit, FlowExpander, FlowMapper

# --- ВНУТРЕННИЕ ФАБРИКИ ПОЛЕЙ ---
def ast_id_factory(module_name: str):
    # raw_pair[1] — это словарь meta, забираем его idx
    return lambda raw_pair: f"{module_name}.{raw_pair[1]['idx']}"

def ast_meta_factory():
    # Возвращаем meta (индекс 1)
    return lambda raw_pair: raw_pair[1]

def ast_body_extractor():
    # Возвращаем узел AST (индекс 0)
    return lambda raw_pair: raw_pair[0]

def load(file_path):
    """Деструктурирует файл и возвращает готовый список кортежей."""
    path_obj = Path(file_path).resolve()
    module_name = path_obj.get_module_name if hasattr(path_obj, "get_module_name") else path_obj.stem

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
        raw_items.append((node, meta))

        new_stack = parent_stack + [current_idx]
        for child in ast.iter_child_nodes(node):
            dfs_walk(child, parent_stack=new_stack)

    dfs_walk(tree)
    return raw_items


class ModuleLoader(FlowExpander):
    """Рекурсивно разворачивает модули, вытаскивая корень из памяти потока."""

    def expand(self, unit: FlowUnit, id_generator, pipeline) -> list[FlowUnit]:
        if unit.meta.get("op_type") != "ImportFrom":
            return []

        module_name = unit.body.module
        project_root = Path(pipeline.pipeline_meta["project_root"])
        potential_file = project_root / f"{module_name}.py"

        if potential_file.exists():
            from pipeline import StreamPipeline
            raw_pairs = load(potential_file)
            
            ext_pipeline = StreamPipeline(
                raw_pairs,
                id_fn=ast_id_factory(module_name),
                meta_fn=ast_meta_factory(),
                body_fn=ast_body_extractor(),
                pipeline_meta=pipeline.pipeline_meta
            )

            imported_units = []
            for local_unit in ext_pipeline:
                local_unit.id = id_generator()
                imported_units.append(local_unit)
            return imported_units
        return []


class AstRouter:
    """Линейный путеводитель: шагает по реальному списку ключей."""

    def __init__(self):
        self.functions_map = {}
        self.ordered_ids = []
        self.initialized = False

    def initialize(self, pipeline):
        if self.initialized:
            return
        registry = pipeline.pipeline_meta.get("registry_map", {})
        self.ordered_ids = list(registry.keys())
        
        for uid, u in registry.items():
            if u.meta.get("op_type") in ["FunctionDef", "AsyncFunctionDef"]:
                func_name = u.body.name
                try:
                    pos = self.ordered_ids.index(uid)
                    if pos + 1 < len(self.ordered_ids):
                        self.functions_map[func_name] = self.ordered_ids[pos + 1]
                except ValueError:
                    pass
        self.initialized = True

    def get_next_id(self, unit: FlowUnit) -> Any:
        try:
            pos = self.ordered_ids.index(unit.id)
            if pos + 1 < len(self.ordered_ids):
                return self.ordered_ids[pos + 1]
        except ValueError:
            pass
        return None

    def get_jump_id(self, unit: FlowUnit) -> Any:
        if unit.meta.get("op_type") == "Call" and isinstance(unit.body.func, ast.Name):
            func_name = unit.body.func.id
            if func_name not in ["print", "asyncio", "sleep"]:
                return self.functions_map.get(func_name)
        return None

    def is_return(self, unit: FlowUnit) -> bool:
        return unit.meta.get("op_type") == "Return"


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

