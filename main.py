import logging,random,json,asyncio,threading,time,base64,os,psutil,pytz,gc
from datetime import datetime,timedelta
from telegram import Update,InlineKeyboardButton,InlineKeyboardMarkup
from telegram.ext import Application,CommandHandler,CallbackQueryHandler,ContextTypes
from github import Github
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor
load_dotenv()
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",level=logging.INFO)
BOT_TOKEN=os.getenv("BOT_TOKEN");GITHUB_TOKEN=os.getenv("GITHUB_TOKEN");GITHUB_REPO=os.getenv("GITHUB_REPO","htuananh1/Data-manager");GITHUB_FILE_PATH="bot_data.json";LOCAL_BACKUP_FILE="local_backup.json";VIETNAM_TZ=pytz.timezone("Asia/Ho_Chi_Minh")

FISH_RANKS={
"1":{"name":"🎣 Ngư Tân Thủ","exp_required":0,"coin_bonus":1,"fish_bonus":1},
"2":{"name":"⚔️ Ngư Tiểu Hiệp","exp_required":5000,"coin_bonus":1.15,"fish_bonus":1.1},
"3":{"name":"🗡️ Ngư Hiệp Khách","exp_required":20000,"coin_bonus":1.35,"fish_bonus":1.2},
"4":{"name":"🛡️ Ngư Tráng Sĩ","exp_required":80000,"coin_bonus":1.6,"fish_bonus":1.35},
"5":{"name":"⚡ Ngư Đại Hiệp","exp_required":250000,"coin_bonus":2,"fish_bonus":1.5},
"6":{"name":"🌟 Ngư Tông Sư","exp_required":800000,"coin_bonus":2.5,"fish_bonus":1.75},
"7":{"name":"🔥 Ngư Chân Nhân","exp_required":2000000,"coin_bonus":3.2,"fish_bonus":2},
"8":{"name":"💫 Ngư Thánh Giả","exp_required":5000000,"coin_bonus":4,"fish_bonus":2.5},
"9":{"name":"⚔️ Ngư Võ Thần","exp_required":15000000,"coin_bonus":5.5,"fish_bonus":3},
"10":{"name":"👑 Ngư Minh Chủ","exp_required":50000000,"coin_bonus":8,"fish_bonus":4},
"11":{"name":"🌌 Ngư Vũ Trụ","exp_required":150000000,"coin_bonus":12,"fish_bonus":5},
"12":{"name":"⭐ Ngư Vĩnh Hằng","exp_required":500000000,"coin_bonus":20,"fish_bonus":7}
}

FISH_TYPES={
"🍤 Tép":{"value":2,"chance":25,"exp":1,"rarity":"common"},
"🦐 Tôm":{"value":5,"chance":22,"exp":2,"rarity":"common"},
"🐟 Cá nhỏ":{"value":10,"chance":20,"exp":3,"rarity":"common"},
"🐠 Cá vàng":{"value":30,"chance":18,"exp":5,"rarity":"common"},
"🦀 Cua nhỏ":{"value":25,"chance":16,"exp":4,"rarity":"common"},
"🐡 Cá nóc":{"value":50,"chance":12,"exp":8,"rarity":"uncommon"},
"🦀 Cua lớn":{"value":60,"chance":10,"exp":10,"rarity":"uncommon"},
"🦑 Mực":{"value":80,"chance":8,"exp":12,"rarity":"uncommon"},
"🐚 Sò điệp":{"value":70,"chance":9,"exp":11,"rarity":"uncommon"},
"🦐 Tôm hùm nhỏ":{"value":90,"chance":7,"exp":13,"rarity":"uncommon"},
"🦈 Cá mập nhỏ":{"value":150,"chance":5,"exp":20,"rarity":"rare"},
"🐙 Bạch tuộc":{"value":200,"chance":4,"exp":25,"rarity":"rare"},
"🦈 Cá mập lớn":{"value":300,"chance":3,"exp":30,"rarity":"rare"},
"🐢 Rùa biển":{"value":400,"chance":2.5,"exp":35,"rarity":"rare"},
"🦞 Tôm hùm":{"value":500,"chance":2,"exp":40,"rarity":"rare"},
"🐊 Cá sấu":{"value":800,"chance":1.5,"exp":50,"rarity":"epic"},
"🐋 Cá voi":{"value":1000,"chance":1,"exp":60,"rarity":"epic"},
"🦭 Hải cẩu":{"value":900,"chance":0.8,"exp":55,"rarity":"epic"},
"⚡ Cá điện":{"value":1200,"chance":0.6,"exp":70,"rarity":"epic"},
"🌟 Cá thần":{"value":1500,"chance":0.5,"exp":80,"rarity":"epic"},
"🐉 Rồng biển":{"value":2500,"chance":0.4,"exp":100,"rarity":"legendary"},
"💎 Kho báu":{"value":3000,"chance":0.3,"exp":120,"rarity":"legendary"},
"👑 Vua đại dương":{"value":5000,"chance":0.2,"exp":150,"rarity":"legendary"},
"🔱 Thủy thần":{"value":6000,"chance":0.15,"exp":180,"rarity":"legendary"},
"🌊 Hải vương":{"value":7000,"chance":0.1,"exp":200,"rarity":"legendary"},
"🦄 Kỳ lân biển":{"value":10000,"chance":0.08,"exp":300,"rarity":"mythic"},
"🐲 Long vương":{"value":15000,"chance":0.05,"exp":400,"rarity":"mythic"},
"☄️ Thiên thạch":{"value":20000,"chance":0.03,"exp":500,"rarity":"mythic"},
"🌌 Vũ trụ":{"value":25000,"chance":0.02,"exp":600,"rarity":"mythic"},
"✨ Thần thánh":{"value":30000,"chance":0.01,"exp":700,"rarity":"mythic"},
"🎭 Bí ẩn":{"value":50000,"chance":0.008,"exp":1000,"rarity":"secret"},
"🗿 Cổ đại":{"value":75000,"chance":0.005,"exp":1500,"rarity":"secret"},
"🛸 Ngoài hành tinh":{"value":100000,"chance":0.003,"exp":2000,"rarity":"secret"},
"🔮 Hư không":{"value":150000,"chance":0.002,"exp":3000,"rarity":"secret"},
"⭐ Vĩnh hằng":{"value":500000,"chance":0.001,"exp":5000,"rarity":"secret"}
}

FISHING_RODS={
"1":{"name":"🎣 Cần cơ bản","price":0,"speed":3,"auto_speed":4,"common_bonus":1,"rare_bonus":0.5,"epic_bonus":0.1,"legendary_bonus":0.01,"mythic_bonus":0.001,"secret_bonus":0.0001,"exp_bonus":1},
"2":{"name":"🎋 Cần tre","price":100,"speed":2.8,"auto_speed":3.8,"common_bonus":1.1,"rare_bonus":0.6,"epic_bonus":0.15,"legendary_bonus":0.02,"mythic_bonus":0.002,"secret_bonus":0.0002,"exp_bonus":1.1},
"3":{"name":"🪵 Cần gỗ","price":500,"speed":2.5,"auto_speed":3.5,"common_bonus":1.2,"rare_bonus":0.8,"epic_bonus":0.2,"legendary_bonus":0.05,"mythic_bonus":0.005,"secret_bonus":0.0005,"exp_bonus":1.2},
"4":{"name":"🥉 Cần đồng","price":1500,"speed":2.3,"auto_speed":3.3,"common_bonus":1.3,"rare_bonus":1,"epic_bonus":0.3,"legendary_bonus":0.08,"mythic_bonus":0.008,"secret_bonus":0.0008,"exp_bonus":1.3},
"5":{"name":"⚙️ Cần sắt","price":5000,"speed":2,"auto_speed":3,"common_bonus":1.4,"rare_bonus":1.5,"epic_bonus":0.5,"legendary_bonus":0.15,"mythic_bonus":0.015,"secret_bonus":0.001,"exp_bonus":1.5},
"6":{"name":"🥈 Cần bạc","price":15000,"speed":1.8,"auto_speed":2.8,"common_bonus":1.5,"rare_bonus":2,"epic_bonus":0.8,"legendary_bonus":0.25,"mythic_bonus":0.025,"secret_bonus":0.0015,"exp_bonus":1.75},
"7":{"name":"🥇 Cần vàng","price":50000,"speed":1.5,"auto_speed":2.5,"common_bonus":1.6,"rare_bonus":3,"epic_bonus":1.5,"legendary_bonus":0.5,"mythic_bonus":0.05,"secret_bonus":0.002,"exp_bonus":2},
"8":{"name":"💍 Cần bạch kim","price":150000,"speed":1.3,"auto_speed":2.3,"common_bonus":1.7,"rare_bonus":4,"epic_bonus":2.5,"legendary_bonus":1,"mythic_bonus":0.1,"secret_bonus":0.003,"exp_bonus":2.5},
"9":{"name":"💎 Cần pha lê","price":500000,"speed":1,"auto_speed":2,"common_bonus":1.8,"rare_bonus":5,"epic_bonus":4,"legendary_bonus":2,"mythic_bonus":0.2,"secret_bonus":0.005,"exp_bonus":3},
"10":{"name":"💠 Cần kim cương","price":1500000,"speed":0.8,"auto_speed":1.8,"common_bonus":2,"rare_bonus":6,"epic_bonus":6,"legendary_bonus":3.5,"mythic_bonus":0.5,"secret_bonus":0.008,"exp_bonus":4}
}

def fmt(n):return f"{n//1000}k" if n>=1000 else str(n)
def get_rank(exp):r=FISH_RANKS["1"];lvl=1;nx=None;need=0
 for lv,d in FISH_RANKS.items():
  if exp>=d["exp_required"]:r=d;lvl=int(lv)
  else:break
 if lvl<len(FISH_RANKS):nx=FISH_RANKS[str(lvl+1)];need=nx["exp_required"]-exp
 return r,lvl,nx,need

class Local: 
 @staticmethod
 def save(d):open(LOCAL_BACKUP_FILE,'w',encoding='utf-8').write(json.dumps(d,ensure_ascii=False))
 @staticmethod
 def load(): 
  try:return json.load(open(LOCAL_BACKUP_FILE,'r',encoding='utf-8'))
  except:return{}

class Monitor: 
 @staticmethod
 def ok():s=psutil.virtual_memory();return psutil.cpu_percent(0.1)<85 and s.percent<90

class Data:
 def __init__(s):s.repo=Github(GITHUB_TOKEN).get_repo(GITHUB_REPO);s.q=[];s.l=threading.Lock();s.t={};s.ex=ThreadPoolExecutor(2);threading.Thread(target=s.auto,daemon=True).start()
 def get(s,uid): 
  try:f=s.repo.get_contents(GITHUB_FILE_PATH);c=base64.b64decode(f.content).decode();u={json.loads(x)['user_id']:json.loads(x)for x in c.strip().split('\n')if x};return u.get(str(uid),s.new(uid))
  except:return Local.load().get(str(uid),s.new(uid))
 def new(s,uid):return{"user_id":str(uid),"username":"","coins":100,"exp":0,"total_exp":0,"level":1,"fishing_count":0,"win_count":0,"lose_count":0,"owned_rods":["1"],"inventory":{"rod":"1","fish":{}}}
 def upd(s,uid,d):d['user_id']=str(uid);s.l.acquire();s.q.append(d);s.l.release()
 def batch(s): 
  if not s.q or not Monitor.ok():return
  s.l.acquire();u=s.q.copy();s.q.clear();s.l.release()
  try:f=s.repo.get_contents(GITHUB_FILE_PATH);c=base64.b64decode(f.content).decode();all={json.loads(x)['user_id']:json.loads(x)for x in c.strip().split('\n')if x};[all.update({x['user_id']:x})for x in u];Local.save(all);ct='\n'.join(json.dumps(v,ensure_ascii=False)for v in all.values());s.repo.update_file(GITHUB_FILE_PATH,"upd",ct,f.sha)
  except:s.repo.create_file(GITHUB_FILE_PATH,"new",ct)
 def auto(s): 
  while 1:time.sleep(20);s.ex.submit(s.batch)
dm=Data()

async def start(u:Update,c:ContextTypes.DEFAULT_TYPE):
 id=u.effective_user.id;user=dm.get(id);user["username"]=u.effective_user.first_name;dm.upd(id,user);r,_,_,_=get_rank(user['total_exp']);await u.message.reply_text(f"👋 {user['username']} Xu:{fmt(user['coins'])} Lv:{user['level']} {r['name']}\n/menu")
async def menu(u:Update,c:ContextTypes.DEFAULT_TYPE):await show(u,u.effective_user.id)
async def show(x,uid):u=dm.get(uid);r,_,_,_=get_rank(u['total_exp']);k=[[InlineKeyboardButton("🎣",callback_data='fish')],[InlineKeyboardButton("🎒",callback_data='inv')],[InlineKeyboardButton("🏆 EXP",callback_data='lb_exp'),InlineKeyboardButton("💰 Coin",callback_data='lb_coin')],[InlineKeyboardButton("🎲",callback_data='chanle')],[InlineKeyboardButton("🤖 Auto",callback_data='auto')]];await (x.edit_message_text if hasattr(x,"edit_message_text") else x.message.reply_text)(f"{u['username']} {fmt(u['coins'])} xu {r['name']}",reply_markup=InlineKeyboardMarkup(k))
async def cb(u:Update,c:ContextTypes.DEFAULT_TYPE):q=u.callback_query;await q.answer();d=q.data;id=q.from_user.id
 if d=='fish':await fish(q,id)
 elif d=='inv':await inv(q,id)
 elif d=='sell':await sell(q,id)
 elif d=='chanle':await chanle(q,id)
 elif d.startswith('co_'):await chanle_res(q,id,d)
 elif d=='lb_exp':await lb(q,'total_exp')
 elif d=='lb_coin':await lb(q,'coins')
 elif d=='auto':await auto(q,c,id)
 elif d=='stop':dm.t[id]=False;await q.edit_message_text("🛑");await show(q,id)
async def fish(q,id):u=dm.get(id);rod=FISHING_RODS[u['inventory']['rod']];await q.edit_message_text("⏳");await asyncio.sleep(rod['speed']);r,e=await process(id);await q.edit_message_text(f"🎣 {r['fish']} +{fmt(r['reward'])} xu" if r and r["success"] else "❌",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩",callback_data='menu')]]))
async def process(id,auto=False):u=dm.get(id); 
 if u['coins']<10:return None,"❌"
 u['coins']-=10;r,_,_,_=get_rank(u['total_exp']);rod=FISHING_RODS[u['inventory']['rod']];x=random.uniform(0,100);c=0
 for n,f in FISH_TYPES.items():ch=f['chance']*(rod.get(f['rarity']+'_bonus',1))*r['fish_bonus'];c+=ch
  if x<=c:u['coins']+=int(f['value']*r['coin_bonus']);u['exp']+=int(f['exp']*rod['exp_bonus']);u['total_exp']+=int(f['exp']*rod['exp_bonus']);u['inventory']['fish'][n]=u['inventory']['fish'].get(n,0)+1;dm.upd(id,u);return{"success":1,"fish":n,"reward":f['value'],"coins":u['coins']},None
 dm.upd(id,u);return{"success":0,"coins":u['coins']},None
async def inv(q,id):u=dm.get(id);t="🎒\n"+'\n'.join([f"{n}:{c}"for n,c in u['inventory']['fish'].items()]);await q.edit_message_text(t or "Empty",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💰 Sell",callback_data='sell')]]))
async def sell(q,id):u=dm.get(id);v=sum(FISH_TYPES[n]['value']*c*0.7 for n,c in u['inventory']['fish'].items());u['coins']+=int(v);u['inventory']['fish']={};dm.upd(id,u);await q.edit_message_text(f"+{fmt(int(v))} xu")
async def chanle(q,id):u=dm.get(id);await q.edit_message_text(f"🎲 {fmt(u['coins'])} xu",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⚪",callback_data='co_even'),InlineKeyboardButton("🔴",callback_data='co_odd')]]))
async def chanle_res(q,id,t):u=dm.get(id)
 if u['coins']<1000:await q.edit_message_text("❌");return
 u['coins']-=1000;d=random.randint(1,6);w=(d%2==0 and t=='co_even')or(d%2==1 and t=='co_odd')
 if w:u['coins']+=2500;await q.edit_message_text(f"{d} 🎉 +1500 xu")
 else:await q.edit_message_text(f"{d} ❌ -1000 xu")
 dm.upd(id,u)
async def lb(q,key):f=dm.repo.get_contents(GITHUB_FILE_PATH);c=base64.b64decode(f.content).decode();u=[json.loads(x)for x in c.strip().split('\n')if x];s=sorted(u,key=lambda x:x.get(key,0),reverse=True)[:10];await q.edit_message_text('\n'.join([f"{i+1}.{v.get('username')} {fmt(v.get(key,0))}"for i,v in enumerate(s)]))
async def auto(q,c,id):
 if id in dm.t and dm.t[id]:await q.edit_message_text("⚠️");return
 dm.t[id]=True;await q.edit_message_text("🤖");asyncio.create_task(auto_task(q,c,id))
async def auto_task(q,c,id):m=q.message.message_id;chat=q.message.chat_id;rod=FISHING_RODS[dm.get(id)['inventory']['rod']]
 while id in dm.t and dm.t[id]:r,e=await process(id,1)
  try:await c.bot.edit_message_text(chat_id=chat,message_id=m,text=f"AUTO {fmt(dm.get(id)['coins'])}",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛑",callback_data='stop')]]))
  except:pass
  await asyncio.sleep(rod['auto_speed'])
def main():app=Application.builder().token(BOT_TOKEN).build();app.add_handler(CommandHandler("start",start));app.add_handler(CommandHandler("menu",menu));app.add_handler(CallbackQueryHandler(cb));app.run_polling()
if __name__=="__main__":main()
