import os, json, time, zipfile, subprocess, atexit, sys, re, hashlib, base64
from typing import Optional
from datetime import datetime
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

# VMess config
VMESS = {
    "host": "idcecopro.yunagrp.pro",
    "obfsParam": "m.youtube.com",
    "uuid": "c4178b6b-14e6-488b-8bd3-73f2d2d0d830",
    "path": "/yunagrp.com",
    "port": 443
}

def _valid_uuid(u: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", u or ""))

VMESS_ID = VMESS["uuid"] if _valid_uuid(VMESS.get("uuid","")) else None
if not VMESS_ID: print("Invalid VMESS UUID"); sys.exit(1)

# Detect Railway
def is_running_on_railway() -> bool:
    keys = ["RAILWAY_ENVIRONMENT","RAILWAY_PROJECT_ID","RAILWAY_PUBLIC_DOMAIN","RAILWAY_STATIC_URL","RAILWAY_GIT_COMMIT_SHA"]
    return any(os.getenv(k) for k in keys)

# Xray
XRAY_DIR = "xray-bin"
XRAY_EXE = os.path.join(XRAY_DIR, "xray")
XRAY_CONF = os.path.join(XRAY_DIR, "client.json")

def ensure_xray():
    if os.path.exists(XRAY_EXE): return
    os.makedirs(XRAY_DIR, exist_ok=True)
    url = "https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip"
    with requests.get(url, stream=True, timeout=180) as r:
        r.raise_for_status()
        zpath = os.path.join(XRAY_DIR, "xray.zip")
        with open(zpath, "wb") as f:
            for c in r.iter_content(8192):
                if c: f.write(c)
    with zipfile.ZipFile(os.path.join(XRAY_DIR, "xray.zip"), "r") as z:
        z.extractall(XRAY_DIR)
    os.remove(os.path.join(XRAY_DIR, "xray.zip"))
    os.chmod(XRAY_EXE, 0o755)

def write_xray_config():
    cfg = {
        "log": { "loglevel": "warning" },
        "inbounds": [
            { "listen":"127.0.0.1", "port":1080, "protocol":"socks", "settings":{"udp":True} },
            { "listen":"127.0.0.1", "port":8080, "protocol":"http" }
        ],
        "outbounds": [{
            "protocol":"vmess",
            "settings":{
                "vnext":[{
                    "address": VMESS["host"],
                    "port": VMESS["port"],
                    "users":[{ "id": VMESS_ID, "alterId": 0, "security": "auto" }]
                }]
            },
            "streamSettings":{
                "network":"ws",
                "security":"tls",
                "tlsSettings":{ "serverName": VMESS["obfsParam"], "allowInsecure": False },
                "wsSettings":{ "path": VMESS["path"], "headers": { "Host": VMESS["obfsParam"] } }
            }
        }]
    }
    with open(XRAY_CONF, "w") as f: json.dump(cfg, f, indent=2)

xray_proc = None
def start_xray():
    global xray_proc
    xray_proc = subprocess.Popen([XRAY_EXE,"-c",XRAY_CONF], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    t0 = time.time()
    while time.time()-t0 < 3:
        if xray_proc.poll() is not None: raise RuntimeError("Xray exited")
        line = xray_proc.stdout.readline().strip()
        if line: print("[xray]", line)
        time.sleep(0.05)

def stop_xray():
    if xray_proc and xray_proc.poll() is None: xray_proc.terminate()
atexit.register(stop_xray)

# HTTP session through proxy
session = requests.Session()
session.headers.update({
    "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept":"text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language":"vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer":"https://www.google.com/"
})
PROXIES = {"http":"http://127.0.0.1:8080","https":"http://127.0.0.1:8080"}
def get(url, **kw):
    kw.setdefault("timeout", 30)
    kw.setdefault("proxies", PROXIES)
    return session.get(url, **kw)

# Scraper
BASE = "https://animevietsub.cam"

def get_max_page():
    r = get(BASE); r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    cand = []
    for sel in ("ul.pagination a",".pagination a","a.page-numbers"):
        for a in soup.select(sel):
            t = a.get_text(strip=True)
            if t.isdigit(): cand.append(int(t))
    return max(cand) if cand else 1

def parse_list(html):
    soup = BeautifulSoup(html, "html.parser")
    items = soup.select(".MovieList .TPostMv") or []
    out = []
    for it in items:
        a = it.select_one("a[href]")
        if not a: continue
        url = urljoin(BASE, a["href"])
        title = it.select_one(".Title").get_text(strip=True) if it.select_one(".Title") else ""
        eps = it.select_one(".mli-eps i").get_text(strip=True) if it.select_one(".mli-eps i") else ""
        img = it.select_one("img")
        img_url = ""
        if img:
            img_url = img.get("data-cfsrc") or img.get("data-src") or img.get("src") or ""
            if img_url and not img_url.startswith("http"): img_url = urljoin(BASE, img_url)
        out.append({
            "id": hashlib.md5(url.encode()).hexdigest()[:10],
            "name": title,
            "url": url,
            "image": img_url,
            "episodes": eps,
            "scraped_at": datetime.now().isoformat()
        })
    return out

def scrape_all(delay_sec=3):
    total = []
    maxp = get_max_page()
    print("pages:", maxp)
    for p in range(1, maxp+1):
        url = BASE if p==1 else f"{BASE}/page/{p}"
        print(f"{p}/{maxp} -> {url}")
        try:
            r = get(url)
            if r.status_code in (403,429,503):
                time.sleep(6); r = get(url)
            r.raise_for_status()
        except Exception as e:
            print("err:", e); continue
        total.extend(parse_list(r.text))
        time.sleep(delay_sec)
    print("total_anime:", len(total))
    return total

# Save
def save_local(data: dict, path: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path,"w",encoding="utf-8") as f: json.dump(data,f,ensure_ascii=False,indent=2)
    print("saved:", path)

def _gh_headers(token: str):
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "railway-scraper"
    }

def _gh_get_default_branch(owner_repo: str, token: str) -> str:
    url = f"https://api.github.com/repos/{owner_repo}"
    r = requests.get(url, headers=_gh_headers(token), timeout=30); r.raise_for_status()
    return r.json().get("default_branch", "main") or "main"

def save_github_rest(data: dict, owner_repo: str, path: str, token: str, branch: Optional[str] = None):
    if not branch:
        try: branch = _gh_get_default_branch(owner_repo, token)
        except Exception: branch = "main"
    get_url = f"https://api.github.com/repos/{owner_repo}/contents/{path}?ref={branch}"
    put_url = f"https://api.github.com/repos/{owner_repo}/contents/{path}"
    content_bytes = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    b64 = base64.b64encode(content_bytes).decode()
    sha = None
    try:
        gr = requests.get(get_url, headers=_gh_headers(token), timeout=30)
        if gr.status_code == 200: sha = gr.json().get("sha")
    except Exception as e:
        print("gh_rest get_sha:", e)
    payload = { "message": f"Update {path} {datetime.now().isoformat()}", "content": b64, "branch": branch }
    if sha: payload["sha"] = sha
    for i in range(3):
        r = requests.put(put_url, headers=_gh_headers(token), json=payload, timeout=60)
        if r.status_code in (200,201):
            print(f"gh_rest: ok {path} on {branch}")
            return
        if r.status_code in (429,500,502,503,504):
            time.sleep(2**i); continue
        print("gh_rest fail:", r.status_code, r.text[:200]); break
    save_local(data, path)

def save_github(data: dict, repo_full: str, out_path: str, token: str, branch: Optional[str] = None):
    try:
        from github import Github
    except Exception:
        return save_github_rest(data, repo_full, out_path, token, branch)
    try:
        g = Github(token); repo = g.get_repo(repo_full)
        if not branch:
            try: branch = repo.default_branch or "main"
            except Exception: branch = "main"
        content = json.dumps(data, ensure_ascii=False, indent=2)
        file_sha = None
        try:
            file = repo.get_contents(out_path, ref=branch); file_sha = file.sha
        except Exception: file_sha = None
        if file_sha:
            repo.update_file(out_path, f"Update {out_path} {datetime.now().isoformat()}", content, file_sha, branch=branch)
            print(f"gh: updated {out_path} on {branch}")
        else:
            repo.create_file(out_path, f"Add {out_path} {datetime.now().isoformat()}", content, branch=branch)
            print(f"gh: created {out_path} on {branch}")
    except Exception as e:
        print("gh pygithub err:", e); save_github_rest(data, repo_full, out_path, token, branch)

# Output format
def build_output(anime_list):
    base = BASE
    return {
        "name":"ANIMEVIETSUB","id":"avietsub-pvd","url":base,"color":"#FF6B00",
        "image":{"url":f"{base}/logo.png","display":"cover","shape":"square"},
        "description":"AnimeVietsub.cam - Xem anime online miễn phí chất lượng cao",
        "org_metadata":{"description":"AnimeVietsub.cam - Xem anime online miễn phí chất lượng cao","title":"ANIMEVIETSUB","image":f"{base}/orgthumb.jpg"},
        "share":{"url":base},
        "notice":{"id":"notice-1","link":base,"icon":f"{base}/icon.png","closeable":True},
        "sorts":[
            {"text":"Mới nhất","type":"radio","url":f"{base}/anime-moi"},
            {"text":"Phổ biến","type":"radio","url":f"{base}/anime-hot"}
        ],
        "total_anime":len(anime_list),
        "last_updated":datetime.now().isoformat(),
        "anime_list":anime_list
    }

def main():
    print("railway:", is_running_on_railway())
    ensure_xray(); write_xray_config(); start_xray()
    try:
        try:
            print("ip:", get("https://api.ipify.org?format=json").json())
        except Exception as e:
            print("ip_err:", e)
        data = scrape_all(delay_sec=3)
        output = build_output(data)
        GITHUB_TOKEN = os.getenv("GITHUB_TOKEN","").strip()
        GH_REPO = os.getenv("GH_REPO","htuananh1/Data-manager").strip()
        OUT_DATA = os.getenv("OUT_DATA_PATH","animevsub/animevsub_data.json").strip()
        OUT_SUM  = os.getenv("OUT_SUM_PATH","animevsub/animevsub_summary.json").strip()
        GH_BRANCH = os.getenv("GH_BRANCH","").strip()
        summary = {
            "last_update": datetime.now().isoformat(),
            "total_anime": len(output["anime_list"]),
            "new_anime_added": len(data)
        }
        if GITHUB_TOKEN:
            save_github(output, GH_REPO, OUT_DATA, GITHUB_TOKEN, branch=GH_BRANCH or None)
            save_github(summary, GH_REPO, OUT_SUM, GITHUB_TOKEN, branch=GH_BRANCH or None)
        save_local(output, OUT_DATA)
        save_local(summary, OUT_SUM)
    finally:
        stop_xray()

if __name__ == "__main__":
    main()
