import os
import re
import asyncio
import io
import logging
import random
import datetime
import base64
import json
from typing import Optional, Dict, List, Tuple, Any, Union
from collections import deque, defaultdict
from dataclasses import dataclass, field
from enum import Enum
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
from telegram.error import BadRequest, TimedOut, NetworkError
from openai import OpenAI

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("linh_bot")

@dataclass
class Config:
    BOT_TOKEN: str = field(default_factory=lambda: os.getenv("BOT_TOKEN", ""))
    VERCEL_API_KEY: str = field(default_factory=lambda: os.getenv("VERCEL_API_KEY", ""))
    BASE_URL: str = field(default_factory=lambda: os.getenv("BASE_URL", "https://ai-gateway.vercel.sh/v1"))
    
    CHAT_MODEL: str = field(default_factory=lambda: os.getenv("CHAT_MODEL", "anthropic/claude-3.5-haiku"))
    CODE_MODEL: str = field(default_factory=lambda: os.getenv("CODE_MODEL", "anthropic/claude-4-opus"))
    FILE_MODEL: str = field(default_factory=lambda: os.getenv("FILE_MODEL", "anthropic/claude-4-opus"))
    
    MAX_TOKENS: int = field(default_factory=lambda: int(os.getenv("MAX_TOKENS", "900")))
    MAX_TOKENS_CODE: int = field(default_factory=lambda: int(os.getenv("MAX_TOKENS_CODE", "4000")))
    FILE_OUTPUT_TOKENS: int = field(default_factory=lambda: int(os.getenv("FILE_OUTPUT_TOKENS", "6000")))
    
    CHUNK_CHARS: int = field(default_factory=lambda: int(os.getenv("CHUNK_CHARS", "120000")))
    PAGE_CHARS: int = field(default_factory=lambda: int(os.getenv("PAGE_CHARS", "3200")))
    CTX_TURNS: int = field(default_factory=lambda: int(os.getenv("CTX_TURNS", "15")))
    REQUEST_TIMEOUT: float = field(default_factory=lambda: float(os.getenv("REQUEST_TIMEOUT", "90")))
    
    GEMINI_API_KEY: str = field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    GEMINI_IMAGE_MODEL: str = field(default_factory=lambda: os.getenv("GEMINI_IMAGE_MODEL", "gemini-2.0-flash-exp"))
    
    CACHE_TTL: int = 3600
    MAX_CACHE_SIZE: int = 100

config = Config()

try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None
    types = None

try:
    import chardet
except ImportError:
    chardet = None

try:
    import PyPDF2
except ImportError:
    PyPDF2 = None

try:
    import docx
    from docx import Document as DocxDocument
except ImportError:
    docx = None
    DocxDocument = None

try:
    import openpyxl
except ImportError:
    openpyxl = None

try:
    from pptx import Presentation
except ImportError:
    Presentation = None

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

class FileType(Enum):
    TEXT = "text"
    CODE = "code"
    PDF = "pdf"
    DOCX = "docx"
    XLSX = "xlsx"
    PPTX = "pptx"
    HTML = "html"
    JSON = "json"
    CSV = "csv"
    ARCHIVE = "archive"
    UNKNOWN = "unknown"

ARCHIVES = (".zip", ".rar", ".7z", ".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tar.xz")
TEXT_LIKE = (
    ".txt", ".md", ".log", ".csv", ".tsv", ".json", ".yaml", ".yml", 
    ".ini", ".cfg", ".env", ".xml", ".html", ".htm"
)
CODE_EXTENSIONS = (
    ".py", ".js", ".ts", ".java", ".c", ".cpp", ".cs", ".go", 
    ".php", ".rb", ".rs", ".sh", ".bat", ".ps1", ".sql", ".swift",
    ".kt", ".scala", ".r", ".m", ".dart", ".lua", ".pl", ".asm"
)

@dataclass
class UserState:
    history: deque = field(default_factory=lambda: deque(maxlen=32))
    file_mode: bool = False
    pending_file: Optional[Dict[str, Any]] = None
    last_result: str = ""
    active_messages: Dict[int, Any] = field(default_factory=dict)

class BotState:
    def __init__(self):
        self.users: Dict[int, UserState] = defaultdict(UserState)
        self.pagers: Dict[Tuple[int, int], Dict] = {}
        self.cache: Dict[str, Tuple[Any, float]] = {}
        
    def get_user(self, chat_id: int) -> UserState:
        return self.users[chat_id]
    
    def cache_get(self, key: str) -> Optional[Any]:
        if key in self.cache:
            value, timestamp = self.cache[key]
            if time.time() - timestamp < config.CACHE_TTL:
                return value
            del self.cache[key]
        return None
    
    def cache_set(self, key: str, value: Any):
        if len(self.cache) >= config.MAX_CACHE_SIZE:
            oldest_key = min(self.cache.keys(), key=lambda k: self.cache[k][1])
            del self.cache[oldest_key]
        self.cache[key] = (value, time.time())

bot_state = BotState()

class AIClient:
    def __init__(self):
        self.client = None
        if config.VERCEL_API_KEY:
            self.client = OpenAI(
                api_key=config.VERCEL_API_KEY,
                base_url=config.BASE_URL,
                timeout=config.REQUEST_TIMEOUT
            )
    
    def stream_complete(
        self,
        model: str,
        messages: List[Dict[str, str]],
        max_tokens: int,
        temperature: float = 0.7
    ):
        if not self.client:
            yield "❌ Thiếu VERCEL_API_KEY."
            return
        
        try:
            stream = self.client.chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=messages,
                stream=True
            )
            
            for chunk in stream:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
                    
        except Exception as e:
            yield f"\n❌ Lỗi: {str(e)[:200]}"
    
    async def complete(
        self,
        model: str,
        messages: List[Dict[str, str]],
        max_tokens: int,
        temperature: float = 0.7,
        retries: int = 3
    ) -> str:
        if not self.client:
            return "❌ Thiếu VERCEL_API_KEY."
        
        cache_key = f"{model}:{json.dumps(messages)}:{max_tokens}:{temperature}"
        cached = bot_state.cache_get(cache_key)
        if cached:
            return cached
        
        last_error = None
        for attempt in range(retries):
            try:
                response = await asyncio.wait_for(
                    asyncio.to_thread(
                        self._sync_complete,
                        model, messages, max_tokens, temperature
                    ),
                    timeout=config.REQUEST_TIMEOUT + 10
                )
                
                bot_state.cache_set(cache_key, response)
                return response
                    
            except asyncio.TimeoutError:
                last_error = "Timeout - yêu cầu mất quá nhiều thời gian"
            except Exception as e:
                last_error = str(e)
                
            if attempt < retries - 1:
                await asyncio.sleep(1.5 * (attempt + 1) + random.random())
        
        raise Exception(f"Lỗi sau {retries} lần thử: {last_error}")
    
    def _sync_complete(
        self, 
        model: str, 
        messages: List[Dict[str, str]], 
        max_tokens: int,
        temperature: float
    ) -> str:
        response = self.client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=messages
        )
        return (response.choices[0].message.content or "").strip()

ai_client = AIClient()

class TextProcessor:
    @staticmethod
    def escape_markdown_v2(text: str) -> str:
        special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
        for char in special_chars:
            text = text.replace(char, f'\\{char}')
        return text
    
    @staticmethod
    def to_blockquote_md2(text: str) -> str:
        lines = text.split('\n')
        quoted_lines = []
        for line in lines:
            if line.strip():
                escaped = TextProcessor.escape_markdown_v2(line)
                quoted_lines.append(f'>{escaped}')
            else:
                quoted_lines.append('')
        return '\n'.join(quoted_lines)
    
    @staticmethod
    def chunk_code_pages(code: str, per_page: int = None) -> List[str]:
        per_page = per_page or config.PAGE_CHARS
        if len(code) <= per_page:
            return [code]
        
        pages = []
        current_page = []
        current_size = 0
        
        blocks = TextProcessor._split_code_blocks(code)
        
        for block in blocks:
            block_size = len(block) + 1
            
            if current_size + block_size > per_page:
                if current_page:
                    pages.append('\n'.join(current_page))
                    current_page = []
                    current_size = 0
                
                if block_size > per_page:
                    pages.extend(TextProcessor._split_large_block(block, per_page))
                else:
                    current_page.append(block)
                    current_size = block_size
            else:
                current_page.append(block)
                current_size += block_size
        
        if current_page:
            pages.append('\n'.join(current_page))
        
        return pages
    
    @staticmethod
    def _split_code_blocks(code: str) -> List[str]:
        blocks = []
        current_block = []
        
        for line in code.splitlines():
            if line and not line[0].isspace() and current_block:
                blocks.append('\n'.join(current_block))
                current_block = [line]
            else:
                current_block.append(line)
        
        if current_block:
            blocks.append('\n'.join(current_block))
        
        return blocks
    
    @staticmethod
    def _split_large_block(block: str, per_page: int) -> List[str]:
        pages = []
        lines = block.splitlines()
        current_lines = []
        current_size = 0
        
        for line in lines:
            line_size = len(line) + 1
            if current_size + line_size > per_page and current_lines:
                pages.append('\n'.join(current_lines))
                current_lines = [line]
                current_size = line_size
            else:
                current_lines.append(line)
                current_size += line_size
        
        if current_lines:
            pages.append('\n'.join(current_lines))
        
        return pages

text_processor = TextProcessor()

class FileProcessor:
    @staticmethod
    def detect_file_type(filename: str) -> FileType:
        name_lower = filename.lower()
        
        if any(name_lower.endswith(ext) for ext in ARCHIVES):
            return FileType.ARCHIVE
        elif any(name_lower.endswith(ext) for ext in CODE_EXTENSIONS):
            return FileType.CODE
        elif name_lower.endswith('.pdf'):
            return FileType.PDF
        elif name_lower.endswith(('.docx', '.doc')):
            return FileType.DOCX
        elif name_lower.endswith(('.xlsx', '.xls')):
            return FileType.XLSX
        elif name_lower.endswith(('.pptx', '.ppt')):
            return FileType.PPTX
        elif name_lower.endswith(('.html', '.htm')):
            return FileType.HTML
        elif name_lower.endswith('.json'):
            return FileType.JSON
        elif name_lower.endswith('.csv'):
            return FileType.CSV
        elif any(name_lower.endswith(ext) for ext in TEXT_LIKE):
            return FileType.TEXT
        else:
            return FileType.UNKNOWN
    
    @staticmethod
    def detect_encoding(data: bytes) -> str:
        if not data:
            return "utf-8"
        
        if chardet:
            result = chardet.detect(data)
            if result and result.get('encoding'):
                return result['encoding']
        
        for encoding in ['utf-8', 'utf-16', 'latin-1', 'cp1252', 'gb2312']:
            try:
                data.decode(encoding)
                return encoding
            except UnicodeDecodeError:
                continue
        
        return 'utf-8'
    
    @staticmethod
    async def process_file(filename: str, data: bytes) -> Tuple[Optional[str], str]:
        file_type = FileProcessor.detect_file_type(filename)
        
        try:
            if file_type == FileType.ARCHIVE:
                return None, "📦 File nén không được hỗ trợ trực tiếp."
            
            elif file_type == FileType.PDF:
                if not PyPDF2:
                    return None, "❌ Thư viện PyPDF2 chưa được cài đặt."
                return FileProcessor._read_pdf(data), "pdf"
            
            elif file_type == FileType.DOCX:
                if not docx:
                    return None, "❌ Thư viện python-docx chưa được cài đặt."
                return FileProcessor._read_docx(data), "docx"
            
            elif file_type == FileType.XLSX:
                if not openpyxl:
                    return None, "❌ Thư viện openpyxl chưa được cài đặt."
                return FileProcessor._read_excel(data), "xlsx"
            
            elif file_type == FileType.PPTX:
                if not Presentation:
                    return None, "❌ Thư viện python-pptx chưa được cài đặt."
                return FileProcessor._read_pptx(data), "pptx"
            
            elif file_type == FileType.HTML:
                text = FileProcessor._decode_text(data)
                if BeautifulSoup:
                    soup = BeautifulSoup(text, 'html.parser')
                    return soup.get_text(separator='\n'), "html"
                return text, "html"
            
            elif file_type == FileType.JSON:
                text = FileProcessor._decode_text(data)
                try:
                    obj = json.loads(text)
                    return json.dumps(obj, indent=2, ensure_ascii=False), "json"
                except:
                    return text, "json"
            
            elif file_type in [FileType.TEXT, FileType.CODE, FileType.CSV]:
                return FileProcessor._decode_text(data), file_type.value
            
            else:
                return None, f"❌ Định dạng {filename} chưa được hỗ trợ."
                
        except Exception as e:
            return None, f"❌ Lỗi xử lý file: {str(e)}"
    
    @staticmethod
    def _decode_text(data: bytes) -> str:
        encoding = FileProcessor.detect_encoding(data)
        try:
            return data.decode(encoding, errors='ignore')
        except:
            return data.decode('utf-8', errors='ignore')
    
    @staticmethod
    def _read_pdf(data: bytes) -> str:
        pdf_file = io.BytesIO(data)
        pdf_reader = PyPDF2.PdfReader(pdf_file)
        text = []
        for page_num in range(len(pdf_reader.pages)):
            page = pdf_reader.pages[page_num]
            text.append(page.extract_text())
        return '\n'.join(text)
    
    @staticmethod
    def _read_docx(data: bytes) -> str:
        doc_file = io.BytesIO(data)
        doc = DocxDocument(doc_file)
        return '\n'.join([paragraph.text for paragraph in doc.paragraphs])
    
    @staticmethod
    def _read_excel(data: bytes) -> str:
        excel_file = io.BytesIO(data)
        wb = openpyxl.load_workbook(excel_file, read_only=True)
        text = []
        for sheet_name in wb.sheetnames:
            sheet = wb[sheet_name]
            text.append(f"=== Sheet: {sheet_name} ===")
            for row in sheet.iter_rows(values_only=True):
                row_text = '\t'.join([str(cell) if cell else '' for cell in row])
                if row_text.strip():
                    text.append(row_text)
        return '\n'.join(text)
    
    @staticmethod
    def _read_pptx(data: bytes) -> str:
        pptx_file = io.BytesIO(data)
        prs = Presentation(pptx_file)
        text = []
        for slide_num, slide in enumerate(prs.slides, 1):
            text.append(f"=== Slide {slide_num} ===")
            for shape in slide.shapes:
                if hasattr(shape, "text"):
                    if shape.text.strip():
                        text.append(shape.text)
        return '\n'.join(text)

file_processor = FileProcessor()

class PagerManager:
    @staticmethod
    def create_keyboard(idx: int, total: int) -> Optional[InlineKeyboardMarkup]:
        if total <= 1:
            return None
        
        buttons = []
        nav_row = []
        if idx > 0:
            nav_row.append(InlineKeyboardButton("⏪", callback_data="pg_first"))
            nav_row.append(InlineKeyboardButton("◀️", callback_data="pg_prev"))
        
        nav_row.append(InlineKeyboardButton(f"📄 {idx+1}/{total}", callback_data="pg_info"))
        
        if idx < total - 1:
            nav_row.append(InlineKeyboardButton("▶️", callback_data="pg_next"))
            nav_row.append(InlineKeyboardButton("⏩", callback_data="pg_last"))
        
        buttons.append(nav_row)
        
        action_row = [
            InlineKeyboardButton("📋 Copy", callback_data="pg_copy"),
            InlineKeyboardButton("💾 Download", callback_data="pg_download"),
            InlineKeyboardButton("❌ Close", callback_data="pg_close")
        ]
        buttons.append(action_row)
        
        return InlineKeyboardMarkup(buttons)
    
    @staticmethod
    def prepare_page(pager_data: Dict) -> Tuple[str, str]:
        text = pager_data["pages"][pager_data["idx"]]
        
        if pager_data.get("is_code"):
            lang = pager_data.get("lang", "")
            formatted = f"```{lang}\n{text}\n```"
            return formatted, ParseMode.MARKDOWN_V2
        else:
            return f"<pre>{text}</pre>", ParseMode.HTML

pager_manager = PagerManager()

class MessageBuilder:
    @staticmethod
    def build_system_prompt(context_type: str = "chat") -> str:
        current_time = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        
        base_prompt = (
            f"Bạn là Linh - AI assistant thông minh và thân thiện.\n"
            f"Thời gian hiện tại: {current_time}\n"
            f"Được phát triển bởi Hoàng Tuấn Anh (@cucodoivandep)\n\n"
        )
        
        if context_type == "chat":
            return base_prompt + (
                "Hướng dẫn giao tiếp:\n"
                "• Trả lời ngắn gọn, súc tích, đi thẳng vào vấn đề\n"
                "• Nói chuyện tự nhiên như người Việt\n"
                "• Thể hiện cảm xúc phù hợp ngữ cảnh\n"
                "• Không nịnh bợ, không vòng vo tam quốc\n"
                "• Được phép dùng từ mạnh khi cần thiết"
            )
        
        elif context_type == "code":
            return base_prompt + (
                "Bạn là lập trình viên chuyên nghiệp với 10+ năm kinh nghiệm.\n\n"
                "Nguyên tắc viết code:\n"
                "• Code phải clean, readable và maintainable\n"
                "• Tuân thủ best practices và design patterns\n"
                "• Thêm comments và docstrings đầy đủ\n"
                "• Xử lý errors và edge cases cẩn thận\n"
                "• Tối ưu performance khi cần thiết\n"
                "• Security first - validate inputs, sanitize outputs\n"
                "• Viết unit tests nếu được yêu cầu"
            )
        
        elif context_type == "file":
            return base_prompt + (
                "Bạn đang xử lý và phân tích file.\n\n"
                "Hướng dẫn:\n"
                "• Phân tích cấu trúc và nội dung file cẩn thận\n"
                "• Trích xuất thông tin quan trọng\n"
                "• Tóm tắt nội dung chính\n"
                "• Trả lời câu hỏi dựa trên nội dung file\n"
                "• Đề xuất cải thiện nếu phù hợp"
            )
        
        return base_prompt
    
    @staticmethod
    def build_messages(
        chat_id: int,
        user_text: str,
        context_type: str = "chat",
        include_history: bool = True
    ) -> List[Dict[str, str]]:
        messages = []
        
        system_prompt = MessageBuilder.build_system_prompt(context_type)
        messages.append({"role": "system", "content": system_prompt})
        
        if include_history:
            user = bot_state.get_user(chat_id)
            history_messages = []
            
            keep_turns = config.CTX_TURNS * 2
            for role, content in list(user.history)[-keep_turns:]:
                truncated = content[:500] + "..." if len(content) > 500 else content
                history_messages.append({
                    "role": "user" if role == "user" else "assistant",
                    "content": truncated
                })
            
            messages.extend(history_messages)
        
        messages.append({"role": "user", "content": user_text})
        
        return messages

message_builder = MessageBuilder()

async def stream_response(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    model: str,
    messages: List[Dict[str, str]],
    max_tokens: int,
    temperature: float = 0.7
):
    msg = await context.bot.send_message(chat_id, "💭 Đang suy nghĩ...")
    
    full_response = ""
    chunk_buffer = ""
    update_counter = 0
    
    async def update_message():
        nonlocal chunk_buffer
        try:
            if chunk_buffer:
                await msg.edit_text(chunk_buffer[:4096])
        except:
            pass
    
    try:
        stream = await asyncio.to_thread(
            ai_client.stream_complete,
            model, messages, max_tokens, temperature
        )
        
        for chunk in stream:
            full_response += chunk
            chunk_buffer += chunk
            update_counter += 1
            
            if update_counter % 5 == 0 and len(chunk_buffer) > 100:
                await update_message()
        
        if full_response:
            if len(full_response) > 4096:
                await msg.delete()
                pages = text_processor.chunk_code_pages(full_response)
                pager_data = {
                    "pages": pages,
                    "is_code": False,
                    "lang": "",
                    "idx": 0
                }
                await send_paged_message(context, chat_id, None, pager_data)
            else:
                await msg.edit_text(full_response)
        
        return full_response
        
    except Exception as e:
        await msg.edit_text(f"❌ Lỗi: {str(e)[:200]}")
        return None

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
🤖 **LINH AI BOT**

📝 **Lệnh:**
• /help - Hướng dẫn
• /start - Khởi động
• /clear - Xóa lịch sử
• /stats - Thống kê
• /code <yêu cầu> - Viết code (Claude-4-Opus)
• /img <mô tả> - Tạo ảnh (Gemini)
• /cancelfile - Thoát file mode
• /sendfile - Tải kết quả

💬 **Sử dụng:**
• Nhắn tin trực tiếp để chat
• Gửi file để phân tích
• img: <prompt> để tạo ảnh

🚀 **Models:**
• Chat: Claude-3.5-Haiku
• Code/File: Claude-4-Opus

👨‍💻 **Dev:** @cucodoivandep
    """
    
    await context.bot.send_message(
        update.effective_chat.id,
        help_text,
        parse_mode=ParseMode.MARKDOWN
    )

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = """
👋 Xin chào! Mình là Linh - AI Assistant.

💬 Nhắn tin trực tiếp để chat
💻 /code để viết code với Claude-4-Opus
🎨 /img để tạo ảnh với Gemini
📄 Gửi file để phân tích

/help để xem chi tiết.
    """
    
    await context.bot.send_message(
        update.effective_chat.id,
        welcome_text
    )

async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = bot_state.get_user(chat_id)
    user.history.clear()
    
    await context.bot.send_message(
        chat_id,
        "✅ Đã xóa lịch sử chat."
    )

async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = bot_state.get_user(chat_id)
    
    stats_text = f"""
📊 **Thống kê:**

• 💬 Lịch sử: {len(user.history)} tin
• 📁 File mode: {'Bật' if user.file_mode else 'Tắt'}
• 💾 Cache: {len(bot_state.cache)}

🚀 **Models:**
• Chat: {config.CHAT_MODEL}
• Code: {config.CODE_MODEL}
• File: {config.FILE_MODEL}
    """
    
    await context.bot.send_message(
        chat_id,
        stats_text,
        parse_mode=ParseMode.MARKDOWN
    )

async def cmd_img(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    prompt = " ".join(context.args).strip()
    
    if not prompt:
        await context.bot.send_message(
            chat_id,
            "📝 /img <mô tả hình ảnh>"
        )
        return
    
    if not config.GEMINI_API_KEY:
        await context.bot.send_message(
            chat_id,
            "❌ Thiếu GEMINI_API_KEY."
        )
        return
    
    if genai is None:
        await context.bot.send_message(
            chat_id,
            "❌ Thiếu thư viện google-generativeai."
        )
        return
    
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
    
    try:
        gemini_client = genai.Client(api_key=config.GEMINI_API_KEY)
        
        response = await asyncio.to_thread(
            gemini_client.models.generate_images,
            model=config.GEMINI_IMAGE_MODEL,
            prompt=prompt,
            n=1,
            safety_settings=[
                {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"}
            ]
        )
        
        sent_count = 0
        if hasattr(response, 'images') and response.images:
            for img in response.images:
                try:
                    if hasattr(img, 'url') and img.url:
                        await context.bot.send_photo(
                            chat_id,
                            photo=img.url,
                            caption=f"🎨 {prompt[:100]}"
                        )
                        sent_count += 1
                    elif hasattr(img, '_image_bytes') and img._image_bytes:
                        await context.bot.send_photo(
                            chat_id,
                            photo=io.BytesIO(img._image_bytes),
                            caption=f"🎨 {prompt[:100]}"
                        )
                        sent_count += 1
                except Exception:
                    pass
        
        if sent_count == 0:
            await context.bot.send_message(
                chat_id,
                "❌ Không nhận được ảnh từ Gemini."
            )
        
        user = bot_state.get_user(chat_id)
        user.history.append(("user", f"/img {prompt}"))
        user.history.append(("assistant", f"Đã tạo {sent_count} ảnh"))
        
    except Exception as e:
        await context.bot.send_message(
            chat_id,
            f"❌ Lỗi: {str(e)[:200]}"
        )

async def cmd_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    request = " ".join(context.args).strip()
    
    if not request:
        await context.bot.send_message(
            chat_id,
            "📝 /code <yêu cầu>"
        )
        return
    
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    
    messages = message_builder.build_messages(
        chat_id, 
        request,
        context_type="code",
        include_history=False
    )
    
    result = await stream_response(
        context,
        chat_id,
        config.CODE_MODEL,
        messages,
        config.MAX_TOKENS_CODE,
        temperature=0.3
    )
    
    if result:
        user = bot_state.get_user(chat_id)
        user.last_result = result
        user.history.append(("user", f"/code {request}"))
        user.history.append(("assistant", result[:500] + "..."))

async def cmd_cancelfile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = bot_state.get_user(chat_id)
    
    if not user.file_mode:
        await context.bot.send_message(
            chat_id,
            "ℹ️ Không trong file mode."
        )
        return
    
    user.file_mode = False
    user.pending_file = None
    
    await context.bot.send_message(
        chat_id,
        "✅ Đã thoát file mode."
    )

async def cmd_sendfile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = bot_state.get_user(chat_id)
    
    if not user.last_result:
        await context.bot.send_message(
            chat_id,
            "❌ Không có kết quả."
        )
        return
    
    file_bytes = user.last_result.encode('utf-8')
    file_io = io.BytesIO(file_bytes)
    file_io.name = f"result_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    
    await context.bot.send_document(
        chat_id,
        document=file_io,
        caption="📄 Kết quả"
    )

async def send_paged_message(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message: Optional[Update],
    pager_data: Dict
):
    text, parse_mode = pager_manager.prepare_page(pager_data)
    keyboard = pager_manager.create_keyboard(pager_data["idx"], len(pager_data["pages"]))
    
    try:
        if message:
            await message.edit_text(
                text,
                parse_mode=parse_mode,
                reply_markup=keyboard
            )
        else:
            sent_message = await context.bot.send_message(
                chat_id,
                text,
                parse_mode=parse_mode,
                reply_markup=keyboard
            )
            bot_state.pagers[(sent_message.chat_id, sent_message.message_id)] = pager_data
            
    except BadRequest:
        try:
            if message:
                await message.edit_text(text, reply_markup=keyboard)
            else:
                sent_message = await context.bot.send_message(
                    chat_id, text, reply_markup=keyboard
                )
                bot_state.pagers[(sent_message.chat_id, sent_message.message_id)] = pager_data
        except:
            await context.bot.send_message(
                chat_id,
                "❌ Lỗi hiển thị. /sendfile để tải."
            )

async def on_page_navigation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = query.message.chat_id
    message_id = query.message.message_id
    
    pager_data = bot_state.pagers.get((chat_id, message_id))
    if not pager_data:
        await query.answer("❌ Không có dữ liệu")
        return
    
    action = query.data
    
    if action == "pg_prev":
        pager_data["idx"] = (pager_data["idx"] - 1) % len(pager_data["pages"])
    elif action == "pg_next":
        pager_data["idx"] = (pager_data["idx"] + 1) % len(pager_data["pages"])
    elif action == "pg_first":
        pager_data["idx"] = 0
    elif action == "pg_last":
        pager_data["idx"] = len(pager_data["pages"]) - 1
    elif action == "pg_copy":
        await query.answer("📋 Copy từ tin nhắn")
        return
    elif action == "pg_download":
        full_text = "\n---\n".join(pager_data["pages"])
        file_bytes = full_text.encode('utf-8')
        file_io = io.BytesIO(file_bytes)
        file_io.name = f"content_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        
        await context.bot.send_document(
            chat_id,
            document=file_io,
            caption="📄 Nội dung"
        )
        await query.answer("✅ Đã gửi")
        return
    elif action == "pg_close":
        await query.message.delete()
        del bot_state.pagers[(chat_id, message_id)]
        await query.answer("✅ Đã đóng")
        return
    elif action == "pg_info":
        total_chars = sum(len(page) for page in pager_data["pages"])
        await query.answer(
            f"📊 {pager_data['idx']+1}/{len(pager_data['pages'])}\n"
            f"📝 {total_chars:,} ký tự"
        )
        return
    
    await query.answer()
    await send_paged_message(context, chat_id, query.message, pager_data)
    bot_state.pagers[(chat_id, message_id)] = pager_data

async def on_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    document = update.message.document
    
    if not document:
        await context.bot.send_message(
            chat_id,
            "❌ Không nhận được file."
        )
        return
    
    if document.file_size > 20 * 1024 * 1024:
        await context.bot.send_message(
            chat_id,
            "❌ File quá lớn (max 20MB)."
        )
        return
    
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    
    try:
        file = await context.bot.get_file(document.file_id)
        file_data = await file.download_as_bytearray()
        
        content, file_type = await file_processor.process_file(
            document.file_name or "unknown",
            bytes(file_data)
        )
        
        if not content:
            await context.bot.send_message(chat_id, file_type)
            return
        
        user = bot_state.get_user(chat_id)
        user.file_mode = True
        user.pending_file = {
            "name": document.file_name,
            "content": content[:config.CHUNK_CHARS],
            "type": file_type
        }
        
        await context.bot.send_message(
            chat_id,
            f"✅ File: {document.file_name}\n"
            f"📄 Loại: {file_type}\n"
            f"📝 {len(content):,} ký tự\n\n"
            f"Gửi câu hỏi hoặc /cancelfile"
        )
        
        if len(content) <= 1000:
            await context.bot.send_message(
                chat_id,
                f"```\n{content[:1000]}\n```",
                parse_mode=ParseMode.MARKDOWN
            )
        
    except Exception as e:
        await context.bot.send_message(
            chat_id,
            f"❌ Lỗi: {str(e)[:200]}"
        )

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    message_text = (update.message.text or "").strip()
    
    if not message_text:
        return
    
    if message_text.lower().startswith("img:"):
        prompt = message_text[4:].strip()
        context.args = prompt.split()
        await cmd_img(update, context)
        return
    
    user = bot_state.get_user(chat_id)
    
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    
    if user.file_mode and user.pending_file:
        file_content = user.pending_file["content"]
        file_name = user.pending_file["name"]
        
        prompt = (
            f"File: {file_name}\n\n"
            f"Nội dung file:\n{file_content[:10000]}\n\n"
            f"Câu hỏi: {message_text}"
        )
        
        messages = message_builder.build_messages(
            chat_id,
            prompt,
            context_type="file",
            include_history=False
        )
        
        result = await stream_response(
            context,
            chat_id,
            config.FILE_MODEL,
            messages,
            config.FILE_OUTPUT_TOKENS,
            temperature=0.5
        )
    else:
        messages = message_builder.build_messages(
            chat_id,
            message_text,
            context_type="chat",
            include_history=True
        )
        
        result = await stream_response(
            context,
            chat_id,
            config.CHAT_MODEL,
            messages,
            config.MAX_TOKENS,
            temperature=0.7
        )
    
    if result:
        user.last_result = result
        user.history.append(("user", message_text[:500]))
        user.history.append(("assistant", result[:500]))

def main():
    if not config.BOT_TOKEN:
        print("❌ Thiếu BOT_TOKEN")
        return
    
    if not config.VERCEL_API_KEY:
        print("⚠️ Thiếu VERCEL_API_KEY")
    
    app = ApplicationBuilder().token(config.BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("clear", cmd_clear))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("img", cmd_img))
    app.add_handler(CommandHandler("code", cmd_code))
    app.add_handler(CommandHandler("cancelfile", cmd_cancelfile))
    app.add_handler(CommandHandler("sendfile", cmd_sendfile))
    
    app.add_handler(CallbackQueryHandler(on_page_navigation, pattern=r"^pg_"))
    
    app.add_handler(MessageHandler(filters.Document.ALL, on_file))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    
    print("🚀 Bot đang chạy!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
