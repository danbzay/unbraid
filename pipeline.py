import copy
from contracts import FlowUnit


class StreamPipeline:
    """Абстрактный конвейер Fluent API, полностью отвязанный от типов."""

    def __init__(self, iterable, id_fn, meta_fn, body_fn, pipeline_meta=None):
        self.source = iter(iterable)
        self.id_fn = id_fn
        self.meta_fn = meta_fn
        self.body_fn = body_fn
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

    def map(self, mapper_func) -> "StreamPipeline":
        """1. Операция Модификации."""
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
            pipeline_meta=self.pipeline_meta
        )

    def flat_map(self, expander) -> "StreamPipeline":
        """2. Операция Размножения/Вставки."""
        def expand_generator():
            for unit in self:
                local_counter = 0
                def next_id_factory():
                    nonlocal local_counter
                    local_counter += 1
                    return f"{unit.id}.{local_counter}"

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
            pipeline_meta=self.pipeline_meta
        )

    def materialize(self) -> "StreamPipeline":
        """Замораживает ленивый источник в плоскую хэш-карту."""
        units_list = list(self)
        registry_map = {u.id: u for u in units_list}
        return StreamPipeline(
            units_list,
            id_fn=lambda u: u.id,
            meta_fn=lambda u: u.meta,
            body_fn=lambda u: u.body,
            pipeline_meta={**self.pipeline_meta, "registry_map": registry_map}
        )

    def route(self, router) -> "StreamPipeline":
        """3. Операция Смены маршрута."""
        registry = self.pipeline_meta.get("registry_map", {})

        def route_generator():
            if not registry:
                return
            router.initialize(self)
            current_id = next(iter(registry.keys()))
            counter = 0

            while current_id is not None and counter < 1000:
                counter += 1
                unit = registry.get(current_id)
                if not unit:
                    break

                cloned = copy.deepcopy(unit)
                yield cloned

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

    def save(self, store_instance, formatter_func) -> "StreamPipeline":
        processed_rows = []
        for unit in self:
            row_dict = formatter_func(unit)
            if row_dict is not None:
                processed_rows.append(row_dict)
        store_instance.export(processed_rows)
        return self

