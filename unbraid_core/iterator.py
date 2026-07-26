# unbraid_core/iterator.py
import ast
import os

class SimplifiedFlowIterator:
    def __init__(
        self, node, file_name: str, strategy, file_registry: dict, 
        current_path="Module", state=None
    ):
        self.node = node
        self.file_name = os.path.normpath(file_name)
        self.strategy = strategy
        self.file_registry = file_registry
        self.current_path = current_path
        # Состояние теперь передается по ссылке внутри одного уровня, 
        # чтобы переменные накапливались
        self.state = state if state is not None else {}

        if isinstance(node, ast.Module):
            self._load_imports(node.body)

    def _load_imports(self, body_nodes):
        for stmt in body_nodes:
            if isinstance(stmt, ast.Import):
                for alias in stmt.names:
                    self.state[
                        alias.asname if alias.asname else alias.name
                    ] = f"ext://{alias.name}"
            elif isinstance(stmt, ast.ImportFrom):
                module = stmt.module if stmt.module else ""
                possible_paths = [
                    os.path.normpath(f"{module}.py"), 
                    os.path.normpath(f"tests/{module}.py")
                ]
                target_file = possible_paths[0]
                for p in possible_paths:
                    if p in self.file_registry:
                        target_file = p
                        break
                for alias in stmt.names:
                    self.state[
                        alias.asname if alias.asname else alias.name
                    ] = f"{target_file}#{alias.name}"

    def __iter__(self):
        lineno = getattr(self.node, 'lineno', 0)
        col = getattr(self.node, 'col_offset', 0)
        cls_name = self.node.__class__.__name__
        address = f"{self.file_name} Rhine@{lineno}:{col}#{self.current_path}"
                  f"({cls_name})"

        # Запись переменной происходит в ОРИГИНАЛЬНЫЙ словарь текущего уровня
        if cls_name == "Assign":
            for target in self.node.targets:
                if isinstance(target, ast.Name):
                    self.state[target.id] = address

        # Проверяем ТЕЛЕПОРТАЦИЮ (Прыжок) строго на узле Call
        if cls_name == "Call" and isinstance(self.node.func, ast.Name):
            func_name = self.node.func.id
            target_address = self.state.get(func_name)
            
            if target_address and "#" in target_address:
                import_file, real_func_name = target_address.split("#")
                import_file = os.path.normpath(import_file)

                if import_file in self.file_registry:
                    target_tree = self.file_registry[import_file]
                    
                    for child in ast.walk(target_tree):
                        if isinstance(
                            child, (ast.FunctionDef, ast.AsyncFunctionDef)
                        ) and child.name == real_func_name:
                            # 1. Готовим чистое изолированное пространство для
                            # функции (только внешние библиотеки)
                            child_state = {
                                k: v for k, v in self.state.items() 
                                if v.startswith("ext://")
                            }
                            
                            # СВЯЗЫВАНИЕ АРГУМЕНТОВ (Ваш вопрос):
                            # Берем переданные в Call узлы и сопоставляем их 
                            # с именами аргументов в FunctionDef
                            for idx, param in enumerate(child.args.args):
                                if idx < len(self.node.args):
                                    arg_node = self.node.args[idx]
                                    if isinstance(arg_node, ast.Name):
                                        # Вытаскиваем адрес переменной, которая
                                        # была передана как аргумент!
                                        source_address = self.state.get(
                                            arg_node.id, 
                                            f"unknown_source_for_{arg_node.id}"
                                        )
                                        child_state[param.arg] = source_address
                                    else:
                                        # Если передали константу типа "строка"
                                        # или 25
                                        child_state[param.arg] = (
                                            f"constant_value_at_{address}"
                                        )

                            # Сначала выдаем сам узел Call
                            yield (self.node, address, dict(self.state))

                            # 2. Уходим в прыжок по телу функции
                            # (передаем список инструкций child.body)
                            jump_iterator = SimplifiedFlowIterator(
                                node=child, # Передаем саму функцию как 
                                            # родителя для путей
                                file_name=import_file,
                                strategy=self.strategy,
                                file_registry=self.file_registry,
                                current_path=(
                                    f"{self.current_path}.Jump({func_name})"
                                ),
                                state=child_state
                            )
                            # Запускаем последовательный обход тела функции
                            yield from jump_iterator._process_list(
                                child.body, 
                                f"{self.current_path}.Jump({func_name}).body"
                            )
                            return

        # Стандартный обход шагов стратегии
        custom_steps = self.strategy.get_next_steps(self.node)

        if custom_steps is not None:
            for label, child in custom_steps:
                if label == "self":
                    yield (child, address, dict(self.state))
                else:
                    yield from self._process_child(
                        child, f"{self.current_path}.{label}"
                    )
        else:
            yield (self.node, address, dict(self.state))
            for field, value in ast.iter_fields(self.node):
                yield from self._process_child(
                    value, f"{self.current_path}.{field}"
                )

    def _process_list(self, body_list, path_prefix):
        """ Специальный метод для последовательного (line-by-line) 
            выполнения списка инструкций """
        for idx, stmt in enumerate(body_list):
            # Передаем ОДИН И ТОТ ЖЕ словарь self.state от строчки к строчке,
            # чтобы переменные копились!
            iterator = SimplifiedFlowIterator(
                stmt, self.file_name, self.strategy, self.file_registry, 
                f"{path_prefix}[{idx}]", self.state
            )
            yield from iterator

    def _process_child(self, child, child_path):
        if isinstance(child, list):
            yield from self._process_list(child, child_path)
        elif isinstance(child, ast.AST):
            # Для внутренних под-выражений (типа правой части Assign) 
            # используем текущий state
            yield from SimplifiedFlowIterator(
                child, self.file_name, self.strategy, self.file_registry, 
                child_path, self.state
            )

