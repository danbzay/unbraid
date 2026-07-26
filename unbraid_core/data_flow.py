# unbraid_core/data_flow.py
import ast

class DataFlowTracker:
    def __init__(self):
        self.registry = []
        self._next_var_id = 1
        self._next_flow_id = 1
        
        # Стек областей видимости
        self.scope_stack = [{}]
        # Стек контекстов ветвлений (чтобы if-блоки знали, от чего они зависят)
        self.if_context_stack = []

    def enter_scope(self):
        self.scope_stack.append({})

    def exit_scope(self):
        if len(self.scope_stack) > 1:
            self.scope_stack.pop()

    def enter_if(self, dependencies):
        """Запоминаем, что текущий блок кода зависит, например, от переменной age"""
        self.if_context_stack.append(dependencies)

    def exit_if(self):
        if self.if_context_stack:
            self.if_context_stack.pop()

    @property
    def current_scope(self):
        return self.scope_stack[-1]

    def lookup_variable(self, name):
        for scope in reversed(self.scope_stack):
            if name in scope:
                return scope[name]
        return None

    def register_variable(self, name, address, dependencies=None, force_flow_id=None):
        dependencies = dependencies or []
        
        # Если мы находимся внутри IF, переменная автоматически зависит от условия этого IF
        if self.if_context_stack:
            for if_deps in self.if_context_stack:
                dependencies.extend(if_deps)
            dependencies = list(set(dependencies)) # Убираем дубликаты

        var_id = self._next_var_id
        self._next_var_id += 1

        # Определение ID потока (flow_id)
        if force_flow_id is not None:
            flow_id = force_flow_id
        elif dependencies:
            # Наследуем поток первой главной зависимости (например, status наследует поток от age)
            parent_var = self.lookup_variable(dependencies[0])
            flow_id = parent_var["flow_id"] if parent_var else self._next_flow_id
        else:
            flow_id = self._next_flow_id
            self._next_flow_id += 1

        # Собираем ID зависимостей для вывода
        dep_ids = []
        for dep_name in dependencies:
            dep_var = self.lookup_variable(dep_name)
            if dep_var:
                dep_ids.append(str(dep_var["var_id"]))

        record = {
            "var_id": var_id,
            "flow_id": flow_id,
            "name": name,
            "dependencies": ", ".join(dep_ids) if dep_ids else "-",
            "path": address,
            "format": "Unknown"
        }

        self.current_scope[name] = record
        self.registry.append(record)
        return record

    def extract_dependencies(self, expr_node):
        deps = []
        if expr_node is None:
            return deps
        for child in ast.walk(expr_node):
            if isinstance(child, ast.Name):
                deps.append(child.id)
        return list(set(deps))

