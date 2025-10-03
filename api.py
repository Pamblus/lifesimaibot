import requests
import json
from config import API_KEY

def call_ai(messages, model="openai/gpt-3.5-turbo"):
    """Вызов API ИИ"""
    try:
        response = requests.post(
            url="https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {API_KEY}",
                "Content-Type": "application/json"
            },
            data=json.dumps({
                "model": model,
                "messages": messages
            }),
            timeout=30
        )
        
        if response.status_code == 200:
            try:
                result = response.json()
                return result['choices'][0]['message']['content']
            except json.JSONDecodeError:
                return "Ошибка: неверный ответ от API"
        else:
            return f"Ошибка API: {response.status_code} - {response.text}"
            
    except Exception as e:
        return f"Ошибка соединения: {str(e)}"
