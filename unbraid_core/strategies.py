# unbraid_core/strategies.py
import ast

class SimplifiedFlowStrategy:
    @staticmethod
    def get_next_steps(node):
        # Пропускаем внутренности объявлений функций! Зайдём туда только по вызову.
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return [("self", node)]

        if isinstance(node, ast.Assign):
            return [
                ("value", node.value),
                ("targets", node.targets),
                ("self", node)
            ]
            
        elif isinstance(node, ast.Call):
            return [
                ("func_name", node.func),
                ("arguments", node.args),
                ("self", node)
            ]

        elif isinstance(node, ast.Await):
            return [
                ("await_value", node.value),
                ("self", node)
            ]

        elif isinstance(node, ast.If):
            return [
                ("test", node.test),
                ("if_body", node.body), 
                ("else_body", node.orelse),
                ("self", node)
            ]

        return None

