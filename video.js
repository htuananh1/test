// ==UserScript==
// @name         UGPHONE VIP TOOL 
// @namespace    https://ugphone.com/
// @version      4.7
// @author       Hoàng Anh
// @match        https://www.ugphone.com/toc-portal/#/login
// @match        https://www.ugphone.com/toc-portal/#/dashboard/index
// @icon         https://media2.giphy.com/media/v1.Y2lkPTc5MGI3NjExcGhmdmJyN3cxdWNjNDc1aG5iN3J4eTBrMWV6Z3lscTh0MHFnemV0diZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9cw/jPdNzfqIDmokLbSqO0/giphy.gif
// @grant        GM_xmlhttpRequest
// ==/UserScript==

(function() {
    'use strict';

    // ==== Thông tin GitHub ====
    const GITHUB_OWNER = "htuananh1";
    const GITHUB_REPO = "Deb2929";
    const GITHUB_FILE = "Test";
    const GITHUB_TOKEN = "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";

    let themes = [];
    let themeIndex = 0;

    const orderedKeys = [
        "ugPhoneLang","ugBrowserId","UGPHONE-ID","UGrightSlideTips","hadAgreePolicy","_gcl_ls","UGPHONE-Token","UGPHONE-MQTT"
    ];

    const host = document.createElement('div');
    host.id = 'ugphone-vip-tool';
    document.body.appendChild(host);

    const shadow = host.attachShadow({ mode: 'open' });

    // ==== UI ====
    shadow.innerHTML = `
        <style>
            :host { all: initial; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
            #bubble { position: fixed; top: 20px; right: 20px; width: 46px; height: 46px; border-radius: 50%;
                background: #4a6bdf; background-image: url('https://cdn-icons-png.flaticon.com/512/1995/1995485.png');
                background-size: 60%; background-repeat: no-repeat; background-position: center; cursor: pointer;
                box-shadow: 0 4px 12px rgba(0,0,0,0.15); z-index: 9999; border: 2px solid white;}
            #bubble:hover { transform: scale(1.08);}
            #overlay { position: fixed; top: 0; left: 0; width: 100vw; height: 100vh; background: rgba(0,0,0,0.5);
                display: flex; justify-content: center; align-items: flex-start; z-index: 9998; }
            #modal { width: 380px; height: 950px; background: transparent; border-radius: 16px; box-shadow: 0 8px 32px rgba(0,0,0,0.2);
                overflow: hidden; animation: fadeIn 0.3s ease; position:relative; margin-top:70px;}
            @keyframes fadeIn { from { opacity: 0; transform: translateY(-24px); } to { opacity: 1; transform: translateY(0); } }
            #modal-header { 
                background: #5777db;
                color: #fff; 
                padding: 8px 16px 7px 16px;
                font-size: 1.05rem;
                font-weight: bold;
                display: flex; 
                justify-content: space-between; 
                align-items: center; 
                z-index:2; 
                position:relative; 
                border-radius: 16px 16px 0 0;
                letter-spacing: 0.5px;
                line-height: 1.08;
                height: 40px;
            }
            #modal-header span {
                font-size: 1.05rem;
                font-weight: bold;
                letter-spacing: 0.5px;
                line-height: 1.08;
            }
            #modal-content {
                padding: 0;
                position:relative;
                background: transparent;
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                height: 460px;
            }
            #modal-bg-video {
                position: absolute;
                top: 0; left: 0; width: 100%; height: 100%; object-fit: cover;
                z-index: 0; border-radius: 0 0 16px 16px; pointer-events: none;
                opacity: 0.995; filter: blur(0.1px) brightness(1.09) grayscale(0.03) contrast(1.22) saturate(1.16);
                transition: opacity 0.25s;
                background: #232b3b;
            }
            #modal-inner {
                position: relative;
                z-index: 2;
                width: 100%;
                height: 100%;
                padding: 10px 10px 0 10px;
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
            }
            #message { min-height: 20px; color: #e74c3c; font-size: 13px; margin-bottom: 7px; text-align: center; background:rgba(0,0,0,0.10); border-radius:6px; padding:3px 4px;}
            textarea { width: 100%; height: 80px; padding: 7px; border: 1.2px solid #fff4; border-radius: 10px; resize: none;
                font-family: monospace; margin-bottom: 8px; background: rgba(255,255,255,0.11); color: #fff; font-size: 0.95em; box-shadow: 0 1.5px 18px #0002; outline: none;}
            #input::placeholder { color: #fff9; }
            .button-group { display: flex; gap: 7px; margin-bottom: 7px; width:99%; }
            button {
                flex: 1;
                padding: 9px;
                border: none;
                border-radius: 8px;
                cursor: pointer;
                font-weight: 500;
                font-size: 0.97em;
                background: rgba(72,114,181,0.12);
                color: #fff;
                transition: background .18s, color .18s;
                margin: 0 0 0 0;
            }
            button:hover, button:focus {
                background: #5777db;
                color: #fff;
            }
            #submit { background: #314e92b0;}
            #logout { background: #a14a4ab0;}
            #copy { background: #3a7660b0;}
            #upload { background: #3c4a6eb0;}
            #auto-trial { 
                background: #d8b64c; 
                color: #fff; 
                font-weight: bold; 
                margin: 0 0 7px 0;
                padding: 9px 0;
                border-radius: 8px;
                font-size: 0.97em;
                width: 49%;
                min-width: 120px;
                max-width: 180px;
                align-self: flex-start;
                transition: background .18s, color .18s;
            }
            #auto-trial:hover { background: #c7a238; color: #232733;}
            #modal-footer {
                text-align: center;
                padding: 10px 0 6px 0;
                font-size: 11.5px;
                color: #fff;
                border-top: 1px solid rgba(240,242,245,0.16);
                background: transparent;
                border-radius: 0 0 16px 16px;
                z-index: 2;
                position: relative;
            }
            #theme-row {
                display: flex; align-items: center; gap: 8px; margin-top: 2px; margin-bottom: 0; justify-content: flex-end; width: 100%;
            }
            #theme-select {
                font-size: 13px; padding: 3px 6px; border-radius: 6px; border: 1px solid #8fa2e9; background: #f7faff;
                color: #3a3a4a; font-weight: 500; min-width: 108px;
            }
            #theme-add-btn { flex: 0 0 auto; padding: 4px 10px; font-size: 12px; border-radius: 7px;
                background: #4a6bdf; color: #fff; border: none; cursor: pointer; font-weight: bold; margin: 0 0 0 8px;}
            #theme-add-btn:hover { background: #304fb7;}
            #theme-popup-outer { display:none; position:fixed; z-index:1000001; top:0; left:0; width:100vw; height:100vh;
                background:rgba(0,0,0,0.45); align-items:center; justify-content:center; }
            #theme-popup-inner { background:#242e4b; color:#fff; border-radius:12px; padding:24px 18px; min-width:180px; max-width:92vw; box-shadow:0 2px 24px #0008;
                display:flex; flex-direction:column; gap:10px; align-items:stretch; position:relative; font-size: 14px; z-index: 1000002;}
            #theme-popup-inner input { padding:6px 9px; border-radius:7px; font-size:13px; border:1.5px solid #4a6bdf; color:#fff; background:#1a2034; margin-bottom: 4px; outline: none; transition: border-color .2s;}
            #theme-popup-inner input:focus { border-color: #6a93ff;}
            #theme-popup-title { font-size:15px; margin-bottom:3px; font-weight:bold; color:#ffda6a; text-align:center;}
            #theme-popup-msg { min-height: 18px; color: #f7f191; background: #2b2c36; border-radius: 5px; padding: 4px 6px; margin: 2px 0 0 0; font-size: 12px; text-align: center; word-break: break-word;}
            #theme-popup-close { position:absolute;top:6px;right:13px;background:none;border:none;font-size:17px;color:#fff;cursor:pointer;line-height:1;}
            #theme-popup-btns { display:flex;gap:6px;margin-top:11px;}
            #theme-popup-ok { flex:1;background:#4a6bdf;border:none;border-radius:7px;color:#fff;font-weight:bold;padding:6px 0;font-size:13px;cursor:pointer;}
            #theme-popup-cancel { flex:1;background:#555b75;border:none;border-radius:7px;color:#fff;padding:6px 0;font-size:13px;cursor:pointer;}
            #theme-popup-ok:hover {background:#2c4ac2;}
            #theme-popup-cancel:hover {background:#313448;}
            #ugphone-global-notify {
                position:fixed;top:22px;right:85px;z-index:10000000;
                min-width:170px;max-width:320px;
                background:rgba(33,39,68,0.97);
                color:#ffe666;
                font-size:13px;
                font-weight:bold;
                border-radius:8px;
                box-shadow:0 4px 24px #0006;
                padding:8px 16px 8px 12px;
                display:none;
                align-items:center;
                gap:8px;
                border:2px solid #4a6bdf;
                transition: all .22s;
                pointer-events:none;
                text-align:left;
                white-space:pre-line;
            }
        </style>
        <div id="bubble" title="UGPHONE VIP TOOL"></div>
        <div id="overlay">
            <div id="modal">
                <div id="modal-header">
                    <span>UGPHONE VIP TOOL</span>
                    <span id="close-modal" style="cursor:pointer;font-size:1.3rem;font-weight:bold;line-height:0.7;">×</span>
                </div>
                <div id="modal-content">
                    <video id="modal-bg-video" autoplay loop muted playsinline preload="auto" style="display:none"></video>
                    <div id="modal-inner">
                        <div id="message"></div>
                        <textarea id="input" placeholder='Nhập nội dung JSON tại đây...'></textarea>
                        <div class="button-group" style="justify-content:center;">
                            <button id="submit">Đăng nhập</button>
                            <button id="logout">Đăng xuất</button>
                        </div>
                        <div class="button-group" style="justify-content:center;">
                            <button id="copy">Sao chép</button>
                            <button id="upload">Tải lên</button>
                        </div>
                        <div class="button-group" style="justify-content:center;margin-bottom:8px;">
                            <button id="auto-trial">AUTO MUA MÁY TRIAL 4H</button>
                        </div>
                        <div id="theme-row">
                            <label for="theme-select" style="color:#fff;font-size:13px;">Theme:</label>
                            <select id="theme-select"></select>
                            <button id="theme-add-btn" type="button">+ Thêm theme</button>
                        </div>
                    </div>
                </div>
                <div id="modal-footer">
                    Phát triển bởi Hoàng Anh<br>
                    <small>Phiên bản 4.7</small>
                </div>
            </div>
        </div>
        <div id="ugphone-global-notify"></div>
        <div id="theme-popup-outer">
            <div id="theme-popup-inner">
                <button id="theme-popup-close" title="Đóng">×</button>
                <div id="theme-popup-title">Thêm / Update Theme</div>
                <input id="theme-input-name" placeholder="Tên theme">
                <input id="theme-input-url" placeholder="Link mp4">
                <div id="theme-popup-msg"></div>
                <div id="theme-popup-btns">
                    <button id="theme-popup-ok">Lưu theme</button>
                    <button id="theme-popup-cancel">Hủy</button>
                </div>
            </div>
        </div>
    `;

    // ==== DOM refs ====
    const overlay = shadow.getElementById('overlay');
    const bubble = shadow.getElementById('bubble');
    const closeModal = shadow.getElementById('close-modal');
    const themeSelect = shadow.getElementById('theme-select');
    const themeAddBtn = shadow.getElementById('theme-add-btn');
    const videoBg = shadow.getElementById('modal-bg-video');
    const btnUpload = shadow.getElementById('upload');
    const btnSubmit = shadow.getElementById('submit');
    const btnLogout = shadow.getElementById('logout');
    const btnCopy = shadow.getElementById('copy');
    const btnAuto = shadow.getElementById('auto-trial');
    const txtArea = shadow.getElementById('input');
    const messageEl = shadow.getElementById('message');
    // Theme popup
    const themePopup = shadow.getElementById('theme-popup-outer');
    const themePopupInputName = shadow.getElementById('theme-input-name');
    const themePopupInputUrl = shadow.getElementById('theme-input-url');
    const themePopupMsg = shadow.getElementById('theme-popup-msg');
    const themePopupOk = shadow.getElementById('theme-popup-ok');
    const themePopupCancel = shadow.getElementById('theme-popup-cancel');
    const themePopupClose = shadow.getElementById('theme-popup-close');
    const globalNotifyBox = shadow.getElementById('ugphone-global-notify');

    // ==== Notify helpers ====
    function showGlobalNotify(msg, color="#ffe666", time=3000) {
        globalNotifyBox.textContent = msg;
        globalNotifyBox.style.color = color;
        globalNotifyBox.style.display = "block";
        clearTimeout(globalNotifyBox._hideTimer);
        globalNotifyBox._hideTimer = setTimeout(()=>{
            globalNotifyBox.style.display = "none";
        }, time);
    }
    function showMsg(msg, color="#ffe666", timeout=2600) {
        messageEl.textContent = msg;
        messageEl.style.color = color;
        setTimeout(()=>{if(messageEl.textContent===msg)messageEl.textContent=''}, timeout);
        showGlobalNotify(msg, color, timeout+600);
    }
    function showThemeNotify(msg, color="#92ffb3", timeout=3500) {
        showMsg("[Theme] "+msg, color, timeout);
    }

    // ==== Theme video background ====
    function setThemeVideo(idx, noSave) {
        if (!videoBg) return;
        if (typeof idx !== "number" || !themes[idx] || !themes[idx].url) {
            videoBg.style.display = "none";
            videoBg.src = "";
            return;
        }
        videoBg.src = themes[idx].url;
        videoBg.currentTime = 0;
        videoBg.loop = true;
        videoBg.muted = true;
        videoBg.style.display = "block";
        try { videoBg.play(); } catch(e) {}
        if(!noSave) localStorage.setItem('ugphone_video_theme', idx);
    }
    // ==== Load/save theme from GitHub ====
    async function loadThemesFromGitHub(callback) {
        showThemeNotify("Đang tải theme từ GitHub...");
        try {
            const r = await fetch(`https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/contents/${GITHUB_FILE}`, {
                headers: {
                    "Authorization": "token " + GITHUB_TOKEN,
                    "Accept": "application/vnd.github.v3+json"
                }
            });
            if (!r.ok) {
                const errText = await r.text();
                showThemeNotify(`[Theme] Lỗi HTTP ${r.status}: ${errText}`,"#e74c3c", 4000);
                if(callback) callback(false);
                return;
            }
            const j = await r.json();
            if (j.content) {
                let arr = [];
                try {
                    arr = JSON.parse(decodeURIComponent(escape(atob(j.content))));
                } catch (e) { arr = []; }
                if (Array.isArray(arr)) {
                    themes = arr;
                    let storedIdx = parseInt(localStorage.getItem('ugphone_video_theme'), 10);
                    if (!isNaN(storedIdx) && storedIdx >= 0 && storedIdx < themes.length) {
                        themeIndex = storedIdx;
                    } else {
                        themeIndex = 0;
                    }
                    renderThemeSelect();
                    showThemeNotify("Danh sách theme đã làm mới từ Github!","#92ffb3");
                    if(callback) callback(true);
                    return;
                }
            }
            showThemeNotify("Không lấy được theme hoặc file theme không tồn tại.","#e74c3c", 4000);
            showPopupMsg("Không lấy được theme hoặc file theme không tồn tại.","#e74c3c");
            if(callback) callback(false);
        } catch(e) {
            showThemeNotify("Lỗi tải theme: "+(e.message||e),"#e74c3c", 4000);
            showPopupMsg("Lỗi tải theme: "+(e.message||e),"#e74c3c");
            if(callback) callback(false);
        }
    }
    async function saveThemesToGitHub(callback) {
        showPopupMsg("Đang lưu lên GitHub...", "#ffe666");
        showThemeNotify("Đang lưu theme lên GitHub...", "#ffe666", 3500);
        const content = btoa(unescape(encodeURIComponent(JSON.stringify(themes))));
        let sha = "";
        try {
            let r = await fetch(`https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/contents/${GITHUB_FILE}`, {
                headers: {Authorization: "token "+GITHUB_TOKEN}
            });
            if(r.ok){ let j = await r.json(); sha = j.sha||""; }
        } catch{}
        let body = {
            message: "Update themes (array 1 dòng)",
            content: content
        };
        if(sha) body.sha = sha;
        fetch(`https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/contents/${GITHUB_FILE}`, {
            method: "PUT",
            headers: {
                "Authorization": "token "+GITHUB_TOKEN,
                "Accept": "application/vnd.github.v3+json"
            },
            body: JSON.stringify(body)
        }).then(r=>r.json()).then(j=>{
            if(j.content) {
                showThemeNotify("Đã lưu theme lên GitHub!","#80ffb3", 3500);
                showPopupMsg("Đã lưu lên Github!","#80ffb3");
                if(callback) callback(true);
            }
            else {
                showThemeNotify("Lỗi khi lưu theme: "+(j.message||"Không rõ"),"#e74c3c", 4000);
                showPopupMsg("Lỗi khi lưu: "+(j.message||"Không rõ"),"#e74c3c");
                if(callback) callback(false);
            }
        }).catch(e=>{
            showThemeNotify("Lỗi Github: "+e.message,"#e74c3c", 4000);
            showPopupMsg("Lỗi: "+e.message,"#e74c3c");
            if(callback) callback(false);
        });
    }

    function renderThemeSelect() {
        themeSelect.innerHTML = "";
        if (!themes.length) {
            const opt = document.createElement('option');
            opt.value = "-1";
            opt.textContent = "(Chưa có theme)";
            themeSelect.appendChild(opt);
            setThemeVideo(null, true);
            return;
        }
        themes.forEach((t,i) => {
            const opt = document.createElement('option');
            opt.value = i;
            opt.textContent = t.name;
            themeSelect.appendChild(opt);
        });
        if (themeIndex >= themes.length) themeIndex = 0;
        themeSelect.value = themeIndex;
        setThemeVideo(themeIndex, true);
    }

    // ==== UI logic ====
    bubble.addEventListener('click', () => {
        overlay.style.display = 'flex';
        loadThemesFromGitHub(function(success) {
            if (success && themeSelect.value) {
                let storedIdx = parseInt(localStorage.getItem('ugphone_video_theme'), 10);
                if (!isNaN(storedIdx) && storedIdx >= 0 && storedIdx < themes.length) {
                    themeIndex = storedIdx;
                } else {
                    themeIndex = 0;
                }
                themeSelect.value = themeIndex;
                setThemeVideo(themeIndex, true);
                showThemeNotify("Danh sách theme đã làm mới từ Github!", "#aaffb3", 2600);
            }
        });
        setTimeout(() => {
            if(videoBg && videoBg.src) videoBg.play().catch(() => {});
        }, 120);
    });
    closeModal.addEventListener('click', () => { overlay.style.display = 'none'; });

    themeSelect.addEventListener('change', function() {
        themeIndex = parseInt(this.value,10);
        setThemeVideo(themeIndex);
        localStorage.setItem('ugphone_video_theme', themeIndex);
        showThemeNotify("Đã đổi theme nền video!", "#afe7ff", 2000);
    });

    // Thêm theme popup
    themeAddBtn.onclick = () => {
        themePopup.style.display = 'flex';
        themePopupInputName.value = "";
        themePopupInputUrl.value = "";
        showPopupMsg("Nhập tên và link mp4 theme mới","#ffe666");
        setTimeout(() => { themePopupInputName.focus(); }, 120);
    };
    function showPopupMsg(msg, color="#ffe666") {
        themePopupMsg.textContent = msg;
        themePopupMsg.style.color = color;
    }
    themePopupClose.onclick = themePopupCancel.onclick = () => {
        themePopup.style.display = 'none';
        themePopupMsg.textContent = '';
    };
    themePopupOk.onclick = async () => {
        const pname = themePopupInputName.value.trim();
        const purl  = themePopupInputUrl.value.trim();
        if (!pname || !purl) return showPopupMsg("Nhập đầy đủ tên và url", "#ffb366");
        if (!/^https?:\/\/.+\.mp4(\?.*)?$/i.test(purl)) return showPopupMsg("Link mp4 không hợp lệ", "#e74c3c");
        let idx = themes.findIndex(t => t.name.toLowerCase() === pname.toLowerCase() || t.url === purl);
        if (idx >= 0) themes.splice(idx, 1);
        themes.push({name: pname, url: purl});
        renderThemeSelect();
        themeSelect.value = (themes.length-1) + "";
        themeIndex = themes.length-1;
        setThemeVideo(themeIndex);
        localStorage.setItem('ugphone_video_theme', themeIndex);
        showPopupMsg("Đang lưu lên GitHub...", "#ffe666");
        await saveThemesToGitHub();
        showPopupMsg("Đã thêm/cập nhật theme mới và lưu Github!", "#80ffb3");
        showThemeNotify("Đã thêm/cập nhật theme mới và lưu Github!", "#80ffb3", 3500);
        setTimeout(()=>{themePopup.style.display='none';}, 1200);
    };

    // Upload theme JSON
    btnUpload.onclick = () => {
        const fileInput = document.createElement('input');
        fileInput.type = 'file';
        fileInput.accept = '.json,application/json';
        fileInput.onchange = async (e) => {
            const file = fileInput.files[0];
            if (!file) return;
            const text = await file.text();
            try {
                const arr = JSON.parse(text);
                if (Array.isArray(arr)) {
                    themes = arr;
                    renderThemeSelect();
                    showThemeNotify('Đã tải theme từ file JSON!');
                } else {
                    showThemeNotify('File không đúng định dạng theme (array)!', "#e74c3c");
                }
            } catch (err) {
                showThemeNotify('Lỗi đọc file JSON: ' + err.message, "#e74c3c");
            }
        };
        fileInput.click();
    };

    // Nhập localStorage
    btnSubmit.addEventListener('click', () => {
        const text = txtArea.value.trim();
        if (!text) { showMsg('Vui lòng nhập JSON!', "#e74c3c", 3000); return; }
        let obj;
        try { obj = JSON.parse(text); }
        catch (e) { showMsg('JSON không hợp lệ!', "#e74c3c", 3500); return; }
        Object.entries(obj).forEach(([k, v]) => localStorage.setItem(k, typeof v === 'object' ? JSON.stringify(v) : String(v)));
        showMsg('Đã import localStorage', "#bcffbe", 2600);
        setTimeout(() => { overlay.style.display = 'none'; location.reload(); }, 600);
    });

    btnLogout.addEventListener('click', () => {
        localStorage.clear();
        showMsg('Đã logout và xóa localStorage!', "#e74c3c", 2500);
        setTimeout(() => { overlay.style.display = 'none'; location.reload(); }, 600);
    });

    btnCopy.addEventListener('click', () => {
        const data = {};
        for (const k of orderedKeys) {
            const v = localStorage.getItem(k);
            if (v !== null) data[k] = v;
        }
        const json = JSON.stringify(data, null, 2);
        (navigator.clipboard?.writeText
            ? navigator.clipboard.writeText(json)
            : new Promise((res, rej) => {
                const ta = document.createElement('textarea');
                ta.value = json; document.body.appendChild(ta); ta.select();
                try { document.execCommand('copy'); res(); } catch (e) { rej(e); }
                document.body.removeChild(ta);
            })
        ).then(() => showMsg('Đã copy localStorage!', "#b3ecfb", 2000))
         .catch(() => showMsg('Copy thất bại', "#e74c3c", 3000));
    });

    // Auto mua máy trial
    btnAuto.addEventListener('click', async () => {
        if (btnAuto.disabled) return;
        showMsg("Đang tự động mua gói trial 4h…", "#ffe666", 6000);
        btnAuto.disabled = true;
        btnAuto.innerHTML = '<span class="spinner"></span> AUTO MUA MÁY TRIAL 4H';
        try {
            let domain = window.location.hostname;
            if (!(domain === 'www.ugphone.com' || domain === 'ugphone.com')) {
                showMsg("Vui lòng vào trang ugphone.com","#e74c3c",3500);
                btnAuto.disabled = false; btnAuto.textContent = "AUTO MUA MÁY TRIAL 4H";
                return;
            }
            const mqtt = JSON.parse(localStorage.getItem('UGPHONE-MQTT') || '{}');
            const headers = {
                'accept': 'application/json, text/plain, */*',
                'accept-language': 'vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7',
                'content-type': 'application/json;charset=UTF-8',
                'lang': 'vi',
                'terminal': 'web',
                'access-token': mqtt.access_token,
                'login-id': mqtt.login_id
            };
            await xhrRequest('POST', 'https://www.ugphone.com/api/apiv1/fee/newPackage', {}, headers);
            const json1 = await xhrRequest('GET', 'https://www.ugphone.com/api/apiv1/info/configList2', null, headers);
            let list1 = Array.isArray(json1.data?.list) ? json1.data.list : json1.data;
            if (!Array.isArray(list1)) {
                const arr = Object.values(json1.data || {}).find(v => Array.isArray(v));
                list1 = Array.isArray(arr) ? arr : [];
            }
            if (!list1.length || !Array.isArray(list1[0].android_version) || !list1[0].android_version.length)
                throw new Error('Không lấy được config_id');
            const config_id = list1[0].android_version[0].config_id;
            const json2 = await xhrRequest('POST', 'https://www.ugphone.com/api/apiv1/info/mealList', { config_id }, headers);
            let subscriptions = [];
            let subData = json2.data?.list;
            if (Array.isArray(subData)) subscriptions = subData.flatMap(i => i.subscription || []);
            else if (subData?.subscription) subscriptions = subData.subscription;
            if (!subscriptions.length) throw new Error('Không lấy được subscription');
            let success = false;
            while (!success) {
                for (const net_id of subscriptions.map(o => o.network_id)) {
                    const priceJson = await xhrRequest('POST', 'https://www.ugphone.com/api/apiv1/fee/queryResourcePrice', {
                        order_type: 'newpay', period_time: '4', unit: 'hour', resource_type: 'cloudphone',
                        resource_param: { pay_mode: 'subscription', config_id, network_id: net_id, count: 1, use_points: 3, points: 250 }
                    }, headers);
                    const amount_id = priceJson.data?.amount_id;
                    if (!amount_id) continue;
                    await new Promise(r=>setTimeout(r,5000));
                    const payJson = await xhrRequest('POST', 'https://www.ugphone.com/api/apiv1/fee/payment', { amount_id, pay_channel: 'free' }, headers);
                    if (payJson.code === 200) {
                        showMsg("Đã mua thành công trial 4h!", "#b3ffb3", 4000);
                        success = true;
                        location.reload();
                        break;
                    }
                }
            }
        } catch (e) {
            showMsg("Lỗi auto mua: "+e.message, "#e74c3c", 4000);
        } finally {
            btnAuto.disabled = false;
            btnAuto.textContent = "AUTO MUA MÁY TRIAL 4H";
        }
    });

    function xhrRequest(method, url, data, headers) {
        return new Promise((resolve, reject) => {
            const xhr = new XMLHttpRequest();
            xhr.open(method, url, true);
            xhr.withCredentials = true;
            for (const key in headers) xhr.setRequestHeader(key, headers[key]);
            xhr.onreadystatechange = function () {
                if (xhr.readyState === 4) {
                    if (xhr.status >= 200 && xhr.status < 300) {
                        try { resolve(JSON.parse(xhr.responseText)); }
                        catch (e) { reject(e); }
                    } else reject(new Error('Status ' + xhr.status));
                }
            };
            xhr.send(data ? JSON.stringify(data) : null);
        });
    }

    // Tải themes lần đầu khi load trang (để select có dữ liệu)
    loadThemesFromGitHub();
})();
