# tests/data_processor.py
import asyncio

async def process_user_data(raw_name: str, age: int) -> list:
    # 1. Проверяем условие (Ветвление IF)
    if age < 18:
        status = "minor"
    else:
        status = "adult"
        
    # Имитируем асинхронную задержку (работа с циклом событий)
    await asyncio.sleep(0.1)
    
    # 2. Создаем и наполняем массив (Мутация данных)
    result_list = []
    result_list.append(raw_name.strip().capitalize())
    result_list.append(status)
    
    return result_list

