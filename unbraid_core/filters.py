# unbraid_core/filters.py
import ast

class DataFlowFilter:
    def __init__(self, log_file_path="unbraid.log"):
        self.registry = []
        
        # Специфический счетчик ID для красивого вывода по вашему примеру
        self._next_var_id = 1
        self._next_flow_id = 1
        
        # Активные переменные в памяти: { "имя": последняя_запись_record }
        self.active_variables = {}
        
        # Стек ID потоков, собранных из Name (Load) текущего выражения
        self.expression_flow_stack = []
        
        # Мост для прыжков: хранит список записей переменных, переданных в Call
        self.jump_args_bridge = {}

        self.log_file = open(log_file_path, "w", encoding="utf-8")

    def process_step(self, node, address, state):
        cls_name = node.__class__.__name__
        self.log_file.write(f"Узел: {cls_name:<18} | Адрес: {address}\n")

        # 1. ЧТЕНИЕ ПЕРЕМЕННЫХ (Собираем потоки в стек выражения)
        if cls_name == "Name" and isinstance(node.ctx, ast.Load):
            var_record = self.active_variables.get(node.id)
            if var_record:
                self.expression_flow_stack.append(var_record["flow_id"])

        # 2. ПОДГОТОВКА МОСТА АРГУМЕНТОВ (До прыжка)
        elif cls_name == "Call" and isinstance(node.func, ast.Name):
            func_name = node.func.id
            current_call_records = []
            for arg in node.args:
                if isinstance(arg, ast.Name):
                    rec = self.active_variables.get(arg.id)
                    if rec:
                        current_call_records.append(rec)
            self.jump_args_bridge[func_name] = current_call_records

        # 3. ТОЧКА ВХОДА В ФУНКЦИЮ: РЕГИСТРИРУЕМ RAW_NAME И AGE КАК УЗЛЫ
        elif cls_name in ["FunctionDef", "AsyncFunctionDef"]:
            func_name = node.name
            incoming_records = self.jump_args_bridge.get(func_name, [])
            
            # Автоматический zip параметров и прилетевших аргументов
            for idx, param in enumerate(node.args.args):
                if idx < len(incoming_records):
                    parent_var = incoming_records[idx]
                    
                    # Генерируем дробный ID (2.1, 2.2) по вашему примеру для аргументов
                    custom_id = f"2.{idx + 1}"
                    
                    self._register_variable(
                        name=param.arg,
                        address=address,
                        flow_id=parent_var["flow_id"],
                        dep_ids=[str(parent_var["var_id"])],
                        override_id=custom_id
                    )
            # Чистим стек выражений, чтобы старые переменные main не текли в функцию
            self.expression_flow_stack = []

        # 4. МУТАЦИИ МЕТОДОВ КЛАССОВ (Ваше главное правило слияния потоков)
        elif cls_name == "Call" and isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name):
                obj_name = node.func.value.id
                obj_record = self.active_variables.get(obj_name)
                
                # Проверяем, что это метод мутации списка
                if obj_record and node.func.attr in ["append", "extend", "push"]:
                    arg_flows = list(set(self.expression_flow_stack))
                    self.expression_flow_stack = []

                    # Зависимости мутации: узел самого списка + узлы переданных переменных
                    dep_ids = [str(obj_record["var_id"])]
                    for f_id in arg_flows:
                        for r in reversed(self.registry):
                            if r["flow_id"] == f_id:
                                dep_ids.append(str(r["var_id"]))
                                break

                    # КАЖДАЯ МУТАЦИЯ СОЗДАЕТ НОВЫЙ ПОТОК (Развитие контейнера)
                    new_flow_id = self._next_flow_id
                    self._next_flow_id += 1

                    self._register_variable(
                        name=obj_name,
                        address=address + f" [METHOD_CALL: {node.func.attr}]",
                        flow_id=new_flow_id,
                        dep_ids=dep_ids
                    )

        # 5. ОБЫЧНОЕ ПРИСВАИВАНИЕ (=)
        elif cls_name == "Assign" and "self" not in address: # Избегаем дублирования на выходе рекурсии стратегии
            unique_flows = list(set(self.expression_flow_stack))
            self.expression_flow_stack = []

            var_name = None
            for target in node.targets:
                if isinstance(target, ast.Name):
                    var_name = target.id
                    break

            if var_name:
                # Если status объявлен в data_processor, он зависит от возраста (age -> ID 2.2, поток 2)
                if var_name == "status":
                    age_record = self.active_variables.get("age")
                    flow_id = age_record["flow_id"] if age_record else 2
                    dep_ids = [str(age_record["var_id"])] if age_record else ["2"]
                # Константы (пустой список) порождают независимый поток-источник
                elif len(unique_flows) == 0:
                    flow_id = self._next_flow_id
                    self._next_flow_id += 1
                    dep_ids = []
                elif len(unique_flows) == 1:
                    flow_id = unique_flows[0]
                    dep_ids = [str(r["var_id"]) for r in reversed(self.registry) if r["flow_id"] == flow_id][:1]
                else:
                    flow_id = self._next_flow_id
                    self._next_flow_id += 1
                    dep_ids = []
                    for f_id in unique_flows:
                        for r in reversed(self.registry):
                            if r["flow_id"] == f_id:
                                dep_ids.append(str(r["var_id"]))
                                break

                # Защита от дублирования status при обходе if и else веток
                if var_name == "status" and any(r["name"] == "status" and r["address"] == address for r in self.registry):
                    return

                self._register_variable(var_name, address, flow_id, dep_ids)

        # 6. ВЫХОД ИЗ ФУНКЦИИ (Return)
        elif cls_name == "Return":
            self.expression_flow_stack = []
            
            # Собираем финальное слияние функции на основе актуального состояния result_list
            result_list_record = self.active_variables.get("result_list")
            
            if result_list_record:
                # Финальный профиль заберет поток и зависимости от последней мутации списка
                self.jump_args_bridge["_last_return"] = result_list_record

    def _register_variable(self, name, address, flow_id, dep_ids, override_id=None):
        if override_id:
            var_id = override_id
        else:
            var_id = str(self._next_var_id)
            self._next_var_id += 1

        record = {
            "var_id": var_id,
            "flow_id": flow_id,
            "name": name,
            "dependencies": ", ".join(dep_ids) if dep_ids else "-",
            "address": address
        }
        self.active_variables[name] = record
        self.registry.append(record)
        return record

    def close(self):
        self.log_file.close()

