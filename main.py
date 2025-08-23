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
import psutil
import gc
import pytz
from collections import deque

load_dotenv()
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

BOT_TOKEN = os.getenv('BOT_TOKEN')
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
GITHUB_REPO = os.getenv('GITHUB_REPO', 'htuananh1/Data-manager')
GITHUB_FILE_PATH = "bot_data.json"
LOCAL_BACKUP_FILE = "local_backup.json"
VIETNAM_TZ = pytz.timezone('Asia/Ho_Chi_Minh')

FISH_RANKS = {str(i+1): {"name": n, "exp_required": e, "coin_bonus": c, "fish_bonus": f} for i, (n, e, c, f) in enumerate([
    ("🎣 Ngư Tân Thủ", 0, 1.0, 1.0), ("⚔️ Ngư Tiểu Hiệp", 10000, 1.1, 1.05), ("🗡️ Ngư Hiệp Khách", 50000, 1.2, 1.1),
    ("🛡️ Ngư Tráng Sĩ", 150000, 1.3, 1.15), ("⚡ Ngư Đại Hiệp", 400000, 1.4, 1.2), ("🌟 Ngư Tông Sư", 1000000, 1.5, 1.25),
    ("🔥 Ngư Chân Nhân", 2500000, 1.6, 1.3), ("💫 Ngư Thánh Giả", 5000000, 1.7, 1.35), ("⚔️ Ngư Võ Thần", 10000000, 1.8, 1.4),
    ("👑 Ngư Minh Chủ", 25000000, 2.0, 1.5), ("🌊 Ngư Hải Vương", 50000000, 2.2, 1.6), ("🔱 Ngư Thần Thánh", 100000000, 2.4, 1.7),
    ("⭐ Ngư Tiên Vương", 200000000, 2.6, 1.8), ("🌌 Ngư Thiên Tôn", 400000000, 2.8, 1.9), ("♾️ Ngư Vĩnh Hằng", 800000000, 3.0, 2.0),
    ("🔮 Ngư Toàn Năng", 1500000000, 3.3, 2.1), ("🌠 Ngư Sáng Thế", 3000000000, 3.6, 2.2), ("⚜️ Ngư Tối Cao", 6000000000, 4.0, 2.3),
    ("🎭 Ngư Huyền Thoại", 12000000000, 4.5, 2.5), ("🏆 Ngư Cực Phẩm", 25000000000, 5.0, 2.7), ("👑 Ngư Thần", 50000000000, 5.5, 3.0),
    ("⚡ Ngư Thiên Đế", 100000000000, 6.0, 3.3), ("🌌 Ngư Vũ Trụ", 200000000000, 7.0, 3.6), ("♾️ Ngư Vô Cực", 500000000000, 8.0, 4.0),
    ("🔯 Ngư Siêu Việt", 1000000000000, 10.0, 5.0)
])}

FISH_TYPES = {n: {"value": v, "chance": c, "exp": e, "rarity": r} for n, v, c, e, r in [
    ("🍤 Tép", 1, 30.0, 1, "common"),
    ("🦐 Tôm", 2, 25.0, 2, "common"),
    ("🐟 Cá nhỏ", 3, 20.0, 3, "common"),
    ("🐠 Cá vàng", 5, 15.0, 4, "common"),
    ("🦀 Cua nhỏ", 4, 10.0, 3, "common"),
    
    ("🐡 Cá nóc", 8, 5.0, 5, "uncommon"),
    ("🦀 Cua lớn", 10, 4.0, 6, "uncommon"),
    ("🦑 Mực", 12, 3.0, 7, "uncommon"),
    ("🐚 Sò điệp", 11, 2.5, 6, "uncommon"),
    ("🦐 Tôm hùm nhỏ", 15, 2.0, 8, "uncommon"),
    ("🦪 Hàu", 13, 1.5, 7, "uncommon"),
    
    ("🦈 Cá mập nhỏ", 25, 1.0, 10, "rare"),
    ("🐙 Bạch tuộc", 30, 0.8, 12, "rare"),
    ("🦈 Cá mập lớn", 40, 0.6, 15, "rare"),
    ("🐢 Rùa biển", 50, 0.5, 18, "rare"),
    ("🦞 Tôm hùm", 60, 0.4, 20, "rare"),
    ("🦑 Mực khổng lồ", 70, 0.3, 22, "rare"),
    ("🐠 Cá chép vàng", 80, 0.25, 25, "rare"),
    ("🐟 Cá kiếm", 85, 0.2, 27, "rare"),
    ("🦭 Sư tử biển", 75, 0.15, 24, "rare"),
    
    ("🐊 Cá sấu", 100, 0.1, 30, "epic"),
    ("🐋 Cá voi", 150, 0.08, 40, "epic"),
    ("🦭 Hải cẩu", 120, 0.06, 35, "epic"),
    ("⚡ Cá điện", 180, 0.05, 45, "epic"),
    ("🌟 Cá thần", 200, 0.04, 50, "epic"),
    ("🦈 Megalodon", 250, 0.03, 55, "epic"),
    ("🐙 Kraken nhỏ", 300, 0.025, 60, "epic"),
    ("🌊 Cá thủy tinh", 280, 0.02, 58, "epic"),
    ("🔥 Cá lửa", 320, 0.015, 62, "epic"),
    ("❄️ Cá băng", 310, 0.012, 61, "epic"),
    ("🌈 Cá cầu vồng", 290, 0.01, 59, "epic"),
    
    ("🐉 Rồng biển", 500, 0.008, 80, "legendary"),
    ("💎 Cá kim cương", 600, 0.006, 90, "legendary"),
    ("👑 Vua đại dương", 800, 0.005, 100, "legendary"),
    ("🔱 Thủy thần", 1000, 0.004, 120, "legendary"),
    ("🌊 Hải vương", 1200, 0.003, 140, "legendary"),
    ("🐙 Kraken", 1500, 0.0025, 160, "legendary"),
    ("🦕 Thủy quái", 1800, 0.002, 180, "legendary"),
    ("⚓ Cá ma", 2000, 0.0015, 200, "legendary"),
    ("🏴‍☠️ Cướp biển", 2200, 0.001, 220, "legendary"),
    ("🧜‍♀️ Tiên cá", 2500, 0.0008, 250, "legendary"),
    ("🔮 Pha lê biển", 2800, 0.0006, 280, "legendary"),
    
    ("🦄 Kỳ lân biển", 5000, 0.0005, 400, "mythic"),
    ("🐲 Long vương", 7000, 0.0004, 500, "mythic"),
    ("☄️ Thiên thạch", 9000, 0.0003, 600, "mythic"),
    ("🌌 Vũ trụ", 12000, 0.00025, 700, "mythic"),
    ("✨ Thần thánh", 15000, 0.0002, 800, "mythic"),
    ("🎇 Tinh vân", 18000, 0.00015, 900, "mythic"),
    ("🌠 Sao băng", 20000, 0.0001, 1000, "mythic"),
    ("💫 Thiên hà", 25000, 0.00008, 1200, "mythic"),
    ("🪐 Hành tinh", 30000, 0.00006, 1400, "mythic"),
    ("☀️ Mặt trời", 35000, 0.00005, 1600, "mythic"),
    
    ("🎭 Bí ẩn", 50000, 0.00004, 2000, "secret"),
    ("🗿 Cổ đại", 70000, 0.00003, 2500, "secret"),
    ("🛸 Ngoài hành tinh", 100000, 0.00002, 3000, "secret"),
    ("🔮 Hư không", 150000, 0.000015, 4000, "secret"),
    ("⭐ Vĩnh hằng", 200000, 0.00001, 5000, "secret"),
    ("🌟 Thần thoại", 300000, 0.000008, 6000, "secret"),
    ("💠 Vô cực", 500000, 0.000006, 7500, "secret"),
    ("🔯 Siêu việt", 750000, 0.000004, 9000, "secret"),
    ("⚜️ Tối thượng", 1000000, 0.000002, 10000, "secret"),
    ("♾️ Vô hạn", 2000000, 0.000001, 15000, "secret"),
    ("🏆 Ultimate", 5000000, 0.0000005, 20000, "secret")
]}

FISHING_RODS = {str(i+1): {"name": n, "price": p, "speed": s, "auto_speed": a, "coin_multiplier": cm, "common_bonus": cb, 
    "rare_bonus": rb, "epic_bonus": eb, "legendary_bonus": lb, "mythic_bonus": mb, "secret_bonus": sb, 
    "exp_bonus": ex, "description": d} 
    for i, (n, p, s, a, cm, cb, rb, eb, lb, mb, sb, ex, d) in enumerate([
    ("🎣 Cần cơ bản", 0, 3.0, 4.0, 1.0, 1.0, 0.1, 0.01, 0.001, 0.0001, 0.00001, 1.0, "Mặc định"),
    ("🎋 Cần tre", 500, 2.9, 3.9, 1.05, 1.1, 0.15, 0.015, 0.0015, 0.00015, 0.000015, 1.05, "+5% xu +5% EXP"),
    ("🪵 Cần gỗ", 2000, 2.8, 3.8, 1.1, 1.2, 0.2, 0.02, 0.002, 0.0002, 0.00002, 1.1, "+10% xu +10% EXP"),
    ("🥉 Cần đồng", 8000, 2.7, 3.7, 1.15, 1.3, 0.25, 0.025, 0.0025, 0.00025, 0.000025, 1.15, "+15% xu +15% EXP"),
    ("⚙️ Cần sắt", 25000, 2.6, 3.6, 1.2, 1.4, 0.3, 0.03, 0.003, 0.0003, 0.00003, 1.2, "+20% xu +20% EXP"),
    ("🥈 Cần bạc", 80000, 2.5, 3.5, 1.25, 1.5, 0.35, 0.035, 0.0035, 0.00035, 0.000035, 1.25, "+25% xu +25% EXP"),
    ("🥇 Cần vàng", 250000, 2.4, 3.4, 1.3, 1.6, 0.4, 0.04, 0.004, 0.0004, 0.00004, 1.3, "+30% xu +30% EXP"),
    ("💍 Cần bạch kim", 800000, 2.3, 3.3, 1.35, 1.7, 0.45, 0.045, 0.0045, 0.00045, 0.000045, 1.35, "+35% xu +35% EXP"),
    ("💎 Cần pha lê", 2500000, 2.2, 3.2, 1.4, 1.8, 0.5, 0.05, 0.005, 0.0005, 0.00005, 1.4, "+40% xu +40% EXP"),
    ("💠 Cần kim cương", 8000000, 2.1, 3.1, 1.45, 1.9, 0.55, 0.055, 0.0055, 0.00055, 0.000055, 1.45, "+45% xu +45% EXP"),
    ("🗿 Cần hắc diệu", 25000000, 2.0, 3.0, 1.5, 2.0, 0.6, 0.06, 0.006, 0.0006, 0.00006, 1.5, "+50% xu +50% EXP"),
    ("⚔️ Cần mythril", 80000000, 1.9, 2.9, 1.6, 2.2, 0.65, 0.065, 0.0065, 0.00065, 0.000065, 1.6, "+60% xu +60% EXP"),
    ("✨ Cần thiên thần", 250000000, 1.8, 2.8, 1.7, 2.4, 0.7, 0.07, 0.007, 0.0007, 0.00007, 1.7, "+70% xu +70% EXP"),
    ("🌌 Cần vũ trụ", 800000000, 1.7, 2.7, 1.8, 2.6, 0.75, 0.075, 0.0075, 0.00075, 0.000075, 1.8, "+80% xu +80% EXP"),
    ("♾️ Cần vĩnh hằng", 2500000000, 1.6, 2.6, 1.9, 2.8, 0.8, 0.08, 0.008, 0.0008, 0.00008, 1.9, "+90% xu +90% EXP"),
    ("🔮 Cần toàn năng", 8000000000, 1.5, 2.5, 2.0, 3.0, 0.85, 0.085, 0.0085, 0.00085, 0.000085, 2.0, "x2 xu x2 EXP"),
    ("🌟 Cần thần thoại", 25000000000, 1.4, 2.4, 2.2, 3.3, 0.9, 0.09, 0.009, 0.0009, 0.00009, 2.2, "x2.2 xu x2.2 EXP"),
    ("⚡ Cần lôi thần", 80000000000, 1.3, 2.3, 2.4, 3.6, 0.95, 0.095, 0.0095, 0.00095, 0.000095, 2.4, "x2.4 xu x2.4 EXP"),
    ("🏆 Cần tối cao", 250000000000, 1.2, 2.2, 2.6, 4.0, 1.0, 0.1, 0.01, 0.001, 0.0001, 2.6, "x2.6 xu x2.6 EXP"),
    ("👑 Cần chúa tể", 1000000000000, 1.0, 2.0, 3.0, 5.0, 1.1, 0.11, 0.011, 0.0011, 0.00011, 3.0, "x3 xu x3 EXP")
])}

class CacheManager:
    def __init__(self):
        self.cache = {}
        self.cache_timeout = 120
        self.last_github_read = 0
        self.github_cooldown = 5
        
    def get(self, key):
        if key in self.cache:
            data, timestamp = self.cache[key]
            if time.time() - timestamp < self.cache_timeout:
                return data
        return None
        
    def set(self, key, value):
        self.cache[key] = (value, time.time())
        
    def clear(self):
        self.cache = {}
        
    def can_read_github(self):
        return time.time() - self.last_github_read >= self.github_cooldown
        
    def mark_github_read(self):
        self.last_github_read = time.time()

cache_manager = CacheManager()

def get_next_sunday():
    now = datetime.now(VIETNAM_TZ)
    days_until_sunday = (6 - now.weekday()) % 7
    if days_until_sunday == 0 and now.hour >= 0:
        days_until_sunday = 7
    next_sunday = now + timedelta(days=days_until_sunday)
    return next_sunday.replace(hour=0, minute=0, second=0, microsecond=0)

def should_reset_weekly():
    now = datetime.now(VIETNAM_TZ)
    return now.weekday() == 6 and now.hour == 0 and now.minute < 1

def get_user_rank(exp):
    current_rank = FISH_RANKS["1"]
    rank_level = 1
    for level, rank_data in FISH_RANKS.items():
        if exp >= rank_data["exp_required"]:
            current_rank = rank_data
            rank_level = int(level)
        else:
            break
    next_rank = FISH_RANKS.get(str(rank_level + 1)) if rank_level < len(FISH_RANKS) else None
    exp_to_next = next_rank["exp_required"] - exp if next_rank else 0
    return current_rank, rank_level, next_rank, exp_to_next

def format_number(num):
    if num >= 1000000000:
        return f"{num/1000000000:.1f}B".replace('.0B', 'B')
    elif num >= 1000000:
        return f"{num/1000000:.1f}M".replace('.0M', 'M')
    elif num >= 1000:
        return f"{num/1000:.1f}K".replace('.0K', 'K')
    else:
        return str(num)

class LocalStorage:
    @staticmethod
    def save_local(data):
        try:
            with open(LOCAL_BACKUP_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.error(f"Error saving local: {e}")
            
    @staticmethod
    def load_local():
        try:
            with open(LOCAL_BACKUP_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}

class ResourceMonitor:
    @staticmethod
    def get_system_stats():
        cpu = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()
        return {"cpu": cpu, "ram": mem.percent, "ram_used": mem.used/(1024**3), "ram_total": mem.total/(1024**3)}
        
    @staticmethod
    def check_resources():
        stats = ResourceMonitor.get_system_stats()
        if stats["cpu"] > 90 or stats["ram"] > 90:
            gc.collect()
            return False
        return True

class DataManager:
    def __init__(self):
        self.github = Github(GITHUB_TOKEN)
        self.repo = self.github.get_repo(GITHUB_REPO)
        self.auto_fishing_tasks = {}
        self.save_queue = deque(maxlen=100)
        self.lock = threading.Lock()
        self.last_save_time = time.time()
        self.save_interval = 30
        self.all_users_cache = {}
        self.last_full_load = 0
        self.start_auto_save()
        self.start_weekly_reset_check()
        
    def check_and_reset_weekly(self):
        while True:
            if should_reset_weekly():
                self.reset_all_users_coins()
                time.sleep(60)
            time.sleep(30)
            
    def start_weekly_reset_check(self):
        threading.Thread(target=self.check_and_reset_weekly, daemon=True).start()
        
    def reset_all_users_coins(self):
        try:
            self.load_all_users()
            for user_id in self.all_users_cache:
                self.all_users_cache[user_id]['coins'] = 100
                self.all_users_cache[user_id]['last_reset'] = datetime.now(VIETNAM_TZ).isoformat()
            self.force_save_to_github()
            cache_manager.clear()
        except Exception as e:
            logging.error(f"Reset error: {e}")
            
    def load_all_users(self):
        if time.time() - self.last_full_load < 10:
            return self.all_users_cache
            
        if not cache_manager.can_read_github():
            return self.all_users_cache
            
        try:
            cache_manager.mark_github_read()
            file_content = self.repo.get_contents(GITHUB_FILE_PATH)
            content_str = base64.b64decode(file_content.content).decode()
            self.all_users_cache = {}
            
            for line in content_str.strip().split('\n'):
                if line.strip():
                    try:
                        user_data = json.loads(line)
                        if 'user_id' in user_data:
                            self.all_users_cache[user_data['user_id']] = user_data
                    except:
                        pass
                        
            self.last_full_load = time.time()
            LocalStorage.save_local(self.all_users_cache)
        except:
            self.all_users_cache = LocalStorage.load_local()
            
        return self.all_users_cache
        
    def load_user_from_github(self, user_id):
        str_user_id = str(user_id)
        
        cached = cache_manager.get(f"user_{str_user_id}")
        if cached:
            return cached
            
        if str_user_id in self.all_users_cache:
            user_data = self.all_users_cache[str_user_id]
            cache_manager.set(f"user_{str_user_id}", user_data)
            return user_data
            
        self.load_all_users()
        
        if str_user_id in self.all_users_cache:
            user_data = self.all_users_cache[str_user_id]
            cache_manager.set(f"user_{str_user_id}", user_data)
            return user_data
            
        return self.create_new_user(str_user_id)
        
    def create_new_user(self, user_id):
        new_user = {
            "user_id": str(user_id),
            "username": "",
            "coins": 100,
            "exp": 0,
            "total_exp": 0,
            "level": 1,
            "fishing_count": 0,
            "win_count": 0,
            "lose_count": 0,
            "chanle_win": 0,
            "chanle_lose": 0,
            "owned_rods": ["1"],
            "inventory": {"rod": "1", "fish": {}},
            "created_at": datetime.now().isoformat()
        }
        self.all_users_cache[str(user_id)] = new_user
        return new_user
        
    def save_user_to_github(self, user_data):
        with self.lock:
            str_user_id = str(user_data['user_id'])
            self.all_users_cache[str_user_id] = user_data
            cache_manager.set(f"user_{str_user_id}", user_data)
            
            existing = False
            for i, queued in enumerate(self.save_queue):
                if queued['user_id'] == str_user_id:
                    self.save_queue[i] = user_data
                    existing = True
                    break
                    
            if not existing:
                self.save_queue.append(user_data)
                
    def batch_save_to_github(self):
        if not self.save_queue:
            return
            
        if time.time() - self.last_save_time < self.save_interval:
            return
            
        with self.lock:
            users_to_save = list(self.save_queue)
            self.save_queue.clear()
            
        if not users_to_save:
            return
            
        try:
            for user_data in users_to_save:
                self.all_users_cache[user_data['user_id']] = user_data
                
            self.force_save_to_github()
            self.last_save_time = time.time()
            
        except Exception as e:
            logging.error(f"Save error: {e}")
            with self.lock:
                self.save_queue.extend(users_to_save)
                
    def force_save_to_github(self):
        try:
            lines = []
            for user_id, data in self.all_users_cache.items():
                data['user_id'] = user_id
                lines.append(json.dumps(data, ensure_ascii=False))
                
            content = '\n'.join(lines)
            
            LocalStorage.save_local(self.all_users_cache)
            
            try:
                file = self.repo.get_contents(GITHUB_FILE_PATH)
                self.repo.update_file(
                    GITHUB_FILE_PATH,
                    f"Update - {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                    content,
                    file.sha
                )
            except:
                self.repo.create_file(
                    GITHUB_FILE_PATH,
                    f"Create - {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                    content
                )
                
            logging.info(f"Saved {len(self.all_users_cache)} users")
            
        except Exception as e:
            logging.error(f"Force save error: {e}")
            
    def auto_save(self):
        while True:
            time.sleep(30)
            if self.save_queue:
                try:
                    self.batch_save_to_github()
                except:
                    pass
                    
    def start_auto_save(self):
        threading.Thread(target=self.auto_save, daemon=True).start()
        
    def get_user(self, user_id):
        user_data = self.load_user_from_github(user_id)
        user_data.setdefault('inventory', {"rod": "1", "fish": {}})
        if user_data['inventory'].get('rod') not in FISHING_RODS:
            user_data['inventory']['rod'] = "1"
        user_data.setdefault('total_exp', user_data.get('exp', 0))
        user_data.setdefault('chanle_win', 0)
        user_data.setdefault('chanle_lose', 0)
        user_data.setdefault('owned_rods', ["1"])
        return user_data
        
    def update_user(self, user_id, data):
        data['user_id'] = str(user_id)
        self.save_user_to_github(data)

data_manager = DataManager()

def get_rarity_color(rarity):
    return {"common": "⚪", "uncommon": "🟢", "rare": "🔵", "epic": "🟣",
            "legendary": "🟡", "mythic": "🔴", "secret": "⚫"}.get(rarity, "⚪")

def get_current_rod_name(user):
    rod_id = user.get('inventory', {}).get('rod', '1')
    return FISHING_RODS.get(rod_id, FISHING_RODS['1'])['name']

async def odd_even_game(user_id, choice, bet_amount=1000):
    user = data_manager.get_user(user_id)
    if user["coins"] < bet_amount:
        return None, f"❌ Không đủ xu! (Có: {format_number(user['coins'])} xu)"
    user["coins"] -= bet_amount
    dice = random.randint(1, 6)
    dice_is_even = (dice % 2 == 0)
    player_wins = (choice == "even" and dice_is_even) or (choice == "odd" and not dice_is_even)
    if player_wins:
        winnings = int(bet_amount * 2.5)
        user["coins"] += winnings
        user["chanle_win"] = user.get("chanle_win", 0) + 1
        data_manager.update_user(user_id, user)
        return {"success": True, "dice": dice, "winnings": winnings, "coins": user["coins"], "choice": choice}, None
    else:
        user["chanle_lose"] = user.get("chanle_lose", 0) + 1
        data_manager.update_user(user_id, user)
        return {"success": False, "dice": dice, "coins": user["coins"], "choice": choice}, None

async def process_fishing(user_id, is_auto=False):
    user = data_manager.get_user(user_id)
    if user["coins"] < 10:
        return None, "❌ Cần 10 xu!"
    user["coins"] -= 10
    rod_id = user.get('inventory', {}).get('rod', '1')
    rod_data = FISHING_RODS.get(rod_id, FISHING_RODS['1'])
    current_rank, _, _, _ = get_user_rank(user.get('total_exp', 0))
    
    luck_bonus = 1.0
    if not is_auto:
        if random.random() < 0.05:
            luck_bonus = 3.0
        elif random.random() < 0.15:
            luck_bonus = 2.0
        elif random.random() < 0.3:
            luck_bonus = 1.5
            
    rand = random.uniform(0, 100)
    cumulative = 0
    caught_fish = None
    
    fish_items = list(FISH_TYPES.items())
    random.shuffle(fish_items)
    
    for fish_name, fish_data in fish_items:
        rarity = fish_data['rarity']
        chance_map = {
            'common': rod_data['common_bonus'],
            'uncommon': rod_data['common_bonus'],
            'rare': rod_data['rare_bonus'],
            'epic': rod_data['epic_bonus'],
            'legendary': rod_data['legendary_bonus'],
            'mythic': rod_data['mythic_bonus'],
            'secret': rod_data['secret_bonus']
        }
        chance = fish_data["chance"] * chance_map.get(rarity, 1.0) * current_rank['fish_bonus'] * luck_bonus
        if is_auto and rarity in ['epic', 'legendary', 'mythic', 'secret']:
            chance *= 0.5
        cumulative += chance
        if rand <= cumulative:
            caught_fish = fish_name
            base_value = fish_data["value"]
            reward = int(base_value * rod_data.get('coin_multiplier', 1.0) * current_rank['coin_bonus'])
            exp = int(fish_data["exp"] * rod_data.get('exp_bonus', 1.0))
            break
            
    if caught_fish:
        user['inventory'].setdefault('fish', {})
        user['inventory']['fish'][caught_fish] = user['inventory']['fish'].get(caught_fish, 0) + 1
        user["coins"] += reward
        user["exp"] += exp
        user["total_exp"] = user.get('total_exp', 0) + exp
        new_level = (user["exp"] // 100) + 1
        leveled_up = new_level > user["level"]
        if leveled_up:
            user["level"] = new_level
        user["fishing_count"] += 1
        user["win_count"] += 1
        data_manager.update_user(user_id, user)
        return {"success": True, "fish": caught_fish, "rarity": FISH_TYPES[caught_fish]['rarity'],
                "reward": reward, "exp": exp, "leveled_up": leveled_up, "new_level": user["level"],
                "coins": user["coins"], "luck_bonus": luck_bonus}, None
    else:
        user["fishing_count"] += 1
        user["lose_count"] += 1
        data_manager.update_user(user_id, user)
        return {"success": False, "coins": user["coins"]}, None

async def auto_fishing_task(user_id, message_id, chat_id, bot):
    count = 0
    total_coins = 0
    total_exp = 0
    rarity_count = {r: 0 for r in ["common", "uncommon", "rare", "epic", "legendary", "mythic", "secret"]}
    last_update_time = time.time()
    
    try:
        data_manager.auto_fishing_tasks[user_id] = True
        
        while user_id in data_manager.auto_fishing_tasks and data_manager.auto_fishing_tasks.get(user_id, False):
            count += 1
            result, error = await process_fishing(user_id, is_auto=True)
            
            if error:
                try:
                    await bot.edit_message_text(chat_id=chat_id, message_id=message_id,
                        text=f"⛔ **AUTO DỪNG**\n{error}\n\n📊 Kết quả:\n🔄 Đã câu: {count-1} lần\n💰 Thu được: {format_number(total_coins)} xu\n⭐ Tổng EXP: {total_exp}",
                        parse_mode='Markdown')
                except:
                    pass
                break
                
            if result and result["success"]:
                rarity_count[result["rarity"]] += 1
                total_coins += result["reward"] - 10
                total_exp += result["exp"]
            else:
                total_coins -= 10
                
            current_time = time.time()
            if current_time - last_update_time >= 3 or count % 5 == 0:
                last_update_time = current_time
                user = data_manager.get_user(user_id)
                current_rank, _, _, _ = get_user_rank(user.get('total_exp', 0))
                rod_data = FISHING_RODS.get(user.get('inventory', {}).get('rod', '1'), FISHING_RODS['1'])
                
                status_text = f"🤖 **AUTO FISHING**\n\n📊 **Thống kê:**\n├ 🔄 Số lần: {count}\n├ 💰 Thu được: {format_number(total_coins)} xu\n├ ⭐ Tổng EXP: {total_exp}\n└ 💰 Xu hiện tại: {format_number(user['coins'])}\n\n🏆 Rank: {current_rank['name']}\n📈 Buff: 💰x{current_rank['coin_bonus']} | 🎣x{current_rank['fish_bonus']}\n\n📈 Độ hiếm: "
                for rarity, cnt in rarity_count.items():
                    if cnt > 0:
                        status_text += f"{get_rarity_color(rarity)}{cnt} "
                status_text += f"\n\n🎣 Cần: {rod_data['name']}\n💰 Buff xu cần: x{rod_data['coin_multiplier']}\n⏱️ Tốc độ: {rod_data['auto_speed']}s\n\n💡 Dùng /stop hoặc nút bên dưới để dừng"
                
                keyboard = [[InlineKeyboardButton("🛑 DỪNG AUTO", callback_data='stop_auto')]]
                
                try:
                    await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=status_text,
                        reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
                except:
                    pass
                    
            user = data_manager.get_user(user_id)
            rod_data = FISHING_RODS.get(user.get('inventory', {}).get('rod', '1'), FISHING_RODS['1'])
            await asyncio.sleep(rod_data['auto_speed'])
            
    except Exception as e:
        logging.error(f"Auto fishing error for user {user_id}: {e}")
        
    finally:
        if user_id in data_manager.auto_fishing_tasks:
            del data_manager.auto_fishing_tasks[user_id]
            
        try:
            final_text = f"✅ **AUTO KẾT THÚC**\n\n📊 **Tổng kết:**\n├ 🔄 Tổng câu: {count} lần\n├ 💰 Thu được: {format_number(total_coins)} xu\n├ ⭐ Tổng EXP: {total_exp}\n└ 📈 Độ hiếm: "
            for rarity, cnt in rarity_count.items():
                if cnt > 0:
                    final_text += f"{get_rarity_color(rarity)}{cnt} "
            final_text += "\n\n💡 Dùng /menu để chơi tiếp"
            await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=final_text, parse_mode='Markdown')
        except:
            pass

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_name = update.effective_user.username or update.effective_user.first_name
    user = data_manager.get_user(user_id)
    user["username"] = f"@{user_name}" if update.effective_user.username else user_name
    data_manager.update_user(user_id, user)
    current_rank, _, _, _ = get_user_rank(user.get('total_exp', 0))
    stats = ResourceMonitor.get_system_stats()
    next_reset = get_next_sunday()
    await update.message.reply_text(f"🎮 **FISHING GAME**\n\n👤 {user['username']}\n💰 {format_number(user['coins'])} xu\n⭐ Lv.{user['level']}\n🎯 {format_number(user.get('total_exp', 0))} EXP\n🏆 {current_rank['name']}\n🎣 {get_current_rod_name(user)}\n\n⏰ Reset: CN {next_reset.strftime('%d/%m %H:%M')}\n\n/menu - Menu game\n/stop - Dừng auto\n\n💻 CPU {stats['cpu']:.1f}% | RAM {stats['ram']:.1f}%", parse_mode='Markdown')

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = data_manager.get_user(user_id)
    if not user.get("username"):
        user["username"] = f"@{update.effective_user.username}" if update.effective_user.username else update.effective_user.first_name
        data_manager.update_user(user_id, user)
    current_rank, _, _, _ = get_user_rank(user.get('total_exp', 0))
    keyboard = [
        [InlineKeyboardButton("🎣 Câu Cá", callback_data='game_fishing'),
         InlineKeyboardButton("🤖 Auto", callback_data='auto_fishing')],
        [InlineKeyboardButton("🎣 Shop Cần", callback_data='shop_rods'),
         InlineKeyboardButton("🎲 Chẵn Lẻ", callback_data='game_chanle')],
        [InlineKeyboardButton("🎒 Kho Đồ", callback_data='view_inventory'),
         InlineKeyboardButton("📊 Thống Kê", callback_data='view_stats')],
        [InlineKeyboardButton("🏆 BXH Xu", callback_data='leaderboard_coins'),
         InlineKeyboardButton("🏆 BXH Rank", callback_data='leaderboard_rank')],
        [InlineKeyboardButton("🏆 Hệ Thống Rank", callback_data='view_rank'),
         InlineKeyboardButton("📖 Hướng Dẫn", callback_data='help')]
    ]
    next_reset = get_next_sunday()
    await update.message.reply_text(f"🎮 **MENU**\n\n👤 {user['username']} Lv.{user['level']}\n💰 {format_number(user['coins'])} xu\n⭐ {format_number(user.get('total_exp', 0))} EXP\n🏆 {current_rank['name']}\n🎣 {get_current_rod_name(user)}\n\n⏰ Reset: CN {next_reset.strftime('%d/%m')}", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in data_manager.auto_fishing_tasks:
        data_manager.auto_fishing_tasks[user_id] = False
        await update.message.reply_text("🛑 **ĐANG DỪNG AUTO...**\n\nĐang tổng kết kết quả...", parse_mode='Markdown')
    else:
        await update.message.reply_text("❌ Bạn không có auto nào đang chạy!\n\nDùng /menu để bắt đầu", parse_mode='Markdown')

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data
    
    if data == 'shop_rods':
        user = data_manager.get_user(user_id)
        current_rod = user.get('inventory', {}).get('rod', '1')
        owned_rods = user.get('owned_rods', ['1'])
        text = f"🎣 **SHOP CẦN**\n\n💰 {format_number(user['coins'])} xu\n🎣 {FISHING_RODS[current_rod]['name']}\n\n"
        keyboard = []
        current_rod_num = int(current_rod)
        start_rod = max(1, current_rod_num - 2)
        end_rod = min(len(FISHING_RODS), current_rod_num + 3)
        for rod_id in range(start_rod, end_rod + 1):
            rod_id_str = str(rod_id)
            if rod_id_str in FISHING_RODS:
                rod_data = FISHING_RODS[rod_id_str]
                if rod_id_str in owned_rods:
                    text += f"✅ {rod_data['name']} - {rod_data['description']}\n"
                    if rod_id_str != current_rod:
                        keyboard.append([InlineKeyboardButton(f"Dùng {rod_data['name']}", callback_data=f'equip_rod_{rod_id_str}')])
                else:
                    text += f"⬜ {rod_data['name']} - {format_number(rod_data['price'])} xu - {rod_data['description']}\n"
                    if user['coins'] >= rod_data['price'] and rod_id_str not in owned_rods:
                        keyboard.append([InlineKeyboardButton(f"Mua {rod_data['name']}", callback_data=f'buy_rod_{rod_id_str}')])
        keyboard.append([InlineKeyboardButton("↩️ Menu", callback_data='back_menu')])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    
    elif data.startswith('buy_rod_'):
        rod_id = data.replace('buy_rod_', '')
        user = data_manager.get_user(user_id)
        rod_data = FISHING_RODS.get(rod_id)
        if not rod_data:
            await query.edit_message_text("❌ Cần không tồn tại!")
            return
        if user['coins'] < rod_data['price']:
            await query.edit_message_text(f"❌ Không đủ xu! Cần {format_number(rod_data['price'])} xu")
            return
        user['coins'] -= rod_data['price']
        user.setdefault('owned_rods', ['1']).append(rod_id)
        user['inventory']['rod'] = rod_id
        data_manager.update_user(user_id, user)
        await query.edit_message_text(f"✅ Mua thành công!\n{rod_data['name']}\n{rod_data['description']}\n💰 Còn: {format_number(user['coins'])} xu", parse_mode='Markdown')
    
    elif data.startswith('equip_rod_'):
        rod_id = data.replace('equip_rod_', '')
        user = data_manager.get_user(user_id)
        if rod_id not in user.get('owned_rods', []):
            await query.edit_message_text("❌ Chưa sở hữu cần này!")
            return
        user['inventory']['rod'] = rod_id
        data_manager.update_user(user_id, user)
        rod_data = FISHING_RODS[rod_id]
        await query.edit_message_text(f"✅ Đã trang bị: {rod_data['name']}\n{rod_data['description']}", parse_mode='Markdown')
    
    elif data == 'game_chanle':
        user = data_manager.get_user(user_id)
        text = f"🎲 **CHẴN LẺ**\n\n💰 {format_number(user['coins'])} xu\n🏆 Thắng: {user.get('chanle_win', 0)}\n💔 Thua: {user.get('chanle_lose', 0)}\n\n📋 Luật:\n🎲 Xúc xắc 1-6\n💰 Cược: 1K xu\n🏆 Thắng: x2.5 (2.5K xu)\n\nChọn:"
        keyboard = [[InlineKeyboardButton("CHẴN", callback_data='chanle_even'), InlineKeyboardButton("LẺ", callback_data='chanle_odd')],
                   [InlineKeyboardButton("↩️ Menu", callback_data='back_menu')]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    
    elif data in ['chanle_even', 'chanle_odd']:
        choice = 'even' if data == 'chanle_even' else 'odd'
        await query.edit_message_text("🎲 Đang tung...")
        await asyncio.sleep(1)
        result, error = await odd_even_game(user_id, choice)
        if error:
            await query.edit_message_text(error)
            return
        dice_display = ["⚀", "⚁", "⚂", "⚃", "⚄", "⚅"][result['dice'] - 1]
        choice_text = "CHẴN" if choice == "even" else "LẺ"
        result_text = "CHẴN" if result['dice'] % 2 == 0 else "LẺ"
        if result["success"]:
            text = f"🎉 **THẮNG!**\n\n{dice_display} Kết quả: {result['dice']} ({result_text})\nBạn chọn: {choice_text}\n\n💰 Thắng: {format_number(result['winnings'])} xu\n💰 Tổng: {format_number(result['coins'])} xu"
        else:
            text = f"😢 **THUA!**\n\n{dice_display} Kết quả: {result['dice']} ({result_text})\nBạn chọn: {choice_text}\n\n💸 Mất: 1K xu\n💰 Còn: {format_number(result['coins'])} xu"
        keyboard = [[InlineKeyboardButton("🎲 Chơi tiếp", callback_data='game_chanle')], [InlineKeyboardButton("↩️ Menu", callback_data='back_menu')]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    
    elif data == 'view_inventory':
        user = data_manager.get_user(user_id)
        fish_inv = user.get('inventory', {}).get('fish', {})
        text = f"🎒 **KHO ĐỒ**\n\n💰 {format_number(user['coins'])} xu\n🎣 {get_current_rod_name(user)}\n\n📦 Cá:\n"
        total_value = 0
        total_count = 0
        if fish_inv:
            sorted_fish = sorted(fish_inv.items(), key=lambda x: FISH_TYPES.get(x[0], {}).get('value', 0), reverse=True)[:15]
            for fish_name, count in sorted_fish:
                if fish_name in FISH_TYPES:
                    value = FISH_TYPES[fish_name]['value'] * count
                    total_value += value * 0.7
                    total_count += count
                    text += f"{get_rarity_color(FISH_TYPES[fish_name]['rarity'])} {fish_name}: {count}\n"
            text += f"\n📊 Tổng: {total_count} con\n💰 Giá: {format_number(int(total_value))} xu"
            keyboard = [[InlineKeyboardButton("💰 Bán tất cả", callback_data='sell_fish')], [InlineKeyboardButton("↩️ Menu", callback_data='back_menu')]]
        else:
            text += "❌ Chưa có cá!"
            keyboard = [[InlineKeyboardButton("↩️ Menu", callback_data='back_menu')]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    
    elif data == 'sell_fish':
        user = data_manager.get_user(user_id)
        current_rank, _, _, _ = get_user_rank(user.get('total_exp', 0))
        rod_data = FISHING_RODS.get(user.get('inventory', {}).get('rod', '1'), FISHING_RODS['1'])
        total_value = 0
        total_count = 0
        fish_inv = user.get('inventory', {}).get('fish', {})
        if fish_inv:
            for fish_name, count in fish_inv.items():
                if fish_name in FISH_TYPES:
                    total_value += FISH_TYPES[fish_name]['value'] * count * 0.7 * rod_data.get('coin_multiplier', 1.0) * current_rank['coin_bonus']
                    total_count += count
            user['inventory']['fish'] = {}
            user["coins"] += int(total_value)
            data_manager.update_user(user_id, user)
            await query.edit_message_text(f"💰 **BÁN THÀNH CÔNG!**\n{total_count} con\n+{format_number(int(total_value))} xu\n(Cần x{rod_data.get('coin_multiplier', 1.0)} | Rank x{current_rank['coin_bonus']})\n💰 Xu: {format_number(user['coins'])}", parse_mode='Markdown')
        else:
            await query.edit_message_text("❌ Không có cá!")
    
    elif data == 'leaderboard_coins':
        all_users = []
        for uid, udata in data_manager.all_users_cache.items():
            all_users.append(udata)
        sorted_users = sorted(all_users, key=lambda x: x.get('coins', 0), reverse=True)[:10]
        text = "🏆 **TOP 10 XU**\n\n"
        medals = ["🥇", "🥈", "🥉"] + [f"{i}." for i in range(4, 11)]
        for i, user_data in enumerate(sorted_users, 1):
            text += f"{medals[i-1]} {user_data.get('username', 'User')} - {format_number(user_data.get('coins', 0))} xu\n"
        keyboard = [[InlineKeyboardButton("↩️ Menu", callback_data='back_menu')]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    
    elif data == 'leaderboard_rank':
        all_users = []
        for uid, udata in data_manager.all_users_cache.items():
            all_users.append(udata)
        sorted_users = sorted(all_users, key=lambda x: x.get('total_exp', 0), reverse=True)[:10]
        text = "🏆 **TOP 10 RANK**\n\n"
        medals = ["🥇", "🥈", "🥉"] + [f"{i}." for i in range(4, 11)]
        for i, user_data in enumerate(sorted_users, 1):
            user_rank, _, _, _ = get_user_rank(user_data.get('total_exp', 0))
            text += f"{medals[i-1]} {user_data.get('username', 'User')}\n   {user_rank['name']} - {format_number(user_data.get('total_exp', 0))} EXP\n"
        keyboard = [[InlineKeyboardButton("↩️ Menu", callback_data='back_menu')]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    
    elif data == 'view_rank':
        user = data_manager.get_user(user_id)
        current_rank, rank_level, next_rank, exp_to_next = get_user_rank(user.get('total_exp', 0))
        text = f"🏆 **RANK NGƯ HIỆP**\n\n🎯 {format_number(user.get('total_exp', 0))} EXP\n🏆 {current_rank['name']}\n\n📊 Buff:\n💰 x{current_rank['coin_bonus']}\n🎣 x{current_rank['fish_bonus']}"
        if next_rank:
            progress = user.get('total_exp', 0) - current_rank['exp_required']
            total_needed = next_rank['exp_required'] - current_rank['exp_required']
            percent = (progress / total_needed * 100) if total_needed > 0 else 0
            text += f"\n\n📈 Tiếp: {next_rank['name']}\nCần: {format_number(exp_to_next)} EXP\n{percent:.1f}%"
        else:
            text += "\n\n👑 Max rank!"
        keyboard = [[InlineKeyboardButton("↩️ Menu", callback_data='back_menu')]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    
    elif data == 'help':
        text = "📖 **HƯỚNG DẪN**\n\n🎣 Câu: 10 xu/lần\n🍀 Câu thường may mắn hơn auto\n💰 Cần cao = buff xu nhiều\n🏆 Rank chỉ buff ít (khó cày)\n🎲 Chẵn lẻ: 1K xu, thắng x2.5\n💰 Reset CN 00:00\n🎒 Bán cá = 70% giá\n\n⚠️ Cá cực hiếm (0.00001%)\n💡 Cần quan trọng hơn rank\n\n/menu - Menu game\n/stop - Dừng auto"
        keyboard = [[InlineKeyboardButton("↩️ Menu", callback_data='back_menu')]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    
    elif data == 'game_fishing':
        user = data_manager.get_user(user_id)
        rod_data = FISHING_RODS.get(user.get('inventory', {}).get('rod', '1'), FISHING_RODS['1'])
        current_rank, _, _, _ = get_user_rank(user.get('total_exp', 0))
        await query.edit_message_text(f"🎣 Đang câu... ({rod_data['speed']}s)")
        await asyncio.sleep(rod_data['speed'])
        result, error = await process_fishing(user_id, is_auto=False)
        if error:
            await query.edit_message_text(error)
            return
        if result["success"]:
            luck_text = ""
            if result.get("luck_bonus", 1.0) >= 3.0:
                luck_text = "\n🍀 **SIÊU MAY MẮN x3!**"
            elif result.get("luck_bonus", 1.0) >= 2.0:
                luck_text = "\n🍀 **MAY MẮN x2!**"
            elif result.get("luck_bonus", 1.0) > 1.0:
                luck_text = "\n🍀 May mắn x1.5!"
            text = f"🎉 **BẮT ĐƯỢC!**\n{result['fish']} {get_rarity_color(result['rarity'])}\n💰 +{format_number(result['reward'])} xu\n(Cần x{rod_data.get('coin_multiplier', 1.0)} | Rank x{current_rank['coin_bonus']})\n⭐ +{result['exp']} EXP\n💰 {format_number(result['coins'])} xu{luck_text}"
            if result['leveled_up']:
                text += f"\n\n🎊 **LEVEL {result['new_level']}!**"
        else:
            text = f"😢 Trượt!\n💰 {format_number(result['coins'])} xu"
        keyboard = [[InlineKeyboardButton("🎣 Câu tiếp", callback_data='game_fishing')], [InlineKeyboardButton("↩️ Menu", callback_data='back_menu')]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    
    elif data == 'auto_fishing':
        if user_id in data_manager.auto_fishing_tasks and data_manager.auto_fishing_tasks.get(user_id, False):
            await query.edit_message_text("⚠️ Bạn đang auto rồi!\nDùng /stop để dừng", parse_mode='Markdown')
            return
        if not ResourceMonitor.check_resources():
            await query.edit_message_text("⚠️ Hệ thống đang quá tải!\nVui lòng thử lại sau", parse_mode='Markdown')
            return
        user = data_manager.get_user(user_id)
        if user["coins"] < 10:
            await query.edit_message_text("❌ Cần ít nhất 10 xu để auto!", parse_mode='Markdown')
            return
        await query.edit_message_text("🤖 **KHỞI ĐỘNG AUTO FISHING...**", parse_mode='Markdown')
        asyncio.create_task(auto_fishing_task(user_id, query.message.message_id, query.message.chat_id, context.bot))
    
    elif data == 'stop_auto':
        if user_id in data_manager.auto_fishing_tasks:
            data_manager.auto_fishing_tasks[user_id] = False
            await query.edit_message_text("🛑 **ĐANG DỪNG AUTO...**\n\nVui lòng chờ...", parse_mode='Markdown')
        else:
            await query.edit_message_text("❌ Không có auto nào đang chạy!", parse_mode='Markdown')
    
    elif data == 'view_stats':
        user = data_manager.get_user(user_id)
        current_rank, _, _, _ = get_user_rank(user.get('total_exp', 0))
        rod_data = FISHING_RODS.get(user.get('inventory', {}).get('rod', '1'), FISHING_RODS['1'])
        win_rate = (user.get('win_count', 0) / user.get('fishing_count', 1)) * 100 if user.get('fishing_count', 0) > 0 else 0
        text = f"📊 **THỐNG KÊ**\n\n👤 {user['username']}\n⭐ Level {user['level']}\n🏆 {current_rank['name']}\n🎣 {rod_data['name']}\n\n📈 Thống kê câu:\n🎣 Tổng: {user.get('fishing_count', 0)}\n✅ Thành công: {user.get('win_count', 0)}\n❌ Thất bại: {user.get('lose_count', 0)}\n📊 Tỷ lệ: {win_rate:.1f}%\n\n🎲 Chẵn lẻ:\n✅ Thắng: {user.get('chanle_win', 0)}\n❌ Thua: {user.get('chanle_lose', 0)}\n\n💰 Buff hiện tại:\nCần: x{rod_data.get('coin_multiplier', 1.0)}\nRank: x{current_rank['coin_bonus']}\nTổng: x{rod_data.get('coin_multiplier', 1.0) * current_rank['coin_bonus']:.1f}"
        keyboard = [[InlineKeyboardButton("↩️ Menu", callback_data='back_menu')]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    
    elif data == 'back_menu':
        user = data_manager.get_user(user_id)
        current_rank, _, _, _ = get_user_rank(user.get('total_exp', 0))
        keyboard = [
            [InlineKeyboardButton("🎣 Câu Cá", callback_data='game_fishing'),
             InlineKeyboardButton("🤖 Auto", callback_data='auto_fishing')],
            [InlineKeyboardButton("🎣 Shop Cần", callback_data='shop_rods'),
             InlineKeyboardButton("🎲 Chẵn Lẻ", callback_data='game_chanle')],
            [InlineKeyboardButton("🎒 Kho Đồ", callback_data='view_inventory'),
             InlineKeyboardButton("📊 Thống Kê", callback_data='view_stats')],
            [InlineKeyboardButton("🏆 BXH Xu", callback_data='leaderboard_coins'),
             InlineKeyboardButton("🏆 BXH Rank", callback_data='leaderboard_rank')],
            [InlineKeyboardButton("🏆 Hệ Thống Rank", callback_data='view_rank'),
             InlineKeyboardButton("📖 Hướng Dẫn", callback_data='help')]
        ]
        next_reset = get_next_sunday()
        await query.edit_message_text(f"🎮 **MENU**\n\n👤 {user['username']} Lv.{user['level']}\n💰 {format_number(user['coins'])} xu\n⭐ {format_number(user.get('total_exp', 0))} EXP\n🏆 {current_rank['name']}\n🎣 {get_current_rod_name(user)}\n\n⏰ Reset: CN {next_reset.strftime('%d/%m')}", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.error(f"Error: {context.error}")

def cleanup_on_shutdown():
    for user_id in list(data_manager.auto_fishing_tasks.keys()):
        data_manager.auto_fishing_tasks[user_id] = False
    time.sleep(1)
    data_manager.auto_fishing_tasks.clear()
    data_manager.force_save_to_github()

def main():
    application = Application.builder().token(BOT_TOKEN).concurrent_updates(True).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", menu))
    application.add_handler(CommandHandler("stop", stop_command))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_error_handler(error_handler)
    
    next_reset = get_next_sunday()
    stats = ResourceMonitor.get_system_stats()
    print(f"🤖 Bot started - Ultra Hard Mode\n🏆 Ranks: {len(FISH_RANKS)} (Low buff)\n🐟 Fish: {len(FISH_TYPES)} (0.00001% rare)\n🎣 Rods: {len(FISHING_RODS)} (Main buff)\n⏰ Reset: {next_reset.strftime('%d/%m/%Y %H:%M')}\n💻 CPU: {stats['cpu']:.1f}% | RAM: {stats['ram']:.1f}%")
    
    try:
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except KeyboardInterrupt:
        print("\n🛑 Shutting down...")
        cleanup_on_shutdown()
        print("✅ Cleanup completed")
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        cleanup_on_shutdown()

if __name__ == '__main__':
    main()
