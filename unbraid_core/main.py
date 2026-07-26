# main.py
import json
import os
import ast
from unbraid_core.iterator import SimplifiedFlowIterator
from unbraid_core.strategies import SimplifiedFlowStrategy
from unbraid_core.filters import DataFlowFilter

def run_analysis():
    if not os.path.exists("config.json"): return

    with open("config.json", "r") as f:
        config = json.load(f)

    entry_point = config.get("entry_point")
    target_files = config.get("target_files", [])

    file_registry = {}
    entry_tree = None

    for file_path in target_files:
        if not os.path.exists(file_path): continue
        with open(file_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())
            file_registry[os.path.normpath(file_path)] = tree
            if file_path == entry_point: entry_tree = tree

    # Находим функцию main
    main_func_node = None
    for node in entry_tree.body:
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) 
            and node.name == "main"
        ):
            main_func_node = node
            break

    initial_iterator = SimplifiedFlowIterator(
        entry_tree, entry_point, SimplifiedFlowStrategy(), file_registry
    )
    initial_iterator.state["process_user_data"] = (
        "tests/data_processor.py#process_user_data"
    )
    flow = initial_iterator._process_list(
        main_func_node.body, "FunctionDef(main).body"
    )

    # Инициализируем фильтр
    df_filter = DataFlowFilter()

    # НАШ ЦИКЛ ТРАССИРОВКИ
    for node, address, state in flow:
        cls_name = node.__class__.__name__

        # Передаем узел в фильтр
        df_filter.process_step(node, address, state)

        # Фиксируем сборку final_profile строго в момент возврата управления 
        # в main
        if cls_name == "Assign" and "final_profile" in address and "_last_return" in df_filter.jump_args_bridge:
            ret_record = df_filter.jump_args_bridge.pop("_last_return")
            df_filter._register_variable(
                name="final_profile",
                address=address,
                flow_id=ret_record["flow_id"],
                dep_ids=[str(ret_record["var_id"])]
            )

    df_filter.close()

    # КРАСИВЫЙ ИТОГОВЫЙ ВЫВОД В КОНСОЛЬ
    print("[Unbraid] Анализ потоков данных (Data Flow Graph) успешно завершен.\n")
    print(f"{'ID':<4} | {'ID Потока':<10} | {'Имя переменной':<15} | {'Зависимости (ID)':<18} | {'Глобальный адрес узла (URI) мутации'}")
    print("-" * 120)
    for row in df_filter.registry:
        short_addr = row['address'].replace("Module.body[4].body", "main")
        print(f"{row['var_id']:<4} | {row['flow_id']:<10} | {row['name']:<15} | {row['dependencies']:<18} | {short_addr}")

if __name__ == "__main__":
    run_analysis()

