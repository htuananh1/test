// ==UserScript==
// @name         UGPHONE VIP TOOL 
// @namespace    https://ugphone.com/
// @version      4.4
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
    const GITHUB_TOKEN = "Token";

    let themes = [];
    let themeIndex = 0;
    let videoTag;

    const config = {
        bubbleIcon: 'https://cdn-icons-png.flaticon.com/512/1995/1995485.png',
        autoBtnText: 'AUTO MUA MÁY TRIAL 4H',
        themeColor: '#4a6bdf',
        secondaryColor: '#f0f2f5'
    };

    const orderedKeys = [
        "ugPhoneLang","ugBrowserId","UGPHONE-ID","UGrightSlideTips","hadAgreePolicy","_gcl_ls","UGPHONE-Token","UGPHONE-MQTT"
    ];

    const host = document.createElement('div');
    host.id = 'ugphone-vip-tool';
    document.body.appendChild(host);

    const shadow = host.attachShadow({ mode: 'open' });

    // BẢNG THÔNG BÁO NGOÀI MENU
    const globalNotifyBox = document.createElement('div');
    globalNotifyBox.id = 'ugphone-global-notify';
    globalNotifyBox.style.cssText = `
        position:fixed;top:22px;right:85px;z-index:10000000;
        min-width:240px;max-width:400px;
        background:rgba(33,39,68,0.98);
        color:#ffe666;
        font-size:15px;
        font-weight:bold;
        border-radius:8px;
        box-shadow:0 4px 24px #0006;
        padding:10px 22px 10px 16px;
        display:none;
        align-items:center;
        gap:10px;
        border:2px solid #4a6bdf;
        transition: all .22s;
        pointer-events:none;
        text-align:left;
        white-space:pre-line;
    `;
    document.body.appendChild(globalNotifyBox);

    function showGlobalNotify(msg, color="#ffe666", time=3100) {
        globalNotifyBox.textContent = msg;
        globalNotifyBox.style.color = color;
        globalNotifyBox.style.display = "block";
        clearTimeout(globalNotifyBox._hideTimer);
        globalNotifyBox._hideTimer = setTimeout(()=>{
            globalNotifyBox.style.display = "none";
        }, time);
    }

    // SHADOW DOM UI
    shadow.innerHTML = `
        <style>
            :host { all: initial; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
            #bubble { position: fixed; top: 20px; right: 20px; width: 50px; height: 50px; border-radius: 50%;
                background: ${config.themeColor}; background-image: url('${config.bubbleIcon}');
                background-size: 60%; background-repeat: no-repeat; background-position: center; cursor: pointer;
                box-shadow: 0 4px 12px rgba(0,0,0,0.15); z-index: 9999; transition: all 0.3s ease; border: 2px solid white; }
            #bubble:hover { transform: scale(1.1); box-shadow: 0 6px 16px rgba(0,0,0,0.2); }
            #overlay { position: fixed; top: 0; left: 0; width: 100vw; height: 100vh; background: rgba(0,0,0,0.5);
                display: none; justify-content: center; align-items: center; z-index: 9998; }
            #modal { width: 380px; background: transparent; border-radius: 16px; box-shadow: 0 8px 32px rgba(0,0,0,0.2);
                overflow: hidden; animation: fadeIn 0.3s ease; position:relative; }
            @keyframes fadeIn { from { opacity: 0; transform: translateY(-20px); } to { opacity: 1; transform: translateY(0); } }
            #modal-header { background: rgba(74,107,223,0.92); color: white; padding: 16px; font-size: 18px; font-weight: bold;
                display: flex; justify-content: space-between; align-items: center; z-index:2; position:relative; border-radius: 16px 16px 0 0;}
            #modal-content {
                padding: 20px;
                position:relative;
                z-index:2;
                background: rgba(255,255,255,0.03);
                box-shadow: 0 4px 30px rgba(0, 0, 0, 0.08);
                border-radius: 0 0 16px 16px;
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
            }
            #theme-row { display: flex; align-items: center; gap: 10px; margin-top: 0; margin-bottom: 0; justify-content: flex-end;}
            #theme-select {
                filter: blur(2px) brightness(0.7) grayscale(0.2);
                opacity: 0.72;
                transition: filter 0.25s, opacity 0.25s;
            }
            #theme-select:focus, #theme-select:hover {
                filter: none;
                opacity: 1;
            }
            #theme-select { font-size: 14px; padding: 4px 8px; border-radius: 6px; border: 1px solid #ddd;}
            #theme-add-btn { flex: 0 0 auto; padding: 4px 16px; font-size: 13px; border-radius: 6px;
                background: #4a6bdf; color: #fff; border: none; cursor: pointer; font-weight: bold; margin: 0 0 0 10px;}
            #theme-add-btn:hover { background: #304fb7;}
            #message { min-height: 22px; color: #e74c3c; font-size: 15px; margin-bottom: 12px; text-align: center; background:rgba(0,0,0,0.10); border-radius:6px; padding:4px 6px;}
            textarea { width: 100%; height: 120px; padding: 10px; border: 1px solid #ddd; border-radius: 6px; resize: none;
                font-family: monospace; margin-bottom: 12px; background:rgba(255,255,255,0.14); }
            .button-group { display: flex; gap: 8px; margin-bottom: 12px; }
            button {
                flex: 1;
                padding: 10px;
                border: none;
                border-radius: 6px;
                cursor: pointer;
                font-weight: 500;
                transition: all 0.2s;
                opacity: 0.93;
                background: rgba(74,107,223,0.13);
                color: #fff;
            }
            button:hover {
                opacity: 1;
                background: #4a6bdf;
                color: #fff;
                box-shadow: 0 2px 8px rgba(74,107,223,0.2);
                transform: translateY(-2px) scale(1.04);
            }
            #submit { background: rgba(74,107,223,0.13); }
            #logout { background: rgba(231,76,60,0.13); }
            #copy { background: rgba(46,204,113,0.13); }
            #cancel { background: rgba(149,165,166,0.13); }
            #auto-trial { width: 100%; background: rgba(243,156,18,0.18); color: white; font-weight: bold; margin-top: 8px; }
            #modal-footer {
                text-align: center;
                padding: 12px;
                font-size: 12px;
                color: #fff;
                border-top: 1px solid rgba(240,242,245,0.18);
                position:relative;
                z-index:2;
                background: rgba(74,107,223,0.08);
                border-radius: 0 0 16px 16px;
            }
            #ug-toast {
                min-width: 120px;
                max-width: 380px;
                position: fixed;
                left: 50%;
                top: 34px;
                transform: translateX(-50%);
                background: #232b3bcc;
                color: #eaf1ff;
                font-size: 13px;
                font-weight: 500;
                border-radius: 6px;
                box-shadow: 0 4px 10px #0001;
                padding: 6px 18px 6px 10px;
                z-index: 10000;
                display: flex;
                align-items: center;
                gap: 7px;
                border: 1px solid #4a6bdf;
                pointer-events: none;
                opacity: 0.98;
                transition: opacity .22s;
                letter-spacing: 0.01em;
                justify-content: center;
                flex-direction: row;
            }
            #ug-toast .ug-toast-icon {
                font-size: 16px;
                font-weight: bold;
                color: #6a8af7;
                margin-right: 5px;
            }
            #ug-toast b {
                font-size: 13px;
                color: #89a6f7;
                font-weight: 700;
                margin-left: 4px;
            }
            #theme-popup-outer {
                display:none; position:fixed; z-index:1000001; top:0; left:0; width:100vw; height:100vh; 
                background:rgba(0,0,0,0.45); align-items:center; justify-content:center;
            }
            #theme-popup-inner {
                background:#242e4b; color:#fff; border-radius:12px; padding:28px 30px; min-width:280px; max-width:92vw; box-shadow:0 2px 24px #0008;
                display:flex; flex-direction:column; gap:12px; align-items:stretch; position:relative;
                font-size: 16px;
                z-index: 1000002;
            }
            #theme-popup-inner input {
                padding:7px 11px;
                border-radius:7px;
                font-size:15px;
                border:1.5px solid #4a6bdf;
                color:#fff;
                background:#1a2034;
                margin-bottom: 6px;
                outline: none;
                transition: border-color .2s;
            }
            #theme-popup-inner input:focus {
                border-color: #6a93ff;
            }
            #theme-popup-title {
                font-size:19px;
                margin-bottom:5px;
                font-weight:bold;
                color:#ffda6a;
                text-align:center;
            }
            #theme-popup-msg {
                min-height: 22px;
                color: #f7f191;
                background: #2b2c36;
                border-radius: 5px;
                padding: 6px 9px;
                margin: 2px 0 0 0;
                font-size: 14px;
                text-align: center;
                word-break: break-word;
                white-space: pre-wrap;
            }
            #theme-popup-close {
                position:absolute;top:7px;right:15px;background:none;border:none;font-size:23px;color:#fff;cursor:pointer;line-height:1;
            }
            #theme-popup-btns {
                display:flex;gap:8px;margin-top:13px;
            }
            #theme-popup-ok {
                flex:1;background:#4a6bdf;border:none;border-radius:7px;color:#fff;font-weight:bold;padding:8px 0;font-size:16px;cursor:pointer;
            }
            #theme-popup-cancel {
                flex:1;background:#555b75;border:none;border-radius:7px;color:#fff;padding:8px 0;font-size:16px;cursor:pointer;
            }
            #theme-popup-ok:hover {background:#2c4ac2;}
            #theme-popup-cancel:hover {background:#313448;}
        </style>
        <div id="bubble" title="UGPHONE VIP TOOL"></div>
        <div id="overlay">
            <div id="modal">
                <div id="modal-header">
                    <span>UGPHONE VIP TOOL</span>
                    <span id="close-modal" style="cursor:pointer">×</span>
                </div>
                <div id="modal-content">
                    <div id="message"></div>
                    <textarea id="input" placeholder='Nhập nội dung JSON tại đây...' style="display:block;margin:auto;"></textarea>
                    <div class="button-group" style="justify-content:center;">
                        <button id="submit">Đăng nhập</button>
                        <button id="logout">Đăng xuất</button>
                    </div>
                    <div class="button-group" style="justify-content:center;">
                        <button id="copy">Sao chép</button>
                    </div>
                    <button id="auto-trial">${config.autoBtnText}</button>
                    <div id="theme-row">
                        <label for="theme-select" style="color:#fff">Theme:</label>
                        <select id="theme-select"></select>
                        <button id="theme-add-btn" type="button">+ Thêm theme</button>
                    </div>
                </div>
                <div id="modal-footer">
                    Phát triển bởi Hoàng Anh<br>
                    <small>Phiên bản 4.4</small>
                </div>
            </div>
        </div>
        <div id="ug-toast" style="display:none"></div>
        <!-- POPUP THÊM THEME -->
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

    // Video logic
    const modal = shadow.getElementById('modal');
    const themeSelect = shadow.getElementById('theme-select');
    const themeAddBtn = shadow.getElementById('theme-add-btn');
    let overlay = shadow.getElementById('overlay');

    // POPUP DOM
    const themePopup = shadow.getElementById('theme-popup-outer');
    const themePopupInputName = shadow.getElementById('theme-input-name');
    const themePopupInputUrl = shadow.getElementById('theme-input-url');
    const themePopupMsg = shadow.getElementById('theme-popup-msg');
    const themePopupOk = shadow.getElementById('theme-popup-ok');
    const themePopupCancel = shadow.getElementById('theme-popup-cancel');
    const themePopupClose = shadow.getElementById('theme-popup-close');

    // Message function - bảng ngoài menu
    function showMsg(msg, color="#ffe666", timeout=2600) {
        showGlobalNotify(msg, color, timeout);
        const el = shadow.getElementById('message');
        el.textContent = msg;
        el.style.color = color;
        el.style.background = "#232b3b";
        setTimeout(()=>{if(el.textContent===msg)el.textContent=''}, timeout);
    }
    // THÔNG BÁO THEME RA NGOÀI
    function showThemeNotify(msg, color="#ffe666", timeout=3200) {
        showGlobalNotify("[Theme] " + msg, color, timeout);
    }

    // ==== GITHUB: Tải theme từ GitHub ====
    async function loadThemesFromGitHub(callback) {
        showThemeNotify("Đang tải theme từ GitHub...");
        try {
            const r = await fetch(`https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/contents/${GITHUB_FILE}`, {
                headers: {
                    "Authorization": "token " + GITHUB_TOKEN,
                    "Accept": "application/vnd.github.v3+json"
                }
            });
            const j = await r.json();
            if (j.content) {
                // Parse as JSON array (1 dòng)
                let arr = [];
                try {
                    arr = JSON.parse(decodeURIComponent(escape(atob(j.content))));
                } catch (e) { arr = []; }
                if (Array.isArray(arr)) {
                    themes = arr;
                    renderThemeSelect();
                    showThemeNotify("Đã tải danh sách theme mới từ Github!","#80ffb3");
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

    // ==== GITHUB: Lưu theme lên GitHub 1 dòng ====
    async function saveThemesToGitHub(callback) {
        showPopupMsg("Đang lưu lên GitHub...", "#ffe666");
        showThemeNotify("Đang lưu theme lên GitHub...", "#ffe666", 3500);
        // Ghi 1 dòng JSON array
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

    // Render select theme
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
        // Đảm bảo index hợp lệ
        if (themeIndex >= themes.length) themeIndex = 0;
        themeSelect.value = themeIndex;
        setThemeVideo(themeIndex, true);
    }

    // Play video theme
    function setThemeVideo(idx, noSave) {
        if (!modal) return;
        if (videoTag) { videoTag.pause(); videoTag.remove(); videoTag = null; }
        if (idx === null || !themes[idx] || !themes[idx].url) return;
        videoTag = document.createElement('video');
        Object.assign(videoTag, {
            src: themes[idx].url,
            autoplay: true,
            loop: true,
            muted: false,
            volume: 1.0,
            playsInline: true,
            controls: true,
            preload: "auto"
        });
        videoTag.className = "bg-video";
        modal.prepend(videoTag);
        videoTag.volume = 1.0;
        setTimeout(() => {
            videoTag.play().catch(() => {
                showThemeNotify('Nếu video không phát, hãy click lại menu hoặc click vào màn hình để bật nhạc nền!', "#ffb366", 4000);
            });
        }, 100);
        if(!noSave) localStorage.setItem('ugphone_video_theme', idx);
    }

    // Đổi theme khi chọn select
    themeSelect.addEventListener('change', function() {
        themeIndex = parseInt(this.value,10);
        setThemeVideo(themeIndex);
        showThemeNotify("Đã đổi theme nền video!", "#afe7ff", 2000);
    });

    // Khi mở menu (bubble), tự động tải theme mới nhất từ GitHub và play video
    const bubble      = shadow.getElementById('bubble');
    bubble.addEventListener('click', () => {
        overlay.style.display = 'flex';
        loadThemesFromGitHub(function(success) {
            if (success && themeSelect.value) {
                setThemeVideo(parseInt(themeSelect.value,10), true);
                showThemeNotify("Danh sách theme đã làm mới từ Github!", "#aaffb3", 2600);
            }
        });
        setTimeout(() => {
            if(videoTag) videoTag.play().catch(() => {
                showThemeNotify('Nếu video không phát, hãy click lại menu hoặc click vào màn hình để bật nhạc nền!', "#ffb366", 4000);
            });
        }, 120);
    });

    const closeModal  = shadow.getElementById('close-modal');
    closeModal.addEventListener('click', () => { overlay.style.display = 'none'; });

    // =========== POPUP THÊM THEME =============
    function showPopupMsg(msg, color="#ffe666") {
        themePopupMsg.textContent = msg;
        themePopupMsg.style.color = color;
        themePopupMsg.style.background = "#2b2c36";
        showThemeNotify(msg, color, 3500);
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
        // Xoá nếu trùng tên hoặc url
        let idx = themes.findIndex(t => t.name.toLowerCase() === pname.toLowerCase() || t.url === purl);
        if (idx >= 0) themes.splice(idx, 1);
        themes.push({name: pname, url: purl});
        renderThemeSelect();
        themeSelect.value = (themes.length-1) + "";
        themeIndex = themes.length-1;
        setThemeVideo(themeIndex);
        showPopupMsg("Đang lưu lên GitHub...", "#ffe666");
        await saveThemesToGitHub();
        showPopupMsg("Đã thêm/cập nhật theme mới và lưu Github!", "#80ffb3");
        showThemeNotify("Đã thêm/cập nhật theme mới và lưu Github!", "#80ffb3", 3500);
        setTimeout(()=>{themePopup.style.display='none';}, 1200);
    };

    // Thay sự kiện nút "Thêm theme" thành mở popup
    themeAddBtn.onclick = () => {
        themePopup.style.display = 'flex';
        themePopupInputName.value = "";
        themePopupInputUrl.value = "";
        showPopupMsg("Nhập tên và link mp4 theme mới","#ffe666");
        setTimeout(() => { themePopupInputName.focus(); }, 120);
    };

    // ============ Các nút còn lại đều thông báo ============
    const messageEl   = shadow.getElementById('message');
    const btnSubmit   = shadow.getElementById('submit');
    const btnLogout   = shadow.getElementById('logout');
    const btnCopy     = shadow.getElementById('copy');
    const btnAuto     = shadow.getElementById('auto-trial');
    const txtArea     = shadow.getElementById('input');
    const ugToast     = shadow.getElementById('ug-toast');

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

    // Toast giữ nguyên
    function showToast(msg, timeout = 1800) {
        ugToast.innerHTML = `<span class="ug-toast-icon">⚡</span>${msg}`;
        ugToast.style.display = 'flex';
        ugToast.style.opacity = 0.98;
        clearTimeout(ugToast._hideTimer);
        clearInterval(ugToast._timerInterval);
        ugToast._hideTimer = setTimeout(() => {
            ugToast.style.opacity = 0;
            setTimeout(() => { ugToast.style.display = 'none'; }, 260);
        }, timeout);
    }

    // Auto mua máy trial thông báo chỉ bảng ngoài menu
    function showAutoToast(startText = "Đang mua gói trial 4h…", icon = "⚡") {
        let seconds = 1;
        showGlobalNotify(startText+` (${seconds}s)`, "#ffe666", 60000);
        ugToast.innerHTML = `<span class="ug-toast-icon">${icon}</span>${startText}<b> (${seconds}s)</b>`;
        ugToast.style.display = 'none'; // Không hiện toast cục bộ nữa
        clearTimeout(ugToast._hideTimer);
        clearInterval(ugToast._timerInterval);
        const timeElem = ugToast.querySelector('b');
        ugToast._timerInterval = setInterval(() => {
            seconds += 1;
            if (timeElem) timeElem.textContent = ` (${seconds}s)`;
            globalNotifyBox.textContent = startText+` (${seconds}s)`;
        }, 1000);
    }
    function clearAutoToast(newMsg = null, timeout = 2000, icon = "✅") {
        clearInterval(ugToast._timerInterval);
        if (newMsg) {
            showGlobalNotify(newMsg, "#b3ffb3", timeout+500);
        } else {
            globalNotifyBox.style.display = "none";
        }
    }

    btnAuto.addEventListener('click', async () => {
        if (btnAuto.disabled) return;
        showAutoToast("Đang tự động mua gói trial 4h…", "⚡");
        btnAuto.disabled = true;
        btnAuto.innerHTML = '<span class="spinner"></span>' + config.autoBtnText;
        try {
            let domain = window.location.hostname;
            if (!(domain === 'www.ugphone.com' || domain === 'ugphone.com')) {
                clearAutoToast('Vui lòng vào trang ugphone.com', 2600, "⚠️");
                showMsg("Vui lòng vào trang ugphone.com","#e74c3c",3500);
                btnAuto.disabled = false; btnAuto.textContent = config.autoBtnText;
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
                        clearAutoToast('Đã mua thành công!', 2200, "✅");
                        showMsg("Đã mua thành công trial 4h!", "#b3ffb3", 4000);
                        success = true;
                        location.reload();
                        break;
                    }
                }
            }
        } catch (e) {
            clearAutoToast('Lỗi: ' + e.message, 2800, "❌");
            showMsg("Lỗi auto mua: "+e.message, "#e74c3c", 4000);
        } finally {
            btnAuto.disabled = false;
            btnAuto.textContent = config.autoBtnText;
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
