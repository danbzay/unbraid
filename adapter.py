import ast
from contracts import FlowUnit


class PythonASTAdapter:
    """Адаптер: упаковывает плоские узлы Python AST в абстрактные FlowUnit."""

    def __init__(self, flat_ast_body, module_name="main_test"):
        self.flat_body = flat_ast_body
        self.module_name = module_name

    def get_units(self):
        """Лениво генерирует FlowUnit для каждого узла AST."""
        for idx, stmt in enumerate(self.flat_body):
            # Извлекаем метаданные пространства имён, привязанные к атрибутам
            space = getattr(stmt, "unbraid_space", self.module_name)
            if isinstance(space, list):
                space = ".".join(space)

            # Собираем уникальный составной ID (имя_модуля.номер_строки)
            unit_id = f"{self.module_name}.{idx:03d}"

            # Формируем изолированный мешок метаданных
            meta_data = {
                "space": space,
                "op_type": type(stmt).__name__,
                "module": self.module_name
            }

            # Возвращаем полностью готовый, чистый FlowUnit
            yield FlowUnit(
                id=unit_id,
                is_active=True,
                meta=meta_data,
                body=stmt  # Сам сырой узел AST как полезная нагрузка (payload)
            )

