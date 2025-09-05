import asyncio
import base64
import json
import logging
import os
import random
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import aiofiles
import pytz
from dotenv import load_dotenv
from github import Github
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from openai import AsyncOpenAI

load_dotenv()
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv('BOT_TOKEN')
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
GITHUB_REPO = os.getenv('GITHUB_REPO', 'htuananh1/Data-manager')
GITHUB_FILE_PATH = "bot_data.json"
LOCAL_BACKUP_FILE = "local_backup.json"
VIETNAM_TZ = pytz.timezone('Asia/Ho_Chi_Minh')
SAVE_INTERVAL = 30
MIN_UPDATE_INTERVAL = 0.1
GLOBAL_RATE_LIMIT = 25
BOT_OWNER_ID = 2026797305
AI_GATEWAY_API_KEY = os.getenv('AI_GATEWAY_API_KEY')
AI_MODEL = 'openai/gpt-4o'

ai_client = AsyncOpenAI(
    api_key=AI_GATEWAY_API_KEY,
    base_url='https://ai-gateway.vercel.sh/v1'
)

UserData = Dict[str, Any]

class GuessNumberGame:
    def __init__(self, min_val: int = 1, max_val: int = 100, bet: int = 0, secret_number: Optional[int] = None, guesses: int = 0, game_over: bool = False):
        self.min_val = min_val
        self.max_val = max_val
        self.secret_number = secret_number if secret_number is not None else random.randint(min_val, max_val)
        self.guesses = guesses
        self.game_over = game_over
        self.bet = bet

    def make_guess(self, guess: int) -> str:
        self.guesses += 1
        if guess == self.secret_number:
            self.game_over = True
            return "correct"
        return "higher" if guess < self.secret_number else "lower"

    def to_dict(self) -> Dict[str, Any]:
        return self.__dict__

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'GuessNumberGame':
        return cls(**data)

class HighLowGame:
    def __init__(self, bet: int = 0, current_card: Optional[int] = None, game_over: bool = False, win: bool = False):
        self.bet = bet
        self.current_card = current_card if current_card is not None else random.randint(1, 13)
        self.game_over = game_over
        self.win = win

    def play(self, choice: str) -> int:
        new_card = random.randint(1, 13)
        if new_card == self.current_card:
            self.win = False
        elif (choice == 'high' and new_card > self.current_card) or \
             (choice == 'low' and new_card < self.current_card):
            self.win = True
        else:
            self.win = False
        self.game_over = True
        return new_card

    def to_dict(self) -> Dict[str, Any]:
        return self.__dict__

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'HighLowGame':
        return cls(**data)

class DiceRollGame:
    def __init__(self, bet: int = 0, game_over: bool = False, win: bool = False, dice_result: Optional[Tuple[int, int]] = None):
        self.bet = bet
        self.game_over = game_over
        self.win = win
        self.dice_result = dice_result

    def roll_dice(self) -> Tuple[int, int]:
        d1 = random.randint(1, 6)
        d2 = random.randint(1, 6)
        self.dice_result = (d1, d2)
        self.game_over = True
        self.win = (d1 + d2 == 7)
        return self.dice_result

    def to_dict(self) -> Dict[str, Any]:
        return self.__dict__

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DiceRollGame':
        return cls(**data)

class RateLimiter:
    def __init__(self):
        self.user_last_action: Dict[int, float] = {}
        self.global_semaphore = asyncio.Semaphore(GLOBAL_RATE_LIMIT)
        self.lock = asyncio.Lock()

    async def acquire(self, user_id: int):
        async with self.global_semaphore:
            async with self.lock:
                last_action = self.user_last_action.get(user_id, 0)
            
            wait_time = MIN_UPDATE_INTERVAL - (asyncio.get_event_loop().time() - last_action)
            if wait_time > 0:
                await asyncio.sleep(wait_time)
            
            async with self.lock:
                self.user_last_action[user_id] = asyncio.get_event_loop().time()

rate_limiter = RateLimiter()

def get_user_rank(exp: float) -> Tuple[Dict, Optional[Dict]]:
    ranks = [
        {"name": "🌱 Newbie", "exp": 0},
        {"name": "🌳 Apprentice", "exp": 5000},
        {"name": "🌲 Adept", "exp": 20000},
        {"name": "🌴 Expert", "exp": 100000},
        {"name": "🔥 Master", "exp": 500000},
        {"name": "🌟 Grandmaster", "exp": 2000000},
        {"name": "⚡ Legend", "exp": 5000000},
        {"name": "🔮 Mystic", "exp": 10000000},
        {"name": "🌌 Celestial", "exp": 25000000},
        {"name": "👑 God", "exp": 100000000}
    ]
    user_rank = ranks[0]
    next_rank = None
    for i, rank in enumerate(ranks):
        if exp >= rank["exp"]:
            user_rank = rank
            next_rank = ranks[i + 1] if i + 1 < len(ranks) else None
        else:
            break
    return user_rank, next_rank

def fmt(num: float) -> str:
    if num is None:
        num = 0
    if num < 1000:
        return str(int(num))
    if num < 1e6:
        return f"{num/1000.0:.1f}K".replace('.0', '')
    if num < 1e9:
        return f"{num/1e6:.1f}M".replace('.0', '')
    return f"{num/1e9:.1f}B".replace('.0', '')

class Storage:
    @staticmethod
    async def save(data: Dict) -> None:
        try:
            async with aiofiles.open(LOCAL_BACKUP_FILE, 'w', encoding='utf-8') as f:
                await f.write(json.dumps(data, ensure_ascii=False, indent=2))
        except Exception as e:
            logger.error(f"Async save failed: {e}")

    @staticmethod
    async def load() -> Dict:
        if not os.path.exists(LOCAL_BACKUP_FILE):
            return {}
        try:
            async with aiofiles.open(LOCAL_BACKUP_FILE, 'r', encoding='utf-8') as f:
                return json.loads(await f.read())
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

class DataManager:
    def __init__(self):
        self.users: Dict[str, UserData] = {}
        self.lock = asyncio.Lock()
        self.github = Github(GITHUB_TOKEN) if GITHUB_TOKEN else None
        self.repo = self.github.get_repo(GITHUB_REPO) if self.github else None
        self._autosave_task: Optional[asyncio.Task] = None

    async def initialize(self):
        self.users = await Storage.load()
        if not self.users:
            await self.sync_from_github()
        self._autosave_task = asyncio.create_task(self.auto_save_loop())

    async def sync_from_github(self):
        if not self.repo:
            return
        loop = asyncio.get_event_loop()
        try:
            file_content = await loop.run_in_executor(None, self.repo.get_contents, GITHUB_FILE_PATH)
            self.users = json.loads(base64.b64decode(file_content.content).decode())
            await Storage.save(self.users)
            logger.info("Successfully synced from GitHub.")
        except Exception as e:
            logger.error(f"GitHub sync failed: {e}")

    async def auto_save_loop(self):
        while True:
            await asyncio.sleep(SAVE_INTERVAL)
            async with self.lock:
                await Storage.save(self.users)
            logger.debug("Autosave complete.")

    async def get_user(self, uid: int) -> UserData:
        uid_str = str(uid)
        async with self.lock:
            user = self.users.get(uid_str)
            if not user:
                user = self.users[uid_str] = self.new_user(uid_str)
            
            defaults = {
                'total_exp': 0, 'minigames': {},
                'stats': {'cl_win': 0, 'cl_lose': 0, 'hl_win': 0, 'hl_lose': 0},
                'daily_streak': 0, 'last_daily': None,
                'minigame_streaks': {}
            }
            for k, v in defaults.items():
                user.setdefault(k, v)

            for game_name, game_obj_dict in list(user['minigames'].items()):
                if not game_obj_dict or game_obj_dict.get('game_over', True):
                    del user['minigames'][game_name]
            return user

    async def update_user(self, uid: int, data: UserData):
        async with self.lock:
            self.users[str(uid)] = data

    def new_user(self, uid: str) -> UserData:
        return {"user_id": uid, "username": "", "coins": 100, "created_at": datetime.now().isoformat()}

    async def get_top_users(self, key: str, limit: int = 10) -> List[UserData]:
        async with self.lock:
            return sorted(self.users.values(), key=lambda x: x.get(key, 0), reverse=True)[:limit]

    async def shutdown(self):
        if self._autosave_task:
            self._autosave_task.cancel()
        await Storage.save(self.users)
        logger.info("DataManager shut down gracefully.")

dm = DataManager()

def add_exp(user: UserData, exp: int):
    user['total_exp'] = user.get('total_exp', 0) + exp

def get_game_bet(user: UserData) -> int:
    bet = int(user.get('coins', 0) * 0.10)
    return max(10, bet)

def get_exp_reward(user: UserData, bet: int) -> int:
    return 1000

def _update_minigame_streak(user: UserData, game_name: str, won: bool):
    streaks = user.setdefault('minigame_streaks', {})
    game_streak = streaks.setdefault(game_name, {'losses': 0, 'guaranteed_win': False})

    if won:
        game_streak['losses'] = 0
        game_streak['guaranteed_win'] = False
    else:
        game_streak['losses'] += 1
        if game_streak['losses'] >= 3:
            game_streak['guaranteed_win'] = True
            game_streak['losses'] = 0

async def safe_edit_message(bot: Bot, chat_id: int, msg_id: int, text: str, kbd: InlineKeyboardMarkup):
    try:
        await bot.edit_message_text(text, chat_id, msg_id, reply_markup=kbd, parse_mode='Markdown')
    except Exception as e:
        if "message is not modified" not in str(e).lower():
            logger.warning(f"Edit failed: {e}")

async def update_username_if_needed(user_id: int, telegram_user: Update.effective_user):
    db_user = await dm.get_user(user_id)
    new_username = f"@{telegram_user.username}" if telegram_user.username else telegram_user.first_name
    
    if db_user.get("username") != new_username:
        db_user["username"] = new_username
        await dm.update_user(user_id, db_user)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user:
        return
    user, uid = update.effective_user, update.effective_user.id
    await rate_limiter.acquire(uid)
    await update_username_if_needed(uid, user)
    await update.message.reply_text("✨ **MINI GAME BOT** ✨\n\nChào mừng! Bot đã được cập nhật với các trò chơi mới. Sử dụng /menu để khám phá.", parse_mode='Markdown')

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user:
        return
    uid = update.effective_user.id
    await rate_limiter.acquire(uid)
    await update_username_if_needed(uid, update.effective_user)
    user = await dm.get_user(uid)
    rank, next_rank = get_user_rank(user.get('total_exp', 0))
    
    exp_str = f"{fmt(user.get('total_exp', 0))}"
    if next_rank:
        exp_str += f" / {fmt(next_rank['exp'])}"

    txt = f"""
👤 **{user.get('username', 'Player')}**
- 🏆 **Rank:** {rank['name']}
- ⭐ **EXP:** {exp_str}
- 💰 **Xu:** {fmt(user['coins'])}
"""
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🪙 Tung Đồng Xu", callback_data='game_coinflip'), InlineKeyboardButton("🎰 Máy Xèng", callback_data='game_slots')],
        [InlineKeyboardButton("💎 Kho Báu", callback_data='game_treasure'), InlineKeyboardButton("✊ Oẳn Tù Tì", callback_data='rps_start')],
        [InlineKeyboardButton("🔢 Đoán Số", callback_data='guess_start'), InlineKeyboardButton("🃏 Cao/Thấp", callback_data='game_highlow')],
        [InlineKeyboardButton("🎲 Chẵn Lẻ", callback_data='game_chanle'), InlineKeyboardButton("🎲 Tài Xỉu", callback_data='game_taixiu'), InlineKeyboardButton("🎲 Lắc Xúc Xắc", callback_data='game_diceroll')],
        [InlineKeyboardButton("🎡 Vòng Quay", callback_data='game_luckywheel'), InlineKeyboardButton("🎁 Điểm Danh", callback_data='daily_bonus')],
        [InlineKeyboardButton("📊 Thống Kê", callback_data='stats'), InlineKeyboardButton("🏆 Bảng Xếp Hạng", callback_data='ranking')],
        [InlineKeyboardButton("📖 Hướng Dẫn", callback_data='help')]
    ])
    
    if update.callback_query:
        await safe_edit_message(context.bot, update.effective_chat.id, update.callback_query.message.message_id, txt, kb)
    else:
        await update.message.reply_text(txt, reply_markup=kb, parse_mode='Markdown')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q or not q.from_user:
        return
    await q.answer()
    uid = q.from_user.id
    await update_username_if_needed(uid, q.from_user)
    data = q.data
    await rate_limiter.acquire(uid)

    if data.startswith('rps_play_'):
        await handle_rps(update, context)
    elif data.startswith('cf_play_'):
        await handle_coin_flip_play(update, context)
    elif data.startswith('taixiu_'):
        await handle_taixiu_bet(update, context)
    elif data.startswith('treasure_chest_'):
        await handle_treasure_choice(update, context)
    elif data.startswith('hl_play_'):
        await handle_highlow_play(update, context)
    elif data.startswith('dr_play_'):
        await handle_dice_roll_play(update, context)
    elif data.startswith('chanle_play_'):
        await handle_chanle_play(update, context)
    else:
        handlers = {
            'game_treasure': handle_treasure_hunt, 'game_chanle': handle_chanle, 'game_highlow': handle_highlow_start,
            'game_taixiu': handle_taixiu, 'game_luckywheel': handle_lucky_wheel, 'daily_bonus': handle_daily_bonus,
            'stats': handle_stats, 'ranking': handle_ranking, 'top_coins': handle_top_coins, 'top_rank': handle_top_rank,
            'help': handle_help, 'back_menu': menu, 'guess_start': guess_game, 'rps_start': rps_start, 
            'game_coinflip': handle_coin_flip_start,
            'game_slots': handle_slot_machine_start,
            'game_diceroll': handle_dice_roll_start,
        }
        if data in handlers:
            await handlers[data](update, context)

async def guess_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user:
        return
    uid = update.effective_user.id
    user = await dm.get_user(uid)
    
    if update.callback_query:
        if 'guess_number' in user.get('minigames', {}):
            await context.bot.answer_callback_query(update.callback_query.id, "Bạn đang trong ván chơi rồi!", show_alert=True)
            return

        bet = get_game_bet(user)
        if user['coins'] < bet:
            await context.bot.answer_callback_query(update.callback_query.id, f"❌ Cần {fmt(bet)} xu!", show_alert=True)
            return
        
        user['coins'] -= bet
        game = GuessNumberGame(bet=bet)
        user['minigames']['guess_number'] = game.to_dict()
        await dm.update_user(uid, user)
        
        text = f"🤔 **ĐOÁN SỐ** 🤔\n\nTôi đã nghĩ một số từ {game.min_val} đến {game.max_val}.\n(Cược: {fmt(bet)} xu)\nHãy trả lời tin nhắn này với số bạn đoán!"
        await safe_edit_message(context.bot, update.effective_chat.id, update.callback_query.message.message_id, text, InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Menu", callback_data='back_menu')]]))
        return

    if update.message and update.message.text:
        game_dict = user.get('minigames', {}).get('guess_number')
        if not game_dict:
            await update.message.reply_text("Bắt đầu game Đoán Số từ /menu đã.", reply_to_message_id=update.message.message_id)
            return
        
        game = GuessNumberGame.from_dict(game_dict)

        try:
            guess = int(update.message.text)
        except (ValueError, IndexError):
            await update.message.reply_text("Vui lòng nhập một số hợp lệ.", reply_to_message_id=update.message.message_id)
            return

        result = game.make_guess(guess)
        user['minigames']['guess_number'] = game.to_dict()

        if result == "correct":
            prize = game.bet * 2.5
            exp = get_exp_reward(user, game.bet)
            user['coins'] += prize
            add_exp(user, exp)
            del user['minigames']['guess_number']
            txt = f"🎉 **CHÍNH XÁC!** 🎉\nSố bí mật là {game.secret_number}.\nBạn đoán đúng sau {game.guesses} lần.\n\n> 💰 **Thưởng:** {fmt(prize)} xu\n> ⭐ **Kinh nghiệm:** +{fmt(exp)} EXP"
            await update.message.reply_text(txt, reply_to_message_id=update.message.message_id)
        elif result == "higher":
            await update.message.reply_text("⬆️ Cao hơn!", reply_to_message_id=update.message.message_id)
        else:
            await update.message.reply_text("⬇️ Thấp hơn!", reply_to_message_id=update.message.message_id)
        
        await dm.update_user(uid, user)

async def rps_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.callback_query:
        return
    bet = get_game_bet(await dm.get_user(update.effective_user.id))
    keyboard = [[
        InlineKeyboardButton("✌️ Kéo", callback_data='rps_play_scissors'),
        InlineKeyboardButton("✋ Bao", callback_data='rps_play_paper'),
        InlineKeyboardButton("✊ Búa", callback_data='rps_play_rock')
    ], [InlineKeyboardButton("↩️ Menu", callback_data='back_menu')]]
    text = f"Oẳn tù tì!\nCược: **{fmt(bet)} xu**"
    await safe_edit_message(context.bot, update.effective_chat.id, update.callback_query.message.message_id, text, InlineKeyboardMarkup(keyboard))

async def handle_rps(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q or not q.from_user:
        return
    user_choice = q.data.split('_')[2]
    uid = q.from_user.id
    user = await dm.get_user(uid)
    
    bet = get_game_bet(user)
    if user['coins'] < bet:
        await q.answer(f"❌ Cần {fmt(bet)} xu!", show_alert=True)
        return
    user['coins'] -= bet

    game_name = 'rps'
    streaks = user.setdefault('minigame_streaks', {})
    game_streak = streaks.setdefault(game_name, {'losses': 0, 'guaranteed_win': False})
    forced_win = game_streak.get('guaranteed_win', False)
    if forced_win:
        game_streak['guaranteed_win'] = False

    choices = ['rock', 'paper', 'scissors']
    bot_choice = random.choice(choices)
    
    outcomes = {('rock', 'scissors'): 'win', ('scissors', 'paper'): 'win', ('paper', 'rock'): 'win'}
    choice_text = {'rock': '✊ Búa', 'paper': '✋ Bao', 'scissors': '✌️ Kéo'}
    
    result_text = f"Bạn chọn: {choice_text[user_choice]}\nBot chọn: {choice_text[bot_choice]}\n\n" 
    
    won = False
    if user_choice == bot_choice:
        result = f"⚖️ **HÒA!**\n(Hoàn lại {fmt(bet)} xu)"
        user['coins'] += bet
        won = True
    elif (outcomes.get((user_choice, bot_choice)) == 'win') or forced_win:
        if forced_win and outcomes.get((user_choice, bot_choice)) != 'win':
            if user_choice == 'rock': bot_choice = 'scissors'
            elif user_choice == 'paper': bot_choice = 'rock'
            elif user_choice == 'scissors': bot_choice = 'paper'
            result_text = f"Bạn chọn: {choice_text[user_choice]}\nBot chọn: {choice_text[bot_choice]}\n\n"

        prize = bet * 2.5
        exp = get_exp_reward(user, bet)
        user['coins'] += prize
        add_exp(user, exp)
        result = f"🎉 **BẠN THẮNG!**\n\n> 💰 **Thưởng:** +{fmt(prize)} xu\n> ⭐ **Kinh nghiệm:** +{fmt(exp)} EXP"
        if forced_win:
            result = "✨ **Bảo hiểm kích hoạt!** ✨\n" + result
        won = True
    else:
        result = f"😢 **BẠN THUA!**\n\n> 💸 **Mất:** {fmt(bet)} xu"
        won = False

    _update_minigame_streak(user, game_name, won)
    await dm.update_user(uid, user)
    await safe_edit_message(context.bot, q.message.chat_id, q.message.message_id, result_text + result, InlineKeyboardMarkup([[InlineKeyboardButton("Chơi lại", callback_data='rps_start'), InlineKeyboardButton("↩️ Menu", callback_data='back_menu')]]))

async def handle_coin_flip_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.callback_query:
        return
    uid = update.effective_user.id
    user = await dm.get_user(uid)
    bet = get_game_bet(user)
    if user['coins'] < bet:
        await context.bot.answer_callback_query(update.callback_query.id, f"❌ Cần {fmt(bet)} xu!", show_alert=True)
        return

    keyboard = [[
        InlineKeyboardButton("🪙 Ngửa (Heads)", callback_data='cf_play_heads'),
        InlineKeyboardButton("🌑 Sấp (Tails)", callback_data='cf_play_tails')
    ], [InlineKeyboardButton("↩️ Menu", callback_data='back_menu')]]
    text = f"🪙 **TUNG ĐỒNG XU** 🪙\n\nCược: **{fmt(bet)} xu**\nChọn Sấp hoặc Ngửa:"
    await safe_edit_message(context.bot, update.effective_chat.id, update.callback_query.message.message_id, text, InlineKeyboardMarkup(keyboard))

async def handle_coin_flip_play(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q or not q.from_user:
        return
    uid = q.from_user.id
    user = await dm.get_user(uid)
    
    user_choice = q.data.split('_')[2]
    bet = get_game_bet(user)

    if user['coins'] < bet:
        await q.answer(f"❌ Cần {fmt(bet)} xu!", show_alert=True)
        return
    user['coins'] -= bet

    game_name = 'coinflip'
    streaks = user.setdefault('minigame_streaks', {})
    game_streak = streaks.setdefault(game_name, {'losses': 0, 'guaranteed_win': False})
    forced_win = game_streak.get('guaranteed_win', False)
    if forced_win:
        game_streak['guaranteed_win'] = False

    actual_result = random.choice(['heads', 'tails'])
    
    won = forced_win or (user_choice == actual_result)
    if forced_win:
        result = user_choice
    else:
        result = actual_result

    _update_minigame_streak(user, game_name, won)

    result_text = f"Đồng xu rơi... **{actual_result.upper()}**!\n\n" 

    if won:
        prize = bet * 2.5
        exp = get_exp_reward(user, bet)
        user['coins'] += prize
        add_exp(user, exp)
        txt = f"🎉 **BẠN THẮNG!**\n\n> 💰 **Thưởng:** +{fmt(prize)} xu\n> ⭐ **Kinh nghiệm:** +{fmt(exp)} EXP"
        if forced_win:
            txt = "✨ **Bảo hiểm kích hoạt!** ✨\n" + txt
    else:
        txt = f"😢 **BẠN THUA!**\n\n> 💸 **Mất:** {fmt(bet)} xu"
        
    await dm.update_user(uid, user)
    await safe_edit_message(context.bot, q.message.chat_id, q.message.message_id, result_text + txt, InlineKeyboardMarkup([[InlineKeyboardButton("Chơi lại", callback_data='game_coinflip'), InlineKeyboardButton("↩️ Menu", callback_data='back_menu')]]))

async def handle_slot_machine_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q or not q.from_user:
        return
    uid = q.from_user.id
    user = await dm.get_user(uid)
    bet = get_game_bet(user)
    if user['coins'] < bet:
        await q.answer(f"❌ Cần {fmt(bet)} xu!", show_alert=True)
        return
    
    user['coins'] -= bet

    game_name = 'slots'
    streaks = user.setdefault('minigame_streaks', {})
    game_streak = streaks.setdefault(game_name, {'losses': 0, 'guaranteed_win': False})
    forced_win = game_streak.get('guaranteed_win', False)
    if forced_win:
        game_streak['guaranteed_win'] = False

    reels = ['🍒', '🍋', '🍊', '🍉', '💰', '💎', '💔']
    
    if forced_win:
        win_symbol = random.choice(['💰', '🍉', '🍒'])
        results = [win_symbol, win_symbol, win_symbol]
    else:
        results = random.choices(reels, weights=[10, 10, 10, 5, 4, 2, 15], k=3)

    payouts = {
        ('💎', '💎', '💎'): 10,
        ('💰', '💰', '💰'): 5,
        ('🍉', '🍉', '🍉'): 4,
        ('🍊', '🍊', '🍊'): 3,
        ('🍋', '🍋', '🍋'): 3,
        ('🍒', '🍒', '🍒'): 3,
    }
    
    win_multiplier = 0
    if results[0] == results[1] == results[2]:
        win_multiplier = payouts.get(tuple(results), 0)
    else:
        checked_symbols = set()
        for symbol in results:
            if symbol in checked_symbols:
                continue
            if results.count(symbol) == 2:
                if symbol == '💎':
                    win_multiplier = 2
                    break
                if symbol == '💰':
                    win_multiplier = 1.5
                    break
                if symbol in ['🍉', '🍊', '🍋', '🍒']:
                    win_multiplier = 1
                    break
            checked_symbols.add(symbol)

    prize = int(bet * win_multiplier)
    won = prize > bet
    _update_minigame_streak(user, game_name, won)
    
    result_text = f"🎰 **MÁY XÈNG** 🎰\n\n`{results[0]} | {results[1]} | {results[2]}`\n\n" 

    if win_multiplier > 1:
        user['coins'] += prize
        exp = get_exp_reward(user, bet)
        add_exp(user, exp)
        txt = f"🎉 **THẮNG LỚN!**\n\n> 💰 **Thưởng:** +{fmt(prize - bet)} xu\n> ⭐ **Kinh nghiệm:** +{fmt(exp)} EXP"
        if forced_win:
            txt = "✨ **Bảo hiểm kích hoạt!** ✨\n" + txt
    elif win_multiplier == 1:
        user['coins'] += prize
        txt = f"😌 **HÒA VỐN!**\n\n> Bạn được hoàn lại tiền cược: {fmt(bet)} xu"
    else:
        txt = f"😢 **THUA!**\n\n> 💸 **Mất:** {fmt(bet)} xu"

    await dm.update_user(uid, user)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("Quay tiếp", callback_data='game_slots'), InlineKeyboardButton("↩️ Menu", callback_data='back_menu')] ])
    await safe_edit_message(context.bot, q.message.chat_id, q.message.message_id, result_text + txt, kb)

async def handle_taixiu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.callback_query:
        return
    uid = update.effective_user.id
    user = await dm.get_user(uid)
    bet = get_game_bet(user)
    if user['coins'] < bet:
        await context.bot.answer_callback_query(update.callback_query.id, f"❌ Cần {fmt(bet)} xu!", show_alert=True)
        return
    
    keyboard = [[
        InlineKeyboardButton("Tài (11-18)", callback_data=f'taixiu_tai_{bet}'),
        InlineKeyboardButton("Xỉu (3-10)", callback_data=f'taixiu_xiu_{bet}')
    ], [InlineKeyboardButton("↩️ Menu", callback_data='back_menu')]]
    text = f"🎲 **TÀI XỈU** 🎲\n\nCược: **{fmt(bet)} xu**\nChọn Tài hoặc Xỉu:"
    await safe_edit_message(context.bot, update.effective_chat.id, update.callback_query.message.message_id, text, InlineKeyboardMarkup(keyboard))

async def handle_taixiu_bet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q or not q.from_user:
        return
    uid = q.from_user.id
    user = await dm.get_user(uid)
    
    _, choice, bet_str = q.data.split('_')
    bet = int(bet_str)

    if user['coins'] < bet:
        await q.answer(f"❌ Cần {fmt(bet)} xu!", show_alert=True)
        return
    user['coins'] -= bet
    
    game_name = 'taixiu'
    streaks = user.setdefault('minigame_streaks', {})
    game_streak = streaks.setdefault(game_name, {'losses': 0, 'guaranteed_win': False})
    forced_win = game_streak.get('guaranteed_win', False)
    if forced_win:
        game_streak['guaranteed_win'] = False

    d1, d2, d3 = random.randint(1, 6), random.randint(1, 6), random.randint(1, 6)
    total = d1 + d2 + d3
    actual_result = 'tai' if 11 <= total <= 18 else 'xiu'
    
    won = forced_win or (choice == actual_result)
    if forced_win:
        result = choice
    else:
        result = actual_result

    _update_minigame_streak(user, game_name, won)

    result_text = f"Kết quả: `{d1}` + `{d2}` + `{d3}` = **{total}** ({actual_result.upper()})\n\n" 

    if won:
        prize = bet * 2.5
        exp = get_exp_reward(user, bet)
        user['coins'] += prize
        add_exp(user, exp)
        txt = f"🎉 **THẮNG!**\n\n> 💰 **Thưởng:** +{fmt(prize)} xu\n> ⭐ **Kinh nghiệm:** +{fmt(exp)} EXP"
        if forced_win:
            txt = "✨ **Bảo hiểm kích hoạt!** ✨\n" + txt
    else:
        txt = f"😢 **THUA!**\n\n> 💸 **Mất:** {fmt(bet)} xu"
        
    await dm.update_user(uid, user)
    await safe_edit_message(context.bot, q.message.chat_id, q.message.message_id, result_text + txt, InlineKeyboardMarkup([[InlineKeyboardButton("Chơi lại", callback_data='game_taixiu'), InlineKeyboardButton("↩️ Menu", callback_data='back_menu')]]))

async def handle_treasure_hunt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.callback_query:
        return
    uid = update.effective_user.id
    user = await dm.get_user(uid)
    bet = get_game_bet(user)
    if user['coins'] < bet:
        await context.bot.answer_callback_query(update.callback_query.id, f"❌ Cần {fmt(bet)} xu!", show_alert=True)
        return

    keyboard = [[
        InlineKeyboardButton("Rương 1", callback_data='treasure_chest_1'),
        InlineKeyboardButton("Rương 2", callback_data='treasure_chest_2'),
        InlineKeyboardButton("Rương 3", callback_data='treasure_chest_3')
    ], [InlineKeyboardButton("↩️ Menu", callback_data='back_menu')]]
    
    text = f"💎 **SĂN KHO BÁU** 💎\n\nChọn một trong ba rương để mở.\nCược: **{fmt(bet)} xu**"
    await safe_edit_message(context.bot, update.effective_chat.id, update.callback_query.message.message_id, text, InlineKeyboardMarkup(keyboard))

async def handle_treasure_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q or not q.from_user:
        return
    uid = q.from_user.id
    user = await dm.get_user(uid)
    bet = get_game_bet(user)

    if user['coins'] < bet:
        await q.answer(f"❌ Cần {fmt(bet)} xu!", show_alert=True)
        return
    
    user['coins'] -= bet

    prizes = [0, 0, 2.5]
    random.shuffle(prizes)
    chosen_multiplier = random.choice(prizes)
    prize_amount = int(bet * chosen_multiplier)
    
    if prize_amount > 0:
        user['coins'] += prize_amount
        exp = get_exp_reward(user, bet)
        add_exp(user, exp)
        txt = f"🎉 **BẠN TÌM THẤY KHO BÁU!**\n\n> 💰 **Thưởng:** +{fmt(prize_amount - bet)} xu\n> ⭐ **Kinh nghiệm:** +{fmt(exp)} EXP"
    else:
        txt = f"😢 **RƯƠNG RỖNG!**\n\n> 💸 **Mất:** {fmt(bet)} xu"

    await dm.update_user(uid, user)
    await safe_edit_message(context.bot, q.message.chat_id, q.message.message_id, txt, InlineKeyboardMarkup([[InlineKeyboardButton("Chơi lại", callback_data='game_treasure'), InlineKeyboardButton("↩️ Menu", callback_data='back_menu')]]))

async def handle_highlow_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.callback_query:
        return
    uid = update.effective_user.id
    user = await dm.get_user(uid)
    bet = get_game_bet(user)

    if user['coins'] < bet:
        await context.bot.answer_callback_query(update.callback_query.id, f"❌ Cần {fmt(bet)} xu!", show_alert=True)
        return
    
    user['coins'] -= bet
    game = HighLowGame(bet=bet)
    user['minigames']['highlow'] = game.to_dict()
    await dm.update_user(uid, user)

    keyboard = [[
        InlineKeyboardButton("⬆️ Cao Hơn", callback_data='hl_play_high'),
        InlineKeyboardButton("⬇️ Thấp Hơn", callback_data='hl_play_low')
    ], [InlineKeyboardButton("↩️ Menu", callback_data='back_menu')]]
    
    text = f"🃏 **CAO / THẤP** 🃏\n\nLá bài hiện tại là: **{game.current_card}**\nCược: **{fmt(bet)} xu**\n\nĐoán xem lá tiếp theo cao hơn hay thấp hơn?"
    await safe_edit_message(context.bot, update.effective_chat.id, update.callback_query.message.message_id, text, InlineKeyboardMarkup(keyboard))

async def handle_highlow_play(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q or not q.from_user:
        return
    uid = q.from_user.id
    user = await dm.get_user(uid)
    game_dict = user.get('minigames', {}).get('highlow')
    if not game_dict:
        return

    game = HighLowGame.from_dict(game_dict)
    choice = q.data.split('_')[2]

    game_name = 'highlow'
    streaks = user.setdefault('minigame_streaks', {})
    game_streak = streaks.setdefault(game_name, {'losses': 0, 'guaranteed_win': False})
    forced_win = game_streak.get('guaranteed_win', False)
    if forced_win:
        game_streak['guaranteed_win'] = False

    if forced_win:
        if choice == 'high':
            game.current_card = random.randint(1, 12)
            new_card = random.randint(game.current_card + 1, 13)
        else:
            game.current_card = random.randint(2, 13)
            new_card = random.randint(1, game.current_card - 1)
        game.win = True
    else:
        new_card = game.play(choice)

    del user['minigames']['highlow']

    _update_minigame_streak(user, game_name, game.win)

    result_text = f"Lá bài mới là **{new_card}**.\n\n" 

    if game.win:
        prize = game.bet * 2.5
        exp = get_exp_reward(user, game.bet)
        user['coins'] += prize
        add_exp(user, exp)
        txt = f"🎉 **THẮNG!**\n\n> 💰 **Thưởng:** +{fmt(prize)} xu\n> ⭐ **Kinh nghiệm:** +{fmt(exp)} EXP"
        if forced_win:
            txt = "✨ **Bảo hiểm kích hoạt!** ✨\n" + txt
    else:
        txt = f"😢 **THUA!**\n\n> 💸 **Mất:** {fmt(game.bet)} xu"
    
    await dm.update_user(uid, user)
    await safe_edit_message(context.bot, q.message.chat_id, q.message.message_id, result_text + txt, InlineKeyboardMarkup([[InlineKeyboardButton("Chơi lại", callback_data='game_highlow'), InlineKeyboardButton("↩️ Menu", callback_data='back_menu')]]))

async def handle_dice_roll_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.callback_query:
        return
    uid = update.effective_user.id
    user = await dm.get_user(uid)
    bet = get_game_bet(user)

    if user['coins'] < bet:
        await context.bot.answer_callback_query(update.callback_query.id, f"❌ Cần {fmt(bet)} xu!", show_alert=True)
        return

    keyboard = [[ 
        InlineKeyboardButton("🎲 Lắc Xúc Xắc", callback_data='dr_play_roll')
    ], [InlineKeyboardButton("↩️ Menu", callback_data='back_menu')]]

    text = f"🎲 **LẮC XÚC XẮC** 🎲\n\nCược: **{fmt(bet)} xu**\n\nNếu tổng 2 xúc xắc là 7, bạn thắng!"
    await safe_edit_message(context.bot, update.effective_chat.id, update.callback_query.message.message_id, text, InlineKeyboardMarkup(keyboard))

async def handle_dice_roll_play(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q or not q.from_user:
        return
    uid = q.from_user.id
    user = await dm.get_user(uid)

    bet = get_game_bet(user)

    if user['coins'] < bet:
        await q.answer(f"❌ Cần {fmt(bet)} xu!", show_alert=True)
        return
    
    user['coins'] -= bet

    game_name = 'diceroll'
    streaks = user.setdefault('minigame_streaks', {})
    game_streak = streaks.setdefault(game_name, {'losses': 0, 'guaranteed_win': False})
    forced_win = game_streak.get('guaranteed_win', False)
    if forced_win:
        game_streak['guaranteed_win'] = False

    game = DiceRollGame(bet=bet)
    
    if forced_win:
        d1 = random.randint(1, 6)
        d2 = 7 - d1
        if d2 < 1 or d2 > 6:
            d1 = random.choice([1, 2, 3])
            d2 = 7 - d1
        game.dice_result = (d1, d2)
        game.win = True
    else:
        d1, d2 = game.roll_dice()

    total = d1 + d2

    _update_minigame_streak(user, game_name, game.win)

    result_text = f"Bạn lắc được: `{d1}` và `{d2}`. Tổng là **{total}**.\n\n" 

    if game.win:
        prize = bet * 2.5
        exp = get_exp_reward(user, bet)
        user['coins'] += prize
        add_exp(user, exp)
        txt = f"🎉 **THẮNG!**\n\n> 💰 **Thưởng:** +{fmt(prize)} xu\n> ⭐ **Kinh nghiệm:** +{fmt(exp)} EXP"
        if forced_win:
            txt = "✨ **Bảo hiểm kích hoạt!** ✨\n" + txt
    else:
        txt = f"😢 **THUA!**\n\n> 💸 **Mất:** {fmt(bet)} xu"
    
    await dm.update_user(uid, user)
    await safe_edit_message(context.bot, q.message.chat_id, q.message.message_id, result_text + txt, InlineKeyboardMarkup([[InlineKeyboardButton("Chơi lại", callback_data='game_diceroll'), InlineKeyboardButton("↩️ Menu", callback_data='back_menu')]]))

async def handle_chanle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.callback_query:
        return
    uid = update.effective_user.id
    user = await dm.get_user(uid)
    bet = get_game_bet(user)
    if user['coins'] < bet:
        await context.bot.answer_callback_query(update.callback_query.id, f"❌ Cần {fmt(bet)} xu!", show_alert=True)
        return

    keyboard = [[ 
        InlineKeyboardButton("Chẵn", callback_data='chanle_play_chan'),
        InlineKeyboardButton("Lẻ", callback_data='chanle_play_le')
    ], [InlineKeyboardButton("↩️ Menu", callback_data='back_menu')]]
    text = f"🎲 **CHẴN LẺ** 🎲\n\nCược: **{fmt(bet)} xu**\nChọn Chẵn hoặc Lẻ:"
    await safe_edit_message(context.bot, update.effective_chat.id, update.callback_query.message.message_id, text, InlineKeyboardMarkup(keyboard))

async def handle_chanle_play(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q or not q.from_user:
        return
    uid = q.from_user.id
    user = await dm.get_user(uid)
    
    user_choice = q.data.split('_')[2]
    bet = get_game_bet(user)

    if user['coins'] < bet:
        await q.answer(f"❌ Cần {fmt(bet)} xu!", show_alert=True)
        return
    user['coins'] -= bet

    game_name = 'chanle'
    streaks = user.setdefault('minigame_streaks', {})
    game_streak = streaks.setdefault(game_name, {'losses': 0, 'guaranteed_win': False})
    
    forced_win = game_streak.get('guaranteed_win', False)
    if forced_win:
        game_streak['guaranteed_win'] = False

    d1, d2 = random.randint(1, 6), random.randint(1, 6)
    total = d1 + d2
    actual_result = 'chan' if total % 2 == 0 else 'le'
    
    won = forced_win or (user_choice == actual_result)
    if forced_win:
        result = user_choice
    else:
        result = actual_result
    
    _update_minigame_streak(user, game_name, won)

    result_text = f"Kết quả: `{d1}` + `{d2}` = **{total}** ({actual_result.upper()})\n\n" 

    if won:
        prize = bet * 2.5
        exp = get_exp_reward(user, bet)
        user['coins'] += prize
        add_exp(user, exp)
        user.setdefault('stats', {}).setdefault('cl_win', 0)
        user['stats']['cl_win'] += 1
        txt = f"🎉 **THẮNG!**\n\n> 💰 **Thưởng:** +{fmt(prize)} xu\n> ⭐ **Kinh nghiệm:** +{fmt(exp)} EXP"
        if forced_win:
            txt = "✨ **Bảo hiểm kích hoạt!** ✨\n" + txt
    else:
        user.setdefault('stats', {}).setdefault('cl_lose', 0)
        user['stats']['cl_lose'] += 1
        txt = f"😢 **THUA!**\n\n> 💸 **Mất:** {fmt(bet)} xu"
        
    await dm.update_user(uid, user)
    await safe_edit_message(context.bot, q.message.chat_id, q.message.message_id, result_text + txt, InlineKeyboardMarkup([[InlineKeyboardButton("Chơi lại", callback_data='game_chanle'), InlineKeyboardButton("↩️ Menu", callback_data='back_menu')]]))

async def handle_lucky_wheel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q or not q.from_user:
        return
    uid = q.from_user.id
    user = await dm.get_user(uid)
    bet = get_game_bet(user)
    if user['coins'] < bet:
        await q.answer(f"❌ Cần {fmt(bet)} xu!", show_alert=True)
        return
    
    user['coins'] -= bet

    outcomes = [(0, 0.20), (0.5, 0.30), (2, 0.20), (3, 0.15), (4, 0.10), (5, 0.05)]
    multipliers, weights = zip(*outcomes)
    chosen_multiplier = random.choices(multipliers, weights=weights, k=1)[0]
    
    prize = int(bet * chosen_multiplier)
    user['coins'] += prize
    
    title = ""
    details = f"Kết quả: **x{chosen_multiplier}**"
    
    if chosen_multiplier > 1:
        title = "🎉 **THẮNG LỚN!**"
        exp = get_exp_reward(user, bet)
        add_exp(user, exp)
        details += f"\n\n> 💰 **Thưởng:** +{fmt(prize - bet)} xu\n> ⭐ **Kinh nghiệm:** +{fmt(exp)} EXP"
    elif chosen_multiplier == 1:
        title = "😌 **HÒA VỐN!**"
        details += f"(Hoàn lại {fmt(bet)} xu)"
    else:
        title = "😢 **THUA!**"
        details += f"\n\n> 💸 **Mất:** {fmt(bet - prize)} xu"

    await dm.update_user(uid, user)
    
    txt = f"🎡 **VÒNG QUAY MAY MẮN** 🎡\n\n{title}\n{details}"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("Chơi lại", callback_data='game_luckywheel'), InlineKeyboardButton("↩️ Menu", callback_data='back_menu')] ])
    await safe_edit_message(context.bot, q.message.chat_id, q.message.message_id, txt, kb)

async def handle_daily_bonus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q or not q.from_user:
        return
    uid = q.from_user.id
    user = await dm.get_user(uid)
    now = datetime.now(VIETNAM_TZ)
    
    streak = user.get('daily_streak', 0)
    last_daily_str = user.get('last_daily')
    
    if last_daily_str:
        last_daily = datetime.fromisoformat(last_daily_str).astimezone(VIETNAM_TZ)
        if now.date() == last_daily.date():
            await q.answer("Bạn đã nhận thưởng hôm nay rồi. Quay lại vào ngày mai!", show_alert=True)
            return
        streak = streak + 1 if (now.date() - last_daily.date()).days == 1 else 1
    else:
        streak = 1

    streak = min(streak, 7)
    base_prize = random.randint(1000, 2000)
    streak_bonus = streak * 500
    prize = base_prize + streak_bonus
    exp = 150 + (streak * 25)

    title = f"🎉 **ĐIỂM DANH NGÀY {streak}**"
    if streak == 7:
        jackpot = random.randint(5000, 10000)
        prize += jackpot
        title += " - JACKPOT!"
        prize_details = f"> 💰 **Thưởng:** +{fmt(prize)} xu (có {fmt(jackpot)} xu thưởng!)"
    else:
        prize_details = f"> 💰 **Thưởng:** +{fmt(prize)} xu"

    result_txt = f"{title}\n\n{prize_details}\n> ⭐ **Kinh nghiệm:** +{fmt(exp)} EXP"
    user['coins'] += prize
    add_exp(user, exp)
        
    user['last_daily'] = now.isoformat()
    user['daily_streak'] = streak
    await dm.update_user(uid, user)
    
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Menu", callback_data='back_menu')] ])
    await safe_edit_message(context.bot, q.message.chat_id, q.message.message_id, result_txt, kb)

async def handle_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.callback_query:
        return
    uid = update.effective_user.id
    user = await dm.get_user(uid)
    rank, next_rank = get_user_rank(user.get('total_exp', 0))
    
    txt = f"""
📊 **THỐNG KÊ CÁ NHÂN**

👤 **{user.get('username', 'Player')}**
- 💰 **Xu:** {fmt(user['coins'])}
- 🏆 **Rank:** {rank['name']}
- ⭐ **Tổng EXP:** {fmt(user.get('total_exp', 0))}
"""
    if next_rank:
        exp_needed = next_rank['exp'] - user.get('total_exp', 0)
        txt += f"📈 **Hạng tiếp:** {next_rank['name']} (còn {fmt(exp_needed)} EXP)"
    
    s = user.get('stats', {})
    txt += f"\n\n**Thành Tích**\n🎲 Chẵn Lẻ: {s.get('cl_win', 0)} thắng - {s.get('cl_lose', 0)} thua"
    
    await safe_edit_message(context.bot, update.effective_chat.id, update.callback_query.message.message_id, txt, InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Menu", callback_data='back_menu')]]))

async def handle_ranking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.callback_query:
        return
    txt = "🏆 **BẢNG XẾP HẠNG** 🏆\n\nChọn loại bảng xếp hạng bạn muốn xem."
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 Top Xu", callback_data='top_coins'), InlineKeyboardButton("⭐ Top Rank", callback_data='top_rank')],
        [InlineKeyboardButton("↩️ Menu", callback_data='back_menu')]
    ])
    await safe_edit_message(context.bot, update.effective_chat.id, update.callback_query.message.message_id, txt, kb)

async def handle_top_coins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.callback_query:
        return
    uid = update.callback_query.from_user.id
    
    async with dm.lock:
        all_users_sorted = sorted(dm.users.values(), key=lambda x: x.get('coins', 0), reverse=True)
    
    top_10_users = all_users_sorted[:10]

    txt = "🏆 **TOP 10 GIÀU CÓ** 🏆\n\n" 
    medals = ["🥇", "🥈", "🥉"] + [f"**{i}.**" for i in range(4, 11)]
    user_in_top_10 = False
    for i, u in enumerate(top_10_users):
        if u.get('user_id') == str(uid):
            user_in_top_10 = True
        txt += f"{medals[i]} {u.get('username', 'User')[:20]} - **{fmt(u.get('coins', 0))} xu**\n"

    if not user_in_top_10:
        try:
            user_rank_index = next(i for i, u in enumerate(all_users_sorted) if u.get('user_id') == str(uid))
            user_data = all_users_sorted[user_rank_index]
            txt += "...\n"
            txt += f"**{user_rank_index + 1}.** {user_data.get('username', 'User')[:20]} - **{fmt(user_data.get('coins', 0))} xu** (Bạn)\n"
        except StopIteration:
            pass

    await safe_edit_message(context.bot, update.effective_chat.id, update.callback_query.message.message_id, txt, InlineKeyboardMarkup([[InlineKeyboardButton("↩️ BXH", callback_data='ranking')]]))

async def handle_top_rank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.callback_query:
        return
    uid = update.callback_query.from_user.id

    async with dm.lock:
        all_users_sorted = sorted(dm.users.values(), key=lambda x: x.get('total_exp', 0), reverse=True)
    
    top_10_users = all_users_sorted[:10]

    txt = "🏆 **TOP 10 CẤP ĐỘ** 🏆\n\n" 
    medals = ["🥇", "🥈", "🥉"] + [f"**{i}.**" for i in range(4, 11)]
    user_in_top_10 = False
    for i, u in enumerate(top_10_users):
        if u.get('user_id') == str(uid):
            user_in_top_10 = True
        rank, _ = get_user_rank(u.get('total_exp', 0))
        txt += f"{medals[i]} {u.get('username', 'User')[:20]} - **{rank['name']}** ({fmt(u.get('total_exp', 0))} EXP)\n"

    if not user_in_top_10:
        try:
            user_rank_index = next(i for i, u in enumerate(all_users_sorted) if u.get('user_id') == str(uid))
            user_data = all_users_sorted[user_rank_index]
            rank, _ = get_user_rank(user_data.get('total_exp', 0))
            txt += "...\n"
            txt += f"**{user_rank_index + 1}.** {user_data.get('username', 'User')[:20]} - **{rank['name']}** ({fmt(user_data.get('total_exp', 0))} EXP) (Bạn)\n"
        except StopIteration:
            pass

    await safe_edit_message(context.bot, update.effective_chat.id, update.callback_query.message.message_id, txt, InlineKeyboardMarkup([[InlineKeyboardButton("↩️ BXH", callback_data='ranking')]]))

async def handle_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.callback_query:
        return
    txt = """
📖 **HƯỚNG DẪN CHƠI GAME** 📖

Chào mừng bạn đến với thế giới mini-game!

**📜 QUY TẮC CHUNG**
- **Cược Mặc Định:** 10% số xu hiện có (tối thiểu 10 xu). Thắng nhận x2.5 tiền cược.
- **Phần Thưởng EXP:** Mỗi ván thắng được 1,000 EXP.
- **Bảo Hiểm Thua:** Thua 3 ván liên tiếp = chắc chắn thắng ván tiếp theo!

**🎲 DANH SÁCH TRÒ CHƠI**

- **🪙 Tung Đồng Xu:** 50/50 Sấp hoặc Ngửa
- **🎰 Máy Xèng:** Quay 3 biểu tượng giống nhau để thắng lớn
- **💎 Kho Báu:** Chọn 1/3 rương chứa kho báu
- **✊ Oẳn Tù Tì:** Kéo, Búa, Bao cổ điển
- **🔢 Đoán Số:** Đoán số từ 1-100
- **🃏 Cao/Thấp:** Đoán lá bài tiếp theo
- **🎲 Chẵn Lẻ / Tài Xỉu:** Dựa vào tổng xúc xắc
- **🎡 Vòng Quay:** Quay nhận thưởng ngẫu nhiên

**🎁 TÍNH NĂNG KHÁC**
- **/menu:** Menu chính
- **/stats:** Thống kê cá nhân
- **/ranking:** Bảng xếp hạng
- **/daily:** Điểm danh hàng ngày
- **/tip:** Chuyển xu cho người khác

Chúc bạn chơi game vui vẻ! 🍀
"""
    await safe_edit_message(context.bot, update.effective_chat.id, update.callback_query.message.message_id, txt, InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Menu", callback_data='back_menu')]]))

async def chat_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.message or not update.message.text:
        return
    uid = update.effective_user.id
    await rate_limiter.acquire(uid)
    await update_username_if_needed(uid, update.effective_user)

    user_message = update.message.text[1:].lstrip()

    if not user_message:
        await update.message.reply_text("Vui lòng nhập nội dung sau dấu ! Ví dụ: !hello")
        return

    try:
        response = await ai_client.chat.completions.create(
            model=AI_MODEL,
            messages=[
                {
                    'role': 'user',
                    'content': user_message
                }
            ]
        )
        bot_response = response.choices[0].message.content
        if bot_response:
            await update.message.reply_text(bot_response)
        else:
            await update.message.reply_text("Tôi không có câu trả lời cho điều đó.")

    except Exception as e:
        logger.error(f"Error calling OpenAI: {e}")
        await update.message.reply_text("Xin lỗi, tôi không thể xử lý yêu cầu của bạn lúc này.")

async def tip_coins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user:
        return

    sender_id = update.effective_user.id
    
    target_user_id = None
    amount = 0
    
    args = context.args
    
    if update.message.reply_to_message:
        target_user_id = update.message.reply_to_message.from_user.id
        if not args:
            await update.message.reply_text("Usage: /tip <số tiền> khi reply tin nhắn.")
            return
        try:
            amount = int(args[0])
        except (ValueError, IndexError):
            await update.message.reply_text("Số tiền không hợp lệ.")
            return
    else:
        if len(args) < 2:
            await update.message.reply_text("Usage: /tip <user_id/@username> <số tiền>")
            return
        
        target_identifier = args[0]
        try:
            amount = int(args[1])
        except ValueError:
            await update.message.reply_text("Số tiền không hợp lệ.")
            return

        if target_identifier.startswith('@'):
            target_username = target_identifier
            found = False
            async with dm.lock:
                for uid, udata in dm.users.items():
                    if udata.get('username') == target_username:
                        target_user_id = int(uid)
                        found = True
                        break
            if not found:
                await update.message.reply_text(f"Không tìm thấy người dùng {target_username}.")
                return
        else:
            try:
                target_user_id = int(target_identifier)
            except ValueError:
                await update.message.reply_text("User ID hoặc username không hợp lệ.")
                return

    if amount <= 0:
        await update.message.reply_text("Số tiền phải lớn hơn 0.")
        return

    if sender_id == target_user_id:
        await update.message.reply_text("Bạn không thể tip cho chính mình.")
        return

    sender_user = await dm.get_user(sender_id)

    if sender_user['coins'] < amount:
        await update.message.reply_text(f"Bạn không đủ xu. Bạn chỉ có {fmt(sender_user['coins'])} xu.")
        return

    target_user = await dm.get_user(target_user_id)
    
    sender_user['coins'] -= amount
    target_user['coins'] += amount
    
    await dm.update_user(sender_id, sender_user)
    await dm.update_user(target_user_id, target_user)

    sender_username = sender_user.get('username', f'User {sender_id}')
    target_username = target_user.get('username', f'User {target_user_id}')
    await update.message.reply_text(f"{sender_username} đã tip {target_username} {fmt(amount)} xu!")

async def give_coins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != BOT_OWNER_ID:
        await update.message.reply_text("Bạn không có quyền sử dụng lệnh này.")
        return

    args = context.args
    target_user_id = None
    amount = 0

    try:
        if update.message.reply_to_message:
            target_user_id = update.message.reply_to_message.from_user.id
            if not args:
                await update.message.reply_text("Usage: /give <số tiền> khi reply.")
                return
            amount = int(args[0])
        else:
            if not args:
                await update.message.reply_text("Usage: /give <user_id> <số tiền> HOẶC /give <số tiền> (cho chính mình).")
                return
            
            if len(args) == 1:
                amount = int(args[0])
                target_user_id = update.effective_user.id
            else:
                target_user_id = int(args[0])
                amount = int(args[1])

    except (ValueError, IndexError):
        await update.message.reply_text("Format lệnh không hợp lệ.")
        return

    if amount <= 0:
        await update.message.reply_text("Số tiền phải lớn hơn 0.")
        return

    if not target_user_id:
        await update.message.reply_text("Không thể xác định người nhận.")
        return

    target_user = await dm.get_user(target_user_id)
    target_user['coins'] += amount
    await dm.update_user(target_user_id, target_user)

    target_username = target_user.get('username', f'User {target_user_id}')
    await update.message.reply_text(f"Đã cấp {fmt(amount)} xu cho {target_username}.")

async def kick_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.message.chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("Lệnh này chỉ dùng trong nhóm.")
        return

    chat_id = update.message.chat_id
    user_id = update.effective_user.id

    admins = await context.bot.get_chat_administrators(chat_id)
    admin_ids = {admin.user.id for admin in admins}

    if user_id not in admin_ids:
        await update.message.reply_text("Bạn không phải admin.")
        return

    try:
        target_user_id_str = context.args[0]
        target_user_id = int(target_user_id_str)
    except (ValueError, IndexError):
        await update.message.reply_text("Usage: /kick <user_id>")
        return

    try:
                await context.bot.kick_chat_member(chat_id, target_user_id)
        await update.message.reply_text(f"Đã kick người dùng {target_user_id}.")
    except Exception as e:
        logger.error(f"Không thể kick user {target_user_id}: {e}")
        await update.message.reply_text(f"Không thể kick người dùng {target_user_id}.")

async def ban_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.message.chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("Lệnh này chỉ dùng trong nhóm.")
        return

    chat_id = update.message.chat_id
    user_id = update.effective_user.id

    admins = await context.bot.get_chat_administrators(chat_id)
    admin_ids = {admin.user.id for admin in admins}

    if user_id not in admin_ids:
        await update.message.reply_text("Bạn không phải admin.")
        return

    try:
        target_user_id_str = context.args[0]
        target_user_id = int(target_user_id_str)
    except (ValueError, IndexError):
        await update.message.reply_text("Usage: /ban <user_id>")
        return

    try:
        await context.bot.restrict_chat_member(chat_id, target_user_id, permissions={'can_send_messages': False})
        await update.message.reply_text(f"Đã cấm người dùng {target_user_id} gửi tin nhắn.")
    except Exception as e:
        logger.error(f"Không thể ban user {target_user_id}: {e}")
        await update.message.reply_text(f"Không thể ban người dùng {target_user_id}.")

async def unban_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.message.chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("Lệnh này chỉ dùng trong nhóm.")
        return

    chat_id = update.message.chat_id
    user_id = update.effective_user.id

    admins = await context.bot.get_chat_administrators(chat_id)
    admin_ids = {admin.user.id for admin in admins}

    if user_id not in admin_ids:
        await update.message.reply_text("Bạn không phải admin.")
        return

    try:
        target_user_id_str = context.args[0]
        target_user_id = int(target_user_id_str)
    except (ValueError, IndexError):
        await update.message.reply_text("Usage: /unban <user_id>")
        return

    try:
        await context.bot.unban_chat_member(chat_id, target_user_id)
        await update.message.reply_text(f"Đã bỏ cấm người dùng {target_user_id}.")
    except Exception as e:
        logger.error(f"Không thể unban user {target_user_id}: {e}")
        await update.message.reply_text(f"Không thể unban người dùng {target_user_id}.")

def parse_duration(duration_str: str) -> Optional[int]:
    if not duration_str:
        return None
    duration_str = duration_str.lower()
    if duration_str.endswith('m'):
        return int(duration_str[:-1]) * 60
    if duration_str.endswith('h'):
        return int(duration_str[:-1]) * 3600
    if duration_str.endswith('d'):
        return int(duration_str[:-1]) * 86400
    return None

async def mute_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.message.chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("Lệnh này chỉ dùng trong nhóm.")
        return

    chat_id = update.message.chat_id
    user_id = update.effective_user.id

    admins = await context.bot.get_chat_administrators(chat_id)
    admin_ids = {admin.user.id for admin in admins}

    if user_id not in admin_ids:
        await update.message.reply_text("Bạn không phải admin.")
        return

    try:
        target_user_id_str = context.args[0]
        target_user_id = int(target_user_id_str)
        duration_str = context.args[1] if len(context.args) > 1 else None
        mute_duration = parse_duration(duration_str)
    except (ValueError, IndexError):
        await update.message.reply_text("Usage: /mute <user_id> [thời gian(m,h,d)]")
        return

    try:
        if mute_duration:
            await context.bot.restrict_chat_member(chat_id, target_user_id, permissions={'can_send_messages': False}, until_date=datetime.now() + timedelta(seconds=mute_duration))
            await update.message.reply_text(f"Đã tắt tiếng người dùng {target_user_id} trong {duration_str}.")
        else:
            await context.bot.restrict_chat_member(chat_id, target_user_id, permissions={'can_send_messages': False})
            await update.message.reply_text(f"Đã tắt tiếng người dùng {target_user_id} vĩnh viễn.")
    except Exception as e:
        logger.error(f"Không thể mute user {target_user_id}: {e}")
        await update.message.reply_text(f"Không thể mute người dùng {target_user_id}.")

async def unmute_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.message.chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("Lệnh này chỉ dùng trong nhóm.")
        return

    chat_id = update.message.chat_id
    user_id = update.effective_user.id

    admins = await context.bot.get_chat_administrators(chat_id)
    admin_ids = {admin.user.id for admin in admins}

    if user_id not in admin_ids:
        await update.message.reply_text("Bạn không phải admin.")
        return

    try:
        target_user_id_str = context.args[0]
        target_user_id = int(target_user_id_str)
    except (ValueError, IndexError):
        await update.message.reply_text("Usage: /unmute <user_id>")
        return

    try:
        await context.bot.restrict_chat_member(chat_id, target_user_id, permissions={
            'can_send_messages': True, 
            'can_send_media_messages': True, 
            'can_send_polls': True, 
            'can_send_other_messages': True, 
            'can_add_web_page_previews': True, 
            'can_change_info': True, 
            'can_invite_users': True, 
            'can_pin_messages': True
        })
        await update.message.reply_text(f"Đã bỏ tắt tiếng người dùng {target_user_id}.")
    except Exception as e:
        logger.error(f"Không thể unmute user {target_user_id}: {e}")
        await update.message.reply_text(f"Không thể unmute người dùng {target_user_id}.")

async def pin_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.message.chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("Lệnh này chỉ dùng trong nhóm.")
        return

    chat_id = update.message.chat_id
    user_id = update.effective_user.id

    admins = await context.bot.get_chat_administrators(chat_id)
    admin_ids = {admin.user.id for admin in admins}

    if user_id not in admin_ids:
        await update.message.reply_text("Bạn không phải admin.")
        return

    if not update.message.reply_to_message:
        await update.message.reply_text("Reply vào tin nhắn cần ghim.")
        return

    try:
        await context.bot.pin_chat_message(chat_id, update.message.reply_to_message.message_id)
        await update.message.reply_text("Đã ghim tin nhắn.")
    except Exception as e:
        logger.error(f"Không thể ghim tin nhắn: {e}")
        await update.message.reply_text("Không thể ghim tin nhắn.")

async def unpin_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.message.chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("Lệnh này chỉ dùng trong nhóm.")
        return

    chat_id = update.message.chat_id
    user_id = update.effective_user.id

    admins = await context.bot.get_chat_administrators(chat_id)
    admin_ids = {admin.user.id for admin in admins}

    if user_id not in admin_ids:
        await update.message.reply_text("Bạn không phải admin.")
        return

    try:
        await context.bot.unpin_chat_message(chat_id)
        await update.message.reply_text("Đã bỏ ghim tin nhắn.")
    except Exception as e:
        logger.error(f"Không thể bỏ ghim tin nhắn: {e}")
        await update.message.reply_text("Không thể bỏ ghim tin nhắn.")

async def post_init(application: Application) -> None:
    await dm.initialize()
    logger.info("🤖 Bot khởi động thành công!")

async def post_shutdown(application: Application) -> None:
    await dm.shutdown()
    logger.info("Bot đã tắt.")

def main() -> None:
    if not BOT_TOKEN:
        logger.critical("BOT_TOKEN chưa được cấu hình.")
        return

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'^!.*'), chat_handler))
    app.add_handler(CommandHandler("tip", tip_coins))
    app.add_handler(CommandHandler("give", give_coins))
    app.add_handler(CommandHandler("kick", kick_member))
    app.add_handler(CommandHandler("ban", ban_member))
    app.add_handler(CommandHandler("unban", unban_member))
    app.add_handler(CommandHandler("mute", mute_member))
    app.add_handler(CommandHandler("unmute", unmute_member))
    app.add_handler(CommandHandler("pin", pin_message))
    app.add_handler(CommandHandler("unpin", unpin_message))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, guess_game))

    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    try:
        main()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot dừng bởi người dùng.")
