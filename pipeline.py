import copy
from collections.abc import Callable, Iterable, Mapping
import itertools

import logging
logger = logging.getLogger(f"unbraid.{__name__}")

class DerivedUnit:
    def __init__(self, body, meta=None):
        self.body = body   
        self.meta = meta or {}  
        self.id = getattr(body, 'id', id(self))

    def __repr__(self):
        return f"Derived(body={self.body}, meta={self.meta})"

import itertools
from collections.abc import Iterable

class DynamicChainValve:
    """Плоский динамический переключатель ленивых потоков.
    Позволяет делать .append() новых генераторов прямо во время итерации!"""
    def __init__(self, initial_source):
        self._streams = [iter(initial_source)]
        self._current_idx = 0

    def append(self, new_source):
        """Динамически добавляет новый ленивый поток в хвост цепочки."""
        if not isinstance(new_source, Iterable):
            raise TypeError("Можно аппендить только итерируемые объекты ")
        self._streams.append(iter(new_source))
        return self

    def __iter__(self):
        return self

    def __next__(self):
        while self._current_idx < len(self._streams):
            try:
                return next(self._streams[self._current_idx])
            except StopIteration:
                self._current_idx += 1
                
        raise StopIteration

class StreamPipeline:
    """Конвейер.
    """

    def __init__(
        self, source=None, merge_context=True, only=None, **overrides
    ):
        # поля которые нельзя копировать при переносе параметров
        self._infra_attributes = [
            "_base_factory", 
            "_operators", 
            "_active_valve", 
            "_append_buffer", 
            "hooks",
            "term_len",
        ]
        # поля которые будут копируются поверхностно
        self._shallow_attributes = []

        self._append_buffer = [] 
        if source is None:
            self._base_factory = lambda: DynamicChainValve(self._append_buffer)
        elif isinstance(source, Callable):
            self._base_factory = (
                lambda: DynamicChainValve(source()).append(self._append_buffer)
            )
        elif (
                isinstance(source, Iterable) and 
                not isinstance(source, (str, bytes, Mapping))
            ):
            self._base_factory = (
                lambda: DynamicChainValve(source).append(self._append_buffer)
            )
        else:
            raise TypeError(
                f"Source must be an Iterable sequence or Callable. "
                f"Got {type(source).__name__}. Strings, bytes and mappings are "
                f"explicitly blocked."
            )

        self._operators = []
        self.applied_operators = []
        self.hooks = {}
        self._active_valve = None
        self.term_len = None

        if merge_context:
            self.merge_context_from(source, only=only, **overrides)

    def merge_context_from(self, source=None, only=None, **overrides):
        """
        Сливает прикладной контекст из source.
        Если передан only (tuple/list), переносятся ТОЛЬКО указанные свойства.
        """
        source_attrs = vars(source) if hasattr(source, "__dict__") else source
        if not isinstance(source_attrs, dict):
            source_attrs = {}

        self._infra_attributes = list(set(
            self._infra_attributes + getattr(source, "_infra_attributes", [])
        ))
        self._shallow_attributes = list(set(
            self._shallow_attributes + getattr(source, "_shallow_attributes", []
        )))
#        logger.debug(
#            f"[MERGE_CONTEXT_FROM] {self._infra_attributes=}\n"
#            f"{self._shallow_attributes=}"
#        )

        keys_to_copy = only if only is not None else source_attrs.keys()

        for key in keys_to_copy:
            if key in self._infra_attributes or key not in source_attrs:
                continue
            value = source_attrs[key]
#            logger.debug(f"[MERGE_CONTEXT_FROM] {key=}, {value=}")
            if key in self._shallow_attributes:
                vars(self)[key] = value
            else:
                vars(self)[key] = copy.deepcopy(value)

        for key, value in overrides.items():
#            logger.debug(f"[MERGE_CONTEXT_FROM] {key=}, {value=}")
            if key in self._shallow_attributes:
                vars(self)[key] = value
            else:
                vars(self)[key] = copy.deepcopy(value)

        return self

    def __iter__(self):
        """Многократный ленивый обход."""
        self._active_valve = self._base_factory()
        logger.debug(f"[__ITER__]: {self=}, {self._active_valve=}")
        return self._run_operators(self._active_valve)
  
    def _run_operators(self, current_stream):
        """Внутренний служебный метод для безопасного прогона цепочки 
        операторов."""
        import inspect
        for operator in self._operators:
            logger.debug(f"[_RUN_OPERATORS]: {operator=}")
            # Проверяем, принимает ли оператор аргумент pipeline
            sig = inspect.signature(operator)
            if len(sig.parameters) >= 2:
                current_stream = operator(current_stream, pipeline=self)
            else:
                current_stream = operator(current_stream)

        current_stream = self._hook_dispatcher(current_stream)
        return current_stream

    def _hook_dispatcher(self, current_stream):
        """Полностью слепой диспетчер. Прогоняет каждый элемент 
        сквозь динамический список пользовательских хуков."""
        logger = logging.getLogger(f"unbraid.{__name__}._hook_dispatcher")
        try:
            for item in current_stream:
                processed_item = item
                
                active_hook_items = sorted(
                    self.hooks.items(),
                    key=lambda x: x[1][0] if isinstance(x, tuple) else 0,
                    reverse=True
                )
                logger.debug(f"[_HOOK_DISPATCHER]: {active_hook_items=}")
                for key, hook_data  in active_hook_items:
                    logger.debug(f"[_HOOK_DISPATCHER]: {key=}")
                    if key not in self.hooks:
                        continue
                    hook_func = (
                        hook_data[1] if isinstance(hook_data, tuple)
                        else hook_data
                    )
                    if hook_func:
                        processed_item = hook_func(
                            processed_item, pipeline=self
                        )
                        if processed_item is None:
                            break
                
                if processed_item is not None:
                    if (
                        isinstance(processed_item, Iterable) and  
                        not isinstance(processed_item, (str, bytes))
                    ):
                            yield from processed_item
                            continue

                    yield processed_item

            return current_stream
        finally:
            self._active_valve = None

    def pipe(self, operators):
        """Добавляет внешние операторы в цепочку."""
        operators = ([operators] if not isinstance(operators, (list, tuple)) 
                     else operators)
        self._operators.extend(operators)
        return self
        
    def append(self, item):
        """ Добавляет элемент в хвост текущего конвейера"""
        self._append_buffer.append(item)
        return self

    def execute(self):
        """
        Терминальный оператор фиксации на месте. 
        Полностью выкачивает ленивый поток, превращая его в жесткий массив нод,
        очищает отработавшие операторы статики, но сохраняет сам экземпляр 
        пайплайна (self). Cсылки на этот объект остаются валидными.
        """

        for op in self._operators:
            self.applied_operators.append(getattr(op, "__name__", str(op)))
        executed_data = list(self)
        logger.debug(f"[EXECUTE]: {self=}, {self.applied_operators=}")
        self._operators = []
        self.hooks = {}
        self._active_valve = None
        self.term_len = len(executed_data)
        
        self._base_factory = (
            lambda: DynamicChainValve(executed_data).append(self._append_buffer)
        )
        return self

    def isolate(self, **overrides):
        """
        Терминальный метод. Выкачивает поток в буфер и возвращает независимый 
        новый пайплайн с сохраненным контекстом.
        """
        logger = logging.getLogger(f"unbraid.{__name__}.isolate")

        isolated_data = copy.deepcopy(tuple(self))
        new_pipeline = (
            StreamPipeline(isolated_data).merge_context_from(self, **overrides)
        )
        for op in self._operators:
            new_pipeline.applied_operators.append(
                getattr(op, "__name__", str(op))
            )
        new_pipeline.term_len = len(isolated_data)
        logger.debug(f"[ISOLATE]: {new_pipeline.applied_operators=}")
        logger.info(
            f"[ISOLATE]: {len(isolated_data)} items from {self} "
            f" to {new_pipeline}"
            )
        logger.debug(
            f"[ISOLATE]:\n" + "\n".join(str(i)[:80] for i in isolated_data))
        return new_pipeline

    # ВСТРОЕННЫЕ МЕТОДЫ

    def trigger_action(cond_func, action_func, key="trigger", priority=0):
        """
        Создает оператор, который вешает хук-растяжку.
        Как только условие выполняется, запускается action_func.
        """
        logger = logging.getLogger(f"unbraid.{__name__}.divert_to")
        import inspect
        logger.info(
            f"[TRIGGER_ACTION]: {self=} {key=}\n"
            f"{inspect.getsource(cond_func)}"
            f"{inspect.getsource(action_func)}"
        )
        def trigger_hook(item, pipeline):
            if cond_func(item):
                action_func(item, pipeline)
                if key in pipeline.hooks:
                    del pipeline.hooks[key]
            return item

        if self._active_valve is None:
            def trigger_operator(current_stream, pipeline):
                pipeline.hooks[key] = (priority, trigger_hook)
                yield from current_stream
            self._operators.append(trigger_operator)
        else:
            pipeline.hooks[key] = (priority, trigger_hook)
                
        return self


    def append_stream(self, new_source):
        """
        Лениво добавляет новый поток в конец цепочки.  
        Если в _append_buffer уже есть элементы, они остаются в цепочке
        перед новым источником, а новый пустой буфер добавляется в конец.
        """
        self._append_buffer = []
        old_factory = self._base_factory
        self._base_factory = lambda: (
            old_factory().append(new_source).append(self._append_buffer)
        )

        if self._active_valve is not None:
            self._active_valve.append(new_source).append(self._append_buffer)
            
        return self

    def map(self, transform_func):
        def map_operator(current_stream):
            for item in current_stream:
                yield transform_func(item)
        self._operators.append(map_operator)
        return self

    def divert_to(
        self, target_pipeline, is_group_member, key="divert", priority=0
    ):
        """
        Мутабельно-ленивый увод данных. Создает хук или оператор для отвода
        данных по условию is_group_member(item) в target_pipeline.  
        """
        logger = logging.getLogger(f"unbraid.{__name__}.divert_to")
        import inspect
        logger.info(
                f"[DIVERT TO]: {self=} to {target_pipeline} {key=}\n"
                f"{inspect.getsource(is_group_member)}"
        )
        if self._active_valve is None:
            def divert_operator(current_stream):
                for item in current_stream:
                    if is_group_member(item):
                        target_pipeline.append(item)
                    else:
                        yield item
            self._operators.append(divert_operator)
            logger.debug(f"[DIVERT TO]: {self._operators=}")
            return self
        else:
            def divert_hook(item, pipeline):
                if is_group_member(item):
                    target_pipeline.append(item)
                    logger.debug(
                        f"[DIVERT_HOOK]: {key} append {item.meta} "
                        f"to {target_pipeline}\n"
                    )
                    return None
                return item
            self.hooks[key] = (priority, divert_hook)
            logger.debug(
                f"[DIVERT TO]: add {(key, priority)} to "
                f"hooks: {[(k, v[0]) for k,v in self.hooks.items()]}"
            )

            return self


    def inject_from(
        self, embedded_source, inject_cond, key="inject_hook", priority=0
    ):
        """
        Лениво внедряет элементы из embedded_source (массив или другой пайплайн)
        ПЕРЕД элементом, для которого inject_cond вернул True.
        """
        import inspect
        logger.debug(
            f"[INJECT_FROM]: {embedded_source} to {self}\n"
            f"{inspect.getsource(inject_cond)}"
        )
        def create_inject_operator(inject_cond):
            def inject_operator(current_stream):
                for item in current_stream:
                    if inject_cond(item):
                        yield from embedded_source
                    yield item
            return inject_operator

        if self._active_valve is None:
            self._operators.append(create_inject_operator(inject_cond))
            logger.debug(f"[INJECT_FROM]: {self._operators=}")
            return self
        else:
            def dynamic_inject_hook(item, pipeline):
                if inject_cond(item):
                    logger.debug(f"[INJECT_HOOK]: {key} triggered on {item=}")
                    if key in pipeline.hooks:
                        del pipeline.hooks[key]
                    pipeline._operators.append(
                        create_inject_operator(inject_cond)
                    )
                    def _inject_generator():
                        yield from embedded_source
                        yield item
                    return _inject_generator()
                return item
            self.hooks[key] = (priority, dynamic_inject_hook)
            logger.debug(
                f"[INJECT_FROM]: add {(key, priority)} to "
                f"hooks: {[(k, v[0]) for k,v in self.hooks.items()]}"
            )
            return self

    def switch_to(
            self, alternative_stream, toggle_to_alt_cond=lambda item: True,
            key="switch", priority=0
    ):
        """
        Ленивый односторонний триггер. 
        Пропускает элементы. Если срабатывает toggle_to_alt_cond,
        он полностью опустошает alternative_stream в текущее русло конвейера
        перед элементом.
        """
        logger.debug(
            f"[SWITCH_TO]: {alternative_stream=}, {self._active_valve=}, {key=}"
            f"{self=}"
        )

        if self._active_valve is None:
            def switch_operator(current_stream):
                for item in current_stream:
                    yield item
                    if toggle_to_alt_cond(item):
                        yield from alternative_stream
            self._operators.append(switch_operator)
            logger.debug(f"[SWITCH_TO]: {self._operators=}")
            return self
        else:
            def switch_hook(item, pipeline):
                if toggle_to_alt_cond(item):
                    logger.debug(f"[SWITCH_HOOK]: {str(item.body):.40}")
                    if key in pipeline.hooks:
                        del pipeline.hooks[key]
                    return (alternative_stream, item)
                return item

            self.hooks[key] = (priority, switch_hook)
            logger.debug(f"[SWITCH_TO]: {self.hooks=}")
            return self

    def context_scan(
        self, context_key, accumulator_func, initial_value=0, **acc_kwargs
    ):
        """
        Акуммулирует значение прямо внутри контекста пайплайна 
        (self.context_key).
        """
        def context_scan_operator(current_stream, pipeline):
            if not hasattr(self, context_key):
                setattr(self, context_key, copy.deepcopy(initial_value))
                
            for item in current_stream:
                old_val = getattr(pipeline, context_key)
                new_val = accumulator_func(old_val, item, **acc_kwargs)
                setattr(pipeline, context_key, new_val)
                yield item
                
        self._operators.append(context_scan_operator)
        return self

    def on_completion_scan(self, context_key, export_func):
        """
        Оператор, который регистрирует генераторный хук-финализатор.
        Он ждет окончания потока, запускает export_func и кладет результат 
        в контекст.
        """
        def finalizer_operator(current_stream, pipeline):
            try:
                for item in current_stream:
                    yield item
            finally:
                logger.debug(f"[FINALIZER_HOOK]: Запускаем сбор контекста")
                final_result = export_func(pipeline)
                setattr(pipeline, context_key, final_result)

        self._operators.append(finalizer_operator)
        return self

def resolve_pipeline_tree(data, target_field=None):
    """
    Рекурсивно обходит нативный словарь или список.
    Если встречает объект пайплайна, заменяет его на внутреннее поле 
    и лавиной разворачивает всю вложенную иерархию скоупов.
    """

    if isinstance(data, StreamPipeline):
        return resolve_pipeline_tree(
            getattr(data, target_field, str(data)), target_field
        )

    elif isinstance(data, dict):
        resolved_dict = {}
        for key, value in data.items():
            resolved_dict[key] = resolve_pipeline_tree(
                value, target_field
            )
        return resolved_dict

    elif isinstance(data, (list, tuple)):
        return [resolve_pipeline_tree(item, target_field) for item in data]

    return data

