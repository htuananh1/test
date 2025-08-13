import os
import asyncio
import io
import logging
import datetime
import json
import requests
import uuid
from typing import Optional, Dict, List
from collections import deque, defaultdict
from dataclasses import dataclass, field
import time

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode, ChatAction
from telegram.ext import (
    ApplicationBuilder, 
    ContextTypes, 
    MessageHandler, 
    filters, 
    CommandHandler, 
    CallbackQueryHandler
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("linh_bot")

@dataclass
class Config:
    BOT_TOKEN: str = field(default_factory=lambda: os.getenv("BOT_TOKEN", ""))
    
    MODELS = {
        "gpt-5": "983bc566-b783-4d28-b24c-3cb80b8eb108",
        "claude-opus": "96ae95fd-b70d-49c3-91cc-b58c7da1090b", 
        "claude-haiku": "f6fbf06c-532c-4c8a-89c7-f3ddcfb34db1"
    }
    
    CHAT_MODEL: str = "claude-haiku"
    CODE_MODEL: str = "claude-opus"
    
    BASE_URL: str = "https://lmarena.ai/api/stream/create-evaluation"
    PAGE_CHARS: int = 3200

config = Config()

@dataclass
class UserState:
    history: deque = field(default_factory=lambda: deque(maxlen=20))
    current_model: str = "claude-haiku"
    last_result: str = ""

class BotState:
    def __init__(self):
        self.users: Dict[int, UserState] = defaultdict(UserState)
        self.pagers: Dict = {}
        
    def get_user(self, chat_id: int) -> UserState:
        return self.users[chat_id]

bot_state = BotState()

class SimpleLMArenaClient:
    """Simplified LMArena client - always creates new evaluation"""
    
    def __init__(self):
        self.base_url = config.BASE_URL
        self.models = config.MODELS
    
    def stream_complete(self, model_name: str, prompt: str):
        """Simple streaming without session management"""
        
        model_id = self.models.get(model_name)
        if not model_id:
            yield f"❌ Unknown model: {model_name}"
            return
        
        # Generate IDs
        eval_id = str(uuid.uuid4())
        user_msg_id = str(uuid.uuid4())
        model_msg_id = str(uuid.uuid4())
        
        payload = {
            "id": eval_id,
            "mode": "direct",
            "modelAId": model_id,
            "userMessageId": user_msg_id,
            "modelAMessageId": model_msg_id,
            "messages": [
                {
                    "id": user_msg_id,
                    "role": "user",
                    "content": prompt,
                    "experimental_attachments": [],
                    "parentMessageIds": [],
                    "participantPosition": "a",
                    "modelId": None,
                    "evaluationSessionId": eval_id,
                    "status": "pending",
                    "failureReason": None
                },
                {
                    "id": model_msg_id,
                    "role": "assistant",
                    "content": "",
                    "experimental_attachments": [],
                    "parentMessageIds": [user_msg_id],
                    "participantPosition": "a",
                    "modelId": model_id,
                    "evaluationSessionId": eval_id,
                    "status": "pending",
                    "failureReason": None
                }
            ],
            "modality": "chat"
        }
        
        headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "Origin": "https://lmarena.ai",
            "Referer": "https://lmarena.ai/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        
        try:
            response = requests.post(
                self.base_url,
                headers=headers,
                data=json.dumps(payload),
                stream=True,
                timeout=30
            )
            
            if response.status_code != 200:
                yield f"❌ Error {response.status_code}"
                return
            
            for line in response.iter_lines():
                if line:
                    try:
                        decoded = line.decode("utf-8")
                        
                        # Parse different response formats
                        if decoded.startswith("a0:"):
                            content = decoded[3:]
                            if content.startswith('"') and content.endswith('"'):
                                content = json.loads(content)
                            yield content
                            
                        elif decoded.startswith("data: "):
                            data = decoded[6:]
                            if data and data != "[DONE]":
                                try:
                                    chunk = json.loads(data)
                                    if "content" in chunk:
                                        yield chunk["content"]
                                    elif "delta" in chunk:
                                        yield chunk.get("delta", {}).get("content", "")
                                except:
                                    if not data.startswith("{"):
                                        yield data
                                        
                    except Exception as e:
                        logger.debug(f"Parse error: {e}")
                        
        except requests.exceptions.Timeout:
            yield "⏱️ Timeout"
        except Exception as e:
            yield f"❌ Error: {str(e)[:100]}"

lmarena_client = SimpleLMArenaClient()

def build_prompt_with_context(chat_id: int, message: str) -> str:
    """Build prompt with conversation history"""
    user = bot_state.get_user(chat_id)
    
    if not user.history:
        return message
    
    context = "Previous conversation:\n"
    for role, content in list(user.history)[-10:]:
        context += f"{'User' if role == 'user' else 'Assistant'}: {content[:200]}\n"
    
    return f"{context}\n\nCurrent message: {message}"

async def stream_response(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    model_name: str,
    user_message: str,
    use_context: bool = True
):
    """Stream response"""
    
    msg = await context.bot.send_message(chat_id, "💭 Thinking...")
    
    # Build prompt
    prompt = build_prompt_with_context(chat_id, user_message) if use_context else user_message
    
    full_response = ""
    buffer = ""
    counter = 0
    
    try:
        stream = await asyncio.to_thread(
            lmarena_client.stream_complete,
            model_name,
            prompt
        )
        
        for chunk in stream:
            full_response += chunk
            buffer += chunk
            counter += 1
            
            # Update every 10 chunks
            if counter % 10 == 0 and len(buffer) > 50:
                try:
                    display = buffer[:4000]
                    if len(buffer) > 4000:
                        display += "..."
                    await msg.edit_text(display)
                except:
                    pass
        
        # Final update
        if full_response:
            if len(full_response) > 4096:
                await msg.delete()
                pages = chunk_text(full_response)
                await send_paged(context, chat_id, pages)
            else:
                await msg.edit_text(full_response)
            
            # Save to history
            user = bot_state.get_user(chat_id)
            user.history.append(("user", user_message[:200]))
            user.history.append(("assistant", full_response[:200]))
            user.last_result = full_response
        else:
            await msg.edit_text("No response received")
            
        return full_response
        
    except Exception as e:
        await msg.edit_text(f"❌ Error: {str(e)[:200]}")
        return None

def chunk_text(text: str, size: int = config.PAGE_CHARS) -> List[str]:
    """Split text into pages"""
    if len(text) <= size:
        return [text]
    
    pages = []
    lines = text.split('\n')
    current = []
    current_size = 0
    
    for line in lines:
        line_size = len(line) + 1
        if current_size + line_size > size and current:
            pages.append('\n'.join(current))
            current = [line]
            current_size = line_size
        else:
            current.append(line)
            current_size += line_size
    
    if current:
        pages.append('\n'.join(current))
    
    return pages

async def send_paged(context, chat_id: int, pages: List[str]):
    """Send paginated message"""
    if not pages:
        return
    
    data = {"pages": pages, "idx": 0}
    
    keyboard = None
    if len(pages) > 1:
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("◀️", callback_data="p_prev"),
            InlineKeyboardButton(f"1/{len(pages)}", callback_data="p_info"),
            InlineKeyboardButton("▶️", callback_data="p_next")
        ]])
    
    msg = await context.bot.send_message(
        chat_id,
        pages[0][:4096],
        reply_markup=keyboard
    )
    
    if keyboard:
        bot_state.pagers[(msg.chat_id, msg.message_id)] = data

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
🤖 **LINH AI - FREE LMArena**

**Commands:**
• /help - Show help
• /clear - Clear history
• /model <name> - Switch model
• /code <request> - Write code

**Models:**
• claude-haiku (fast)
• claude-opus (powerful)
• gpt-5 (advanced)

**Usage:**
Just send a message to chat!

✨ **100% FREE - No API Key!**
    """
    
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = bot_state.get_user(chat_id)
    user.history.clear()
    await update.message.reply_text("✅ History cleared!")

async def cmd_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = bot_state.get_user(chat_id)
    
    if not context.args:
        models = ", ".join(config.MODELS.keys())
        await update.message.reply_text(
            f"Current: **{user.current_model}**\n"
            f"Available: {models}\n"
            f"Usage: /model <name>",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    model = context.args[0].lower()
    if model not in config.MODELS:
        await update.message.reply_text(f"❌ Unknown model: {model}")
        return
    
    user.current_model = model
    await update.message.reply_text(f"✅ Switched to **{model}**", parse_mode=ParseMode.MARKDOWN)

async def cmd_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    request = " ".join(context.args).strip()
    
    if not request:
        await update.message.reply_text("Usage: /code <request>")
        return
    
    prompt = f"Write clean, well-commented code for: {request}"
    
    await update.message.chat.send_action(ChatAction.TYPING)
    await stream_response(context, chat_id, config.CODE_MODEL, prompt, use_context=False)

async def on_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    key = (query.message.chat_id, query.message.message_id)
    
    data = bot_state.pagers.get(key)
    if not data:
        await query.answer("No data")
        return
    
    if query.data == "p_prev":
        data["idx"] = max(0, data["idx"] - 1)
    elif query.data == "p_next":
        data["idx"] = min(len(data["pages"]) - 1, data["idx"] + 1)
    elif query.data == "p_info":
        await query.answer(f"Page {data['idx']+1}/{len(data['pages'])}")
        return
    
    await query.answer()
    
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("◀️", callback_data="p_prev"),
        InlineKeyboardButton(f"{data['idx']+1}/{len(data['pages'])}", callback_data="p_info"),
        InlineKeyboardButton("▶️", callback_data="p_next")
    ]])
    
    await query.message.edit_text(
        data["pages"][data["idx"]][:4096],
        reply_markup=keyboard
    )

async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = update.message.text.strip()
    
    if not text:
        return
    
    user = bot_state.get_user(chat_id)
    
    await update.message.chat.send_action(ChatAction.TYPING)
    await stream_response(context, chat_id, user.current_model, text)

def main():
    if not config.BOT_TOKEN:
        print("❌ Missing BOT_TOKEN in .env!")
        return
    
    print("🚀 LINH AI BOT - FREE LMArena API")
    print("✨ No API key required!")
    print("Starting...")
    
    app = ApplicationBuilder().token(config.BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("clear", cmd_clear))
    app.add_handler(CommandHandler("model", cmd_model))
    app.add_handler(CommandHandler("code", cmd_code))
    app.add_handler(CallbackQueryHandler(on_page, pattern=r"^p_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
