// ============================================================================
// SISTEMA DE AVISOS - IPE (v3)
// Toasts, modais de confirmação, modal de input e helpers de permissão
// ============================================================================

// -------- TOASTS --------
function garantirToastContainer() {
    let c = document.getElementById("toast-container");
    if (!c) {
        c = document.createElement("div");
        c.id = "toast-container";
        c.className = "toast-container";
        document.body.appendChild(c);
    }
    return c;
}

/**
 * Exibe um toast.
 * @param {string} mensagem - Texto (aceita HTML leve: <strong>, <br>)
 * @param {string} tipo - "sucesso" | "erro" | "aviso" | "info" | "carregando"
 * @param {number} duracao - ms (padrão 4000). Use 0 para não sumir sozinho.
 * @returns {HTMLElement} elemento do toast (para remover manualmente)
 */
function toast(mensagem, tipo = "info", duracao = 4000) {
    const container = garantirToastContainer();
    const icones = {
        sucesso: "✅",
        erro: "❌",
        aviso: "⚠️",
        info: "ℹ️",
        carregando: "⏳",
    };
    const el = document.createElement("div");
    el.className = `toast ${tipo}`;
    el.innerHTML = `<span class="icone">${icones[tipo] || "ℹ️"}</span><span class="texto">${mensagem}</span>`;

    // Botão fechar (X) em todos os toasts
    const btnFechar = document.createElement("button");
    btnFechar.className = "toast-fechar";
    btnFechar.innerHTML = "✕";
    btnFechar.onclick = () => {
        el.classList.add("saindo");
        setTimeout(() => el.remove(), 250);
    };
    el.appendChild(btnFechar);

    container.appendChild(el);

    if (duracao > 0) {
        setTimeout(() => {
            el.classList.add("saindo");
            setTimeout(() => el.remove(), 250);
        }, duracao);
    }

    return el;
}

/**
 * Toast "carregando" que pode ser fechado manualmente após a operação.
 * Retorna o próprio elemento para você chamar .remove() depois.
 */
function toastCarregando(mensagem = "Processando...") {
    return toast(mensagem, "carregando", 0);
}

// -------- HELPERS DE ESCAPE --------
function escapeHtml(s) {
    if (s === null || s === undefined) return "";
    return String(s)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
}

function escapeAttr(s) {
    if (s === null || s === undefined) return "";
    return String(s)
        .replace(/&/g, "&amp;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
}

// -------- FETCH JSON COM TRATAMENTO DE ERRO --------
async function fetchJson(url, opcoes = {}) {
    let res;
    try {
        res = await fetch(url, opcoes);
    } catch (err) {
        throw new Error("Falha de conexão com o servidor. O Flask está rodando?");
    }

    if (res.status === 401) {
        toast("Sessão expirada. Faça login novamente.", "aviso");
        setTimeout(() => { window.location.href = "/login"; }, 1500);
        throw new Error("Não autenticado. Faça login.");
    }

    if (res.status === 403) {
        let msg = "Acesso negado.";
        try {
            const data = await res.json();
            msg = data.erro || msg;
        } catch {}
        toast(msg, "erro");
        throw new Error(msg);
    }

    if (res.status === 404) {
        throw new Error(`Endpoint não encontrado: ${url}`);
    }

    if (!res.ok) {
        let msg = `Erro HTTP ${res.status}`;
        try {
            const data = await res.json();
            msg = data.erro || data.mensagem || msg;
        } catch {
            try {
                const txt = await res.text();
                if (txt) msg += ` — ${txt.substring(0, 100)}`;
            } catch {}
        }
        throw new Error(msg);
    }

    try {
        return await res.json();
    } catch {
        throw new Error("Resposta do servidor não é JSON válido.");
    }
}

// -------- AVISO INLINE --------
function exibirAvisoRestricao(container, mensagem, opcoes = {}) {
    if (typeof container === "string") container = document.querySelector(container);
    if (!container) return;

    const antigo = container.querySelector(".aviso-restricao");
    if (antigo) antigo.remove();

    const div = document.createElement("div");
    div.className = "aviso-restricao";
    div.innerHTML = `
        <span class="icone">🔒</span>
        <div>
            <strong>Acesso restrito</strong>
            ${mensagem}
            ${opcoes.link ? `<br><a href="${opcoes.link}">${opcoes.linkTexto || "Solicitar acesso"}</a>` : ""}
        </div>
    `;

    if (opcoes.preparar) opcoes.preparar(div);
    container.insertBefore(div, container.firstChild);
}

// -------- MODAL DE ACESSO RESTRITO --------
function modalRestrito(mensagem, titulo = "Acesso Restrito") {
    return new Promise((resolve) => {
        const overlay = document.createElement("div");
        overlay.className = "modal-restrito-overlay";
        overlay.style.cssText = `
            position: fixed; inset: 0; background: rgba(21,41,55,0.55);
            display: flex; align-items: center; justify-content: center;
            z-index: 10000; padding: 20px; animation: avisoIn 0.25s ease;
            backdrop-filter: blur(3px);
        `;
        overlay.innerHTML = `
            <div style="background:white; border-radius:18px; padding:35px 32px; max-width:460px;
                        width:100%; text-align:center; box-shadow:0 24px 60px rgba(0,0,0,0.3);">
                <div style="font-size:3rem; margin-bottom:12px;">🔒</div>
                <h3 style="color:#152937; margin-bottom:10px; font-size:1.25rem;">${titulo}</h3>
                <p style="color:#5b6670; font-size:0.92rem; line-height:1.6; margin-bottom:24px;">${mensagem}</p>
                <button id="btn-restrito-ok" style="
                    background: linear-gradient(135deg, #FFD730, #F29310);
                    color:#152937; border:none; padding:12px 26px; border-radius:10px;
                    font-family:'Poppins', sans-serif; font-weight:600; font-size:0.9rem;
                    cursor:pointer; box-shadow:0 6px 16px rgba(242,147,16,0.28);">
                    Entendi
                </button>
            </div>
        `;
        document.body.appendChild(overlay);
        overlay.querySelector("#btn-restrito-ok").onclick = () => {
            overlay.remove();
            resolve(true);
        };
        overlay.onclick = (e) => {
            if (e.target === overlay) { overlay.remove(); resolve(false); }
        };
    });
}

// -------- MODAL DE CONFIRMAÇÃO --------
function confirmarAcao(mensagem, opcoes = {}) {
    return new Promise((resolve) => {
        const titulo = opcoes.titulo || "Confirmação";
        const textoConfirmar = opcoes.textoConfirmar || "Confirmar";
        const textoCancelar = opcoes.textoCancelar || "Cancelar";
        const perigo = opcoes.perigo === true;

        const overlay = document.createElement("div");
        overlay.className = "modal-confirma-overlay";
        overlay.style.cssText = `
            position: fixed; inset: 0; background: rgba(21,41,55,0.55);
            display: flex; align-items: center; justify-content: center;
            z-index: 10000; padding: 20px; animation: avisoIn 0.25s ease;
            backdrop-filter: blur(3px);
        `;
        overlay.innerHTML = `
            <div style="background:white; border-radius:18px; padding:30px; max-width:460px;
                        width:100%; text-align:center; box-shadow:0 24px 60px rgba(0,0,0,0.3);">
                <div style="font-size:2.5rem; margin-bottom:12px;">${perigo ? "⚠️" : "❓"}</div>
                <h3 style="color:#152937; margin-bottom:12px; font-size:1.15rem;">${titulo}</h3>
                <p style="color:#5b6670; font-size:0.92rem; line-height:1.6; margin-bottom:24px; white-space:pre-line;">${mensagem}</p>
                <div style="display:flex; gap:10px; justify-content:center; flex-wrap:wrap;">
                    <button id="btn-confirma-cancelar" style="
                        background:#f3f4f6; color:#152937; border:none;
                        padding:11px 24px; border-radius:10px; cursor:pointer;
                        font-family:'Poppins', sans-serif; font-weight:500; font-size:0.9rem;">
                        ${textoCancelar}
                    </button>
                    <button id="btn-confirma-ok" style="
                        background: ${perigo ? 'linear-gradient(135deg, #ef4444, #991b1b)' : 'linear-gradient(135deg, #FFD730, #F29310)'};
                        color: ${perigo ? 'white' : '#152937'}; border:none;
                        padding:11px 24px; border-radius:10px; cursor:pointer;
                        font-family:'Poppins', sans-serif; font-weight:600; font-size:0.9rem;
                        box-shadow: 0 4px 12px rgba(0,0,0,0.15);">
                        ${textoConfirmar}
                    </button>
                </div>
            </div>
        `;
        document.body.appendChild(overlay);

        const fechar = (resultado) => {
            overlay.remove();
            resolve(resultado);
        };

        overlay.querySelector("#btn-confirma-ok").onclick = () => fechar(true);
        overlay.querySelector("#btn-confirma-cancelar").onclick = () => fechar(false);
        overlay.onclick = (e) => {
            if (e.target === overlay) fechar(false);
        };
        document.addEventListener("keydown", function esc(e) {
            if (e.key === "Escape") {
                document.removeEventListener("keydown", esc);
                fechar(false);
            }
        });
    });
}

// -------- MODAL DE INPUT (para cancelamento, observações, etc.) --------
/**
 * Modal com textarea para o usuário digitar um texto.
 * Retorna Promise<string|null> — string com o texto, ou null se cancelou.
 *
 * Opções:
 *  - titulo (string)
 *  - label (string)
 *  - placeholder (string)
 *  - textoConfirmar (string)
 *  - textoCancelar (string)
 *  - minLength (number, padrão 0)
 *  - maxLength (number, padrão 1000)
 *  - required (boolean, padrão true)
 *  - valorInicial (string)
 */
function modalInput(opcoes = {}) {
    return new Promise((resolve) => {
        const titulo = opcoes.titulo || "Digite uma informação";
        const label = opcoes.label || "";
        const placeholder = opcoes.placeholder || "";
        const textoConfirmar = opcoes.textoConfirmar || "Confirmar";
        const textoCancelar = opcoes.textoCancelar || "Cancelar";
        const minLength = opcoes.minLength || 0;
        const maxLength = opcoes.maxLength || 1000;
        const required = opcoes.required !== false;
        const valorInicial = opcoes.valorInicial || "";

        const overlay = document.createElement("div");
        overlay.className = "modal-input-overlay";
        overlay.style.cssText = `
            position: fixed; inset: 0; background: rgba(21,41,55,0.55);
            display: flex; align-items: center; justify-content: center;
            z-index: 10000; padding: 20px; animation: avisoIn 0.25s ease;
            backdrop-filter: blur(3px);
        `;
        overlay.innerHTML = `
            <div style="background:white; border-radius:18px; padding:28px; max-width:520px;
                        width:100%; box-shadow:0 24px 60px rgba(0,0,0,0.3);">
                <h3 style="color:#152937; margin-bottom:14px; font-size:1.15rem;">${titulo}</h3>
                ${label ? `<label style="display:block; color:#5b6670; font-size:0.82rem;
                            font-weight:600; text-transform:uppercase; letter-spacing:0.3px;
                            margin-bottom:6px;">${label}</label>` : ""}
                <textarea id="modal-input-texto" rows="4" maxlength="${maxLength}"
                    placeholder="${escapeAttr(placeholder)}"
                    style="width:100%; padding:12px 14px; border:1px solid #d1d5db; border-radius:10px;
                           font-family:'Poppins', sans-serif; font-size:0.92rem; resize:vertical;
                           min-height:90px;">${escapeHtml(valorInicial)}</textarea>
                <div id="modal-input-erro" style="display:none; color:#991b1b;
                     font-size:0.82rem; margin-top:8px;"></div>
                <div style="display:flex; gap:10px; justify-content:flex-end; margin-top:18px; flex-wrap:wrap;">
                    <button id="btn-input-cancelar" style="
                        background:#f3f4f6; color:#152937; border:none;
                        padding:11px 24px; border-radius:10px; cursor:pointer;
                        font-family:'Poppins', sans-serif; font-weight:500; font-size:0.9rem;">
                        ${textoCancelar}
                    </button>
                    <button id="btn-input-ok" style="
                        background: linear-gradient(135deg, #FFD730, #F29310);
                        color:#152937; border:none;
                        padding:11px 24px; border-radius:10px; cursor:pointer;
                        font-family:'Poppins', sans-serif; font-weight:600; font-size:0.9rem;
                        box-shadow:0 4px 12px rgba(242,147,16,0.28);">
                        ${textoConfirmar}
                    </button>
                </div>
            </div>
        `;
        document.body.appendChild(overlay);

        const textarea = overlay.querySelector("#modal-input-texto");
        const erro = overlay.querySelector("#modal-input-erro");
        textarea.focus();

        const fechar = (resultado) => {
            overlay.remove();
            resolve(resultado);
        };

        overlay.querySelector("#btn-input-ok").onclick = () => {
            const texto = textarea.value.trim();
            if (required && texto.length < Math.max(1, minLength)) {
                erro.style.display = "block";
                erro.innerText = `Preencha pelo menos ${Math.max(1, minLength)} caractere(s).`;
                return;
            }
            fechar(texto);
        };

        overlay.querySelector("#btn-input-cancelar").onclick = () => fechar(null);

        overlay.onclick = (e) => {
            if (e.target === overlay) fechar(null);
        };

        document.addEventListener("keydown", function esc(e) {
            if (e.key === "Escape") {
                document.removeEventListener("keydown", esc);
                fechar(null);
            }
        });

        // Ctrl+Enter envia
        textarea.addEventListener("keydown", (e) => {
            if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
                overlay.querySelector("#btn-input-ok").click();
            }
        });
    });
}

// -------- HELPER DE PERMISSÃO --------
async function protegerAcao(perfilNecessario, callback) {
    const perfil = await obterPerfilAtual();
    const isAdmin = perfil && perfil.id_perfil === 1;

    if (perfilNecessario === "admin" && !isAdmin) {
        await modalRestrito(
            "Esta ação é exclusiva para <strong>Administradores</strong> do sistema. " +
            "Se você precisa executar esta operação, solicite acesso ao responsável."
        );
        return false;
    }
    if (typeof callback === "function") callback();
    return true;
}

// -------- CACHE DO PERFIL --------
let _perfilCache = null;
async function obterPerfilAtual(force = false) {
    if (_perfilCache && !force) return _perfilCache;
    try {
        const res = await fetch("/api/dados_usuario");
        if (!res.ok) { _perfilCache = null; return null; }
        _perfilCache = await res.json();
        return _perfilCache;
    } catch {
        _perfilCache = null;
        return null;
    }
}

// -------- MENU (controlado por Jinja2 no servidor) --------
function aplicarRestricoesMenu() {
    return;
}

document.addEventListener("DOMContentLoaded", () => {
    aplicarRestricoesMenu();
});

// -------- SPINNER --------
async function comSpinner(botao, fn) {
    if (!botao) return await fn();

    const htmlOriginal = botao.innerHTML;
    const eraDisabled = botao.disabled;

    botao.classList.add("btn-loading");
    botao.disabled = true;

    if (botao.classList.contains("btn-login") ||
        botao.classList.contains("btn-cancel") ||
        botao.classList.contains("btn-testar")) {
        botao.classList.add("btn-loading-dark");
    }

    try {
        return await fn();
    } finally {
        botao.classList.remove("btn-loading", "btn-loading-dark");
        botao.innerHTML = htmlOriginal;
        botao.disabled = eraDisabled;
    }
}

// -------- EXPORTA HELPERS GLOBAIS --------
window.toast = toast;
window.toastCarregando = toastCarregando;
window.escapeHtml = escapeHtml;
window.escapeAttr = escapeAttr;
window.fetchJson = fetchJson;
window.exibirAvisoRestricao = exibirAvisoRestricao;
window.modalRestrito = modalRestrito;
window.confirmarAcao = confirmarAcao;
window.modalInput = modalInput;
window.protegerAcao = protegerAcao;
window.obterPerfilAtual = obterPerfilAtual;
window.comSpinner = comSpinner;