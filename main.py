import os
import re
import asyncio
import io
import logging
import random
import datetime
import json
import requests
import uuid
from typing import Optional, Dict, List, Tuple, Any
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
from telegram.error import BadRequest

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
        "claude-haiku": "f6fbf06c-532c-4c8a-89c7-f3ddcfb34bd1"
    }
    
    CHAT_MODEL: str = "claude-haiku"
    CODE_MODEL: str = "claude-opus"
    FILE_MODEL: str = "gpt-5"
    
    BASE_URL: str = "https://lmarena.ai/api/stream"
    PAGE_CHARS: int = 3200
    MAX_HISTORY: int = 20
    
    GEMINI_API_KEY: str = field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    GEMINI_IMAGE_MODEL: str = "gemini-2.0-flash-exp"

config = Config()

try:
    from google import genai
except ImportError:
    genai = None

@dataclass
class Message:
    id: str
    role: str
    content: str
    parent_ids: List[str] = field(default_factory=list)
    status: str = "pending"

@dataclass
class UserSession:
    session_id: Optional[str] = None
    messages: List[Message] = field(default_factory=list)
    model_id: Optional[str] = None
    last_activity: float = field(default_factory=time.time)
    
    def add_message(self, role: str, content: str, parent_id: str = None) -> Message:
        msg = Message(
            id=str(uuid.uuid4()),
            role=role,
            content=content,
            parent_ids=[parent_id] if parent_id else []
        )
        self.messages.append(msg)
        self.last_activity = time.time()
        return msg
    
    def get_last_message_id(self) -> Optional[str]:
        return self.messages[-1].id if self.messages else None
    
    def should_reset(self) -> bool:
        # Reset session after 30 minutes of inactivity or 50 messages
        return (time.time() - self.last_activity > 1800) or (len(self.messages) > 50)

@dataclass
class UserState:
    sessions: Dict[str, UserSession] = field(default_factory=dict)
    current_model: str = "claude-haiku"
    last_result: str = ""

class BotState:
    def __init__(self):
        self.users: Dict[int, UserState] = defaultdict(UserState)
        self.pagers: Dict[Tuple[int, int], Dict] = {}
        
    def get_user(self, chat_id: int) -> UserState:
        return self.users[chat_id]
    
    def get_session(self, chat_id: int, model_name: str) -> UserSession:
        user = self.get_user(chat_id)
        
        if model_name not in user.sessions:
            user.sessions[model_name] = UserSession(model_id=config.MODELS.get(model_name))
        
        session = user.sessions[model_name]
        
        # Reset if needed
        if session.should_reset():
            user.sessions[model_name] = UserSession(model_id=config.MODELS.get(model_name))
            session = user.sessions[model_name]
        
        return session

bot_state = BotState()

class LMArenaClient:
    """LMArena API Client with session management"""
    
    def __init__(self):
        self.base_url = config.BASE_URL
        self.models = config.MODELS
        self.headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
    
    def create_new_session_payload(self, model_name: str, user_content: str) -> Tuple[dict, str]:
        """Create payload for new session"""
        
        model_id = self.models.get(model_name)
        if not model_id:
            raise ValueError(f"Unknown model: {model_name}")
        
        session_id = str(uuid.uuid4())
        user_msg_id = str(uuid.uuid4())
        model_msg_id = str(uuid.uuid4())
        
        payload = {
            "id": session_id,
            "mode": "direct",
            "modelAId": model_id,
            "userMessageId": user_msg_id,
            "modelAMessageId": model_msg_id,
            "messages": [
                {
                    "id": user_msg_id,
                    "role": "user",
                    "content": user_content,
                    "experimental_attachments": [],
                    "parentMessageIds": [],
                    "participantPosition": "a",
                    "modelId": None,
                    "evaluationSessionId": session_id,
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
                    "evaluationSessionId": session_id,
                    "status": "pending",
                    "failureReason": None
                }
            ],
            "modality": "chat"
        }
        
        return payload, session_id
    
    def create_continuation_payload(self, session: UserSession, user_content: str) -> dict:
        """Create payload for continuing existing session"""
        
        # Get last message ID as parent
        parent_id = session.get_last_message_id()
        
        # Create new message IDs
        user_msg_id = str(uuid.uuid4())
        model_msg_id = str(uuid.uuid4())
        
        # Build messages array with full history
        messages = []
        
        # Add all existing messages
        for msg in session.messages:
            messages.append({
                "id": msg.id,
                "role": msg.role,
                "content": msg.content,
                "experimental_attachments": [],
                "parentMessageIds": msg.parent_ids,
                "participantPosition": "a",
                "modelId": session.model_id if msg.role == "assistant" else None,
                "evaluationSessionId": session.session_id,
                "status": msg.status,
                "failureReason": None
            })
        
        # Add new user message
        messages.append({
            "id": user_msg_id,
            "role": "user",
            "content": user_content,
            "experimental_attachments": [],
            "parentMessageIds": [parent_id] if parent_id else [],
            "participantPosition": "a",
            "modelId": None,
            "evaluationSessionId": session.session_id,
            "status": "pending",
            "failureReason": None
        })
        
        # Add placeholder for assistant response
        messages.append({
            "id": model_msg_id,
            "role": "assistant",
            "content": "",
            "experimental_attachments": [],
            "parentMessageIds": [user_msg_id],
            "participantPosition": "a",
            "modelId": session.model_id,
            "evaluationSessionId": session.session_id,
            "status": "pending",
            "failureReason": None
        })
        
        payload = {
            "id": session.session_id,
            "mode": "direct",
            "modelAId": session.model_id,
            "userMessageId": user_msg_id,
            "modelAMessageId": model_msg_id,
            "messages": messages,
            "modality": "chat"
        }
        
        return payload
    
    def stream_complete(self, session: UserSession, model_name: str, user_content: str):
        """Stream completion with session management"""
        
        try:
            # Determine if new session or continuation
            if not session.session_id or len(session.messages) == 0:
                # Create new session
                payload, session_id = self.create_new_session_payload(model_name, user_content)
                session.session_id = session_id
                session.model_id = self.models.get(model_name)
                url = f"{self.base_url}/create-evaluation"
                
                # Add user message to session
                user_msg = session.add_message("user", user_content)
                
            else:
                # Continue existing session
                # Add user message first
                parent_id = session.get_last_message_id()
                user_msg = session.add_message("user", user_content, parent_id)
                
                payload = self.create_continuation_payload(session, user_content)
                url = f"{self.base_url}/post-to-evaluation/{session.session_id}"
            
            # Make request
            response = requests.post(
                url,
                headers=self.headers,
                data=json.dumps(payload),
                stream=True,
                timeout=30
            )
            
            if response.status_code == 200:
                full_content = ""
                
                for line in response.iter_lines():
                    if line:
                        try:
                            decoded = line.decode("utf-8")
                            
                            # Parse streaming response format
                            if decoded.startswith("a0:"):
                                # Extract content after a0:
                                content = decoded[3:]
                                if content.startswith('"') and content.endswith('"'):
                                    content = json.loads(content)
                                
                                full_content += content
                                yield content
                                
                            elif decoded.startswith("ad:"):
                                # Metadata - contains finish reason
                                try:
                                    metadata = json.loads(decoded[3:])
                                    if metadata.get("finishReason") == "stop":
                                        # Add assistant message to session
                                        session.add_message("assistant", full_content, user_msg.id)
                                        session.messages[-1].status = "success"
                                except:
                                    pass
                                    
                        except Exception as e:
                            logger.debug(f"Parse line error: {e}")
                            continue
                            
            else:
                error_msg = f"Error {response.status_code}"
                try:
                    error_data = response.json()
                    if "error" in error_data:
                        error_msg = f"❌ {error_data['error']}"
                except:
                    error_msg = f"❌ {response.text[:200]}"
                yield error_msg
                
        except requests.exceptions.Timeout:
            yield "⏱️ Timeout - Server không phản hồi"
        except requests.exceptions.ConnectionError:
            yield "🔌 Lỗi kết nối - Kiểm tra mạng"
        except Exception as e:
            logger.error(f"Stream error: {e}")
            yield f"❌ Lỗi: {str(e)[:100]}"

lmarena_client = LMArenaClient()

class TextProcessor:
    @staticmethod
    def chunk_pages(text: str, per_page: int = None) -> List[str]:
        per_page = per_page or config.PAGE_CHARS
        if len(text) <= per_page:
            return [text]
        
        pages = []
        lines = text.split('\n')
        current_page = []
        current_size = 0
        
        for line in lines:
            line_size = len(line) + 1
            if current_size + line_size > per_page and current_page:
                pages.append('\n'.join(current_page))
                current_page = [line]
                current_size = line_size
            else:
                current_page.append(line)
                current_size += line_size
        
        if current_page:
            pages.append('\n'.join(current_page))
        
        return pages

text_processor = TextProcessor()

async def stream_response(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    model_name: str,
    user_message: str
):
    """Stream response with session management"""
    
    msg = await context.bot.send_message(chat_id, "💭 Đang suy nghĩ...")
    
    full_response = ""
    chunk_buffer = ""
    update_counter = 0
    last_update_time = time.time()
    
    try:
        # Get or create session for this model
        session = bot_state.get_session(chat_id, model_name)
        
        # Show session info
        session_info = f"📊 Session: {len(session.messages)} messages" if session.messages else "🆕 New session"
        await msg.edit_text(f"{session_info}\n💭 Đang xử lý...")
        
        # Stream from LMArena
        stream = await asyncio.to_thread(
            lmarena_client.stream_complete,
            session,
            model_name,
            user_message
        )
        
        for chunk in stream:
            full_response += chunk
            chunk_buffer += chunk
            update_counter += 1
            
            # Update message periodically
            current_time = time.time()
            if (update_counter % 10 == 0 or current_time - last_update_time > 1.5) and len(chunk_buffer) > 30:
                try:
                    display_text = chunk_buffer[:4000]
                    if len(chunk_buffer) > 4000:
                        display_text += "..."
                    await msg.edit_text(display_text)
                    last_update_time = current_time
                except:
                    pass
        
        # Final update
        if full_response:
            if len(full_response) > 4096:
                await msg.delete()
                pages = text_processor.chunk_pages(full_response)
                await send_paged_message(context, chat_id, pages)
            else:
                try:
                    await msg.edit_text(full_response)
                except:
                    await context.bot.send_message(chat_id, full_response[:4096])
            
            # Save result
            user = bot_state.get_user(chat_id)
            user.last_result = full_response
                
        else:
            await msg.edit_text("😔 Không nhận được phản hồi. Hãy thử lại!")
        
        return full_response
        
    except Exception as e:
        logger.error(f"Stream error: {e}")
        await msg.edit_text(f"❌ Lỗi: {str(e)[:200]}")
        return None

async def send_paged_message(context, chat_id: int, pages: List[str]):
    """Send paginated message"""
    pager_data = {
        "pages": pages,
        "idx": 0
    }
    
    keyboard = None
    if len(pages) > 1:
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("⏪", callback_data="pg_first"),
            InlineKeyboardButton("◀️", callback_data="pg_prev"),
            InlineKeyboardButton(f"1/{len(pages)}", callback_data="pg_info"),
            InlineKeyboardButton("▶️", callback_data="pg_next"),
            InlineKeyboardButton("⏩", callback_data="pg_last")
        ]])
    
    msg = await context.bot.send_message(
        chat_id,
        pages[0][:4096],
        reply_markup=keyboard
    )
    
    if len(pages) > 1:
        bot_state.pagers[(msg.chat_id, msg.message_id)] = pager_data

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
🤖 **LINH AI - LMArena FREE API**

📝 **Commands:**
• /help - Hiển thị trợ giúp
• /start - Bắt đầu mới
• /clear - Xóa toàn bộ sessions
• /session - Xem thông tin session
• /switch <model> - Đổi model (gpt-5/claude-opus/claude-haiku)
• /code <yêu cầu> - Viết code
• /img <mô tả> - Tạo ảnh

💬 **Features:**
• Nhớ context cả cuộc hội thoại
• Mỗi model có session riêng
• Auto-reset sau 30 phút không hoạt động
• Streaming responses

🚀 **Available Models:**
• **claude-haiku** - Nhanh, thông minh
• **claude-opus** - Mạnh nhất cho code
• **gpt-5** - Phân tích sâu

✨ **100% FREE - No API Key Required!**

👨‍💻 **Dev:** @cucodoivandep
    """
    
    await context.bot.send_message(
        update.effective_chat.id,
        help_text,
        parse_mode=ParseMode.MARKDOWN
    )

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = bot_state.get_user(chat_id)
    
    # Clear all sessions
    user.sessions.clear()
    
    await context.bot.send_message(
        chat_id,
        "👋 **Xin chào! Mình là Linh AI**\n\n"
        "🚀 Powered by **LMArena FREE API**\n"
        "✨ Không cần API key!\n\n"
        "💬 Chat trực tiếp với mình\n"
        "🔄 Mình sẽ nhớ cả cuộc trò chuyện\n"
        "💻 /code để viết code\n"
        "📚 /help xem hướng dẫn\n\n"
        f"🤖 Model hiện tại: **{user.current_model}**",
        parse_mode=ParseMode.MARKDOWN
    )

async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = bot_state.get_user(chat_id)
    
    sessions_count = len(user.sessions)
    messages_count = sum(len(s.messages) for s in user.sessions.values())
    
    user.sessions.clear()
    
    await context.bot.send_message(
        chat_id, 
        f"✅ Đã xóa {sessions_count} sessions với tổng {messages_count} tin nhắn!"
    )

async def cmd_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = bot_state.get_user(chat_id)
    
    if not user.sessions:
        await context.bot.send_message(chat_id, "📭 Chưa có session nào!")
        return
    
    info = "📊 **Session Information:**\n\n"
    
    for model_name, session in user.sessions.items():
        info += f"**{model_name}:**\n"
        info += f"• Messages: {len(session.messages)}\n"
        info += f"• Session ID: `{session.session_id[:8]}...`\n"
        info += f"• Last activity: {int(time.time() - session.last_activity)}s ago\n\n"
    
    info += f"🤖 Current model: **{user.current_model}**"
    
    await context.bot.send_message(
        chat_id,
        info,
        parse_mode=ParseMode.MARKDOWN
    )

async def cmd_switch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = bot_state.get_user(chat_id)
    
    if not context.args:
        models_list = "\n".join([f"• {m}" for m in config.MODELS.keys()])
        await context.bot.send_message(
            chat_id,
            f"📝 Usage: /switch <model>\n\nAvailable models:\n{models_list}"
        )
        return
    
    model_name = context.args[0].lower()
    
    if model_name not in config.MODELS:
        await context.bot.send_message(
            chat_id,
            f"❌ Unknown model: {model_name}\n"
            f"Available: {', '.join(config.MODELS.keys())}"
        )
        return
    
    user.current_model = model_name
    session = bot_state.get_session(chat_id, model_name)
    
    await context.bot.send_message(
        chat_id,
        f"✅ Switched to **{model_name}**\n"
        f"📊 Session has {len(session.messages)} messages",
        parse_mode=ParseMode.MARKDOWN
    )

async def cmd_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    request = " ".join(context.args).strip()
    
    if not request:
        await context.bot.send_message(
            chat_id, 
            "📝 Usage: /code <request>\n\n"
            "Examples:\n"
            "• /code bubble sort in Python\n"
            "• /code REST API with FastAPI\n"
            "• /code React component with hooks"
        )
        return
    
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    
    code_prompt = f"""Write clean, well-commented code for: {request}

Requirements:
- Add helpful comments
- Use best practices
- Include error handling
- Provide brief explanation"""
    
    await stream_response(
        context, 
        chat_id, 
        config.CODE_MODEL, 
        code_prompt
    )

async def cmd_img(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    prompt = " ".join(context.args).strip()
    
    if not prompt:
        await context.bot.send_message(
            chat_id, 
            "📝 Usage: /img <description>"
        )
        return
    
    if config.GEMINI_API_KEY and genai:
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
        
        try:
            gemini_client = genai.Client(api_key=config.GEMINI_API_KEY)
            response = await asyncio.to_thread(
                gemini_client.models.generate_images,
                model=config.GEMINI_IMAGE_MODEL,
                prompt=prompt,
                n=1
            )
            
            if hasattr(response, 'images') and response.images:
                for img in response.images:
                    if hasattr(img, 'url') and img.url:
                        await context.bot.send_photo(
                            chat_id,
                            photo=img.url,
                            caption=f"🎨 {prompt[:100]}"
                        )
                        return
            
            await context.bot.send_message(chat_id, "😔 Couldn't generate image")
            
        except Exception as e:
            await context.bot.send_message(
                chat_id,
                f"❌ Gemini error: {str(e)[:100]}"
            )
    else:
        # Text description fallback
        description_prompt = f"Create a detailed, vivid description of an image: {prompt}"
        user = bot_state.get_user(chat_id)
        await stream_response(
            context,
            chat_id,
            user.current_model,
            description_prompt
        )

async def on_page_nav(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = query.message.chat_id
    message_id = query.message.message_id
    
    pager_data = bot_state.pagers.get((chat_id, message_id))
    if not pager_data:
        await query.answer("❌ No data")
        return
    
    action = query.data
    pages = pager_data["pages"]
    
    if action == "pg_first":
        pager_data["idx"] = 0
    elif action == "pg_prev":
        pager_data["idx"] = max(0, pager_data["idx"] - 1)
    elif action == "pg_next":
        pager_data["idx"] = min(len(pages) - 1, pager_data["idx"] + 1)
    elif action == "pg_last":
        pager_data["idx"] = len(pages) - 1
    elif action == "pg_info":
        await query.answer(f"Page {pager_data['idx']+1}/{len(pages)}")
        return
    
    await query.answer()
    
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("⏪", callback_data="pg_first"),
        InlineKeyboardButton("◀️", callback_data="pg_prev"),
        InlineKeyboardButton(f"{pager_data['idx']+1}/{len(pages)}", callback_data="pg_info"),
        InlineKeyboardButton("▶️", callback_data="pg_next"),
        InlineKeyboardButton("⏩", callback_data="pg_last")
    ]])
    
    await query.message.edit_text(
        pages[pager_data["idx"]][:4096],
        reply_markup=keyboard
    )

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    message_text = (update.message.text or "").strip()
    
    if not message_text:
        return
    
    user = bot_state.get_user(chat_id)
    
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    
    await stream_response(
        context,
        chat_id,
        user.current_model,
        message_text
    )

def main():
    if not config.BOT_TOKEN:
        print("❌ Missing BOT_TOKEN!")
        print("📝 Create .env file with: BOT_TOKEN=your_token")
        return
    
    print("="*50)
    print("🚀 LINH AI BOT - LMArena FREE API")
    print("="*50)
    print("✨ NO API KEY REQUIRED - 100% FREE!")
    print(f"💬 Default Chat Model: {config.CHAT_MODEL}")
    print(f"💻 Code Model: {config.CODE_MODEL}")
    print(f"📊 File Model: {config.FILE_MODEL}")
    print("="*50)
    print("📌 Features:")
    print("• Full conversation memory")
    print("• Multiple model sessions")
    print("• Streaming responses")
    print("• Auto session management")
    print("="*50)
    print("Bot is running... Press Ctrl+C to stop")
    
    app = ApplicationBuilder().token(config.BOT_TOKEN).build()
    
    # Commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("clear", cmd_clear))
    app.add_handler(CommandHandler("session", cmd_session))
    app.add_handler(CommandHandler("switch", cmd_switch))
    app.add_handler(CommandHandler("code", cmd_code))
    app.add_handler(CommandHandler("img", cmd_img))
    
    # Callbacks
    app.add_handler(CallbackQueryHandler(on_page_nav, pattern=r"^pg_"))
    
    # Messages
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
