import copy
from collections.abc import Callable, Iterable

class StreamPipeline:
    """Конвейер.
    """

    def __init__(self, source=None, **kwargs):

        if hasattr(source, "__dict__"):
            for key, value in vars(source).items():
                vars(self)[key] = copy.deepcopy(value)

        if source is None:
            self._base_factory = lambda: iter([])
        elif isinstance(source, dict):
            self._base_factory = lambda: iter(source.values())
        elif isinstance(source, Iterable) and not isinstance(source, Callable):
            self._base_factory = lambda: iter(source)
        elif isinstance(source, Callable):
            self._base_factory = source
        else:
            raise TypeError("Source must be Iterable, Callable, or dict")

        self._operators = []

        for key, value in kwargs.items():
            vars(self)[key] = copy.deepcopy(value)

    def pipe(self, operator_function):
        """Добавляет внешний оператор в цепочку."""
        self._operators.append(operator_function)
        return self
  
    def _run_operators(self, current_stream):
        """Внутренний служебный метод для безопасного прогона цепочки 
        операторов."""
        import inspect
        for operator in self._operators:
            # Проверяем, принимает ли оператор аргумент pipeline
            sig = inspect.signature(operator)
            if len(sig.parameters) >= 2:
                current_stream = operator(current_stream, pipeline=self)
            else:
                current_stream = operator(current_stream)
        return current_stream

    def __iter__(self):
        """Многократный ленивый обход."""
        return self._run_operators(self._base_factory())
        
    def isolate(self, collector_func=tuple):
        """
        Терминальный метод. Выкачивает поток в коллектор, превращает его 
        в заданный тип данных и возвращает независимый новый объект 
        с сохраненным контекстом.
        """
        final_stream = self._run_operators(self._base_factory())
        raw_collected = collector_func(final_stream)
        isolated_data = copy.deepcopy(raw_collected)
        print(f"{isolated_data=}")
        context_kwargs = vars(self).copy()
        context_kwargs.pop("_base_factory", None)
        context_kwargs.pop("_operators", None)
        
        return StreamPipeline(isolated_data, **context_kwargs)

    # ВСТРОЕННЫЕ МЕТОДЫ

    def map(self, transform_func):
        def map_operator(current_stream):
            for item in current_stream:
                yield transform_func(item)
        self._operators.append(map_operator)
        return self

    def divert_to(
        self, target_pipeline, start_cond, stop_cond, collector_func=tuple
    ):
        """
        Мутабельно-ленивый увод. Накапливает элементы в буфер.
        В момент stop_cond создает из буфера новый изолированный объект 
        при помощи метода .isolate() и обновляет target_pipeline.
        """
        def divert_operator(current_stream):
            is_diverted = False
            temp_buffer = []
            
            for item in current_stream:
                if start_cond(item):
                    is_diverted = True
                    
                if is_diverted:
                    temp_buffer.append(item)
                    
                    if stop_cond(item):
                        is_diverted = False
                        context_kwargs = {
                            k: v for k, v in vars(self).items() if k not in (
                                "_base_factory", "_operators"
                            )}
                        isolated_ps = StreamPipeline(
                            temp_buffer, **context_kwargs
                        ).isolate(collector_func)
                        target_pipeline._base_factory = (
                            isolated_ps._base_factory
                        )
                        vars(target_pipeline).update(vars(isolated_ps))
                                
                        temp_buffer = []
                    continue
                    
                yield item
                
        self._operators.append(divert_operator)
        return self

    def inject(self, embedded_source, inject_cond):
        """
        Лениво внедряет элементы из embedded_source (массив или другой пайплайн)
        ПЕРЕД элементом, для которого inject_cond вернул True.
        """
        def inject_operator(current_stream):
            for item in current_stream:
                if inject_cond(item):
                    # Выкачиваем встроенный источник (он пойдет со своего нуля)
                    for embedded_item in iter(embedded_source):
                        yield embedded_item
                yield item
        self._operators.append(inject_operator)
        return self


    def switch(
        self, alternative_pipeline, toggle_to_alt_cond, toggle_to_main_cond
    ):
        """
        Ленивый переключатель бесконечного потока.
        Пропускает элементы через себя, но если срабатывает toggle_to_alt_cond,
        поток временно перенаправляется на обработку в alternative_pipeline.
        Как только срабатывает toggle_to_main_cond — возвращается в основное 
        русло.
        """
        def switch_operator(current_stream):
            in_alternative_mode = False
            
            for item in current_stream:
                if not in_alternative_mode and toggle_to_alt_cond(item):
                    in_alternative_mode = True

                if in_alternative_mode:
                    processed_item_stream = alternative_pipeline._run_operators(
                        iter([item])
                    )
                    
                    for processed_item in processed_item_stream:
                        yield processed_item
                        
                    if toggle_to_main_cond(item):
                        in_alternative_mode = False
                        
                else:
                    yield item
                    
        self._operators.append(switch_operator)
        return self

    def context_scan(self, context_key, accumulator_func, initial_value=0):
        """
        Акуммулирует значение прямо внутри контекста пайплайна 
        (self.context_key).
        """
        def operator(current_stream):
            if not hasattr(self, context_key):
                setattr(self, context_key, initial_value)
                
            for item in current_stream:
                old_val = getattr(self, context_key)
                new_val = accumulator_func(old_val, item)
                setattr(self, context_key, new_val)
                yield item
                
        self._operators.append(operator)
        return self

