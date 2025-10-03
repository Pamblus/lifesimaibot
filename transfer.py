import re
from api import call_ai
from prompt import load_user_data, save_user_data, get_inventory_count
from datetime import datetime

# Словарь ожидающих передач
pending_transfers = {}

def parse_transfer_command(text):
    """Парсит команду передачи через ИИ"""
    system_prompt = """
Ты парсер команд передачи в игре. Игроки могут передавать деньги и предметы друг другу.

ФОРМАТ ОТВЕТА:
<money=СУММА>
<items=ПРЕДМЕТ1:КОЛИЧЕСТВО,ПРЕДМЕТ2:КОЛИЧЕСТВО>
<receiver_id=ID_ПОЛУЧАТЕЛЯ>
<message=СООБЩЕНИЕ>

ПРИМЕРЫ:

Игрок: "хочу передать 100$ и яблоко игроку 123456 с сообщением привет"
Ты:
<money=100>
<items=яблоко:1>
<receiver_id=123456>
<message=привет>

Игрок: "кину другану 50$ вот его айди 399292 и так же передаю мои штаны"
Ты:
<money=50>
<items=штаны:1>
<receiver_id=399292>
<message=>

Игрок: "передать хлеб и воду игроку 555555"
Ты:
<money=0>
<items=хлеб:1,вода:1>
<receiver_id=555555>
<message=>

Если не можешь распарсить - верни пустые значения.
"""
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": text}
    ]
    
    from api import call_ai
    response = call_ai(messages)
    
    # Парсим ответ
    money_match = re.search(r'<money=(\d+)>', response)
    items_match = re.search(r'<items=([^>]+)>', response)
    receiver_match = re.search(r'<receiver_id=(\d+)>', response)
    message_match = re.search(r'<message=([^>]*)>', response)
    
    money = int(money_match.group(1)) if money_match else 0
    receiver_id = int(receiver_match.group(1)) if receiver_match else None
    message = message_match.group(1) if message_match else ""
    
    items = {}
    if items_match:
        items_str = items_match.group(1)
        if items_str.strip():
            for item_part in items_str.split(','):
                if ':' in item_part:
                    item_name, quantity = item_part.split(':', 1)
                    items[item_name.strip()] = int(quantity)
    
    return money, items, receiver_id, message

def validate_transfer(sender_id, receiver_id, money, items):
    """Проверяет возможность передачи через ИИ"""
    sender_data = load_user_data(sender_id)
    receiver_data = load_user_data(receiver_id)
    
    system_prompt = f"""
Проверь возможность передачи между игроками:

ОТПРАВИТЕЛЬ (ID: {sender_id}):
- Баланс: {sender_data['balance']}$
- Инвентарь: {sender_data['inventory']}

ПОЛУЧАТЕЛЬ (ID: {receiver_id}):
- Баланс: {receiver_data['balance']}$
- Инвентарь: {receiver_data['inventory']}
- Количество предметов: {get_inventory_count(receiver_data['inventory'])}/20

ПЕРЕДАЧА:
- Деньги: {money}$
- Предметы: {items}

Максимум предметов у получателя: 20

ФОРМАТ ОТВЕТА:
<valid=true/false>
<reason=ПРИЧИНА>

Если передача возможна - valid=true, иначе valid=false с причиной.
"""
    
    messages = [{"role": "system", "content": system_prompt}]
    
    from api import call_ai
    response = call_ai(messages)
    
    valid_match = re.search(r'<valid=(true|false)>', response)
    reason_match = re.search(r'<reason=([^>]+)>', response)
    
    is_valid = valid_match.group(1) == "true" if valid_match else False
    reason = reason_match.group(1) if reason_match else "Неизвестная ошибка"
    
    return is_valid, reason

def create_transfer(sender_id, receiver_id, money, items, message):
    """Создает запрос на передачу"""
    # Проверяем получателя
    receiver_data = load_user_data(receiver_id)
    if "user_id" not in receiver_data:
        return False, "❌ Игрок не найден"
    
    # Проверяем через ИИ
    is_valid, reason = validate_transfer(sender_id, receiver_id, money, items)
    if not is_valid:
        return False, f"❌ {reason}"
    
    # Создаем передачу
    transfer_id = f"{sender_id}_{receiver_id}_{datetime.now().timestamp()}"
    
    transfer_data = {
        "sender_id": sender_id,
        "sender_name": load_user_data(sender_id).get("first_name", "Неизвестный"),
        "receiver_id": receiver_id,
        "money": money,
        "items": items,
        "message": message,
        "timestamp": datetime.now().isoformat()
    }
    
    pending_transfers[transfer_id] = transfer_data
    return True, transfer_id

def execute_transfer(transfer_id):
    """Выполняет подтвержденную передачу"""
    if transfer_id not in pending_transfers:
        return False
    
    transfer = pending_transfers[transfer_id]
    sender_data = load_user_data(transfer["sender_id"])
    receiver_data = load_user_data(transfer["receiver_id"])
    
    # Передаем деньги
    sender_data["balance"] -= transfer["money"]
    receiver_data["balance"] += transfer["money"]
    
    # Передаем предметы
    for item, quantity in transfer["items"].items():
        sender_data["inventory"][item] = sender_data["inventory"].get(item, 0) - quantity
        if sender_data["inventory"][item] <= 0:
            del sender_data["inventory"][item]
        
        receiver_data["inventory"][item] = receiver_data["inventory"].get(item, 0) + quantity
    
    # Сохраняем историю
    sender_data["history"].append({
        "type": "transfer_sent",
        "to": transfer["receiver_id"],
        "money": transfer["money"],
        "items": transfer["items"],
        "message": transfer["message"],
        "timestamp": datetime.now().isoformat()
    })
    
    receiver_data["history"].append({
        "type": "transfer_received", 
        "from": transfer["sender_id"],
        "money": transfer["money"],
        "items": transfer["items"],
        "message": transfer["message"],
        "timestamp": datetime.now().isoformat()
    })
    
    save_user_data(sender_data)
    save_user_data(receiver_data)
    
    del pending_transfers[transfer_id]
    return True

def get_transfer_info(transfer_id):
    """Возвращает информацию о передаче"""
    return pending_transfers.get(transfer_id)
