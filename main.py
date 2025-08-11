import os, re, json, threading, asyncio, requests, io
from collections import deque, defaultdict
from flask import Flask, request, jsonify, abort
from telegram import Update as TUpdate, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction, ParseMode
from telegram.ext import ApplicationBuilder as TAppBuilder, ContextTypes as TContext, MessageHandler as TMsgHandler, filters as tfilters, CommandHandler as TCmd, CallbackQueryHandler as TCB
from openai import OpenAI
try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None; types = None

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
VERCEL_API_KEY = os.environ["VERCEL_API_KEY"]
BASE_URL = os.getenv("BASE_URL","https://ai-gateway.vercel.sh/v1")
CHAT_MODEL = os.getenv("CHAT_MODEL","alibaba/qwen-3-235b")
CODE_MODEL = os.getenv("CODE_MODEL","anthropic/claude-4-sonnet")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY","")
GEMINI_IMAGE_MODEL = os.getenv("GEMINI_IMAGE_MODEL","gemini-2.0-flash-preview-image-generation")
ZALO_OA_ACCESS_TOKEN = os.getenv("ZALO_OA_ACCESS_TOKEN","")
ZALO_VERIFY_TOKEN = os.getenv("ZALO_VERIFY_TOKEN","")
PAGE_CHARS = int(os.getenv("PAGE_CHARS","3200"))
MAX_TOKENS = int(os.getenv("MAX_TOKENS","700"))
MAX_TOKENS_CODE = int(os.getenv("MAX_TOKENS_CODE","4000"))
CTX_TURNS = int(os.getenv("CTX_TURNS","7"))

client = OpenAI(api_key=VERCEL_API_KEY, base_url=BASE_URL)
app = Flask(__name__)
histories = defaultdict(lambda: deque(maxlen=32))
locks = defaultdict(asyncio.Lock)
PAGERS = {}

def chunk_pages(raw, per_page=PAGE_CHARS):
    lines = (raw or "").splitlines(); pages=[]; cur=[]; used=0
    for line in lines:
        add=len(line)+1
        if used+add>per_page and cur:
            pages.append("\n".join(cur)); cur=[line]; used=add
        else:
            cur.append(line); used+=add
    if cur: pages.append("\n".join(cur))
    return pages or [""]

def kb(idx,total):
    return None if total<=1 else InlineKeyboardMarkup([[InlineKeyboardButton("⏪", callback_data="pg_prev"), InlineKeyboardButton(f"{idx+1}/{total}", callback_data="pg_stay"), InlineKeyboardButton("⏩", callback_data="pg_next")]])

def page_payload(p):
    txt=p["pages"][p["idx"]]
    return (f"```{p['lang']}\n{txt}\n```", ParseMode.MARKDOWN) if p["is_code"] else (txt, ParseMode.HTML)

async def send_or_update_tg(ctx, chat_id, msg, p):
    text,mode = page_payload(p); keyboard = kb(p["idx"], len(p["pages"]))
    if msg: await msg.edit_text(text, parse_mode=mode, reply_markup=keyboard)
    else:
        m = await ctx.bot.send_message(chat_id, text, parse_mode=mode, reply_markup=keyboard)
        PAGERS[(m.chat_id, m.message_id)] = p

async def start_pager_tg(ctx, chat_id, raw, is_code=False, lang_hint=""):
    pages = chunk_pages(raw)
    await send_or_update_tg(ctx, chat_id, None, {"pages": pages, "is_code": is_code, "lang": lang_hint or "", "idx": 0})

async def on_page_nav_tg(update: TUpdate, context: TContext.DEFAULT_TYPE):
    q = update.callback_query
    if not q: return
    key=(q.message.chat_id, q.message.message_id); p=PAGERS.get(key)
    if not p: return await q.answer("Hết phiên.")
    if q.data=="pg_prev" and p["idx"]>0: p["idx"]-=1
    elif q.data=="pg_next" and p["idx"]<len(p["pages"])-1: p["idx"]+=1
    else: return await q.answer()
    await send_or_update_tg(context, q.message.chat_id, q.message, p); await q.answer()

def build_messages(cid, user_text, sys_prompt):
    msgs=[{"role":"system","content":sys_prompt}]
    keep=max(2, CTX_TURNS*2)
    msgs += [{"role":r,"content":c} for r,c in list(histories[cid])[-keep:]]
    msgs.append({"role":"user","content":user_text})
    return msgs

def complete_with_model(model, messages, max_tokens):
    res = client.chat.completions.create(model=model, max_tokens=max_tokens, temperature=0.7, messages=messages)
    return (res.choices[0].message.content or "").strip()

def _gem_client():
    if genai is None or types is None: raise RuntimeError("Thiếu google-genai")
    if not GEMINI_API_KEY: raise RuntimeError("Thiếu GEMINI_API_KEY")
    return genai.Client(api_key=GEMINI_API_KEY)

def create_image_bytes_gemini(prompt: str):
    cli = _gem_client()
    resp = cli.models.generate_content(model=GEMINI_IMAGE_MODEL, contents=prompt, config=types.GenerateContentConfig(response_modalities=['TEXT','IMAGE']))
    parts = resp.candidates[0].content.parts if resp and resp.candidates else []
    for part in parts:
        if getattr(part, "inline_data", None) and getattr(part.inline_data, "data", None):
            return part.inline_data.data
    raise RuntimeError("Gemini không trả ảnh.")

def want_image(t):
    t=(t or "").lower()
    return any(k in t for k in ["tạo ảnh","vẽ","generate image","draw image","vẽ giúp","create image","/img "])

def geocode_vn(q):
    r = requests.get("https://geocoding-api.open-meteo.com/v1/search", params={"name": q, "count": 1, "language":"vi", "format":"json", "country_code":"VN"}, timeout=20)
    r.raise_for_status(); data=r.json()
    if not data.get("results"): return None
    it=data["results"][0]
    return {"name":it["name"],"lat":it["latitude"],"lon":it["longitude"],"admin1":it.get("admin1","")}

def weather_vn(q):
    g=geocode_vn(q)
    if not g: return "Không tìm thấy địa danh ở Việt Nam."
    params={"latitude":g["lat"],"longitude":g["lon"],"current":"temperature_2m,relative_humidity_2m,precipitation,apparent_temperature,wind_speed_10m","daily":"temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,wind_speed_10m_max","timezone":"Asia/Ho_Chi_Minh"}
    r=requests.get("https://api.open-meteo.com/v1/forecast", params=params, timeout=20)
    r.raise_for_status(); j=r.json()
    cur=j.get("current",{}); daily=j.get("daily",{})
    name=g["name"]+(f", {g['admin1']}" if g.get("admin1") else "")
    t=cur.get("temperature_2m"); feels=cur.get("apparent_temperature"); rh=cur.get("relative_humidity_2m")
    ws=cur.get("wind_speed_10m"); p=cur.get("precipitation")
    tmax0=daily.get("temperature_2m_max",[None])[0]; tmin0=daily.get("temperature_2m_min",[None])[0]
    rain0=daily.get("precipitation_sum",[None])[0]; prob0=daily.get("precipitation_probability_max",[None])[0]
    tmax1=daily.get("temperature_2m_max",[None,None])[1]; tmin1=daily.get("temperature_2m_min",[None,None])[1]
    rain1=daily.get("precipitation_sum",[None,None])[1]; prob1=daily.get("precipitation_probability_max",[None,None])[1]
    icon="☀️"
    if (prob0 or 0)>=70 or (rain0 or 0)>=5: icon="🌧️"
    elif (prob0 or 0)>=30: icon="🌦️"
    elif (t or 0)>=33: icon="🥵"
    return (f"{icon} Thời tiết {name}\nHiện tại: {t}°C (cảm giác {feels}°C), ẩm {rh}%, gió {ws} km/h, mưa {p} mm\nHôm nay: {tmin0}–{tmax0}°C, mưa ~{rain0} mm, xác suất {prob0}%\nNgày mai: {tmin1}–{tmax1}°C, mưa ~{rain1} mm, xác suất {prob1}%")

def want_weather(t):
    t=(t or "").lower()
    if "thời tiết" not in t: return None
    known=["hà nội","hn","ha noi","hồ chí minh","tp.hcm","tphcm","sài gòn","đà nẵng","hải phòng","cần thơ","nha trang","đà lạt","huế","quy nhơn","vũng tàu","hạ long","phú quốc","biên hòa","thủ đức"]
    for k in known:
        if k in t: return k
    return "Hà Nội"

async def cmd_help_tg(update: TUpdate, context: TContext.DEFAULT_TYPE):
    txt = "Lệnh:\n/help – trợ giúp (@cuocdoivandep)\n/img <mô tả> – tạo ảnh (Gemini)\n/weather <địa danh VN> – thời tiết\n/code <yêu cầu> – code (Claude)\nChat thường dùng Qwen"
    await update.message.reply_text(txt)

async def cmd_img_tg(update: TUpdate, context: TContext.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    prompt = " ".join(context.args).strip()
    if not prompt: return await update.message.reply_text("Dùng: /img <mô tả>")
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
    try:
        data = create_image_bytes_gemini(prompt)
        buf = io.BytesIO(data); buf.name = "gen.png"
        await context.bot.send_photo(chat_id, buf, caption=prompt)
    except Exception as e:
        await update.message.reply_text(f"Lỗi tạo ảnh: {e}")

async def cmd_weather_tg(update: TUpdate, context: TContext.DEFAULT_TYPE):
    place = " ".join(context.args).strip() or "Hà Nội"
    try:
        txt = weather_vn(place)
        await start_pager_tg(context, update.effective_chat.id, txt, is_code=False)
    except Exception:
        await update.message.reply_text("Lỗi lấy thời tiết.")

async def cmd_code_tg(update: TUpdate, context: TContext.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    q = " ".join(context.args).strip()
    if not q: return await update.message.reply_text("Dùng: /code <yêu cầu>")
    async with locks[chat_id]:
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        msgs = build_messages(chat_id, q, sys_prompt="Bạn là lập trình viên kỳ cựu. Viết code đầy đủ, sạch, best practice. Không giới hạn độ dài; nếu dài, cứ trả hết.")
        try:
            result = complete_with_model(CODE_MODEL, msgs, MAX_TOKENS_CODE) or "..."
            m = re.search(r"```(\w+)?\n(.*?)```", result, flags=re.S)
            if m: await start_pager_tg(context, chat_id, m.group(2).rstrip(), is_code=True, lang_hint=m.group(1) or "")
            else: await start_pager_tg(context, chat_id, result, is_code=True)
            histories[chat_id].append(("user", q)); histories[chat_id].append(("assistant", result[:1000]))
        except Exception:
            await update.message.reply_text("Lỗi kết nối.")

async def on_text_tg(update: TUpdate, context: TContext.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    q = update.message.text or ""
    if want_image(q):
        prompt = re.sub(r"(?i)(tạo ảnh|vẽ|generate image|draw image|vẽ giúp|create image|/img)[:\-]*", "", q).strip() or "A cute cat in space suit, 3D render"
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
        try:
            data = create_image_bytes_gemini(prompt)
            buf = io.BytesIO(data); buf.name = "gen.png"
            await context.bot.send_photo(chat_id, buf, caption=prompt)
        except Exception as e:
            return await update.message.reply_text(f"Lỗi tạo ảnh: {e}")
        return
    place = want_weather(q)
    if place:
        try:
            txt = weather_vn(place)
            return await start_pager_tg(context, chat_id, txt, is_code=False)
        except Exception:
            return await update.message.reply_text("Lỗi lấy thời tiết.")
    async with locks[chat_id]:
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        msgs = build_messages(chat_id, q, sys_prompt="Bạn là Linh – bộc trực kiểu Grok; trả lời ngắn gọn, tự nhiên.")
        try:
            result = complete_with_model(CHAT_MODEL, msgs, MAX_TOKENS) or "..."
            await start_pager_tg(context, chat_id, result, is_code=False)
            histories[chat_id].append(("user", q)); histories[chat_id].append(("assistant", result[:1000]))
        except Exception:
            await update.message.reply_text("Lỗi kết nối.")

def zalo_send_text(user_id: str, text: str):
    if not ZALO_OA_ACCESS_TOKEN: 
        print("[ZALO] missing access token"); 
        return
    url = f"https://openapi.zalo.me/v3.0/oa/message/dispatch?access_token={ZALO_OA_ACCESS_TOKEN}"
    h = {"Content-Type":"application/json"}
    body = {"recipient":{"user_id":user_id},"message":{"text":text}}
    r = requests.post(url, headers=h, data=json.dumps(body), timeout=15)
    print("[ZALO] dispatch:", r.status_code, r.text[:200])

def handle_zalo_text(user_id: str, text: str):
    cid = f"zalo:{user_id}"
    if want_image(text):
        prompt = re.sub(r"(?i)(tạo ảnh|vẽ|generate image|draw image|vẽ giúp|create image|/img)[:\-]*", "", text).strip() or "A cute cat in space suit, 3D render"
        try:
            create_image_bytes_gemini(prompt); zalo_send_text(user_id, "Ảnh đã tạo xong.")
        except Exception as e:
            zalo_send_text(user_id, f"Lỗi tạo ảnh: {e}")
        return
    place = want_weather(text)
    if place:
        zalo_send_text(user_id, weather_vn(place)); return
    if text.strip().startswith("/code"):
        q = text.strip()[5:].strip() or "Hello"
        msgs = build_messages(cid, q, sys_prompt="Bạn là lập trình viên kỳ cựu. Viết code đầy đủ, sạch, best practice. Không giới hạn độ dài; nếu dài, cứ trả hết.")
        try:
            out = complete_with_model(CODE_MODEL, msgs, MAX_TOKENS_CODE) or "..."
            m = re.search(r"```(\w+)?\n(.*?)```", out, flags=re.S)
            out = m.group(2).rstrip() if m else out
            zalo_send_text(user_id, out[:3500])
        except Exception:
            zalo_send_text(user_id, "Lỗi kết nối."); 
        return
    sys_prompt = "Bạn là trợ lý của Hoàng Tuấn Anh (Zalo). Nói chuyện tự nhiên, ngắn gọn, thân thiện."
    msgs = build_messages(cid, text, sys_prompt=sys_prompt)
    try:
        out = complete_with_model(CHAT_MODEL, msgs, MAX_TOKENS) or "..."
        zalo_send_text(user_id, out[:3500])
    except Exception:
        zalo_send_text(user_id, "Lỗi kết nối.")

@app.get("/")
def root_ok():
    return "ok"

@app.get("/zalo/webhook")
def zalo_verify():
    v = request.args.get("verify","")
    return (v,200) if v==ZALO_VERIFY_TOKEN else ("Verify token mismatch",403)

@app.post("/zalo/webhook")
def zalo_events():
    try:
        data = request.get_json(force=True, silent=False) or {}
        print("[ZALO] incoming:", json.dumps(data, ensure_ascii=False)[:500])
    except Exception as e:
        print("[ZALO] bad json:", e); 
        return jsonify({"ok":False}), 400
    user_id = ""; text = ""
    if "sender" in data and "message" in data:
        user_id = str(data["sender"].get("id") or data["sender"].get("user_id") or "")
        msg = data["message"]; text = msg.get("text","") if isinstance(msg,dict) else ""
    elif "from" in data and "text" in data:
        user_id = str(data["from"].get("id") or "")
        text = data.get("text","")
    if user_id and text:
        threading.Thread(target=handle_zalo_text, args=(user_id, text), daemon=True).start()
    else:
        print("[ZALO] no user_id/text parsed")
    return jsonify({"ok":True})

def run_telegram():
    if not BOT_TOKEN: 
        print("[TG] disabled: missing BOT_TOKEN"); 
        return
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    app_tg = TAppBuilder().token(BOT_TOKEN).build()
    app_tg.add_handler(TCmd("help", cmd_help_tg))
    app_tg.add_handler(TCmd("img", cmd_img_tg))
    app_tg.add_handler(TCmd("weather", cmd_weather_tg))
    app_tg.add_handler(TCmd("code", cmd_code_tg))
    app_tg.add_handler(TCB(on_page_nav_tg, pattern=r"^pg_"))
    app_tg.add_handler(TMsgHandler(tfilters.TEXT & ~tfilters.COMMAND, on_text_tg))
    app_tg.run_polling(close_loop=False)

if __name__ == "__main__":
    threading.Thread(target=run_telegram, daemon=True).start()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT","8080")))
