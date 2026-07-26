import asyncio
import sys
import os
from data_processor import process_user_data

class User:
    def __init__(self, name, age):
        self.name = name
        self.age = age

async def main():
    # Проверяем работу с классами и атрибутами
    u = User("lex_botcraft", 25)
    input_name = u.name
    input_age = u.age

    print(f"-> Запуск обработки для {input_name}...")
    
    # Проверяем устойчивость к исключениям
    try:
        final_profile = await process_user_data(input_name, input_age)
        print(f"-> Результат обработки: {final_profile}")
    except Exception as e:
        print(f"[ОШИБКА] Перехвачено исключение: {e}")

if __name__ == '__main__':
    try:
        asyncio.run(main())
    finally:
        print('\n[Unbraid] Трассировка успешно завершена. Данные в data_flow.db')

