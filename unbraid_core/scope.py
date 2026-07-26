# unbraid_core/scope.py
import ast
import os

class Scope:
    def __init__(self, parent=None):
        self.parent = parent
        self.symbols = {}  # { "имя": "глобальный_адрес_источника" }

    def set(self, name: str, address: str):
        self.symbols[name] = address

    def lookup(self, name: str) -> str:
        if name in self.symbols:
            return self.symbols[name]
        if self.parent:
            return self.parent.lookup(name)
        return None

    def load_imports(self, body_nodes, current_file_path: str):
        """Парсит импорты относительно папки текущего файла"""
        current_dir = os.path.dirname(current_file_path)

        for stmt in body_nodes:
            if isinstance(stmt, ast.Import):
                for alias in stmt.names:
                    local_name = alias.asname if alias.asname else alias.name
                    self.set(local_name, f"ext://{alias.name}")
            
            elif isinstance(stmt, ast.ImportFrom):
                module = stmt.module if stmt.module else ""
                
                # Нормализуем путь к модулю относительно текущей директории файла
                module_path = module.replace(".", "/") + ".py"
                target_file = os.path.normpath(os.path.join(current_dir, module_path))
                
                for alias in stmt.names:
                    local_name = alias.asname if alias.asname else alias.name
                    address = f"{target_file}#{alias.name}"
                    self.set(local_name, address)

    def load_assign(self, assign_node, address: str):
        """Регистрирует переменные, которые возникают при присваивании"""
        for target in assign_node.targets:
            if isinstance(target, ast.Name):
                self.set(target.id, address)

    def get_all_visible(self):
        all_syms = {}
        if self.parent:
            all_syms.update(self.parent.get_all_visible())
        all_syms.update(self.symbols)
        return list(all_syms.items())

