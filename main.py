import os, re, json, threading, asyncio, io, time, gc
from collections import deque, defaultdict
from html import escape as htmlesc
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction, ParseMode
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters, CommandHandler, CallbackQueryHandler
from telegram.error import BadRequest, Forbidden
from openai import OpenAI

try:
    from google import genai
    from google.genai import types
except Exception:
    genai = None
    types = None

try:
    import chardet
except Exception:
    chardet = None
try:
    import PyPDF2
except Exception:
    PyPDF2 = None
try:
    import docx
    from docx import Document as DocxDocument
except Exception:
    docx = None
    DocxDocument = None
try:
    import openpyxl
except Exception:
    openpyxl = None
try:
    from pptx import Presentation
except Exception:
    Presentation = None
try:
    from bs4 import BeautifulSoup
except Exception:
    BeautifulSoup = None

BOT_TOKEN = os.environ["BOT_TOKEN"]
VERCEL_API_KEY = os.environ.get("VERCEL_API_KEY", "")
BASE_URL = os.getenv("BASE_URL", "https://ai-gateway.vercel.sh/v1")
CHAT_MODEL = os.getenv("CHAT_MODEL", "anthropic/claude-3.5-haiku")
CODE_MODEL = os.getenv("CODE_MODEL", "anthropic/claude-4-opus")
FILE_MODEL = os.getenv("FILE_MODEL", "anthropic/claude-4-sonnet")
ADMIN_ID = int(os.getenv("ADMIN_ID", "2026797305"))

PAGE_CHARS = int(os.getenv("PAGE_CHARS", "3200"))
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "900"))
MAX_TOKENS_CODE = int(os.getenv("MAX_TOKENS_CODE", "4000"))
MAX_TOKENS_FILE = int(os.getenv("MAX_TOKENS_FILE", "160000"))
CTX_TURNS = int(os.getenv("CTX_TURNS", "7"))

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_IMAGE_MODEL = os.getenv("GEMINI_IMAGE_MODEL", "gemini-2.0-flash-preview-image-generation")

MAX_EMIT_CHARS = int(os.getenv("MAX_EMIT_CHARS", "800000"))
CHUNK_CHARS = int(os.getenv("CHUNK_CHARS", "180000"))

INACTIVE_SECS = int(os.getenv("INACTIVE_SECS", "900"))
MAX_PAGERS = int(os.getenv("MAX_PAGERS", "2000"))
GC_EVERY = int(os.getenv("GC_EVERY", "10"))

ARCHIVES = (".zip",".rar",".7z",".tar",".tar.gz",".tgz",".tar.bz2",".tar.xz")
TEXT_LIKE = (".txt",".md",".log",".csv",".tsv",".json",".yaml",".yml",".ini",".cfg",".env",".xml",".html",".htm",
             ".py",".js",".ts",".java",".c",".cpp",".cs",".go",".php",".rb",".rs",".sh",".bat",".ps1",".sql")

client = OpenAI(api_key=VERCEL_API_KEY, base_url=BASE_URL) if VERCEL_API_KEY else None
app = Flask(__name__)
histories = defaultdict(lambda: deque(maxlen=32))
locks = defaultdict(asyncio.Lock)
PAGERS = {}
LAST_DOC = {}
LAST_SEEN = defaultdict(lambda: time.time())
REQ_COUNT = 0

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
    return None if total<=1 else InlineKeyboardMarkup(
        [[InlineKeyboardButton("⏪", callback_data="pg_prev"),
          InlineKeyboardButton(f"{idx+1}/{total}", callback_data="pg_stay"),
          InlineKeyboardButton("⏩", callback_data="pg_next")]]
    )

def page_payload(p):
    txt=p["pages"][p["idx"]]
    return (f"```{p['lang']}\n{txt}\n```", ParseMode.MARKDOWN) if p["is_code"] else (htmlesc(txt), ParseMode.HTML)

async def send_or_update(ctx, chat_id, msg, p):
    text,mode = page_payload(p); keyboard = kb(p["idx"], len(p["pages"]))
    try:
        if msg:
            await msg.edit_text(text, parse_mode=mode, reply_markup=keyboard)
        else:
            m = await ctx.bot.send_message(chat_id, text, parse_mode=mode, reply_markup=keyboard)
            PAGERS[(m.chat_id, m.message_id)] = p
    except BadRequest:
        p["is_code"]=True
        text,mode = page_payload(p)
        if msg:
            await msg.edit_text(text, parse_mode=mode, reply_markup=keyboard)
        else:
            m = await ctx.bot.send_message(chat_id, text, parse_mode=mode, reply_markup=keyboard)
            PAGERS[(m.chat_id, m.message_id)] = p

async def start_pager(ctx, chat_id, raw, is_code=False, lang_hint=""):
    pages = chunk_pages(raw)
    await send_or_update(ctx, chat_id, None, {"pages": pages, "is_code": is_code, "lang": lang_hint or "", "idx": 0, "ts": time.time()})

async def on_page_nav(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q: return
    touch(q.message.chat_id)
    key=(q.message.chat_id, q.message.message_id); p=PAGERS.get(key)
    if not p: return await q.answer("Hết phiên.")
    if q.data=="pg_prev" and p["idx"]>0: p["idx"]-=1
    elif q.data=="pg_next" and p["idx"]<len(p["pages"])-1: p["idx"]+=1
    else: return await q.answer()
    await send_or_update(context, q.message.chat_id, q.message, p); await q.answer()
    maybe_gc()

def build_messages(cid, user_text, sys_prompt):
    msgs=[{"role":"system","content":sys_prompt}]
    keep=max(2, CTX_TURNS*2)
    msgs += [{"role":"user" if r=="user" else "assistant","content":c} for r,c in list(histories[cid])[-keep:]]
    msgs.append({"role":"user","content":user_text})
    return msgs

def sys_prompt_linh():
    return ("Bạn tên là Linh. Nói chuyện tự nhiên như người Việt, ngắn gọn, thẳng, có cảm xúc; "
            "cho phép văng tục nhẹ khi hợp ngữ cảnh, không thù hằn và không công kích cá nhân. "
            "Không nịnh bợ, không vòng vo. Tập trung ý chính."
            "Và được tạo bởi Hoàng Tuấn Anh(@cuodoivandep).")

def complete_with_model(model, messages, max_tokens, temperature=0.7):
    if not client:
        return "Thiếu VERCEL_API_KEY."
    res = client.chat.completions.create(model=model, max_tokens=max_tokens, temperature=temperature, messages=messages)
    return (res.choices[0].message.content or "").strip()

def is_archive(name: str):
    n=(name or "").lower()
    return n.endswith(ARCHIVES)

def detect_decode(data: bytes):
    if not data: return ""
    if chardet:
        enc = (chardet.detect(data) or {}).get("encoding") or "utf-8"
        try:
            return data.decode(enc, errors="ignore")
        except Exception:
            pass
    try:
        return data.decode("utf-8", errors="ignore")
    except Exception:
        return data.decode("latin-1", errors="ignore")

def read_any_file(name: str, data: bytes):
    n=(name or "").lower()
    if is_archive(n):
        return None, "archive"
    if any(n.endswith(ext) for ext in TEXT_LIKE):
        raw = detect_decode(data)
        if n.endswith((".html",".htm")) and BeautifulSoup:
            soup = BeautifulSoup(raw, "html.parser")
            raw = soup.get_text(separator="\n")
        return raw, "text"
    if n.endswith(".pdf"):
        if not PyPDF2: return "Không có PyPDF2 để đọc PDF.", "error"
        buf = io.BytesIO(data); r = PyPDF2.PdfReader(buf)
        parts=[]
        for i in range(min(len(r.pages), 200)):
            try: parts.append(r.pages[i].extract_text() or "")
            except Exception: parts.append("")
        return "\n".join(parts), "text"
    if n.endswith((".docx",".doc")):
        if not docx: return "Không có python-docx để đọc DOCX.", "error"
        if n.endswith(".doc"):
            return "Không hỗ trợ .doc, hãy chuyển sang .docx.", "error"
        buf = io.BytesIO(data); d = docx.Document(buf)
        parts=[p.text for p in d.paragraphs]
        for t in d.tables:
            for row in t.rows:
                parts.append("\t".join(cell.text for cell in row.cells))
        return "\n".join(parts), "text"
    if n.endswith((".xlsx",".xlsm",".xltx",".xltm",".xls")):
        if not openpyxl: return "Không có openpyxl để đọc Excel.", "error"
        buf = io.BytesIO(data); wb = openpyxl.load_workbook(buf, read_only=True, data_only=True)
        out=[]
        for ws in wb.worksheets[:12]:
            out.append(f"# Sheet: {ws.title}")
            for row in ws.iter_rows(values_only=True):
                vals=[("" if v is None else str(v)) for v in row]
                out.append("\t".join(vals))
        return "\n".join(out), "text"
    if n.endswith(".pptx"):
        if not Presentation: return "Không có python-pptx để đọc PPTX.", "error"
        buf = io.BytesIO(data); prs = Presentation(buf)
        parts=[]
        for i, slide in enumerate(prs.slides[:300]):
            parts.append(f"# Slide {i+1}")
            for shape in slide.shapes:
                if hasattr(shape, "text"): parts.append(shape.text)
        return "\n".join(parts), "text"
    return "Định dạng này chưa hỗ trợ. Hãy gửi văn bản, PDF, DOCX, XLSX, PPTX, HTML, JSON, CSV, v.v.", "error"

def split_text_smart(text: str, chunk_chars: int = CHUNK_CHARS):
    if len(text) <= chunk_chars:
        return [text]
    parts=[]
    cur=[]; used=0
    for para in text.split("\n"):
        add=len(para)+1
        if used+add>chunk_chars and cur:
            parts.append("\n".join(cur))
            cur=[para]; used=add
        else:
            cur.append(para); used+=add
    if cur: parts.append("\n".join(cur))
    return parts

def _safe_name(s):
    return re.sub(r"[^\w\-]+","_", s).strip("_") or "output"

def make_docx_from_text(text: str) -> bytes:
    if DocxDocument is None:
        raise RuntimeError("Thiếu python-docx")
    doc = DocxDocument()
    for line in (text or "").splitlines():
        doc.add_paragraph(line if line.strip() else "")
    bio = io.BytesIO()
    doc.save(bio)
    return bio.getvalue()

def _emit_text_file(base, ext, text):
    out_name = f"{_safe_name(base)}{ext}"
    buf = io.BytesIO((text or "").encode("utf-8")); buf.name = out_name
    return out_name, buf

def _emit_docx_file(base, text):
    data = make_docx_from_text(text)
    out_name = f"{_safe_name(base)}.docx"
    buf = io.BytesIO(data); buf.name = out_name
    return out_name, buf

def _get_gem_client():
    if genai is None or types is None:
        raise RuntimeError("Thiếu package google-genai")
    if not GEMINI_API_KEY:
        raise RuntimeError("Thiếu GEMINI_API_KEY")
    return genai.Client(api_key=GEMINI_API_KEY)

def create_image_bytes_gemini(prompt: str):
    cli = _get_gem_client()
    resp = cli.models.generate_content(model=GEMINI_IMAGE_MODEL, contents=prompt, config=types.GenerateContentConfig(response_modalities=['TEXT','IMAGE']))
    parts = resp.candidates[0].content.parts if resp and resp.candidates else []
    for part in parts:
        if getattr(part, "inline_data", None) and getattr(part.inline_data, "data", None):
            return part.inline_data.data, part.inline_data.mime_type or "image/png"
    raise RuntimeError("Gemini không trả ảnh.")

async def send_note(context, chat_id: int, text: str):
    body = f"📝 <i>Lời nhắn</i>\n{htmlesc(text)}"
    try:
        await context.bot.send_message(chat_id, body, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except BadRequest:
        await context.bot.send_message(chat_id, f"📝 {text}")

def touch(chat_id: int):
    LAST_SEEN[chat_id] = time.time()

def close_and_del(*objs):
    for o in objs:
        try:
            if hasattr(o, "close"):
                o.close()
        except Exception:
            pass
        try:
            del o
        except Exception:
            pass

def cleanup_maps_now():
    now = time.time()
    for cid, ts in list(LAST_SEEN.items()):
        if now - ts > INACTIVE_SECS:
            histories.pop(cid, None)
            LAST_DOC.pop(cid, None)
            LAST_SEEN.pop(cid, None)
    if len(PAGERS) > MAX_PAGERS:
        items = sorted(PAGERS.items(), key=lambda kv: kv[1].get("ts", 0))
        drop = len(PAGERS) - MAX_PAGERS
        for k, _ in items[:drop]:
            PAGERS.pop(k, None)

def maybe_gc():
    global REQ_COUNT
    REQ_COUNT += 1
    if REQ_COUNT % max(1, GC_EVERY) == 0:
        cleanup_maps_now()
        gc.collect()

def start_janitor_thread():
    def _loop():
        while True:
            cleanup_maps_now()
            gc.collect()
            time.sleep(30)
    threading.Thread(target=_loop, daemon=True).start()

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (
        "Lệnh:\n"
        "/help – trợ giúp\n"
        "/img <mô tả> – Chuyên gia tạo ảnh(hơi ngáo tí) (Gemini)\n"
        "/code <yêu cầu> – code (Claude-3.7-sonnet)\n"
    )
    await update.message.reply_text(txt)

async def cmd_addlink(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid != ADMIN_ID:
        return await send_note(context, update.effective_chat.id, "Xin lỗi, lệnh này chỉ cho chủ bot.")
    if not context.args:
        return await send_note(context, update.effective_chat.id, "Dùng: /addlink <CHAT_ID> (bot phải là admin trong nhóm đó).")
    chat_id = int(context.args[0])
    try:
        link = await context.bot.create_chat_invite_link(chat_id, name="Linh auto invite")
        return await send_note(context, update.effective_chat.id, f"Link mời: {link.invite_link}")
    except Forbidden:
        return await send_note(context, update.effective_chat.id, "Bot không phải admin ở nhóm đó hoặc không có quyền tạo link.")
    except BadRequest as e:
        return await send_note(context, update.effective_chat.id, f"Lỗi tạo link: {e}")

async def cmd_img(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    touch(chat_id)
    prompt = " ".join(context.args).strip()
    if not prompt:
        return await send_note(context, chat_id, "Dùng: /img <mô tả>")
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
    buf = None
    try:
        data, mime = create_image_bytes_gemini(prompt)
        buf = io.BytesIO(data); buf.name = "gen.png"
        await context.bot.send_photo(chat_id, buf, caption=prompt)
    except Exception as e:
        await send_note(context, chat_id, f"Lỗi tạo ảnh: {e}")
    finally:
        close_and_del(buf)
        maybe_gc()

async def cmd_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    touch(chat_id)
    q = " ".join(context.args).strip()
    if not q:
        return await send_note(context, chat_id, "Dùng: /code <yêu cầu>")
    async with locks[chat_id]:
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        msgs = build_messages(chat_id, q, sys_prompt_linh()+" Bạn là lập trình viên kỳ cựu. Viết code sạch, best practice. Có tư duy nằm trong 0.1% người thông minh nhất thế giới.")
        result = complete_with_model(CODE_MODEL, msgs, MAX_TOKENS_CODE, temperature=0.4) or "..."
        m = re.search(r"```(\w+)?\n(.*?)```", result, flags=re.S)
        if m: await start_pager(context, chat_id, m.group(2).rstrip(), is_code=True, lang_hint=m.group(1) or "")
        else: await start_pager(context, chat_id, result, is_code=True)
        histories[chat_id].append(("user", q))
        histories[chat_id].append(("assistant", result[:1000]))
        maybe_gc()

def want_image(t):
    t=(t or "").lower()
    return any(k in t for k in ["tạo ảnh","vẽ","generate image","draw image","vẽ giúp","create image","/img "])

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    touch(chat_id)
    q = (update.message.text or "").strip()
    low = q.lower()

    if want_image(q):
        prompt = re.sub(r"(?i)(tạo ảnh|vẽ|generate image|draw image|vẽ giúp|create image|/img)\s*[:\-]*", "", q).strip() or "A cute cat in space suit, 3D render"
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
        buf = None
        try:
            data, mime = create_image_bytes_gemini(prompt)
            buf = io.BytesIO(data); buf.name = "gen.png"
            await context.bot.send_photo(chat_id, buf, caption=prompt)
        except Exception as e:
            return await send_note(context, chat_id, f"Lỗi tạo ảnh: {e}")
        finally:
            close_and_del(buf)
            maybe_gc()
        return

    if chat_id in LAST_DOC:
        src_name = LAST_DOC[chat_id]["name"]
        src_text = LAST_DOC[chat_id]["text"]
        action = None; target_lang=None
        if any(k in low for k in ["nâng cấp","upgrade","cải thiện","improve","tối ưu","optimize","refactor"]):
            action="upgrade"
        elif any(k in low for k in ["sửa lại","chỉnh sửa","viết lại","rewrite","edit"]):
            action="rewrite"
        elif any(k in low for k in ["tóm tắt","summary","tổng hợp"]):
            action="summarize"
        elif re.search(r"(dịch|translate)", low):
            action="translate"
            m = re.search(r"(?:sang|to)\s+([a-zA-ZÀ-ỹ ]+)$", low)
            target_lang = (m.group(1).strip() if m else "English")
        elif any(k in low for k in ["sửa chính tả","chính tả","grammar","spellcheck"]):
            action="proof"
        elif any(k in low for k in ["chuẩn hoá markdown","format markdown","định dạng markdown","markdown"]):
            action="markdown"

        if action:
            await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
            out = await process_action(src_text, action, target_lang)
            base, ext = os.path.splitext(src_name)
            out_name = None; buf = None
            try:
                if ext.lower() in TEXT_LIKE:
                    out_name, buf = _emit_text_file(base, ext, out)
                elif ext.lower() == ".docx":
                    out_name, buf = _emit_docx_file(base, out)
                else:
                    out_name, buf = _emit_text_file(base, ".txt", out)
                await context.bot.send_document(chat_id, document=buf, caption=f"{action} → {out_name}")
            finally:
                close_and_del(buf)
            LAST_DOC[chat_id] = {"name": out_name, "text": out}
            await start_pager(context, chat_id, out, is_code=False)
            maybe_gc()
            return

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    msgs = build_messages(chat_id, q, sys_prompt_linh())
    result = complete_with_model(CHAT_MODEL, msgs, MAX_TOKENS, temperature=0.85) or "..."
    await start_pager(context, chat_id, result, is_code=False)
    histories[chat_id].append(("user", q))
    histories[chat_id].append(("assistant", result[:1000]))
    maybe_gc()

async def warmup_long_context(text: str):
    if not client: return
    chunks = split_text_smart(text, CHUNK_CHARS)
    sys = "Đọc và lưu ngữ cảnh cho các đoạn văn bản sau. Không trả lời gì cả."
    for ck in chunks[:3]:
        msgs=[{"role":"system","content":sys},{"role":"user","content":ck}]
        try:
            _ = complete_with_model(FILE_MODEL, msgs, max_tokens=min(256, MAX_TOKENS_FILE//100), temperature=0.0)
        except Exception:
            break

async def process_action(text: str, action: str, target_lang: str | None):
    if action=="upgrade":
        sys_part = "Cải thiện chất lượng: rõ ràng, logic, rút lặp, thêm tiêu đề/mục nếu cần, giữ nguyên ý, ví dụ ngắn khi hữu ích."
    elif action=="rewrite":
        sys_part = "Viết lại tiếng Việt gọn gàng, mạch lạc, giữ ý, tránh lặp, dùng tiêu đề và bullet hợp lý."
    elif action=="summarize":
        sys_part = "Tóm tắt theo mục: Ý chính; Dữ kiện quan trọng; Con số/Mốc thời gian; Rủi ro/Điểm bất thường; Việc nên làm."
    elif action=="translate":
        sys_part = f"Dịch chính xác sang {target_lang or 'English'}, giữ ngữ cảnh và định dạng."
    elif action=="proof":
        sys_part = "Sửa chính tả và ngữ pháp tiếng Việt, giữ nguyên nghĩa, trả bản sạch."
    else:
        sys_part = "Chuẩn hoá sang Markdown rõ ràng: tiêu đề, bullet, bảng nếu cần, mã để trong ```."

    chunks = split_text_smart(text, CHUNK_CHARS)
    if len(chunks)==1:
        msgs=[{"role":"system","content":sys_part},{"role":"user","content":chunks[0]}]
        return complete_with_model(FILE_MODEL, msgs, max_tokens=MAX_TOKENS_FILE, temperature=0.3)

    partials=[]
    for i,ck in enumerate(chunks,1):
        sys = f"{sys_part} Đây là phần {i}/{len(chunks)} của tài liệu lớn. Xử lý độc lập và nhất quán."
        msgs=[{"role":"system","content":sys},{"role":"user","content":ck}]
        part = complete_with_model(FILE_MODEL, msgs, max_tokens=max(2048, min(MAX_TOKENS_FILE//len(chunks), 32000)), temperature=0.3)
        partials.append(part)

    merge_prompt = (
        "Bạn sẽ hợp nhất các phần đã xử lý dưới đây thành một phiên bản cuối cùng, thống nhất giọng văn, định dạng và nội dung. "
        "Giữ đúng yêu cầu: " + sys_part + "\n\n" +
        "\n\n-----\n\n".join(f"[PHẦN {i+1}]\n{p}" for i,p in enumerate(partials))
    )
    msgs=[{"role":"system","content":"Hợp nhất các phần thành một tài liệu hoàn chỉnh, liền mạch, không lặp."},{"role":"user","content":merge_prompt}]
    return complete_with_model(FILE_MODEL, msgs, max_tokens=MAX_TOKENS_FILE, temperature=0.2)

async def on_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    touch(chat_id)
    doc = update.message.document
    name = doc.file_name or "file"
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    bio = None; buf = None
    try:
        if is_archive(name):
            return await send_note(context, chat_id, "Không nhận file nén (.zip, .rar, .7z, .tar.*).")
        f = await context.bot.get_file(doc.file_id)
        bio = io.BytesIO(); await f.download_to_memory(out=bio)
        data = bio.getvalue()
        text, kind = read_any_file(name, data)
        if kind == "error":
            return await start_pager(context, chat_id, text, is_code=False)
        if not text:
            return await send_note(context, chat_id, "Không trích được nội dung từ file.")
        text = (text or "")[:MAX_EMIT_CHARS]
        base, ext = os.path.splitext(name)
        if ext.lower() in TEXT_LIKE:
            out_name, buf = _emit_text_file(base, ext, text)
        elif ext.lower()==".docx" and DocxDocument is not None:
            out_name, buf = _emit_docx_file(base, text)
        else:
            out_name, buf = _emit_text_file(base, ".txt", text)
        await context.bot.send_document(chat_id, document=buf, caption=f"Đã đọc: {name} → {out_name}")
        LAST_DOC[chat_id] = {"name": out_name, "text": text}
        await warmup_long_context(text)
        await send_note(context, chat_id, "Đã tải file. Gõ: 'sửa lại' | 'nâng cấp' | 'tối ưu' | 'refactor' | 'tóm tắt' | 'dịch sang <ngôn ngữ>' | 'sửa chính tả' | 'chuẩn hoá markdown'.")
    except BadRequest:
        await start_pager(context, chat_id, "Đã gửi file .txt.", is_code=True)
    except Exception as e:
        await send_note(context, chat_id, f"Lỗi đọc file: {e}")
    finally:
        close_and_del(bio, buf)
        maybe_gc()

def main():
    start_janitor_thread()
    app_tg = ApplicationBuilder().token(BOT_TOKEN).build()
    app_tg.add_handler(CommandHandler("help", cmd_help))
    app_tg.add_handler(CommandHandler("img", cmd_img))
    app_tg.add_handler(CommandHandler("code", cmd_code))
    app_tg.add_handler(CommandHandler("addlink", cmd_addlink))
    app_tg.add_handler(CallbackQueryHandler(on_page_nav, pattern=r"^pg_"))
    app_tg.add_handler(MessageHandler(filters.Document.ALL, on_file))
    app_tg.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=8080), daemon=True).start()
    app_tg.run_polling()

if __name__ == "__main__":
    main()
