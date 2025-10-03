import asyncio
import threading
from collections import deque
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

from config import TELEGRAM_TOKEN
from prompt import load_user_data, process_user_action, get_inventory_count
from transfer import parse_transfer_command, create_transfer, execute_transfer, pending_transfers
from datetime import datetime
import os
import json
# Очередь для обработки запросов
request_queue = deque()
processing_lock = threading.Lock()

# Создаем папку users
os.makedirs("users", exist_ok=True)

async def process_queue():
    """Обрабатывает очередь запросов"""
    while True:
        if request_queue:
            with processing_lock:
                if request_queue:
                    update, context, user_input, user_data = request_queue.popleft()
                    
                    processing_msg = await update.message.reply_text("🤔 Думаю над вашим предложением...")
                    
                    # Обрабатываем действие через ИИ
                    response_text = process_user_action(user_input, user_data)
                    
                    await processing_msg.delete()
                    await update.message.reply_text(response_text)
        
        await asyncio.sleep(1)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    user = update.effective_user
    user_data = load_user_data(user.id, user.username, user.first_name)
    
    welcome_text = f"""
🎮 ИГРА О ЖИЗНИ

Привет, {user.first_name}! 
💰 Баланс: {user_data['balance']}$ 

📊 Команды:
/start - начать
/profile - мой профиль
/profile ID - профиль игрока
/balance - баланс  
/inventory - инвентарь
/top - топ игроков

💬 Можно передавать предметы и деньги другим игрокам!
Пример: "передать 100$ и яблоко игроку 123456 с сообщением привет"
    """
    
    await update.message.reply_text(welcome_text)

async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /profile"""
    user = update.effective_user
    
    if context.args:
        try:
            target_id = int(context.args[0])
            user_data = load_user_data(target_id)
            if "user_id" not in user_data:
                await update.message.reply_text("❌ Игрок не найден")
                return
        except ValueError:
            await update.message.reply_text("❌ Неверный ID игрока")
            return
    else:
        user_data = load_user_data(user.id)
    
    profile_text = f"""
👤 ПРОФИЛЬ ИГРОКА

ID: {user_data['user_id']}
Имя: {user_data.get('first_name', 'Неизвестно')}
Юзернейм: @{user_data.get('username', 'нет')}
💰 Баланс: {user_data['balance']}$
🎒 Предметов: {get_inventory_count(user_data['inventory'])}/20

📅 Зарегистрирован: {datetime.fromisoformat(user_data['registered_date']).strftime('%d.%m.%Y')}
    """
    
    if user_data["inventory"]:
        profile_text += "\n🎒 ИНВЕНТАРЬ:\n"
        for item, quantity in user_data["inventory"].items():
            profile_text += f"• {item}: {quantity} шт.\n"
    
    await update.message.reply_text(profile_text)

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /balance"""
    user = update.effective_user
    user_data = load_user_data(user.id)
    
    await update.message.reply_text(f"💰 Ваш баланс: {user_data['balance']}$")

async def inventory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /inventory"""
    user = update.effective_user
    user_data = load_user_data(user.id)
    
    if user_data["inventory"]:
        inventory_text = f"🎒 ВАШ ИНВЕНТАРЬ ({get_inventory_count(user_data['inventory'])}/20):\n"
        for item, quantity in user_data["inventory"].items():
            inventory_text += f"• {item}: {quantity} шт.\n"
    else:
        inventory_text = "🎒 Ваш инвентарь пуст"
    
    await update.message.reply_text(inventory_text)

async def top_players(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /top"""
    all_users = []
    for filename in os.listdir("users"):
        if filename.endswith('.json'):
            user_file = os.path.join("users", filename)
            with open(user_file, 'r', encoding='utf-8') as f:
                user_data = json.load(f)
                all_users.append(user_data)
    
    all_users.sort(key=lambda x: x['balance'], reverse=True)
    
    top_text = "🏆 ТОП-15 ИГРОКОВ 🏆\n\n"
    
    for i, user in enumerate(all_users[:15], 1):
        username = user.get('username', '')
        first_name = user.get('first_name', '')
        display_name = f"@{username}" if username else first_name
        
        medal = ""
        if i == 1: medal = "🥇"
        elif i == 2: medal = "🥈" 
        elif i == 3: medal = "🥉"
        
        top_text += f"{medal}{i}. {display_name}: {user['balance']}$ (ID: {user['user_id']})\n"
    
    if not all_users:
        top_text = "📊 Пока нет игроков в рейтинге!"
    
    await update.message.reply_text(top_text)

async def handle_transfer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик передачи"""
    user = update.effective_user
    text = update.message.text
    
    # Парсим команду через ИИ
    money, items, receiver_id, message = parse_transfer_command(text)
    
    if not receiver_id:
        await update.message.reply_text("❌ Не удалось распознать команду передачи. Пример: 'передать 100$ и яблоко игроку 123456 с сообщением привет'")
        return
    
    # Создаем передачу
    success, result = create_transfer(user.id, receiver_id, money, items, message)
    
    if success:
        transfer_id = result
        keyboard = [
            [
                InlineKeyboardButton("✅ Принять", callback_data=f"accept_{transfer_id}"),
                InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{transfer_id}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        transfer_info = f"💸 НОВАЯ ПЕРЕДАЧА\n\n"
        transfer_info += f"От: {user.first_name} (ID: {user.id})\n"
        if money > 0:
            transfer_info += f"💰 Деньги: {money}$\n"
        if items:
            transfer_info += f"🎒 Предметы: {', '.join([f'{k} ({v} шт.)' for k, v in items.items()])}\n"
        if message:
            transfer_info += f"💬 Сообщение: {message}\n"
        
        try:
            await context.bot.send_message(
                chat_id=receiver_id,
                text=transfer_info,
                reply_markup=reply_markup
            )
            await update.message.reply_text("✅ Запрос на передачу отправлен!")
        except:
            await update.message.reply_text("❌ Не удалось отправить запрос. Возможно, игрок не начал диалог с ботом.")
    else:
        await update.message.reply_text(result)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик кнопок"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = query.from_user.id
    
    if data.startswith('accept_'):
        transfer_id = data.replace('accept_', '')
        transfer = pending_transfers.get(transfer_id)
        
        if transfer and transfer["receiver_id"] == user_id:
            success = execute_transfer(transfer_id)
            if success:
                await query.edit_message_text("✅ Передача принята!")
                
                # Уведомляем отправителя
                try:
                    sender_msg = f"✅ Игрок (ID: {user_id}) принял вашу передачу!"
                    if transfer.get("money", 0) > 0:
                        sender_msg += f"\n💰 Передано: {transfer['money']}$"
                    if transfer.get("items"):
                        sender_msg += f"\n🎒 Предметы: {', '.join(transfer['items'].keys())}"
                    await context.bot.send_message(chat_id=transfer["sender_id"], text=sender_msg)
                except:
                    pass
            else:
                await query.edit_message_text("❌ Ошибка при выполнении передачи")
        else:
            await query.edit_message_text("❌ Передача не найдена")
    
    elif data.startswith('reject_'):
        transfer_id = data.replace('reject_', '')
        transfer = pending_transfers.get(transfer_id)
        
        if transfer and transfer["receiver_id"] == user_id:
            del pending_transfers[transfer_id]
            await query.edit_message_text("❌ Передача отклонена")
            
            # Уведомляем отправителя
            try:
                await context.bot.send_message(
                    chat_id=transfer["sender_id"], 
                    text=f"❌ Игрок (ID: {user_id}) отклонил вашу передачу"
                )
            except:
                pass

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик сообщений"""
    user = update.effective_user
    user_input = update.message.text.strip()
    
    # Проверяем是否是 команда передачи
    if any(word in user_input.lower() for word in ['передать', 'кинуть', 'отдать', 'дать']):
        await handle_transfer(update, context)
        return
    
    user_data = load_user_data(user.id, user.username, user.first_name)
    
    request_queue.append((update, context, user_input, user_data))
    await update.message.reply_text("⏳ Ваш запрос добавлен в очередь...")

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ошибок"""
    print(f"Ошибка: {context.error}")
    if update and update.message:
        await update.message.reply_text("⚠️ Произошла ошибка. Попробуйте позже.")

def main():
    """Запуск бота"""
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Регистрируем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("profile", profile))
    application.add_handler(CommandHandler("balance", balance))
    application.add_handler(CommandHandler("inventory", inventory))
    application.add_handler(CommandHandler("top", top_players))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    application.add_error_handler(error_handler)
    
    # Запускаем обработку очереди
    loop = asyncio.get_event_loop()
    loop.create_task(process_queue())
    
    print("Бот запущен...")
    application.run_polling()

if __name__ == "__main__":
    main()
