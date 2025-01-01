import re
import html
from typing import Optional

def sanitize_input(text: Optional[str]) -> str:
    if not text:
        return ""
    
    # Remove any SQL injection attempts
    text = re.sub(r'[\;\'\"\-\-]', '', text)
    
    # Escape HTML entities
    text = html.escape(text)
    
    # Remove control characters
    text = ''.join(char for char in text if ord(char) >= 32)
    
    # Limit message length
    return text[:4096]  # Telegram's message length limit

def sanitize_user_data(user_id: int, username: Optional[str], first_name: Optional[str]) -> tuple:
    username = sanitize_input(username)
    first_name = sanitize_input(first_name)
    
    # Ensure user_id is a positive integer
    if not isinstance(user_id, int) or user_id <= 0:
        raise ValueError("Invalid user ID")
        
    return user_id, username, first_name