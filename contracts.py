from dataclasses import dataclass, field
from typing import Any


@dataclass
class FlowUnit:
    """Атомарная единица потока данных проекта.

    Контейнер, не зависящий от конкретного языка (AST/JSON/Logs).
    """

    id: Any  # Уникальный идентификатор (число, кортеж или строка)
    meta: dict = field(default_factory=dict)
    body: Any = None  # Полезная нагрузка (узел AST или любая другая сущность)


class FlowMapper:
    """Интерфейс для операции .map() (Модификация)."""

    def modify(self, unit: FlowUnit) -> None:
        raise NotImplementedError


class FlowFilter:
    """Интерфейс для операции .filter() (Фильтрация)."""

    def predicate(self, unit: FlowUnit) -> bool:
        raise NotImplementedError


class FlowRouter:
    """Интерфейс для операции .route() (Смена маршрута)."""

    def get_next_id(self, unit: FlowUnit) -> Any:
        """Возвращает ID следующего элемента по умолчанию (линейный ход)."""
        raise NotImplementedError

    def get_jump_id(self, unit: FlowUnit) -> Any:
        """Возвращает ID элемента для прыжка (вызов функции), иначе None."""
        raise NotImplementedError

    def is_return(self, unit: FlowUnit) -> bool:
        """Возвращает True, если это маркер выхода из блока/функции."""
        raise NotImplementedError


class FlowExpander:
    """Интерфейс для операции .flat_map() (Размножение/Вставка)."""
    def expand(self, unit, id_generator, pipeline):
        """Возвращает список новых FlowUnit, вставляемых вместо текущего."""
        raise NotImplementedError

