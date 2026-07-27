import copy
from contracts import FlowUnit


class StreamPipeline:
    """Абстрактный конвейер Fluent API с жесткой гарантией контракта полей."""

    def __init__(self, iterable, id_fn, meta_fn, body_fn, ctx=None):
        self.ctx = ctx if ctx is not None else {}
        self.call_stack = []

        # Индексируем источник в плоский массив
        units_list = []
        for raw_item in iterable:
            # ИСПРАВЛЕНИЕ: Передаем параметры СТРОГО именованно!
            # Это вычистит is_active и положит узел AST именно в body
            u = FlowUnit(
                id=id_fn(raw_item),
                meta=meta_fn(raw_item),
                body=body_fn(raw_item)
            )
            units_list.append(u)

        self.registry_map = {u.id: u for u in units_list}
        self.units = units_list

    def __iter__(self):
        return self

    def __next__(self) -> FlowUnit:
        return next(self.source)

    def route(self, router) -> "StreamPipeline":
        """Потоковый роутер: каретка двигается по живым объектам FlowUnit."""
        def route_generator():
            if not self.units:
                return

            current_unit = self.units[0]
            counter = 0

            while current_unit is not None and counter < 1000:
                counter += 1
                
                cloned = copy.deepcopy(current_unit)
                yield cloned  # Выталкиваем элемент в поток выполнения

                # Роутер на лету вычисляет и возвращает следующий объект FlowUnit!
                current_unit = router.calculate_next_unit(cloned, self)

        # Результирующий пайплайн тоже собираем строго по именованным контрактам
        return StreamPipeline(
            route_generator(),
            id_fn=lambda u: u.id,
            meta_fn=lambda u: u.meta,
            body_fn=lambda u: u.body,
            ctx=self.ctx
        )

    def save(self, store_instance, formatter_func) -> "StreamPipeline":
        processed_rows = []
        for unit in self.units:
            row_dict = formatter_func(unit)
            if row_dict is not None:
                processed_rows.append(row_dict)
        store_instance.export(processed_rows)
        return self

