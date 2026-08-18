# tests/data_processor.py
import asyncio

class DataValidator:
    def validate_age(self, age: int) -> bool:
        return age < 18

def format_name_recursive(name) -> str:
    if isinstance(name, (list, tuple)):
        return format_name_recursive(name[0])
    return name.strip().capitalize()

def make_adder(x):
    # Внутренняя функция-модификатор
    def adder(y):
        return x + y
    return adder

# Использование фабрики
add_five = make_adder(5)
result = add_five(10) # Ожидаем 15


async def process_user_data(raw_name, age: int) -> list:
    if DataValidator.validate_age(age):
        status = "minor"
    else:
        status = "adult"
        
    await asyncio.sleep(0.1)
    
    result_list = []
    
    clean_name = format_name_recursive(raw_name)
    result_list.append(clean_name)
    result_list.append(status)
    
    add_five = make_adder(5)
    result = add_five(10) 
    result_list.append(result)

    return result_list, [0, 1]

