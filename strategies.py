import ast
import copy
import pprint
import ast
import copy
import logging
logger = logging.getLogger("unbraid")


def add_parents(tree):
    """Связывает узлы дерева, прописывая каждому ссылку на родителя."""
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            child.parent = parent


def get_absolute_space(node, module_name):
    """Поднимается по родителям и строит точный путь пространства имён."""
    space_parts = []
    current = getattr(node, "parent", None)

    while current is not None:
        if isinstance(
            current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            # Извлекаем чистое имя функции/класса, отсекая старые префиксы
            clean_name = current.name.split(".")[-1]
            space_parts.insert(0, clean_name)
        current = getattr(current, "parent", None)

    space_parts.insert(0, module_name)
    return ".".join(space_parts)

class FileNormalizer(ast.NodeTransformer):
    """Привязывает честное пространство имён к атрибутам узлов, не меняя код."""

    def __init__(self, module_name):
        self.module_name = module_name

    def visit_Name(self, node):
        # Вычисляем пространство через предков (например, 'main_test.main')
        space = get_absolute_space(node, self.module_name)
        # Записываем строго в атрибут узла!
        node.unbraid_space = space
        return node

    def visit_FunctionDef(self, node):
        space = get_absolute_space(node, self.module_name)
        node.unbraid_space = space
        self.generic_visit(node)
        return node

    def visit_AsyncFunctionDef(self, node):
        space = get_absolute_space(node, self.module_name)
        node.unbraid_space = space
        self.generic_visit(node)
        return node

    def visit_ClassDef(self, node):
        """Ловит класс и заменяет self на имя класса в его теле."""
        # Вычисляем чистое имя класса (например, 'C')
        class_name = node.name.split(".")[-1]

        class ClassSelfReplacer(ast.NodeTransformer):
            def visit_Name(self, n):
                # Если встретили self — превращаем его в имя класса
                if n.id == "self":
                    return ast.copy_location(
                        ast.Name(id=class_name, ctx=n.ctx), n
                    )
                return n

        # Прогоняем тело класса через реплейсер до общей нормализации
        ClassSelfReplacer().visit(node)
        
        # Дальше запускаем стандартный обход для прописки unbraid_space
        space = get_absolute_space(node, self.module_name)
        node.name = f"{space}.{class_name}"
        self.generic_visit(node)
        return node


class ProjectRegistry:

    def __init__(self):
        # Плоский реестр всех найденных переменных и их метаданных
        self.variables = {}
        # Сюда собираются плоские инструкции
        self.flat_body = []
        # Текущее пространство в виде стека: ['main_test'] -> ['main_test', 'main']
        self.current_space = ["main_test"]
        self.functions_pool = {}
        self.symbols = {}


    def get_space_string(self):
        """Возвращает текущее пространство в виде строки через точку."""
        return ".".join(self.current_space)

    def register_variable(self, stmt_node):
        """Регистрирует переменные, используя атрибуты unbraid_space узлов."""
        # Собираем найденные метаданные (пространство и имя)
        found_items = []

        if isinstance(
            stmt_node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            space = getattr(stmt_node, "unbraid_space", "main_test")
            found_items.append((space, stmt_node.name))

        elif isinstance(stmt_node, ast.Assign):
            for target in stmt_node.targets:
                for child in ast.walk(target):
                    # Случай А: Обычное имя (x = 1)
                    if isinstance(child, ast.Name):
                        space = getattr(child, "unbraid_space", "main_test")
                        found_items.append((space, child.id))
                        
                    # Случай Б: Свойство класса или объекта (C.x = 2)
                    elif isinstance(child, ast.Attribute):
                        space = getattr(child, "unbraid_space", "main_test")
                        
                        # Собираем красивую строку свойства: 'C.x'
                        if isinstance(child.value, ast.Name):
                            obj_name = child.value.id
                            attr_identity = f"{obj_name}.{child.attr}"
                            found_items.append((space, attr_identity))

            # Логика копирования ярлыков функций f = process_user_data
            if len(found_items) == 1 and isinstance(stmt_node.value, ast.Name):
                space, var_name = found_items[0]
                right_name = stmt_node.value.id
                
                # Ищем оригинальный узел функции в реестре 
                # по корзине пространства
                right_key = (space, right_name)
                if right_key not in self.variables:
                    # Если локально нет, проверяем корень файла
                    right_key = (self.current_space[0], right_name)

                if right_key in self.variables:
                    func_meta = copy.deepcopy(self.variables[right_key])
                    func_meta["name"] = var_name
                    self.variables[(space, var_name)] = func_meta
                    return

        # Записываем элементы в плоский словарь по ключу-кортежу (space, name)
        for space, name in found_items:
            self.variables[(space, name)] = {
                "name": name,
                "space": space,
                "node": stmt_node,
                "call_count": 0
            }
            logger.debug(f"[REGISTERED]: {space}, {name}")


class LinearFlowCompiler:

    def __init__(self, registry, target_file):
        self.registry = registry
        self.project_root = target_file.parent
        self._load_module_on_import(target_file.stem)

    def _load_module_on_import(self, module_name, names=[]):
        """Находит файл импорта, регистрирует и создаёт ярлыки-алиасы."""
        potential_file = self.project_root / f"{module_name}.py"
        
        if potential_file.exists():
            with open(potential_file, "r", encoding="utf-8") as f:
                ext_tree = ast.parse(f.read())
            
            old_space = copy.deepcopy(self.registry.current_space)
            self.registry.current_space = [module_name]
            
            self.process_block(ext_tree.body)
            
            self.registry.current_space = old_space
            
            for alias in names:
                orig_key = (module_name, alias.name)
                
                if orig_key in self.registry.variables:
                    local_name = alias.asname if alias.asname else alias.name
                    
                    func_meta = copy.deepcopy(self.registry.variables[orig_key])
                    func_meta["name"] = local_name
                    func_meta["space"] = old_space
                    
                    new_key = (old_space, local_name)
                    self.registry.variables[new_key] = func_meta
                    
                    logger.debug(f"[ALIAS]: {new_key}")
            

    def _find_registered_call(self, stmt_node):
        """Ищет Call на основе ключей-кортежей (space, name) в реестре."""
        ignored_nodes = (ast.List, ast.Dict, ast.Subscript)
        ignored_fields = {"body", "orelse", "finalbody", "handlers"}
        
        queue = [stmt_node]
        while queue:
            current = queue.pop(0)
            
            if isinstance(current, ast.Call) and isinstance(current.func, ast.Name):
                func_name = current.func.id
                
                # Достаем текущее пространство (например, 'main_test.main' или 'main_test')
                current_space = self.registry.get_space_string()
                
                # 1. Проверяем локальный ключ в реестре
                local_key = (current_space, func_name)
                logger.debug(f"[LOCAL_KEY]: {local_key}")
                # 2. Проверяем глобальный ключ файла (первый элемент стека пространства)
                global_key = (self.registry.current_space[0], func_name)
                
                # Выбираем правильный ключ из реестра
                target_key = None
                if local_key in self.registry.variables:
                    target_key = local_key
                elif global_key in self.registry.variables:
                    target_key = global_key
                    
                if target_key:
                    # Привязываем метаданные прямо к узлу вызова!
                    current.unbraid_meta = self.registry.variables[target_key]
                    return current
                    
            if isinstance(current, ignored_nodes):
                continue
                
            for field, value in ast.iter_fields(current):
                if field in ignored_fields:
                    continue
                if isinstance(value, ast.AST):
                    queue.append(value)
                elif isinstance(value, list):
                    for item in value:
                        if isinstance(item, ast.AST):
                            queue.append(item)
        return None


    def process_block(self, body_list):
        idx = 0
        counter = 0

        logger.debug(
            f"[PROCESS_BLOCK]:---------"
            f"space:{self.registry.get_space_string()}-----------"
        )

        while idx < len(body_list) and counter < 20:
            counter += 1
            stmt = body_list[idx]
            logger.debug(f"[STMT]:{ast.dump(stmt)}, {counter=}")

            # Import
            if isinstance(stmt, ast.ImportFrom):
                logger.debug(f"[IMPORT_FROM]: {stmt.module}")
                self._load_module_on_import(stmt.module, stmt.names)
                idx += 1
                continue

            # Register names
            if isinstance(stmt, (
                ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
                ast.Assign )
            ):
                self.registry.register_variable(stmt)

            # Call 
            target_call = self._find_registered_call(stmt)

            if target_call:
                func_meta = target_call.unbraid_meta
                func_def = func_meta["node"]
                func_space = func_meta["space"]
                func_name = func_meta["name"]
                logger.debug(f"[TARGET_CALL]: {target_call}")

                # Увеличиваем счетчик вызовов индивидуально для этой функции
                func_meta["call_count"] = func_meta.get("call_count", 0) + 1
                call_id = func_meta["call_count"]
                
                # Создаем изолированное точечное пространство для этого вызова
                call_prefix = f"{func_space}.{func_name}.{call_id}"
                
                # Чистое имя переменной результата (без точек!)
                tmp_res_name = f"_unbraid_res_{func_name}_{call_id:03d}"
                
                inserted_stmts = []

                # 1. Присвоение аргументов параметрам функции
                for param, arg in zip(func_def.args.args, target_call.args):
                    param_node = ast.Name(id=param.arg, ctx=ast.Store())
                    # Привязываем уникальное пространство вызова в атрибут!
                    param_node.unbraid_space = call_prefix
                    
                    arg_assign = ast.Assign(
                        targets=[param_node],
                        value=copy.deepcopy(arg)
                    )
                    ast.copy_location(arg_assign, target_call)
                    inserted_stmts.append(arg_assign)

                # 2. Переносим тело функции, прописывая call_prefix в атрибуты имен
                class AttrSpaceMangler(ast.NodeTransformer):
                    def visit_Name(self, n):
                        system_names = ["print", "asyncio", "sys", "os", "len", "range"]
                        if n.id not in system_names and not n.id.startswith("_unbraid"):
                            # Прописываем строго в атрибут узла, имя не трогаем
                            n.unbraid_space = call_prefix
                        return n

                mangler = AttrSpaceMangler()

                for f_stmt in func_def.body:
                    cloned_f_stmt = copy.deepcopy(f_stmt)
                    mangler.visit(cloned_f_stmt)

                    # 3. Присвоение значения Return во временную переменную результата
                    if isinstance(cloned_f_stmt, ast.Return):
                        res_target = ast.Name(id=tmp_res_name, ctx=ast.Store())
                        # Переменная результата лежит в текущем родительском пространстве
                        res_target.unbraid_space = self.registry.get_space_string()
                        
                        return_assign = ast.Assign(
                            targets=[res_target],
                            value=cloned_f_stmt.value if cloned_f_stmt.value else ast.Constant(value=None)
                        )
                        ast.copy_location(return_assign, target_call)
                        inserted_stmts.append(return_assign)
                    else:
                        ast.copy_location(cloned_f_stmt, target_call)
                        inserted_stmts.append(cloned_f_stmt)

                class CallReplacer(ast.NodeTransformer):
                    def visit_Call(self, c_node):
                        # Сначала рекурсивно обрабатываем вложенные аргументы
                        self.generic_visit(c_node)
                        
                        if isinstance(c_node.func, ast.Name):
                            # Сравниваем чистое имя функции (например, 'main')
                            # с именем оригинальной функции из реестра
                            if c_node.func.id == func_def.name:
                                repl_node = ast.Name(
                                    id=tmp_res_name, ctx=ast.Load()
                                )
                                # Передаем пространство вызывающей стороны
                                repl_node.unbraid_space = func_meta["space"]
                                return ast.copy_location(repl_node, c_node)
                        return c_node

                modified_stmt = copy.deepcopy(stmt)
                CallReplacer().visit(modified_stmt)
                inserted_stmts.append(modified_stmt)

                logger.debug(f"[INSERT STMTS]:{inserted_stmts}")
                body_list[idx:idx+1] = inserted_stmts
                continue

            # обрабатываем ветки с со встроенными списками
            if isinstance(stmt, (ast.If, ast.For, ast.While)):
                self.process_block(stmt.body)
                self.process_block(stmt.orelse)

            elif isinstance(stmt, ast.Try):
                self.process_block(stmt.body)
                self.process_block(stmt.finalbody)
                for handler in stmt.handlers:
                    self.process_block(handler.body)

            elif not isinstance(stmt, (
                ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef
            )):
                self.registry.flat_body.append(copy.deepcopy(stmt))

            idx += 1
            

def run_flat_strategy(target_file):
    registry = ProjectRegistry()
    compiler = LinearFlowCompiler(registry, target_file)

    flat_ast = ast.Module(body=registry.flat_body, type_comments=[])
    flat_code = ast.unparse(flat_ast)
    logger.debug(f"[BODY]: {ast.dump(flat_ast, indent=4)}")
    logger.debug(f"[VARIABLES]: {registry.variables.keys()}")
    
    return {
        "status": "success",
        "mode": "flat",
        "flat_code": flat_code.split("\n"),
        "flat_body": registry.flat_body
    }

