import copy
from contracts import FlowUnit

import copy
from contracts import FlowUnit

import copy
from pathlib import Path


class UnitedStreamSystem:
    """Универсальный координатор изолированных потоков.

    Поддерживает динамическую ленивую регистрацию импортов на лету [Example 4].
    """

    def __init__(self):
        # Словарь изолированных материализованных реестров: { "main_test": {id: unit} }
        self.project_registry = {}
        self.coordinate_stack = []
        # Глобальная мета-память системы (хранит корни проекта)
        self.system_meta = {}

    def register_stream_from_nodes(self, name: str, raw_items) -> None:
        """Внутренний метод: превращает сырой список load() в замороженную карту."""
        if name in self.project_registry:
            return
        # Материализуем элементы в плоскую карту для мгновенного прыжка по ID
        self.project_registry[name] = {f"{name}.{item[1]['idx']}": item for item in raw_items}

    def coordinate_route(self, router) -> "StreamPipeline":
        """Сквозной координатный проходчик с динамической загрузкой модулей."""

        def system_coordinate_generator():
            if not self.project_registry:
                return

            # Инициализируем роутер: передаем ему ссылку на UnitedStreamSystem
            router.initialize(self)

            # Стартуем с первого зарегистрированного модуля (главного файла)
            curr_stream_name = next(iter(self.project_registry.keys()))
            curr_registry = self.project_registry[curr_stream_name]
            curr_id = next(iter(curr_registry.keys())) if curr_registry else None

            counter = 0
            while curr_stream_name is not None and curr_id is not None and counter < 1000:
                counter += 1
                
                # Достаем сырую пару (node, meta) из текущего активного модуля
                raw_pair = self.project_registry[curr_stream_name].get(curr_id)
                if not raw_pair:
                    break

                # Лениво оборачиваем во FlowUnit строго в момент наступания!
                from contracts import FlowUnit
                # Извлекаем фабрики полей для текущего модуля
                from ast_flow import _ast_id_factory, _ast_meta_factory, _ast_body_extractor
                
                unit = FlowUnit(
                    id=_ast_id_factory(curr_stream_name)(raw_pair),
                    meta=_ast_meta_factory()(raw_pair[1]),
                    body=_ast_body_extractor()(raw_pair[0])
                )

                cloned = copy.deepcopy(unit)
                yield cloned

                # --- ДИНАМИЧЕСКИЙ ЛЕНИВЫЙ ИМПОРТ НА ЛЕТУ ---
                if cloned.meta.get("op_type") == "ImportFrom":
                    module_name = cloned.body.module
                    
                    # Проверяем, зарегистрирован ли этот модуль. Если нет — загружаем!
                    if module_name not in self.project_registry:
                        project_root = Path(self.system_meta["project_root"])
                        potential_file = project_root / f"{module_name}.py"
                        
                        if potential_file.exists():
                            import ast_flow
                            # Рекурсивно деструктурируем сторонний файл
                            raw_pairs = ast_flow.load(potential_file)
                            # Динамически подселяем его в общую систему проекта!
                            self.register_stream_from_nodes(module_name, raw_pairs)
                            # Переинициализируем роутер, чтобы он увидел новые def-ы
                            router.initialize(self)

                # --- УМНЫЙ КООРДИНАТНЫЙ МАРШРУТИЗАТОР СИСТЕМЫ ---
                if router.is_return(cloned, self):
                    if self.coordinate_stack:
                        curr_stream_name, curr_id = self.coordinate_stack.pop()
                        curr_registry = self.project_registry[curr_stream_name]
                    else:
                        curr_stream_name, curr_id = None, None
                    continue

                jump_coordinates = router.get_jump_coordinates(cloned, self)
                if jump_coordinates is not None:
                    next_id = router.get_next_id(cloned, curr_registry)
                    if next_id is not None:
                        self.coordinate_stack.append((curr_stream_name, next_id))
                    
                    curr_stream_name, curr_id = jump_coordinates
                    curr_registry = self.project_registry[curr_stream_name]
                    continue

                curr_id = router.get_next_id(cloned, curr_registry)

        from pipeline import StreamPipeline
        return StreamPipeline(
            system_coordinate_generator(),
            id_fn=lambda u: u.id,
            meta_fn=lambda u: u.meta,
            body_fn=lambda u: u.body
        )

class StreamPipeline:
    """Абстрактный конвейер Fluent API с поддержкой глобального контекста."""

    def __init__(self, iterable, id_fn, meta_fn, body_fn, pipeline_meta=None):
        self.source = iter(iterable)
        self.id_fn = id_fn
        self.meta_fn = meta_fn
        self.body_fn = body_fn
        # ГЛОБАЛЬНАЯ ПАМЯТЬ ПОТОКА: хранит пути, корни проекта, таблицы прыжков
        self.pipeline_meta = pipeline_meta if pipeline_meta is not None else {}
        self.call_stack = []

    def __iter__(self):
        return self

    def __next__(self) -> FlowUnit:
        raw_item = next(self.source)
        return FlowUnit(
            id=self.id_fn(raw_item),
            meta=self.meta_fn(raw_item),
            body=self.body_fn(raw_item)
        )

    def flat_map(self, expander) -> "StreamPipeline":
        """Операция Вставки. Передает ссылку на сам pipeline внутрь экспандера."""
        def expand_generator():
            for unit in self:
                local_counter = 0
                def next_id_factory():
                    nonlocal local_counter
                    local_counter += 1
                    return f"{unit.id}.{local_counter}"

                # КРИТИЧЕСКИЙ ШАГ: Передаем ССЫЛКУ на текущий pipeline (self),
                # чтобы экспандер мог прочитать глобальные метаданные потока!
                new_units = expander.expand(unit, next_id_factory, self)
                if new_units:
                    for new_unit in new_units:
                        yield new_unit
                else:
                    yield unit

        return StreamPipeline(
            expand_generator(),
            id_fn=lambda u: u.id,
            meta_fn=lambda u: u.meta,
            body_fn=lambda u: u.body,
            pipeline_meta=self.pipeline_meta  # Передаем глобальную память дальше
        )


    def map(self, mapper_func) -> "StreamPipeline":
        def map_generator():
            for unit in self:
                cloned = copy.deepcopy(unit)
                mapper_func(cloned)
                yield cloned
        return StreamPipeline(
            map_generator(),
            id_fn=lambda u: u.id,
            meta_fn=lambda u: u.meta,
            body_fn=lambda u: u.body,
            pipeline_meta=self.pipeline_meta  # Сохраняем глобальную память
        )


    def filter(self, predicate_func) -> "StreamPipeline":
        """2. Операция Фильтрации."""
        def filter_generator():
            for unit in self:
                cloned = copy.deepcopy(unit)
                # Если переданная функция-фильтр возвращает False, выключаем узел
                if not predicate_func(cloned):
                    cloned.meta["is_disabled"] = True  # Сохраняем признак в мета
                yield cloned
                
        return StreamPipeline(
            filter_generator(),
            id_fn=lambda u: u.id,
            meta_fn=lambda u: u.meta,
            body_fn=lambda u: u.body
        )


    def save(self, store_instance, formatter_func) -> "StreamPipeline":
        """Терминальный метод выгрузки данных в БД или файлы."""
        processed_rows = []
        for unit in self:
            row_dict = formatter_func(unit)
            if row_dict is not None:
                processed_rows.append(row_dict)
        store_instance.export(processed_rows)
        return self


    def filter(self, predicate_func) -> "StreamPipeline":
        """2. ... (код filter_generator) ..."""
        def filter_generator():
            for unit in self:
                cloned = copy.deepcopy(unit)
                # ИСПРАВЛЕНИЕ: Вызываем предикат напрямую как чистую функцию
                if not predicate_func(cloned):
                    cloned.meta["is_disabled"] = True
                yield cloned

        return StreamPipeline(
            filter_generator(),
            id_fn=lambda u: u.id,
            meta_fn=lambda u: u.meta,
            body_fn=lambda u: u.body
        )

    def materialize(self) -> "StreamPipeline":
        """Замораживает текущую фазу и строит хэш-карту для прыжков.

        Сохраняет бесконечную цепочку Fluent API.
        """
        # Вычитываем ленивый источник в плоский список элементов FlowUnit
        units_list = list(self)
        
        # Строим быструю карту для мгновенного доступа по ID: { "main_test.1": FlowUnit }
        registry_map = {u.id: u for u in units_list}

        # Возвращаем новый Pipeline, передав карту в его глобальную память!
        return StreamPipeline(
            units_list,
            id_fn=lambda u: u.id,
            meta_fn=lambda u: u.meta,
            body_fn=lambda u: u.body,
            pipeline_meta={
                **self.pipeline_meta,
                "registry_map": registry_map  # Сохранили карту для роутера!
            }
        )

    def route(self, router) -> "StreamPipeline":
        """3. Операция Смены маршрута (Проходчик по инструкциям)."""
        # Извлекаем замороженную карту элементов из глобального контекста
        registry = self.pipeline_meta.get("registry_map", {})

        def route_generator():
            if not registry:
                return

            # Инициализируем роутер: даем ему построить карту функций
            # Передаем self, чтобы он мог прочитать реестр
            router.initialize(self)

            # Находим стартовый ID (самый первый элемент в реестре)
            current_id = next(iter(registry.keys()))
            counter = 0

            while current_id is not None and counter < 1000:
                counter += 1
                unit = registry.get(current_id)
                if not unit:
                    break

                # Лениво клонируем элемент для этого конкретного шага выполнения
                cloned = copy.deepcopy(unit)
                yield cloned

                # --- ДИНАМИЧЕСКИЙ ХОД ПО ИНСТРУКЦИЯМ (ВАРИАНТ №2) ---
                if router.is_return(cloned):
                    current_id = self.call_stack.pop() if self.call_stack else None
                    continue

                jump_id = router.get_jump_id(cloned)
                if jump_id is not None:
                    next_id = router.get_next_id(cloned)
                    if next_id is not None:
                        self.call_stack.append(next_id)
                    current_id = jump_id
                    continue

                current_id = router.get_next_id(cloned)

        return StreamPipeline(
            route_generator(),
            id_fn=lambda u: u.id,
            meta_fn=lambda u: u.meta,
            body_fn=lambda u: u.body,
            pipeline_meta=self.pipeline_meta
        )


