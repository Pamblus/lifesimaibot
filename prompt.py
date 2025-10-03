import re
import os
import json
from datetime import datetime
from api import call_ai
from config import USERS_DIR

def load_prompt():
    """Загружает промпт из файла"""
    try:
        with open("prompt.txt", 'r', encoding='utf-8') as f:
            return f.read()
    except:
        return "Ты ведущий игры о жизни. Игрок начинает с 1000$ и пустым инвентарем."

def parse_ai_response(response):
    """Парсит ответ AI"""
    if not response or "Ошибка" in response:
        return {
            'response': response or "Произошла ошибка",
            'balance': None,
            'inventory': {},
            'raw': response
        }
    
    # Ищем баланс
    balance_match = re.search(r'<balance=([+-]?\d+)>', response)
    new_balance = int(balance_match.group(1)) if balance_match else None
    
    # Ищем инвентарь
    inventory_updates = {}
    inventory_matches = re.findall(r'<inventory:([^=]+)=([+-]?\d+)>', response)
    for item, quantity in inventory_matches:
        inventory_updates[item.strip()] = int(quantity)
    
    # Ищем основной ответ
    clean_response = re.sub(r'<[^>]+>', '', response).strip()
    
    return {
        'response': clean_response or "Не удалось обработать ответ",
        'balance': new_balance,
        'inventory': inventory_updates,
        'raw': response
    }

def get_user_file(user_id):
    """Возвращает путь к файлу пользователя"""
    return os.path.join(USERS_DIR, f"{user_id}.json")

def load_user_data(user_id, username="", first_name=""):
    """Загружает данные пользователя"""
    user_file = get_user_file(user_id)
    
    try:
        if os.path.exists(user_file):
            with open(user_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Проверяем обязательные поля
                if "message_history" not in data:
                    data["message_history"] = []
                if "inventory" not in data:
                    data["inventory"] = {}
                return data
    except json.JSONDecodeError:
        print(f"Ошибка чтения файла пользователя {user_id}, создаем новый")
    
    # Создаем нового пользователя
    user_data = {
        "user_id": user_id,
        "username": username or "",
        "first_name": first_name or "",
        "balance": 1000,
        "inventory": {},
        "message_history": [],
        "registered_date": datetime.now().isoformat(),
        "history": []
    }
    save_user_data(user_data)
    return user_data

def save_user_data(user_data):
    """Сохраняет данные пользователя"""
    try:
        user_file = get_user_file(user_data["user_id"])
        with open(user_file, 'w', encoding='utf-8') as f:
            json.dump(user_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Ошибка сохранения пользователя {user_data['user_id']}: {e}")

def update_message_history(user_data, message, role="user"):
    """Обновляет историю сообщений"""
    user_data["message_history"].append({
        "role": role,
        "content": message,
        "timestamp": datetime.now().isoformat()
    })
    user_data["message_history"] = user_data["message_history"][-5:]
    save_user_data(user_data)

def get_inventory_count(inventory):
    """Возвращает количество предметов"""
    return sum(inventory.values())

def process_user_action(user_input, user_data):
    """Обрабатывает действие пользователя через ИИ"""
    try:
        system_prompt = load_prompt()
        system_prompt += f"\n\nТЕКУЩАЯ ИНФОРМАЦИЯ:\nБаланс: {user_data['balance']}$\n"
        
        if user_data["inventory"]:
            system_prompt += "Инвентарь:\n"
            for item, quantity in user_data["inventory"].items():
                system_prompt += f"- {item}: {quantity} шт.\n"
        else:
            system_prompt += "Инвентарь: пусто\n"
        
        system_prompt += f"Количество предметов: {get_inventory_count(user_data['inventory'])}/20\n"
        
        # Добавляем историю сообщений
        if user_data["message_history"]:
            system_prompt += "\nПОСЛЕДНИЕ ДЕЙСТВИЯ ИГРОКА:\n"
            for msg in user_data["message_history"][-3:]:
                system_prompt += f"- {msg['content']}\n"
        
        messages = [{"role": "system", "content": system_prompt}]
        
        # Добавляем историю в контекст
        for msg in user_data["message_history"]:
            messages.append({"role": msg["role"], "content": msg["content"]})
        
        messages.append({"role": "user", "content": user_input})
        
        # Вызываем ИИ
        ai_response = call_ai(messages)
        parsed = parse_ai_response(ai_response)
        
        # Обновляем баланс
        balance_changed = False
        old_balance = user_data["balance"]
        if parsed['balance'] is not None:
            user_data["balance"] = parsed['balance']
            change = user_data["balance"] - old_balance
            balance_changed = True
        
        # Обновляем инвентарь
        inventory_changed = False
        inventory_updates = []
        
        for item, quantity_change in parsed['inventory'].items():
            current_qty = user_data["inventory"].get(item, 0)
            new_qty = current_qty + quantity_change
            
            # Проверяем лимит инвентаря
            if new_qty > 0 and get_inventory_count(user_data["inventory"]) + quantity_change > 20:
                parsed['response'] += f"\n\n⚠️ Не хватает места в инвентаре! Максимум 20 предметов."
                continue
            
            if new_qty <= 0:
                if item in user_data["inventory"]:
                    del user_data["inventory"][item]
                    inventory_updates.append(f"🗑️ {item} удален")
            else:
                user_data["inventory"][item] = new_qty
                if quantity_change > 0:
                    inventory_updates.append(f"📦 {item}: +{quantity_change} (всего: {new_qty})")
                elif quantity_change < 0:
                    inventory_updates.append(f"📦 {item}: {quantity_change} (всего: {new_qty})")
            
            inventory_changed = True
        
        # Сохраняем изменения
        if balance_changed or inventory_changed:
            user_data["history"].append({
                "action": user_input,
                "old_balance": old_balance,
                "new_balance": user_data["balance"],
                "inventory_changes": parsed['inventory'],
                "timestamp": datetime.now().isoformat()
            })
        
        # Обновляем историю сообщений
        update_message_history(user_data, user_input, "user")
        update_message_history(user_data, parsed['response'], "assistant")
        
        save_user_data(user_data)
        
        # Формируем ответ
        response_text = f"📊 {parsed['response']}"
        
        if balance_changed:
            balance_info = f"\n\n💳 БАЛАНС: {old_balance}$ → {user_data['balance']}$ "
            if change > 0:
                balance_info += f"(+{change}$) 📈"
            elif change < 0:
                balance_info += f"({change}$) 📉"
            response_text += balance_info
        
        if inventory_updates:
            response_text += "\n\n🎒 ИНВЕНТАРЬ:\n" + "\n".join(inventory_updates)
        
        return response_text
        
    except Exception as e:
        return f"❌ Ошибка обработки: {str(e)}"
