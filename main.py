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
import aiohttp
import requests

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

# Vietnam Constants
VIETNAM_CITIES = {
    "hanoi": {"name": "Hà Nội", "lat": 21.0285, "lon": 105.8542},
    "hcm": {"name": "TP.HCM", "lat": 10.8231, "lon": 106.6297},
    "danang": {"name": "Đà Nẵng", "lat": 16.0544, "lon": 108.2022},
    "haiphong": {"name": "Hải Phòng", "lat": 20.8449, "lon": 106.6881},
    "cantho": {"name": "Cần Thơ", "lat": 10.0452, "lon": 105.7469},
    "nhatrang": {"name": "Nha Trang", "lat": 12.2388, "lon": 109.1967},
    "dalat": {"name": "Đà Lạt", "lat": 11.9404, "lon": 108.4583},
    "hue": {"name": "Huế", "lat": 16.4637, "lon": 107.5909},
    "vungtau": {"name": "Vũng Tàu", "lat": 10.3460, "lon": 107.0843},
    "quynhon": {"name": "Quy Nhơn", "lat": 13.7830, "lon": 109.2197},
    "phuquoc": {"name": "Phú Quốc", "lat": 10.2271, "lon": 103.9564},
    "sapa": {"name": "Sapa", "lat": 22.3363, "lon": 103.8437}
}

VIETNAM_HOLIDAYS = {
    "01-01": "Tết Dương Lịch",
    "30-04": "Ngày Giải phóng miền Nam", 
    "01-05": "Ngày Quốc tế Lao động",
    "02-09": "Ngày Quốc khánh"
}

@dataclass
class Config:
    BOT_TOKEN: str = field(default_factory=lambda: os.getenv("BOT_TOKEN", ""))
    
    # Vercel AI API
    VERCEL_API_KEY: str = field(default_factory=lambda: os.getenv("VERCEL_API_KEY", ""))
    BASE_URL: str = field(default_factory=lambda: os.getenv("BASE_URL", "https://ai-gateway.vercel.sh/v1"))
    
    # Text models
    CHAT_MODEL: str = field(default_factory=lambda: os.getenv("CHAT_MODEL", "anthropic/claude-3.5-haiku"))
    CODE_MODEL: str = field(default_factory=lambda: os.getenv("CODE_MODEL", "anthropic/claude-3.5-sonnet"))
    FILE_MODEL: str = field(default_factory=lambda: os.getenv("FILE_MODEL", "anthropic/claude-3.5-sonnet"))
    IMAGE_GEN_MODEL: str = field(default_factory=lambda: os.getenv("IMAGE_GEN_MODEL", "black-forest-labs/flux-schnell"))
    
    # Token limits
    MAX_TOKENS: int = field(default_factory=lambda: int(os.getenv("MAX_TOKENS", "1500")))
    MAX_TOKENS_CODE: int = field(default_factory=lambda: int(os.getenv("MAX_TOKENS_CODE", "4000")))
    FILE_OUTPUT_TOKENS: int = field(default_factory=lambda: int(os.getenv("FILE_OUTPUT_TOKENS", "6000")))
    
    # Processing limits
    CHUNK_CHARS: int = field(default_factory=lambda: int(os.getenv("CHUNK_CHARS", "120000")))
    CTX_TURNS: int = field(default_factory=lambda: int(os.getenv("CTX_TURNS", "15")))
    REQUEST_TIMEOUT: float = field(default_factory=lambda: float(os.getenv("REQUEST_TIMEOUT", "90")))
    
    # Cache
    CACHE_TTL: int = 3600
    MAX_CACHE_SIZE: int = 100

config = Config()

# Import optional libraries
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
    ".ini", ".cfg", ".env", ".xml", ".html", ".htm", ".toml"
)
CODE_EXTENSIONS = (
    ".py", ".js", ".ts", ".java", ".c", ".cpp", ".cs", ".go", 
    ".php", ".rb", ".rs", ".sh", ".bat", ".ps1", ".sql", ".swift",
    ".kt", ".scala", ".r", ".m", ".dart", ".lua", ".pl", ".asm",
    ".jsx", ".tsx", ".vue", ".sol"
)

@dataclass
class UserState:
    history: deque = field(default_factory=lambda: deque(maxlen=32))
    file_mode: bool = False
    pending_file: Optional[Dict[str, Any]] = None
    last_result: str = ""
    language: str = "vi"
    location: str = "hanoi"

class BotState:
    def __init__(self):
        self.users: Dict[int, UserState] = defaultdict(UserState)
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

class VietnamServices:
    """Services for Vietnam-specific features using AI"""
    
    @staticmethod
    def get_vietnam_time() -> Dict:
        """Get current time in Vietnam"""
        try:
            import pytz
            vn_tz = pytz.timezone('Asia/Ho_Chi_Minh')
            vn_time = datetime.datetime.now(vn_tz)
        except:
            vn_time = datetime.datetime.utcnow() + datetime.timedelta(hours=7)
        
        vn_days = ['Thứ Hai', 'Thứ Ba', 'Thứ Tư', 'Thứ Năm', 'Thứ Sáu', 'Thứ Bảy', 'Chủ Nhật']
        day_name = vn_days[vn_time.weekday()]
        
        date_str = vn_time.strftime("%d-%m")
        holiday = VIETNAM_HOLIDAYS.get(date_str, "")
        
        hour = vn_time.hour
        if 5 <= hour < 11:
            greeting = "Chào buổi sáng"
        elif 11 <= hour < 13:
            greeting = "Chào buổi trưa"
        elif 13 <= hour < 18:
            greeting = "Chào buổi chiều"
        else:
            greeting = "Chào buổi tối"
        
        return {
            "datetime": vn_time,
            "day_name": day_name,
            "date": vn_time.strftime('%d/%m/%Y'),
            "time": vn_time.strftime('%H:%M:%S'),
            "holiday": holiday,
            "greeting": greeting,
            "hour": hour
        }
    
    @staticmethod
    async def get_exchange_rate() -> str:
        """Get USD/VND exchange rate"""
        try:
            url = "https://api.exchangerate-api.com/v4/latest/USD"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10) as response:
                    data = await response.json()
            
            vnd = data["rates"].get("VND", 0)
            eur = 1 / data["rates"].get("EUR", 1)
            gbp = 1 / data["rates"].get("GBP", 1)
            jpy = data["rates"].get("JPY", 0)
            cny = data["rates"].get("CNY", 0)
            
            return (
                f"💱 **Tỷ giá hôm nay**\n\n"
                f"🇺🇸 1 USD = **{vnd:,.0f}** VND\n"
                f"🇪🇺 1 EUR = **{vnd * eur:,.0f}** VND\n"
                f"🇬🇧 1 GBP = **{vnd * gbp:,.0f}** VND\n"
                f"🇯🇵 100 JPY = **{vnd * 100 / jpy:,.0f}** VND\n"
                f"🇨🇳 1 CNY = **{vnd / cny:,.0f}** VND\n\n"
                f"📊 Nguồn: exchangerate-api.com"
            )
        except Exception as e:
            logger.error(f"Exchange rate error: {e}")
            return None

vietnam_services = VietnamServices()

class AIClient:
    """Handle AI text generation"""
    
    def __init__(self):
        self.client = None
        if config.VERCEL_API_KEY:
            self.client = OpenAI(
                api_key=config.VERCEL_API_KEY,
                base_url=config.BASE_URL,
                timeout=config.REQUEST_TIMEOUT
            )
    
    async def generate_image(self, prompt: str) -> Optional[bytes]:
        """Generate image using FLUX via Vercel API"""
        if not self.client:
            return None
        
        try:
            # Enhance prompt
            enhanced = f"{prompt}, masterpiece, high quality, detailed, 8k"
            
            response = await asyncio.to_thread(
                self.client.images.generate,
                model=config.IMAGE_GEN_MODEL,
                prompt=enhanced,
                n=1,
                size="1024x1024"
            )
            
            if response.data:
                image_url = response.data[0].url
                async with aiohttp.ClientSession() as session:
                    async with session.get(image_url, timeout=30) as resp:
                        if resp.status == 200:
                            return await resp.read()
                        
        except Exception as e:
            logger.error(f"Image generation error: {e}")
        
        return None
    
    def stream_complete(
        self,
        model: str,
        messages: List[Dict[str, str]],
        max_tokens: int,
        temperature: float = 0.7
    ):
        if not self.client:
            yield "❌ Thiếu VERCEL_API_KEY"
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
            logger.error(f"Stream error: {e}")
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
            return "❌ Thiếu VERCEL_API_KEY"
        
        # Check cache
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
                last_error = "Timeout"
            except Exception as e:
                last_error = str(e)
                
            if attempt < retries - 1:
                await asyncio.sleep(2 ** attempt + random.random())
        
        raise Exception(f"Failed after {retries} attempts: {last_error}")
    
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
    def chunk_text(text: str, max_length: int = 4096) -> List[str]:
        """Split text into chunks for Telegram"""
        if len(text) <= max_length:
            return [text]
        
        chunks = []
        lines = text.split('\n')
        current = ""
        
        for line in lines:
            if len(current) + len(line) + 1 > max_length:
                if current:
                    chunks.append(current)
                current = line[:max_length]
            else:
                current = current + '\n' + line if current else line
        
        if current:
            chunks.append(current)
        
        return chunks

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
                return None, "📦 File nén - giải nén trước khi gửi"
            
            elif file_type == FileType.PDF:
                if not PyPDF2:
                    return None, "❌ Cần cài PyPDF2 để đọc PDF"
                return FileProcessor._read_pdf(data), "pdf"
            
            elif file_type == FileType.DOCX:
                if not docx:
                    return None, "❌ Cần cài python-docx để đọc Word"
                return FileProcessor._read_docx(data), "docx"
            
            elif file_type == FileType.XLSX:
                if not openpyxl:
                    return None, "❌ Cần cài openpyxl để đọc Excel"
                return FileProcessor._read_excel(data), "xlsx"
            
            elif file_type == FileType.PPTX:
                if not Presentation:
                    return None, "❌ Cần cài python-pptx để đọc PowerPoint"
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
                return None, f"❌ File {filename} không được hỗ trợ"
                
        except Exception as e:
            logger.error(f"File processing error: {e}")
            return None, f"❌ Lỗi: {str(e)[:100]}"
    
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
        for page in pdf_reader.pages:
            text.append(page.extract_text())
        return '\n'.join(text)
    
    @staticmethod
    def _read_docx(data: bytes) -> str:
        doc_file = io.BytesIO(data)
        doc = DocxDocument(doc_file)
        return '\n'.join([p.text for p in doc.paragraphs])
    
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
        for i, slide in enumerate(prs.slides, 1):
            text.append(f"=== Slide {i} ===")
            for shape in slide.shapes:
                if hasattr(shape, "text") and shape.text.strip():
                    text.append(shape.text)
        return '\n'.join(text)

file_processor = FileProcessor()

class MessageBuilder:
    @staticmethod
    def build_system_prompt(context_type: str = "chat") -> str:
        time_info = vietnam_services.get_vietnam_time()
        
        base = (
            f"Bạn là Linh - AI Assistant thông minh của Việt Nam.\n"
            f"Thời gian hiện tại: {time_info['time']} {time_info['date']}\n"
            f"Developer: @cucodoivandep\n\n"
        )
        
        if context_type == "chat":
            return base + (
                "Kiến thức:\n"
                "• Văn hóa, lịch sử, địa lý Việt Nam\n"
                "• Ẩm thực, du lịch Việt Nam\n"
                "• Công nghệ, khoa học\n"
                "• Thời tiết, khí hậu các vùng miền\n\n"
                "Phong cách:\n"
                "• Thân thiện, vui vẻ\n"
                "• Trả lời ngắn gọn, chính xác\n"
                "• Dùng emoji phù hợp\n"
                "• Ưu tiên thông tin về Việt Nam"
            )
        
        elif context_type == "weather":
            return base + (
                "Bạn là chuyên gia dự báo thời tiết Việt Nam.\n\n"
                "Nhiệm vụ:\n"
                "• Cung cấp thông tin thời tiết chi tiết cho các thành phố Việt Nam\n"
                "• Dự báo xu hướng thời tiết\n"
                "• Tư vấn hoạt động phù hợp với thời tiết\n"
                "• Cảnh báo thiên tai nếu cần\n\n"
                "Lưu ý:\n"
                "• Việt Nam có 3 miền với khí hậu khác nhau\n"
                "• Miền Bắc: 4 mùa rõ rệt\n"
                "• Miền Trung: Mùa mưa từ tháng 9-12\n"
                "• Miền Nam: Mùa mưa từ tháng 5-11"
            )
        
        elif context_type == "code":
            return base + (
                "Bạn là lập trình viên chuyên nghiệp.\n\n"
                "Nguyên tắc:\n"
                "• Code clean, optimal\n"
                "• Comment rõ ràng\n"
                "• Best practices\n"
                "• Xử lý errors đầy đủ"
            )
        
        elif context_type == "file":
            return base + (
                "Xử lý file chuyên nghiệp.\n\n"
                "Tasks:\n"
                "• Phân tích nội dung\n"
                "• Tóm tắt key points\n"
                "• Trả lời câu hỏi\n"
                "• Đề xuất cải thiện"
            )
        
        return base
    
    @staticmethod
    def build_messages(
        chat_id: int,
        user_text: str,
        context_type: str = "chat",
        include_history: bool = True
    ) -> List[Dict[str, str]]:
        messages = []
        
        # System prompt
        messages.append({
            "role": "system",
            "content": MessageBuilder.build_system_prompt(context_type)
        })
        
        # History
        if include_history:
            user = bot_state.get_user(chat_id)
            keep_turns = config.CTX_TURNS * 2
            
            for role, content in list(user.history)[-keep_turns:]:
                truncated = content[:500] + "..." if len(content) > 500 else content
                messages.append({
                    "role": "user" if role == "user" else "assistant",
                    "content": truncated
                })
        
        # Current message
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
    """Stream AI response with live updates"""
    msg = await context.bot.send_message(chat_id, "💭 Đang suy nghĩ...")
    
    full_response = ""
    buffer = ""
    counter = 0
    
    async def update_message():
        nonlocal buffer
        try:
            if buffer:
                await msg.edit_text(buffer[:4096])
        except:
            pass
    
    try:
        stream = await asyncio.to_thread(
            ai_client.stream_complete,
            model, messages, max_tokens, temperature
        )
        
        for chunk in stream:
            full_response += chunk
            buffer += chunk
            counter += 1
            
            # Update every 5 chunks
            if counter % 5 == 0 and len(buffer) > 100:
                await update_message()
        
        # Final update
        if full_response:
            chunks = text_processor.chunk_text(full_response)
            
            if len(chunks) == 1:
                await msg.edit_text(chunks[0])
            else:
                await msg.delete()
                for i, chunk in enumerate(chunks, 1):
                    await context.bot.send_message(
                        chat_id,
                        f"📄 Phần {i}/{len(chunks)}:\n\n{chunk}"
                    )
        
        return full_response
        
    except Exception as e:
        logger.error(f"Stream response error: {e}")
        await msg.edit_text(f"❌ Lỗi: {str(e)[:200]}")
        return None

# Command Handlers
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
🇻🇳 **LINH AI - TRỢ LÝ VIỆT NAM**

📝 **Lệnh cơ bản:**
• /help - Hướng dẫn
• /start - Khởi động
• /clear - Xóa lịch sử
• /stats - Thống kê

💻 **AI Features:**
• /code <yêu cầu> - Viết code
• /img <mô tả> - Tạo ảnh AI
• Chat trực tiếp để hỏi đáp

🇻🇳 **Việt Nam:**
• /weather <city> - Thời tiết (AI)
• /exchange - Tỷ giá
• /time - Giờ Việt Nam
• /translate <text> - Dịch Anh-Việt

📄 **File:**
• Gửi file để xử lý (PDF, Word, Excel...)
• /sendfile - Tải kết quả
• /cancelfile - Hủy file mode

💡 **Tips:**
• img: <prompt> - Tạo ảnh nhanh
• Hỏi về văn hóa, ẩm thực, du lịch VN
• Hỏi thời tiết bất kỳ thành phố VN

⚙️ **Models:**
• Chat: Claude-3.5-Haiku
• Code: Claude-3.5-Sonnet
• Image: FLUX-Schnell

👨‍💻 Dev: @cucodoivandep
    """
    
    await context.bot.send_message(
        update.effective_chat.id,
        help_text,
        parse_mode=ParseMode.MARKDOWN
    )

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    time_info = vietnam_services.get_vietnam_time()
    
    welcome = f"""
🇻🇳 **Xin chào! Mình là Linh - AI Assistant Việt Nam**

{time_info['greeting']}! 🌟

🎯 **Mình có thể giúp:**
• 💬 Chat, tư vấn mọi chủ đề
• 💻 Viết code, debug
• 🎨 Tạo ảnh từ text
• 📄 Xử lý file, documents
• 🇻🇳 Thông tin Việt Nam
• ☀️ Dự báo thời tiết

💡 **Thử ngay:**
• "Thời tiết Hà Nội hôm nay thế nào?"
• "Cho tôi công thức nấu phở bò"
• /img phong cảnh vịnh Hạ Long

Chúc bạn một ngày tốt lành! 🌺
    """
    
    if time_info['holiday']:
        welcome += f"\n\n🎉 Hôm nay là: **{time_info['holiday']}**"
    
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📖 Hướng dẫn", callback_data="help"),
            InlineKeyboardButton("🇻🇳 Về VN", callback_data="vietnam")
        ],
        [
            InlineKeyboardButton("💬 Bắt đầu chat", callback_data="chat")
        ]
    ])
    
    await context.bot.send_message(
        update.effective_chat.id,
        welcome,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard
    )

async def cmd_weather(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get weather using AI"""
    chat_id = update.effective_chat.id
    
    if not context.args:
        cities = ", ".join(VIETNAM_CITIES.keys())
        await context.bot.send_message(
            chat_id,
            f"☀️ **Thời tiết (AI dự báo)**\n\n"
            f"Cú pháp: /weather <city>\n\n"
            f"Cities: {cities}\n\n"
            f"💡 Hoặc hỏi trực tiếp: 'Thời tiết Sài Gòn hôm nay?'",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    city_name = " ".join(context.args)
    
    # Get current time info
    time_info = vietnam_services.get_vietnam_time()
    
    # Build weather query for AI
    weather_prompt = f"""
    Hãy dự báo thời tiết cho {city_name} hôm nay ({time_info['date']}).
    
    Thông tin cần có:
    - Nhiệt độ (cao nhất, thấp nhất)
    - Tình trạng thời tiết (nắng/mưa/nhiều mây)
    - Độ ẩm
    - Gió
    - Chỉ số UV
    - Lời khuyên cho hoạt động ngoài trời
    
    Lưu ý:
    - Đây là tháng {time_info['datetime'].month} tại Việt Nam
    - Trả lời ngắn gọn, dùng emoji phù hợp
    - Nếu không phải thành phố Việt Nam, vẫn cố gắng trả lời
    """
    
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    
    # Build messages with weather context
    messages = message_builder.build_messages(
        chat_id,
        weather_prompt,
        context_type="weather",
        include_history=False
    )
    
    # Get AI response
    result = await stream_response(
        context,
        chat_id,
        config.CHAT_MODEL,
        messages,
        config.MAX_TOKENS,
        temperature=0.7
    )
    
    if result:
        user = bot_state.get_user(chat_id)
        user.history.append(("user", f"Thời tiết {city_name}"))
        user.history.append(("assistant", result[:500]))

async def cmd_img(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate image from text"""
    chat_id = update.effective_chat.id
    prompt = " ".join(context.args).strip()
    
    if not prompt:
        examples = [
            "vịnh Hạ Long lúc hoàng hôn",
            "phở bò Hà Nội",
            "áo dài Việt Nam",
            "phố cổ Hội An",
            "ruộng bậc thang Sapa"
        ]
        
        await context.bot.send_message(
            chat_id,
            "🎨 **Tạo ảnh AI**\n\n"
            f"Cú pháp: /img <mô tả>\n\n"
            f"**Ví dụ:**\n" + "\n".join([f"• /img {e}" for e in examples]),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    if not config.VERCEL_API_KEY:
        await context.bot.send_message(
            chat_id,
            "❌ Cần VERCEL_API_KEY để tạo ảnh"
        )
        return
    
    # Send typing action
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
    
    # Status message
    status = await context.bot.send_message(
        chat_id,
        f"🎨 Đang tạo: _{prompt}_\n⏳ Vui lòng chờ 10-30 giây...",
        parse_mode=ParseMode.MARKDOWN
    )
    
    try:
        # Generate image
        image_data = await ai_client.generate_image(prompt)
        
        if image_data:
            await status.delete()
            await context.bot.send_photo(
                chat_id,
                photo=io.BytesIO(image_data),
                caption=f"🎨 {prompt}\n\n💡 Mẹo: Dùng 'img: {prompt}' để tạo nhanh"
            )
            
            # Save to history
            user = bot_state.get_user(chat_id)
            user.history.append(("user", f"/img {prompt}"))
            user.history.append(("assistant", f"Đã tạo ảnh: {prompt}"))
        else:
            await status.edit_text(
                "❌ Không thể tạo ảnh\n\n"
                "💡 Thử:\n"
                "• Mô tả chi tiết hơn\n"
                "• Dùng tiếng Anh\n"
                "• Tránh nội dung nhạy cảm"
            )
            
    except Exception as e:
        logger.error(f"Image generation error: {e}")
        await status.edit_text(f"❌ Lỗi: {str(e)[:100]}")

async def cmd_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate code"""
    chat_id = update.effective_chat.id
    request = " ".join(context.args).strip()
    
    if not request:
        examples = [
            "game snake Python",
            "validate email regex",
            "REST API Flask",
            "React todo app",
            "quicksort C++"
        ]
        
        await context.bot.send_message(
            chat_id,
            "💻 **Viết Code**\n\n"
            f"Cú pháp: /code <yêu cầu>\n\n"
            f"**Ví dụ:**\n" + "\n".join([f"• /code {e}" for e in examples]),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    
    # Build messages
    messages = message_builder.build_messages(
        chat_id,
        request,
        context_type="code",
        include_history=False
    )
    
    # Generate
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
        user.history.append(("assistant", result[:500]))

async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clear user data"""
    chat_id = update.effective_chat.id
    user = bot_state.get_user(chat_id)
    
    user.history.clear()
    user.file_mode = False
    user.pending_file = None
    user.last_result = ""
    
    await context.bot.send_message(
        chat_id,
        "✅ **Đã xóa:**\n"
        "• Lịch sử chat\n"
        "• File lưu\n"
        "• Kết quả"
    )

async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show statistics"""
    chat_id = update.effective_chat.id
    user = bot_state.get_user(chat_id)
    
    time_info = vietnam_services.get_vietnam_time()
    
    stats = f"""
📊 **Thống kê**

👤 User: {update.effective_user.first_name}
🆔 ID: `{chat_id}`
💬 Lịch sử: {len(user.history)} tin
📁 File mode: {'Bật' if user.file_mode else 'Tắt'}

⚙️ **Models:**
• Chat: {config.CHAT_MODEL}
• Code: {config.CODE_MODEL}

🇻🇳 **Giờ Việt Nam:**
• {time_info['time']} {time_info['date']}
• {time_info['greeting']}
    """
    
    if time_info['holiday']:
        stats += f"\n• 🎉 {time_info['holiday']}"
    
    await context.bot.send_message(
        chat_id,
        stats,
        parse_mode=ParseMode.MARKDOWN
    )

async def cmd_exchange(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get exchange rates"""
    chat_id = update.effective_chat.id
    
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    
    # Try to get real exchange rate
    rates = await vietnam_services.get_exchange_rate()
    
    if rates:
        await context.bot.send_message(
            chat_id,
            rates,
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        # Use AI as fallback
        messages = [
            {"role": "system", "content": "Bạn là chuyên gia tài chính. Cung cấp tỷ giá ước tính USD/VND và các ngoại tệ phổ biến."},
            {"role": "user", "content": "Cho tôi tỷ giá ngoại tệ hôm nay với VND"}
        ]
        
        result = await ai_client.complete(
            config.CHAT_MODEL,
            messages,
            500,
            temperature=0.7
        )
        
        await context.bot.send_message(
            chat_id,
            f"💱 **Tỷ giá (ước tính)**\n\n{result}",
            parse_mode=ParseMode.MARKDOWN
        )

async def cmd_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get Vietnam time"""
    chat_id = update.effective_chat.id
    time_info = vietnam_services.get_vietnam_time()
    
    time_text = f"""
🇻🇳 **Giờ Việt Nam**

📅 {time_info['day_name']}, {time_info['date']}
🕐 {time_info['time']} (GMT+7)

{time_info['greeting']}! 🌟
    """
    
    if time_info['holiday']:
        time_text += f"\n\n🎉 **{time_info['holiday']}**"
    
    # Add some contextual info based on time
    hour = time_info['hour']
    if 6 <= hour < 9:
        time_text += "\n\n☕ Giờ uống cà phê sáng!"
    elif 11 <= hour < 14:
        time_text += "\n\n🍜 Giờ ăn trưa!"
    elif 17 <= hour < 20:
        time_text += "\n\n🍽 Giờ ăn tối!"
    elif 22 <= hour or hour < 5:
        time_text += "\n\n😴 Giờ ngủ ngon!"
    
    await context.bot.send_message(
        chat_id,
        time_text,
        parse_mode=ParseMode.MARKDOWN
    )

async def cmd_translate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Translate English to Vietnamese"""
    chat_id = update.effective_chat.id
    text = " ".join(context.args).strip()
    
    if not text:
        await context.bot.send_message(
            chat_id,
            "🔤 **Dịch Anh-Việt**\n\n"
            "Cú pháp: /translate <text>\n\n"
            "Ví dụ: /translate Hello world",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    messages = [
        {"role": "system", "content": "Bạn là chuyên gia dịch thuật. Dịch sang tiếng Việt tự nhiên, chính xác. Chỉ trả về bản dịch."},
        {"role": "user", "content": f"Translate to Vietnamese:\n{text}"}
    ]
    
    result = await ai_client.complete(
        config.CHAT_MODEL,
        messages,
        500,
        temperature=0.3
    )
    
    await context.bot.send_message(
        chat_id,
        f"🔤 **Original:**\n{text}\n\n"
        f"🇻🇳 **Tiếng Việt:**\n{result}",
        parse_mode=ParseMode.MARKDOWN
    )

async def cmd_sendfile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send last result as file"""
    chat_id = update.effective_chat.id
    user = bot_state.get_user(chat_id)
    
    if not user.last_result:
        await context.bot.send_message(
            chat_id,
            "❌ Không có kết quả"
        )
        return
    
    file_io = io.BytesIO(user.last_result.encode('utf-8'))
    file_io.name = f"result_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    
    await context.bot.send_document(
        chat_id,
        document=file_io,
        caption="📄 Kết quả"
    )

async def cmd_cancelfile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel file mode"""
    chat_id = update.effective_chat.id
    user = bot_state.get_user(chat_id)
    
    user.file_mode = False
    user.pending_file = None
    
    await context.bot.send_message(
        chat_id,
        "✅ Đã thoát file mode"
    )

# Message Handlers
async def on_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle file uploads"""
    chat_id = update.effective_chat.id
    document = update.message.document
    
    if not document:
        return
    
    if document.file_size > 20 * 1024 * 1024:
        await context.bot.send_message(
            chat_id,
            "❌ File quá lớn (max 20MB)"
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
            await context.bot.send_message(chat_id, file_type)
            return
        
        # Save to user state
        user = bot_state.get_user(chat_id)
        user.file_mode = True
        user.pending_file = {
            "name": document.file_name,
            "content": content[:config.CHUNK_CHARS],
            "type": file_type
        }
        
        # Preview
        preview = content[:500] + "..." if len(content) > 500 else content
        
        await context.bot.send_message(
            chat_id,
            f"✅ **File nhận được**\n\n"
            f"📄 Tên: {document.file_name}\n"
            f"📊 Loại: {file_type}\n"
            f"📝 Size: {len(content):,} ký tự\n\n"
            f"**Preview:**\n```\n{preview}\n```\n\n"
            f"💬 Hỏi về file hoặc /cancelfile",
            parse_mode=ParseMode.MARKDOWN
        )
        
    except Exception as e:
        logger.error(f"File handling error: {e}")
        await context.bot.send_message(
            chat_id,
            f"❌ Lỗi: {str(e)[:100]}"
        )

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages"""
    chat_id = update.effective_chat.id
    text = (update.message.text or "").strip()
    
    if not text:
        return
    
    # Quick image generation
    if text.lower().startswith("img:"):
        prompt = text[4:].strip()
        context.args = prompt.split()
        await cmd_img(update, context)
        return
    
    # Check for weather queries
    weather_keywords = ["thời tiết", "weather", "nhiệt độ", "mưa", "nắng", "gió", "độ ẩm"]
    if any(keyword in text.lower() for keyword in weather_keywords):
        # Extract city name if mentioned
        for city in VIETNAM_CITIES.keys():
            if city in text.lower() or VIETNAM_CITIES[city]["name"].lower() in text.lower():
                context.args = [city]
                await cmd_weather(update, context)
                return
        
        # If no specific city, ask AI about weather in general
        messages = message_builder.build_messages(
            chat_id,
            text,
            context_type="weather",
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
            user = bot_state.get_user(chat_id)
            user.last_result = result
            user.history.append(("user", text[:500]))
            user.history.append(("assistant", result[:500]))
        return
    
    user = bot_state.get_user(chat_id)
    
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    
    # File mode
    if user.file_mode and user.pending_file:
        file_info = user.pending_file
        prompt = (
            f"File: {file_info['name']}\n"
            f"Content:\n{file_info['content'][:10000]}\n\n"
            f"Question: {text}"
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
        # Normal chat
        messages = message_builder.build_messages(
            chat_id,
            text,
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
        user.history.append(("user", text[:500]))
        user.history.append(("assistant", result[:500]))

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle callback queries"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "help":
        await cmd_help(update, context)
    
    elif query.data == "vietnam":
        info = """
🇻🇳 **VIỆT NAM TÔI YÊU**

🏛 **Lịch sử:**
• 4000 năm văn hiến
• Kinh đô: Thăng Long - Hà Nội
• Độc lập: 2/9/1945

🌏 **Địa lý:**
• Diện tích: 331,212 km²
• Dân số: ~98 triệu
• 63 tỉnh thành
• 3260km bờ biển

🎭 **Văn hóa:**
• 54 dân tộc anh em
• 8 Di sản UNESCO
• Ẩm thực phong phú
• Tết Nguyên Đán

🏆 **Thành tựu:**
• Top 20 kinh tế thế giới
• Xuất khẩu gạo số 2
• Du lịch phát triển
• Công nghệ bùng nổ

💪 Việt Nam - Vươn tầm thế giới!
        """
        await context.bot.send_message(
            query.message.chat_id,
            info,
            parse_mode=ParseMode.MARKDOWN
        )
    
    elif query.data == "chat":
        await context.bot.send_message(
            query.message.chat_id,
            "💬 Sẵn sàng! Hãy chat với mình nhé.\n\n"
            "💡 Thử hỏi:\n"
            "• Thời tiết Hà Nội thế nào?\n"
            "• Cho tôi công thức phở bò\n"
            "• Kể về lịch sử Việt Nam\n"
            "• Địa điểm du lịch Đà Nẵng"
        )

def main():
    if not config.BOT_TOKEN:
        print("❌ Missing BOT_TOKEN")
        return
    
    print("=" * 50)
    print("🇻🇳 LINH BOT - AI Assistant Vietnam")
    print("=" * 50)
    
    if not config.VERCEL_API_KEY:
        print("⚠️  No VERCEL_API_KEY - Limited features")
    else:
        print("✅ Vercel API: Ready")
    
    print("=" * 50)
    
    app = ApplicationBuilder().token(config.BOT_TOKEN).build()
    
    # Commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("clear", cmd_clear))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("img", cmd_img))
    app.add_handler(CommandHandler("code", cmd_code))
    app.add_handler(CommandHandler("weather", cmd_weather))
    app.add_handler(CommandHandler("exchange", cmd_exchange))
    app.add_handler(CommandHandler("time", cmd_time))
    app.add_handler(CommandHandler("translate", cmd_translate))
    app.add_handler(CommandHandler("sendfile", cmd_sendfile))
    app.add_handler(CommandHandler("cancelfile", cmd_cancelfile))
    
    # Callbacks
    app.add_handler(CallbackQueryHandler(on_callback))
    
    # Messages
    app.add_handler(MessageHandler(filters.Document.ALL, on_file))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    
    print("🚀 Bot running...")
    print("💬 Chat: Claude-3.5")
    print("🎨 Image: FLUX via Vercel")
    print("☀️ Weather: AI-powered")
    print("👨‍💻 Dev: @cucodoivandep")
    print("=" * 50)
    
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
