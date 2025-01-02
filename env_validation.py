from typing import NamedTuple, List
from dotenv import load_dotenv
import os

class EnvConfig(NamedTuple):
    telegram_token: str
    openai_api_key: str
    message_limit: int
    db_path: str = 'chatzzipper.db'
    allowed_chat_ids: List[int] = []

def validate_env() -> EnvConfig:
    load_dotenv()
    
    telegram_token = os.getenv('TELEGRAM_BOT_TOKEN')
    if not telegram_token:
        raise ValueError("TELEGRAM_BOT_TOKEN is required")
        
    openai_api_key = os.getenv('OPENAI_API_KEY')
    if not openai_api_key:
        raise ValueError("OPENAI_API_KEY is required")
    
    try:
        message_limit = int(os.getenv('MESSAGE_LIMIT', '75'))
        if message_limit <= 0:
            raise ValueError("MESSAGE_LIMIT must be positive")
    except ValueError:
        raise ValueError("MESSAGE_LIMIT must be a valid integer")
    
    allowed_chat_ids_str = os.getenv('ALLOWED_CHAT_IDS', '')
    allowed_chat_ids = [int(id.strip()) for id in allowed_chat_ids_str.split(',')] if allowed_chat_ids_str else []
    
    return EnvConfig(
        telegram_token=telegram_token,
        openai_api_key=openai_api_key,
        message_limit=message_limit,
        allowed_chat_ids=allowed_chat_ids
    )