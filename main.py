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
from functools import lru_cache, wraps
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

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("linh_bot")

# ===================== Configuration =====================
@dataclass
class Config:
    """Bot configuration"""
    BOT_TOKEN: str = field(default_factory=lambda: os.getenv("BOT_TOKEN", ""))
    VERCEL_API_KEY: str = field(default_factory=lambda: os.getenv("VERCEL_API_KEY", ""))
    BASE_URL: str = field(default_factory=lambda: os.getenv("BASE_URL", "https://ai-gateway.vercel.sh/v1"))
    
    CHAT_MODEL: str = field(default_factory=lambda: os.getenv("CHAT_MODEL", "anthropic/claude-3.5-haiku"))
    CODE_MODEL: str = field(default_factory=lambda: os.getenv("CODE_MODEL", "anthropic/claude-3.5-sonnet"))
    FILE_MODEL: str = field(default_factory=lambda: os.getenv("FILE_MODEL", "anthropic/claude-3.5-sonnet"))
    
    MAX_TOKENS: int = field(default_factory=lambda: int(os.getenv("MAX_TOKENS", "900")))
    MAX_TOKENS_CODE: int = field(default_factory=lambda: int(os.getenv("MAX_TOKENS_CODE", "4000")))
    FILE_OUTPUT_TOKENS: int = field(default_factory=lambda: int(os.getenv("FILE_OUTPUT_TOKENS", "6000")))
    
    CHUNK_CHARS: int = field(default_factory=lambda: int(os.getenv("CHUNK_CHARS", "120000")))
    PAGE_CHARS: int = field(default_factory=lambda: int(os.getenv("PAGE_CHARS", "3200")))
    CTX_TURNS: int = field(default_factory=lambda: int(os.getenv("CTX_TURNS", "15")))
    MAX_CONCURRENCY: int = field(default_factory=lambda: int(os.getenv("MAX_CONCURRENCY", "3")))
    REQUEST_TIMEOUT: float = field(default_factory=lambda: float(os.getenv("REQUEST_TIMEOUT", "90")))
    MAX_EMIT_CHARS: int = field(default_factory=lambda: int(os.getenv("MAX_EMIT_CHARS", "800000")))
    
    GEMINI_API_KEY: str = field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    GEMINI_IMAGE_MODEL: str = field(default_factory=lambda: os.getenv("GEMINI_IMAGE_MODEL", "gemini-2.0-flash-exp"))
    
    # Rate limiting
    RATE_LIMIT_MESSAGES: int = 30
    RATE_LIMIT_WINDOW: int = 60  # seconds
    
    # Cache settings
    CACHE_TTL: int = 3600  # seconds
    MAX_CACHE_SIZE: int = 100

config = Config()

# ===================== Optional Imports =====================
try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None
    types = None
    logger.warning("Google Generative AI library not installed")

try:
    import chardet
except ImportError:
    chardet = None
    logger.warning("chardet not installed - using fallback encoding detection")

try:
    import PyPDF2
except ImportError:
    PyPDF2 = None
    logger.warning("PyPDF2 not installed - PDF support disabled")

try:
    import docx
    from docx import Document as DocxDocument
except ImportError:
    docx = None
    DocxDocument = None
    logger.warning("python-docx not installed - DOCX support disabled")

try:
    import openpyxl
except ImportError:
    openpyxl = None
    logger.warning("openpyxl not installed - Excel support disabled")

try:
    from pptx import Presentation
except ImportError:
    Presentation = None
    logger.warning("python-pptx not installed - PowerPoint support disabled")

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None
    logger.warning("BeautifulSoup not installed - HTML parsing disabled")

# ===================== File Types =====================
class FileType(Enum):
    """Supported file types"""
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

# ===================== State Management =====================
@dataclass
class UserState:
    """User state management"""
    history: deque = field(default_factory=lambda: deque(maxlen=32))
    file_mode: bool = False
    pending_file: Optional[Dict[str, Any]] = None
    last_result: str = ""
    rate_limit_count: int = 0
    rate_limit_reset: float = 0
    preferences: Dict[str, Any] = field(default_factory=dict)

class BotState:
    """Global bot state management"""
    def __init__(self):
        self.users: Dict[int, UserState] = defaultdict(UserState)
        self.locks: Dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
        self.pagers: Dict[Tuple[int, int], Dict] = {}
        self.cache: Dict[str, Tuple[Any, float]] = {}
        self.semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY)
        
    def get_user(self, chat_id: int) -> UserState:
        return self.users[chat_id]
    
    def get_lock(self, chat_id: int) -> asyncio.Lock:
        return self.locks[chat_id]
    
    def cache_get(self, key: str) -> Optional[Any]:
        if key in self.cache:
            value, timestamp = self.cache[key]
            if time.time() - timestamp < config.CACHE_TTL:
                return value
            del self.cache[key]
        return None
    
    def cache_set(self, key: str, value: Any):
        if len(self.cache) >= config.MAX_CACHE_SIZE:
            # Remove oldest entry
            oldest_key = min(self.cache.keys(), key=lambda k: self.cache[k][1])
            del self.cache[oldest_key]
        self.cache[key] = (value, time.time())

bot_state = BotState()

# ===================== Rate Limiting =====================
def rate_limit(func):
    """Rate limiting decorator"""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        user = bot_state.get_user(chat_id)
        
        current_time = time.time()
        if current_time > user.rate_limit_reset:
            user.rate_limit_count = 0
            user.rate_limit_reset = current_time + config.RATE_LIMIT_WINDOW
        
        if user.rate_limit_count >= config.RATE_LIMIT_MESSAGES:
            await context.bot.send_message(
                chat_id,
                f"⚠️ Quá nhiều yêu cầu! Vui lòng đợi {int(user.rate_limit_reset - current_time)} giây."
            )
            return
        
        user.rate_limit_count += 1
        return await func(update, context)
    return wrapper

# ===================== OpenAI Client =====================
class AIClient:
    """Enhanced AI client with retry and caching"""
    def __init__(self):
        self.client = None
        if config.VERCEL_API_KEY:
            self.client = OpenAI(
                api_key=config.VERCEL_API_KEY,
                base_url=config.BASE_URL,
                timeout=config.REQUEST_TIMEOUT
            )
    
    async def complete(
        self,
        model: str,
        messages: List[Dict[str, str]],
        max_tokens: int,
        temperature: float = 0.7,
        retries: int = 3
    ) -> str:
        """Complete with retry logic"""
        if not self.client:
            return "❌ Thiếu VERCEL_API_KEY."
        
        # Check cache
        cache_key = f"{model}:{json.dumps(messages)}:{max_tokens}:{temperature}"
        cached = bot_state.cache_get(cache_key)
        if cached:
            logger.info(f"Cache hit for model {model}")
            return cached
        
        last_error = None
        for attempt in range(retries):
            try:
                async with bot_state.semaphore:
                    response = await asyncio.wait_for(
                        asyncio.to_thread(
                            self._sync_complete,
                            model, messages, max_tokens, temperature
                        ),
                        timeout=config.REQUEST_TIMEOUT + 10
                    )
                    
                    # Cache result
                    bot_state.cache_set(cache_key, response)
                    return response
                    
            except asyncio.TimeoutError:
                last_error = "Timeout - yêu cầu mất quá nhiều thời gian"
            except Exception as e:
                last_error = str(e)
                logger.error(f"AI completion error (attempt {attempt + 1}): {e}")
                
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
        """Synchronous completion"""
        response = self.client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=messages
        )
        return (response.choices[0].message.content or "").strip()

ai_client = AIClient()

# ===================== Text Processing =====================
class TextProcessor:
    """Enhanced text processing utilities"""
    
    @staticmethod
    def escape_markdown_v2(text: str) -> str:
        """Escape special characters for Markdown V2"""
        special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
        for char in special_chars:
            text = text.replace(char, f'\\{char}')
        return text
    
    @staticmethod
    def to_blockquote_md2(text: str) -> str:
        """Convert text to blockquote markdown v2"""
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
        """Smart code chunking preserving structure"""
        per_page = per_page or config.PAGE_CHARS
        if len(code) <= per_page:
            return [code]
        
        pages = []
        current_page = []
        current_size = 0
        
        # Try to split by functions/classes first
        blocks = TextProcessor._split_code_blocks(code)
        
        for block in blocks:
            block_size = len(block) + 1
            
            if current_size + block_size > per_page:
                if current_page:
                    pages.append('\n'.join(current_page))
                    current_page = []
                    current_size = 0
                
                # If block is too large, split by lines
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
        """Split code into logical blocks"""
        blocks = []
        current_block = []
        indent_level = 0
        
        for line in code.splitlines():
            # Detect new top-level block
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
        """Split large block by lines"""
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

# ===================== File Processing =====================
class FileProcessor:
    """Enhanced file processing"""
    
    @staticmethod
    def detect_file_type(filename: str) -> FileType:
        """Detect file type from filename"""
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
        """Detect text encoding"""
        if not data:
            return "utf-8"
        
        if chardet:
            result = chardet.detect(data)
            if result and result.get('encoding'):
                return result['encoding']
        
        # Try common encodings
        for encoding in ['utf-8', 'utf-16', 'latin-1', 'cp1252', 'gb2312']:
            try:
                data.decode(encoding)
                return encoding
            except UnicodeDecodeError:
                continue
        
        return 'utf-8'
    
    @staticmethod
    async def process_file(filename: str, data: bytes) -> Tuple[Optional[str], str]:
        """Process file and extract content"""
        file_type = FileProcessor.detect_file_type(filename)
        
        try:
            if file_type == FileType.ARCHIVE:
                return None, "📦 File nén không được hỗ trợ trực tiếp. Vui lòng giải nén trước."
            
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
                # Pretty print JSON
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
            logger.error(f"Error processing file {filename}: {e}")
            return None, f"❌ Lỗi xử lý file: {str(e)}"
    
    @staticmethod
    def _decode_text(data: bytes) -> str:
        """Decode text with encoding detection"""
        encoding = FileProcessor.detect_encoding(data)
        try:
            return data.decode(encoding, errors='ignore')
        except:
            return data.decode('utf-8', errors='ignore')
    
    @staticmethod
    def _read_pdf(data: bytes) -> str:
        """Extract text from PDF"""
        pdf_file = io.BytesIO(data)
        pdf_reader = PyPDF2.PdfReader(pdf_file)
        text = []
        for page_num in range(len(pdf_reader.pages)):
            page = pdf_reader.pages[page_num]
            text.append(page.extract_text())
        return '\n'.join(text)
    
    @staticmethod
    def _read_docx(data: bytes) -> str:
        """Extract text from DOCX"""
        doc_file = io.BytesIO(data)
        doc = DocxDocument(doc_file)
        return '\n'.join([paragraph.text for paragraph in doc.paragraphs])
    
    @staticmethod
    def _read_excel(data: bytes) -> str:
        """Extract text from Excel"""
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
        """Extract text from PowerPoint"""
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

# ===================== Pager System =====================
class PagerManager:
    """Enhanced pager management"""
    
    @staticmethod
    def create_keyboard(idx: int, total: int) -> Optional[InlineKeyboardMarkup]:
        """Create navigation keyboard"""
        if total <= 1:
            return None
        
        buttons = []
        
        # First row: navigation
        nav_row = []
        if idx > 0:
            nav_row.append(InlineKeyboardButton("⏪", callback_data="pg_first"))
            nav_row.append(InlineKeyboardButton("◀️", callback_data="pg_prev"))
        
        nav_row.append(InlineKeyboardButton(f"📄 {idx+1}/{total}", callback_data="pg_info"))
        
        if idx < total - 1:
            nav_row.append(InlineKeyboardButton("▶️", callback_data="pg_next"))
            nav_row.append(InlineKeyboardButton("⏩", callback_data="pg_last"))
        
        buttons.append(nav_row)
        
        # Second row: actions
        action_row = [
            InlineKeyboardButton("📋 Copy", callback_data="pg_copy"),
            InlineKeyboardButton("💾 Download", callback_data="pg_download"),
            InlineKeyboardButton("❌ Close", callback_data="pg_close")
        ]
        buttons.append(action_row)
        
        return InlineKeyboardMarkup(buttons)
    
    @staticmethod
    def prepare_page(pager_data: Dict) -> Tuple[str, str]:
        """Prepare page content for display"""
        text = pager_data["pages"][pager_data["idx"]]
        
        if pager_data.get("is_code"):
            lang = pager_data.get("lang", "")
            # Format as code block
            formatted = f"```{lang}\n{text}\n```"
            return formatted, ParseMode.MARKDOWN_V2
        else:
            # Format as HTML
            return f"<pre>{text}</pre>", ParseMode.HTML

pager_manager = PagerManager()

# ===================== Message Builder =====================
class MessageBuilder:
    """Build and manage conversation messages"""
    
    @staticmethod
    def build_system_prompt(context_type: str = "chat") -> str:
        """Build system prompt based on context"""
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
        """Build message list for AI"""
        messages = []
        
        # System prompt
        system_prompt = MessageBuilder.build_system_prompt(context_type)
        messages.append({"role": "system", "content": system_prompt})
        
        # Add conversation history if needed
        if include_history:
            user = bot_state.get_user(chat_id)
            history_messages = []
            
            # Keep last N turns
            keep_turns = config.CTX_TURNS * 2
            for role, content in list(user.history)[-keep_turns:]:
                # Truncate long messages in history
                truncated = content[:500] + "..." if len(content) > 500 else content
                history_messages.append({
                    "role": "user" if role == "user" else "assistant",
                    "content": truncated
                })
            
            messages.extend(history_messages)
        
        # Add current user message
        messages.append({"role": "user", "content": user_text})
        
        return messages

message_builder = MessageBuilder()

# ===================== Command Handlers =====================
@rate_limit
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show help message"""
    help_text = """
🤖 **LINH AI BOT - HƯỚNG DẪN SỬ DỤNG**

📝 **Lệnh cơ bản:**
• /help - Hiển thị hướng dẫn này
• /start - Khởi động bot
• /clear - Xóa lịch sử chat
• /stats - Xem thống kê sử dụng

💬 **Chat & AI:**
• Nhắn tin trực tiếp để chat với AI
• /chat <câu hỏi> - Chat với context rõ ràng
• /code <yêu cầu> - Viết code chuyên nghiệp
• /img <mô tả> - Tạo hình ảnh với AI

📁 **Xử lý file:**
• Gửi file để phân tích (PDF, DOCX, XLSX, code...)
• /cancelfile - Thoát chế độ xử lý file
• /sendfile - Tải xuống kết quả gần nhất

⚙️ **Cài đặt:**
• /settings - Tùy chỉnh bot
• /model <name> - Chọn AI model
• /temp <0.0-1.0> - Điều chỉnh creativity

📊 **Hỗ trợ:**
• PDF, Word, Excel, PowerPoint
• Code (Python, JS, Java, C++...)
• HTML, JSON, CSV, Markdown
• Text files và nhiều định dạng khác

👨‍💻 **Developed by:** @cucodoivandep
    """
    
    await context.bot.send_message(
        update.effective_chat.id,
        help_text,
        parse_mode=ParseMode.MARKDOWN
    )

@rate_limit
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command"""
    welcome_text = """
👋 Xin chào! Mình là Linh - AI Assistant của bạn.

Mình có thể giúp bạn:
• 💬 Chat và trả lời câu hỏi
• 💻 Viết code chuyên nghiệp
• 🎨 Tạo hình ảnh với AI
• 📄 Phân tích và xử lý file

Gõ /help để xem hướng dẫn chi tiết.
Hoặc nhắn tin trực tiếp để bắt đầu chat!
    """
    
    await context.bot.send_message(
        update.effective_chat.id,
        welcome_text
    )

@rate_limit
async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clear chat history"""
    chat_id = update.effective_chat.id
    user = bot_state.get_user(chat_id)
    user.history.clear()
    
    await context.bot.send_message(
        chat_id,
        "✅ Đã xóa lịch sử chat. Bắt đầu cuộc trò chuyện mới!"
    )

@rate_limit
async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show usage statistics"""
    chat_id = update.effective_chat.id
    user = bot_state.get_user(chat_id)
    
    stats_text = f"""
📊 **Thống kê sử dụng:**

• 💬 Tin nhắn trong lịch sử: {len(user.history)}
• 📁 Chế độ file: {'Bật' if user.file_mode else 'Tắt'}
• 🔄 Giới hạn rate: {user.rate_limit_count}/{config.RATE_LIMIT_MESSAGES}
• 💾 Cache hits: {len(bot_state.cache)}
• 🔧 Model đang dùng: {config.CHAT_MODEL}
    """
    
    await context.bot.send_message(
        chat_id,
        stats_text,
        parse_mode=ParseMode.MARKDOWN
    )

@rate_limit
async def cmd_img(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate image with Gemini"""
    chat_id = update.effective_chat.id
    prompt = " ".join(context.args).strip()
    
    if not prompt:
        await context.bot.send_message(
            chat_id,
            "📝 Cách dùng: /img <mô tả hình ảnh>\n"
            "Ví dụ: /img một con mèo đang ngồi trên mặt trăng"
        )
        return
    
    if not config.GEMINI_API_KEY:
        await context.bot.send_message(
            chat_id,
            "❌ Chưa cấu hình GEMINI_API_KEY."
        )
        return
    
    if genai is None:
        await context.bot.send_message(
            chat_id,
            "❌ Thư viện google-generativeai chưa được cài đặt."
        )
        return
    
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
    
    try:
        # Initialize Gemini client
        gemini_client = genai.Client(api_key=config.GEMINI_API_KEY)
        
        # Generate image
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
        
        # Send generated images
        sent_count = 0
        if hasattr(response, 'images') and response.images:
            for img in response.images:
                try:
                    if hasattr(img, 'url') and img.url:
                        await context.bot.send_photo(
                            chat_id,
                            photo=img.url,
                            caption=f"🎨 Prompt: {prompt[:100]}..."
                        )
                        sent_count += 1
                    elif hasattr(img, '_image_bytes') and img._image_bytes:
                        await context.bot.send_photo(
                            chat_id,
                            photo=io.BytesIO(img._image_bytes),
                            caption=f"🎨 Prompt: {prompt[:100]}..."
                        )
                        sent_count += 1
                except Exception as e:
                    logger.error(f"Error sending image: {e}")
        
        if sent_count == 0:
            await context.bot.send_message(
                chat_id,
                "❌ Không nhận được hình ảnh từ Gemini. Thử lại với prompt khác."
            )
        
        # Save to history
        user = bot_state.get_user(chat_id)
        user.history.append(("user", f"/img {prompt}"))
        user.history.append(("assistant", f"Đã tạo {sent_count} ảnh"))
        
    except Exception as e:
        logger.error(f"Image generation error: {e}")
        await context.bot.send_message(
            chat_id,
            f"❌ Lỗi tạo ảnh: {str(e)[:200]}"
        )

@rate_limit
async def cmd_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate code with enhanced model"""
    chat_id = update.effective_chat.id
    request = " ".join(context.args).strip()
    
    if not request:
        await context.bot.send_message(
            chat_id,
            "📝 Cách dùng: /code <yêu cầu>\n\n"
            "Ví dụ:\n"
            "• /code viết function sort array trong Python\n"
            "• /code tạo REST API với Express.js\n"
            "• /code implement binary search tree"
        )
        return
    
    async with bot_state.get_lock(chat_id):
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        
        try:
            # Build messages with code context
            messages = message_builder.build_messages(
                chat_id, 
                request,
                context_type="code",
                include_history=False  # Fresh context for code
            )
            
            # Generate code
            result = await ai_client.complete(
                config.CODE_MODEL,
                messages,
                config.MAX_TOKENS_CODE,
                temperature=0.3  # Lower temperature for code
            )
            
            if not result:
                await context.bot.send_message(
                    chat_id,
                    "❌ Không nhận được kết quả từ model."
                )
                return
            
            # Save result
            user = bot_state.get_user(chat_id)
            user.last_result = result
            
            # Detect programming language
            lang_hint = "python"  # default
            lang_patterns = {
                "python": r"```python|def |import |class |printKATEX_INLINE_OPEN",
                "javascript": r"```javascript|```js|function |const |let |var |console\.",
                "java": r"```java|public class |public static void main",
                "cpp": r"```cpp|```c\+\+|#include |int mainKATEX_INLINE_OPEN",
                "go": r"```go|func mainKATEX_INLINE_OPEN|package main",
                "rust": r"```rust|fn mainKATEX_INLINE_OPEN|use std::",
                "typescript": r"```typescript|```ts|interface |type |export"
            }
            
            for lang, pattern in lang_patterns.items():
                if re.search(pattern, result, re.IGNORECASE):
                    lang_hint = lang
                    break
            
            # Prepare pages
            pages = text_processor.chunk_code_pages(result)
            
            # Send with pager
            pager_data = {
                "pages": pages,
                "is_code": True,
                "lang": lang_hint,
                "idx": 0
            }
            
            await send_paged_message(context, chat_id, None, pager_data)
            
            # Update history
            user.history.append(("user", f"/code {request}"))
            user.history.append(("assistant", result[:500] + "..."))
            
        except asyncio.TimeoutError:
            await context.bot.send_message(
                chat_id,
                "⏱️ Timeout - yêu cầu mất quá nhiều thời gian. Thử lại với yêu cầu ngắn hơn."
            )
        except Exception as e:
            logger.error(f"Code generation error: {e}")
            await context.bot.send_message(
                chat_id,
                f"❌ Lỗi: {str(e)[:200]}"
            )

@rate_limit
async def cmd_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Direct chat command with context"""
    chat_id = update.effective_chat.id
    message = " ".join(context.args).strip()
    
    if not message:
        await context.bot.send_message(
            chat_id,
            "📝 Cách dùng: /chat <câu hỏi>\n"
            "Hoặc nhắn tin trực tiếp không cần /chat"
        )
        return
    
    await process_chat_message(update, context, message)

async def cmd_cancelfile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel file processing mode"""
    chat_id = update.effective_chat.id
    user = bot_state.get_user(chat_id)
    
    if not user.file_mode:
        await context.bot.send_message(
            chat_id,
            "ℹ️ Bạn không trong chế độ xử lý file."
        )
        return
    
    user.file_mode = False
    user.pending_file = None
    
    await context.bot.send_message(
        chat_id,
        "✅ Đã thoát chế độ xử lý file."
    )

async def cmd_sendfile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send last result as file"""
    chat_id = update.effective_chat.id
    user = bot_state.get_user(chat_id)
    
    if not user.last_result:
        await context.bot.send_message(
            chat_id,
            "❌ Không có kết quả nào để gửi."
        )
        return
    
    # Create file
    file_bytes = user.last_result.encode('utf-8')
    file_io = io.BytesIO(file_bytes)
    file_io.name = f"result_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    
    await context.bot.send_document(
        chat_id,
        document=file_io,
        caption="📄 Kết quả xử lý gần nhất"
    )

# ===================== Message Handlers =====================
async def send_paged_message(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message: Optional[Update],
    pager_data: Dict
):
    """Send or update paged message"""
    text, parse_mode = pager_manager.prepare_page(pager_data)
    keyboard = pager_manager.create_keyboard(pager_data["idx"], len(pager_data["pages"]))
    
    try:
        if message:
            # Update existing message
            await message.edit_text(
                text,
                parse_mode=parse_mode,
                reply_markup=keyboard
            )
        else:
            # Send new message
            sent_message = await context.bot.send_message(
                chat_id,
                text,
                parse_mode=parse_mode,
                reply_markup=keyboard
            )
            # Store pager data
            bot_state.pagers[(sent_message.chat_id, sent_message.message_id)] = pager_data
            
    except BadRequest as e:
        # Retry without formatting if parse error
        if "can't parse" in str(e).lower():
            try:
                if message:
                    await message.edit_text(text, reply_markup=keyboard)
                else:
                    sent_message = await context.bot.send_message(
                        chat_id, text, reply_markup=keyboard
                    )
                    bot_state.pagers[(sent_message.chat_id, sent_message.message_id)] = pager_data
            except Exception as e2:
                logger.error(f"Failed to send message: {e2}")
                await context.bot.send_message(
                    chat_id,
                    "❌ Lỗi hiển thị. Dùng /sendfile để tải xuống kết quả."
                )

async def on_page_navigation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle pager navigation callbacks"""
    query = update.callback_query
    chat_id = query.message.chat_id
    message_id = query.message.message_id
    
    pager_data = bot_state.pagers.get((chat_id, message_id))
    if not pager_data:
        await query.answer("❌ Không tìm thấy dữ liệu")
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
        await query.answer("📋 Chọn và copy text từ tin nhắn")
        return
    elif action == "pg_download":
        # Send as file
        full_text = "\n---\n".join(pager_data["pages"])
        file_bytes = full_text.encode('utf-8')
        file_io = io.BytesIO(file_bytes)
        file_io.name = f"content_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        
        await context.bot.send_document(
            chat_id,
            document=file_io,
            caption="📄 Nội dung đầy đủ"
        )
        await query.answer("✅ Đã gửi file")
        return
    elif action == "pg_close":
        await query.message.delete()
        del bot_state.pagers[(chat_id, message_id)]
        await query.answer("✅ Đã đóng")
        return
    elif action == "pg_info":
        total_chars = sum(len(page) for page in pager_data["pages"])
        await query.answer(
            f"📊 Trang {pager_data['idx']+1}/{len(pager_data['pages'])}\n"
            f"📝 Tổng: {total_chars:,} ký tự"
        )
        return
    
    await query.answer()
    await send_paged_message(context, chat_id, query.message, pager_data)
    bot_state.pagers[(chat_id, message_id)] = pager_data

@rate_limit
async def on_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle file uploads"""
    chat_id = update.effective_chat.id
    document = update.message.document
    
    if not document:
        await context.bot.send_message(
            chat_id,
            "❌ Không nhận được file."
        )
        return
    
    # Check file size
    if document.file_size > 20 * 1024 * 1024:  # 20MB limit
        await context.bot.send_message(
            chat_id,
            "❌ File quá lớn. Giới hạn 20MB."
        )
        return
    
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    
    try:
        # Download file
        file = await context.bot.get_file(document.file_id)
        file_data = await file.download_as_bytearray()
        
        # Process file
        content, file_type = await file_processor.process_file(
            document.file_name or "unknown",
            bytes(file_data)
        )
        
        if not content:
            await context.bot.send_message(chat_id, file_type)  # Error message
            return
        
        # Save file info
        user = bot_state.get_user(chat_id)
        user.file_mode = True
        user.pending_file = {
            "name": document.file_name,
            "content": content[:config.CHUNK_CHARS],  # Limit content size
            "type": file_type
        }
        
        # Send confirmation
        await context.bot.send_message(
            chat_id,
            f"✅ Đã nhận file: {document.file_name}\n"
            f"📄 Loại: {file_type}\n"
            f"📝 Kích thước: {len(content):,} ký tự\n\n"
            f"Gửi câu hỏi về file hoặc /cancelfile để thoát."
        )
        
        # Show preview if text is short
        if len(content) <= 1000:
            await context.bot.send_message(
                chat_id,
                f"📋 **Preview:**\n```\n{content[:1000]}\n```",
                parse_mode=ParseMode.MARKDOWN
            )
        
    except Exception as e:
        logger.error(f"File processing error: {e}")
        await context.bot.send_message(
            chat_id,
            f"❌ Lỗi xử lý file: {str(e)[:200]}"
        )

async def process_chat_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    message_text: str
):
    """Process regular chat messages"""
    chat_id = update.effective_chat.id
    user = bot_state.get_user(chat_id)
    
    async with bot_state.get_lock(chat_id):
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        
        try:
            # Check if in file mode
            if user.file_mode and user.pending_file:
                # Process file-related query
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
                
                result = await ai_client.complete(
                    config.FILE_MODEL,
                    messages,
                    config.FILE_OUTPUT_TOKENS,
                    temperature=0.5
                )
            else:
                # Regular chat
                messages = message_builder.build_messages(
                    chat_id,
                    message_text,
                    context_type="chat",
                    include_history=True
                )
                
                result = await ai_client.complete(
                    config.CHAT_MODEL,
                    messages,
                    config.MAX_TOKENS,
                    temperature=0.7
                )
            
            if not result:
                result = "Không nhận được phản hồi từ AI."
            
            # Save result
            user.last_result = result
            
            # Send response
            if len(result) > config.PAGE_CHARS:
                # Use pager for long responses
                pages = text_processor.chunk_code_pages(result)
                pager_data = {
                    "pages": pages,
                    "is_code": False,
                    "lang": "",
                    "idx": 0
                }
                await send_paged_message(context, chat_id, None, pager_data)
            else:
                # Send as regular message
                try:
                    # Try with formatting
                    formatted = text_processor.to_blockquote_md2(result)
                    await context.bot.send_message(
                        chat_id,
                        formatted,
                        parse_mode=ParseMode.MARKDOWN_V2,
                        disable_web_page_preview=True
                    )
                except:
                    # Fallback to plain text
                    await context.bot.send_message(
                        chat_id,
                        result,
                        disable_web_page_preview=True
                    )
            
            # Update history
            user.history.append(("user", message_text[:500]))
            user.history.append(("assistant", result[:500]))
            
        except asyncio.TimeoutError:
            await context.bot.send_message(
                chat_id,
                "⏱️ Timeout - yêu cầu mất quá nhiều thời gian."
            )
        except Exception as e:
            logger.error(f"Chat processing error: {e}")
            await context.bot.send_message(
                chat_id,
                f"❌ Lỗi: {str(e)[:200]}"
            )

@rate_limit
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages"""
    message_text = (update.message.text or "").strip()
    
    if not message_text:
        return
    
    # Check for image generation request
    if message_text.lower().startswith("img:"):
        # Extract prompt and call image handler
        prompt = message_text[4:].strip()
        context.args = prompt.split()
        await cmd_img(update, context)
    else:
        # Process as chat message
        await process_chat_message(update, context, message_text)

# ===================== Main Application =====================
def main():
    """Main entry point"""
    # Validate configuration
    if not config.BOT_TOKEN:
        logger.error("Missing BOT_TOKEN environment variable")
        print("❌ Thiếu BOT_TOKEN. Vui lòng cấu hình biến môi trường.")
        return
    
    if not config.VERCEL_API_KEY:
        logger.warning("Missing VERCEL_API_KEY - AI features will be limited")
        print("⚠️ Thiếu VERCEL_API_KEY - một số tính năng AI sẽ bị giới hạn.")
    
    # Build application
    logger.info("Initializing Telegram bot...")
    app = ApplicationBuilder().token(config.BOT_TOKEN).build()
    
    # Register command handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("clear", cmd_clear))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("img", cmd_img))
    app.add_handler(CommandHandler("code", cmd_code))
    app.add_handler(CommandHandler("chat", cmd_chat))
    app.add_handler(CommandHandler("cancelfile", cmd_cancelfile))
    app.add_handler(CommandHandler("sendfile", cmd_sendfile))
    
    # Register callback handlers
    app.add_handler(CallbackQueryHandler(on_page_navigation, pattern=r"^pg_"))
    
    # Register message handlers
    app.add_handler(MessageHandler(filters.Document.ALL, on_file))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    
    # Start polling
    logger.info("Starting bot polling...")
    print("🚀 Bot đang chạy! Nhấn Ctrl+C để dừng.")
    
    try:
        app.run_polling(drop_pending_updates=True)
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
        print("\n👋 Bot đã dừng.")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        print(f"❌ Lỗi nghiêm trọng: {e}")

if __name__ == "__main__":
    main()
