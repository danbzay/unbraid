import ast
from pathlib import Path 

import logging
logger = logging.getLogger("unbraid")



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

import ast
from pathlib import Path


class AstRouter:
    """Абсолютно ленивый роутер: линкует и переезжает в модули на лету [Example 4]."""

    def get_next_unit(self, pipeline) -> Any:
        """Реактивно выдает"""

        if pipeline.index >= len(pipeline.units):
            return None

        unit = pipeline.units[pipeline.index]
        logger.info(f"[AST_FLOW]: {unit=}")
        logger.info(f"[AST_FLOW]: {pipeline.ctx=}")

        for trigger in pipeline.ctx["triggers"].values():
            trigger()
                

        pipeline.index += 1

        op = unit.meta.get("op_type")

        if op == "ImportFrom":
            module_name = unit.body.module
            
            project_root = Path(pipeline.ctx.get("project_root", "."))
            potential_file = project_root / f"{module_name}.py"

            if potential_file.exists():
                logger.info(f"[IMPORT]: {module_name}")
                
                module_pipeline = load(
                    potential_file, project_root=project_root
                ).route(AstRouter())

                module_units = module_pipeline.units
                
                if module_units:
                    def reroute_trigger():
                        return next(module_pipeline)
                    
                    pipeline.ctx["triggers"]["reroute"] = reroute_trigger

                    def endroute_trigger():
                        if module_pipeline.index >= len(module_units) - 1:
                            module_pipeline.ctx["triggers"].pop("endroute")
                            pipeline.ctx["triggers"].pop("reroute")

                    module_pipeline.ctx["triggers"][
                        "endroute"
                    ] = endroute_trigger

                    logger.info(f"[IMPORT]: {pipeline.ctx=}")
                    logger.info(f"[IMPORT]: {module_pipeline.ctx=}")
                    return unit
            else:
                print(f"-> [ОШИБКА]: Модуль {module_name}.py не найден по пути {potential_file}")

        return unit



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

