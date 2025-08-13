import os, re, threading, asyncio, io, logging, random, datetime
import base64
from collections import deque, defaultdict
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode, ChatAction
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters, CommandHandler, CallbackQueryHandler
from telegram.error import BadRequest
from openai import OpenAI

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("linh")

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
VERCEL_API_KEY = os.environ.get("VERCEL_API_KEY", "")
BASE_URL = os.getenv("BASE_URL", "https://ai-gateway.vercel.sh/v1")

CHAT_MODEL = os.getenv("CHAT_MODEL", "anthropic/claude-3.5-haiku")
CODE_MODEL = os.getenv("CODE_MODEL", "anthropic/claude-4-sonnet")
FILE_MODEL = os.getenv("FILE_MODEL", "anthropic/claude-4.1-opus")

MAX_TOKENS = int(os.getenv("MAX_TOKENS", "900"))
MAX_TOKENS_CODE = int(os.getenv("MAX_TOKENS_CODE", "4000"))
FILE_OUTPUT_TOKENS = int(os.getenv("FILE_OUTPUT_TOKENS", "6000"))
CHUNK_CHARS = int(os.getenv("CHUNK_CHARS", "120000"))
PAGE_CHARS = int(os.getenv("PAGE_CHARS", "3200"))
CTX_TURNS = int(os.getenv("CTX_TURNS", "15"))
MAX_CONCURRENCY = int(os.getenv("MAX_CONCURRENCY", "3"))
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "90"))
MAX_EMIT_CHARS = int(os.getenv("MAX_EMIT_CHARS", "800000"))

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_IMAGE_MODEL = os.getenv("GEMINI_IMAGE_MODEL", "gemini-2.0-flash-preview-image-generation")

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

client = OpenAI(api_key=VERCEL_API_KEY, base_url=BASE_URL, timeout=REQUEST_TIMEOUT) if VERCEL_API_KEY else None
SEM = asyncio.Semaphore(MAX_CONCURRENCY)
histories = defaultdict(lambda: deque(maxlen=32))
locks = defaultdict(asyncio.Lock)
PAGERS = {}
FILE_MODE = defaultdict(lambda: False)
PENDING_FILE = {}
LAST_RESULT = {}

ARCHIVES = (".zip",".rar",".7z",".tar",".tar.gz",".tgz",".tar.bz2",".tar.xz")
TEXT_LIKE = (".txt",".md",".log",".csv",".tsv",".json",".yaml",".yml",".ini",".cfg",".env",".xml",".html",".htm",
             ".py",".js",".ts",".java",".c",".cpp",".cs",".go",".php",".rb",".rs",".sh",".bat",".ps1",".sql")

def chunk_code_pages(code: str, per_page: int = PAGE_CHARS) -> list:
    if len(code) <= per_page:
        return [code]

    pages = []
    current_page = []
    current_size = 0
    blocks = []
    current_block = []

    for line in code.splitlines():
        if line and not line.startswith(' ') and not line.startswith('\t'):
            if current_block:
                blocks.append('\n'.join(current_block))
            current_block = [line]
        else:
            current_block.append(line)

    if current_block:
        blocks.append('\n'.join(current_block))

    for block in blocks:
        block_size = len(block) + 1

        if current_size + block_size > per_page:
            if current_page:
                pages.append('\n'.join(current_page))
                current_page = []
                current_size = 0

        if block_size > per_page:
            lines = block.splitlines()
            current_lines = []
            current_lines_size = 0

            for line in lines:
                line_size = len(line) + 1
                if current_lines_size + line_size > per_page:
                    pages.append('\n'.join(current_lines))
                    current_lines = [line]
                    current_lines_size = line_size
                else:
                    current_lines.append(line)
                    current_lines_size += line_size

            if current_lines:
                pages.append('\n'.join(current_lines))
        else:
            current_page.append(block)
            current_size += block_size

    if current_page:
        pages.append('\n'.join(current_page))

    return pages

def chunk_pages(raw: str, per_page: int = PAGE_CHARS) -> list:
    if len(raw) <= per_page:
        return [raw]
    pages = []
    current = []
    current_size = 0

    for line in raw.splitlines():
        line_size = len(line) + 1
        if current_size + line_size > per_page and current:
            pages.append('\n'.join(current))
            current = [line]
            current_size = line_size
        else:
            current.append(line)
            current_size += line_size

    if current:
        pages.append('\n'.join(current))
    return pages

def kb(idx: int, total: int) -> InlineKeyboardMarkup:
    return None if total <= 1 else InlineKeyboardMarkup([[
        InlineKeyboardButton("⏪", callback_data="pg_prev"),
        InlineKeyboardButton(f"{idx+1}/{total}", callback_data="pg_stay"),
        InlineKeyboardButton("⏩", callback_data="pg_next")
    ]])

def page_payload(p: dict) -> tuple:
    txt = p["pages"][p["idx"]]
    return (f"```{p['lang']}\n{txt}\n```", ParseMode.MARKDOWN_V2) if p["is_code"] else (txt, ParseMode.HTML)

async def send_or_update(ctx: ContextTypes.DEFAULT_TYPE, chat_id: int, msg: Update, p: dict):
    text, mode = page_payload(p)
    keyboard = kb(p["idx"], len(p["pages"]))

    async def try_send(text: str, mode: str, keyboard: InlineKeyboardMarkup, retry_without_format: bool = True) -> bool:
        try:
            if msg:
                await msg.edit_text(text, parse_mode=mode, reply_markup=keyboard)
            else:
                m = await ctx.bot.send_message(chat_id, text, parse_mode=mode, reply_markup=keyboard)
                PAGERS[(m.chat_id, m.message_id)] = p
            return True
        except BadRequest as e:
            if retry_without_format and "can't parse entities" in str(e).lower():
                await try_send(text, None, keyboard, False)
            else:
                raise e
        return False

    try:
        await try_send(text, mode, keyboard)
    except Exception:
        p["is_code"] = not p["is_code"]
        text, mode = page_payload(p)
        await try_send(text, mode, keyboard)

async def start_pager(ctx: ContextTypes.DEFAULT_TYPE, chat_id: int, raw: str, is_code: bool = False, lang_hint: str = ""):
    pages = chunk_code_pages(raw) if is_code else chunk_pages(raw)
    await send_or_update(ctx, chat_id, None, {
        "pages": pages,
        "is_code": is_code,
        "lang": lang_hint or "markdown",
        "idx": 0
    })

def build_messages(cid: int, user_text: str, sys_prompt: str) -> list:
    msgs = [{"role": "system", "content": sys_prompt}]
    keep = max(2, CTX_TURNS * 2)
    msgs += [{"role": "user" if r == 'user' else 'assistant', "content": c}
             for r, c in list(histories[cid])[-keep:]]
    msgs.append({"role": "user", "content": user_text})
    return msgs

def sys_prompt_linh() -> str:
    current_time = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    return (
        f"Bạn tên là Linh. Nói chuyện tự nhiên như người Việt, ngắn gọn, thẳng, có cảm xúc.\n"
        f"Cho phép văng tục khi hợp ngữ cảnh, không thù hằn và không công kích cá nhân.\n"
        f"Không nịnh bợ, không vòng vo. Tập trung ý chính.\n"
        f"Thời gian hiện tại (UTC): {current_time}\n"
        f"Được làm ra bởi Hoàng Tuấn Anh. Telegram: @cucodoivandep."
    )

def complete_with_model(model: str, messages: list, max_tokens: int, temperature: float = 0.7) -> str:
    if not client:
        return "Thiếu VERCEL_API_KEY."
    res = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        messages=messages
    )
    return (res.choices[0].message.content or "").strip()

async def _run_llm_retry(model: str, messages: list, max_tokens: int, temperature: float, tries: int = 3) -> str:
    last = None
    for i in range(tries):
        try:
            return await asyncio.to_thread(
                complete_with_model,
                model,
                messages,
                max_tokens,
                temperature
            )
        except Exception as e:
            last = e
            await asyncio.sleep(1.2 * (i + 1) + random.random())
    raise last

async def run_llm(model: str, messages: list, max_tokens: int, temperature: float = 0.7) -> str:
    async with SEM:
        return await asyncio.wait_for(
            _run_llm_retry(model, messages, max_tokens, temperature),
            timeout=REQUEST_TIMEOUT + 10
        )

def is_archive(name: str) -> bool:
    return (name or "").lower().endswith(ARCHIVES)

def detect_decode(data: bytes) -> str:
    if not data:
        return ""
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

def read_any_file(name: str, data: bytes) -> tuple:
    n = (name or "").lower()
    if is_archive(n):
        return None, "archive"
    if any(n.endswith(ext) for ext in TEXT_LIKE):
        raw = detect_decode(data)
        if n.endswith((".html", ".htm")) and BeautifulSoup:
            soup = BeautifulSoup(raw, "html.parser")
            raw = soup.get_text(separator="\n")
        return raw, "text"


    return "Định dạng này chưa hỗ trợ. Hãy gửi văn bản, PDF, DOCX, XLSX, PPTX, HTML, JSON, CSV, v.v.", "error"



async def cmd_img(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    q = " ".join(context.args).strip()
    if not q:
        await context.bot.send_message(chat_id, "Dùng: /img <mô tả>")
        return
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
    if not GEMINI_API_KEY:
        await context.bot.send_message(chat_id, "Thiếu GEMINI_API_KEY.")
        return
    try:
        if genai is None:
            await context.bot.send_message(chat_id, "Thư viện google.genai chưa cài.")
            return
        client_gemini = genai.Client(api_key=GEMINI_API_KEY)
        resp = client_gemini.models.generate_images(model=GEMINI_IMAGE_MODEL, prompt=q)
        sent = 0
        if hasattr(resp, "images") and resp.images:
            for i, img in enumerate(resp.images):
                if hasattr(img, "url") and img.url:
                    await context.bot.send_photo(chat_id, photo=img.url)
                    sent += 1
                else:
                    b64 = getattr(img, "image", None) or getattr(img, "data", None)
                    if b64:
                        data = base64.b64decode(b64)
                        await context.bot.send_photo(chat_id, photo=io.BytesIO(data))
                        sent += 1
        if sent == 0:
            await context.bot.send_message(chat_id, "Không nhận được ảnh từ Gemini.")
    except Exception as e:
        await context.bot.send_message(chat_id, f"Lỗi tạo ảnh: {e}")

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(
        update.effective_chat.id,
        "/help – Hiện danh sách lệnh\n"
        "/img <mô tả> – Tạo ảnh (GEMINI)\n"
        "/code <yêu cầu> – Viết code (CLAUDE-4-SONNET)\n"
        "/cancelfile – Thoát FILE MODE\n"
        "/sendfile – Tải kết quả gần nhất\n"
        "chat – Chat nhanh (CLAUDE-3.5-HAIKU)\n"
        "Gửi file – Vào FILE MODE (CLAUDE-4.1-OPUS), nhắn yêu cầu để xử lý.\n"
    )

async def cmd_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    q = " ".join(context.args).strip()
    if not q:
        return await context.bot.send_message(chat_id, "Dùng: /code <yêu cầu>")

    async with locks[chat_id]:
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        try:
            sys_prompt = (
                sys_prompt_linh() + "\n" +
                "Bạn là lập trình viên kỳ cựu. Tuân thủ các nguyên tắc sau:\n" +
                "1. Viết code sạch, có comments và docstrings đầy đủ\n" +
                "2. Áp dụng best practices và design patterns phù hợp\n" +
                "3. Tối ưu hiệu năng khi cần thiết\n" +
                "4. Code phải dễ bảo trì và mở rộng\n" +
                "5. Thêm error handling đầy đủ"
            )

            msgs = build_messages(chat_id, q, sys_prompt)
            result = await run_llm(CODE_MODEL, msgs, MAX_TOKENS_CODE, temperature=0.4)
            if not result:
                return await context.bot.send_message(chat_id, "Không nhận được kết quả từ model.")

            lang_hint = "markdown"
            code_markers = ["```python", "```javascript", "```java", "```cpp", "```go"]
            for marker in code_markers:
                if marker in result:
                    lang_hint = marker.replace("```", "")
                    break

            await start_pager(context, chat_id, result, is_code=True, lang_hint=lang_hint)
            histories[chat_id].append(("user", q))
            histories[chat_id].append(("assistant", result[:1000]))

        except asyncio.TimeoutError:
            await context.bot.send_message(
                chat_id,
                "Lâu quá chưa xong. Thử chia nhỏ yêu cầu hoặc gửi lại nhé."
            )
        except Exception as e:
            await context.bot.send_message(chat_id, f"Lỗi khi xử lý code: {str(e)}")


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    q = (update.message.text or "").strip()

    recent_msgs = list(histories[chat_id])[-10:]
    context_summary = "\n".join([
        f"{'User' if r=='user' else 'Assistant'}: {c[:100]}..."
        for r, c in recent_msgs[-10:]
    ])

    if want_image(q):
        pass

    if FILE_MODE[chat_id] and chat_id in PENDING_FILE:
        pass

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    sys_prompt = sys_prompt_linh() + f"\n\nTin nhắn gần đây:\n{context_summary}"
    msgs = build_messages(chat_id, q, sys_prompt)

    try:
        result = await run_llm(CHAT_MODEL, msgs, MAX_TOKENS, temperature=0.85) or "..."

        if len(result) > PAGE_CHARS:
            await start_pager(context, chat_id, result)
        else:
            md_text = to_blockquote_md2(result)
            await context.bot.send_message(
                chat_id,
                md_text,
                parse_mode=ParseMode.MARKDOWN_V2,
                disable_web_page_preview=True
            )

        histories[chat_id].append(("user", q))
        histories[chat_id].append(("assistant", result[:1000]))

    except asyncio.TimeoutError:
        await context.bot.send_message(
            chat_id,
            "Lâu quá chưa xong. Thử rút ngắn yêu cầu hoặc gửi lại nhé."
        )
    except Exception as e:
        await context.bot.send_message(chat_id, f"Lỗi khi gọi model: {e}")

def main():
    if not BOT_TOKEN:
        print("Thiếu BOT_TOKEN: đặt biến môi trường BOT_TOKEN trước khi chạy.")
        return
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("img", cmd_img))
    app.add_handler(CommandHandler("code", cmd_code))
    app.add_handler(CommandHandler("chat", cmd_chat))
    app.add_handler(CommandHandler("cancelfile", cmd_cancelfile))
    app.add_handler(CommandHandler("sendfile", cmd_sendfile))
    app.add_handler(CallbackQueryHandler(on_page_nav, pattern=r"^pg_"))
    app.add_handler(MessageHandler(filters.Document.ALL, on_file))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    log.info("Starting Telegram polling...")
    app.run_polling()

if __name__ == "__main__":
    main()
