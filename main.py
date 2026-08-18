import json
import logging
from pathlib import Path
import ast
from cli import parse_args
from config import get_project_context
from pipeline import StreamPipeline, resolve_pipeline_tree

ctx = get_project_context()
main_logger = ctx["logger"]
logging.getLogger("unbraid.pipeline").setLevel(logging.DEBUG)
#logging.getLogger("unbraid.pipeline._hook_dispatcher").setLevel(logging.INFO)
logging.getLogger("unbraid.pipeline.isolate").setLevel(logging.INFO)
#logging.getLogger("unbraid.pipeline.divert_to").setLevel(logging.INFO)
logging.getLogger("unbraid.ast_flow").setLevel(logging.DEBUG)
#logging.getLogger("unbraid.ast_flow.resolve_scopes").setLevel(logging.INFO)



def main():
    import ast_flow

    target_file = ctx["target_file"]

    final_flow = (
            ast_flow.parse_module(
            target_file.stem, 
            project_root=target_file.parent,
            __main__=True
        )
        .pipe(ast_flow.resolve_scopes)
        .execute()
        .pipe(ast_flow.resolve_calls)
#        .pipe(ast.flow.resolve_assigns)
    ).execute()

    main_logger.info(
        f"[MAIN]:final_flow:\n" + 
        "\n".join(f"{k} = {str(v)}" for k, v in final_flow.__dict__.items())
    )
    lines = [
        f"{i.meta['module']}--{i.meta.get('call_frame', '')}--{i.meta['idx']}--"
        f"{i.meta['preds']}--{str(i.body)[:50]}"
        for i in final_flow
    ]

    main_logger.info(f"[MAIN]:output stream:\n" + "\n".join(lines))

    import json 
    main_logger.info(f"[MAIN]: {final_flow.modules_cache=}")

    for module, module_sp in final_flow.modules_cache.items():
        main_logger.info(f"[MAIN]: {module=}")
        symbol_tables = resolve_pipeline_tree(module_sp, "symbol_table")
        safe_data = json.loads(json.dumps(symbol_tables, default=str))
        main_logger.info(json.dumps(safe_data, indent=4, ensure_ascii=False))



if __name__ == "__main__":
    main()

