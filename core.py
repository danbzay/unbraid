import sys
import os
import inspect
import ast
from db import UnbraidDB

def extract_dependencies(code_line: str) -> tuple[str | None, list[str]]:
    """Разбирает строку кода на цель и зависимости."""
    try:
        tree = ast.parse(code_line.strip())
    except SyntaxError:
        return None, []

    if not tree.body:
        return None, []
    
    node = tree.body[0]
    
    if isinstance(node, ast.Assign):
        target = node.targets[0].id if isinstance(node.targets[0], ast.Name) else None
        predecessors = [n.id for n in ast.walk(node.value) if isinstance(n, ast.Name)]
        return target, predecessors
    elif isinstance(node, ast.If):
        condition_vars = [n.id for n in ast.walk(node.test) if isinstance(n, ast.Name)]
        return "IF_CONDITION", condition_vars
    return None, []

class UnbraidTracker:
    def __init__(self, db_path="data_flow.db"):
        self.db = UnbraidDB(db_path)
        self.call_stack = []
        self.project_dir = ""

    def _get_current_context(self) -> str:
        return ":".join(self.call_stack) if self.call_stack else "global"

    def profile_callback(self, frame, event, arg):
        """Этот коллбек вызывается при входе и выходе из функций."""
        filename = frame.f_code.co_filename
        
        # Отсекаем системные файлы, смотрим только на папку тестов
        if self.project_dir not in filename or "unbraid" in filename:
            return

        func_name = frame.f_code.co_name
        current_context = self._get_current_context()

        # 1. ЗАШЛИ В ФУНКЦИЮ: Логируем её аргументы как начальные узлы данных
        if event == "call":
            self.call_stack.append(func_name)
            new_context = self._get_current_context()
            
            # Читаем локальные переменные на старте функции — это её аргументы!
            for var_name, var_val in frame.f_locals.items():
                if var_name.startswith('_'): continue
                
                # Ищем, откуда этот аргумент мог прийти из родительского контекста
                last_id = self.db.find_last_node_id(var_name, current_context)
                preds = [last_id] if last_id else []
                
                self.db.insert_node(
                    stream_id=0,
                    var_name=var_name,
                    predecessors=preds,
                    control_dependencies=[],
                    context=new_context,
                    notes=f"Argument initialized: {var_name}"
                )

        # 2. ВЫШЛИ ИЗ ФУНКЦИИ
        elif event == "return":
            # Фиксируем, что функция что-то вернула
            if self.call_stack:
                self.db.insert_node(
                    stream_id=0,
                    var_name=f"{func_name}_result",
                    predecessors=[],
                    control_dependencies=[],
                    context=current_context,
                    notes=f"Function {func_name} returned data"
                )
                self.call_stack.pop()

    def start_trace(self, project_dir):
        self.project_dir = os.path.abspath(project_dir)
        self.db.connect()
        # Включаем профилирование вместо трассировки
        sys.setprofile(self.profile_callback)

    def stop_trace(self):
        sys.setprofile(None)
        self.db.close()

