import sqlite3
import os

class UnbraidDB:
    def __init__(self, db_path="data_flow.db"):
        self.db_path = db_path
        self.conn = None
        self.cursor = None

    def connect(self):
        """Подключается к базе данных и создает таблицу, если её нет."""
        self.conn = sqlite3.connect(self.db_path)
        self.cursor = self.conn.cursor()
        self._create_table()

    def _create_table(self):
        """Создает объединенную таблицу узлов и потоков."""
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS data_nodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stream_id INTEGER NOT NULL,
                variable_name TEXT NOT NULL,
                predecessor_ids TEXT,          -- Прямые зависимости (справа от '=')
                control_dependencies TEXT,     -- Зависимости по управлению (из условий IF)
                execution_context TEXT NOT NULL, -- Стек вызовов через двоеточие (main:process)
                notes TEXT
            );
        """)
        self.conn.commit()

    def insert_node(self, stream_id, var_name, predecessors, controls, context, notes=""):
        """Вставляет новый узел данных в граф."""
        # Превращаем списки ID в строки через запятую для SQLite
        preds_str = ",".join(map(str, predecessors)) if predecessors else None
        ctrls_str = ",".join(map(str, controls)) if controls else None
        
        self.cursor.execute("""
            INSERT INTO data_nodes 
            (stream_id, variable_name, predecessor_ids, control_dependencies, execution_context, notes)
            VALUES (?, ?, ?, ?, ?, ?);
        """, (stream_id, var_name, preds_str, ctrls_str, context, notes))
        self.conn.commit()
        return self.cursor.lastrowid

    def find_last_node_id(self, var_name, context):
        """Ищет последний ID узла для переменной, чтобы связать её как предшественника."""
        self.cursor.execute("""
            SELECT id FROM data_nodes 
            WHERE variable_name = ? AND (execution_context = ? OR ? LIKE execution_context || '%')
            ORDER BY id DESC LIMIT 1;
        """, (var_name, context, context))
        row = self.cursor.fetchone()
        return row[0] if row else None

    def close(self):
        if self.conn:
            self.conn.close()

