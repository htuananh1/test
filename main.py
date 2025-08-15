import os
import random
import asyncio
import logging
import requests
import json
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

# Cấu hình
BOT_TOKEN = os.environ["BOT_TOKEN"]
VERCEL_API_KEY = os.environ.get("VERCEL_API_KEY", "")
BASE_URL = os.getenv("BASE_URL", "https://ai-gateway.vercel.sh/v1")
CHAT_MODEL = os.getenv("CHAT_MODEL", "anthropic/claude-3-haiku")
PAGE_CHARS = int(os.getenv("PAGE_CHARS", "3200"))
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "700"))
MAX_TOKENS_CODE = int(os.getenv("MAX_TOKENS_CODE", "4000"))
CTX_TURNS = int(os.getenv("CTX_TURNS", "15"))
WEATHER_API_KEY = os.environ.get("WEATHER_API_KEY", "")

# Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Database setup
def init_db():
    """Khởi tạo database để lưu điểm"""
    conn = sqlite3.connect('bot_scores.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS scores (
            user_id INTEGER,
            username TEXT,
            game_type TEXT,
            score INTEGER,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# Lưu trữ game sessions và chat history
active_games: Dict[int, dict] = {}
chat_history: Dict[int, List[dict]] = {}
vietnamese_words: set = set()
quiz_sessions: Dict[int, dict] = {}

# Load từ điển tiếng Việt
def load_vietnamese_dictionary():
    """Load từ điển tiếng Việt từ URL"""
    global vietnamese_words
    try:
        response = requests.get("https://raw.githubusercontent.com/undertheseanlp/dictionary/refs/heads/hongocduc/data/Viet74K.txt")
        if response.status_code == 200:
            words = response.text.strip().split('\n')
            vietnamese_words = {word.lower().strip() for word in words if word.strip() and len(word.strip()) > 1}
            logger.info(f"Loaded {len(vietnamese_words)} Vietnamese words")
        else:
            logger.error("Failed to load Vietnamese dictionary")
    except Exception as e:
        logger.error(f"Error loading dictionary: {e}")

# Load từ điển khi khởi động
load_vietnamese_dictionary()

def save_score(user_id: int, username: str, game_type: str, score: int):
    """Lưu điểm vào database"""
    conn = sqlite3.connect('bot_scores.db')
    c = conn.cursor()
    c.execute('INSERT INTO scores (user_id, username, game_type, score) VALUES (?, ?, ?, ?)',
              (user_id, username, game_type, score))
    conn.commit()
    conn.close()

def get_leaderboard(game_type: str, limit: int = 10) -> List[tuple]:
    """Lấy bảng xếp hạng"""
    conn = sqlite3.connect('bot_scores.db')
    c = conn.cursor()
    c.execute('''
        SELECT username, MAX(score) as best_score
        FROM scores
        WHERE game_type = ?
        GROUP BY user_id
        ORDER BY best_score DESC
        LIMIT ?
    ''', (game_type, limit))
    results = c.fetchall()
    conn.close()
    return results

class GuessNumberGame:
    def __init__(self, chat_id: int, use_ai: bool = False):
        self.chat_id = chat_id
        self.attempts = 0
        self.max_attempts = 10
        self.hints_used = 0
        self.max_hints = 3
        self.start_time = datetime.now()
        self.use_ai = use_ai
        self.score = 1000  # Điểm khởi đầu
        
        if use_ai:
            # AI tạo số bí mật và câu đố
            self.secret_number, self.riddle = self.generate_ai_number()
        else:
            # Script tạo số ngẫu nhiên
            self.secret_number = random.randint(1, 100)
            self.riddle = self.generate_riddle()
            
    def generate_ai_number(self) -> Tuple[int, str]:
        """AI tạo số và câu đố"""
        # Tạm thời dùng random, có thể tích hợp AI sau
        number = random.randint(1, 100)
        riddle = self.generate_riddle_for_number(number)
        return number, riddle
        
    def generate_riddle(self) -> str:
        """Tạo câu đố cho số bí mật"""
        if self.secret_number % 2 == 0:
            riddle = "Số bí mật là số chẵn"
        else:
            riddle = "Số bí mật là số lẻ"
            
        if self.secret_number < 50:
            riddle += " và nhỏ hơn 50"
        else:
            riddle += " và lớn hơn hoặc bằng 50"
            
        return riddle
        
    def generate_riddle_for_number(self, number: int) -> str:
        """Tạo câu đố cụ thể cho một số"""
        riddles = []
        
        # Tính chất cơ bản
        if number % 2 == 0:
            riddles.append("là số chẵn")
        else:
            riddles.append("là số lẻ")
            
        # Khoảng giá trị
        if number <= 25:
            riddles.append("nằm trong khoảng 1-25")
        elif number <= 50:
            riddles.append("nằm trong khoảng 26-50")
        elif number <= 75:
            riddles.append("nằm trong khoảng 51-75")
        else:
            riddles.append("nằm trong khoảng 76-100")
            
        # Tính chất đặc biệt
        if number % 5 == 0:
            riddles.append("chia hết cho 5")
        if number % 10 == 0:
            riddles.append("chia hết cho 10")
        if self.is_prime(number):
            riddles.append("là số nguyên tố")
            
        return f"Số bí mật {' và '.join(riddles[:2])}"
        
    def is_prime(self, n: int) -> bool:
        """Kiểm tra số nguyên tố"""
        if n < 2:
            return False
        for i in range(2, int(n**0.5) + 1):
            if n % i == 0:
                return False
        return True
        
    def get_hint(self) -> str:
        """Đưa ra gợi ý"""
        if self.hints_used >= self.max_hints:
            return "❌ Bạn đã dùng hết số lần gợi ý!"
            
        self.hints_used += 1
        self.score -= 100  # Trừ điểm khi dùng gợi ý
        
        hints = []
        
        # Gợi ý 1: Chữ số hàng chục
        if self.hints_used == 1:
            tens = self.secret_number // 10
            if tens == 0:
                hints.append("💡 Gợi ý 1: Số bí mật có 1 chữ số")
            else:
                hints.append(f"💡 Gợi ý 1: Chữ số hàng chục là {tens}")
                
        # Gợi ý 2: Tổng các chữ số
        elif self.hints_used == 2:
            digit_sum = sum(int(d) for d in str(self.secret_number))
            hints.append(f"💡 Gợi ý 2: Tổng các chữ số là {digit_sum}")
            
        # Gợi ý 3: Khoảng cụ thể
        elif self.hints_used == 3:
            lower = (self.secret_number // 10) * 10
            upper = lower + 9
            if lower == 0:
                hints.append(f"💡 Gợi ý 3: Số nằm trong khoảng 1-9")
            else:
                hints.append(f"💡 Gợi ý 3: Số nằm trong khoảng {lower}-{upper}")
                
        return f"{hints[0]}\n\n🎯 Còn {self.max_hints - self.hints_used} gợi ý"
        
    def make_guess(self, guess: int) -> Tuple[bool, str]:
        self.attempts += 1
        self.score -= 50  # Trừ điểm mỗi lần đoán
        
        if guess == self.secret_number:
            time_taken = (datetime.now() - self.start_time).seconds
            final_score = max(self.score, 100)  # Điểm tối thiểu là 100
            return True, f"🎉 Chúc mừng! Bạn đã đoán đúng số {self.secret_number} sau {self.attempts} lần thử trong {time_taken} giây!\n\n🏆 Điểm: {final_score}"
            
        if self.attempts >= self.max_attempts:
            return True, f"😢 Hết lượt! Số bí mật là {self.secret_number}.\n\n💡 Câu đố: {self.riddle}\n\nChơi lại với /guessnumber"
            
        hint = "📈 cao hơn" if guess < self.secret_number else "📉 thấp hơn"
        remaining = self.max_attempts - self.attempts
        return False, f"Số {guess} {hint}!\n\n📊 Còn {remaining} lượt\n💰 Điểm hiện tại: {self.score}\n\n💡 Gửi /hint để xem gợi ý (trừ 100 điểm)"

class NoiTuGame:
    def __init__(self, chat_id: int):
        self.chat_id = chat_id
        self.history = []
        self.score = 0
        self.current_word = ""
        self.start_time = datetime.now()
        self.player_words = 0
        self.bot_words = 0
        # Chọn từ bắt đầu phổ biến
        common_starts = ["con", "người", "bầu", "trời", "mặt", "đất", "nước", "tình", "yêu", "cuộc", "sống", "gia", "đình", "nhà", "cửa", "bạn", "thân"]
        self.start_words = [w for w in common_starts if w in vietnamese_words]
        
    def start(self) -> str:
        self.current_word = random.choice(self.start_words)
        self.history = [self.current_word]
        return f"""🎮 **Trò chơi Nối Từ**

📖 Luật chơi:
- Nối từ tiếng Việt có trong từ điển
- Từ mới phải bắt đầu bằng chữ cái cuối của từ trước
- Không được lặp lại từ đã dùng
- Gõ 'thua' để kết thúc

🎯 Từ đầu tiên: **{self.current_word}**

Hãy nối từ bắt đầu bằng chữ '{self.current_word[-1]}'"""
        
    def play_word(self, word: str) -> Tuple[bool, str]:
        word = word.lower().strip()
        
        # Kiểm tra người chơi đầu hàng
        if word == "thua":
            time_taken = (datetime.now() - self.start_time).seconds
            return True, f"""🏁 Kết thúc trò chơi!

📊 Thống kê:
- Điểm: {self.score}
- Thời gian: {time_taken} giây
- Tổng số từ: {len(self.history)}
- Từ của bạn: {self.player_words}
- Từ của bot: {self.bot_words}

Chơi lại với /noitu"""
        
        # Kiểm tra từ hợp lệ
        if not word:
            return False, "❌ Vui lòng nhập một từ!"
            
        if word[0] != self.current_word[-1]:
            return False, f"❌ Từ phải bắt đầu bằng chữ '{self.current_word[-1]}'"
            
        if word in self.history:
            return False, "❌ Từ này đã được sử dụng!"
            
        # Kiểm tra từ có trong từ điển
        if word not in vietnamese_words:
            return False, "❌ Từ không có trong từ điển tiếng Việt!"
            
        # Từ hợp lệ
        self.history.append(word)
        self.current_word = word
        self.player_words += 1
        points = len(word) * 10
        self.score += points
        
        # Bot nối từ
        bot_word = self.find_bot_word(word[-1])
        if bot_word:
            self.history.append(bot_word)
            self.current_word = bot_word
            self.bot_words += 1
            return False, f"""✅ Tốt! (+{points} điểm)

🤖 Tôi nối: **{bot_word}**

📊 Điểm: {self.score} | Số từ: {len(self.history)}

Lượt của bạn, chữ '{bot_word[-1]}'"""
        else:
            # Bot không nối được
            time_taken = (datetime.now() - self.start_time).seconds
            self.score += 500  # Bonus thắng
            return True, f"""🎉 Xuất sắc! Bot không nối được!

🏆 **BẠN THẮNG!**

📊 Thống kê:
- Điểm: {self.score} (bonus +500)
- Thời gian: {time_taken} giây
- Tổng số từ: {len(self.history)}
- Từ của bạn: {self.player_words}
- Từ của bot: {self.bot_words}"""
            
    def find_bot_word(self, start_char: str) -> Optional[str]:
        """Tìm từ cho bot nối - ưu tiên từ dễ để game cân bằng"""
        available_words = [
            word for word in vietnamese_words 
            if word.startswith(start_char) and word not in self.history and len(word) <= 7
        ]
        
        if not available_words:
            # Thử tìm từ dài hơn nếu không có từ ngắn
            available_words = [
                word for word in vietnamese_words 
                if word.startswith(start_char) and word not in self.history
            ]
        
        if available_words:
            # Chọn ngẫu nhiên trong top 20 từ
            return random.choice(available_words[:20])
        return None

async def call_vercel_api(messages: List[dict], max_tokens: int = 700) -> str:
    """Gọi Vercel AI Gateway API"""
    try:
        headers = {
            "Authorization": f"Bearer {VERCEL_API_KEY}",
            "Content-Type": "application/json"
        }
        
        data = {
            "model": CHAT_MODEL,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.7
        }
        
        response = requests.post(
            f"{BASE_URL}/chat/completions",
            headers=headers,
            json=data,
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            return result['choices'][0]['message']['content']
        else:
            logger.error(f"API error: {response.status_code} - {response.text}")
            return "Xin lỗi, tôi gặp lỗi khi xử lý. Vui lòng thử lại sau."
            
    except Exception as e:
        logger.error(f"API call error: {e}")
        return "Xin lỗi, có lỗi xảy ra. Vui lòng thử lại sau."

async def get_weather(city: str) -> str:
    """Lấy thông tin thời tiết"""
    if not WEATHER_API_KEY:
        # Sử dụng AI để trả lời về thời tiết
        messages = [
            {"role": "system", "content": "Bạn là trợ lý AI thân thiện. Khi được hỏi về thời tiết mà không có dữ liệu thực, hãy trả lời một cách hữu ích và gợi ý người dùng kiểm tra các nguồn thời tiết đáng tin cậy."},
            {"role": "user", "content": f"Thời tiết ở {city} như thế nào?"}
        ]
        return await call_vercel_api(messages)
        
    try:
        # Chuẩn hóa tên thành phố
        city_map = {
            "hà nội": "Hanoi",
            "hồ chí minh": "Ho Chi Minh City", 
            "sài gòn": "Ho Chi Minh City",
            "đà nẵng": "Da Nang",
            "cần thơ": "Can Tho",
            "hải phòng": "Hai Phong",
            "nha trang": "Nha Trang",
            "đà lạt": "Da Lat",
            "huế": "Hue",
            "vũng tàu": "Vung Tau",
            "phú quốc": "Phu Quoc",
            "quy nhơn": "Quy Nhon"
        }
        
        city_query = city_map.get(city.lower(), city)
        
        url = f"https://api.openweathermap.org/data/2.5/weather?q={city_query},VN&appid={WEATHER_API_KEY}&units=metric&lang=vi"
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            
            weather_info = f"""
🌤️ **Thời tiết {data['name']}**

🌡️ Nhiệt độ: {data['main']['temp']}°C (cảm giác như {data['main']['feels_like']}°C)
💨 Gió: {data['wind']['speed']} m/s
💧 Độ ẩm: {data['main']['humidity']}%
☁️ Mây: {data['clouds']['all']}%
🌅 Bình minh: {datetime.fromtimestamp(data['sys']['sunrise']).strftime('%H:%M')}
🌇 Hoàng hôn: {datetime.fromtimestamp(data['sys']['sunset']).strftime('%H:%M')}

📝 {data['weather'][0]['description'].capitalize()}
"""
            return weather_info
        else:
            # Fallback to AI response
            messages = [
                {"role": "system", "content": "Bạn là trợ lý AI. Trả lời về thời tiết một cách hữu ích."},
                {"role": "user", "content": f"Thời tiết ở {city} như thế nào?"}
            ]
            return await call_vercel_api(messages)
            
    except Exception as e:
        logger.error(f"Weather API error: {e}")
        # Fallback to AI response
        messages = [
            {"role": "system", "content": "Bạn là trợ lý AI. Trả lời về thời tiết một cách hữu ích."},
            {"role": "user", "content": f"Thời tiết ở {city} như thế nào?"}
        ]
        return await call_vercel_api(messages)

async def generate_quiz() -> dict:
    """Sử dụng AI để tạo câu đố"""
    prompt = """Hãy tạo một câu đố vui bằng tiếng Việt với format sau:

Câu hỏi: [câu hỏi thú vị về kiến thức tổng quát, ưu tiên về Việt Nam]
A. [đáp án A]
B. [đáp án B]
C. [đáp án C]
D. [đáp án D]
Đáp án: [A/B/C/D]
Giải thích: [giải thích ngắn gọn và thú vị]"""

    messages = [
        {"role": "system", "content": "Bạn là người tạo câu đố thông minh. Tạo câu đố về các chủ đề đa dạng: lịch sử, địa lý, khoa học, văn hóa, đặc biệt là về Việt Nam."},
        {"role": "user", "content": prompt}
    ]
    
    response = await call_vercel_api(messages, max_tokens=500)
    
    # Parse response
    lines = response.strip().split('\n')
    quiz = {
        "question": "",
        "options": [],
        "correct": "",
        "explanation": ""
    }
    
    for line in lines:
        line = line.strip()
        if line.startswith("Câu hỏi:"):
            quiz["question"] = line.replace("Câu hỏi:", "").strip()
        elif line.startswith(("A.", "B.", "C.", "D.")):
            quiz["options"].append(line)
        elif line.startswith("Đáp án:"):
            quiz["correct"] = line.replace("Đáp án:", "").strip()[0]
        elif line.startswith("Giải thích:"):
            quiz["explanation"] = line.replace("Giải thích:", "").strip()
            
    return quiz

# Command handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler cho lệnh /start"""
    welcome_message = """
👋 **Xin chào! Tôi là Bot AI thông minh**

🤖 **Tính năng chính:**
• Chat AI thông minh với Claude 3 Haiku
• Thông tin thời tiết Việt Nam
• Nhiều trò chơi thú vị với bảng xếp hạng

📝 **Lệnh cơ bản:**
/help - Xem hướng dẫn chi tiết
/game - Menu trò chơi
/leaderboard - Bảng xếp hạng
/weather <city> - Thời tiết

💬 Hoặc chat trực tiếp với tôi!
"""
    await update.message.reply_text(welcome_message)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler cho lệnh /help"""
    help_text = """
📚 **HƯỚNG DẪN SỬ DỤNG**

**💬 Chat AI:**
• Nhắn tin trực tiếp để chat
• Hỏi bất cứ điều gì bạn muốn

**🌤️ Thời tiết:**
• /weather hanoi - Thời tiết Hà Nội
• Hoặc chat: "thời tiết hồ chí minh"

**🎮 Trò chơi:**
• /game - Xem menu trò chơi
• /guessnumber - Đoán số (1-100)
• /noitu - Nối từ tiếng Việt
• /quiz - Câu đố vui

**🏆 Bảng xếp hạng:**
• /leaderboard - Xem tất cả
• /leaderboard guess - BXH đoán số
• /leaderboard noitu - BXH nối từ

**🛠️ Lệnh khác:**
• /clear - Xóa lịch sử chat
• /hint - Gợi ý (trong game đoán số)
• /about - Thông tin bot
"""
    await update.message.reply_text(help_text)

async def about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler cho lệnh /about"""
    about_text = """
🤖 **VỀ BOT AI**

**Công nghệ:**
• AI: Claude 3 Haiku (Anthropic)
• Platform: Vercel AI Gateway
• Từ điển: 74K+ từ tiếng Việt
• Database: SQLite

**Tính năng nổi bật:**
• Chat AI thông minh
• Mini games có bảng xếp hạng
• Thông tin thời tiết real-time
• Hỗ trợ tiếng Việt hoàn hảo

**Phiên bản:** 3.0
**Cập nhật:** 2024

💡 Mẹo: Dùng /help để xem hướng dẫn chi tiết!
"""
    await update.message.reply_text(about_text)

async def clear_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xóa lịch sử chat"""
    chat_id = update.effective_chat.id
    if chat_id in chat_history:
        chat_history[chat_id] = []
    await update.message.reply_text("✅ Đã xóa lịch sử chat!")

async def weather_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler cho lệnh /weather"""
    if not context.args:
        await update.message.reply_text("❌ Vui lòng nhập tên thành phố!\n\nVí dụ: /weather hanoi")
        return
        
    city = " ".join(context.args)
    weather_info = await get_weather(city)
    await update.message.reply_text(weather_info)

async def leaderboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Hiển thị bảng xếp hạng"""
    game_type = context.args[0] if context.args else None
    
    if game_type == "guess":
        title = "🔢 Bảng Xếp Hạng Đoán Số"
        scores = get_leaderboard("guessnumber")
    elif game_type == "noitu":
        title = "🔤 Bảng Xếp Hạng Nối Từ"
        scores = get_leaderboard("noitu")
    else:
        # Hiển thị cả hai bảng
        guess_scores = get_leaderboard("guessnumber", 5)
        noitu_scores = get_leaderboard("noitu", 5)
        
        message = "🏆 **BẢNG XẾP HẠNG**\n\n"
        
        message += "**🔢 Đoán Số:**\n"
        if guess_scores:
            for i, (username, score) in enumerate(guess_scores, 1):
                medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
                message += f"{medal} {username}: {score} điểm\n"
        else:
            message += "Chưa có dữ liệu\n"
            
        message += "\n**🔤 Nối Từ:**\n"
        if noitu_scores:
            for i, (username, score) in enumerate(noitu_scores, 1):
                medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
                message += f"{medal} {username}: {score} điểm\n"
        else:
            message += "Chưa có dữ liệu\n"
            
        message += "\n💡 Dùng /leaderboard guess hoặc /leaderboard noitu để xem chi tiết"
        
        await update.message.reply_text(message)
        return
        
    # Hiển thị bảng xếp hạng cụ thể
    message = f"🏆 **{title}**\n\n"
    
    if scores:
        for i, (username, score) in enumerate(scores, 1):
            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
            message += f"{medal} {username}: {score} điểm\n"
    else:
        message += "Chưa có dữ liệu. Hãy chơi game để lên bảng xếp hạng!"
        
    await update.message.reply_text(message)

async def game_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Hiển thị menu trò chơi"""
    keyboard = [
        [InlineKeyboardButton("🔢 Đoán Số", callback_data="game_guessnumber")],
        [InlineKeyboardButton("🔤 Nối Từ", callback_data="game_noitu")],
        [InlineKeyboardButton("❓ Câu Đố", callback_data="game_quiz")],
        [InlineKeyboardButton("🏆 Bảng Xếp Hạng", callback_data="game_leaderboard")],
        [InlineKeyboardButton("❌ Đóng", callback_data="game_close")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message = """🎮 **MENU TRÒ CHƠI**

Chọn trò chơi bạn muốn chơi:

🔢 **Đoán Số** - Đoán số từ 1-100
🔤 **Nối Từ** - Nối từ tiếng Việt
❓ **Câu Đố** - Trả lời câu đố vui

Mỗi trò chơi đều có bảng xếp hạng!
"""
    
    await update.message.reply_text(message, reply_markup=reply_markup)

async def start_guess_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bắt đầu game đoán số"""
    chat_id = update.effective_chat.id
    
    # Kết thúc game cũ nếu có
    if chat_id in active_games:
        del active_games[chat_id]
        
    # Tạo game mới
    use_ai = random.choice([True, False])  # Ngẫu nhiên chọn AI hoặc script
    game = GuessNumberGame(chat_id, use_ai)
    active_games[chat_id] = {"type": "guessnumber", "game": game}
    
    message = f"""🎮 **ĐOÁN SỐ BÍ MẬT**

🎯 Tôi đang nghĩ một số từ 1 đến 100
📝 Bạn có 10 lần đoán
💡 Có 3 lần gợi ý (gõ /hint)

🔍 **Câu đố:** {game.riddle}

Hãy gửi số đoán của bạn!"""
    
    if hasattr(update, 'callback_query'):
        await update.callback_query.message.reply_text(message)
    else:
        await update.message.reply_text(message)

async def hint_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xem gợi ý trong game đoán số"""
    chat_id = update.effective_chat.id
    
    if chat_id not in active_games or active_games[chat_id]["type"] != "guessnumber":
        await update.message.reply_text("❌ Bạn không đang chơi đoán số!\n\nDùng /guessnumber để bắt đầu")
        return
        
    game = active_games[chat_id]["game"]
    hint = game.get_hint()
    await update.message.reply_text(hint)

async def start_noitu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bắt đầu game nối từ"""
    chat_id = update.effective_chat.id
    
    # Kết thúc game cũ nếu có
    if chat_id in active_games:
        del active_games[chat_id]
        
    # Tạo game mới
    game = NoiTuGame(chat_id)
    active_games[chat_id] = {"type": "noitu", "game": game}
    
    message = game.start()
    
    if hasattr(update, 'callback_query'):
        await update.callback_query.message.reply_text(message)
    else:
        await update.message.reply_text(message)

async def quiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tạo câu đố mới"""
    chat_id = update.effective_chat.id
    
    # Tạo câu đố
    quiz = await generate_quiz()
    
    if quiz["question"] and quiz["options"]:
        # Lưu quiz session
        quiz_sessions[chat_id] = quiz
        
        # Tạo keyboard cho câu trả lời
        keyboard = []
        for option in quiz["options"]:
            letter = option[0]
            keyboard.append([InlineKeyboardButton(option, callback_data=f"quiz_{letter}")])
        keyboard.append([InlineKeyboardButton("❌ Bỏ qua", callback_data="quiz_skip")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message = f"❓ **CÂU ĐỐ VUI**\n\n{quiz['question']}"
        
        if hasattr(update, 'callback_query'):
            await update.callback_query.message.reply_text(message, reply_markup=reply_markup)
        else:
            await update.message.reply_text(message, reply_markup=reply_markup)
    else:
        await update.message.reply_text("Xin lỗi, không thể tạo câu đố lúc này. Vui lòng thử lại!")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xử lý callback từ inline keyboard"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    chat_id = update.effective_chat.id
    
    if data.startswith("game_"):
        if data == "game_guessnumber":
            await start_guess_number(update, context)
        elif data == "game_noitu":
            await start_noitu(update, context)
        elif data == "game_quiz":
            await quiz_command(update, context)
        elif data == "game_leaderboard":
            # Hiển thị menu bảng xếp hạng
            keyboard = [
                [InlineKeyboardButton("🔢 BXH Đoán Số", callback_data="lb_guess")],
                [InlineKeyboardButton("🔤 BXH Nối Từ", callback_data="lb_noitu")],
                [InlineKeyboardButton("🔙 Quay lại", callback_data="game_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.edit_text("🏆 **Chọn bảng xếp hạng:**", reply_markup=reply_markup)
        elif data == "game_close":
            await query.message.delete()
            
    elif data.startswith("lb_"):
        game_type = "guessnumber" if data == "lb_guess" else "noitu"
        title = "🔢 Đoán Số" if data == "lb_guess" else "🔤 Nối Từ"
        scores = get_leaderboard(game_type)
        
        message = f"🏆 **Bảng Xếp Hạng {title}**\n\n"
        
        if scores:
            for i, (username, score) in enumerate(scores, 1):
                medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
                message += f"{medal} {username}: {score} điểm\n"
        else:
            message += "Chưa có dữ liệu!"
            
        keyboard = [[InlineKeyboardButton("🔙 Quay lại", callback_data="game_leaderboard")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(message, reply_markup=reply_markup)
        
    elif data == "game_menu":
        # Quay lại menu game
        keyboard = [
            [InlineKeyboardButton("🔢 Đoán Số", callback_data="game_guessnumber")],
            [InlineKeyboardButton("🔤 Nối Từ", callback_data="game_noitu")],
            [InlineKeyboardButton("❓ Câu Đố", callback_data="game_quiz")],
            [InlineKeyboardButton("🏆 Bảng Xếp Hạng", callback_data="game_leaderboard")],
            [InlineKeyboardButton("❌ Đóng", callback_data="game_close")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text("🎮 **MENU TRÒ CHƠI**", reply_markup=reply_markup)
            
    elif data.startswith("quiz_"):
        if chat_id not in quiz_sessions:
            await query.message.edit_text("❌ Câu đố đã hết hạn!")
            return
            
        quiz = quiz_sessions[chat_id]
        
        if data == "quiz_skip":
            await query.message.edit_text(f"Đáp án đúng là: **{quiz['correct']}**\n\n{quiz['explanation']}")
            del quiz_sessions[chat_id]
        else:
            answer = data.split("_")[1]
            if answer == quiz["correct"]:
                await query.message.edit_text(f"✅ Chính xác!\n\n{quiz['explanation']}")
            else:
                await query.message.edit_text(f"❌ Sai rồi! Đáp án đúng là: **{quiz['correct']}**\n\n{quiz['explanation']}")
            del quiz_sessions[chat_id]

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xử lý tin nhắn từ người dùng"""
    message = update.message.text
    chat_id = update.effective_chat.id
    user = update.effective_user
    user_name = user.first_name
    username = user.username or user_name
    
    # Kiểm tra game đang chơi
    if chat_id in active_games:
        game_info = active_games[chat_id]
        
        if game_info["type"] == "guessnumber":
            try:
                guess = int(message)
                if 1 <= guess <= 100:
                    is_finished, response = game_info["game"].make_guess(guess)
                    await update.message.reply_text(response)
                    
                    if is_finished and "Chúc mừng" in response:
                        # Lưu điểm
                        final_score = game_info["game"].score
                        if final_score < 0:
                            final_score = 100
                        save_score(user.id, username, "guessnumber", final_score)
                        
                    if is_finished:
                        del active_games[chat_id]
                else:
                    await update.message.reply_text("❌ Vui lòng nhập số từ 1 đến 100!")
            except ValueError:
                await update.message.reply_text("❌ Vui lòng nhập một số!\n\n💡 Gõ /hint để xem gợi ý")
                
        elif game_info["type"] == "noitu":
            is_finished, response = game_info["game"].play_word(message)
            await update.message.reply_text(response)
            
            if is_finished:
                # Lưu điểm
                save_score(user.id, username, "noitu", game_info["game"].score)
                del active_games[chat_id]
                
        return
    
    # Kiểm tra yêu cầu thời tiết
    if "thời tiết" in message.lower():
        # Tìm tên thành phố
        words = message.lower().split()
        if "thời tiết" in words:
            idx = words.index("thời tiết")
            if idx + 1 < len(words):
                city = " ".join(words[idx + 1:])
                weather_info = await get_weather(city)
                await update.message.reply_text(weather_info)
                return
    
    # Chat AI thông thường
    # Quản lý lịch sử chat
    if chat_id not in chat_history:
        chat_history[chat_id] = []
        
    # Thêm tin nhắn mới
    chat_history[chat_id].append({"role": "user", "content": message})
    
    # Giới hạn lịch sử
    if len(chat_history[chat_id]) > CTX_TURNS * 2:
        chat_history[chat_id] = chat_history[chat_id][-(CTX_TURNS * 2):]
    
    # Tạo messages cho API
    messages = [
        {"role": "system", "content": f"Bạn là trợ lý AI thân thiện, hữu ích. Bạn đang chat với {user_name}. Hãy trả lời bằng tiếng Việt một cách tự nhiên, thân thiện. Khi được hỏi về bot hoặc các tính năng, hãy giới thiệu về các lệnh và trò chơi có sẵn."}
    ]
    messages.extend(chat_history[chat_id])
    
    # Gọi API
    response = await call_vercel_api(messages, MAX_TOKENS)
    
    # Lưu response
    chat_history[chat_id].append({"role": "assistant", "content": response})
    
    # Gửi response
    await update.message.reply_text(response)

def main():
    """Khởi động bot"""
    # Tạo application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("about", about))
    application.add_handler(CommandHandler("clear", clear_history))
    application.add_handler(CommandHandler("weather", weather_command))
    application.add_handler(CommandHandler("leaderboard", leaderboard_command))
    
    # Game handlers
    application.add_handler(CommandHandler("game", game_menu))
    application.add_handler(CommandHandler("guessnumber", start_guess_number))
    application.add_handler(CommandHandler("noitu", start_noitu))
    application.add_handler(CommandHandler("quiz", quiz_command))
    application.add_handler(CommandHandler("hint", hint_command))
    
    # Callback query handler
    application.add_handler(CallbackQueryHandler(button_callback))
    
    # Message handler
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Run bot
    logger.info("Bot started!")
    application.run_polling()

if __name__ == "__main__":
    main()
