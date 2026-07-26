#!/usr/bin/env bash

# Находим реальный путь к папке, где лежит сам инструмент unbraid
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Экспортируем путь к инструменту, чтобы Python видел свои модули,
# и добавляем текущую рабочую папку в PYTHONPATH для локальных импортов проекта
export PYTHONPATH="${SCRIPT_DIR}:${PYTHONPATH:-.}"

# Запускаем Python-скрипт и передаем ему все аргументы из консоли
python3 "${SCRIPT_DIR}/main.py" "$@"
