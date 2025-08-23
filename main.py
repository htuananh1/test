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

load_dotenv()
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

BOT_TOKEN = os.getenv('BOT_TOKEN')
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
GITHUB_REPO = os.getenv('GITHUB_REPO', 'htuananh1/Data-manager')
GITHUB_FILE_PATH = "bot_data.json"
LOCAL_BACKUP_FILE = "local_backup.json"
VIETNAM_TZ = pytz.timezone('Asia/Ho_Chi_Minh')

FISH_RANKS = {str(i+1): {"name": n, "exp_required": e, "coin_bonus": c, "fish_bonus": f} for i, (n, e, c, f) in enumerate([
    ("🎣 Ngư Tân Thủ", 0, 1.0, 1.0), ("⚔️ Ngư Tiểu Hiệp", 5000, 1.15, 1.1), ("🗡️ Ngư Hiệp Khách", 20000, 1.35, 1.2),
    ("🛡️ Ngư Tráng Sĩ", 80000, 1.6, 1.35), ("⚡ Ngư Đại Hiệp", 250000, 2.0, 1.5), ("🌟 Ngư Tông Sư", 800000, 2.5, 1.75),
    ("🔥 Ngư Chân Nhân", 2000000, 3.2, 2.0), ("💫 Ngư Thánh Giả", 5000000, 4.0, 2.5), ("⚔️ Ngư Võ Thần", 15000000, 5.5, 3.0),
    ("👑 Ngư Minh Chủ", 50000000, 8.0, 4.0), ("🌊 Ngư Hải Vương", 100000000, 10.0, 5.0), ("🔱 Ngư Thần Thánh", 200000000, 13.0, 6.0),
    ("⭐ Ngư Tiên Vương", 400000000, 17.0, 7.5), ("🌌 Ngư Thiên Tôn", 800000000, 22.0, 9.0), ("♾️ Ngư Vĩnh Hằng", 1500000000, 30.0, 12.0),
    ("🔮 Ngư Toàn Năng", 3000000000, 40.0, 15.0), ("🌠 Ngư Sáng Thế", 6000000000, 55.0, 20.0), ("⚜️ Ngư Tối Cao", 10000000000, 75.0, 25.0),
    ("🎭 Ngư Huyền Thoại", 20000000000, 100.0, 35.0), ("🏆 Ngư Cực Phẩm", 50000000000, 150.0, 50.0), ("👑 Ngư Thần", 100000000000, 200.0, 75.0),
    ("⚡ Ngư Thiên Đế", 200000000000, 300.0, 100.0), ("🌌 Ngư Vũ Trụ", 500000000000, 500.0, 150.0), ("♾️ Ngư Vô Cực", 1000000000000, 750.0, 200.0),
    ("🔯 Ngư Siêu Việt", 2000000000000, 1000.0, 300.0)
])}

FISH_TYPES = {n: {"value": v, "chance": c, "exp": e, "rarity": r} for n, v, c, e, r in [
    ("🍤 Tép", 2, 10.0, 1, "common"), ("🦐 Tôm", 5, 9.5, 2, "common"), ("🐟 Cá nhỏ", 10, 9.0, 3, "common"),
    ("🐠 Cá vàng", 30, 8.5, 5, "common"), ("🦀 Cua nhỏ", 25, 8.0, 4, "common"), ("🐡 Cá nóc", 50, 7.5, 8, "uncommon"),
    ("🦀 Cua lớn", 60, 7.0, 10, "uncommon"), ("🦑 Mực", 80, 6.5, 12, "uncommon"), ("🐚 Sò điệp", 70, 6.0, 11, "uncommon"),
    ("🦐 Tôm hùm nhỏ", 90, 5.5, 13, "uncommon"), ("🦪 Hàu", 85, 5.0, 14, "uncommon"), ("🦈 Cá mập nhỏ", 150, 4.5, 20, "rare"),
    ("🐙 Bạch tuộc", 200, 4.0, 25, "rare"), ("🦈 Cá mập lớn", 300, 3.5, 30, "rare"), ("🐢 Rùa biển", 400, 3.0, 35, "rare"),
    ("🦞 Tôm hùm", 500, 2.5, 40, "rare"), ("🦑 Mực khổng lồ", 600, 2.3, 45, "rare"), ("🐠 Cá chép vàng", 700, 2.1, 50, "rare"),
    ("🐟 Cá kiếm", 750, 1.9, 52, "rare"), ("🦭 Sư tử biển", 650, 1.7, 48, "rare"), ("🐊 Cá sấu", 800, 1.5, 60, "epic"),
    ("🐋 Cá voi", 1000, 1.3, 70, "epic"), ("🦭 Hải cẩu", 900, 1.2, 65, "epic"), ("⚡ Cá điện", 1200, 1.1, 75, "epic"),
    ("🌟 Cá thần", 1500, 1.0, 80, "epic"), ("🦈 Megalodon", 1800, 0.9, 85, "epic"), ("🐙 Kraken nhỏ", 2000, 0.8, 90, "epic"),
    ("🌊 Cá thủy tinh", 2200, 0.7, 95, "epic"), ("🔥 Cá lửa", 2400, 0.6, 98, "epic"), ("❄️ Cá băng", 2300, 0.55, 96, "epic"),
    ("🌈 Cá cầu vồng", 2100, 0.5, 92, "epic"), ("🐉 Rồng biển", 2500, 0.45, 120, "legendary"), ("💎 Cá kim cương", 3000, 0.4, 140, "legendary"),
    ("👑 Vua đại dương", 5000, 0.35, 180, "legendary"), ("🔱 Thủy thần", 6000, 0.3, 200, "legendary"), ("🌊 Hải vương", 7000, 0.25, 220, "legendary"),
    ("🐙 Kraken", 8000, 0.22, 250, "legendary"), ("🦕 Thủy quái", 9000, 0.2, 280, "legendary"), ("⚓ Cá ma", 10000, 0.18, 300, "legendary"),
    ("🏴‍☠️ Cướp biển", 11000, 0.16, 320, "legendary"), ("🧜‍♀️ Tiên cá", 12000, 0.14, 350, "legendary"), ("🔮 Pha lê biển", 13000, 0.12, 380, "legendary"),
    ("🦄 Kỳ lân biển", 15000, 0.1, 500, "mythic"), ("🐲 Long vương", 20000, 0.09, 600, "mythic"), ("☄️ Thiên thạch", 25000, 0.08, 700, "mythic"),
    ("🌌 Vũ trụ", 30000, 0.07, 800, "mythic"), ("✨ Thần thánh", 35000, 0.06, 900, "mythic"), ("🎇 Tinh vân", 40000, 0.05, 1000, "mythic"),
    ("🌠 Sao băng", 45000, 0.04, 1100, "mythic"), ("💫 Thiên hà", 50000, 0.035, 1200, "mythic"), ("🪐 Hành tinh", 55000, 0.03, 1300, "mythic"),
    ("☀️ Mặt trời", 60000, 0.025, 1500, "mythic"), ("🎭 Bí ẩn", 100000, 0.02, 2000, "secret"), ("🗿 Cổ đại", 150000, 0.018, 2500, "secret"),
    ("🛸 Ngoài hành tinh", 200000, 0.015, 3000, "secret"), ("🔮 Hư không", 300000, 0.012, 4000, "secret"), ("⭐ Vĩnh hằng", 500000, 0.01, 5000, "secret"),
    ("🌟 Thần thoại", 750000, 0.008, 6000, "secret"), ("💠 Vô cực", 1000000, 0.006, 7500, "secret"), ("🔯 Siêu việt", 1500000, 0.004, 9000, "secret"),
    ("⚜️ Tối thượng", 2000000, 0.003, 10000, "secret"), ("♾️ Vô hạn", 5000000, 0.002, 15000, "secret"), ("🏆 Ultimate", 10000000, 0.001, 20000, "secret")
]}

FISHING_RODS = {str(i+1): {"name": n, "price": p, "speed": s, "auto_speed": a, "common_bonus": cb, "rare_bonus": rb, "epic_bonus": eb, 
    "legendary_bonus": lb, "mythic_bonus": mb, "secret_bonus": sb, "exp_bonus": ex, "description": d} 
    for i, (n, p, s, a, cb, rb, eb, lb, mb, sb, ex, d) in enumerate([
    ("🎣 Cần cơ bản", 0, 3.0, 4.0, 1.0, 0.5, 0.1, 0.01, 0.001, 0.0001, 1.0, "Mặc định"),
    ("🎋 Cần tre", 100, 2.8, 3.8, 1.1, 0.6, 0.15, 0.02, 0.002, 0.0002, 1.1, "+10% EXP"),
    ("🪵 Cần gỗ", 500, 2.5, 3.5, 1.2, 0.8, 0.2, 0.05, 0.005, 0.0005, 1.2, "+20% EXP"),
    ("🥉 Cần đồng", 1500, 2.3, 3.3, 1.3, 1.0, 0.3, 0.08, 0.008, 0.0008, 1.3, "+30% EXP"),
    ("⚙️ Cần sắt", 5000, 2.0, 3.0, 1.4, 1.5, 0.5, 0.15, 0.015, 0.001, 1.5, "+50% EXP"),
    ("🥈 Cần bạc", 15000, 1.8, 2.8, 1.5, 2.0, 0.8, 0.25, 0.025, 0.0015, 1.75, "+75% EXP"),
    ("🥇 Cần vàng", 50000, 1.5, 2.5, 1.6, 3.0, 1.5, 0.5, 0.05, 0.002, 2.0, "x2 EXP"),
    ("💍 Cần bạch kim", 150000, 1.3, 2.3, 1.7, 4.0, 2.5, 1.0, 0.1, 0.003, 2.5, "x2.5 EXP"),
    ("💎 Cần pha lê", 500000, 1.0, 2.0, 1.8, 5.0, 4.0, 2.0, 0.2, 0.005, 3.0, "x3 EXP"),
    ("💠 Cần kim cương", 1500000, 0.8, 1.8, 2.0, 6.0, 6.0, 3.5, 0.5, 0.008, 4.0, "x4 EXP"),
    ("🗿 Cần hắc diệu", 5000000, 0.6, 1.5, 2.2, 8.0, 10.0, 6.0, 1.0, 0.01, 5.0, "x5 EXP"),
    ("⚔️ Cần mythril", 15000000, 0.5, 1.3, 2.5, 10.0, 15.0, 10.0, 2.0, 0.02, 7.0, "x7 EXP"),
    ("✨ Cần thiên thần", 50000000, 0.4, 1.0, 3.0, 15.0, 25.0, 20.0, 5.0, 0.05, 10.0, "x10 EXP"),
    ("🌌 Cần vũ trụ", 150000000, 0.3, 0.8, 3.5, 20.0, 40.0, 35.0, 10.0, 0.1, 15.0, "x15 EXP"),
    ("♾️ Cần vĩnh hằng", 500000000, 0.2, 0.5, 5.0, 30.0, 60.0, 50.0, 20.0, 0.5, 20.0, "x20 EXP"),
    ("🔮 Cần toàn năng", 1000000000, 0.1, 0.3, 10.0, 50.0, 100.0, 100.0, 50.0, 1.0, 30.0, "x30 EXP"),
    ("🌟 Cần thần thoại", 2000000000, 0.08, 0.25, 15.0, 75.0, 150.0, 150.0, 75.0, 1.5, 40.0, "x40 EXP"),
    ("⚡ Cần lôi thần", 5000000000, 0.06, 0.2, 20.0, 100.0, 200.0, 200.0, 100.0, 2.0, 50.0, "x50 EXP"),
    ("🏆 Cần tối cao", 10000000000, 0.04, 0.15, 30.0, 150.0, 300.0, 300.0, 150.0, 3.0, 75.0, "x75 EXP"),
    ("👑 Cần chúa tể", 50000000000, 0.02, 0.1, 50.0, 250.0, 500.0, 500.0, 250.0, 5.0, 100.0, "x100 EXP")
])}

class CacheManager:
    def __init__(self):
        self.cache = {}
        self.cache_timeout = 60
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
        if stats["cpu"] > 80 or stats["ram"] > 85:
            gc.collect()
            return False
        return True

class DataManager:
    def __init__(self):
        self.github = Github(GITHUB_TOKEN)
        self.repo = self.github.get_repo(GITHUB_REPO)
        self.auto_fishing_tasks = {}
        self.save_queue = []
        self.lock = threading.Lock()
        self.executor = ThreadPoolExecutor(max_workers=4)
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
            all_users = {}
            try:
                file_content = self.repo.get_contents(GITHUB_FILE_PATH)
                content_str = base64.b64decode(file_content.content).decode()
                for line in content_str.strip().split('\n'):
                    if line.strip():
                        try:
                            user_data = json.loads(line)
                            if 'user_id' in user_data:
                                user_data['coins'] = 100
                                user_data['last_reset'] = datetime.now(VIETNAM_TZ).isoformat()
                                all_users[user_data['user_id']] = user_data
                        except:
                            pass
            except:
                pass
            if all_users:
                lines = [json.dumps(data, ensure_ascii=False) for data in all_users.values()]
                content = '\n'.join(lines)
                try:
                    file = self.repo.get_contents(GITHUB_FILE_PATH)
                    self.repo.update_file(GITHUB_FILE_PATH, f"Reset - {datetime.now().strftime('%Y-%m-%d %H:%M')}", content, file.sha)
                except:
                    self.repo.create_file(GITHUB_FILE_PATH, f"Reset - {datetime.now().strftime('%Y-%m-%d %H:%M')}", content)
            cache_manager.clear()
        except Exception as e:
            logging.error(f"Reset error: {e}")
    
    def load_user_from_github(self, user_id):
        cached = cache_manager.get(f"user_{user_id}")
        if cached:
            return cached
        try:
            file_content = self.repo.get_contents(GITHUB_FILE_PATH)
            content_str = base64.b64decode(file_content.content).decode()
            for line in content_str.strip().split('\n'):
                if line.strip():
                    try:
                        user_data = json.loads(line)
                        if user_data.get('user_id') == str(user_id):
                            user_data.setdefault('owned_rods', ["1"])
                            user_data.setdefault('inventory', {"rod": "1", "fish": {}})
                            user_data.setdefault('total_exp', user_data.get('exp', 0))
                            cache_manager.set(f"user_{user_id}", user_data)
                            return user_data
                    except:
                        pass
        except:
            local_data = LocalStorage.load_local()
            if str(user_id) in local_data:
                return local_data[str(user_id)]
        return self.create_new_user(str(user_id))
    
    def create_new_user(self, user_id):
        return {"user_id": str(user_id), "username": "", "coins": 100, "exp": 0, "total_exp": 0, "level": 1,
                "fishing_count": 0, "win_count": 0, "lose_count": 0, "owned_rods": ["1"],
                "inventory": {"rod": "1", "fish": {}}, "created_at": datetime.now().isoformat()}
    
    def save_user_to_github(self, user_data):
        with self.lock:
            cache_manager.set(f"user_{user_data['user_id']}", user_data)
            self.save_queue.append(user_data)
    
    def batch_save_to_github(self):
        if not self.save_queue or not ResourceMonitor.check_resources():
            return
        with self.lock:
            if not self.save_queue:
                return
            users_to_save = self.save_queue.copy()
            self.save_queue.clear()
        try:
            all_users = {}
            try:
                file_content = self.repo.get_contents(GITHUB_FILE_PATH)
                content_str = base64.b64decode(file_content.content).decode()
                for line in content_str.strip().split('\n'):
                    if line.strip():
                        try:
                            user_data = json.loads(line)
                            if 'user_id' in user_data:
                                all_users[user_data['user_id']] = user_data
                        except:
                            pass
            except:
                pass
            for user_data in users_to_save:
                all_users[user_data['user_id']] = user_data
            LocalStorage.save_local(all_users)
            lines = [json.dumps(data, ensure_ascii=False) for data in all_users.values()]
            content = '\n'.join(lines)
            try:
                file = self.repo.get_contents(GITHUB_FILE_PATH)
                self.repo.update_file(GITHUB_FILE_PATH, f"Update - {datetime.now().strftime('%Y-%m-%d %H:%M')}", content, file.sha)
            except:
                self.repo.create_file(GITHUB_FILE_PATH, f"Create - {datetime.now().strftime('%Y-%m-%d %H:%M')}", content)
        except Exception as e:
            logging.error(f"Save error: {e}")
    
    def auto_save(self):
        while True:
            time.sleep(20)
            if self.save_queue:
                self.executor.submit(self.batch_save_to_github)
    
    def start_auto_save(self):
        threading.Thread(target=self.auto_save, daemon=True).start()
    
    def get_user(self, user_id):
        user_data = self.load_user_from_github(user_id)
        user_data.setdefault('inventory', {"rod": "1", "fish": {}})
        if user_data['inventory'].get('rod') not in FISHING_RODS:
            user_data['inventory']['rod'] = "1"
        user_data.setdefault('total_exp', user_data.get('exp', 0))
        return user_data
    
    def update_user(self, user_id, data):
        data['user_id'] = str(user_id)
        self.save_user_to_github(data)

data_manager = DataManager()

def format_number(num):
    return "{:,}".format(num)

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
        user["win_count"] = user.get("win_count", 0) + 1
        data_manager.update_user(user_id, user)
        return {"success": True, "dice": dice, "winnings": winnings, "coins": user["coins"], "choice": choice}, None
    else:
        user["lose_count"] = user.get("lose_count", 0) + 1
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
    
    rand = random.uniform(0, 100)
    cumulative = 0
    caught_fish = None
    
    fish_items = list(FISH_TYPES.items())
    random.shuffle(fish_items)
    
    for fish_name, fish_data in fish_items:
        rarity = fish_data['rarity']
        chance_map = {'common': rod_data['common_bonus'], 'uncommon': rod_data['common_bonus'],
                     'rare': rod_data['rare_bonus'], 'epic': rod_data['epic_bonus'],
                     'legendary': rod_data['legendary_bonus'], 'mythic': rod_data['mythic_bonus'],
                     'secret': rod_data['secret_bonus']}
        chance = fish_data["chance"] * chance_map.get(rarity, 1.0) * current_rank['fish_bonus']
        if is_auto and rarity in ['epic', 'legendary', 'mythic', 'secret']:
            chance *= 0.7
        cumulative += chance
        if rand <= cumulative:
            caught_fish = fish_name
            reward = int(fish_data["value"] * current_rank['coin_bonus'])
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
                "coins": user["coins"]}, None
    else:
        user["fishing_count"] += 1
        data_manager.update_user(user_id, user)
        return {"success": False, "coins": user["coins"]}, None

async def auto_fishing_task(user_id, message_id, chat_id, bot):
    count = 0
    total_coins = 0
    total_exp = 0
    rarity_count = {r: 0 for r in ["common", "uncommon", "rare", "epic", "legendary", "mythic", "secret"]}
    last_update_time = time.time()
    
    try:
        while user_id in data_manager.auto_fishing_tasks and data_manager.auto_fishing_tasks[user_id]:
            if count % 5 == 0 and not ResourceMonitor.check_resources():
                await asyncio.sleep(3)
                continue
            
            count += 1
            result, error = await process_fishing(user_id, is_auto=True)
            
            if error:
                try:
                    await bot.edit_message_text(chat_id=chat_id, message_id=message_id,
                        text=f"⛔ AUTO DỪNG\n{error}\nĐã câu: {count-1} lần\n💰 Thu: {format_number(total_coins)} xu", parse_mode='Markdown')
                except:
                    pass
                break
            
            if result["success"]:
                rarity_count[result["rarity"]] += 1
                total_coins += result["reward"] - 10
                total_exp += result["exp"]
            else:
                total_coins -= 10
            
            current_time = time.time()
            if current_time - last_update_time >= 2 or count % 3 == 0:
                last_update_time = current_time
                user = data_manager.get_user(user_id)
                current_rank, _, _, _ = get_user_rank(user.get('total_exp', 0))
                rod_data = FISHING_RODS.get(user.get('inventory', {}).get('rod', '1'), FISHING_RODS['1'])
                
                status_text = f"🤖 AUTO FISHING\n\n📊 Lần: {count}\n💰 Thu: {format_number(total_coins)} xu\n⭐ EXP: {total_exp}\n💰 Xu: {format_number(user['coins'])}\n\n🏆 {current_rank['name']}\n📈 Buff: 💰x{current_rank['coin_bonus']} 🎣x{current_rank['fish_bonus']}\n\n📈 "
                status_text += " ".join([f"{get_rarity_color(r)}{c}" for r, c in rarity_count.items() if c > 0])
                status_text += f"\n\n🎣 {rod_data['name']}\n⏱️ {rod_data['auto_speed']}s\n\n💡 /stop để dừng"
                
                keyboard = [[InlineKeyboardButton("🛑 DỪNG", callback_data=f'stop_auto_{user_id}')]]
                
                try:
                    await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=status_text,
                        reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
                except Exception as e:
                    if "message is not modified" not in str(e).lower():
                        try:
                            new_msg = await bot.send_message(chat_id=chat_id, text=status_text,
                                reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
                            message_id = new_msg.message_id
                        except:
                            pass
            
            await asyncio.sleep(rod_data['auto_speed'])
    
    except Exception as e:
        logging.error(f"Auto error {user_id}: {e}")
    
    finally:
        if user_id in data_manager.auto_fishing_tasks:
            del data_manager.auto_fishing_tasks[user_id]
        
        try:
            final_text = f"✅ AUTO KẾT THÚC\n\n📊 Tổng:\n🔄 {count} lần\n💰 {format_number(total_coins)} xu\n⭐ {total_exp} EXP\n\n📈 "
            final_text += " ".join([f"{get_rarity_color(r)}{c}" for r, c in rarity_count.items() if c > 0])
            await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=final_text, parse_mode='Markdown')
        except:
            pass

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    user = data_manager.get_user(user_id)
    user["username"] = user_name
    data_manager.update_user(user_id, user)
    current_rank, _, _, _ = get_user_rank(user.get('total_exp', 0))
    stats = ResourceMonitor.get_system_stats()
    next_reset = get_next_sunday()
    await update.message.reply_text(f"🎮 **FISHING GAME**\n\n👤 {user_name}\n💰 {format_number(user['coins'])} xu\n⭐ Lv.{user['level']}\n🎯 {format_number(user.get('total_exp', 0))} EXP\n🏆 {current_rank['name']}\n🎣 {get_current_rod_name(user)}\n\n⏰ Reset: CN {next_reset.strftime('%d/%m %H:%M')}\n\n/menu - Menu game\n/stop - Dừng auto\n\n💻 CPU {stats['cpu']:.1f}% | RAM {stats['ram']:.1f}%", parse_mode='Markdown')

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
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
    await update.message.reply_text(f"🎮 **MENU**\n\n👤 {user['username']} Lv.{user['level']}\n💰 {format_number(user['coins'])} xu\n⭐ {format_number(user.get('total_exp', 0))} EXP\n🏆 {current_rank['name']}\n🎣 {get_current_rod_name(user)}\n\n⏰ Reset: CN {next_reset.strftime('%d/%m')}", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in data_manager.auto_fishing_tasks:
        data_manager.auto_fishing_tasks[user_id] = False
        await update.message.reply_text("🛑 **ĐANG DỪNG AUTO...**", parse_mode='Markdown')
    else:
        await update.message.reply_text("❌ Không có auto nào đang chạy!", parse_mode='Markdown')

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
                    if user['coins'] >= rod_data['price']:
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
        text = f"🎲 **CHẴN LẺ**\n\n💰 {format_number(user['coins'])} xu\n🏆 Thắng: {user.get('win_count', 0)}\n💔 Thua: {user.get('lose_count', 0)}\n\n📋 Luật:\n🎲 Xúc xắc 1-6\n💰 Cược: 1000 xu\n🏆 Thắng: x2.5 (2500 xu)\n\nChọn:"
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
            text = f"😢 **THUA!**\n\n{dice_display} Kết quả: {result['dice']} ({result_text})\nBạn chọn: {choice_text}\n\n💸 Mất: 1000 xu\n💰 Còn: {format_number(result['coins'])} xu"
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
        total_value = 0
        total_count = 0
        fish_inv = user.get('inventory', {}).get('fish', {})
        if fish_inv:
            for fish_name, count in fish_inv.items():
                if fish_name in FISH_TYPES:
                    total_value += FISH_TYPES[fish_name]['value'] * count * 0.7 * current_rank['coin_bonus']
                    total_count += count
            user['inventory']['fish'] = {}
            user["coins"] += int(total_value)
            data_manager.update_user(user_id, user)
            await query.edit_message_text(f"💰 **BÁN THÀNH CÔNG!**\n{total_count} con\n+{format_number(int(total_value))} xu (Rank x{current_rank['coin_bonus']})\n💰 Xu: {format_number(user['coins'])}", parse_mode='Markdown')
        else:
            await query.edit_message_text("❌ Không có cá!")
    
    elif data == 'leaderboard_coins':
        all_users = []
        try:
            file_content = data_manager.repo.get_contents(GITHUB_FILE_PATH)
            content_str = base64.b64decode(file_content.content).decode()
            for line in content_str.strip().split('\n'):
                if line.strip():
                    try:
                        all_users.append(json.loads(line))
                    except:
                        pass
        except:
            pass
        sorted_users = sorted(all_users, key=lambda x: x.get('coins', 0), reverse=True)[:10]
        text = "🏆 **TOP 10 XU**\n\n"
        medals = ["🥇", "🥈", "🥉"] + [f"{i}." for i in range(4, 11)]
        for i, user_data in enumerate(sorted_users, 1):
            text += f"{medals[i-1]} {user_data.get('username', 'User')} - {format_number(user_data.get('coins', 0))} xu\n"
        keyboard = [[InlineKeyboardButton("↩️ Menu", callback_data='back_menu')]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    
    elif data == 'leaderboard_rank':
        all_users = []
        try:
            file_content = data_manager.repo.get_contents(GITHUB_FILE_PATH)
            content_str = base64.b64decode(file_content.content).decode()
            for line in content_str.strip().split('\n'):
                if line.strip():
                    try:
                        all_users.append(json.loads(line))
                    except:
                        pass
        except:
            pass
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
        text = "📖 **HƯỚNG DẪN**\n\n🎣 Câu: 10 xu/lần\n🎲 Chẵn lẻ: 1000 xu, thắng x2.5\n🏆 Rank cao = buff xu & cá\n💰 Reset CN 00:00\n🎒 Bán cá = 70% giá\n\n/menu - Menu game\n/stop - Dừng auto"
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
            text = f"🎉 **BẮT ĐƯỢC!**\n{result['fish']} {get_rarity_color(result['rarity'])}\n💰 +{format_number(result['reward'])} xu (x{current_rank['coin_bonus']})\n⭐ +{result['exp']} EXP\n💰 {format_number(result['coins'])} xu"
            if result['leveled_up']:
                text += f"\n\n🎊 **LEVEL {result['new_level']}!**"
        else:
            text = f"😢 Trượt!\n💰 {format_number(result['coins'])} xu"
        keyboard = [[InlineKeyboardButton("🎣 Câu tiếp", callback_data='game_fishing')], [InlineKeyboardButton("↩️ Menu", callback_data='back_menu')]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    
    elif data == 'auto_fishing':
        if user_id in data_manager.auto_fishing_tasks and data_manager.auto_fishing_tasks[user_id]:
            await query.edit_message_text("⚠️ Đang auto rồi!\n/stop để dừng", parse_mode='Markdown')
            return
        if not ResourceMonitor.check_resources():
            await query.edit_message_text("⚠️ Hệ thống quá tải!", parse_mode='Markdown')
            return
        data_manager.auto_fishing_tasks[user_id] = True
        await query.edit_message_text("🤖 **KHỞI ĐỘNG AUTO...**", parse_mode='Markdown')
        asyncio.create_task(auto_fishing_task(user_id, query.message.message_id, query.message.chat_id, context.bot))
    
    elif data.startswith('stop_auto'):
        target_user_id = user_id
        if '_' in data:
            try:
                target_user_id = int(data.split('_')[-1])
            except:
                pass
        if target_user_id == user_id:
            if target_user_id in data_manager.auto_fishing_tasks:
                data_manager.auto_fishing_tasks[target_user_id] = False
                await query.edit_message_text("🛑 **ĐANG DỪNG...**", parse_mode='Markdown')
            else:
                await query.edit_message_text("❌ Auto đã dừng!", parse_mode='Markdown')
        else:
            await query.answer("❌ Không thể dừng auto của người khác!", show_alert=True)
    
    elif data == 'view_stats':
        user = data_manager.get_user(user_id)
        current_rank, _, _, _ = get_user_rank(user.get('total_exp', 0))
        win_rate = (user.get('win_count', 0) / user.get('fishing_count', 1)) * 100 if user.get('fishing_count', 0) > 0 else 0
        text = f"📊 **THỐNG KÊ**\n\n👤 {user['username']}\n⭐ Level {user['level']}\n🏆 {current_rank['name']}\n\n📈 Thống kê:\n🎣 Câu: {user.get('fishing_count', 0)}\n✅ Thành công: {user.get('win_count', 0)}\n📊 Tỷ lệ: {win_rate:.1f}%\n🎲 Thắng CL: {user.get('win_count', 0)}\n💔 Thua CL: {user.get('lose_count', 0)}"
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

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", menu))
    application.add_handler(CommandHandler("stop", stop_command))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_error_handler(error_handler)
    
    next_reset = get_next_sunday()
    stats = ResourceMonitor.get_system_stats()
    print(f"🤖 Bot started\n🏆 Ranks: {len(FISH_RANKS)}\n🐟 Fish: {len(FISH_TYPES)}\n🎣 Rods: {len(FISHING_RODS)}\n⏰ Reset: {next_reset.strftime('%d/%m/%Y %H:%M')}\n💻 CPU: {stats['cpu']:.1f}% | RAM: {stats['ram']:.1f}%")
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped")
    except Exception as e:
        print(f"❌ Error: {e}")
