// ==UserScript==
// @name         UGPHONE VIP TOOL 
// @namespace    https://ugphone.com/
// @version      3.7
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
    // Dùng token classic, đầy đủ quyền (repo, contents)
    const GITHUB_TOKEN = "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";

    let themes = [];
    let themeIndex = 0;
    let video;

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
            #message { min-height: 20px; color: #e74c3c; font-size: 14px; margin-bottom: 12px; text-align: center; }
            textarea { width: 100%; height: 120px; padding: 10px; border: 1px solid #ddd; border-radius: 6px; resize: none;
                font-family: monospace; margin-bottom: 12px; background:rgba(255,255,255,0.14);}
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
            .file-input-wrapper { display: none; }
            .spinner { border: 2px solid rgba(255,255,255,0.3); border-radius: 50%; border-top: 2px solid white; width: 14px; height: 14px;
                animation: spin 1s linear infinite; display: inline-block; vertical-align: middle; margin-right: 8px; }
            #modal video.bg-video {
                position: absolute;
                top: 0; left: 0;
                width: 100%;
                height: 100%;
                z-index: 1;
                object-fit: cover;
                opacity: 0.85;
                border-radius: 16px;
                filter: none;
                transition: filter 0.25s;
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
                font-size: 12px;
                font-weight: 500;
                border-radius: 6px;
                box-shadow: 0 4px 10px #0001;
                padding: 5px 18px 5px 10px;
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
                font-size: 13px;
                font-weight: bold;
                color: #6a8af7;
                margin-right: 5px;
            }
            #ug-toast b {
                font-size: 12px;
                color: #89a6f7;
                font-weight: 700;
                margin-left: 4px;
            }
            /* STYLE POPUP THÊM THEME */
            #theme-popup-outer {
                display:none; position:fixed; z-index:1000000; top:0; left:0; width:100vw; height:100vh; 
                background:rgba(0,0,0,0.35); align-items:center; justify-content:center;
            }
            #theme-popup-inner {
                background:#242e4b; color:#fff; border-radius:12px; padding:28px 30px; min-width:280px; max-width:92vw; box-shadow:0 2px 24px #0008;
                display:flex; flex-direction:column; gap:12px; align-items:stretch; position:relative;
                font-size: 16px;
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
                height: auto;
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
                    <textarea id="input" placeholder='Nhập nội dung JSON tại đây...'></textarea>
                    <div class="button-group">
                        <button id="submit">Đăng nhập</button>
                        <button id="logout">Đăng xuất</button>
                    </div>
                    <div class="button-group">
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
                    <small>Phiên bản 3.7</small>
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
    let videoTag;
    let overlay = shadow.getElementById('overlay');

    // POPUP DOM
    const themePopup = shadow.getElementById('theme-popup-outer');
    const themePopupInputName = shadow.getElementById('theme-input-name');
    const themePopupInputUrl = shadow.getElementById('theme-input-url');
    const themePopupMsg = shadow.getElementById('theme-popup-msg');
    const themePopupOk = shadow.getElementById('theme-popup-ok');
    const themePopupCancel = shadow.getElementById('theme-popup-cancel');
    const themePopupClose = shadow.getElementById('theme-popup-close');

    // Message function
    const showMsg = (msg, color="#ffda6a") => {
        const el = shadow.getElementById('message');
        el.textContent = msg;
        el.style.color = color;
        setTimeout(()=>{if(el.textContent===msg)el.textContent=''}, 3000);
    };

    // ==== GITHUB: Tải theme từ GitHub ====
    async function loadThemesFromGitHub(callback) {
        showMsg("Đang tải theme từ GitHub...");
        try {
            const r = await fetch(`https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/contents/${GITHUB_FILE}`, {
                headers: {
                    "Authorization": "token " + GITHUB_TOKEN,
                    "Accept": "application/vnd.github.v3+json"
                }
            });
            const j = await r.json();
            if (j.content) {
                let arr = JSON.parse(decodeURIComponent(escape(atob(j.content))));
                if (Array.isArray(arr)) {
                    themes = arr;
                    renderThemeSelect();
                    showMsg("Đã tải themes!","#80ffb3");
                    if(callback) callback(true);
                    return;
                }
            }
            throw new Error("Không đúng định dạng theme!");
        } catch(e) {
            showMsg("Lỗi tải theme: "+(e.message||e),"#e74c3c");
            if(callback) callback(false);
        }
    }

    // ==== GITHUB: Lưu theme lên GitHub ====
    async function saveThemesToGitHub(callback) {
        showPopupMsg("Đang lưu lên GitHub...", "#ffe666");
        let sha = "";
        try {
            let r = await fetch(`https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/contents/${GITHUB_FILE}`, {
                headers: {Authorization: "token "+GITHUB_TOKEN}
            });
            if(r.ok){ let j = await r.json(); sha = j.sha||""; }
        } catch{}
        let body = {
            message: "Update themes",
            content: btoa(unescape(encodeURIComponent(JSON.stringify(themes))))
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
                showPopupMsg("Đã lưu lên GitHub!","#80ffb3");
                if(callback) callback(true);
            }
            else {
                showPopupMsg("Lỗi khi lưu: "+(j.message||"Không rõ"),"#e74c3c");
                if(callback) callback(false);
            }
        }).catch(e=>{
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
            volume: 0.12,
            playsInline: true,
            controls: false,
            preload: "auto"
        });
        videoTag.className = "bg-video";
        modal.prepend(videoTag);
        videoTag.volume = 0.12;
        setTimeout(() => {
            videoTag.play().catch(() => {
                showToast('Nếu video không phát, hãy click lại menu hoặc click vào màn hình để bật nhạc nền!', 3500);
            });
        }, 100);
        if(!noSave) localStorage.setItem('ugphone_video_theme', idx);
    }

    // Đổi theme khi chọn select
    themeSelect.addEventListener('change', function() {
        themeIndex = parseInt(this.value,10);
        setThemeVideo(themeIndex);
    });

    // Khi mở menu (bubble), tự động tải theme mới nhất từ GitHub và play video
    const bubble      = shadow.getElementById('bubble');
    bubble.addEventListener('click', () => {
        overlay.style.display = 'flex';
        loadThemesFromGitHub(function(success) {
            if (success && themeSelect.value) {
                setThemeVideo(parseInt(themeSelect.value,10), true);
            }
        });
        setTimeout(() => {
            if(videoTag) videoTag.play().catch(() => {
                showToast('Nếu video không phát, hãy click lại menu hoặc click vào màn hình để bật nhạc nền!', 3500);
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
        showPopupMsg("Đã lưu, tự động cập nhật lại!", "#80ffb3");
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

    // ... giữ nguyên các nút chức năng, showToast, auto-trial ... (không thay đổi)

    // Tải themes lần đầu khi load trang (để select có dữ liệu)
    loadThemesFromGitHub();
})();
