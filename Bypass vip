// ==UserScript==
// @name          BYPASS.VIP BYPASSER
// @namespace     bypass.vip
// @version       0.3
// @author        bypass.vip
// @description   Bypass ad-links using the bypass.vip API and get to your destination without ads!
// @include       https://linkvertise.com/*
// @include       https://paster.so/*
// @include       https://boost.ink/*
// @include       https://mboost.me/*
// @include       https://bst.gg/*
// @include       https://booo.st/*
// @include       https://socialwolvez.com/*
// @include       https://www.sub2get.com/*
// @include       https://sub2get.com/*
// @include       https://v.gd/*
// @include       https://unlocknow.net/*
// @include       https://sub2unlock.com/*
// @include       https://sub2unlock.net/*
// @include       https://sub2unlock.io/*
// @include       https://sub4unlock.io/*
// @include       https://rekonise.com/*
// @include       https://adfoc.us/*
// @include       https://bstlar.com/*
// @include       https://work.ink/*
// @include       https://workink.net/*
// @include       https://cety.app/*
// @grant         GM_addStyle
// @downloadURL   https://raw.githubusercontent.com/bypass-vip/userscript/master/bypass-vip.user.js
// @updateURL     https://raw.githubusercontent.com/bypass-vip/userscript/master/bypass-vip.user.js
// @homepageURL   https://bypass.vip
// @icon          https://www.google.com/s2/favicons?domain=bypass.vip&sz=64
// @run-at document-idle
// ==/UserScript==

GM_addStyle(`
.bypass-vip-logo {
    width: 48px;
    height: 48px;
    transition: transform 0.3s ease-in-out;
}

.bypass-vip-logo:hover {
    transform: scale(1.1);
}

.bypass-vip-toast-container {
    font-family: 'Montserrat', sans-serif;
    position: fixed;
    bottom: 20px;
    left: 20px;
    max-width: 50%;
    max-height: 100%;
    background: linear-gradient(145deg, rgba(50, 50, 50, 0.9), rgba(30, 30, 30, 0.9));
    color: white;
    backdrop-filter: blur(10px);
    border-radius: 12px;
    overflow: hidden;
    box-shadow: 0 4px 10px rgba(0, 0, 0, 0.4);
    z-index: 2147483648;
    animation: fadeIn 0.5s ease-out;
}

@keyframes fadeIn {
    from {
        opacity: 0;
        transform: translateY(20px);
    }
    to {
        opacity: 1;
        transform: translateY(0);
    }
}

.bypass-vip-toast-header {
    background: rgba(0, 0, 0, 0.85);
    color: white;
    text-align: center;
    padding: 10px;
    font-weight: bold;
    display: flex;
    justify-content: space-between;
    align-items: center;
}

.bypass-vip-toast-actions button {
    margin-top: 15px;
    border: none;
    cursor: pointer;
    border-radius: 8px;
    min-width: 25%;
    padding: 8px 12px;
    background: rgba(255, 255, 255, 0.2);
    color: white;
    transition: background 0.3s ease;
}

.bypass-vip-toast-actions button:hover {
    background: rgba(255, 255, 255, 0.4);
}

.bypass-vip-toast-content {
    padding: 15px;
    overflow-y: auto;
    word-wrap: break-word;
    max-height: 200px;
    text-align: center;
    font-size: 16px;
}

.bypass-vip-toast-loader {
    width: 48px;
    height: 48px;
    border: 5px solid rgba(255, 255, 255, 0.5);
    border-bottom-color: transparent;
    border-radius: 50%;
    display: inline-block;
    box-sizing: border-box;
    animation: rotation 1s linear infinite;
}

@keyframes rotation {
    0% {
        transform: rotate(0deg);
    }
    100% {
        transform: rotate(360deg);
    }
}
`);

document.querySelector("body").innerHTML += `
    <div class="bypass-vip-toast-container">
        <div class="bypass-vip-toast-header">
            <img src="https://bypass.vip/assets/img/logo-light-nobg.png" alt="LOGO" class="bypass-vip-logo">
            BYPASS.VIP
        </div>
        <div class="bypass-vip-toast-content">
            <div class="bypass-vip-toast-result"></div>
            <div class="bypass-vip-toast-loading">
                <span class="bypass-vip-toast-loader"></span>
                <p>Loading bypass...</p>
            </div>
            <div class="bypass-vip-toast-actions" hidden>
                <button id="bypass-vip-copy">Copy</button>
                <button id="bypass-vip-open" hidden>Open</button>
            </div>
        </div>
    </div>
`;

fetch(`https://api.bypass.vip/bypass?url=${encodeURIComponent(window.location.href)}`)
    .then(response => response.json())
    .then(data => {
        setTimeout(() => {
            document.querySelector(".bypass-vip-toast-loading").hidden = true;
            if (data.status == 'success') {
                document.querySelector(".bypass-vip-toast-actions").hidden = false;
                document.querySelector(".bypass-vip-toast-result").innerText = data.result;
                try {
                    new URL(data.result);
                    document.querySelector("#bypass-vip-open").hidden = false;
                } catch (e) {}
            } else {
                document.querySelector(".bypass-vip-toast-result").innerText = data.message;
            }
        }, 2000); // Tự động mở sau 2 giây
    })
    .catch(err => {
        alert('Error bypassing link! The error has been logged to the console.');
        console.error('Fetch Error:', err);
    });

document.querySelector("#bypass-vip-copy").addEventListener("click", () => {
    navigator.clipboard.writeText(document.querySelector(".bypass-vip-toast-result").innerText)
    alert('Content has been copied to your clipboard');
});
document.querySelector("#bypass-vip-open").addEventListener("click", () => {
    window.location.href = document.querySelector(".bypass-vip-toast-result").innerText
});
