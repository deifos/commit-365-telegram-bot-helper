import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler
import sqlite3
from datetime import datetime, timedelta
from openai import AsyncOpenAI
from message_sanitization import sanitize_input, sanitize_user_data
from env_validation import validate_env
import asyncio

config  = validate_env()
client = AsyncOpenAI(api_key=config.openai_api_key)
MESSAGE_LIMIT = config.message_limit

async def generate_summary(messages: list) -> str:
    try:
        messages_text = "\n".join(messages)
        response = await client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "Summarize these chat messages concisely:"},
                {"role": "user", "content": messages_text}
            ]
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"Error generating summary: {e}")
        return "Sorry, I couldn't generate a summary at this time."

# Set up logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize the database
def init_db():
    print("Initializing database...")
    try:
        conn = sqlite3.connect('chatzzipper.db')
        cursor = conn.cursor()
        # Create users table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_seen TIMESTAMP,
                last_message_id INTEGER,
                last_summary_timestamp TIMESTAMP
            )
        ''')
        # Create messages table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                message_id INTEGER PRIMARY KEY,
                chat_id INTEGER,
                user_id INTEGER,
                username TEXT,
                first_name TEXT,
                text TEXT,
                timestamp TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        ''')
        
        conn.commit()
        conn.close()
        print("Database initialized successfully.")
    except Exception as e:
        print(f"Error initializing database: {e}")

# Update user activity in the database
def update_user_activity(user_id: int, last_seen: datetime, last_message_id: int, summary_timestamp: datetime = None):
    try:
        conn = sqlite3.connect('chatzzipper.db')
        cursor = conn.cursor()
        if summary_timestamp:
            cursor.execute('''
                INSERT OR REPLACE INTO users (user_id, last_seen, last_message_id, last_summary_timestamp)
                VALUES (?, ?, ?, ?)
            ''', (user_id, last_seen, last_message_id, summary_timestamp))
        else:
            cursor.execute('''
                INSERT OR REPLACE INTO users (user_id, last_seen, last_message_id)
                VALUES (?, ?, ?)
            ''', (user_id, last_seen, last_message_id))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error updating user activity: {e}")

async def delete_message_later(message, delay_seconds=10):
    """Delete a message after specified delay"""
    await asyncio.sleep(delay_seconds)
    try:
        await message.delete()
    except Exception as e:
        print(f"Error deleting message: {e}")

async def chatzip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    
    # Only allow command in authorized chats
    if chat_id not in config.allowed_chat_ids:
        reply = await update.message.reply_text("This bot is only available in specific group chats.")
        await delete_message_later(reply)
        return
    
    user_id = update.message.from_user.id
    last_seen = get_user_last_seen(user_id)
    unread_messages = fetch_unread_messages(user_id, last_seen)
    
    if len(unread_messages) > MESSAGE_LIMIT:
        # The ask_for_summary function should be modified to return the sent message
        reply = await ask_for_summary(update, context)
        await delete_message_later(reply)
    else:
        reply = await update.message.reply_text(f"You have {len(unread_messages)} unread messages - you're all caught up! 👍")
        await delete_message_later(reply)


def get_last_summary_timestamp(user_id: int) -> datetime:
    try:
        conn = sqlite3.connect('chatzzipper.db')
        cursor = conn.cursor()
        cursor.execute('SELECT last_summary_timestamp FROM users WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        conn.close()
        
        if result and result[0]:
            return datetime.fromisoformat(result[0])
        return None
    except Exception as e:
        print(f"Error getting user's last summary timestamp: {e}")
        return None

# Store a message in the database
def store_message(chat_id: int, user_id: int, message_id: int, text: str, timestamp: datetime, username: str, first_name: str):
    try:
        conn = sqlite3.connect('chatzzipper.db')
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO messages (message_id, chat_id, user_id, username, first_name, text, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (message_id, chat_id, user_id, username, first_name, text, timestamp))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error storing message: {e}")

# Fetch unread messages since the user's last seen timestamp
def fetch_unread_messages(user_id: int, since_timestamp: datetime) -> list:
    try:
        conn = sqlite3.connect('chatzzipper.db')
        cursor = conn.cursor()
        
        # Debug prints
        print(f"Fetching messages for user_id: {user_id}")
        print(f"Last seen timestamp: {since_timestamp}")
        
        # First check if messages exist
        cursor.execute('SELECT COUNT(*) FROM messages')
        total_messages = cursor.fetchone()[0]
        print(f"Total messages in database: {total_messages}")
        
        cursor.execute('''
            SELECT username, first_name, text, timestamp 
            FROM messages 
            WHERE timestamp > ? AND chat_id IN (
                SELECT DISTINCT chat_id 
                FROM messages
            )
            ORDER BY timestamp ASC
        ''', (since_timestamp,))
        
        messages = [f"[{row[3]}] {row[1] or row[0]}: {row[2]}" for row in cursor.fetchall()]
        conn.close()
        print(messages)
        print(f"Found {len(messages)} messages total")
        return messages
    except Exception as e:
        print(f"Error fetching unread messages: {e}")
        return []

# Ask the user if they want a summary
async def ask_for_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user_name = update.message.from_user.first_name or update.message.from_user.username
    chat_id = update.message.chat_id
    last_summary = get_last_summary_timestamp(user_id)
    
    # If user has received a summary recently, check if there are enough new messages
    if last_summary:
        new_messages = fetch_unread_messages(user_id, last_summary)
        if len(new_messages) < MESSAGE_LIMIT:
            reply = await context.bot.send_message(
                chat_id=user_id,
                text="You're already caught up! I'll notify you when there are more new messages to summarize."
            )
            if chat_id != user_id:  # Only auto-delete in group chats
                await delete_message_later(reply)
            return reply

    # Send notification in group chat
    if chat_id != user_id:  # Check if we're in a group chat
        reply = await update.message.reply_text(
            f"Hey @{user_name}, I've sent you a private message about summarizing the unread messages. Please check your DMs! -This message will self-destruct in 10 seconds. do you feel like Tom Cruise now?🤣🤣🤣"
        )
        await delete_message_later(reply)

    # Send the actual summary request in private
    keyboard = [
        [InlineKeyboardButton("Yes", callback_data="summary_yes")],
        [InlineKeyboardButton("No", callback_data="summary_no")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_message(
        chat_id=user_id,
        text=f"You have more than {MESSAGE_LIMIT} unread messages. Would you like a summary?",
        reply_markup=reply_markup
    )

# Handle callback queries (Yes/No buttons)
async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    await query.answer()

    if query.data == "summary_yes":
        user_id = query.from_user.id
        # last_seen = get_user_last_seen(user_id)
        last_summary = get_last_summary_timestamp(user_id) or datetime.now() - timedelta(days=1)
        messages = fetch_unread_messages(user_id, last_summary)
        if len(messages) >= MESSAGE_LIMIT:
            summary = await generate_summary(messages)
            current_time = datetime.now()
            update_user_activity(user_id, current_time, query.message.message_id, current_time)
            # await query.edit_message_text(f"Here's your summary:\n\n{summary}")
            reply = await context.bot.send_message(
                chat_id=user_id,
                text=f"Here's your summary:\n\n{summary}"
            )
            if chat_id != user_id:  # Only auto-delete in group chats
                await delete_message_later(reply)
        else:
            reply = await context.bot.send_message(
                chat_id=user_id,
                text="You're already caught up! I'll notify you when there are more new messages to summarize."
            )
            if chat_id != user_id:  # Only auto-delete in group chats
                await delete_message_later(reply)
    elif query.data == "summary_no":
        reply = await context.bot.send_message(
            chat_id=user_id,
            text="Okay, let me know if you change your mind!"
        )
        if chat_id != user_id:  # Only auto-delete in group chats
            await delete_message_later(reply)
    # To clean up a little delete the original message with buttons
    await query.message.delete()
    
# Start command handler
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("Start command received.")
    chat_id = update.message.chat_id
    reply = await update.message.reply_text(
        f"👋 Hi! I'm your friendly commit365-Bot-helper. Right now the only thing I can do is help you catch up on group chats by summarizing unread messages. "
        f"You can summon me by calling /start or /chatzip to sumarize your unread chats, also I'll notify you when you have more than {MESSAGE_LIMIT} unread messages in case you want a summary! feel free to make me more useful by adding more features."
    )

    if chat_id != update.message.from_user.id:  # Only auto-delete in group chats
        await delete_message_later(reply)

def get_user_last_seen(user_id: int) -> datetime:
    try:
        conn = sqlite3.connect('chatzzipper.db')
        cursor = conn.cursor()
        cursor.execute('SELECT last_seen FROM users WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        conn.close()
        
        if result and result[0]:
            return datetime.fromisoformat(result[0])
        return datetime.now() - timedelta(days=1)  # Default to 24 hours ago if no record
    except Exception as e:
        print(f"Error getting user's last seen: {e}")
        return datetime.now() - timedelta(days=1)

# Handle incoming messages
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("Message received")
    try:
        chat_id = update.message.chat_id
        
        # Only process messages from allowed group chats
        if chat_id not in config.allowed_chat_ids:
            print(f"Message from unauthorized chat: {chat_id}")
            return
        
        # Sanitize user data and message text
        user_id, username, first_name = sanitize_user_data(
            update.message.from_user.id,
            update.message.from_user.username,
            update.message.from_user.first_name
        )

        text = sanitize_input(update.message.text)
        message_id = update.message.message_id
        chat_id = update.message.chat_id
        current_time = datetime.now()
        
        # Store the message
        store_message(chat_id, user_id, message_id, text, current_time, username, first_name)
        
        # Get user's last seen timestamp
        last_seen = get_user_last_seen(user_id)
        
        # Fetch unread messages
        unread_messages = fetch_unread_messages(user_id, last_seen)
        if len(unread_messages) > MESSAGE_LIMIT:
            await ask_for_summary(update, context)
        
        # Update the user's last seen timestamp and last message ID
        update_user_activity(user_id, current_time, message_id)
        
    except Exception as e:
        print(f"Error handling message: {e}")

async def chatzip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    
    # Only allow command in authorized chats
    if chat_id not in config.allowed_chat_ids:
        await update.message.reply_text("This bot is only available in specific group chats.")
        return
    
    user_id = update.message.from_user.id
    last_seen = get_user_last_seen(user_id)
    unread_messages = fetch_unread_messages(user_id, last_seen)
    
    if len(unread_messages) > MESSAGE_LIMIT:
        await ask_for_summary(update, context)
    else:
        
        reply = await update.message.reply_text(f"You have {len(unread_messages)} unread messages - you're all caught up! 👍")
        if chat_id != user_id:  # Only auto-delete in group chats
            await delete_message_later(reply)


async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle unknown commands."""
    available_commands = """
Sorry, I don't recognize that command. Here are the commands I support:

/start - Start the bot and get welcome message
/chatzip - Check for unread messages and get a summary if needed

Try one of these commands!
"""
    await update.message.reply_text(available_commands)

# Main function
def main():
    print("Starting Bot...")
    init_db()

    print("Setting up the bot...")
    try:
        application = Application.builder().token(config.telegram_token).build()

        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("chatzip", chatzip))
        #When user enteres a command that is not recognized, it will be handled by the unknown_command function
        application.add_handler(MessageHandler(filters.COMMAND, unknown_command))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        application.add_handler(CallbackQueryHandler(handle_callback_query))

        print("Starting the bot...")
        application.run_polling()
        print("Bot is now running. Press Ctrl+C to stop.")
    except Exception as e:
        print(f"Error starting the bot: {e}")

# Entry point
if __name__ == '__main__':
    print("Bot started")
    main()