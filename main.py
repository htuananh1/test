import os
import asyncio
import random
import json
import aiohttp
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)
from telegram.constants import ParseMode, ChatAction

from google import genai
from google.genai import types

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ["BOT_TOKEN"]
VERCEL_API_KEY = os.environ.get("VERCEL_API_KEY", "")
BASE_URL = os.getenv("BASE_URL", "https://ai-gateway.vercel.sh/v1")
CHAT_MODEL = os.getenv("CHAT_MODEL", "alibaba/qwen-3-235b")
CODE_MODEL = os.getenv("CODE_MODEL", "anthropic/claude-3.7-sonnet")
CLAUDE_HAIKU_MODEL = os.getenv("CLAUDE_HAIKU_MODEL", "anthropic/claude-3.5-haiku")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_IMAGE_MODEL = os.getenv("GEMINI_IMAGE_MODEL", "gemini-2.0-flash-preview-image-generation")
PAGE_CHARS = int(os.getenv("PAGE_CHARS", "3200"))
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "700"))
MAX_TOKENS_CODE = int(os.getenv("MAX_TOKENS_CODE", "4000"))
CTX_TURNS = int(os.getenv("CTX_TURNS", "15"))

user_games: Dict = {}
user_conversations: Dict[int, List[Dict]] = {}
user_preferences: Dict[int, Dict] = {}
user_states: Dict[int, str] = {}

class GameManager:
    def __init__(self):
        self.quiz_questions = [
            {
                "question": "Thủ đô của Việt Nam là gì?",
                "options": ["Hà Nội", "TP.HCM", "Đà Nẵng", "Huế"],
                "correct": 0
            },
            {
                "question": "Vịnh Hạ Long thuộc tỉnh nào?",
                "options": ["Quảng Nam", "Quảng Ninh", "Quảng Bình", "Quảng Trị"],
                "correct": 1
            },
            {
                "question": "Sông nào dài nhất Việt Nam?",
                "options": ["Sông Hồng", "Sông Cửu Long", "Sông Đà", "Sông Mã"],
                "correct": 1
            },
            {
                "question": "Món ăn nào là đặc sản của Huế?",
                "options": ["Phở", "Bún bò", "Bánh mì", "Bánh xèo"],
                "correct": 1
            },
            {
                "question": "Núi cao nhất Việt Nam?",
                "options": ["Bà Đen", "Fansipan", "Bà Nà", "Langbiang"],
                "correct": 1
            }
        ]
        
        self.riddles = [
            {"riddle": "Có lông mà không phải thú, có cánh mà không phải chim. Là gì?", "answer": "con dơi"},
            {"riddle": "Cái gì đen khi bạn mua nó, đỏ khi dùng nó và xám khi vứt nó đi?", "answer": "than"},
            {"riddle": "Cái gì có thể đi khắp thế giới nhưng vẫn ở trong góc?", "answer": "con tem"},
            {"riddle": "Có hai người, một người đi về hướng nam, một người đi về hướng bắc, sao họ vẫn nhìn thấy nhau?", "answer": "đối diện"},
            {"riddle": "Cái gì mà đi thì nằm, đứng cũng nằm, nhưng nằm lại đứng?", "answer": "bàn chân"}
        ]
        
        self.math_operations = ['+', '-', '*']
        
        self.tic_tac_toe_board = [[" " for _ in range(3)] for _ in range(3)]

    def create_tic_tac_toe_keyboard(self, board):
        keyboard = []
        for i in range(3):
            row = []
            for j in range(3):
                btn_text = board[i][j] if board[i][j] != " " else f"{i*3+j+1}"
                row.append(InlineKeyboardButton(btn_text, callback_data=f"ttt_{i}_{j}"))
            keyboard.append(row)
        keyboard.append([InlineKeyboardButton("🔄 Chơi lại", callback_data="ttt_reset")])
        return InlineKeyboardMarkup(keyboard)
    
    def check_winner(self, board):
        for i in range(3):
            if board[i][0] == board[i][1] == board[i][2] != " ":
                return board[i][0]
            if board[0][i] == board[1][i] == board[2][i] != " ":
                return board[0][i]
        
        if board[0][0] == board[1][1] == board[2][2] != " ":
            return board[0][0]
        if board[0][2] == board[1][1] == board[2][0] != " ":
            return board[0][2]
        
        for row in board:
            if " " in row:
                return None
        return "Draw"
    
    def ai_move(self, board):
        empty_cells = [(i, j) for i in range(3) for j in range(3) if board[i][j] == " "]
        if empty_cells:
            return random.choice(empty_cells)
        return None

class WeatherAI:
    async def get_weather_claude(self, city: str, detailed: bool = False) -> str:
        prompt = f"""
        Bạn là chuyên gia dự báo thời tiết Việt Nam. 
        Hãy dự báo thời tiết cho {city} hôm nay ({datetime.now().strftime('%d/%m/%Y')}).
        
        Thông tin cần cung cấp:
        1. Nhiệt độ (min-max)
        2. Tình trạng thời tiết (nắng/mưa/mây)
        3. Độ ẩm và chỉ số UV
        4. Lời khuyên cho người dân
        5. Dự báo ngắn 3 ngày tới
        
        {"Cung cấp phân tích CHI TIẾT về áp suất, gió, tầm nhìn và các yếu tố khác" if detailed else ""}
        
        Format với emoji phù hợp. Dựa vào mùa và khí hậu thực tế của Việt Nam.
        """
        
        response = await self.call_claude_ai(prompt)
        return response
    
    async def call_claude_ai(self, prompt: str) -> str:
        headers = {
            "Authorization": f"Bearer {VERCEL_API_KEY}",
            "Content-Type": "application/json"
        }
        
        data = {
            "model": CLAUDE_HAIKU_MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": "Bạn là trợ lý AI thông minh, chuyên về Việt Nam."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "max_tokens": 1000,
            "temperature": 0.7
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(f"{BASE_URL}/chat/completions", headers=headers, json=data) as response:
                    if response.status == 200:
                        result = await response.json()
                        return result['choices'][0]['message']['content']
                    else:
                        return "Lỗi khi kết nối với Claude AI"
        except Exception as e:
            logger.error(f"Claude API error: {e}")
            return "Đã xảy ra lỗi khi xử lý yêu cầu"

async def call_ai_model(prompt: str, model: str = CHAT_MODEL, max_tokens: int = MAX_TOKENS, context_messages: List = None) -> str:
    headers = {
        "Authorization": f"Bearer {VERCEL_API_KEY}",
        "Content-Type": "application/json"
    }
    
    messages = []
    if context_messages:
        messages.extend(context_messages)
    else:
        messages.append({"role": "user", "content": prompt})
    
    data = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.7
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{BASE_URL}/chat/completions", headers=headers, json=data) as response:
                if response.status == 200:
                    result = await response.json()
                    return result['choices'][0]['message']['content']
                else:
                    return f"Lỗi API: {response.status}"
    except Exception as e:
        logger.error(f"AI API error: {e}")
        return "Xin lỗi, đã có lỗi xảy ra khi xử lý yêu cầu của bạn."

async def generate_image(prompt: str) -> bytes:
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        
        contents = [
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=prompt)]
            )
        ]
        
        config = types.GenerateContentConfig(
            response_modalities=["IMAGE"]
        )
        
        response = client.models.generate_content(
            model=GEMINI_IMAGE_MODEL,
            contents=contents,
            config=config
        )
        
        if response.candidates and response.candidates[0].content.parts:
            for part in response.candidates[0].content.parts:
                if part.inline_data and part.inline_data.data:
                    return part.inline_data.data
    except Exception as e:
        logger.error(f"Image generation error: {e}")
    return None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    welcome_message = (
        f"Xin chào {user.first_name}! 👋\n\n"
        f"Tôi là Bot AI Việt Nam 🇻🇳\n\n"
        f"💬 **Chat trực tiếp:** Gửi tin nhắn bất kỳ\n"
        f"💻 **/code** - Viết code với AI\n"
        f"🖼 **/img** - Tạo ảnh từ văn bản\n"
        f"📚 **/help** - Xem tất cả lệnh\n\n"
        f"Bạn có thể chat với tôi ngay bây giờ!"
    )
    
    keyboard = [
        [InlineKeyboardButton("💬 Bắt đầu chat", callback_data="chat"),
         InlineKeyboardButton("🖼 Tạo ảnh", callback_data="image")],
        [InlineKeyboardButton("💻 Viết code", callback_data="code"),
         InlineKeyboardButton("🎮 Chơi game", callback_data="game")],
        [InlineKeyboardButton("📚 Trợ giúp", callback_data="help")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        welcome_message,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
📚 **HƯỚNG DẪN SỬ DỤNG BOT**

**💬 Chat AI:**
• Gửi tin nhắn trực tiếp để chat
• Bot nhớ {CTX_TURNS} tin nhắn gần nhất
• Hỏi bất cứ điều gì bằng tiếng Việt

**💻 Lập trình:**
• /code [yêu cầu] - Viết code với Claude AI
• Hỗ trợ mọi ngôn ngữ lập trình
• Giải thích code chi tiết

**🖼 Tạo ảnh:**
• /img [mô tả] - Tạo ảnh từ văn bản
• Mô tả chi tiết để có kết quả tốt
• VD: /img vẽ phong cảnh Vịnh Hạ Long

**🌤 Thời tiết:**
• /weather [thành phố] - Xem thời tiết
• Dự báo bằng Claude AI
• Lời khuyên theo mùa

**🎮 Trò chơi:**
• /game - Menu trò chơi
• /guess - Đoán số
• /quiz - Quiz Việt Nam
• /math - Toán học
• /riddle - Câu đố
• /wordchain - Nối từ
• /tictactoe - Cờ caro

**🇻🇳 Việt Nam:**
• /vietnam - Thông tin VN
• Hỏi về văn hóa, lịch sử, địa lý

**💡 Mẹo:**
• Gửi "thời tiết Hà Nội" để xem nhanh
• Hỏi "code Python tính giai thừa"
• Chat tự nhiên như với người
    """.format(CTX_TURNS=CTX_TURNS)
    
    keyboard = [
        [InlineKeyboardButton("💬 Chat ngay", callback_data="chat")],
        [InlineKeyboardButton("🎮 Chơi game", callback_data="game")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        help_text, 
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )

async def code_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not context.args:
        user_states[user_id] = "waiting_code_request"
        await update.message.reply_text(
            "💻 **VIẾT CODE VỚI CLAUDE AI**\n\n"
            "Bạn muốn viết code gì? Ví dụ:\n"
            "• Tạo web calculator bằng HTML/JS\n"
            "• Python script đọc file CSV\n"
            "• React component for todo list\n\n"
            "Hãy mô tả yêu cầu của bạn:"
        )
        return
    
    request = ' '.join(context.args)
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    
    prompt = f"""
    Yêu cầu: {request}
    
    Hãy viết code hoàn chỉnh với:
    1. Code đầy đủ, có thể chạy ngay
    2. Comments giải thích bằng tiếng Việt
    3. Xử lý lỗi cơ bản
    4. Ví dụ sử dụng (nếu cần)
    
    Format code với markdown syntax highlighting.
    """
    
    response = await call_ai_model(prompt, model=CODE_MODEL, max_tokens=MAX_TOKENS_CODE)
    
    if len(response) > PAGE_CHARS:
        parts = [response[i:i+PAGE_CHARS] for i in range(0, len(response), PAGE_CHARS)]
        for i, part in enumerate(parts):
            await update.message.reply_text(
                f"📄 Trang {i+1}/{len(parts)}\n\n{part}",
                parse_mode=ParseMode.MARKDOWN
            )
    else:
        await update.message.reply_text(response, parse_mode=ParseMode.MARKDOWN)

async def img_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not context.args:
        user_states[user_id] = "waiting_image_prompt"
        await update.message.reply_text(
            "🖼 **TẠO ẢNH VỚI AI**\n\n"
            "Mô tả hình ảnh bạn muốn tạo:\n"
            "• Phong cảnh: vẽ bãi biển hoàng hôn\n"
            "• Nhân vật: robot tương lai công nghệ cao\n"
            "• Trừu tượng: vũ trụ với các vì sao\n\n"
            "Mô tả càng chi tiết, ảnh càng đẹp!"
        )
        return
    
    prompt = ' '.join(context.args)
    
    await update.message.reply_text("🎨 Đang tạo ảnh, vui lòng đợi...")
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_PHOTO)
    
    enhanced_prompt = f"{prompt}, high quality, detailed, 4k resolution"
    
    image_data = await generate_image(enhanced_prompt)
    
    if image_data:
        await update.message.reply_photo(
            photo=image_data,
            caption=f"🖼 **Ảnh được tạo từ:** {prompt}\n\n💡 Mẹo: Thêm chi tiết để có ảnh đẹp hơn!"
        )
    else:
        await update.message.reply_text(
            "❌ Không thể tạo ảnh. Vui lòng thử lại với mô tả khác."
        )

async def weather_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    weather_ai = WeatherAI()
    
    if context.args:
        city = ' '.join(context.args)
    else:
        keyboard = [
            [InlineKeyboardButton("Hà Nội", callback_data="weather_hanoi"),
             InlineKeyboardButton("TP.HCM", callback_data="weather_hcm")],
            [InlineKeyboardButton("Đà Nẵng", callback_data="weather_danang"),
             InlineKeyboardButton("Cần Thơ", callback_data="weather_cantho")],
            [InlineKeyboardButton("Nha Trang", callback_data="weather_nhatrang"),
             InlineKeyboardButton("Đà Lạt", callback_data="weather_dalat")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "🌤 **Chọn thành phố để xem thời tiết:**",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
        return
    
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    
    weather_report = await weather_ai.get_weather_claude(city)
    
    keyboard = [
        [InlineKeyboardButton("📊 Chi tiết", callback_data=f"weather_detail_{city}"),
         InlineKeyboardButton("📈 7 ngày", callback_data=f"forecast_{city}")],
        [InlineKeyboardButton("🗺 Tư vấn du lịch", callback_data="travel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        weather_report,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )

async def game_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🎯 Đoán số", callback_data="game_guess"),
         InlineKeyboardButton("❓ Quiz VN", callback_data="game_quiz")],
        [InlineKeyboardButton("🧮 Toán học", callback_data="game_math"),
         InlineKeyboardButton("🤔 Câu đố", callback_data="game_riddle")],
        [InlineKeyboardButton("🔤 Nối từ", callback_data="game_wordchain"),
         InlineKeyboardButton("⭕ Cờ caro", callback_data="game_tictactoe")],
        [InlineKeyboardButton("✂️ Oẳn tù tì", callback_data="game_rps"),
         InlineKeyboardButton("🎲 Xúc xắc", callback_data="game_dice")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🎮 **CHỌN TRÒ CHƠI:**\n\n"
        "Chọn một trò chơi bên dưới để bắt đầu!",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    message_text = update.message.text
    
    if user_id in user_states:
        state = user_states[user_id]
        
        if state == "waiting_code_request":
            del user_states[user_id]
            context.args = message_text.split()
            await code_command(update, context)
            return
        
        elif state == "waiting_image_prompt":
            del user_states[user_id]
            context.args = message_text.split()
            await img_command(update, context)
            return
    
    if user_id in user_games:
        if 'guess_number' in user_games[user_id]:
            try:
                guess = int(message_text)
                game = user_games[user_id]['guess_number']
                game['attempts'] += 1
                
                if guess == game['number']:
                    await update.message.reply_text(
                        f"🎉 Chúc mừng! Số đúng là {game['number']}!\n"
                        f"Bạn đoán đúng sau {game['attempts']} lần thử!"
                    )
                    del user_games[user_id]['guess_number']
                elif game['attempts'] >= game['max_attempts']:
                    await update.message.reply_text(
                        f"😢 Hết lượt! Số đúng là {game['number']}"
                    )
                    del user_games[user_id]['guess_number']
                elif guess < game['number']:
                    await update.message.reply_text(
                        f"📈 Cao hơn! Còn {game['max_attempts'] - game['attempts']} lần"
                    )
                else:
                    await update.message.reply_text(
                        f"📉 Thấp hơn! Còn {game['max_attempts'] - game['attempts']} lần"
                    )
                return
            except ValueError:
                pass
        
        if 'math' in user_games[user_id]:
            try:
                answer = int(message_text)
                if answer == user_games[user_id]['math']['answer']:
                    user_games[user_id]['math']['score'] += 1
                    await update.message.reply_text(
                        f"✅ Đúng! Điểm: {user_games[user_id]['math']['score']}\n"
                        f"Gõ /math để chơi tiếp"
                    )
                else:
                    await update.message.reply_text(
                        f"❌ Sai! Đáp án: {user_games[user_id]['math']['answer']}\n"
                        f"Điểm: {user_games[user_id]['math']['score']}"
                    )
                del user_games[user_id]['math']['answer']
                return
            except ValueError:
                pass
    
    message_lower = message_text.lower()
    
    if any(word in message_lower for word in ['thời tiết', 'weather', 'mưa', 'nắng', 'nhiệt độ']):
        cities = ["Hà Nội", "TP.HCM", "Đà Nẵng", "Cần Thơ", "Nha Trang", "Đà Lạt"]
        city_found = None
        for city in cities:
            if city.lower() in message_lower:
                city_found = city
                break
        
        if city_found:
            weather_ai = WeatherAI()
            await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
            weather_report = await weather_ai.get_weather_claude(city_found)
            await update.message.reply_text(weather_report, parse_mode=ParseMode.MARKDOWN)
            return
    
    if any(word in message_lower for word in ['code', 'lập trình', 'python', 'javascript', 'html']):
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
        
        prompt = f"""
        Người dùng hỏi về lập trình: "{message_text}"
        
        Hãy trả lời với:
        1. Giải thích ngắn gọn
        2. Code mẫu (nếu cần)
        3. Giải thích code
        4. Gợi ý thêm
        
        Format code với markdown.
        """
        
        response = await call_ai_model(prompt, model=CODE_MODEL, max_tokens=MAX_TOKENS_CODE)
        await update.message.reply_text(response, parse_mode=ParseMode.MARKDOWN)
        return
    
    if any(word in message_lower for word in ['vẽ', 'tạo ảnh', 'hình', 'image', 'picture']):
        await update.message.reply_text(
            "🖼 Để tạo ảnh, dùng lệnh:\n"
            "`/img [mô tả hình ảnh]`\n\n"
            "Ví dụ: `/img vẽ mặt trời mọc trên biển`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    
    if user_id not in user_conversations:
        user_conversations[user_id] = []
    
    user_conversations[user_id].append({"role": "user", "content": message_text})
    
    if len(user_conversations[user_id]) > CTX_TURNS * 2:
        user_conversations[user_id] = user_conversations[user_id][-(CTX_TURNS * 2):]
    
    context_messages = [
        {
            "role": "system",
            "content": "Bạn là trợ lý AI thông minh cho người Việt Nam. Trả lời thân thiện, hữu ích và chính xác. Sử dụng emoji phù hợp."
        }
    ]
    context_messages.extend(user_conversations[user_id])
    
    response = await call_ai_model("", model=CHAT_MODEL, context_messages=context_messages)
    
    user_conversations[user_id].append({"role": "assistant", "content": response})
    
    if len(response) > PAGE_CHARS:
        parts = [response[i:i+PAGE_CHARS] for i in range(0, len(response), PAGE_CHARS)]
        for i, part in enumerate(parts):
            await update.message.reply_text(f"📄 Trang {i+1}/{len(parts)}\n\n{part}")
    else:
        await update.message.reply_text(response)

async def guess_number_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id not in user_games:
        user_games[user_id] = {}
    
    user_games[user_id]['guess_number'] = {
        'number': random.randint(1, 100),
        'attempts': 0,
        'max_attempts': 7
    }
    
    await update.message.reply_text(
        "🎯 **TRÒ CHƠI ĐOÁN SỐ**\n\n"
        "Tôi đang nghĩ một số từ 1 đến 100.\n"
        "Bạn có 7 lần đoán. Hãy gửi số dự đoán!"
    )

async def quiz_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    game_manager = GameManager()
    
    if user_id not in user_games:
        user_games[user_id] = {}
    
    question = random.choice(game_manager.quiz_questions)
    user_games[user_id]['quiz'] = {
        'question': question,
        'score': user_games[user_id].get('quiz', {}).get('score', 0)
    }
    
    keyboard = []
    for i, option in enumerate(question['options']):
        keyboard.append([InlineKeyboardButton(option, callback_data=f"quiz_{i}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"❓ **QUIZ VIỆT NAM**\n\n{question['question']}",
        reply_markup=reply_markup
    )

async def math_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    game_manager = GameManager()
    
    if user_id not in user_games:
        user_games[user_id] = {}
    
    num1 = random.randint(1, 50)
    num2 = random.randint(1, 50)
    operation = random.choice(game_manager.math_operations)
    
    if operation == '+':
        answer = num1 + num2
    elif operation == '-':
        answer = num1 - num2
    else:
        answer = num1 * num2
    
    user_games[user_id]['math'] = {
        'answer': answer,
        'score': user_games[user_id].get('math', {}).get('score', 0)
    }
    
    await update.message.reply_text(
        f"🧮 **GAME TOÁN HỌC**\n\n"
        f"Tính: {num1} {operation} {num2} = ?\n\n"
        f"Điểm hiện tại: {user_games[user_id]['math']['score']}"
    )

async def riddle_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    game_manager = GameManager()
    
    if user_id not in user_games:
        user_games[user_id] = {}
    
    riddle = random.choice(game_manager.riddles)
    user_games[user_id]['riddle'] = riddle
    
    await update.message.reply_text(
        f"🤔 **CÂU ĐỐ VUI**\n\n{riddle['riddle']}\n\n"
        f"Gửi câu trả lời của bạn!"
    )

async def tic_tac_toe_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    game_manager = GameManager()
    
    if user_id not in user_games:
        user_games[user_id] = {}
    
    user_games[user_id]['tictactoe'] = {
        'board': [[" " for _ in range(3)] for _ in range(3)],
        'player': 'X',
        'ai': 'O'
    }
    
    keyboard = game_manager.create_tic_tac_toe_keyboard(user_games[user_id]['tictactoe']['board'])
    
    await update.message.reply_text(
        "⭕ **CỜ CARO VỚI AI**\n\n"
        "Bạn là X, AI là O\n"
        "Chọn ô để đánh:",
        reply_markup=keyboard
    )

async def word_chain_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id not in user_games:
        user_games[user_id] = {}
    
    starter_words = ["con mèo", "bầu trời", "hoa sen", "đất nước", "tình yêu", "mặt trời", "biển cả"]
    start_word = random.choice(starter_words)
    
    user_games[user_id]['word_chain'] = {
        'last_word': start_word,
        'used_words': [start_word],
        'score': 0
    }
    
    await update.message.reply_text(
        f"🔤 **TRÒ CHƠI NỐI TỪ**\n\n"
        f"Từ đầu tiên: **{start_word}**\n"
        f"Hãy nối với một từ bắt đầu bằng chữ '{start_word.split()[-1][-1]}'\n\n"
        f"Gõ /stop để dừng chơi"
    )

async def vietnam_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    info_text = """
🇻🇳 **THÔNG TIN VỀ VIỆT NAM**

**Thông tin cơ bản:**
• Thủ đô: Hà Nội
• Dân số: ~98 triệu người
• Diện tích: 331,690 km²
• Ngôn ngữ: Tiếng Việt
• Tiền tệ: Đồng (VND)

**Địa lý:**
• 63 tỉnh thành
• 3,260 km bờ biển
• 2 đồng bằng lớn: Sông Hồng & Cửu Long

**Di sản UNESCO:**
• Vịnh Hạ Long
• Phố cổ Hội An
• Cố đô Huế
• Thánh địa Mỹ Sơn
• Phong Nha - Kẻ Bàng

**Ẩm thực nổi tiếng:**
• Phở, Bánh mì, Bún bò Huế
• Bánh xèo, Gỏi cuốn, Nem rán
    """
    
    keyboard = [
        [InlineKeyboardButton("🌤 Thời tiết", callback_data="weather")],
        [InlineKeyboardButton("🎮 Chơi Quiz VN", callback_data="game_quiz")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        info_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    game_manager = GameManager()
    
    if query.data == "help":
        await help_command(query, context)
    
    elif query.data == "chat":
        await query.message.reply_text(
            "💬 **SẴN SÀNG CHAT!**\n\n"
            "Gửi tin nhắn bất kỳ để bắt đầu trò chuyện.\n"
            "Tôi có thể:\n"
            "• Trả lời câu hỏi\n"
            "• Kể chuyện\n"
            "• Giải thích khái niệm\n"
            "• Tư vấn và hỗ trợ\n\n"
            "Hãy hỏi tôi bất cứ điều gì!"
        )
    
    elif query.data == "code":
        user_states[user_id] = "waiting_code_request"
        await query.message.reply_text(
            "💻 **VIẾT CODE**\n\n"
            "Bạn muốn viết code gì?\n"
            "Hãy mô tả chi tiết yêu cầu."
        )
    
    elif query.data == "image":
        user_states[user_id] = "waiting_image_prompt"
        await query.message.reply_text(
            "🖼 **TẠO ẢNH**\n\n"
            "Mô tả hình ảnh bạn muốn tạo:"
        )
    
    elif query.data == "game":
        await game_menu(query, context)
    
    elif query.data == "weather":
        await weather_command(query, context)
    
    elif query.data.startswith("weather_"):
        city_map = {
            "hanoi": "Hà Nội",
            "hcm": "TP.HCM", 
            "danang": "Đà Nẵng",
            "cantho": "Cần Thơ",
            "nhatrang": "Nha Trang",
            "dalat": "Đà Lạt"
        }
        city_code = query.data.split("_")[1]
        if city_code in city_map:
            city = city_map[city_code]
            weather_ai = WeatherAI()
            detailed = "detail" in query.data
            weather_report = await weather_ai.get_weather_claude(city, detailed)
            await query.message.reply_text(weather_report, parse_mode=ParseMode.MARKDOWN)
    
    elif query.data.startswith("game_"):
        game_type = query.data.split("_")[1]
        
        if game_type == "guess":
            await guess_number_game(query, context)
        elif game_type == "quiz":
            await quiz_game(query, context)
        elif game_type == "math":
            await math_game(query, context)
        elif game_type == "riddle":
            await riddle_game(query, context)
        elif game_type == "wordchain":
            await word_chain_game(query, context)
        elif game_type == "tictactoe":
            await tic_tac_toe_game(query, context)

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("code", code_command))
    application.add_handler(CommandHandler("img", img_command))
    application.add_handler(CommandHandler("weather", weather_command))
    application.add_handler(CommandHandler("game", game_menu))
    application.add_handler(CommandHandler("guess", guess_number_game))
    application.add_handler(CommandHandler("quiz", quiz_game))
    application.add_handler(CommandHandler("math", math_game))
    application.add_handler(CommandHandler("riddle", riddle_game))
    application.add_handler(CommandHandler("wordchain", word_chain_game))
    application.add_handler(CommandHandler("tictactoe", tic_tac_toe_game))
    application.add_handler(CommandHandler("vietnam", vietnam_info))
    
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
