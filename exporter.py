class ConsoleExporter:
    """Глупый отладочный логгер: просто печатает сырые данные как есть."""

    def __init__(self, title="СЫРОЙ СРЕЗ ДАННЫХ"):
        self.title = title

    def export(self, rows):
        """Просто выводит элементы в принт для визуального анализа."""
        if not rows:
            print(f"\n[{self.title}] Список пуст.")
            return

        print("\n" + "=" * 60 + f"\n[{self.title}]\n" + "=" * 60)
        
        for pos, row in enumerate(rows):
            # Честно выводим сырой принт объекта, переданного из main.py
            print(f"[{pos}] {repr(row)}")
            print("-" * 60)


import sqlite3


class SQLiteStore:
    """Динамическое хранилище SQLite.

    Семо создает таблицу и колонки на основе переданной структуры словаря.
    """

    def __init__(self, db_path, table_name="data_flow"):
        self.db_path = db_path
        self.table_name = table_name

    def export(self, rows):
        """Принимает список отформатированных словарей и сбрасывает в БД."""
        if not rows:
            return

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # ДИНАМИКА: Извлекаем названия колонок из ключей самого первого элемента
        fields = list(rows[0].keys())
        cursor.execute(f"DROP TABLE IF EXISTS {self.table_name}")

        # Генерируем типы полей (все поля по умолчанию делаем текстовыми TEXT)
        col_definitions = [f"{field} TEXT" for field in fields]
        create_query = f"""
            CREATE TABLE IF NOT EXISTS {self.table_name} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                {", ".join(col_definitions)}
            )
        """
        cursor.execute(create_query)
        
        # Очищаем старые данные перед новой записью в эту таблицу
        cursor.execute(f"DELETE FROM {self.table_name}")

        # Автоматически собираем строку инсерта под любое количество колонок
        placeholders = ", ".join(["?"] * len(fields))
        insert_query = f"""
            INSERT INTO {self.table_name} ({", ".join(fields)}) 
            VALUES ({placeholders})
        """

        # Вытаскиваем значения по динамическому списку полей и пишем в базу
        for r in rows:
            values = [str(r[field]) for field in fields]
            cursor.execute(insert_query, values)

        conn.commit()
        conn.close()


class ExportDispatcher:

    def __init__(self, exporters, filter_func):
        self.exporters = exporters
        self.filter_func = filter_func

    def process_ast(self, flat_body):
        processed_rows = []
        for stmt in flat_body:
            row_data = self.filter_func(stmt)
            if row_data is not None:
                processed_rows.append(row_data)

        for exporter in self.exporters:
            exporter.export(processed_rows)

