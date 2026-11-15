// ============================================================================
// CENTRAL DE NOTIFICAÇÕES - IPE
// ============================================================================

let notificacoesCache = [];
let dropdownAberto = false;

const STORAGE_KEY = "ipe_notificacoes_lidas";

// ============================================================================
// HELPERS DE ESCAPE (segurança contra HTML injection)
// ============================================================================

function escapeAttr(s) {
    if (s === null || s === undefined) return "";
    return String(s)
        .replace(/&/g, "&amp;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
}

function escapeHtml(s) {
    if (s === null || s === undefined) return "";
    return String(s)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
}

// ============================================================================
// HELPERS DE LOCALSTORAGE
// ============================================================================

function getLidas() {
    try {
        return JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
    } catch {
        return [];
    }
}

function salvarLidas(lista) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(lista));
}

function marcarComoLida(id) {
    const lidas = getLidas();
    if (!lidas.includes(id)) {
        lidas.push(id);
        salvarLidas(lidas);
    }
}

function marcarTodasComoLidas() {
    const lidas = notificacoesCache.map(n => n.id);
    salvarLidas(lidas);
    atualizarBadge();
    renderizarDropdown();
}

// ============================================================================
// RENDERIZAR O SINO NO HEADER
// ============================================================================

function criarSino() {
    if (document.getElementById("notif-wrapper")) return;

    const topbar = document.querySelector(".topbar");
    if (!topbar) return;

    const wrapper = document.createElement("div");
    wrapper.id = "notif-wrapper";
    wrapper.className = "notif-wrapper";

    wrapper.innerHTML = `
        <button class="notif-btn" id="notif-btn" title="Notificações" onclick="toggleDropdown(event)">
            🔔
            <span class="notif-badge" id="notif-badge">0</span>
        </button>

        <div class="notif-dropdown" id="notif-dropdown">
            <div class="notif-header">
                <h4>Notificações</h4>
                <button onclick="marcarTodasComoLidas(); event.stopPropagation();">
                    Marcar todas como lidas
                </button>
            </div>

            <div class="notif-list" id="notif-list">
                <div class="notif-empty">
                    <span class="icone">📭</span>
                    Carregando...
                </div>
            </div>

            <div class="notif-footer">
                <a href="admin.html">Ver todas no Painel ADM →</a>
            </div>
        </div>
    `;

    const botoes = topbar.querySelector(".top-buttons");
    if (botoes) {
        botoes.insertBefore(wrapper, botoes.firstChild);
    } else {
        topbar.appendChild(wrapper);
    }

    document.addEventListener("click", (e) => {
        if (!e.target.closest(".notif-wrapper")) {
            fecharDropdown();
        }
    });

    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") fecharDropdown();
    });
}

// ============================================================================
// ABRIR/FECHAR DROPDOWN
// ============================================================================

function toggleDropdown(event) {
    if (event) event.stopPropagation();
    const dd = document.getElementById("notif-dropdown");
    if (!dd) return;

    if (dd.classList.contains("show")) {
        fecharDropdown();
    } else {
        dd.classList.add("show");
        dropdownAberto = true;
    }
}

function fecharDropdown() {
    const dd = document.getElementById("notif-dropdown");
    if (dd) dd.classList.remove("show");
    dropdownAberto = false;
}

// ============================================================================
// CARREGAR NOTIFICAÇÕES
// ============================================================================

async function carregarNotificacoes() {
    try {
        const res = await fetch("/api/notificacoes");
        if (!res.ok) throw new Error("HTTP " + res.status);
        const data = await res.json();
        notificacoesCache = data.notificacoes || [];

        atualizarBadge();
        renderizarDropdown();
    } catch (err) {
        console.error("Erro notificações:", err);
        const list = document.getElementById("notif-list");
        if (list) {
            list.innerHTML = `
                <div class="notif-empty">
                    <span class="icone">⚠️</span>
                    Não foi possível carregar notificações.
                </div>
            `;
        }
    }
}

// ============================================================================
// ATUALIZAR BADGE
// ============================================================================

function atualizarBadge() {
    const badge = document.getElementById("notif-badge");
    if (!badge) return;

    const lidas = getLidas();
    const naoLidas = notificacoesCache.filter(n => !lidas.includes(n.id));

    if (naoLidas.length === 0) {
        badge.classList.remove("show", "urgente", "vencido");
        badge.innerText = "0";
        return;
    }

    badge.classList.add("show");
    badge.innerText = naoLidas.length > 99 ? "99+" : naoLidas.length;

    if (naoLidas.some(n => n.urgencia === "vencido")) {
        badge.classList.add("vencido");
        badge.classList.remove("urgente");
    } else if (naoLidas.some(n => n.urgencia === "urgente")) {
        badge.classList.add("urgente");
        badge.classList.remove("vencido");
    } else {
        badge.classList.remove("urgente", "vencido");
    }
}

// ============================================================================
// RENDERIZAR DROPDOWN
// ============================================================================

function renderizarDropdown() {
    const list = document.getElementById("notif-list");
    if (!list) return;

    if (notificacoesCache.length === 0) {
        list.innerHTML = `
            <div class="notif-empty">
                <span class="icone">✅</span>
                Tudo em ordem! Nenhuma notificação no momento.
            </div>
        `;
        return;
    }

    const lidas = getLidas();

    list.innerHTML = notificacoesCache.map(n => {
        const isLida = lidas.includes(n.id);

        // Escapa tudo que vai pra HTML
        const tituloSeguro = escapeHtml(n.titulo || "");
        const mensagemSegura = escapeHtml(n.mensagem || "");
        const dataSegura = escapeHtml(n.data || "");
        const linkSeguro = escapeAttr(n.link || "#");
        const tipoSeguro = escapeAttr(n.tipo || "");
        const origemSegura = escapeAttr((n.origem || "").toLowerCase());
        const urgenciaSegura = escapeAttr(n.urgencia || "");

        const tagExtra = n.urgencia === "vencido"
            ? '<span class="notif-tag vencido">Vencido</span>'
            : '';

        return `
            <a class="notif-item ${isLida ? '' : 'nao-lida'}"
               href="${linkSeguro}"
               onclick="marcarComoLida('${escapeAttr(n.id)}')">
                <div class="notif-item-top">
                    <div class="notif-titulo">${tituloSeguro}</div>
                    <div class="notif-data">${dataSegura}</div>
                </div>
                <div class="notif-msg">${mensagemSegura}</div>
                <div class="notif-meta">
                    <span class="notif-tag ${tipoSeguro}">${escapeHtml(n.tipo || "")}</span>
                    <span class="notif-tag ${origemSegura}">${escapeHtml(n.origem || "")}</span>
                    ${tagExtra}
                </div>
            </a>
        `;
    }).join("");
}

// ============================================================================
// INICIALIZAÇÃO
// ============================================================================

document.addEventListener("DOMContentLoaded", async () => {
    try {
        const res = await fetch("/api/dados_usuario");
        if (!res.ok) return;

        criarSino();
        await carregarNotificacoes();

        setInterval(carregarNotificacoes, 60000);
    } catch (err) {
        // Silencioso
    }
});