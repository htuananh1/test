import logging
import random
import json
import asyncio
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
import threading
import time
from github import Github
import base64
import os
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor
import psutil
import gc
import pytz
import queue
import traceback
import re

load_dotenv()
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

BOT_TOKEN = os.getenv('BOT_TOKEN')
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')  
GITHUB_REPO = os.getenv('GITHUB_REPO', 'htuananh1/Data-manager')
GITHUB_FILE_PATH = "bot_data.json"
GITHUB_CONFIG_PATH = "game_config.json"
LOCAL_BACKUP_FILE = "local_backup.json"
LOCAL_CONFIG_FILE = "local_config.json"
VIETNAM_TZ = pytz.timezone('Asia/Ho_Chi_Minh')

MAX_CONCURRENT_AUTO = 25
AUTO_UPDATE_INTERVAL = 60
COUNTDOWN_INTERVAL = 15
SAVE_INTERVAL = 30
CONFIG_UPDATE_INTERVAL = 600
MIN_UPDATE_INTERVAL = 1.5
GLOBAL_RATE_LIMIT = 20

class RateLimiter:
    """Rate limiter để tránh flood"""
    def __init__(self):
        self.user_last_action = {}
        self.global_semaphore = asyncio.Semaphore(GLOBAL_RATE_LIMIT)
        self.lock = threading.Lock()
        
    async def acquire(self, user_id):
        """Đợi cho đến khi có thể thực hiện action"""
        async with self.global_semaphore:
            with self.lock:
                last_time = self.user_last_action.get(user_id, 0)
                current_time = time.time()
                wait_time = MIN_UPDATE_INTERVAL - (current_time - last_time)
                
                if wait_time > 0:
                    await asyncio.sleep(wait_time)
                
                self.user_last_action[user_id] = time.time()
                return True
    
    def check_can_update(self, user_id):
        """Kiểm tra xem có thể update ngay không"""
        with self.lock:
            last_time = self.user_last_action.get(user_id, 0)
            return time.time() - last_time >= MIN_UPDATE_INTERVAL

rate_limiter = RateLimiter()

class ConfigManager:
    def __init__(self):
        self.config = None
        self.last_update = 0
        self.github = Github(GITHUB_TOKEN)
        self.repo = self.github.get_repo(GITHUB_REPO)
        self.lock = threading.Lock()
        
    def load_config(self):
        with self.lock:
            try:
                if self.config and (time.time() - self.last_update < CONFIG_UPDATE_INTERVAL):
                    return self.config
                
                try:
                    file_content = self.repo.get_contents(GITHUB_CONFIG_PATH)
                    config_str = base64.b64decode(file_content.content).decode()
                    self.config = json.loads(config_str)
                    
                    with open(LOCAL_CONFIG_FILE, 'w', encoding='utf-8') as f:
                        json.dump(self.config, f, ensure_ascii=False, indent=2)
                    
                    self.last_update = time.time()
                    logging.info("✅ Config loaded from GitHub")
                    return self.config
                    
                except Exception as e:
                    logging.warning(f"⚠️ Cannot load from GitHub: {e}")
                    try:
                        with open(LOCAL_CONFIG_FILE, 'r', encoding='utf-8') as f:
                            self.config = json.load(f)
                        logging.info("✅ Using local config")
                        return self.config
                    except:
                        logging.error("❌ No config found, please create game_config.json on GitHub")
                        return None
                        
            except Exception as e:
                logging.error(f"❌ Config error: {e}")
                return None
    
    def reload_config(self):
        with self.lock:
            self.last_update = 0
            return self.load_config()
    
    def get_fish_ranks(self):
        config = self.load_config()
        if not config:
            return {}
        ranks = {}
        for rank in config.get("FISH_RANKS", []):
            ranks[rank["id"]] = rank
        return ranks
    
    def get_fish_types(self):
        config = self.load_config()
        if not config:
            return {}
        fish = {}
        for f in config.get("FISH_TYPES", []):
            fish[f["name"]] = f
        return fish
    
    def get_fishing_rods(self):
        config = self.load_config()
        if not config:
            return {}
        rods = {}
        for rod in config.get("FISHING_RODS", []):
            rods[rod["id"]] = rod
        return rods

config_manager = ConfigManager()

class AutoFishingManager:
    def __init__(self):
        self.active_sessions = {}
        self.session_stats = {}
        self.message_info = {}
        self.lock = threading.Lock()
        self.semaphore = asyncio.Semaphore(MAX_CONCURRENT_AUTO)
        self.flood_control = {}  # Track flood control per user
        
    def add_session(self, uid, mid, cid):
        with self.lock:
            self.active_sessions[uid] = {
                "active": True,
                "start_time": time.time(),
                "last_update": 0
            }
            self.message_info[uid] = {
                "mid": mid,
                "cid": cid,
                "last_update": time.time()
            }
            self.session_stats[uid] = {
                "count": 0,
                "coins": 0,
                "exp": 0,
                "rarity_count": {r: 0 for r in ["C","U","R","E","L","M","S","X","Z"]},
                "best_catch": None,
                "best_value": 0
            }
            self.flood_control[uid] = {
                "retry_count": 0,
                "last_error": 0
            }
    
    def stop_session(self, uid):
        with self.lock:
            if uid in self.active_sessions:
                self.active_sessions[uid]["active"] = False
    
    def is_active(self, uid):
        with self.lock:
            return uid in self.active_sessions and self.active_sessions[uid]["active"]
    
    def get_message_info(self, uid):
        with self.lock:
            return self.message_info.get(uid, {}).copy()
    
    def update_message_info(self, uid, mid, cid):
        with self.lock:
            self.message_info[uid] = {
                "mid": mid,
                "cid": cid,
                "last_update": time.time()
            }
    
    def update_stats(self, uid, result):
        with self.lock:
            if uid in self.session_stats:
                stats = self.session_stats[uid]
                stats["count"] += 1
                
                if result and result.get("success"):
                    stats["coins"] += result["reward"] - 10
                    stats["exp"] += result["exp"]
                    stats["rarity_count"][result["rarity"]] += 1
                    
                    if result["reward"] > stats["best_value"]:
                        stats["best_catch"] = result["fish"]
                        stats["best_value"] = result["reward"]
                else:
                    stats["coins"] -= 10
    
    def get_stats(self, uid):
        with self.lock:
            return self.session_stats.get(uid, {}).copy()
    
    def get_session_info(self, uid):
        with self.lock:
            return self.active_sessions.get(uid, {}).copy()
    
    def should_update(self, uid):
        """Kiểm tra xem có nên update message không"""
        with self.lock:
            if uid not in self.active_sessions:
                return False
            session = self.active_sessions[uid]
            current_time = time.time()
            time_since_update = current_time - session.get("last_update", 0)
            
            # Update nếu đã qua đủ thời gian và không có flood control
            if time_since_update >= AUTO_UPDATE_INTERVAL:
                session["last_update"] = current_time
                return True
            return False
    
    def cleanup_session(self, uid):
        with self.lock:
            if uid in self.active_sessions:
                del self.active_sessions[uid]
            if uid in self.session_stats:
                del self.session_stats[uid]
            if uid in self.message_info:
                del self.message_info[uid]
            if uid in self.flood_control:
                del self.flood_control[uid]

auto_manager = AutoFishingManager()

def get_level_exp(level):
    return 1000 if level <= 10 else int(1000 * (1.5 ** ((level - 10) // 10)))

def get_next_sunday():
    now = datetime.now(VIETNAM_TZ)
    days = (6 - now.weekday()) % 7
    if days == 0 and now.hour >= 0:
        days = 7
    return (now + timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)

def should_reset():
    now = datetime.now(VIETNAM_TZ)
    return now.weekday() == 6 and now.hour == 0 and now.minute < 1

def get_user_rank(exp):
    FISH_RANKS = config_manager.get_fish_ranks()
    if not FISH_RANKS:
        return {"name": "🎣 Tân Thủ", "exp_required": 0, "coin_bonus": 1.0, "fish_bonus": 1.0, "luck_bonus": 1.0}, 1, None, 0
    
    rank = list(FISH_RANKS.values())[0]
    level = 1
    
    for rid, r in FISH_RANKS.items():
        if exp >= r["exp_required"]:
            rank = r
            level = int(rid)
        else:
            break
    
    next_r = FISH_RANKS.get(str(level + 1)) if level < len(FISH_RANKS) else None
    exp_next = next_r["exp_required"] - exp if next_r else 0
    return rank, level, next_r, exp_next

def fmt(num):
    if num >= 1e12: return f"{num/1e12:.1f}T".replace('.0T', 'T')
    elif num >= 1e9: return f"{num/1e9:.1f}B".replace('.0B', 'B')
    elif num >= 1e6: return f"{num/1e6:.1f}M".replace('.0M', 'M')
    elif num >= 1e3: return f"{num/1e3:.1f}K".replace('.0K', 'K')
    else: return str(int(num))

def get_color(r):
    return {"C":"⚪","U":"🟢","R":"🔵","E":"🟣","L":"🟡","M":"🔴","S":"⚫","X":"💠","Z":"✨"}.get(r,"⚪")

def extract_flood_wait(error_str):
    """Extract số giây cần đợi từ flood error"""
    try:
        match = re.search(r'retry after (\d+)', str(error_str).lower())
        if match:
            return int(match.group(1)) + 1
        return 5
    except:
        return 5

def truncate_text(text, max_length=4096):
    """Cắt text để không vượt quá giới hạn"""
    if len(text) <= max_length:
        return text
    return text[:max_length-3] + "..."

class Cache:
    def __init__(self):
        self.data = {}
        self.timeout = 30
        self.lock = threading.Lock()
        
    def get(self, k):
        with self.lock:
            if k in self.data:
                d, t = self.data[k]
                if time.time() - t < self.timeout:
                    return d
                else:
                    del self.data[k]
            return None
            
    def set(self, k, v):
        with self.lock:
            self.data[k] = (v, time.time())
            
    def clear(self):
        with self.lock:
            self.data = {}

cache = Cache()

class Storage:
    @staticmethod
    def save(data):
        try:
            with open(LOCAL_BACKUP_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except:
            pass
            
    @staticmethod
    def load():
        try:
            with open(LOCAL_BACKUP_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}

class Monitor:
    @staticmethod
    def stats():
        try:
            cpu = psutil.cpu_percent(interval=0.1)
            mem = psutil.virtual_memory()
            return {"cpu": cpu, "ram": mem.percent}
        except:
            return {"cpu": 0, "ram": 0}
            
    @staticmethod
    def check():
        try:
            s = Monitor.stats()
            if s["cpu"] > 90 or s["ram"] > 90:
                gc.collect()
                time.sleep(0.1)
                return False
            return True
        except:
            return True

class DataManager:
    def __init__(self):
        self.github = Github(GITHUB_TOKEN)
        self.repo = self.github.get_repo(GITHUB_REPO)
        self.queue = []
        self.lock = threading.Lock()
        self.executor = ThreadPoolExecutor(max_workers=4)
        self.last_save = time.time()
        threading.Thread(target=self.auto_save, daemon=True).start()
        threading.Thread(target=self.reset_check, daemon=True).start()
    
    def reset_check(self):
        while True:
            try:
                if should_reset():
                    self.reset_coins()
                    time.sleep(60)
                time.sleep(30)
            except:
                time.sleep(60)
    
    def reset_coins(self):
        try:
            users = {}
            try:
                file = self.repo.get_contents(GITHUB_FILE_PATH)
                for line in base64.b64decode(file.content).decode().strip().split('\n'):
                    if line.strip():
                        try:
                            d = json.loads(line)
                            if 'user_id' in d:
                                d['coins'] = 100
                                d['last_reset'] = datetime.now(VIETNAM_TZ).isoformat()
                                users[d['user_id']] = d
                        except:
                            pass
            except:
                pass
            
            if users:
                content = '\n'.join([json.dumps(d, ensure_ascii=False) for d in users.values()])
                try:
                    file = self.repo.get_contents(GITHUB_FILE_PATH)
                    self.repo.update_file(GITHUB_FILE_PATH, f"Reset {datetime.now().strftime('%Y%m%d')}", content, file.sha)
                except:
                    self.repo.create_file(GITHUB_FILE_PATH, f"Reset {datetime.now().strftime('%Y%m%d')}", content)
            cache.clear()
        except:
            pass
    
    def load_user(self, uid):
        uid = str(uid)
        cached = cache.get(f"u_{uid}")
        if cached:
            return cached
            
        try:
            file = self.repo.get_contents(GITHUB_FILE_PATH)
            for line in base64.b64decode(file.content).decode().strip().split('\n'):
                if line.strip():
                    try:
                        d = json.loads(line)
                        if d.get('user_id') == uid:
                            d.setdefault('owned_rods', ["1"])
                            d.setdefault('inventory', {"rod": "1", "fish": {}})
                            d.setdefault('total_exp', d.get('exp', 0))
                            d.setdefault('chanle_win', 0)
                            d.setdefault('chanle_lose', 0)
                            d.setdefault('level_exp', 0)
                            cache.set(f"u_{uid}", d)
                            return d
                    except:
                        pass
        except:
            local = Storage.load()
            if uid in local:
                return local[uid]
        return self.new_user(uid)
    
    def new_user(self, uid):
        return {
            "user_id": str(uid), 
            "username": "", 
            "coins": 100, 
            "exp": 0, 
            "total_exp": 0, 
            "level": 1,
            "level_exp": 0, 
            "fishing_count": 0, 
            "win_count": 0, 
            "lose_count": 0, 
            "chanle_win": 0, 
            "chanle_lose": 0, 
            "owned_rods": ["1"], 
            "inventory": {"rod": "1", "fish": {}}, 
            "created_at": datetime.now().isoformat()
        }
    
    def save_user(self, data):
        with self.lock:
            cache.set(f"u_{data['user_id']}", data)
            self.queue.append(data)
            
            if len(self.queue) >= 10 or (time.time() - self.last_save > SAVE_INTERVAL):
                self.executor.submit(self.batch_save)
    
    def batch_save(self):
        with self.lock:
            if not self.queue:
                return
            to_save = self.queue.copy()
            self.queue.clear()
            self.last_save = time.time()
            
        try:
            users = {}
            try:
                file = self.repo.get_contents(GITHUB_FILE_PATH)
                for line in base64.b64decode(file.content).decode().strip().split('\n'):
                    if line.strip():
                        try:
                            d = json.loads(line)
                            if 'user_id' in d:
                                users[d['user_id']] = d
                        except:
                            pass
            except:
                pass
            
            for d in to_save:
                users[d['user_id']] = d
                
            Storage.save(users)
            content = '\n'.join([json.dumps(d, ensure_ascii=False) for d in users.values()])
            
            try:
                file = self.repo.get_contents(GITHUB_FILE_PATH)
                self.repo.update_file(GITHUB_FILE_PATH, f"U{datetime.now().strftime('%H%M')}", content, file.sha)
            except:
                self.repo.create_file(GITHUB_FILE_PATH, f"C{datetime.now().strftime('%H%M')}", content)
        except:
            pass
    
    def auto_save(self):
        while True:
            try:
                time.sleep(SAVE_INTERVAL)
                if self.queue and Monitor.check():
                    self.batch_save()
            except:
                time.sleep(60)
    
    def get_user(self, uid):
        user = self.load_user(uid)
        user.setdefault('inventory', {"rod": "1", "fish": {}})
        FISHING_RODS = config_manager.get_fishing_rods()
        if FISHING_RODS and user['inventory'].get('rod') not in FISHING_RODS:
            user['inventory']['rod'] = "1"
        user.setdefault('total_exp', user.get('exp', 0))
        user.setdefault('chanle_win', 0)
        user.setdefault('chanle_lose', 0)
        user.setdefault('level_exp', 0)
        return user
    
    def update_user(self, uid, data):
        data['user_id'] = str(uid)
        self.save_user(data)
    
    def best_rod(self, owned):
        FISHING_RODS = config_manager.get_fishing_rods()
        if not FISHING_RODS:
            return "1"
        best = "1"
        best_val = 0
        for rid in owned:
            if rid in FISHING_RODS:
                val = FISHING_RODS[rid].get('coin_multiplier', 1.0)
                if val > best_val:
                    best_val = val
                    best = rid
        return best

dm = DataManager()

def get_rod_name(user):
    FISHING_RODS = config_manager.get_fishing_rods()
    if not FISHING_RODS:
        return "🎣 Cơ bản"
    rid = user.get('inventory', {}).get('rod', '1')
    return FISHING_RODS.get(rid, {"name": "🎣 Cơ bản"})['name']

async def safe_edit_message(bot, chat_id, message_id, text, reply_markup=None, max_retries=3):
    """Edit message với xử lý lỗi tốt"""
    text = truncate_text(text)
    
    for attempt in range(max_retries):
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            return True
        except Exception as e:
            error_str = str(e).lower()
            
            if "message is not modified" in error_str:
                return True
            
            if "flood" in error_str:
                wait_time = extract_flood_wait(error_str)
                logging.warning(f"Flood control, waiting {wait_time}s")
                await asyncio.sleep(wait_time)
                continue
            
            if "message to edit not found" in error_str:
                return False
            
            if attempt < max_retries - 1:
                await asyncio.sleep(1.5 * (attempt + 1))
            else:
                logging.error(f"Failed to edit message after {max_retries} attempts: {e}")
                return False
    
    return False

async def safe_send_message(bot, chat_id, text, reply_markup=None, max_retries=3):
    """Send message với xử lý lỗi"""
    text = truncate_text(text)
    
    for attempt in range(max_retries):
        try:
            msg = await bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            return msg
        except Exception as e:
            error_str = str(e).lower()
            
            if "flood" in error_str:
                wait_time = extract_flood_wait(error_str)
                logging.warning(f"Flood control on send, waiting {wait_time}s")
                await asyncio.sleep(wait_time)
                continue
            
            if attempt < max_retries - 1:
                await asyncio.sleep(1.5 * (attempt + 1))
            else:
                logging.error(f"Failed to send message: {e}")
                return None
    
    return None

async def chanle(uid, choice, bet=1000):
    user = dm.get_user(uid)
    if user["coins"] < bet:
        return None, f"❌ Cần {fmt(bet)} xu!"
    user["coins"] -= bet
    dice = random.randint(1, 6)
    win = (choice == "even" and dice % 2 == 0) or (choice == "odd" and dice % 2 != 0)
    
    if win:
        prize = int(bet * 2.5)
        user["coins"] += prize
        user["chanle_win"] = user.get("chanle_win", 0) + 1
        dm.update_user(uid, user)
        return {"success": True, "dice": dice, "win": prize, "coins": user["coins"]}, None
    else:
        user["chanle_lose"] = user.get("chanle_lose", 0) + 1
        dm.update_user(uid, user)
        return {"success": False, "dice": dice, "coins": user["coins"]}, None

async def fish(uid, auto=False):
    user = dm.get_user(uid)
    if user["coins"] < 10:
        return None, "❌ Cần 10 xu!"
    user["coins"] -= 10
    
    FISHING_RODS = config_manager.get_fishing_rods()
    FISH_TYPES = config_manager.get_fish_types()
    
    if not FISHING_RODS or not FISH_TYPES:
        user["coins"] += 10
        dm.update_user(uid, user)
        return None, "❌ Config chưa được load!"
    
    rod = FISHING_RODS.get(user.get('inventory', {}).get('rod', '1'), list(FISHING_RODS.values())[0])
    rank, _, _, _ = get_user_rank(user.get('total_exp', 0))
    
    luck = 1.0
    if not auto:
        r = random.random()
        if r < 0.01: luck = 5.0
        elif r < 0.03: luck = 3.0
        elif r < 0.08: luck = 2.0
        elif r < 0.2: luck = 1.5
    else:
        if random.random() < 0.005: luck = 2.0
        elif random.random() < 0.02: luck = 1.5
    
    luck *= rank.get('luck_bonus', 1.0)
    
    rand = random.uniform(0, 100)
    total = 0
    caught = None
    
    items = list(FISH_TYPES.items())
    random.shuffle(items)
    
    for name, data in items:
        chance = data["chance"] * rod.get('bonus', 1.0) * rank.get('fish_bonus', 1.0) * luck
        
        if auto:
            if data['rarity'] in ['L', 'M', 'S', 'X', 'Z']:
                chance *= 0.2
            elif data['rarity'] == 'E':
                chance *= 0.5
            elif data['rarity'] == 'R':
                chance *= 0.7
        
        total += chance
        if rand <= total:
            caught = name
            reward = int(data["value"] * rank.get('coin_bonus', 1.0) * rod.get('coin_multiplier', 1.0))
            exp = int(data["exp"] * rod.get('exp_bonus', 1.0))
            break
    
    if caught:
        user['inventory'].setdefault('fish', {})
        user['inventory']['fish'][caught] = user['inventory']['fish'].get(caught, 0) + 1
        user["coins"] += reward
        user["exp"] += exp
        user["total_exp"] = user.get('total_exp', 0) + exp
        user["level_exp"] = user.get('level_exp', 0) + exp
        
        exp_req = get_level_exp(user["level"])
        leveled = False
        while user["level_exp"] >= exp_req:
            user["level_exp"] -= exp_req
            user["level"] += 1
            exp_req = get_level_exp(user["level"])
            leveled = True
        
        user["fishing_count"] += 1
        user["win_count"] += 1
        dm.update_user(uid, user)
        
        return {
            "success": True, 
            "fish": caught, 
            "rarity": FISH_TYPES[caught]['rarity'],
            "reward": reward, 
            "exp": exp, 
            "leveled": leveled, 
            "level": user["level"],
            "coins": user["coins"], 
            "luck": luck
        }, None
    else:
        user["fishing_count"] += 1
        user["lose_count"] += 1
        dm.update_user(uid, user)
        return {"success": False, "coins": user["coins"]}, None

async def auto_fish_optimized(uid, mid, cid, bot):
    """Auto fishing với rate limiting và error handling tốt"""
    async with auto_manager.semaphore:
        auto_manager.add_session(uid, mid, cid)
        
        last_full_update = 0
        error_count = 0
        consecutive_errors = 0
        update_failures = 0
        
        try:
            # Initial message
            await rate_limiter.acquire(uid)
            initial_msg = await safe_edit_message(
                bot, cid, mid,
                "🤖 **KHỞI ĐỘNG AUTO...**\n\n⏳ Đang chuẩn bị..."
            )
            
            if not initial_msg:
                logging.error(f"Failed to start auto for {uid}")
                return
            
            while auto_manager.is_active(uid):
                # Check system resources
                if not Monitor.check():
                    await asyncio.sleep(2)
                    continue
                
                # Fishing với delay ngẫu nhiên
                await asyncio.sleep(random.uniform(0.5, 1.5))
                
                res, err = await fish(uid, auto=True)
                
                if err:
                    error_count += 1
                    consecutive_errors += 1
                    
                    if error_count >= 5 or consecutive_errors >= 3:
                        await rate_limiter.acquire(uid)
                        await safe_edit_message(
                            bot, cid, mid,
                            f"⛔ **AUTO DỪNG**\n\n{err}\n\nLỗi liên tục!"
                        )
                        break
                    
                    await asyncio.sleep(3)
                    continue
                
                # Reset consecutive errors on success
                consecutive_errors = 0
                auto_manager.update_stats(uid, res)
                
                # Check if should update message
                current_time = time.time()
                time_since_update = current_time - last_full_update
                
                if time_since_update >= AUTO_UPDATE_INTERVAL and auto_manager.should_update(uid):
                    # Rate limit the update
                    if rate_limiter.check_can_update(uid):
                        await rate_limiter.acquire(uid)
                        
                        user = dm.get_user(uid)
                        stats = auto_manager.get_stats(uid)
                        session_info = auto_manager.get_session_info(uid)
                        
                        if not session_info:
                            break
                        
                        runtime = int(current_time - session_info.get('start_time', current_time))
                        rank, _, _, _ = get_user_rank(user.get('total_exp', 0))
                        
                        # Create compact message
                        txt = f"🤖 **AUTO**\n"
                        txt += f"📊 {stats['count']} câu | ⏱️ {runtime}s\n"
                        txt += f"💰 +{fmt(stats['coins'])} | ⭐ +{stats['exp']}\n"
                        txt += f"💰 Xu: {fmt(user['coins'])}\n"
                        
                        # Rarity summary
                        rarity_line = ""
                        for r in ["Z", "X", "S", "M", "L", "E", "R", "U", "C"]:
                            if stats['rarity_count'][r] > 0:
                                rarity_line += f"{get_color(r)}{stats['rarity_count'][r]} "
                        
                        if rarity_line:
                            txt += f"\n{rarity_line}\n"
                        
                        if stats['best_catch']:
                            txt += f"\n🎯 Best: {stats['best_catch'][:20]}\n"
                        
                        txt += f"\n🔄 Update: {AUTO_UPDATE_INTERVAL}s"
                        
                        kb = [
                            [InlineKeyboardButton("🛑 DỪNG", callback_data='stop_auto')],
                            [InlineKeyboardButton("↩️ Menu", callback_data='back_menu_auto')]
                        ]
                        
                        success = await safe_edit_message(
                            bot, cid, mid, txt,
                            reply_markup=InlineKeyboardMarkup(kb)
                        )
                        
                        if success:
                            last_full_update = current_time
                            update_failures = 0
                        else:
                            update_failures += 1
                            
                            # Try sending new message if too many failures
                            if update_failures >= 3:
                                new_msg = await safe_send_message(
                                    bot, cid, txt,
                                    reply_markup=InlineKeyboardMarkup(kb)
                                )
                                if new_msg:
                                    auto_manager.update_message_info(uid, new_msg.message_id, cid)
                                    mid = new_msg.message_id
                                    update_failures = 0
                
                # Delay based on rod speed với jitter
                user = dm.get_user(uid)
                FISHING_RODS = config_manager.get_fishing_rods()
                rod = FISHING_RODS.get(user.get('inventory', {}).get('rod', '1'), {"auto_speed": 4.0}) if FISHING_RODS else {"auto_speed": 4.0}
                
                base_delay = rod.get('auto_speed', 4.0)
                jitter = random.uniform(-0.5, 0.5)
                actual_delay = max(2.5, base_delay + jitter)  # Minimum 2.5s
                
                await asyncio.sleep(actual_delay)
        
        except asyncio.CancelledError:
            logging.info(f"Auto fishing cancelled for {uid}")
        except Exception as e:
            logging.error(f"Auto error for {uid}: {e}")
            logging.error(traceback.format_exc())
        
        finally:
            # Cleanup và final message
            stats = auto_manager.get_stats(uid)
            auto_manager.cleanup_session(uid)
            
            try:
                await rate_limiter.acquire(uid)
                
                txt = f"✅ **KẾT THÚC**\n\n"
                txt += f"📊 Tổng: {stats['count']} câu\n"
                txt += f"💰 Thu: +{fmt(stats['coins'])}\n"
                txt += f"⭐ EXP: +{stats['exp']}\n"
                
                if stats['best_catch']:
                    txt += f"\n🎯 Tốt nhất: {stats['best_catch'][:30]}"
                
                kb = [[InlineKeyboardButton("↩️ Menu", callback_data='back_menu')]]
                
                await safe_edit_message(
                    bot, cid, mid, txt,
                    reply_markup=InlineKeyboardMarkup(kb)
                )
            except:
                pass

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    
    # Rate limiting
    await rate_limiter.acquire(uid)
    
    name = update.effective_user.username or update.effective_user.first_name
    user = dm.get_user(uid)
    user["username"] = f"@{name}" if update.effective_user.username else name
    dm.update_user(uid, user)
    rank, _, _, _ = get_user_rank(user.get('total_exp', 0))
    s = Monitor.stats()
    reset = get_next_sunday()
    
    txt = truncate_text(
        f"🎮 **GAME CÂU CÁ**\n\n"
        f"👤 {user['username']}\n"
        f"💰 {fmt(user['coins'])} xu\n"
        f"⭐ Lv.{user['level']}\n"
        f"🎯 {fmt(user.get('total_exp', 0))} EXP\n"
        f"🏆 {rank['name']}\n"
        f"🎣 {get_rod_name(user)}\n\n"
        f"⏰ Reset: CN {reset.strftime('%d/%m')}\n\n"
        f"/menu - Menu\n"
        f"/stop - Dừng auto\n"
        f"/reload - Reload config\n\n"
        f"💻 CPU {s['cpu']:.0f}% RAM {s['ram']:.0f}%"
    )
    
    await update.message.reply_text(txt, parse_mode='Markdown')

async def reload_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await rate_limiter.acquire(uid)
    
    config_manager.reload_config()
    await update.message.reply_text("✅ **Config đã được reload!**\n\n/menu", parse_mode='Markdown')

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    
    # Rate limiting
    await rate_limiter.acquire(uid)
    
    user = dm.get_user(uid)
    if not user.get("username"):
        user["username"] = f"@{update.effective_user.username}" if update.effective_user.username else update.effective_user.first_name
        dm.update_user(uid, user)
    
    rank, _, _, _ = get_user_rank(user.get('total_exp', 0))
    kb = [
        [InlineKeyboardButton("🎣 Câu", callback_data='fish'),
         InlineKeyboardButton("🤖 Auto", callback_data='auto')],
        [InlineKeyboardButton("🎣 Shop", callback_data='shop'),
         InlineKeyboardButton("🎲 Chẵn Lẻ", callback_data='chanle')],
        [InlineKeyboardButton("🎒 Kho", callback_data='inv'),
         InlineKeyboardButton("📊 Stats", callback_data='stats')],
        [InlineKeyboardButton("🏆 Top Xu", callback_data='top_coins'),
         InlineKeyboardButton("🏆 Top Rank", callback_data='top_rank')],
        [InlineKeyboardButton("🏆 Rank", callback_data='rank'),
         InlineKeyboardButton("📖 Help", callback_data='help')]
    ]
    
    reset = get_next_sunday()
    exp_req = get_level_exp(user['level'])
    exp_prog = user.get('level_exp', 0)
    
    txt = truncate_text(
        f"🎮 **MENU**\n\n"
        f"👤 {user['username']} Lv.{user['level']}\n"
        f"💰 {fmt(user['coins'])} xu\n"
        f"⭐ {fmt(user.get('total_exp', 0))} EXP\n"
        f"📊 {exp_prog}/{exp_req}\n"
        f"🏆 {rank['name']}\n"
        f"🎣 {get_rod_name(user)}\n\n"
        f"⏰ Reset: CN {reset.strftime('%d/%m')}"
    )
    
    await update.message.reply_text(
        txt, 
        reply_markup=InlineKeyboardMarkup(kb), 
        parse_mode='Markdown'
    )

async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await rate_limiter.acquire(uid)
    
    if auto_manager.is_active(uid):
        auto_manager.stop_session(uid)
        await update.message.reply_text("🛑 **Đang dừng auto...**", parse_mode='Markdown')
    else:
        await update.message.reply_text("❌ Không có auto!\n\n/menu", parse_mode='Markdown')

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    data = q.data
    
    # Rate limiting cho callbacks
    await rate_limiter.acquire(uid)
    
    if data == 'back_menu_auto':
        if auto_manager.is_active(uid):
            auto_manager.stop_session(uid)
            await q.edit_message_text("🛑 **Đang dừng...**", parse_mode='Markdown')
            await asyncio.sleep(2)
        data = 'back_menu'
    
    if data == 'shop':
        user = dm.get_user(uid)
        FISHING_RODS = config_manager.get_fishing_rods()
        if not FISHING_RODS:
            await q.edit_message_text("❌ Config chưa được load!", parse_mode='Markdown')
            return
            
        rod = user.get('inventory', {}).get('rod', '1')
        owned = user.get('owned_rods', ['1'])
        best = dm.best_rod(owned)
        txt = f"🎣 **SHOP CẦN**\n\n💰 {fmt(user['coins'])} xu\n🎣 {FISHING_RODS.get(rod, {'name': '🎣 Cơ bản'})['name']}\n\n"
        kb = []
        
        if rod != best:
            kb.append([InlineKeyboardButton(f"⚡ Trang bị tốt nhất", callback_data=f'equip_{best}')])
        
        cnt = 0
        for rid, rd in FISHING_RODS.items():
            if rid not in owned and cnt < 5:
                txt += f"⬜ {rd['name']} - {fmt(rd['price'])}\n   {rd['desc'][:50]}\n"
                if user['coins'] >= rd['price']:
                    kb.append([InlineKeyboardButton(f"Mua {rd['name'][:20]}", callback_data=f'buy_{rid}')])
                cnt += 1
        
        if cnt == 0:
            txt += "\n✅ Đã có tất cả!"
        
        kb.append([InlineKeyboardButton("↩️", callback_data='back_menu')])
        await q.edit_message_text(truncate_text(txt), reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    
    elif data.startswith('buy_'):
        rid = data.replace('buy_', '')
        user = dm.get_user(uid)
        FISHING_RODS = config_manager.get_fishing_rods()
        if not FISHING_RODS:
            await q.edit_message_text("❌ Config chưa được load!", parse_mode='Markdown')
            return
            
        rd = FISHING_RODS.get(rid)
        if not rd:
            await q.edit_message_text("❌ Lỗi!")
            return
        if user['coins'] < rd['price']:
            kb = [[InlineKeyboardButton("↩️", callback_data='back_menu')]]
            await q.edit_message_text(f"❌ Cần {fmt(rd['price'])} xu!", reply_markup=InlineKeyboardMarkup(kb))
            return
        user['coins'] -= rd['price']
        user.setdefault('owned_rods', ['1']).append(rid)
        best = dm.best_rod(user['owned_rods'])
        user['inventory']['rod'] = best
        dm.update_user(uid, user)
        kb = [[InlineKeyboardButton("↩️", callback_data='back_menu')]]
        await q.edit_message_text(
            truncate_text(f"✅ Mua thành công!\n{rd['name']}\n{rd['desc'][:100]}\n\n🎣 Đã trang bị!\n💰 Còn: {fmt(user['coins'])}"),
            reply_markup=InlineKeyboardMarkup(kb), 
            parse_mode='Markdown'
        )
    
    elif data.startswith('equip_'):
        rid = data.replace('equip_', '')
        user = dm.get_user(uid)
        if rid not in user.get('owned_rods', []):
            await q.edit_message_text("❌ Chưa có!")
            return
        user['inventory']['rod'] = rid
        dm.update_user(uid, user)
        FISHING_RODS = config_manager.get_fishing_rods()
        rd = FISHING_RODS.get(rid, {'name': '🎣 Cơ bản', 'desc': 'Mặc định'})
        kb = [[InlineKeyboardButton("↩️", callback_data='back_menu')]]
        await q.edit_message_text(
            truncate_text(f"✅ Trang bị: {rd['name']}\n{rd['desc'][:100]}"),
            reply_markup=InlineKeyboardMarkup(kb), 
            parse_mode='Markdown'
        )
    
    elif data == 'chanle':
        user = dm.get_user(uid)
        txt = f"🎲 **CHẴN LẺ**\n\n💰 {fmt(user['coins'])} xu\n🏆 Thắng: {user.get('chanle_win', 0)}\n💔 Thua: {user.get('chanle_lose', 0)}\n\n📋 Luật:\n🎲 1-6\n💰 1K xu\n🏆 x2.5"
        kb = [
            [InlineKeyboardButton("CHẴN", callback_data='cl_even'), 
             InlineKeyboardButton("LẺ", callback_data='cl_odd')],
            [InlineKeyboardButton("↩️", callback_data='back_menu')]
        ]
        await q.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    
    elif data in ['cl_even', 'cl_odd']:
        choice = 'even' if data == 'cl_even' else 'odd'
        await q.edit_message_text("🎲 Đang tung...")
        await asyncio.sleep(1.5)
        res, err = await chanle(uid, choice)
        if err:
            kb = [[InlineKeyboardButton("↩️", callback_data='back_menu')]]
            await q.edit_message_text(err, reply_markup=InlineKeyboardMarkup(kb))
            return
        dice_ico = ["⚀", "⚁", "⚂", "⚃", "⚄", "⚅"][res['dice'] - 1]
        choice_txt = "CHẴN" if choice == "even" else "LẺ"
        res_txt = "CHẴN" if res['dice'] % 2 == 0 else "LẺ"
        if res["success"]:
            txt = f"🎉 **THẮNG!**\n\n{dice_ico} {res['dice']} ({res_txt})\nChọn: {choice_txt}\n\n💰 +{fmt(res['win'])}\n💰 Xu: {fmt(res['coins'])}"
        else:
            txt = f"😢 **THUA!**\n\n{dice_ico} {res['dice']} ({res_txt})\nChọn: {choice_txt}\n\n💸 -1K\n💰 Xu: {fmt(res['coins'])}"
        kb = [
            [InlineKeyboardButton("🎲 Tiếp", callback_data='chanle')], 
            [InlineKeyboardButton("↩️", callback_data='back_menu')]
        ]
        await q.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    
    elif data == 'inv':
        user = dm.get_user(uid)
        FISH_TYPES = config_manager.get_fish_types()
        inv = user.get('inventory', {}).get('fish', {})
        txt = f"🎒 **KHO**\n\n💰 {fmt(user['coins'])}\n🎣 {get_rod_name(user)}\n\n📦 Cá:\n"
        total_val = 0
        total_cnt = 0
        if inv and FISH_TYPES:
            sorted_inv = sorted(inv.items(), key=lambda x: FISH_TYPES.get(x[0], {}).get('value', 0), reverse=True)[:15]
            for name, cnt in sorted_inv:
                if name in FISH_TYPES:
                    val = FISH_TYPES[name]['value'] * cnt
                    total_val += val * 0.7
                    total_cnt += cnt
                    txt += f"{get_color(FISH_TYPES[name]['rarity'])} {name[:20]}: {cnt}\n"
            txt += f"\n📊 {total_cnt} con\n💰 {fmt(int(total_val))}"
            kb = [[InlineKeyboardButton("💰 Bán", callback_data='sell')], [InlineKeyboardButton("↩️", callback_data='back_menu')]]
        else:
            txt += "❌ Trống!"
            kb = [[InlineKeyboardButton("↩️", callback_data='back_menu')]]
        await q.edit_message_text(truncate_text(txt), reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    
    elif data == 'sell':
        user = dm.get_user(uid)
        rank, _, _, _ = get_user_rank(user.get('total_exp', 0))
        FISH_TYPES = config_manager.get_fish_types()
        total_val = 0
        total_cnt = 0
        inv = user.get('inventory', {}).get('fish', {})
        if inv and FISH_TYPES:
            for name, cnt in inv.items():
                if name in FISH_TYPES:
                    total_val += FISH_TYPES[name]['value'] * cnt * 0.7 * rank.get('coin_bonus', 1.0)
                    total_cnt += cnt
            user['inventory']['fish'] = {}
            user["coins"] += int(total_val)
            dm.update_user(uid, user)
            kb = [[InlineKeyboardButton("↩️", callback_data='back_menu')]]
            await q.edit_message_text(
                f"💰 **BÁN OK!**\n{total_cnt} con\n+{fmt(int(total_val))} (x{rank.get('coin_bonus', 1.0):.1f})\n💰 {fmt(user['coins'])}", 
                reply_markup=InlineKeyboardMarkup(kb), 
                parse_mode='Markdown'
            )
        else:
            await q.edit_message_text("❌ Trống!")
    
    elif data == 'top_coins':
        users = []
        try:
            file = dm.repo.get_contents(GITHUB_FILE_PATH)
            for line in base64.b64decode(file.content).decode().strip().split('\n'):
                if line.strip():
                    try:
                        users.append(json.loads(line))
                    except:
                        pass
        except:
            pass
        sorted_u = sorted(users, key=lambda x: x.get('coins', 0), reverse=True)[:10]
        txt = "🏆 **TOP XU**\n\n"
        medals = ["🥇", "🥈", "🥉"] + [f"{i}." for i in range(4, 11)]
        for i, u in enumerate(sorted_u, 1):
            txt += f"{medals[i-1]} {u.get('username', 'User')[:20]} - {fmt(u.get('coins', 0))}\n"
        kb = [[InlineKeyboardButton("↩️", callback_data='back_menu')]]
        await q.edit_message_text(truncate_text(txt), reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    
    elif data == 'top_rank':
        users = []
        try:
            file = dm.repo.get_contents(GITHUB_FILE_PATH)
            for line in base64.b64decode(file.content).decode().strip().split('\n'):
                if line.strip():
                    try:
                        users.append(json.loads(line))
                    except:
                        pass
        except:
            pass
        sorted_u = sorted(users, key=lambda x: x.get('total_exp', 0), reverse=True)[:10]
        txt = "🏆 **TOP RANK**\n\n"
        medals = ["🥇", "🥈", "🥉"] + [f"{i}." for i in range(4, 11)]
        for i, u in enumerate(sorted_u, 1):
            r, _, _, _ = get_user_rank(u.get('total_exp', 0))
            txt += f"{medals[i-1]} {u.get('username', 'User')[:20]}\n   {r['name']} - {fmt(u.get('total_exp', 0))} EXP\n"
        kb = [[InlineKeyboardButton("↩️", callback_data='back_menu')]]
        await q.edit_message_text(truncate_text(txt), reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    
    elif data == 'rank':
        user = dm.get_user(uid)
        rank, level, next_r, exp_next = get_user_rank(user.get('total_exp', 0))
        exp_req = get_level_exp(user['level'])
        exp_prog = user.get('level_exp', 0)
        txt = f"🏆 **RANK**\n\n🎯 {fmt(user.get('total_exp', 0))} EXP\n🏆 {rank['name']}\n⭐ Lv.{user['level']} ({exp_prog}/{exp_req})\n\n📊 Buff:\n💰 Xu x{rank.get('coin_bonus', 1.0):.1f}\n🎣 Cá x{rank.get('fish_bonus', 1.0):.1f}\n🍀 May mắn x{rank.get('luck_bonus', 1.0):.1f}"
        if next_r:
            prog = user.get('total_exp', 0) - rank['exp_required']
            total = next_r['exp_required'] - rank['exp_required']
            pct = (prog / total * 100) if total > 0 else 0
            txt += f"\n\n📈 Tiếp: {next_r['name']}\nCần: {fmt(exp_next)} EXP\n{pct:.1f}%"
        else:
            txt += "\n\n👑 MAX!"
        kb = [[InlineKeyboardButton("↩️", callback_data='back_menu')]]
        await q.edit_message_text(truncate_text(txt), reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    
    elif data == 'help':
        txt = "📖 **HELP**\n\n🎣 10 xu/lần\n🍀 Thường > Auto\n🎲 1K xu, x2.5\n💰 Reset CN 00:00\n🎒 Bán = 70%\n⚡ Auto trang bị tốt nhất\n🔄 Auto update 60s\n📁 Config update 10p\n⚠️ Rate limit: 1 msg/1.5s\n\n/menu - Menu\n/stop - Dừng\n/reload - Reload config"
        kb = [[InlineKeyboardButton("↩️", callback_data='back_menu')]]
        await q.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    
    elif data == 'fish':
        user = dm.get_user(uid)
        FISHING_RODS = config_manager.get_fishing_rods()
        if not FISHING_RODS:
            await q.edit_message_text("❌ Config chưa được load!", parse_mode='Markdown')
            return
            
        rod = FISHING_RODS.get(user.get('inventory', {}).get('rod', '1'), {"speed": 3.0, "name": "🎣 Cơ bản"})
        rank, _, _, _ = get_user_rank(user.get('total_exp', 0))
        await q.edit_message_text(f"🎣 Câu... ({rod.get('speed', 3.0)}s)")
        await asyncio.sleep(rod.get('speed', 3.0))
        res, err = await fish(uid, auto=False)
        if err:
            kb = [[InlineKeyboardButton("↩️", callback_data='back_menu')]]
            await q.edit_message_text(err, reply_markup=InlineKeyboardMarkup(kb))
            return
        if res["success"]:
            luck_txt = ""
            total_luck = res.get("luck", 1.0)
            if total_luck >= 15.0:
                luck_txt = f"\n🍀 **GODLIKE x{total_luck:.1f}!**"
            elif total_luck >= 10.0:
                luck_txt = f"\n🍀 **LEGENDARY x{total_luck:.1f}!**"
            elif total_luck >= 6.0:
                luck_txt = f"\n🍀 **EPIC x{total_luck:.1f}!**"
            elif total_luck >= 3.0:
                luck_txt = f"\n🍀 **LUCKY x{total_luck:.1f}!**"
            elif total_luck > 1.5:
                luck_txt = f"\n🍀 May mắn x{total_luck:.1f}"
            txt = f"🎉 **BẮT ĐƯỢC!**\n{res['fish'][:30]} {get_color(res['rarity'])}\n💰 +{fmt(res['reward'])}\n⭐ +{res['exp']} EXP\n💰 {fmt(res['coins'])}{luck_txt}"
            if res['leveled']:
                txt += f"\n\n🎊 **LEVEL {res['level']}!**"
        else:
            txt = f"😢 Trượt!\n💰 {fmt(res['coins'])}"
        kb = [
            [InlineKeyboardButton("🎣 Tiếp", callback_data='fish')], 
            [InlineKeyboardButton("↩️", callback_data='back_menu')]
        ]
        await q.edit_message_text(truncate_text(txt), reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    
    elif data == 'auto':
        if auto_manager.is_active(uid):
            await q.edit_message_text("⚠️ Đang auto!\n/stop", parse_mode='Markdown')
            return
        if not Monitor.check():
            await q.edit_message_text("⚠️ Quá tải!", parse_mode='Markdown')
            return
        user = dm.get_user(uid)
        if user["coins"] < 10:
            kb = [[InlineKeyboardButton("↩️", callback_data='back_menu')]]
            await q.edit_message_text("❌ Cần 10 xu!", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
            return
        await q.edit_message_text("🤖 **KHỞI ĐỘNG AUTO...**", parse_mode='Markdown')
        asyncio.create_task(auto_fish_optimized(uid, q.message.message_id, q.message.chat_id, context.bot))
    
    elif data == 'stop_auto':
        if auto_manager.is_active(uid):
            auto_manager.stop_session(uid)
            await q.edit_message_text("🛑 **Đang dừng...**", parse_mode='Markdown')
        else:
            await q.edit_message_text("❌ Không có auto!", parse_mode='Markdown')
    
    elif data == 'stats':
        user = dm.get_user(uid)
        rank, _, _, _ = get_user_rank(user.get('total_exp', 0))
        win_rate = (user.get('win_count', 0) / user.get('fishing_count', 1)) * 100 if user.get('fishing_count', 0) > 0 else 0
        exp_req = get_level_exp(user['level'])
        exp_prog = user.get('level_exp', 0)
        txt = f"📊 **STATS**\n\n👤 {user['username'][:30]}\n⭐ Lv.{user['level']} ({exp_prog}/{exp_req})\n🏆 {rank['name']}\n\n📈 Câu:\n🎣 {user.get('fishing_count', 0)}\n✅ {user.get('win_count', 0)}\n❌ {user.get('lose_count', 0)}\n📊 {win_rate:.1f}%\n\n🎲 Chẵn lẻ:\n✅ {user.get('chanle_win', 0)}\n❌ {user.get('chanle_lose', 0)}"
        kb = [[InlineKeyboardButton("↩️", callback_data='back_menu')]]
        await q.edit_message_text(truncate_text(txt), reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    
    elif data == 'back_menu':
        user = dm.get_user(uid)
        rank, _, _, _ = get_user_rank(user.get('total_exp', 0))
        kb = [
            [InlineKeyboardButton("🎣 Câu", callback_data='fish'),
             InlineKeyboardButton("🤖 Auto", callback_data='auto')],
            [InlineKeyboardButton("🎣 Shop", callback_data='shop'),
             InlineKeyboardButton("🎲 Chẵn Lẻ", callback_data='chanle')],
            [InlineKeyboardButton("🎒 Kho", callback_data='inv'),
             InlineKeyboardButton("📊 Stats", callback_data='stats')],
            [InlineKeyboardButton("🏆 Top Xu", callback_data='top_coins'),
             InlineKeyboardButton("🏆 Top Rank", callback_data='top_rank')],
            [InlineKeyboardButton("🏆 Rank", callback_data='rank'),
             InlineKeyboardButton("📖 Help", callback_data='help')]
        ]
        reset = get_next_sunday()
        exp_req = get_level_exp(user['level'])
        exp_prog = user.get('level_exp', 0)
        txt = truncate_text(
            f"🎮 **MENU**\n\n"
            f"👤 {user['username'][:30]} Lv.{user['level']}\n"
            f"💰 {fmt(user['coins'])} xu\n"
            f"⭐ {fmt(user.get('total_exp', 0))} EXP\n"
            f"📊 {exp_prog}/{exp_req}\n"
            f"🏆 {rank['name']}\n"
            f"🎣 {get_rod_name(user)}\n\n"
            f"⏰ Reset: CN {reset.strftime('%d/%m')}"
        )
        await q.edit_message_text(
            txt, 
            reply_markup=InlineKeyboardMarkup(kb), 
            parse_mode='Markdown'
        )

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.error(f"Error: {context.error}")
    
    # Handle flood control errors globally
    if "flood" in str(context.error).lower():
        wait_time = extract_flood_wait(str(context.error))
        logging.warning(f"Global flood control, waiting {wait_time}s")
        await asyncio.sleep(wait_time)

def cleanup():
    """Cleanup trước khi tắt bot"""
    logging.info("Starting cleanup...")
    
    # Stop all auto sessions
    for uid in list(auto_manager.active_sessions.keys()):
        auto_manager.stop_session(uid)
    
    # Wait for sessions to stop
    time.sleep(2)
    
    # Clear all data
    auto_manager.active_sessions.clear()
    auto_manager.session_stats.clear()
    auto_manager.message_info.clear()
    auto_manager.flood_control.clear()
    
    # Shutdown executor
    if hasattr(dm, 'executor'):
        dm.executor.shutdown(wait=False)
    
    # Force garbage collection
    gc.collect()
    
    logging.info("Cleanup completed")

def main():
    """Main function"""
    # Load config first
    config = config_manager.load_config()
    if not config:
        print("❌ Không thể load config! Vui lòng tạo file game_config.json trên GitHub")
        print("📁 Repo: " + GITHUB_REPO)
        print("📄 File: game_config.json")
        return
    
    # Create application
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("stop", stop_cmd))
    app.add_handler(CommandHandler("reload", reload_cmd))
    app.add_handler(CallbackQueryHandler(button))
    app.add_error_handler(error_handler)
    
    # Display startup info
    reset = get_next_sunday()
    s = Monitor.stats()
    FISH_RANKS = config_manager.get_fish_ranks()
    FISH_TYPES = config_manager.get_fish_types()
    FISHING_RODS = config_manager.get_fishing_rods()
    
    print("=" * 50)
    print("🤖 Bot Started Successfully!")
    print("=" * 50)
    print(f"📊 Config loaded from GitHub")
    print(f"🏆 Ranks: {len(FISH_RANKS)}")
    print(f"🐟 Fish: {len(FISH_TYPES)}")
    print(f"🎣 Rods: {len(FISHING_RODS)}")
    print(f"⏰ Reset: {reset.strftime('%d/%m %H:%M')}")
    print(f"💻 CPU {s['cpu']:.0f}% | RAM {s['ram']:.0f}%")
    print(f"🔄 Config auto update every 10 minutes")
    print(f"⚡ Rate limit: {GLOBAL_RATE_LIMIT} msg/s")
    print(f"⏱️ Min interval: {MIN_UPDATE_INTERVAL}s per user")
    print(f"📁 Repository: {GITHUB_REPO}")
    print("=" * 50)
    
    try:
        # Run bot
        app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
    except KeyboardInterrupt:
        print("\n🛑 Shutting down...")
        cleanup()
        print("✅ Bot stopped successfully")
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        cleanup()

if __name__ == '__main__':
    main()
