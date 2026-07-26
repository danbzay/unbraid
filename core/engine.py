# unbraid/core/engine.py
from unbraid.strategies.flat import FlatTreeStrategy
from unbraid.strategies.iterator import IteratorStrategy

class AnalysisEngine:
    def __init__(self, config):
        self.config = config
        # Карта доступных стратегий прохода
        self.strategies = {
            "flat": FlatTreeStrategy,
            "iterator": IteratorStrategy
        }

    def run(self, root_ast):
        # Выбираем стратегию на основе конфига проекта
        strategy_name = self.config.get("strategy", "flat")
        strategy_class = self.strategies.get(strategy_name)
        
        if not strategy_class:
            raise ValueError(f"Неизвестная стратегия: {strategy_name}")
            
        # Запускаем выбранный вариант прохода
        analyzer = strategy_class(self.config)
        result = analyzer.execute(root_ast)
        return result

