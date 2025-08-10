import os, re, json, time, threading, shutil, sys, traceback, asyncio, queue, requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from collections import deque, defaultdict
from flask import Flask
from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters, CommandHandler
from openai import OpenAI

# ========= ENV =========
BOT_TOKEN = os.environ["BOT_TOKEN"]
VERCEL_API_KEY = os.environ["VERCEL_API_KEY"]
BASE_URL = os.getenv("BASE_URL", "https://ai-gateway.vercel.sh/v1")
MODEL = os.getenv("MODEL", "alibaba/qwen-3-235b")

SYSTEM_PROMPT = os.getenv("SYSTEM_PROMPT",
    "Bạn là Linh – mồm mép, bộc trực, thông minh kiểu Grok: nhanh trí, châm biếm duyên dáng, thỉnh thoảng cà khịa nhẹ. "
    "Giọng tự nhiên, ưu tiên ngắn gọn, sắc sảo; luôn hữu ích và chính xác."
)
SYSTEM_PROMPT_CODE = os.getenv("SYSTEM_PROMPT_CODE",
    "Bạn là lập trình viên kỳ cựu. Viết code đầy đủ, sạch, best practice. Không giới hạn độ dài; nếu dài, cứ trả hết."
)

WORD_LIMIT = int(os.getenv("WORD_LIMIT", "350"))
SELF_PING_URL = os.getenv("SELF_PING_URL", "").strip()
ALLOWED_CHAT_ID = int(os.getenv("ALLOWED_CHAT_ID", "0"))   # 0 = mọi group
ALLOWED_TOPIC_ID = int(os.getenv("ALLOWED_TOPIC_ID", "0")) # 0 = mọi topic
OWNER_ID = 2026797305

REMIND_CHAT_IDS = [s.strip() for s in os.getenv("REMIND_CHAT_IDS", "").split(",") if s.strip()]
REMIND_TEXT = os.getenv("REMIND_TEXT", "23h rồi đó, ngủ sớm cho khoẻ nha 🌙")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
CLEAN_INTERVAL_HOURS = int(os.getenv("CLEAN_INTERVAL_HOURS", "6"))

MAX_TOKENS = int(os.getenv("MAX_TOKENS", "700"))
MAX_TOKENS_CODE = int(os.getenv("MAX_TOKENS_CODE", "4000"))
CTX_TURNS = int(os.getenv("CTX_TURNS", "7"))
MAX_DOC_BYTES = int(os.getenv("MAX_DOC_BYTES", str(2 * 1024 * 1024)))

# Giới hạn hiển thị & tạo trang
EDIT_INTERVAL = float(os.getenv("EDIT_INTERVAL", "1.0"))
MAX_EDITS = int(os.getenv("MAX_EDITS", "60"))
PAGE_CHARS = int(os.getenv("PAGE_CHARS", "3200"))  # mỗi trang

client = OpenAI(api_key=VERCEL_API_KEY, base_url=BASE_URL)
app = Flask(__name__)

histories = defaultdict(lambda: deque(maxlen=32))
locks = defaultdict(asyncio.Lock)

# ========= Utils =========
def log_console(tag, payload):
    try: print(f"[{datetime.utcnow().isoformat()}][{tag}] {json.dumps(payload, ensure_ascii=False)}")
    except Exception: print(f"[{datetime.utcnow().isoformat()}][{tag}] {payload}")
    sys.stdout.flush()

def notify_discord(title, payload):
    if DISCORD_WEBHOOK_URL:
        try:
            text = f"**{title}**\n```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}```"
            requests.post(DISCORD_WEBHOOK_URL, json={"content": text}, timeout=15)
        except Exception: pass
    log_console(title, payload)

def strip_code(s):  # bỏ fence ```
    return re.sub(r"```[\w-]*\n|\n```", "", s or "", flags=re.S).strip()

def word_clamp(s, limit):
    w=(s or "").split()
    return s if len(w)<=limit else " ".join(w[:limit])+"…"

def html(s):  # escape đơn giản cho HTML parse_mode
    return (s or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

def chunk_pages(raw: str, per_page: int = PAGE_CHARS) -> list[str]:
    lines = (raw or "").splitlines()
    pages, cur, used = [], [], 0
    for line in lines:
        add = len(line) + 1
        if used + add > per_page and cur:
            pages.append("\n".join(cur)); cur=[line]; used=add
        else:
            cur.append(line); used += add
    if cur: pages.append("\n".join(cur))
    return pages

async def send_pages(ctx, chat_id: int, header: str, raw: str, *, is_code=False, lang_hint="", thread_id=None):
    """Gửi nhiều tin nhắn mới theo trang."""
    raw = raw.rstrip()
    pages = chunk_pages(raw, PAGE_CHARS) if len(raw) > PAGE_CHARS else [raw]
    total = len(pages)
    for i, p in enumerate(pages, 1):
        title = f"{header} — Phần {i}/{total}" if total > 1 else header
        if is_code:
            # dùng parse_mode=None để giữ nguyên fence
            await ctx.bot.send_message(chat_id, f"<b>{title}</b>", message_thread_id=thread_id, parse_mode=ParseMode.HTML)
            await ctx.bot.send_message(chat_id, f"```{lang_hint}\n{p}\n```", message_thread_id=thread_id, parse_mode=None)
        else:
            await ctx.bot.send_message(chat_id, f"<b>{title}</b>\n{html(p)}", message_thread_id=thread_id, parse_mode=ParseMode.HTML)

def asked_creator(text):
    t=(text or "").lower()
    return any(k in t for k in ["ai tạo","người tạo","ai làm ra","người làm ra","tác giả","dev của bạn"])

def is_codey(text):
    if not text: return False
    t = text.lower()
    keys = ["viết code","code giúp","sửa code","bug","lỗi","stack trace","exception",
        "python","java","kotlin","swift","dart","flutter","go","rust","c++","c#","php","ruby",
        "js","ts","typescript","node","react","vue","svelte","angular","next.js","nuxt",
        "`","```","import ","class ","def ","function","const ","let ","var "]
    return any(k in t for k in keys)

def thread_id_of(update: Update):  # topic id (forum)
    msg = update.effective_message
    return getattr(msg, "message_thread_id", None)

def allowed_chat(update: Update):
    chat = update.effective_chat
    if not chat: return False
    if chat.type == "private":
        return update.effective_user and update.effective_user.id == OWNER_ID
    if chat.type in ("group","supergroup"):
        if ALLOWED_CHAT_ID and chat.id != ALLOWED_CHAT_ID: return False
        if ALLOWED_TOPIC_ID:
            return (thread_id_of(update) or 0) == ALLOWED_TOPIC_ID
        return True
    return False

# ========= Keepalive =========
@app.get("/")
def root_ok(): return "OK"
@app.get("/health")
def health_ok(): return "OK"

def auto_ping():
    while True:
        if SELF_PING_URL:
            try: requests.head(SELF_PING_URL, timeout=10)
            except Exception: pass
        time.sleep(45)

def cleanup_disk():
    freed=0
    for p in ["/home/runner/.cache","/home/runner/.npm","/tmp"]:
        try:
            if os.path.exists(p):
                size=sum(os.path.getsize(os.path.join(dp,f)) for dp,_,fs in os.walk(p) for f in fs)
                shutil.rmtree(p, ignore_errors=True); freed+=size
        except Exception: pass
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

# ========= LLM =========
def build_messages(chat_id, user_text, code_mode=False):
    keep = max(2, CTX_TURNS * 2)
    conv = list(histories[chat_id])[-keep:]
    sys_prompt = SYSTEM_PROMPT_CODE if code_mode else SYSTEM_PROMPT
    tail = "\nGiữ giọng tự nhiên." if code_mode else "\nGiữ giọng tự nhiên, 1–4 câu, <350 từ."
    msgs = [{"role":"system","content": sys_prompt + tail}]
    msgs.extend({"role":r,"content":c} for r,c in conv)
    msgs.append({"role":"user","content": user_text})
    return msgs

def complete_block(messages, max_tokens):
    cmp = client.chat.completions.create(
        model=MODEL, stream=False, max_tokens=max_tokens, temperature=0.7, messages=messages
    )
    return (cmp.choices[0].message.content or "").strip()

# ========= Weather & Files =========
async def get_document_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not doc: return None, None
    if doc.file_size and doc.file_size > MAX_DOC_BYTES:
        return None, f"Tệp quá lớn ({doc.file_size} bytes). Giới hạn ~{MAX_DOC_BYTES} bytes."
    f = await context.bot.get_file(doc.file_id)
    url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{f.file_path}"
    try:
        r = requests.get(url, timeout=60); r.raise_for_status()
        data = r.content if not r.encoding else r.text.encode(r.encoding)
        if len(data) > MAX_DOC_BYTES: return None, f"Tệp quá lớn sau tải ({len(data)} bytes)."
        try: text = data.decode("utf-8")
        except Exception:
            try: text = data.decode("latin-1")
            except Exception: text = ""
        return text, None
    except Exception as e:
        return None, f"Lỗi tải tệp: {e}"

def geocode_vn(q):
    r = requests.get("https://geocoding-api.open-meteo.com/v1/search",
                     params={"name": q, "count": 1, "language": "vi", "format": "json", "country_code": "VN"},
                     timeout=20)
    r.raise_for_status(); data = r.json()
    if not data.get("results"): return None
    it = data["results"][0]
    return {"name": it["name"], "lat": it["latitude"], "lon": it["longitude"], "admin1": it.get("admin1","")}

def weather_vn(q):
    g = geocode_vn(q)
    if not g: return None, "Không tìm thấy địa danh ở Việt Nam."
    params = {"latitude": g["lat"], "longitude": g["lon"],
              "current": "temperature_2m,relative_humidity_2m,precipitation",
              "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max",
              "timezone": "Asia/Ho_Chi_Minh"}
    r = requests.get("https://api.open-meteo.com/v1/forecast", params=params, timeout=20); r.raise_for_status()
    j = r.json(); cur = j.get("current", {}); daily = j.get("daily", {})
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
    txt = (f"{icon} Thời tiết {name}\n"
           f"Hiện tại: {t}°C, ẩm {rh}% ; mưa {p} mm\n"
           f"Hôm nay: {tmin0}–{tmax0}°C, mưa ~{rain0} mm, xác suất {prob0}%\n"
           f"Ngày mai: {tmin1}–{tmax1}°C, mưa ~{rain1} mm, xác suất {prob1}%")
    return g, txt

def try_weather_from_text(text):
    t = (text or "").lower()
    if "thời tiết" not in t: return None
    known = ["hà nội","hn","ha noi","hồ chí minh","tp.hcm","tphcm","sài gòn","đà nẵng","hải phòng",
             "cần thơ","nha trang","đà lạt","huế","quy nhơn","vũng tàu","hạ long","phú quốc","biên hòa","thủ đức"]
    for k in known:
        if k in t: return k
    return "Hà Nội"

# ========= Commands =========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if allowed_chat(update):
        await update.message.reply_text("<b>Em là Linh đây ✨</b>\nCứ nhắn là tám nha!", parse_mode=ParseMode.HTML)

async def cmd_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if allowed_chat(update):
        await update.message.reply_text(
            f"<b>Gateway:</b> Vercel AI\n<b>Model:</b> {MODEL}\n"
            f"<b>Context turns:</b> {CTX_TURNS}\n<b>Page size:</b> {PAGE_CHARS} ký tự",
            parse_mode=ParseMode.HTML
        )

async def cmd_clean(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if allowed_chat(update):
        b=cleanup_disk()
        await update.message.reply_text(f"Đã dọn xong ~<b>{round(b/1024/1024,2)}</b> MB. ✅", parse_mode=ParseMode.HTML)

async def cmd_set(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global ALLOWED_CHAT_ID, ALLOWED_TOPIC_ID
    if not update.effective_user or update.effective_user.id != OWNER_ID:
        await update.message.reply_text("⛔ Bạn không có quyền dùng lệnh này."); return
    if not context.args:
        await update.message.reply_text("Dùng: /set <chat_id> [topic_id]"); return
    try:
        chat_id = int(context.args[0]); topic_id = int(context.args[1]) if len(context.args)>1 else 0
    except ValueError:
        await update.message.reply_text("ID phải là số."); return
    ALLOWED_CHAT_ID, ALLOWED_TOPIC_ID = chat_id, topic_id
    await update.message.reply_text(f"✅ Đã set group={chat_id}, topic={topic_id or 'none'}")

async def cmd_weather(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed_chat(update): return
    place = " ".join(context.args).strip() or "Hà Nội"
    try:
        _, text = weather_vn(place)
        await update.message.reply_text(html(text), parse_mode=ParseMode.HTML)
    except Exception as e:
        notify_discord("weather_error", {"error": str(e)})
        await update.message.reply_text("Lấy thời tiết bị lỗi, thử tên khác giúp mình nhé.")

# ========= Text =========
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed_chat(update): return
    chat_id = update.effective_chat.id
    thread_id = thread_id_of(update)
    q = update.message.text or ""
    if asked_creator(q):
        await update.message.reply_text("Tuấn Anh đẹp trai"); return

    wplace = try_weather_from_text(q)
    if wplace:
        try:
            _, text = weather_vn(wplace)
            await update.message.reply_text(html(text), parse_mode=ParseMode.HTML); return
        except Exception as e:
            notify_discord("weather_error", {"error": str(e)})

    code_mode = is_codey(q)

    async with locks[chat_id]:
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING, message_thread_id=thread_id)
        try:
            # CODE MODE: lấy full rồi chia trang, gửi nhiều tin nhắn mới
            if code_mode:
                messages = build_messages(chat_id, q, code_mode=True)
                result = complete_block(messages, MAX_TOKENS_CODE) or "Không nhận được phản hồi."

                # Nếu model từ chối vì nội dung trước đó -> reset history 1 lần rồi thử lại
                if "can't comply" in result.lower() or "cannot help" in result.lower():
                    histories[chat_id].clear()
                    result = complete_block(build_messages(chat_id, q, code_mode=True), MAX_TOKENS_CODE) or result

                m = re.search(r"```(\w+)?\n(.*?)```", result, flags=re.S)
                if m:
                    lang = (m.group(1) or "").strip()
                    code = m.group(2).rstrip()
                    before = result[:m.start()].strip()
                    after  = result[m.end():].strip()
                    if before: await send_pages(context, chat_id, "📝 Mô tả", before, is_code=False, thread_id=thread_id)
                    await send_pages(context, chat_id, "💻 Code", code, is_code=True, lang_hint=lang, thread_id=thread_id)
                    if after: await send_pages(context, chat_id, "📝 Giải thích", after, is_code=False, thread_id=thread_id)
                else:
                    await send_pages(context, chat_id, "💻 Code / Nội dung", result, is_code=True, lang_hint="", thread_id=thread_id)

                histories[chat_id].append(("user", q))
                histories[chat_id].append(("assistant", strip_code(result)[:1000]))
                return

            # CHAT THƯỜNG: stream nhẹ -> nếu dài thì chuyển sang gửi theo trang
            messages = build_messages(chat_id, q, code_mode=False)
            msg = await update.message.reply_text("…")
            acc, last_edit, edits = "", time.monotonic(), 0
            buffer_all = ""

            out_q = queue.Queue()
            def _worker():
                try:
                    stream = client.chat.completions.create(
                        model=MODEL, stream=True, max_tokens=MAX_TOKENS, temperature=0.7, messages=messages
                    )
                    for chunk in stream:
                        delta = chunk.choices[0].delta.content or ""
                        if delta: out_q.put(delta)
                except Exception as e:
                    out_q.put(f"\n[stream_error] {type(e).__name__}: {e}")
                finally:
                    out_q.put(None)

            threading.Thread(target=_worker, daemon=True).start()
            loop = asyncio.get_event_loop()
            while True:
                part = await loop.run_in_executor(None, out_q.get)
                if part is None: break
                acc += part; buffer_all += part
                now = time.monotonic()
                if (now - last_edit) >= EDIT_INTERVAL and edits < MAX_EDITS:
                    tmp = word_clamp(strip_code(acc), WORD_LIMIT) or "…"
                    try:
                        await msg.edit_text(f"<b>Tóm tắt</b>\n{html(tmp)}", parse_mode=ParseMode.HTML)
                        last_edit = now; edits += 1
                    except Exception: pass

            final_plain = strip_code(buffer_all).rstrip()
            if len(final_plain) > PAGE_CHARS:
                try: await msg.delete()
                except Exception: pass
                await send_pages(context, chat_id, "💬 Trả lời", final_plain, is_code=False, thread_id=thread_id)
            else:
                txt = word_clamp(final_plain, WORD_LIMIT) or "Em bị lag mất rồi, nhắn lại giúp em nha."
                try: await msg.edit_text(f"<b>💬 Trả lời</b>\n{html(txt)}", parse_mode=ParseMode.HTML)
                except Exception: await update.message.reply_text(f"<b>💬 Trả lời</b>\n{html(txt)}", parse_mode=ParseMode.HTML)

            histories[chat_id].append(("user", q))
            histories[chat_id].append(("assistant", final_plain[:1000]))

        except Exception as e:
            notify_discord("gateway_error", {"error": str(e), "trace": traceback.format_exc()})
            await update.message.reply_text("Có lỗi kết nối, thử lại giúp em nhé.")

# ========= Documents =========
async def on_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed_chat(update): return
    chat_id = update.effective_chat.id
    thread_id = thread_id_of(update)
    async with locks[chat_id]:
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING, message_thread_id=thread_id)
        try:
            text, err = await get_document_text(update, context)
            if err: await update.message.reply_text(html(err), parse_mode=ParseMode.HTML); return
            if not text.strip():
                await update.message.reply_text("Không đọc được nội dung tệp (có thể là nhị phân)."); return

            prompt = ("Phân tích tệp mã nguồn dưới đây: liệt kê lỗi, hiệu năng/bảo mật, style, đề xuất cải thiện. "
                      "Nếu hợp lý, đưa bản vá (diff) hoặc code đã sửa.\n\n=== NỘI DUNG TỆP ===\n" + text[:MAX_DOC_BYTES].rstrip())
            messages = [{"role":"system","content": SYSTEM_PROMPT_CODE},{"role":"user","content": prompt}]
            result = complete_block(messages, MAX_TOKENS_CODE) or "Không nhận được phản hồi."

            m = re.search(r"```(\w+)?\n(.*?)```", result, flags=re.S)
            if m:
                lang = (m.group(1) or "")
                code = m.group(2).rstrip()
                before = result[:m.start()].strip()
                after  = result[m.end():].strip()
                if before: await send_pages(context, chat_id, "🔎 Phân tích", before, is_code=False, thread_id=thread_id)
                await send_pages(context, chat_id, "💻 Bản vá / Ví dụ", code, is_code=True, lang_hint=lang, thread_id=thread_id)
                if after: await send_pages(context, chat_id, "📝 Nhận xét", after, is_code=False, thread_id=thread_id)
            else:
                await send_pages(context, chat_id, "🔎 Phân tích", result, is_code=False, thread_id=thread_id)

            histories[chat_id].append(("user", "[tệp đính kèm]"))
            histories[chat_id].append(("assistant", strip_code(result)[:1000]))
        except Exception as e:
            notify_discord("doc_analyze_error", {"error": str(e), "trace": traceback.format_exc()})
            await update.message.reply_text("Phân tích tệp bị lỗi, thử lại giúp mình nhé.")

# ========= Boot =========
def main():
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=8080), daemon=True).start()
    threading.Thread(target=auto_ping, daemon=True).start()
    threading.Thread(target=cleanup_loop, daemon=True).start()

    app_tg = ApplicationBuilder().token(BOT_TOKEN).build()
    targets = [int(s) for s in REMIND_CHAT_IDS if s] or ([ALLOWED_CHAT_ID] if ALLOWED_CHAT_ID else [])
    if targets: threading.Thread(target=reminder_loop, args=(app_tg.bot, targets), daemon=True).start()

    app_tg.add_handler(CommandHandler("start", start))
    app_tg.add_handler(CommandHandler("model", cmd_model))
    app_tg.add_handler(CommandHandler("clean", cmd_clean))
    app_tg.add_handler(CommandHandler("set", cmd_set))     # chỉ OWNER_ID dùng
    app_tg.add_handler(CommandHandler("weather", cmd_weather))
    app_tg.add_handler(MessageHandler(filters.Document.ALL, on_document))
    app_tg.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app_tg.run_polling()

if __name__ == "__main__":
    main()
