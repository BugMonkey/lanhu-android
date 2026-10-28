// ==UserScript==
// @name         lanhu-skill提示词助手
// @namespace    http://tampermonkey.net/
// @version      2.9
// @description  自动提取蓝湖截图/JSON，按场景生成高效 Claude Code 提示词
// @match        https://lanhuapp.com/web/*
// @grant        GM_setClipboard
// ==/UserScript==

(function() {
    'use strict';

    const COMMAND_PREFIX = '/lanhu-android';
    const tabs = [
        { key: 'create', label: '生成页面', task: '生成页面' },
        { key: 'restyle', label: '修改已有页面', task: '修改已有页面' },
        { key: 'check', label: '还原度检查', task: '还原度检查' },
    ];

    const state = {
        activeTab: 'create',
        data: {
            designId: '',
            url: '',
            jsonUrl: '',
        },
        pageName: '',
        target: '',
        customRequirement: '',
        actualScreenshotPath: '',
        pastedScreenshot: null,
        lastCopyText: '',
    };

    function escapeHtml(value) {
        return String(value || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function normalizeWhitespace(value) {
        return String(value || '').replace(/\s+/g, ' ').trim();
    }

    function normalizeFileRef(value) {
        return normalizeWhitespace(value).replace(/^@+/, '');
    }

    function looksLikeFilePath(value) {
        const normalized = normalizeFileRef(value);
        return normalized.includes('/') || /\.(kt|java|xml)$/i.test(normalized);
    }

    function getPageNameFromInput(value) {
        const normalized = normalizeFileRef(value);
        if (!normalized) {
            return '';
        }
        const fileName = normalized.split('/').pop() || normalized;
        return fileName.replace(/\.(kt|java|xml)$/i, '');
    }

    function getActiveTab() {
        return tabs.find(tab => tab.key === state.activeTab) || tabs[0];
    }

    function hasScreenshotNeed() {
        return state.activeTab === 'check';
    }

    function isAttachmentMarker(value) {
        return /^截图附件:/.test(normalizeWhitespace(value));
    }

    function buildScreenshotPromptValue(value) {
        const normalized = normalizeWhitespace(value);
        if (!normalized) {
            return '';
        }
        if (isAttachmentMarker(normalized)) {
            return '';
        }
        return normalized;
    }

    function buildPrompt() {
        const tab = getActiveTab();
        const screenshot = state.data.url || '';
        const jsonUrl = state.data.jsonUrl || '';
        const rawPageInput = normalizeWhitespace(state.pageName);
        const pageFile = looksLikeFilePath(rawPageInput) ? normalizeFileRef(rawPageInput) : '';
        const page = getPageNameFromInput(rawPageInput) || (state.activeTab === 'restyle' ? '<现有页面名>' : '<页面名>');
        const target = normalizeWhitespace(state.target);
        const requirement = normalizeWhitespace(state.customRequirement);
        const actualScreenshot = buildScreenshotPromptValue(state.actualScreenshotPath);
        const parts = [
            `${COMMAND_PREFIX}`,
            `截图地址:${screenshot}`,
            `sketchjson:${jsonUrl}`,
            `页面:${page}`,
            `任务:${tab.task}`,
        ];

        if (pageFile) {
            parts.push(`页面文件:${pageFile}`);
        }

        if (state.activeTab === 'check') {
            parts.push(`检查目标:${target || '<检查目标>'}`);
            if (actualScreenshot) {
                parts.push(`实现截图:${actualScreenshot}`);
            } else if (state.pastedScreenshot) {
                parts.push('实现截图:粘贴的截图附件');
            }
        }

        if (requirement) {
            parts.push(`需求:${requirement}`);
        }

        parts.push('(重要)请先与我讨论需求，确认后再开始编码。');

        return parts.join(' ');
    }

    function showToast(message) {
        let toast = document.getElementById('lanhu-toast');
        if (!toast) {
            toast = document.createElement('div');
            toast.id = 'lanhu-toast';
            toast.style.cssText = [
                'position:fixed',
                'top:20px',
                'left:50%',
                'transform:translateX(-50%)',
                'background:rgba(20,24,31,0.9)',
                'color:#fff',
                'padding:10px 18px',
                'border-radius:8px',
                'z-index:999999',
                'font-size:13px',
                'box-shadow:0 8px 28px rgba(0,0,0,0.18)',
            ].join(';');
            document.body.appendChild(toast);
        }

        toast.textContent = message;
        toast.style.display = 'block';

        setTimeout(() => {
            toast.style.display = 'none';
        }, 2200);
    }

    function installStyle() {
        if (document.getElementById('lanhu-helper-style')) {
            return;
        }

        const style = document.createElement('style');
        style.id = 'lanhu-helper-style';
        style.textContent = `
            #lanhu-card * {
                box-sizing: border-box;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            }
            #lanhu-card button,
            #lanhu-card input,
            #lanhu-card textarea {
                font: inherit;
            }
            .lanhu-field {
                margin-top: 10px;
            }
            .lanhu-label {
                display: flex;
                align-items: center;
                justify-content: space-between;
                margin-bottom: 5px;
                color: #4b5563;
                font-size: 12px;
                font-weight: 600;
            }
            .lanhu-input,
            .lanhu-textarea {
                width: 100%;
                border: 1px solid #d8dee9;
                border-radius: 8px;
                padding: 8px 9px;
                color: #111827;
                background: #fff;
                outline: none;
            }
            .lanhu-input:focus,
            .lanhu-textarea:focus {
                border-color: #2563eb;
                box-shadow: 0 0 0 3px rgba(37,99,235,0.12);
            }
            .lanhu-textarea {
                min-height: 74px;
                resize: vertical;
                line-height: 1.45;
            }
            .lanhu-tabs {
                display: grid;
                grid-template-columns: repeat(3, 1fr);
                gap: 6px;
                padding: 4px;
                background: #eef2f7;
                border-radius: 10px;
            }
            .lanhu-tab {
                border: none;
                border-radius: 8px;
                background: transparent;
                color: #536073;
                cursor: pointer;
                padding: 7px 4px;
                font-size: 12px;
                font-weight: 600;
            }
            .lanhu-tab.active {
                background: #fff;
                color: #0f172a;
                box-shadow: 0 1px 4px rgba(15,23,42,0.1);
            }
            .lanhu-small-btn {
                border: 1px solid #d8dee9;
                border-radius: 7px;
                background: #fff;
                color: #475467;
                cursor: pointer;
                padding: 4px 8px;
                font-size: 12px;
            }
            .lanhu-primary-btn {
                width: 100%;
                border: none;
                border-radius: 9px;
                background: #2563eb;
                color: #fff !important;
                cursor: pointer;
                padding: 10px 12px;
                font-weight: 700;
            }
            .lanhu-prompt {
                width: 100%;
                min-height: 84px;
                max-height: 150px;
                border: 1px solid #d8dee9;
                border-radius: 8px;
                padding: 8px 9px;
                background: #fbfcff;
                color: #111827;
                line-height: 1.45;
                resize: vertical;
            }
        `;
        document.head.appendChild(style);
    }

    function formatBytes(bytes) {
        if (!bytes) {
            return '0 KB';
        }
        if (bytes < 1024 * 1024) {
            return `${Math.max(1, Math.round(bytes / 1024))} KB`;
        }
        return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
    }

    async function copyText(text) {
        if (!text) {
            return;
        }

        if (typeof GM_setClipboard !== 'undefined') {
            GM_setClipboard(text);
            return;
        }

        const textarea = document.createElement('textarea');
        textarea.value = text;
        textarea.style.position = 'fixed';
        textarea.style.opacity = '0';
        document.body.appendChild(textarea);

        textarea.select();
        document.execCommand('copy');
        document.body.removeChild(textarea);
    }

    async function copyPrompt() {
        const promptEl = document.getElementById('lanhu-final-prompt');
        const prompt = promptEl ? promptEl.value : buildPrompt();

        try {
            await copyText(prompt);
            state.lastCopyText = prompt;
            showToast( '已复制提示词');
        } catch (error) {
            console.error('复制失败:', error);
            await copyText(prompt);
            state.lastCopyText = prompt;
            showToast('已复制文字；如需截图，请在 Claude Code 同条消息中附上截图或填写路径');
        }
    }

    function handlePastedImage(event) {
        const items = Array.from((event.clipboardData || {}).items || []);
        const imageItem = items.find(item => item.type && item.type.startsWith('image/'));

        if (!imageItem) {
            return;
        }

        event.preventDefault();
        const file = imageItem.getAsFile();
        if (!file) {
            showToast('未能读取截图');
            return;
        }

        state.pastedScreenshot = {
            name: file.name || 'clipboard-image.png',
            size: file.size,
            type: file.type,
        };
        state.actualScreenshotPath = `截图附件:${file.type || 'image'} ${formatBytes(file.size)}`;
        renderContent();
        showToast('已回显截图附件；粘到 Claude Code 后仍需同条消息带上截图附件');
    }

    function clearField(key) {
        state[key] = '';
        if (key === 'actualScreenshotPath') {
            state.pastedScreenshot = null;
        }
        renderContent();
    }

    function bindInput(id, key) {
        const el = document.getElementById(id);
        if (!el) {
            return;
        }
        el.addEventListener('input', () => {
            state[key] = el.value;
            if (key === 'actualScreenshotPath' && !isAttachmentMarker(el.value)) {
                state.pastedScreenshot = null;
            }
            updatePromptOnly();
        });
    }

    function updatePromptOnly() {
        const promptEl = document.getElementById('lanhu-final-prompt');
        if (promptEl) {
            promptEl.value = buildPrompt();
        }
    }

    function renderContent() {
        const el = document.getElementById('lanhu-content');
        if (!el) {
            return;
        }

        const showTarget = state.activeTab === 'check';

        el.innerHTML = `
            <div class="lanhu-tabs">
                ${tabs.map(tab => `
                    <button class="lanhu-tab ${tab.key === state.activeTab ? 'active' : ''}" data-tab="${tab.key}">
                        ${escapeHtml(tab.label)}
                    </button>
                `).join('')}
            </div>

            <div class="lanhu-field">
                <div class="lanhu-label">
                    <span>${state.activeTab === 'restyle' ? '现有页面名或页面文件' : '页面名或页面文件'}</span>
                    <button class="lanhu-small-btn" type="button" data-clear="pageName">清空</button>
                </div>
                <input id="lanhu-page-input" class="lanhu-input" value="${escapeHtml(state.pageName)}"
                    placeholder="${state.activeTab === 'restyle' ? '例如 DiaryFragment / item_coupon / /Users/.../Review.kt' : '例如 DiaryFragment / HomeActivity / /Users/.../Review.kt'}">
            </div>

            ${showTarget ? `
                <div class="lanhu-field">
                    <div class="lanhu-label">
                        <span>检查目标</span>
                        <button class="lanhu-small-btn" type="button" data-clear="target">清空</button>
                    </div>
                    <input id="lanhu-target-input" class="lanhu-input" value="${escapeHtml(state.target)}"
                        placeholder="例如 整页 / 卡片样式 / 顶部标题栏 / 列表 item">
                </div>
            ` : ''}

            <div class="lanhu-field">
                <div class="lanhu-label">
                    <span>自定义需求</span>
                    <button class="lanhu-small-btn" type="button" data-clear="customRequirement">清空</button>
                </div>
                <textarea id="lanhu-requirement-input" class="lanhu-textarea"
                    placeholder="补充范围、保留项、排除项或特殊要求；为空则只按当前场景生成提示词。">${escapeHtml(state.customRequirement)}</textarea>
            </div>

            ${hasScreenshotNeed() ? `
                <div class="lanhu-field">
                    <div class="lanhu-label">
                        <span>实现截图路径或附件，不提供则使用adb截图</span>
                        <button class="lanhu-small-btn" type="button" data-clear="actualScreenshotPath">清空</button>
                    </div>
                    <input id="lanhu-screenshot-path-input" class="lanhu-input" value="${escapeHtml(state.actualScreenshotPath)}"
                        placeholder=".../current.png 或粘贴截图附件，不填则会使用adb截图">
                </div>
            ` : ''}

            <div class="lanhu-field">
                <div class="lanhu-label">
                    <span>提示词</span>
                </div>
                <textarea id="lanhu-final-prompt" class="lanhu-prompt">${escapeHtml(buildPrompt())}</textarea>
            </div>

            <div class="lanhu-field">
                <button id="lanhu-copy-prompt" class="lanhu-primary-btn" type="button">复制</button>
            </div>
        `;

        bindEvents();
    }

    function bindEvents() {
        document.querySelectorAll('#lanhu-card .lanhu-tab').forEach(button => {
            button.addEventListener('click', () => {
                state.activeTab = button.dataset.tab || 'create';
                renderContent();
            });
        });

        bindInput('lanhu-page-input', 'pageName');
        bindInput('lanhu-target-input', 'target');
        bindInput('lanhu-requirement-input', 'customRequirement');
        bindInput('lanhu-screenshot-path-input', 'actualScreenshotPath');

        document.querySelectorAll('#lanhu-card [data-clear]').forEach(button => {
            button.addEventListener('click', () => clearField(button.dataset.clear));
        });

        const screenshotInput = document.getElementById('lanhu-screenshot-path-input');
        if (screenshotInput) {
            screenshotInput.addEventListener('paste', handlePastedImage);
        }

        const copyButton = document.getElementById('lanhu-copy-prompt');
        if (copyButton) {
            copyButton.addEventListener('click', copyPrompt);
        }
    }

    function createCard() {
        installStyle();

        const card = document.createElement('div');
        card.id = 'lanhu-card';
        card.style.cssText = [
            'position:fixed',
            'top:80px',
            'right:20px',
            'width:430px',
            'max-height:calc(100vh - 110px)',
            'background:#fff',
            'border-radius:12px',
            'box-shadow:0 14px 42px rgba(15,23,42,0.18)',
            'z-index:99999',
            'overflow:hidden',
            'user-select:none',
            'border:1px solid rgba(15,23,42,0.08)',
        ].join(';');

        card.innerHTML = `
            <div id="lanhu-card-header" style="
                background:#1f2937;
                color:#fff;
                padding:11px 12px;
                display:flex;
                align-items:center;
                justify-content:space-between;
                cursor:pointer;
            ">
                <div style="display:flex;align-items:center;gap:8px;font-size:13px;font-weight:700;">
                    <span>lanhu-skill提示词助手</span>
                    <span id="lanhu-fold-icon" style="font-size:12px;color:#cbd5e1;">▼</span>
                </div>
                <button id="lanhu-close-btn" style="
                    border:none;
                    background:rgba(255,255,255,0.15);
                    color:#fff;
                    border-radius:6px;
                    width:24px;
                    height:24px;
                    cursor:pointer;
                    flex-shrink:0;
                ">×</button>
            </div>
            <div id="lanhu-content" style="padding:12px;font-size:12px;overflow:auto;max-height:calc(100vh - 160px);">
            </div>
        `;

        document.body.appendChild(card);

        const header = document.getElementById('lanhu-card-header');
        const content = document.getElementById('lanhu-content');
        const closeBtn = document.getElementById('lanhu-close-btn');
        const foldIcon = document.getElementById('lanhu-fold-icon');

        let isCollapsed = false;
        let isDragging = false;
        let hasMoved = false;
        let startX = 0;
        let startY = 0;
        let startLeft = 0;
        let startTop = 0;

        function setCollapsed(collapsed) {
            isCollapsed = collapsed;
            content.style.display = collapsed ? 'none' : 'block';
            foldIcon.textContent = collapsed ? '▲' : '▼';
        }

        header.addEventListener('click', (event) => {
            if (event.target === closeBtn || hasMoved) {
                return;
            }
            setCollapsed(!isCollapsed);
        });

        closeBtn.addEventListener('click', (event) => {
            event.stopPropagation();
            card.style.display = 'none';
        });

        header.addEventListener('mousedown', (event) => {
            if (event.target === closeBtn) {
                return;
            }

            isDragging = true;
            hasMoved = false;

            const rect = card.getBoundingClientRect();
            startX = event.clientX;
            startY = event.clientY;
            startLeft = rect.left;
            startTop = rect.top;

            card.style.left = `${rect.left}px`;
            card.style.top = `${rect.top}px`;
            card.style.right = 'auto';
        });

        document.addEventListener('mousemove', (event) => {
            if (!isDragging) {
                return;
            }

            const dx = event.clientX - startX;
            const dy = event.clientY - startY;

            if (Math.abs(dx) > 3 || Math.abs(dy) > 3) {
                hasMoved = true;
            }

            card.style.left = `${startLeft + dx}px`;
            card.style.top = `${startTop + dy}px`;
        });

        document.addEventListener('mouseup', () => {
            isDragging = false;
            setTimeout(() => {
                hasMoved = false;
            }, 0);
        });

        renderContent();
    }

    function handleApiResponse(res) {
        try {
            const data = JSON.parse(res);

            if (data.code === '00000' && data.result) {
                const result = data.result;

                state.data.designId = result.image_id || result.id || result.uuid || result.doc_id || '';
                state.data.url = result.url || '';

                if (result.versions && result.versions.length) {
                    state.data.jsonUrl = result.versions[0].json_url || '';
                } else {
                    state.data.jsonUrl = result.json_url || '';
                }

                renderContent();
            }
        } catch (error) {
            console.warn('蓝湖接口响应解析失败:', error);
        }
    }

    function installNetworkHooks() {
        const originalOpen = XMLHttpRequest.prototype.open;
        XMLHttpRequest.prototype.open = function(method, url, ...args) {
            this._lanhuUrl = url;
            return originalOpen.apply(this, [method, url, ...args]);
        };

        const originalSend = XMLHttpRequest.prototype.send;
        XMLHttpRequest.prototype.send = function(...args) {
            if (this._lanhuUrl && this._lanhuUrl.includes('/api/project/image')) {
                this.addEventListener('load', () => {
                    handleApiResponse(this.responseText);
                });
            }
            return originalSend.apply(this, args);
        };

        const originalFetch = window.fetch;
        window.fetch = function(url, ...args) {
            return originalFetch(url, ...args).then(response => {
                const urlStr = typeof url === 'string' ? url : url.url;

                if (urlStr && urlStr.includes('/api/project/image')) {
                    response.clone().text().then(handleApiResponse);
                }
                return response;
            });
        };
    }

    function init() {
        createCard();
        installNetworkHooks();
        console.log('lanhu-skill提示词助手已启动');
    }

    init();
})();
