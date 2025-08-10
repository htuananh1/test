import os, re, json, time, threading, shutil, sys, traceback, asyncio, queue, requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from collections import deque, defaultdict
from flask import Flask
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters, CommandHandler
from openai import OpenAI

BOT_TOKEN = os.getenv("BOT_TOKEN")
VERCEL_API_KEY = os.getenv("VERCEL_API_KEY")
BASE_URL = "https://ai-gateway.vercel.sh/v1"
MODEL = os.getenv("MODEL","openai/gpt-oss-120b")
SYSTEM_PROMPT = os.getenv( "SYSTEM_PROMPT","""Bạn là Linh – mồm mép, bộc trực, thông minh kiểu Grok: nhanh trí, châm biếm duyên dáng, thỉnh thoảng cà khịa nhẹ cho tỉnh ngủ. Giọng tự nhiên, có thể dùng tiếng lóng/chửi nhẹ đúng lúc (không tục, không 18+). Ưu tiên ngắn gọn, sắc sảo, có thể hỏi xoáy lại khi đề bài mơ hồ. Luôn hữu ích và chính xác; tránh phán bừa, không tiết lộ dữ liệu nhạy cảm.""" )
SYSTEM_PROMPT_CODE = os.getenv("SYSTEM_PROMPT_CODE", "Bạn là một lập trình viên kỳ cựu. Viết code đầy đủ, sạch, chuẩn best practice, giải thích ngắn gọn bằng tiếng Việt sau khi đưa code. Không giới hạn độ dài nội dung; nếu dài, cứ trả hết (bot sẽ tự chia phần).")
WORD_LIMIT = int(os.getenv("WORD_LIMIT", "350"))
SELF_PING_URL = os.getenv("SELF_PING_URL", "").strip()
ALLOWED_CHAT_ID = int(os.getenv("ALLOWED_CHAT_ID", "0"))
REMIND_CHAT_IDS = [s.strip() for s in os.getenv("REMIND_CHAT_IDS", "").split(",") if s.strip()]
REMIND_TEXT = os.getenv("REMIND_TEXT", "23h rồi đó, ngủ sớm cho khoẻ nha 🌙")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
CLEAN_INTERVAL_HOURS = int(os.getenv("CLEAN_INTERVAL_HOURS", "6"))
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "700"))
MAX_TOKENS_CODE = int(os.getenv("MAX_TOKENS_CODE", "4000"))
CTX_TURNS = int(os.getenv("CTX_TURNS", "4"))
MAX_DOC_BYTES = int(os.getenv("MAX_DOC_BYTES", str(2 * 1024 * 1024)))

client = OpenAI(api_key=VERCEL_API_KEY, base_url=BASE_URL)
app = Flask(__name__)

histories = defaultdict(lambda: deque(maxlen=16))
locks = defaultdict(asyncio.Lock)

def log_console(tag, payload):
    try: print(f"[{datetime.utcnow().isoformat()}][{tag}] {json.dumps(payload, ensure_ascii=False)}")
    except: print(f"[{datetime.utcnow().isoformat()}][{tag}] {payload}")
    sys.stdout.flush()

def notify_discord(title, payload):
    if DISCORD_WEBHOOK_URL:
        try:
            text = f"**{title}**\n```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}```"
            requests.post(DISCORD_WEBHOOK_URL, json={"content": text}, timeout=15)
        except: pass
    log_console(title, payload)

def strip_code(s): return re.sub(r"```[\w-]*\n|\n```", "", s or "").strip()
def word_clamp(s, limit):
    w=(s or "").split()
    return s if len(w)<=limit else " ".join(w[:limit])+"…"

def allowed_chat(update):
    chat = update.effective_chat
    if not chat: return False
    if chat.type == "private": return True
    if chat.type in ("group","supergroup"): return (ALLOWED_CHAT_ID == 0) or (chat.id == ALLOWED_CHAT_ID)
    return False

def asked_creator(text):
    t=(text or "").lower()
    return any(k in t for k in ["ai tạo","người tạo","ai làm ra","người làm ra","tác giả","dev của bạn"])

def is_codey(text):
    if not text: return False
    t = text.lower()
    keys = [
        "viết code","code giúp","sửa code","bug","lỗi","stack trace","exception",
        "python","java","kotlin","swift","dart","flutter","go","rust","c++","c#","php","ruby","js","ts","typescript","node","react","vue","svelte","angular","next.js","nuxt",
        "`","```","import ","class ","def ","function","const ","let ","var "
    ]
    return any(k in t for k in keys)

@app.get("/")
def root_ok(): return "OK"
@app.get("/health")
def health_ok(): return "OK"

def auto_ping():
    while True:
        if SELF_PING_URL:
            try: requests.head(SELF_PING_URL, timeout=10)
            except: pass
        time.sleep(45)

def cleanup_disk():
    freed=0
    for p in ["/home/runner/.cache","/home/runner/.npm","/tmp"]:
        try:
            if os.path.exists(p):
                size=sum(os.path.getsize(os.path.join(dp,f)) for dp,_,fs in os.walk(p) for f in fs)
                shutil.rmtree(p, ignore_errors=True); freed+=size
        except: pass
    return freed

def cleanup_loop():
    next_run=datetime.utcnow()
    while True:
        if datetime.utcnow()>=next_run:
            b=cleanup_disk()
            notify_discord("cleanup_done", {"freed_bytes": b})
            next_run=datetime.utcnow()+timedelta(hours=CLEAN_INTERVAL_HOURS)
        time.sleep(60)

def reminder_loop(bot, chat_ids):
    tz=ZoneInfo("Asia/Ho_Chi_Minh"); last_sent=None
    while True:
        now=datetime.now(tz)
        if now.hour==23 and last_sent!=now.date():
            for cid in chat_ids:
                try: bot.send_message(chat_id=cid, text=REMIND_TEXT)
                except Exception as e: notify_discord("remind_error", {"chat_id": cid, "error": str(e)})
            last_sent=now.date()
        time.sleep(20)

def send_long_text_sync(bot, chat_id, text):
    chunk = 3500
    for i in range(0, len(text), chunk):
        part = text[i:i+chunk]
        try:
            bot.send_message(chat_id=chat_id, text=part, disable_web_page_preview=True)
        except Exception as e:
            notify_discord("send_chunk_error", {"error": str(e)})

async def send_long_text(ctx, chat_id, text):
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, send_long_text_sync, ctx.bot, chat_id, text)

def build_messages(chat_id, user_text, code_mode=False):
    keep = max(1, CTX_TURNS*3-6)
    conv = list(histories[chat_id])[-keep:]
    sys_prompt = SYSTEM_PROMPT_CODE if code_mode else SYSTEM_PROMPT
    msgs = [{"role":"system","content": sys_prompt + ("\nGiữ giọng tự nhiên." if code_mode else "\nGiữ giọng tự nhiên, 1–4 câu, <350 từ.")}]
    msgs.extend({"role":r,"content":c} for r,c in conv)
    msgs.append({"role":"user","content": user_text})
    return msgs

def stream_worker(messages, out_q: "queue.Queue[str]", max_tokens):
    try:
        stream = client.chat.completions.create(
            model=MODEL,
            stream=True,
            max_tokens=max_tokens,
            temperature=0.7,
            messages=messages
        )
        for chunk in stream:
            delta = chunk.choices[0].delta.content or ""
            if delta: out_q.put(delta)
    except Exception as e:
        out_q.put(f"\n[stream_error] {type(e).__name__}: {e}")
    finally:
        out_q.put(None)

async def call_stream(messages, max_tokens):
    out_q = queue.Queue()
    t = threading.Thread(target=stream_worker, args=(messages, out_q, max_tokens), daemon=True)
    t.start()
    loop = asyncio.get_event_loop()
    while True:
        part = await loop.run_in_executor(None, out_q.get)
        if part is None: break
        yield part

def complete_block(messages, max_tokens):
    cmp = client.chat.completions.create(
        model=MODEL,
        stream=False,
        max_tokens=max_tokens,
        temperature=0.7,
        messages=messages
    )
    return (cmp.choices[0].message.content or "").strip()

def fetch_text_from_url(url):
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    ct = r.headers.get("content-type","").lower()
    if "text" in ct or "json" in ct or "xml" in ct or "csv" in ct:
        return r.text
    try:
        return r.content.decode("utf-8", errors="ignore")
    except:
        return ""

async def get_document_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not doc: return None, None
    if doc.file_size and doc.file_size > MAX_DOC_BYTES:
        return None, f"Tệp quá lớn ({doc.file_size} bytes). Giới hạn ~{MAX_DOC_BYTES} bytes."
    f = await context.bot.get_file(doc.file_id)
    url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{f.file_path}"
    try:
        r = requests.get(url, timeout=60)
        r.raise_for_status()
        data = r.content if not r.encoding else r.text.encode(r.encoding)
        if len(data) > MAX_DOC_BYTES:
            return None, f"Tệp quá lớn sau tải ({len(data)} bytes)."
        try:
            text = data.decode("utf-8")
        except:
            try:
                text = data.decode("latin-1")
            except:
                text = ""
        return text, None
    except Exception as e:
        return None, f"Lỗi tải tệp: {e}"

def geocode_vn(q):
    r = requests.get(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={"name": q, "count": 1, "language": "vi", "format": "json", "country_code": "VN"},
        timeout=20
    )
    r.raise_for_status()
    data = r.json()
    if not data.get("results"): return None
    it = data["results"][0]
    return {"name": it["name"], "lat": it["latitude"], "lon": it["longitude"], "admin1": it.get("admin1",""), "country": it.get("country","")}

def weather_vn(q):
    g = geocode_vn(q)
    if not g: return None, "Không tìm thấy địa danh ở Việt Nam."
    params = {
        "latitude": g["lat"], "longitude": g["lon"],
        "current": "temperature_2m,relative_humidity_2m,precipitation",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max",
        "timezone": "Asia/Ho_Chi_Minh"
    }
    r = requests.get("https://api.open-meteo.com/v1/forecast", params=params, timeout=20)
    r.raise_for_status()
    j = r.json()
    cur = j.get("current", {})
    daily = j.get("daily", {})
    name = g["name"] + (f", {g['admin1']}" if g.get("admin1") else "")
    t = cur.get("temperature_2m"); rh = cur.get("relative_humidity_2m"); p = cur.get("precipitation")
    tmax0 = daily.get("temperature_2m_max",[None])[0]; tmin0 = daily.get("temperature_2m_min",[None])[0]
    rain0 = daily.get("precipitation_sum",[None])[0]; prob0 = daily.get("precipitation_probability_max",[None])[0]
    tmax1 = daily.get("temperature_2m_max",[None, None])[1]; tmin1 = daily.get("temperature_2m_min",[None, None])[1]
    rain1 = daily.get("precipitation_sum",[None, None])[1]; prob1 = daily.get("precipitation_probability_max",[None, None])[1]
    icon = "☀️"
    if (prob0 or 0) >= 70 or (rain0 or 0) >= 5: icon = "🌧️"
    elif (prob0 or 0) >= 30: icon = "🌦️"
    elif (t or 0) >= 33: icon = "🥵"
    txt = (
        f"{icon} Thời tiết {name}\n"
        f"Hiện tại: {t}°C, ẩm {rh}% ; mưa {p} mm\n"
        f"Hôm nay: {tmin0}–{tmax0}°C, mưa ~{rain0} mm, xác suất {prob0}%\n"
        f"Ngày mai: {tmin1}–{tmax1}°C, mưa ~{rain1} mm, xác suất {prob1}%"
    )
    return g, txt

def try_weather_from_text(text):
    t = (text or "").lower()
    if "thời tiết" not in t: return None
    known = ["hà nội","hn","ha noi","hồ chí minh","tp.hcm","tphcm","sài gòn","đà nẵng","hải phòng","cần thơ","nha trang","đà lạt","huế","quy nhơn","vũng tàu","hạ long","phú quốc","biên hòa","thủ đức"]
    for k in known:
        if k in t: return k
    return "Hà Nội"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if allowed_chat(update): await update.message.reply_text("Em là Linh đây ✨ cứ nhắn là tám nha!")

async def cmd_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if allowed_chat(update): await update.message.reply_text(f"Gateway: Vercel AI\nModel: {MODEL}\nContext turns: {CTX_TURNS}\nCode: không giới hạn (chia phần gửi)")

async def cmd_clean(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if allowed_chat(update):
        b=cleanup_disk()
        await update.message.reply_text(f"Đã dọn xong ~{round(b/1024/1024,2)} MB. ✅")

async def cmd_weather(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed_chat(update): return
    place = " ".join(context.args).strip() or "Hà Nội"
    try:
        _, text = weather_vn(place)
        await update.message.reply_text(text)
    except Exception as e:
        notify_discord("weather_error", {"error": str(e)})
        await update.message.reply_text("Lấy thời tiết bị lỗi, thử tên khác giúp mình nhé.")

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed_chat(update): return
    chat_id = update.effective_chat.id
    q = update.message.text or ""
    if asked_creator(q):
        await update.message.reply_text("Tuấn Anh đẹp trai"); return

    wplace = try_weather_from_text(q)
    if wplace:
        try:
            _, text = weather_vn(wplace)
            await update.message.reply_text(text); return
        except Exception as e:
            notify_discord("weather_error", {"error": str(e)})

    code_mode = is_codey(q)
    async with locks[chat_id]:
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        try:
            messages = build_messages(chat_id, q, code_mode=code_mode)
            if code_mode:
                text = complete_block(messages, MAX_TOKENS_CODE)
                if not text: text = "Không nhận được phản hồi."
                await send_long_text(context, chat_id, text)
                histories[chat_id].append(("user", q))
                histories[chat_id].append(("assistant", text[:1000]))
                return

            msg = await update.message.reply_text("…")
            acc, last_edit = "", time.monotonic()
            async for chunk in call_stream(messages, MAX_TOKENS):
                acc += chunk
                now = time.monotonic()
                if now - last_edit >= 0.5 or "\n" in chunk:
                    txt = word_clamp(strip_code(acc), WORD_LIMIT) or "…"
                    try:
                        await msg.edit_text(txt, disable_web_page_preview=True)
                        last_edit = now
                    except: pass
            final_txt = word_clamp(strip_code(acc), WORD_LIMIT) or "Em bị lag mất rồi, nhắn lại giúp em nha."
            try: await msg.edit_text(final_txt, disable_web_page_preview=True)
            except: await update.message.reply_text(final_txt, disable_web_page_preview=True)
            histories[chat_id].append(("user", q))
            histories[chat_id].append(("assistant", final_txt))
        except Exception as e:
            notify_discord("gateway_stream_error", {"error": str(e), "trace": traceback.format_exc()})
            await update.message.reply_text("Có lỗi kết nối, thử lại giúp em nhé.")

async def on_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed_chat(update): return
    chat_id = update.effective_chat.id
    async with locks[chat_id]:
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        try:
            text, err = await get_document_text(update, context)
            if err:
                await update.message.reply_text(err); return
            if not text or not text.strip():
                await update.message.reply_text("Không đọc được nội dung tệp (có thể là nhị phân)."); return

            prompt = (
                "Phân tích tệp mã nguồn dưới đây: chỉ ra lỗi tiềm ẩn, bug, vấn đề hiệu năng/bảo mật, style, và đề xuất cải thiện.\n"
                "Nếu hợp lý, đưa luôn bản vá dạng unified diff hoặc code đã sửa.\n\n"
                "=== NỘI DUNG TỆP ===\n" + text[:MAX_DOC_BYTES].rstrip()
            )
            messages = [{"role":"system","content": SYSTEM_PROMPT_CODE},{"role":"user","content": prompt}]
            result = complete_block(messages, MAX_TOKENS_CODE)
            if not result: result = "Không nhận được phản hồi."
            await send_long_text(context, chat_id, result)
            histories[chat_id].append(("user", "[tệp đính kèm]"))
            histories[chat_id].append(("assistant", result[:1000]))
        except Exception as e:
            notify_discord("doc_analyze_error", {"error": str(e), "trace": traceback.format_exc()})
            await update.message.reply_text("Phân tích tệp bị lỗi, thử lại giúp mình nhé.")

def main():
    if not BOT_TOKEN or not VERCEL_API_KEY:
        raise RuntimeError("Thiếu BOT_TOKEN hoặc VERCEL_API_KEY")
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=8080), daemon=True).start()
    threading.Thread(target=auto_ping, daemon=True).start()
    threading.Thread(target=cleanup_loop, daemon=True).start()
    app_tg = ApplicationBuilder().token(BOT_TOKEN).build()
    targets = [int(s) for s in REMIND_CHAT_IDS if s] or ([ALLOWED_CHAT_ID] if ALLOWED_CHAT_ID else [])
    if targets: threading.Thread(target=reminder_loop, args=(app_tg.bot, targets), daemon=True).start()
    app_tg.add_handler(CommandHandler("start", start))
    app_tg.add_handler(CommandHandler("model", cmd_model))
    app_tg.add_handler(CommandHandler("clean", cmd_clean))
    app_tg.add_handler(CommandHandler("weather", cmd_weather))
    app_tg.add_handler(MessageHandler(filters.Document.ALL, on_document))
    app_tg.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app_tg.run_polling()

if __name__ == "__main__":
    main()
