import json
from pathlib import Path
import ast
from cli import parse_args
from config import get_project_context
from pipeline import StreamPipeline


def main():
    ctx = get_project_context()
    import ast_flow
    from exporter import ConsoleExporter

    # Вызываем load, запускаем потоковый route и сохраняем!
    final_flow = ast_flow.load(ctx["target_file"]).route(ast_flow.AstRouter())


    def identity_formatter(unit):
        import ast
        return {
            "unit": unit
        }


    final_flow.save(
        ConsoleExporter(title="ЧИСТЫЙ ПОТОКОВЫЙ КОНВЕЙЕР ОБЪЕКТОВ"),
        formatter_func=identity_formatter
    )

if __name__ == "__main__":
    main()

