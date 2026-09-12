import logging
logger = logging.getLogger(f"unbraid.{__name__}")

import ast
from pathlib import Path
from pipeline import StreamPipeline, DerivedUnit

import ast_flow

DYNAMIC_PASSES = [
#    ast_flow.resolve_calls,
#    ast_flow.resolve_assigns, 
]

def parse_module(module_name, project_root=None, __main__=False):
    """
    Парсит модуль по его имени. Находит файл внутри project_root,
    строит граф AST и возвращает настроенный StreamPipeline.
    """
    root_path = (
        Path(project_root).resolve() if project_root else Path(".").resolve()
    )
    
    relative_path = module_name.replace(".", "/") + ".py"
    file_path = root_path / relative_path
    
    if not file_path.exists():
        raise FileNotFoundError(
            f"Не удалось найти модуль {module_name} по пути {file_path}"
        )

    with open(file_path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())

    derived_tuple = ()
    atom_counter = 0
    if __main__ == True: 
        module_name = "__main__"

    def dfs_walk(node, parent_stack=[0], scope_stack=None):
        nonlocal atom_counter

        if isinstance(node, ast.Module):
            for child in ast.iter_child_nodes(node):
                yield from dfs_walk(child, parent_stack=[0])
            return

        current_idx = atom_counter
        atom_counter += 1
        meta = {
            "module": module_name,
            "idx": current_idx,
            "preds": list(parent_stack),
        }
        
        unit = DerivedUnit(body=node, meta=meta)
        unit.id = current_idx 

        yield unit

        new_stack = parent_stack.copy()
        new_stack.append(current_idx)

        for child in ast.iter_child_nodes(node):
            yield from dfs_walk( child, parent_stack=new_stack)

    module_pipeline = StreamPipeline(
        dfs_walk(tree),
        project_root=root_path,
        module_name=module_name,
        symbol_table={},
        scope_name=module_name
    )

    module_pipeline._shallow_attributes.extend(
        ["parent_scope", "active_scopes", "modules_cache"]
    )
    module_pipeline._infra_attributes.append("symbol_table")

    return module_pipeline

import ast
import copy
from pipeline import StreamPipeline

def resolve_scopes(current_stream, pipeline):
    """
    Обрабатывает основной и импортируемые модули. Вырезает из них тела функций
    и классов в отдельные StreamPipeline и линкует их в symbol_table.
    """
    logger = logging.getLogger(f"unbraid.{__name__}.resolve_scopes")

    if not hasattr(pipeline, "active_scopes"):
        pipeline.active_scopes = {0: pipeline}
    if not hasattr(pipeline, "symbol_table"):
        pipeline.symbol_table = {}
    if not hasattr(pipeline, "modules_cache"):
        pipeline.modules_cache = {}
        pipeline.modules_cache[pipeline.module_name] = pipeline

    logger.info(
        f"[RESOLVE SCOPES]: resolving {pipeline}\n"
        f"modules_cache: {list(pipeline.modules_cache.keys())}\n"
        f"symbol_table: {str(pipeline.symbol_table):.70}"
    )
    for item in current_stream:
        preds = item.meta.get("preds", [])
        current_scope = pipeline
        for pred_id in reversed(preds):
            if pred_id in pipeline.active_scopes:
                current_scope = pipeline.active_scopes[pred_id]
                break
        scope_type = None
        logger.debug(
            f"[RESOLVE SCOPES]: {item.meta["idx"]}: {str(item.body):.49}\n"
            f"{pipeline=}\n{preds=}\n{current_scope=}\n"
            f"active_scopes: {list(pipeline.active_scopes.keys())}\n"
        )

        # new scope (class, function, async function) ----------------------
        if isinstance(item.body, ast.ClassDef):
            scope_type = "class"
        if isinstance(item.body, (ast.FunctionDef, ast.AsyncFunctionDef)):
            scope_type = "local"

        if scope_type:
            if item.meta.get("scope_resolved"):
                logger.debug(
                    f"[RESOLVE SCOPES]: Скоуп {item.body.name} уже обработан"
                )
                yield item
                continue

            scope_name = item.body.name
            node_idx = item.meta["idx"]

            scope_pipeline = StreamPipeline().merge_context_from(
                pipeline,
                parent_scope=pipeline, 
                scope_type=scope_type, 
                scope_name=scope_name,
                symbol_table = {}
            )
            if scope_type == "class":
                scope_pipeline.instance_context = scope_pipeline
            else: 
                scope_pipeline.instance_context = getattr(
                    current_scope, "instance_context", None
                )
            current_scope.symbol_table[scope_name] = {
                "type": scope_type,
                "node_idx": node_idx,
                "body_pipeline": scope_pipeline  
            }
            pipeline.active_scopes[node_idx] = scope_pipeline

            logger.info(
                f"[RESOLVE SCOPES]: Создан {scope_pipeline}, "
                f"Записан в таблице {current_scope} c ключом {scope_name}, "
                f"{node_idx=}"
            )
            item.meta["scope_resolved"] = True
            
            key = f"divert_{scope_name}_{node_idx}"
            pipeline.divert_to(
                scope_pipeline,
                is_group_member=lambda x, idx=node_idx: (
                    x.meta.get("idx") == idx 
                    or idx in x.meta.get("preds", [])
                ),
                key=key,
                priority=len(item.meta.get("preds", []))
            )
            yield item
            continue

        # imports ------------------------------------------------------
        if isinstance(item.body, (ast.Import, ast.ImportFrom)):

            import_node = item.body
            module_names = []
            if isinstance(import_node, ast.ImportFrom):
                if import_node.module:
                    module_names.append(import_node.module)
            else:
                module_names.extend(
                    alias.name for alias in import_node.names
                )

            # resolve new modules
            for module_name in module_names:
                if module_name not in pipeline.modules_cache:
                    import_file_path = (
                        pipeline.project_root / f"{module_name}.py"
                    )
                    if import_file_path.exists():
                        logger.info(
                            f"[RESOLVE_SCOPES]: import:{import_file_path}"
                        )
                        pipeline.modules_cache[module_name] = (
                            parse_module(
                                module_name, 
                                project_root=pipeline.project_root,
                            )
                            .pipe(STATIC_PASSES).execute()
                            .pipe(DYNAMIC_PASSES).execute()
                        )
                    else:
                        logger.warning(
                            f"[RESOLVE_SCOPES]: {module_name} не добавлен")

            for alias in import_node.names:
                final_name = alias.asname if alias.asname else alias.name
                if isinstance(item.body, ast.Import):
                    current_scope.symbol_table[final_name] = {
                        "type": "imported_module",
                        "original_module": alias.name,
                        "node_idx": item.meta["idx"]
                    }
                else:
                    module_name = import_node.module
                    imported_module_sp = (
                        pipeline.modules_cache.get(module_name)
                    )
                    imported_scope = (
                        getattr(imported_module_sp, "symbol_table", {}) 
                        if imported_module_sp else {}
                    )
                    original_info = imported_scope.get(alias.name, {
                        "type": "unknown_external"
                    })

                    current_scope.symbol_table[final_name] = {
                        "type": "imported_name",
                        "source_module": module_name,
                        "original_name": alias.name,  
                        "node_idx": item.meta["idx"],
                        "body_pipeline": original_info.get("body_pipeline")
                    }

            yield item
            continue

        yield item

def resolve_calls(current_stream, pipeline):
    """
    Оператор обработки вызовов ast.Call.
    Ищет шаблон пайплайна функции, создает изолирует его в фрэйм, обрабатывает 
    фрэйм, и инжектирует в поток.
    """

    logger = logging.getLogger(f"unbraid.{__name__}.resolve_calls")

    logger.debug(f"[RESOLVE_CALLS]: resolving {pipeline}, {pipeline.term_len=}")

    if not hasattr(pipeline, "call_counters"):
        pipeline.call_counters = {}

    for item in current_stream:
        if (
            isinstance(item.body, ast.Call) and 
            not item.meta.get("call_injected")
        ):
            logger.debug(
                f"[RESOLVE_CALLS]: {item.meta["idx"]}: {str(item.body):.50}"
            )
            call_node = item.body
            call_idx = item.meta["idx"]
            func_name = (
                getattr(call_node.func, "id", None) or 
                getattr(call_node.func, "attr")
            )

            # нужно доработать алгоритм на случай вызова из массивов и тд
            # рекурсивный вызов игнорируем
            if func_name and getattr(pipeline, "scope_name", None) != func_name:
                # ищем body
                logger.debug(
                        f"[RESOLVE_CALLS]: ищем {func_name=}, "
                        f"{pipeline.scope_name}: {pipeline.symbol_table} "
                )
                target_info = None
                search_scope = pipeline
                while search_scope is not None:
                    symbol_table = getattr(search_scope, "symbol_table", {})
                    if func_name in symbol_table:
                        target_info = symbol_table[func_name]
                        break
                    search_scope = getattr(search_scope, "parent_scope", None)

            if (
                target_info and "body_pipeline" in target_info and 
                target_info["body_pipeline"]
            ):
                logger.debug(
                    f"[RESOLVE_CALLS]: {func_name=}: {target_info=}"
                )
                raw_template_pipeline = target_info["body_pipeline"]
                # __init__, self
                if target_info.get("type") == "class":
                    class_st = getattr(
                        raw_template_pipeline, "symbol_table", {}
                    )
                    if "__init__" in class_st:
                        raw_template_pipeline = (
                            class_st["__init__"]["body_pipeline"]
                        )

                item.meta["call_injected"] = True
                active_call_idx = target_info["node_idx"]

                pipeline.call_counters[func_name] = (
                    pipeline.call_counters.get(func_name, 0) + 1
                )
                call_id = (
                    f"{func_name}_call_{pipeline.call_counters[func_name]}"
                )
                logger.debug(f"[RESOLVE_CALLS]: {call_id=}")

                call_frame = (
                    raw_template_pipeline.isolate(
                        scope_name=call_id,
                        scope_type="call_frame",
                        passed_arguments=call_node.args,
                        parent_scope=pipeline,
                        symbol_table={}
                    )
                    .map(lambda node, call_id=call_id: (
                        node.meta.update({"call_frame": call_id}) or node
                    ))
                    .pipe(DYNAMIC_PASSES).execute()
                )
                call_frame.active_scopes={0: call_frame}
                logger.debug(f"[RESOLVE_CALLS]: {call_frame=}")

                if not hasattr(pipeline, "symbol_table"):
                    pipeline.symbol_table = {}
                pipeline.symbol_table[call_id] = {
                    "type": "call_frame",
                    "node_idx": call_idx,
                    "body_pipeline": call_frame
                }
                # 
                pipeline.inject_from(
                    call_frame,
                    lambda x, trigger_idx=item.meta["idx"]: (
                        trigger_idx != x.meta.get("idx") and
                        trigger_idx not in x.meta.get("preds")
                    ),
                    key=f"inject_{call_id}"
                )
        yield item

def _find_in_scopes(name, pipeline):
    """Служебный LEGB поиск."""
    search_scope = pipeline
    while search_scope is not None:
        st = getattr(search_scope, "symbol_table", {})
        if name in st:
            return st[name]
        search_scope = getattr(search_scope, "parent_scope", None)
    return None

def _get_active_scope(item, pipeline):
    """Определяет актуальный пайплайн на основе метаданных кадра."""
    call_id = item.meta.get("call_frame")
    if call_id and call_id in pipeline.symbol_table:
        return pipeline.symbol_table[call_id]["body_pipeline"]
    return pipeline

def extract_names_path(node):
    if isinstance(node, ast.Name):
        return (node.id,)
    elif isinstance(node, ast.Attribute):
        base_path = extract_names_path(node.value)
        if base_path:
            return base_path + (('.', node.attr),)
    elif isinstance(node, ast.Subscript):
        base_path = extract_names_path(node.value)
        if base_path and isinstance(node.slice, ast.Constant):
            return base_path + (('[]', str(node.slice.value)),)
    return None

def get_targets(nodes):
        elif isinstance(node, (ast.List, ast.Tuple)):
            return [get_targets(elt) for elt in node.elts]
    return [get_targets(node) for node in nodes]

def resolve_operation(current_stream, pipeline)
    for item in current_stream:
        node = item.body
        node_idx = item.meta["idx"]
        def finalize_operation(item, pipeline):
            pass
        if isinstance(node, ast.Operation):
            pipeline.stack[node_idx] = []
            pipeline.trigger_action(
                lambda x, pred_idx: x.preds[-1] == pred_idx,
                finalize_operation,
                key=
            )
        


def resolve_Assign(current_stream, pipeline)
    for item in current_stream:
        node = item.body
        node_idx = item.meta["idx"]
        def finalize_operation(item, pipeline):
            # pipeline.targets = pipeline.values
            pass
        if isinstance(getattr(node, "ctx"), ast.Store):
            # тут вопрос про типы
            pipeline.targets = []
            pipeline.values = []
            pipeline.stack[node_idx] = 
            pipeline.trigger_action(
                lambda x, pred_idx: x.preds[-1] == pred_idx,
                finalize_operation,
                key=
            )
        
def resolve_Store(current_stream, pipeline)
    for item in current_stream:
        node = item.body
        node_idx = item.meta["idx"]
        def finalize_operation(item, pipeline):
            pass
        if isinstance(getattr(node, "ctx"), ast.Store):
            # тут вопрос про типы
            pipeline.stack[node_idx] = []
            pipeline.trigger_action(
                lambda x, pred_idx: x.preds[-1] == pred_idx,
                finalize_operation,
                key=
            )
        

def resolve_stores(current_stream, pipeline):
    """
    Использует принцип Load-Store для наполнения таблиц символов.
    """
    logger = logging.getLogger(f"unbraid.{__name__}.resolve_assigns")
    
    for item in current_stream:
        node = item.body

        if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            pipeline.pending_targets = get_targets(node.targets)
            pipeline.contex_scan("pending_values", func_name, []) 

            # ast.Starred(value)
            # pipeline.targets = resolve_targets(node) либо тоже контекст скан
            # pipeline.context_scan(pending_values, resolve_values, initial)
            # pipeline.triger_action(finalize_condition, finalize_assignment, key)  
            if (isinstance(node, ast.Name)):
                pipeline.symbol_table[node.id] = None
            elif isinstance(node, ast.Attribute):
                if getattr(node.value, "id", None) == "self":
                    target_table = target_scope.symbol_table

            if isinstance(node, ast.Name):
                var_name = node.id
                target_table[var_name] = pipeline.transit_value or {"type": "variable"}
                target_table[var_name]["node_idx"] = item.meta["idx"]
                logger.debug(f"[STORE]: {var_name} <- transit_value")

            # Если это атрибут (self.name = ...)
            elif isinstance(node, ast.Attribute) and getattr(node.value, "id", None) == "self":
                if "instance_attributes" not in target_table:
                    target_table["instance_attributes"] = {}
                
                target_table["instance_attributes"][node.attr] = (
                    pipeline.transit_value or {"type": "object_property"}
                )
                target_table["instance_attributes"][node.attr]["node_idx"] = item.meta["idx"]
                logger.debug(f"[STORE SELF]: {node.attr} <- transit_value")

            # После записи сбрасываем регистр для следующей инструкции
            pipeline.transit_value = None

        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            found_data = _find_in_scopes(node.id, pipeline)
            if found_data:
                # Заряжаем регистр ссылкой на пайплайн или метаданными
                pipeline.transit_value = copy.deepcopy(found_data)
                logger.debug(f"[LOAD]: {node.id} -> transit_value")


        yield item

def extract_assigned_names(target_node):
    """
    Рекурсивно извлекает только плоские имена переменных (ast.Name)
    из левой части присваивания, игнорируя свойства через точку (ast.Attribute).
    """
    import ast
    names = []
    if isinstance(target_node, ast.Name):
        names.append((target_node.id, None))
    elif (
        isinstance(target_node, ast.Attribute) and 
        isinstance(target_node.value, ast.Name)
    ):
        names.append((target_node.attr, target_node.value.id))
    elif isinstance(target_node, (ast.Tuple, ast.List)):
        for elt in target_node.elts:
            names.extend(extract_assigned_names(elt))
    return names

def resolve_assings(current_stream, pipeline):
        # assign -----------------------------------------------------
        if isinstance(item.body, ast.Assign):
            assign_node = item.body
            
            assigned_pairs = []
            for target in assign_node.targets:
                assigned_pairs.extend(extract_assigned_names(target))
                
            right_value = assign_node.value
            
            for name, obj_name in assigned_pairs:

                # self 
                if obj_name == "self":
                    class_scope = None
                    for pred_id in reversed(preds):
                        if pred_id in pipeline.active_scopes:
                            potential_class = pipeline.active_scopes[pred_id]
                            if getattr(
                                potential_class, "scope_type", None
                            ) == "class":
                                class_scope = potential_class
                                break
                    
                    target_scope = (
                        class_scope if class_scope is not None 
                        else current_scope
                    )
                    if "instance_attributes" not in target_scope.symbol_table:
                        target_scope.symbol_table["instance_attributes"] = {}
                    target_scope.symbol_table["instance_attributes"][name] = {
                        "type": "object_property",
                        "node_idx": item.meta["idx"]
                    }
                    
                else:
                    # function alias
                    orig_info = None
                    search_scope = current_scope
                    while search_scope is not None:
                        if (
                            isinstance(right_value, ast.Name) and 
                            right_value.id in search_scope.symbol_table
                        ):
                            orig_info = (
                                search_scope.symbol_table[right_value.id]
                            )
                            break
                        search_scope = getattr(
                            search_scope, "parent_scope", None
                        )

                    if (
                        orig_info and orig_info["type"] in (
                            "function", "method", "imported_name", 
                            "function_alias"
                    )):
                        current_scope.symbol_table[name] = {
                            "type": "function_alias",
                            "node_idx": item.meta["idx"],
                            "body_pipeline": orig_info.get("body_pipeline")
                        }

                    # lambda
                    elif isinstance(right_value, ast.Lambda):
                        current_scope.symbol_table[name] = {
                            "type": "lambda_function",
                            "node_idx": item.meta["idx"]
                        }
                    # variable
                    else:
                        current_scope.symbol_table[name] = {
                            "type": "variable",
                            "node_idx": item.meta["idx"]
                        }
                    

STATIC_PASSES = [
    resolve_scopes,
]
