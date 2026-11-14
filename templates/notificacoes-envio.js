// ============================================================================
// MÓDULO DE ENVIO DE NOTIFICAÇÕES - IPE
// ============================================================================

let tipoAtual = "info";
let destinatariosDisponiveis = [];
let emailsSelecionados = new Set();

document.addEventListener("DOMContentLoaded", () => {
    carregarDestinatarios();
    carregarHistorico();
    carregarConfigSMTP();
});

// ============================================================================
// TABS
// ============================================================================

function abrirTab(nome, btn) {
    document.querySelectorAll(".notif-tab").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".notif-tab-content").forEach(c => c.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById("tab-" + nome).classList.add("active");

    if (nome === "historico") carregarHistorico();
    if (nome === "config") carregarConfigSMTP();
}

// ============================================================================
// TIPO DE NOTIFICAÇÃO
// ============================================================================

function setTipo(tipo) {
    tipoAtual = tipo;
    document.querySelectorAll(".notif-tipo-card").forEach(c => {
        c.classList.toggle("selected", c.dataset.tipo === tipo);
    });
}

// ============================================================================
// DESTINATÁRIOS
// ============================================================================

async function carregarDestinatarios() {
    const div = document.getElementById("lista-destinatarios");
    div.innerHTML = '<em style="padding: 15px; display: block;">Carregando...</em>';

    try {
        const res = await fetch("/api/notificacoes/destinatarios");
        if (!res.ok) throw new Error("HTTP " + res.status);
        destinatariosDisponiveis = await res.json();

        renderizarDestinatarios();
    } catch (err) {
        div.innerHTML = `<em style="padding: 15px; display: block; color: red;">Erro: ${escapeHtml(err.message)}</em>`;
    }
}

function renderizarDestinatarios() {
    const div = document.getElementById("lista-destinatarios");

    if (destinatariosDisponiveis.length === 0) {
        div.innerHTML = '<em style="padding: 15px; display: block;">Nenhum usuário cadastrado.</em>';
        return;
    }

    div.innerHTML = destinatariosDisponiveis.map(u => `
        <label class="destinatario-item">
            <input type="checkbox" value="${escapeAttr(u.e_mail)}"
                   ${emailsSelecionados.has(u.e_mail) ? "checked" : ""}
                   onchange="toggleEmail(this.value, this.checked)">
            <div class="info">
                <div class="nome">${escapeHtml(u.nome)}</div>
                <div class="email">${escapeHtml(u.e_mail)}</div>
            </div>
            ${u.id_perfil === 1 ? '<span class="badge-adm-mini">ADM</span>' : ''}
        </label>
    `).join("");
}

function toggleEmail(email, marcado) {
    if (marcado) emailsSelecionados.add(email);
    else emailsSelecionados.delete(email);
    atualizarPreviewDest();
}

function selecionarTodos() {
    emailsSelecionados.clear();
    destinatariosDisponiveis.forEach(u => emailsSelecionados.add(u.e_mail));
    renderizarDestinatarios();
    atualizarPreviewDest();
}

function selecionarAdmins() {
    emailsSelecionados.clear();
    destinatariosDisponiveis.filter(u => u.id_perfil === 1)
        .forEach(u => emailsSelecionados.add(u.e_mail));
    renderizarDestinatarios();
    atualizarPreviewDest();
}

function limparSelecao() {
    emailsSelecionados.clear();
    renderizarDestinatarios();
    atualizarPreviewDest();
}

function atualizarPreviewDest() {
    const div = document.getElementById("preview-dest");
    const texto = document.getElementById("preview-dest-texto");

    if (emailsSelecionados.size === 0) {
        div.style.display = "none";
        return;
    }

    div.style.display = "block";
    texto.innerText = `${emailsSelecionados.size} destinatário(s): ${Array.from(emailsSelecionados).slice(0, 3).join(", ")}${emailsSelecionados.size > 3 ? "..." : ""}`;
}

// ============================================================================
// ENVIAR NOTIFICAÇÃO
// ============================================================================

async function enviarNotificacao() {
    const assunto = document.getElementById("notif-assunto").value.trim();
    const mensagem = document.getElementById("notif-mensagem").value.trim();
    const link = document.getElementById("notif-link").value.trim();

    if (!assunto) { toast("Preencha o assunto.", "aviso"); return; }
    if (!mensagem) { toast("Preencha a mensagem.", "aviso"); return; }
    if (emailsSelecionados.size === 0) { toast("Selecione pelo menos um destinatário.", "aviso"); return; }

    const btn = document.getElementById("btn-enviar-notif");

    await comSpinner(btn, async () => {
        try {
            const res = await fetch("/api/notificacoes/enviar", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    assunto: assunto,
                    mensagem: mensagem,
                    tipo: tipoAtual,
                    link: link,
                    destinatarios: Array.from(emailsSelecionados)
                })
            });
            const data = await res.json();

            if (res.ok) {
                toast(data.mensagem, "sucesso");
                document.getElementById("notif-assunto").value = "";
                document.getElementById("notif-mensagem").value = "";
                document.getElementById("notif-link").value = "";
                emailsSelecionados.clear();
                renderizarDestinatarios();
                atualizarPreviewDest();
                carregarHistorico();
            } else {
                toast(data.erro || "Erro ao enviar.", "erro");
            }
        } catch (err) {
            toast("Erro de conexão: " + err.message, "erro");
        }
    });
}

// ============================================================================
// ENVIAR TESTE
// ============================================================================

async function enviarTeste() {
    const email = prompt("Digite o e-mail para receber o teste:", "");
    if (!email) return;

    try {
        const res = await fetch("/api/notificacoes/testar-smtp", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email: email })
        });
        const data = await res.json();

        if (res.ok) {
            alert("✅ " + data.mensagem);
        } else {
            alert("❌ " + (data.erro || "Erro ao enviar teste."));
        }
    } catch (err) {
        alert("Erro de conexão: " + err.message);
    }
}

// ============================================================================
// HISTÓRICO
// ============================================================================

async function carregarHistorico() {
    const div = document.getElementById("lista-historico");
    div.innerHTML = '<em style="padding: 15px; display: block;">Carregando...</em>';

    try {
        const res = await fetch("/api/notificacoes/historico");
        const dados = await res.json();

        if (!dados || dados.length === 0) {
            div.innerHTML = '<em style="padding: 15px; display: block;">Nenhuma notificação enviada ainda.</em>';
            return;
        }

        div.innerHTML = dados.map(h => `
            <div class="historico-notif-item">
                <div class="icone-hist">📤</div>
                <div class="info">
                    <div class="descricao">${escapeHtml(h.descricao || '—')}</div>
                    <div class="meta">${escapeHtml(h.data_formatada)} · por ${escapeHtml(h.nome_usuario)}</div>
                </div>
            </div>
        `).join("");
    } catch (err) {
        div.innerHTML = `<em style="padding: 15px; display: block; color: red;">Erro: ${escapeHtml(err.message)}</em>`;
    }
}

// ============================================================================
// CONFIGURAÇÃO SMTP
// ============================================================================

async function carregarConfigSMTP() {
    try {
        const res = await fetch("/api/notificacoes/config-smtp");
        const config = await res.json();

        document.getElementById("smtp-ativo").checked = config.ativo || false;
        document.getElementById("smtp-servidor").value = config.servidor || "smtp.gmail.com";
        document.getElementById("smtp-porta").value = config.porta || 587;
        document.getElementById("smtp-usuario").value = config.usuario || "";
        document.getElementById("smtp-senha").value = config.senha || "";
        document.getElementById("smtp-remetente").value = config.remetente_nome || "IPE - Sistema de Inventário";

        // Mostra alerta se não estiver ativo
        const statusSmtp = document.getElementById("status-smtp");
        statusSmtp.style.display = config.ativo ? "none" : "block";
    } catch (err) {
        console.error("Erro config SMTP:", err);
    }
}

async function salvarConfigSMTP() {
    const dados = {
        ativo: document.getElementById("smtp-ativo").checked,
        servidor: document.getElementById("smtp-servidor").value.trim(),
        porta: parseInt(document.getElementById("smtp-porta").value) || 587,
        usuario: document.getElementById("smtp-usuario").value.trim(),
        senha: document.getElementById("smtp-senha").value.replace(/[\s\u00a0•]/g, ""), // máscara/espaços não são enviados
        remetente_nome: document.getElementById("smtp-remetente").value.trim()
    };

    if (dados.ativo && (!dados.usuario || !dados.senha)) {
        alert("Preencha usuário e senha antes de ativar.");
        return;
    }

    try {
        const res = await fetch("/api/notificacoes/config-smtp", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(dados)
        });
        const data = await res.json();

        if (res.ok) {
            alert("✅ " + data.mensagem);
            carregarConfigSMTP();
        } else {
            alert("❌ " + (data.erro || "Erro ao salvar."));
        }
    } catch (err) {
        alert("Erro: " + err.message);
    }
}

async function testarSMTP() {
    // Salva primeiro
    await salvarConfigSMTP();

    const email = prompt("Para qual e-mail enviar o teste?", document.getElementById("smtp-usuario").value);
    if (!email) return;

    try {
        const res = await fetch("/api/notificacoes/testar-smtp", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email: email })
        });
        const data = await res.json();

        if (res.ok) {
            alert("✅ " + data.mensagem);
        } else {
            alert("❌ " + (data.erro || "Erro ao testar."));
        }
    } catch (err) {
        alert("Erro: " + err.message);
    }
}