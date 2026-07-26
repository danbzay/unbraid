import json
from pathlib import Path
import ast
from cli import parse_args
from config import get_project_context
from pipeline import StreamPipeline


def main():
    ctx = get_project_context()

    import ast_flow
    from pipeline import StreamPipeline
    from exporter import ConsoleExporter

    target_file = ctx["target_file"]
    main_module = target_file.stem

    # 1. Загружаем главный файл
    raw_nodes = ast_flow.load(target_file)

    # 2. Инициализируем StreamPipeline
    pipeline = StreamPipeline(
        raw_nodes,
        id_fn=ast_flow.ast_id_factory(main_module),
        meta_fn=ast_flow.ast_meta_factory(),
        body_fn=ast_flow.ast_body_extractor(),
        pipeline_meta={
            "project_root": ctx["project_root"],
            "target_file": target_file
        }
    )

    # 3. Разворачиваем импорты
    integrated_pipeline = pipeline.flat_map(ast_flow.ModuleLoader())

    # 4. Материализуем для прыжков
    ready_pipeline = integrated_pipeline.materialize()

    # 5. Хронология + Области видимости
    final_flow = (
        ready_pipeline
        .route(ast_flow.AstRouter())
        .map(ast_flow.FlowScopeTracker())
    )

    def identity_formatter(unit):
        return unit

    final_flow.save(
        ConsoleExporter(title="БАЗОВАЯ СТАБИЛЬНАЯ ВЕРСИЯ"),
        formatter_func=identity_formatter
    )

if __name__ == "__main__":
    main()

