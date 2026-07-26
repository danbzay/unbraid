import json
from pathlib import Path
import ast
from cli import parse_args
from config import get_project_context
from pipeline import StreamPipeline


def main():
    ctx = get_project_context()
    import ast_flow
    from exporter import SQLiteStore
    import ast_flow
    from pipeline import UnitedStreamSystem
    # ... (код получения контекста ctx) ...
    import ast_flow
    from pipeline import UnitedStreamSystem
    from exporter import ConsoleExporter

    # 1. Создаем большую систему
    system = UnitedStreamSystem()
    # Запоминаем корень проекта в глобальной памяти системы
    system.system_meta["project_root"] = ctx["project_root"]

    # 2. Регистрируем ОДИН единственный главный файл проекта на старте!
    main_module = ctx["target_file"].stem
    raw_nodes = ast_flow.load(ctx["target_file"])
    system.register_stream_from_nodes(main_module, raw_nodes)

    # 3. АКТИВАЦИЯ КООРДИНАТНОЙ СИСТЕМЫ: Она сама лениво найдет 
    # и подселит все импортируемые модули в момент наступания на ImportFrom!
    final_flow = system.coordinate_route(ast_flow.AstCoordinateRouter())

    # 4. Прогоняем через трекер областей видимости и выводим в консоль
    def identity_formatter(unit):
        return unit

    final_flow.map(ast_flow.FlowScopeTracker()).save(
        ConsoleExporter(title="МНОГОМОДУЛЬНЫЙ КООРДИНАТНЫЙ СРЕЗ"),
        formatter_func=identity_formatter
    )

if __name__ == "__main__":
    main()

