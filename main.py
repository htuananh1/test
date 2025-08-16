import os
import random
import asyncio
import logging
import requests
import json
import sqlite3
import gc
from datetime import datetime, timedelta, time
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

BOT_TOKEN = os.environ["BOT_TOKEN"]
VERCEL_API_KEY = os.environ.get("VERCEL_API_KEY", "")
BASE_URL = os.getenv("BASE_URL", "https://ai-gateway.vercel.sh/v1")
CHAT_MODEL = os.getenv("CHAT_MODEL", "openai/gpt-oss-120b")
CLAUDE_MODEL = "anthropic/claude-3.5-sonnet"
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "400"))
CTX_TURNS = int(os.getenv("CTX_TURNS", "3"))

# Cấu hình Tài Xỉu
ROUND_DURATION_S = 45
START_BALANCE = 1000
MIN_BET = 10
MAX_BET = 100000
ALLOW_REBET = True

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ====== Tài Xỉu Classes ======
@dataclass
class RoundState:
    is_open: bool = False
    bets: Dict[int, Tuple[str, int]] = field(default_factory=dict)
    starter_id: int = 0
    end_ts: float = 0.0
    task: Optional[asyncio.Task] = None

@dataclass
class ChatState:
    balances: Dict[int, int] = field(default_factory=dict)
    round: Optional[RoundState] = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

CHAT_STATES: Dict[int, ChatState] = {}

def init_db():
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
    c.execute('''
        CREATE TABLE IF NOT EXISTS chats (
            chat_id INTEGER PRIMARY KEY,
            chat_type TEXT,
            title TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

active_games: Dict[int, dict] = {}
chat_history: Dict[int, List[dict]] = {}
quiz_sessions: Dict[int, dict] = {}
quiz_mode: Dict[int, bool] = {}
quiz_count: Dict[int, int] = {}
quiz_history: Dict[int, List[str]] = {}
word_game_sessions: Dict[int, dict] = {}
word_history: Dict[int, List[str]] = {}
goodnight_task = None

# ====== Tài Xỉu Helpers ======
def _fmt_money(x: int) -> str:
    return f"{x:,}".replace(",", ".")

def _get_cs(chat_id: int) -> ChatState:
    cs = CHAT_STATES.get(chat_id)
    if not cs:
        cs = ChatState()
        CHAT_STATES[chat_id] = cs
    return cs

def _ensure_balance(cs: ChatState, user_id: int):
    if user_id not in cs.balances:
        cs.balances[user_id] = START_BALANCE

def _norm_side(s: str) -> Optional[str]:
    s = s.strip().lower()
    if s in ("tai", "tài", "t", "over", "o"):
        return "tai"
    if s in ("xiu", "xỉu", "x", "under", "u"):
        return "xiu"
    return None

def _result_from_dice(a: int, b: int, c: int) -> Tuple[str, bool]:
    is_triple = (a == b == c)
    total = a + b + c
    if is_triple:
        return ("house", True)
    if 4 <= total <= 10:
        return ("xiu", False)
    if 11 <= total <= 17:
        return ("tai", False)
    return ("house", is_triple)

def _round_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Đặt TÀI (+100)", callback_data="tx:q:tai:100"),
            InlineKeyboardButton("Đặt XỈU (+100)", callback_data="tx:q:xiu:100"),
        ],
        [
            InlineKeyboardButton("Đặt +500", callback_data="tx:q:keep:500"),
            InlineKeyboardButton("Đặt +1000", callback_data="tx:q:keep:1000"),
        ],
        [
            InlineKeyboardButton("Hủy cược", callback_data="tx:cancel"),
            InlineKeyboardButton("Số dư", callback_data="tx:bal"),
        ]
    ])

def save_chat_info(chat_id: int, chat_type: str, title: str = None):
    conn = sqlite3.connect('bot_scores.db')
    c = conn.cursor()
    c.execute('INSERT OR REPLACE INTO chats (chat_id, chat_type, title) VALUES (?, ?, ?)',
              (chat_id, chat_type, title))
    conn.commit()
    conn.close()

def get_all_chats():
    conn = sqlite3.connect('bot_scores.db')
    c = conn.cursor()
    c.execute('SELECT chat_id, chat_type FROM chats')
    results = c.fetchall()
    conn.close()
    return results

def cleanup_memory():
    global chat_history, quiz_history, word_history
    for chat_id in list(chat_history.keys()):
        if len(chat_history[chat_id]) > 4:
            chat_history[chat_id] = chat_history[chat_id][-4:]
    
    for chat_id in list(quiz_history.keys()):
        if len(quiz_history[chat_id]) > 20:
            quiz_history[chat_id] = quiz_history[chat_id][-20:]
    
    for chat_id in list(word_history.keys()):
        if len(word_history[chat_id]) > 30:
            word_history[chat_id] = word_history[chat_id][-30:]
    
    gc.collect()

def save_score(user_id: int, username: str, game_type: str, score: int):
    try:
        conn = sqlite3.connect('bot_scores.db')
        c = conn.cursor()
        c.execute('INSERT INTO scores (user_id, username, game_type, score) VALUES (?, ?, ?, ?)',
                  (user_id, username, game_type, score))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Save score error: {e}")

def get_leaderboard_24h(limit: int = 10) -> List[tuple]:
    try:
        conn = sqlite3.connect('bot_scores.db')
        c = conn.cursor()
        yesterday = datetime.now() - timedelta(days=1)
        c.execute('''
            SELECT username, SUM(score) as total_score, COUNT(DISTINCT game_type) as games_played
            FROM scores
            WHERE timestamp >= ?
            GROUP BY user_id
            ORDER BY total_score DESC
            LIMIT ?
        ''', (yesterday, limit))
        results = c.fetchall()
        conn.close()
        return results
    except Exception as e:
        logger.error(f"Get leaderboard error: {e}")
        return []

def get_user_stats_24h(user_id: int) -> dict:
    try:
        conn = sqlite3.connect('bot_scores.db')
        c = conn.cursor()
        yesterday = datetime.now() - timedelta(days=1)
        
        c.execute('''
            SELECT game_type, COUNT(*) as games_played, SUM(score) as total_score, MAX(score) as best_score
            FROM scores
            WHERE user_id = ? AND timestamp >= ?
            GROUP BY game_type
        ''', (user_id, yesterday))
        results = c.fetchall()
        
        stats = {'total': 0, 'games': {}}
        
        for game_type, games_played, total_score, best_score in results:
            stats['games'][game_type] = {
                'played': games_played,
                'total': total_score,
                'best': best_score
            }
            stats['total'] += total_score
            
        conn.close()
        return stats
    except Exception as e:
        logger.error(f"Get stats error: {e}")
        return {'total': 0, 'games': {}}

# ====== Tài Xỉu Functions ======
async def _announce_round(update: Update, context: ContextTypes.DEFAULT_TYPE, duration: int):
    chat = update.effective_chat
    await context.bot.send_message(
        chat_id=chat.id,
        text=(
            f"🎲 **TÀI XỈU** đã mở! Thời gian còn: {duration}s\n"
            f"• Cược tối thiểu: {_fmt_money(MIN_BET)} | tối đa: {_fmt_money(MAX_BET)}\n"
            f"• Gõ: `/bet tai <tiền>` hoặc `/bet xiu <tiền>`\n"
            f"• Tam hoa (3 số giống nhau) ➜ **Nhà cái thắng**\n"
            f"• /bal xem số dư\n"
            f"• /stoptaixiu để đóng sớm (người mở ván hoặc admin)\n"
        ),
        reply_markup=_round_keyboard(),
        parse_mode="Markdown"
    )

async def _auto_close_round(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    cs = _get_cs(chat_id)
    await asyncio.sleep(max(0, int(cs.round.end_ts - asyncio.get_event_loop().time())))
    async with cs.lock:
        if cs.round and cs.round.is_open:
            await _resolve_and_report(chat_id, context)

async def _resolve_and_report(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    cs = _get_cs(chat_id)
    if not cs.round:
        return
    rd = cs.round
    rd.is_open = False

    a, b, c = random.randint(1, 6), random.randint(1, 6), random.randint(1, 6)
    res_side, is_triple = _result_from_dice(a, b, c)
    total = a + b + c

    winners = []
    losers = []
    
    for uid, (side, amount) in rd.bets.items():
        # Lấy username từ chat member
        try:
            member = await context.bot.get_chat_member(chat_id, uid)
            username = member.user.username or member.user.first_name
        except:
            username = f"User{uid}"
            
        if res_side == "house":
            losers.append((uid, username, side, amount))
        elif side == res_side:
            cs.balances[uid] = cs.balances.get(uid, START_BALANCE) + amount * 2
            winners.append((uid, username, side, amount))
            save_score(uid, username, "taixiu", amount)
        else:
            losers.append((uid, username, side, amount))

    lines = [
        f"🎲 **KẾT QUẢ**: 🎲 {a} + {b} + {c} = **{total}**",
        f"➡️ Kết cục: {'TAM HOA – NHÀ CÁI THẮNG' if is_triple else ('TÀI' if res_side=='tai' else 'XỈU')}",
        "",
        f"👥 Tổng người cược: {len(rd.bets)}",
    ]
    
    if winners:
        wtxt = "\n".join([f"✅ {name} {side.upper()} +{_fmt_money(amount)}" for uid, name, side, amount in winners])
        lines += ["**Thắng:**", wtxt]
    if losers:
        ltxt = "\n".join([f"❌ {name} {side.upper()} -{_fmt_money(amount)}" for uid, name, side, amount in losers])
        lines += ["", "**Thua:**", ltxt]
    if not winners and not losers:
        lines += ["(Không có ai đặt cược)"]

    if rd.task and not rd.task.cancelled():
        rd.task.cancel()
    cs.round = None

    await context.bot.send_message(
        chat_id=chat_id,
        text="\n".join(lines),
        parse_mode="Markdown"
    )

# ====== Game Classes ======
class GuessNumberGame:
    def __init__(self, chat_id: int):
        self.chat_id = chat_id
        self.attempts = 0
        self.max_attempts = 10
        self.hints_used = 0
        self.max_hints = 3
        self.start_time = datetime.now()
        self.score = 1000
        self.secret_number = random.randint(1, 100)
        self.riddle = self.generate_riddle()
            
    def generate_riddle(self) -> str:
        riddles = []
        if self.secret_number % 2 == 0:
            riddles.append("số chẵn")
        else:
            riddles.append("số lẻ")
        if self.secret_number < 50:
            riddles.append("nhỏ hơn 50")
        else:
            riddles.append("lớn hơn hoặc bằng 50")
        return f"Số bí mật là {' và '.join(riddles)}"
        
    def get_hint(self) -> str:
        if self.hints_used >= self.max_hints:
            return "❌ Hết gợi ý rồi!"
            
        self.hints_used += 1
        self.score -= 100
        
        if self.hints_used == 1:
            tens = self.secret_number // 10
            hint = f"💡 Gợi ý 1: {'Số có 1 chữ số' if tens == 0 else f'Chữ số hàng chục là {tens}'}"
        elif self.hints_used == 2:
            digit_sum = sum(int(d) for d in str(self.secret_number))
            hint = f"💡 Gợi ý 2: Tổng các chữ số là {digit_sum}"
        else:
            lower = (self.secret_number // 10) * 10
            upper = lower + 9 if lower > 0 else 9
            hint = f"💡 Gợi ý 3: Số từ {max(1, lower)} đến {upper}"
        return f"{hint}\n🎯 Còn {self.max_hints - self.hints_used} gợi ý"
        
    def make_guess(self, guess: int) -> Tuple[bool, str]:
        self.attempts += 1
        self.score -= 50
        
        if guess == self.secret_number:
            time_taken = (datetime.now() - self.start_time).seconds
            final_score = max(self.score, 100)
            return True, f"🎉 Đúng rồi! Số {self.secret_number}!\n⏱️ {time_taken}s | 🏆 {final_score} điểm"
            
        if self.attempts >= self.max_attempts:
            return True, f"😤 Hết lượt! Số là {self.secret_number}\n💡 {self.riddle}"
            
        hint = "📈 cao hơn" if guess < self.secret_number else "📉 thấp hơn"
        remaining = self.max_attempts - self.attempts
        return False, f"{guess} {hint}! Còn {remaining} lượt | 💰 {self.score}đ | /hint"

class VuaTiengVietGame:
    def __init__(self, chat_id: int):
        self.chat_id = chat_id
        self.current_word = ""
        self.scrambled = ""
        self.attempts = 0
        self.max_attempts = 3
        self.score = 0
        self.start_time = datetime.now()
        self.round_count = 0
        
    async def start_new_round(self) -> str:
        self.round_count += 1
        self.attempts = 0
        
        await asyncio.sleep(5)
        
        self.current_word, self.scrambled = await self.generate_word_puzzle()
        
        return f"""🎮 **VUA TIẾNG VIỆT - CÂU {self.round_count}**

Sắp xếp các ký tự sau thành từ/cụm từ có nghĩa:

🔤 **{self.scrambled}**

💡 Gợi ý: {len(self.current_word.replace(' ', ''))} chữ cái
📝 Bạn có {self.max_attempts} lần thử

Gõ đáp án của bạn!"""

    async def generate_word_puzzle(self) -> Tuple[str, str]:
        global word_history
        
        if self.chat_id not in word_history:
            word_history[self.chat_id] = []
        
        word_pool = [
            "học sinh", "giáo viên", "bạn bè", "gia đình", "mùa xuân",
            "mùa hạ", "mùa thu", "mùa đông", "trái tim", "nụ cười",
            "ánh sáng", "bóng tối", "sức khỏe", "hạnh phúc", "tình yêu",
            "thành công", "cố gắng", "kiên trì", "phấn đấu", "ước mơ",
            "hoài bão", "tri thức", "văn hóa", "lịch sử", "truyền thống",
            "phát triển", "công nghệ", "khoa học", "nghệ thuật", "sáng tạo",
            "thời gian", "không gian", "vũ trụ", "thiên nhiên", "môi trường",
            "biển cả", "núi non", "sông ngòi", "đồng bằng", "cao nguyên",
            "thành phố", "nông thôn", "làng quê", "đô thị", "giao thông",
            "âm nhạc", "hội họa", "điện ảnh", "văn học", "thơ ca",
            "bánh mì", "phở bò", "bún chả", "cơm tấm", "chả giò",
            "cà phê", "trà sữa", "nước mía", "sinh tố", "bia hơi"
        ]
        
        available_words = [w for w in word_pool if w not in word_history[self.chat_id][-15:]]
        
        if not available_words:
            word_history[self.chat_id] = []
            available_words = word_pool
        
        word = random.choice(available_words)
        word_history[self.chat_id].append(word)
        
        def smart_scramble(text):
            clusters = ['th', 'tr', 'ch', 'ph', 'nh', 'ng', 'gh', 'kh', 'gi', 'qu']
            result = []
            i = 0
            text_no_space = text.replace(' ', '')
            
            while i < len(text_no_space):
                found_cluster = False
                for cluster in clusters:
                    if text_no_space[i:i+len(cluster)].lower() == cluster:
                        result.append(text_no_space[i:i+len(cluster)])
                        i += len(cluster)
                        found_cluster = True
                        break
                
                if not found_cluster:
                    result.append(text_no_space[i])
                    i += 1
            
            random.shuffle(result)
            return ' / '.join(result)
        
        scrambled = smart_scramble(word)
        return word, scrambled
        
    def check_answer(self, answer: str) -> Tuple[bool, str]:
        answer = answer.lower().strip()
        self.attempts += 1
        
        answer_normalized = ''.join(answer.split())
        original_normalized = ''.join(self.current_word.lower().split())
        
        if answer_normalized == original_normalized:
            points = (self.max_attempts - self.attempts + 1) * 100
            self.score += points
            time_taken = (datetime.now() - self.start_time).seconds
            
            return True, f"""✅ **CHÍNH XÁC!**

Đáp án: **{self.current_word}**
Điểm: +{points} (Tổng: {self.score})
Thời gian: {time_taken}s

Gõ 'tiếp' để chơi tiếp hoặc 'dừng' để kết thúc"""
            
        if self.attempts >= self.max_attempts:
            return False, f"""❌ Hết lượt!

Đáp án là: **{self.current_word}**

Gõ 'tiếp' để chơi câu mới hoặc 'dừng' để kết thúc"""
            
        remaining = self.max_attempts - self.attempts
        return False, f"❌ Sai rồi! Còn {remaining} lần thử\n\n🔤 {self.scrambled}"

# ====== API Functions ======
async def call_api(messages: List[dict], model: str = None, max_tokens: int = 400, temperature: float = None) -> str:
    try:
        headers = {
            "Authorization": f"Bearer {VERCEL_API_KEY}",
            "Content-Type": "application/json"
        }
        
        if temperature is None:
            temperature = 0.3 if model == CLAUDE_MODEL else 0.7
        
        data = {
            "model": model or CHAT_MODEL,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": 0.9
        }
        
        response = requests.post(
            f"{BASE_URL}/chat/completions",
            headers=headers,
            json=data,
            timeout=25
        )
        
        if response.status_code == 200:
            result = response.json()
            return result['choices'][0]['message']['content']
        else:
            logger.error(f"API error: {response.status_code}")
            return None
            
    except Exception as e:
        logger.error(f"API error: {e}")
        return None

async def generate_quiz(chat_id: int) -> dict:
    global quiz_history
    
    if chat_id not in quiz_history:
        quiz_history[chat_id] = []
    
    recent_questions = quiz_history[chat_id][-10:] if len(quiz_history[chat_id]) > 0 else []
    history_text = "\n".join(recent_questions) if recent_questions else "None"
    
    topics = ["Lịch sử Việt Nam", "Địa lý Việt Nam", "Văn hóa Việt Nam", "Ẩm thực Việt Nam", "Khoa học Việt Nam", "Thể thao Việt Nam"]
    topic = random.choice(topics)
    
    prompt = f"""Create a quiz question about {topic} with MAXIMUM ACCURACY.

CRITICAL REQUIREMENTS:
1. MUST be 100% factually accurate and verifiable
2. Different from previously asked questions
3. 4 options with ONLY 1 correct answer

Previously asked: {history_text}

Return ONLY valid JSON in Vietnamese:
{{
  "topic": "{topic}",
  "question": "question in Vietnamese",
  "options": ["A. option", "B. option", "C. option", "D. option"],
  "answer": "A or B or C or D",
  "explain": "explanation in Vietnamese"
}}"""

    messages = [
        {"role": "system", "content": "You are a Vietnamese education expert. Create only 100% accurate quiz questions."},
        {"role": "user", "content": prompt}
    ]
    
    try:
        response = await call_api(messages, model=CLAUDE_MODEL, max_tokens=500, temperature=0.2)
        
        if not response:
            return None
        
        json_start = response.find('{')
        json_end = response.rfind('}') + 1
        
        if json_start == -1 or json_end <= json_start:
            return None
            
        json_str = response[json_start:json_end]
        data = json.loads(json_str)
        
        quiz = {
            "topic": data.get("topic", topic),
            "question": data.get("question", ""),
            "options": data.get("options", []),
            "correct": data.get("answer", "")[0].upper() if data.get("answer") else "",
            "explanation": data.get("explain", "")
        }
        
        if quiz["question"] and len(quiz["options"]) == 4 and quiz["correct"] in ["A", "B", "C", "D"]:
            quiz_history[chat_id].append(quiz["question"][:100])
            return quiz
            
    except Exception as e:
        logger.error(f"Generate quiz error: {e}")
    
    return None

# ====== Scheduler Functions ======
async def goodnight_scheduler(app):
    while True:
        now = datetime.now()
        target_time = now.replace(hour=23, minute=0, second=0, microsecond=0)
        
        if now >= target_time:
            target_time += timedelta(days=1)
        
        wait_seconds = (target_time - now).total_seconds()
        logger.info(f"Waiting {wait_seconds} seconds until 23:00")
        
        await asyncio.sleep(wait_seconds)
        
        await send_goodnight_message(app)
        
        await asyncio.sleep(60)

async def send_goodnight_message(app):
    chats = get_all_chats()
    
    messages = [
        "Linh chúc các tình yêu ngủ ngon ❤️❤️",
        "23h rồi! Ngủ ngon nhé mọi người 😴💕",
        "Chúc cả nhà có giấc ngủ thật ngon 🌙✨",
        "Good night! Ngủ ngon và mơ đẹp nhé 💫❤️",
        "Linh chúc mọi người ngủ ngon! Mai gặp lại nha 😘"
    ]
    
    message = random.choice(messages)
    
    for chat_id, chat_type in chats:
        try:
            await app.bot.send_message(chat_id=chat_id, text=message)
            logger.info(f"Sent goodnight to {chat_id}")
        except Exception as e:
            logger.error(f"Failed to send to {chat_id}: {e}")

# ====== Command Handlers ======
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    save_chat_info(chat.id, chat.type, chat.title)
    user = update.effective_user
    cs = _get_cs(chat.id)
    _ensure_balance(cs, user.id)
    balance = cs.balances[user.id]
    
    await update.message.reply_text(f"""
👋 **Xin chào! Mình là Linh!**

💰 Số dư của bạn: **{_fmt_money(balance)}**

🎮 **Game:**
/guessnumber - Đoán số
/vuatiengviet - Sắp xếp chữ cái
/quiz - Câu đố về Việt Nam (Claude AI)
/stopquiz - Dừng câu đố

🎲 **Tài Xỉu:**
/taixiu - Mở ván tài xỉu (45s)
/bet tai/xiu <số tiền> - Đặt cược
/bal - Xem số dư
/stoptaixiu - Đóng ván sớm

🏆 /leaderboard - BXH Tài xỉu
📊 /stats - Thống kê 24h

💬 Chat với Linh (GPT)
💕 Mỗi 23h Linh sẽ chúc ngủ ngon!
""")

async def taixiu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    cs = _get_cs(chat.id)

    try:
        duration = int(context.args[0]) if context.args else ROUND_DURATION_S
        duration = max(10, min(300, duration))
    except:
        duration = ROUND_DURATION_S

    async with cs.lock:
        if cs.round and cs.round.is_open:
            await update.message.reply_text("⚠️ Đang có ván mở. Hãy cược bằng /bet hoặc chờ ván kết thúc.")
            return

        rd = RoundState(is_open=True, bets={}, starter_id=user.id, end_ts=asyncio.get_event_loop().time() + duration)
        cs.round = rd
        rd.task = asyncio.create_task(_auto_close_round(chat.id, context))

        await _announce_round(update, context, duration)

async def bet_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    cs = _get_cs(chat.id)
    
    async with cs.lock:
        if not cs.round or not cs.round.is_open:
            await update.message.reply_text("⛔ Chưa có ván nào đang mở. Dùng /taixiu để mở ván mới.")
            return

        if len(context.args) < 2:
            await update.message.reply_text("Cách dùng: /bet tai|xiu <số tiền>\nVí dụ: /bet tai 1000")
            return

        side = _norm_side(context.args[0])
        if side is None:
            await update.message.reply_text("❓ Vui lòng chọn 'tai' hoặc 'xiu'.")
            return

        try:
            amount = int(context.args[1])
        except:
            await update.message.reply_text("❓ Số tiền không hợp lệ.")
            return

        if amount < MIN_BET or amount > MAX_BET:
            await update.message.reply_text(f"⚠️ Cược tối thiểu {_fmt_money(MIN_BET)} và tối đa {_fmt_money(MAX_BET)}.")
            return

        _ensure_balance(cs, user.id)
        bal = cs.balances[user.id]
        
        if user.id in cs.round.bets and ALLOW_REBET:
            old_side, old_amt = cs.round.bets[user.id]
            bal += old_amt

        if amount > bal:
            await update.message.reply_text(f"💸 Số dư không đủ. Số dư hiện tại: {_fmt_money(bal)}")
            return

        bal -= amount
        cs.balances[user.id] = bal
        cs.round.bets[user.id] = (side, amount)

        await update.message.reply_text(f"✅ Đặt {side.upper()} {_fmt_money(amount)} thành công! Số dư còn: {_fmt_money(bal)}")

async def stop_taixiu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    cs = _get_cs(chat.id)
    
    async with cs.lock:
        if not cs.round or not cs.round.is_open:
            await update.message.reply_text("ℹ️ Không có ván đang mở.")
            return

        can_stop = (user.id == cs.round.starter_id)
        if not can_stop:
            try:
                member = await chat.get_member(user.id)
                can_stop = member.status in ("administrator", "creator")
            except:
                can_stop = False

        if not can_stop:
            await update.message.reply_text("⛔ Chỉ người mở ván hoặc admin mới được đóng sớm.")
            return

        await _resolve_and_report(chat.id, context)

async def bal_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    cs = _get_cs(chat.id)
    _ensure_balance(cs, user.id)
    await update.message.reply_text(f"👛 Số dư của bạn: {_fmt_money(cs.balances[user.id])}")

async def leaderboard_taixiu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    cs = _get_cs(chat.id)
    
    if not cs.balances:
        await update.message.reply_text("Chưa có ai chơi.")
        return
        
    top = sorted(cs.balances.items(), key=lambda x: x[1], reverse=True)[:10]
    lines = ["🏆 **BẢNG XẾP HẠNG TÀI XỈU**"]
    
    for i, (uid, bal) in enumerate(top, 1):
        try:
            member = await chat.get_member(uid)
            name = member.user.username or member.user.first_name
        except:
            name = f"User{uid}"
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        lines.append(f"{medal} {name} — {_fmt_money(bal)}")
        
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def start_guess_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    if chat_id in active_games:
        del active_games[chat_id]
        
    game = GuessNumberGame(chat_id)
    active_games[chat_id] = {"type": "guessnumber", "game": game}
    
    await update.message.reply_text(f"""🎮 **ĐOÁN SỐ 1-100**

💡 {game.riddle}
📝 10 lần | 💰 1000đ
/hint - Gợi ý (-100đ)

Đoán đi!""")

async def hint_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    if chat_id not in active_games or active_games[chat_id]["type"] != "guessnumber":
        await update.message.reply_text("❌ Không trong game đoán số!")
        return
        
    game = active_games[chat_id]["game"]
    await update.message.reply_text(game.get_hint())

async def start_vua_tieng_viet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    if chat_id in active_games:
        del active_games[chat_id]
    
    game = VuaTiengVietGame(chat_id)
    active_games[chat_id] = {"type": "vuatiengviet", "game": game}
    
    loading_msg = await update.message.reply_text("⏳ Đang tạo câu đố...")
    
    message = await game.start_new_round()
    await loading_msg.edit_text(message)

async def quiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    quiz_mode[chat_id] = True
    quiz_count[chat_id] = 1
    
    loading_msg = await update.message.reply_text("⏳ Claude AI đang tạo câu hỏi...")
    
    quiz = await generate_quiz(chat_id)
    
    if not quiz:
        await loading_msg.edit_text("❌ Lỗi tạo câu hỏi! Thử lại /quiz")
        if chat_id in quiz_mode:
            del quiz_mode[chat_id]
        return
    
    quiz_sessions[chat_id] = quiz
    
    keyboard = []
    for option in quiz["options"]:
        keyboard.append([InlineKeyboardButton(option, callback_data=f"quiz_{option[0]}")])
    keyboard.append([InlineKeyboardButton("❌ Dừng", callback_data="quiz_stop")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    topic_emojis = {
        "Lịch sử Việt Nam": "📜",
        "Địa lý Việt Nam": "🗺️",
        "Ẩm thực Việt Nam": "🍜",
        "Văn hóa Việt Nam": "🎭",
        "Khoa học Việt Nam": "🔬",
        "Thể thao Việt Nam": "⚽"
    }
    
    emoji = topic_emojis.get(quiz.get("topic", ""), "❓")
    message = f"{emoji} **CÂU {quiz_count[chat_id]} - {quiz.get('topic', '').upper()}**\n\n{quiz['question']}"
    
    await loading_msg.edit_text(message, reply_markup=reply_markup)

async def stop_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    total_questions = quiz_count.get(chat_id, 0) - 1
    
    if chat_id in quiz_mode:
        del quiz_mode[chat_id]
    if chat_id in quiz_sessions:
        del quiz_sessions[chat_id]
    if chat_id in quiz_count:
        del quiz_count[chat_id]
    if chat_id in quiz_history:
        quiz_history[chat_id] = []
        
    await update.message.reply_text(f"✅ Đã dừng câu đố!\n📊 Bạn đã trả lời {total_questions} câu")

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    stats = get_user_stats_24h(user.id)
    
    message = f"📊 **{user.first_name} (24H)**\n\n"
    message += f"📈 Tổng điểm kiếm được: {stats['total']:,}đ\n"
    
    if stats['games']:
        message += "\n**Chi tiết:**\n"
        for game_type, data in stats['games'].items():
            game_name = {
                "guessnumber": "Đoán số",
                "vuatiengviet": "Vua Tiếng Việt",
                "quiz": "Câu đố",
                "taixiu": "Tài xỉu"
            }.get(game_type, game_type)
            message += f"• {game_name}: {data['total']:,}đ ({data['played']} lần)\n"
            
    await update.message.reply_text(message)

# ====== Callback Handler ======
async def tx_cb_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    chat = update.effective_chat
    user = update.effective_user
    cs = _get_cs(chat.id)
    
    async with cs.lock:
        if not cs.round or not cs.round.is_open:
            await q.answer("⛔ Ván đã đóng hoặc chưa mở.", show_alert=True)
            return

        data = q.data
        if data == "tx:cancel":
            if user.id in cs.round.bets:
                side, amt = cs.round.bets.pop(user.id)
                cs.balances[user.id] = cs.balances.get(user.id, START_BALANCE) + amt
                await q.answer(f"🗑️ Đã hủy cược {side.upper()} {_fmt_money(amt)}", show_alert=True)
            else:
                await q.answer("Bạn chưa có cược để hủy.", show_alert=True)
            return

        if data == "tx:bal":
            _ensure_balance(cs, user.id)
            await q.answer(f"👛 Số dư: {_fmt_money(cs.balances[user.id])}", show_alert=True)
            return

        try:
            _, action, side_raw, amt_raw = data.split(":")
            if action != "q":
                raise ValueError
            if side_raw == "keep":
                if user.id not in cs.round.bets:
                    await q.answer("Bạn chưa chọn TÀI/XỈU.", show_alert=True)
                    return
                side = cs.round.bets[user.id][0]
            else:
                side = _norm_side(side_raw)
            amount = int(amt_raw)
        except:
            await q.answer("Dữ liệu không hợp lệ.", show_alert=True)
            return

        if side is None:
            await q.answer("❓ Vui lòng chọn 'tai' hoặc 'xiu'.", show_alert=True)
            return
        if amount < MIN_BET or amount > MAX_BET:
            await q.answer(f"⚠️ Cược tối thiểu {_fmt_money(MIN_BET)} và tối đa {_fmt_money(MAX_BET)}.", show_alert=True)
            return

        _ensure_balance(cs, user.id)
        bal = cs.balances[user.id]
        if user.id in cs.round.bets and ALLOW_REBET:
            old_side, old_amt = cs.round.bets[user.id]
            bal += old_amt

        if amount > bal:
            await q.answer(f"💸 Không đủ số dư. Hiện có: {_fmt_money(bal)}", show_alert=True)
            return

        bal -= amount
        cs.balances[user.id] = bal
        cs.round.bets[user.id] = (side, amount)
        await q.answer(f"✅ Đặt {side.upper()} {_fmt_money(amount)} thành công!", show_alert=True)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    
    # Xử lý tài xỉu
    if query.data.startswith("tx:"):
        await tx_cb_handler(update, context)
        return
    
    await query.answer()
    
    data = query.data
    chat_id = update.effective_chat.id
    user = update.effective_user
    username = user.username or user.first_name
    
    # Xử lý quiz
    if data.startswith("quiz_"):
        if data == "quiz_stop":
            total_questions = quiz_count.get(chat_id, 1) - 1
            
            if chat_id in quiz_mode:
                del quiz_mode[chat_id]
            if chat_id in quiz_sessions:
                del quiz_sessions[chat_id]
            if chat_id in quiz_count:
                del quiz_count[chat_id]
            if chat_id in quiz_history:
                quiz_history[chat_id] = []
                
            await query.message.edit_text(f"✅ Đã dừng câu đố!\n📊 Bạn đã trả lời {total_questions} câu")
            return
            
        if chat_id not in quiz_sessions:
            await query.message.edit_text("❌ Hết giờ!")
            return
            
        quiz = quiz_sessions[chat_id]
        answer = data.split("_")[1]
        
        if answer == quiz["correct"]:
            save_score(user.id, username, "quiz", 200)
            cs = _get_cs(chat_id)
            _ensure_balance(cs, user.id)
            cs.balances[user.id] += 200
            result = f"✅ Chính xác! (+200đ)\n\n{quiz['explanation']}"
        else:
            result = f"❌ Sai rồi! Đáp án: {quiz['correct']}\n\n{quiz['explanation']}"
        
        del quiz_sessions[chat_id]
        
        await query.message.edit_text(result)
        
        if chat_id in quiz_mode:
            wait_msg = await context.bot.send_message(
                chat_id, 
                "⏳ **Đợi 5 giây cho câu tiếp theo...**"
            )
            
            await asyncio.sleep(5)
            await wait_msg.delete()
            
            quiz_count[chat_id] = quiz_count.get(chat_id, 1) + 1
            
            loading_msg = await context.bot.send_message(chat_id, "⏳ Claude AI đang tạo câu hỏi mới...")
            
            quiz = await generate_quiz(chat_id)
            
            if not quiz:
                await loading_msg.edit_text("❌ Lỗi tạo câu hỏi! Dùng /quiz để thử lại")
                if chat_id in quiz_mode:
                    del quiz_mode[chat_id]
                return
            
            quiz_sessions[chat_id] = quiz
            
            keyboard = []
            for option in quiz["options"]:
                keyboard.append([InlineKeyboardButton(option, callback_data=f"quiz_{option[0]}")])
            keyboard.append([InlineKeyboardButton("❌ Dừng", callback_data="quiz_stop")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            topic_emojis = {
                "Lịch sử Việt Nam": "📜",
                "Địa lý Việt Nam": "🗺️",
                "Ẩm thực Việt Nam": "🍜",
                "Văn hóa Việt Nam": "🎭",
                "Khoa học Việt Nam": "🔬",
                "Thể thao Việt Nam": "⚽"
            }
            
            emoji = topic_emojis.get(quiz.get("topic", ""), "❓")
            message = f"{emoji} **CÂU {quiz_count[chat_id]} - {quiz.get('topic', '').upper()}**\n\n{quiz['question']}"
            
            await loading_msg.edit_text(message, reply_markup=reply_markup)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message.text
    chat_id = update.effective_chat.id
    user = update.effective_user
    username = user.username or user.first_name
    
    chat = update.effective_chat
    save_chat_info(chat.id, chat.type, chat.title)
    
    if chat_id in active_games:
        game_info = active_games[chat_id]
        
        if game_info["type"] == "guessnumber":
            try:
                guess = int(message)
                if 1 <= guess <= 100:
                    is_finished, response = game_info["game"].make_guess(guess)
                    await update.message.reply_text(response)
                    
                    if is_finished and "Đúng" in response:
                        save_score(user.id, username, "guessnumber", game_info["game"].score)
                        cs = _get_cs(chat_id)
                        _ensure_balance(cs, user.id)
                        cs.balances[user.id] += game_info["game"].score
                    
                    if is_finished:
                        del active_games[chat_id]
                else:
                    await update.message.reply_text("❌ Từ 1-100 thôi!")
            except ValueError:
                await update.message.reply_text("❌ Nhập số!")
                
        elif game_info["type"] == "vuatiengviet":
            game = game_info["game"]
            
            if message.lower() in ["tiếp", "tiep"]:
                loading_msg = await update.message.reply_text("⏳ Đang tạo câu mới...")
                msg = await game.start_new_round()
                await loading_msg.edit_text(msg)
            elif message.lower() in ["dừng", "dung", "stop"]:
                if game.score > 0:
                    save_score(user.id, username, "vuatiengviet", game.score)
                    cs = _get_cs(chat_id)
                    _ensure_balance(cs, user.id)
                    cs.balances[user.id] += game.score
                await update.message.reply_text(f"📊 Kết thúc!\nTổng điểm: {game.score}")
                del active_games[chat_id]
            else:
                is_correct, response = game.check_answer(message)
                await update.message.reply_text(response)
                
                if is_correct and "dừng" not in response.lower():
                    loading_msg = await context.bot.send_message(chat_id, "⏳ Đang tạo câu mới...")
                    await asyncio.sleep(2)
                    msg = await game.start_new_round()
                    await loading_msg.edit_text(msg)
        return
    
    # Chat với GPT
    if chat_id not in chat_history:
        chat_history[chat_id] = []
        
    chat_history[chat_id].append({"role": "user", "content": message})
    
    if len(chat_history[chat_id]) > 4:
        chat_history[chat_id] = chat_history[chat_id][-4:]
    
    messages = [
        {"role": "system", "content": "Bạn là Linh - cô gái Việt Nam vui vẻ, thân thiện. Trả lời ngắn gọn."}
    ]
    messages.extend(chat_history[chat_id])
    
    response = await call_api(messages, max_tokens=300)
    
    if response:
        chat_history[chat_id].append({"role": "assistant", "content": response})
        await update.message.reply_text(response)
    else:
        await update.message.reply_text("😅 Xin lỗi, mình đang gặp lỗi!")

async def post_init(application: Application) -> None:
    global goodnight_task
    goodnight_task = asyncio.create_task(goodnight_scheduler(application))
    logger.info("Goodnight scheduler started!")

async def post_shutdown(application: Application) -> None:
    global goodnight_task
    if goodnight_task:
        goodnight_task.cancel()
        try:
            await goodnight_task
        except asyncio.CancelledError:
            pass

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.post_init = post_init
    application.post_shutdown = post_shutdown
    
    # Command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("guessnumber", start_guess_number))
    application.add_handler(CommandHandler("vuatiengviet", start_vua_tieng_viet))
    application.add_handler(CommandHandler("quiz", quiz_command))
    application.add_handler(CommandHandler("stopquiz", stop_quiz))
    application.add_handler(CommandHandler("hint", hint_command))
    application.add_handler(CommandHandler("stats", stats_command))
    
    # Tài xỉu handlers
    application.add_handler(CommandHandler("taixiu", taixiu_cmd))
    application.add_handler(CommandHandler("bet", bet_cmd))
    application.add_handler(CommandHandler("stoptaixiu", stop_taixiu_cmd))
    application.add_handler(CommandHandler("bal", bal_cmd))
    application.add_handler(CommandHandler("leaderboard", leaderboard_taixiu_cmd))
    
    # Callback & message handlers
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("Linh Bot started! 💕")
    application.run_polling()

if __name__ == "__main__":
    main()
