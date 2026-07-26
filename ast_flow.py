import ast
import copy
from pathlib import Path
from contracts import FlowUnit, FlowExpander, FlowMapper, FlowRouter
import logging
# Используем наш глобальный сквозной логгер проекта
logger = logging.getLogger("unbraid")

# --- ВНУТРЕННИЕ ФАБРИКИ ПОЛЕЙ ---
def _ast_id_factory(module_name: str):
    # raw_pair[1] — это словарь meta, из него забираем короткий числовой idx
    return lambda raw_pair: f"{module_name}.{raw_pair[1]['idx']}"


def _ast_meta_factory():
    # Извлекаем и возвращаем словарь meta, который лежит под индексом 1
    return lambda raw_pair: raw_pair[1]


def _ast_body_extractor():
    # Извлекаем и возвращаем сам сырой узел AST, который лежит под индексом 0
    return lambda raw_pair: raw_pair[0]


def load(file_path, project_root=None):
    """Деструктурирует файл и возвращает готовый настроенный StreamPipeline."""
    path_obj = Path(file_path).resolve()
    module_name = path_obj.stem
    # Если корень не передан, берем родительскую папку текущего файла
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

        raw_items.append((node, meta))

        new_stack = parent_stack + [current_idx]
        for child in ast.iter_child_nodes(node):
            dfs_walk(child, parent_stack=new_stack)

    dfs_walk(tree)

    return raw_items


# --- КЛАСС-РАСШИРИТЕЛЬ MODULE_LOADER ---

class ModuleLoader(FlowExpander):
    """Рекурсивно разворачивает модули, вытаскивая корень из памяти потока."""

    def expand(self, unit: FlowUnit, id_generator, pipeline) -> list[FlowUnit]:
        if unit.meta.get("op_type") != "ImportFrom":
            return []

        module_name = unit.body.module
        # Достаем корень из глобальной памяти потока!
        project_root = Path(pipeline.pipeline_meta["project_root"])
        potential_file = project_root / f"{module_name}.py"

        if potential_file.exists():
            # РЕКУРСИЯ: Загружаем сторонний файл через тот же load!
            ext_pipeline = load(potential_file, project_root=project_root)

            imported_units = []
            for local_unit in ext_pipeline:
                local_unit.id = id_generator()
                imported_units.append(local_unit)

            return imported_units

        return []


class AstRouter(FlowRouter):

    def __init__(self):
        self.functions_map = {}
        self.def_skips = {}
        self.function_ends = set()  # Набор ID, на которых функция заканчивается
        self.ordered_ids = []
        self.initialized = False
        self.call_stack = None

    def initialize(self, pipeline):
        if self.initialized:
            return
        registry = pipeline.pipeline_meta.get("registry_map", {})
        self.ordered_ids = list(registry.keys())
        self.call_stack = pipeline.call_stack

        for uid, u in registry.items():
            if u.meta.get("op_type") in ["FunctionDef", "AsyncFunctionDef"]:
                func_name = u.body.name
                func_idx = u.meta["idx"]

                try:
                    current_pos = self.ordered_ids.index(uid)
                    self.functions_map[func_name] = self.ordered_ids[current_pos + 1]
                except IndexError:
                    pass

                # Вычисляем пропуск тела дефа и фиксируем ПОСЛЕДНИЙ элемент функции
                last_inside_uid = uid
                skip_target_id = None
                for future_uid in self.ordered_ids[current_pos + 1:]:
                    future_u = registry[future_uid]
                    if func_idx in future_u.meta.get("preds", []):
                        last_inside_uid = future_uid  # Запоминаем самый последний атом внутренностей
                    else:
                        skip_target_id = future_uid
                        break
                
                if skip_target_id:
                    self.def_skips[uid] = skip_target_id
                
                # Добавляем последний внутренний атом в набор авто-возврата!
                self.function_ends.add(last_inside_uid)

        self.initialized = True

    def get_next_id(self, unit: FlowUnit) -> Any:
        try:
            current_pos = self.ordered_ids.index(unit.id)
            if current_pos + 1 < len(self.ordered_ids):
                return self.ordered_ids[current_pos + 1]
        except ValueError:
            pass
        return None

    def get_jump_id(self, unit: FlowUnit) -> Any:
        import ast
        if unit.meta.get("op_type") in ["FunctionDef", "AsyncFunctionDef"]:
            return self.def_skips.get(unit.id)

        if unit.meta.get("op_type") == "Call" and isinstance(unit.body.func, ast.Name):
            func_name = unit.body.func.id
            if func_name not in ["print", "asyncio", "sleep"]:
                return self.functions_map.get(func_name)
        return None

    def is_return(self, unit: FlowUnit) -> bool:
        # Условие 1: Встретили явный Return в коде
        if unit.meta.get("op_type") == "Return" and self.call_stack:
            return True
            
        # Условие 2: АВТО-RETURN. Если мы пришли сюда по прыжку (стек не пуст)
        # и выполнили САМЫЙ ПОСЛЕДНИЙ атом этой функции — принудительно возвращаемся!
        if unit.id in self.function_ends and self.call_stack:
            return True
            
        return False


import ast
from typing import Any
from contracts import FlowRouter, FlowUnit


class AstCoordinateRouter(FlowRouter):
    """Координатный роутер: управляет прыжками по сетке (модуль, id) [Example 4]."""

    def __init__(self):
        # Глобальная карта проекта: { "имя_функции": ("имя_модуля", "id_строки") }
        self.functions_map = {}
        # Карта пропусков дефов внутри модулей: { "id_дефа": "id_строки_после" }
        self.def_skips = {}
        # Набор граничных ID, где функция физически заканчивается
        self.function_ends = set()
        self.initialized = False

    def initialize(self, system) -> None:
        """Сканирует все изолированные модули системы и строит карту адресов."""
        if self.initialized:
            return

        # Перебираем каждый зарегистрированный в UnitedStreamSystem модуль
        for mod_name, registry in system.streams.items():
            ordered_ids = list(registry.keys())

            for pos, uid in enumerate(ordered_ids):
                unit = registry[uid]
                op = unit.meta.get("op_type")

                if op in ["FunctionDef", "AsyncFunctionDef"]:
                    func_name = unit.body.name
                    func_idx = unit.meta["idx"]

                    # Точка входа в тело функции — следующий элемент в её модуле
                    if pos + 1 < len(ordered_ids):
                        self.functions_map[func_name] = (mod_name, ordered_ids[pos + 1])

                    # Ищем, где функция заканчивается, и куда её перепрыгнуть (def_skip)
                    last_inside_uid = uid
                    skip_target_id = None
                    for future_uid in ordered_ids[pos + 1:]:
                        future_u = registry[future_uid]
                        if func_idx in future_u.meta.get("preds", []):
                            last_inside_uid = future_uid
                        else:
                            skip_target_id = future_uid
                            break

                    if skip_target_id:
                        # Запоминаем локальный пропуск внутри этого же модуля
                        self.def_skips[uid] = skip_target_id
                    
                    # Фиксируем координатную точку авто-возврата
                    self.function_ends.add((mod_name, last_inside_uid))

        self.initialized = True

    def get_next_id(self, unit: FlowUnit, current_registry: dict) -> Any:
        """Линейный ход строго по ключам текущего активного модуля."""
        ordered_ids = list(current_registry.keys())
        try:
            current_pos = ordered_ids.index(unit.id)
            if current_pos + 1 < len(ordered_ids):
                return ordered_ids[current_pos + 1]
        except ValueError:
            pass
        return None

    def get_jump_coordinates(self, unit: FlowUnit, system) -> Any:
        """Вычисляет двумерный прыжок (имя_модуля, id_строки) [Example 4]."""
        op = unit.meta.get("op_type")
        mod_name = unit.meta["module"]

        # Ситуация А: Наступили на объявление 'def' -> перепрыгиваем его локально
        if op in ["FunctionDef", "AsyncFunctionDef"]:
            skip_id = self.def_skips.get(unit.id)
            if skip_id:
                return (mod_name, skip_id)

        # Ситуация Б: Реальный вызов Call -> делаем межмодульный прыжок!
        if op == "Call" and isinstance(unit.body.func, ast.Name):
            func_name = unit.body.func.id
            if func_name not in ["print", "asyncio", "sleep"]:
                # Запрашиваем из карты проекта точные координаты целевой функции
                return self.functions_map.get(func_name)
                
        return None

    def is_return(self, unit: FlowUnit, system) -> bool:
        """Проверяет координатную точку возврата по стеку системы."""
        op = unit.meta.get("op_type")
        mod_name = unit.meta["module"]

        # Если в стеке UnitedStreamSystem пусто, возвращаться некуда
        if not system.coordinate_stack:
            return False

        # Явный Return или физический конец тела функции
        if op == "Return" or (mod_name, unit.id) in self.function_ends:
            return True

        return False


import ast
import builtins
from contracts import FlowMapper


class FlowScopeTracker(FlowMapper):
    """Отслеживает области видимости по правилам модулей Python (__main__).

    Сохраняет имена переменных, функций и изолирует глобальные пространства.
    """

    def __init__(self):
        # Реестр глобальных пространств модулей: { "main_test": {}, "data_processor": {} }
        self.module_globals = {}
        # Динамический стек локальных сред для вызовов функций
        self.local_scopes_stack = []

    def __call__(self, unit: FlowUnit) -> None:
        import ast
        op = unit.meta["op_type"]
        mod_name = unit.meta["module"]

        # Инициализируем глобальное пространство модуля, если его еще нет в реестре
        if mod_name not in self.module_globals:
            self.module_globals[mod_name] = {}

        current_global = self.module_globals[mod_name]

        # ШАГ 1: ВХОД В ФУНКЦИЮ (Открываем локальный карман памяти)
        if op in ["FunctionDef", "AsyncFunctionDef"]:
            self.local_scopes_stack.append({})
            
            # РЕГИСТРАЦИЯ ИМЕНИ ФУНКЦИИ: По правилам Python имя функции 
            # ложится в текущий активный слой (локальный или глобальный)
            func_name = unit.body.name
            func_expr = f"<function {func_name}>"
            if len(self.local_scopes_stack) > 1:
                # Если деф вложен в другую функцию
                self.local_scopes_stack[-2][func_name] = func_expr
            else:
                current_global[func_name] = func_expr

        # ШАГ 2: РЕГИСТРАЦИЯ КЛАССОВ
        if op == "ClassDef":
            class_name = unit.body.name
            class_expr = f"<class {class_name}>"
            if self.local_scopes_stack:
                self.local_scopes_stack[-1][class_name] = class_expr
            else:
                current_global[class_name] = class_expr

        logger.info(f"[SCOPE]: {current_global=}") 
        logger.info(f"[SCOPE]: {self.local_scopes_stack=}") 

        # ШАГ 3: ФИКСАЦИЯ ПЕРЕМЕННЫХ И АТРИБУТОВ (Assign)
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

        # ШАГ 4: ФОРМИРОВАНИЕ СРЕЗА ЖИВОЙ ПАМЯТИ (LEGB)
        # Наливаем глобальные переменные и функции ИМЕННО ЭТОГО модуля
        available_now = {k: v for k, v in current_global.items()}
        
        # Накладываем сверху стек локальных сред активных вызовов
        for scope in self.local_scopes_stack:
            for k, v in scope.items():
                available_now[k] = v

        unit.meta["live_variables"] = available_now

        # ШАГ 5: ВЫХОД ИЗ ФУНКЦИИ (Уничтожение локального контекста)
        if op == "Return":
            if self.local_scopes_stack:
                self.local_scopes_stack.pop()



class VariableTracker(FlowMapper):
    """Шаг 2: Отслеживает зависимости переменных и чистит память уровней."""

    def __init__(self):
        self.live_memory = {}  # { "абсолютное_имя": {"expr": "25", "deps": []} }

    def __call__(self, unit: FlowUnit) -> None:
        import ast
        curr_space = unit.meta.get("space_path", "main_test")
        op = unit.meta["op_type"]

        # ЛОГГЕР 3: Трассируем каждую строчку (какой узел на каком контексте выполняется)
        code_str = ast.unparse(unit.body) if unit.body else ""
        clean_code = " ".join(code_str.split())[:30]
        logger.info(f"[TRACKER] Op: {op:<15} | Ctx: {curr_space:<30} | Code: {clean_code}")


        # 1. СБОР ЗАВИСИМОСТЕЙ: Интересует только узел Assign (запись данных)
        right_vars = []
        if op == "Assign":
            # Ищем переменные, которые используются в правой части (value)
            for child in ast.walk(unit.body.value):
                if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
                    # Проверяем локальную память текущего пространства
                    local_name = f"{curr_space}.{child.id}"
                    if local_name in self.live_memory:
                        right_vars.append(local_name)
                    else:
                        # Если локально нет, ищем на глобальном уровне модуля
                        global_name = f"{curr_space.split('.')[0]}.{child.id}"
                        if global_name in self.live_memory:
                            right_vars.append(global_name)

            # Регистрируем новые переменные в живую память
            for target in unit.body.targets:
                for name_node in ast.walk(target):
                    if isinstance(name_node, ast.Name):
                        abs_name = f"{curr_space}.{name_node.id}"
                        self.live_memory[abs_name] = {
                            "expr": ast.unparse(unit.body.value),
                            "deps": list(right_vars)
                        }

        unit.meta["data_dependencies"] = right_vars

        # 2. ОЧИСТКА ПАМЯТИ: Если встретили Return, удаляем локальные переменные
        if op == "Return":
            # Вычищаем из памяти вообще все переменные, которые начинаются с текущего пространства
            prefix = f"{curr_space}."
            keys_to_delete = [k for k in self.live_memory.keys() if k.startswith(prefix)]
            for k in keys_to_delete:
                del self.live_memory[k]

        # 3. (*) Записываем снимок только тех переменных, которые ЖИВЫ прямо сейчас
        unit.meta["live_variables"] = {k: v["expr"] for k, v in self.live_memory.items()}

