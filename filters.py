import ast


def default_flow_filter(stmt):
    """Формирует стандартную таблицу шагов выполнения проекта."""
    # Игнорируем строки импортов в финальном бизнес-отчете
    if isinstance(stmt, (ast.Import, ast.ImportFrom)):
        return None

    space = getattr(stmt, "unbraid_space", "main_test")
    if isinstance(space, list):
        space = ".".join(space)

    # Задаем структуру полей для таблицы data_flow
    return {
        "context": space,
        "operation": type(stmt).__name__,
        "code_line": ast.unparse(stmt),
    }


def variables_only_filter(stmt):
    """Формирует структуру полей только для операций с переменными."""
    # Интересуют только строки, где данные записываются (Assign)
    if not isinstance(stmt, ast.Assign):
        return None

    space = getattr(stmt, "unbraid_space", "main_test")
    if isinstance(space, list):
        space = ".".join(space)

    # Собираем все имена переменных из левой части
    found_names = []
    for target in stmt.targets:
        for name_node in ast.walk(target):
            if isinstance(name_node, ast.Name):
                found_names.append(name_node.id)

    if not found_names:
        return None

    # Задаем структуру полей для таблицы variables_log
    return {
        "context": space,
        "variable_names": ", ".join(found_names),
        "assigned_expression": ast.unparse(stmt.value),
    }

