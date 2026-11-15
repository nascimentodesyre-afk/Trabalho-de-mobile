// ============================================================================
// PAINEL DO ADMINISTRADOR - IPE (v3 - 3 perfis)
// ============================================================================

document.addEventListener("DOMContentLoaded", () => {
    carregarEstatisticas();
    carregarUsuarios();
    carregarAlertas();
    carregarLogs();

    const form = document.getElementById("form-alerta");
    if (form) form.addEventListener("submit", criarAlerta);
});

function abrirTab(nome, btn) {
    document.querySelectorAll(".tab-content").forEach(t => t.classList.remove("active"));
    document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
    const tab = document.getElementById("tab-" + nome);
    if (tab) tab.classList.add("active");
    if (btn) btn.classList.add("active");
}

// ============================================================================
// ESTATÍSTICAS
// ============================================================================

async function carregarEstatisticas() {
    try {
        const s = await fetchJson("/api/admin/estatisticas");
        const totalPatr = (s.patrimonios_por_status || []).reduce((acc, p) => acc + p.qtd, 0);
        document.getElementById("stat-total-patrimonios").innerText = totalPatr;
        document.getElementById("stat-valor-total").innerText =
            "R$ " + parseFloat(s.valor_total_patrimonio || 0).toFixed(2).replace(".", ",");
        const totalUsr = (s.usuarios_por_perfil || []).reduce((acc, u) => acc + u.qtd, 0);
        document.getElementById("stat-total-usuarios").innerText = totalUsr;
        document.getElementById("stat-chamados-mes").innerText = s.chamados_concluidos_mes || 0;
    } catch (err) {
        console.error("Erro estatísticas:", err);
    }
}

// ============================================================================
// USUÁRIOS
// ============================================================================

const PERFIL_INFO = {
    1: { nome: "Patrimônio",     classe: "manutencao" },
    2: { nome: "Usuário Padrão", classe: "ativo" },
};

async function carregarUsuarios() {
    const tbody = document.getElementById("tabela-usuarios");
    if (!tbody) return;
    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;">Carregando...</td></tr>';

    try {
        const data = await fetchJson("/api/usuarios");
        const usuarios = Array.isArray(data) ? data : (data.usuarios || []);

        tbody.innerHTML = "";
        if (usuarios.length === 0) {
            tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;">Nenhum usuário encontrado.</td></tr>';
            return;
        }

        usuarios.forEach(u => {
    const info = PERFIL_INFO[u.id_perfil] || { nome: u.nome_perfil || "—", classe: "ativo" };

            // Próximo perfil no ciclo: 1 → 2 → 3 → 1
            let proximoPerfil, proximoNome;
    if (u.id_perfil === 1) { proximoPerfil = 2; proximoNome = "Usuário"; }
    else                   { proximoPerfil = 1; proximoNome = "Patrimônio"; }

            const tr = document.createElement("tr");
            tr.innerHTML = `
                <td>#${u.id_usuario}</td>
                <td>${escapeHtml(u.nome)}</td>
                <td>${escapeHtml(u.e_mail)}</td>
                <td><span class="status ${info.classe}">${escapeHtml(info.nome)}</span></td>
                <td>${u.total_chamados}</td>
                <td>
                    <div style="display: flex; gap: 5px; flex-wrap: wrap;">
                        <button class="btn-mini primary" onclick="alterarPerfil(${u.id_usuario}, ${proximoPerfil})">
                            → ${proximoNome}
                        </button>
                        <button class="btn-mini danger btn-excluir-usuario"
                                data-id="${u.id_usuario}"
                                data-nome="${escapeAttr(u.nome)}">🗑 Excluir</button>
                    </div>
                </td>
            `;
            tbody.appendChild(tr);
        });

        tbody.querySelectorAll(".btn-excluir-usuario").forEach(btn => {
            btn.addEventListener("click", () => {
                excluirUsuario(parseInt(btn.dataset.id), btn.dataset.nome);
            });
        });
    } catch (err) {
        console.error("Erro usuários:", err);
        tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;color:red;">
            Erro: ${escapeHtml(err.message)}
        </td></tr>`;
    }
}

async function alterarPerfil(idUsuario, novoPerfil) {
    const nomes = { 1: "PATRIMÔNIO", 2: "USUÁRIO PADRÃO" };
    const ok = await confirmarAcao(
        `Alterar o perfil deste usuário para <strong>${nomes[novoPerfil] || novoPerfil}</strong>?`,
        { titulo: "Alterar perfil", textoConfirmar: "Alterar" }
    );
    if (!ok) return;

    const formData = new FormData();
    formData.append("id_perfil", novoPerfil);

    try {
        const data = await fetchJson(`/api/usuarios/${idUsuario}/perfil`, {
            method: "POST",
            body: formData
        });
        toast(data.mensagem || "Perfil alterado!", "sucesso");
        carregarUsuarios();
        carregarLogs();
    } catch (err) {
        toast("Erro: " + err.message, "erro");
    }
}

async function excluirUsuario(idUsuario, nome) {
    const ok = await confirmarAcao(
        `Excluir o usuário <strong>"${escapeHtml(nome)}"</strong>?\n\nEsta ação NÃO pode ser desfeita.`,
        { titulo: "Excluir usuário", textoConfirmar: "Excluir", perigo: true }
    );
    if (!ok) return;

    try {
        const data = await fetchJson(`/api/usuarios/${idUsuario}`, { method: "DELETE" });
        toast(data.mensagem || "Excluído!", "sucesso");
        carregarUsuarios();
        carregarLogs();
        carregarEstatisticas();
    } catch (err) {
        toast("Erro: " + err.message, "erro");
    }
}

// ============================================================================
// ALERTAS
// ============================================================================

async function carregarAlertas() {
    const div = document.getElementById("lista-alertas");
    if (!div) return;
    div.innerHTML = '<em style="padding: 15px; display: block;">Carregando...</em>';

    try {
        const alertas = await fetchJson("/api/alertas") || [];
        if (alertas.length === 0) {
            div.innerHTML = '<em style="padding: 15px; display: block;">Nenhum alerta ativo.</em>';
            return;
        }
        div.innerHTML = "";
        alertas.forEach(a => {
            const item = document.createElement("div");
            item.className = "log-item";
            item.innerHTML = `
                <span class="log-badge UPDATE">${escapeHtml(a.tipo_alerta)}</span>
                <div style="flex: 1;">
                    <strong>${escapeHtml(a.data_vencimento)}</strong> — ${escapeHtml(a.mensagem)}
                </div>
            `;
            div.appendChild(item);
        });
    } catch (err) {
        div.innerHTML = `<em style="padding: 15px; display: block; color: red;">Erro: ${escapeHtml(err.message)}</em>`;
    }
}

async function criarAlerta(e) {
    e.preventDefault();
    const formData = new FormData();
    formData.append("mensagem", document.getElementById("alerta-mensagem").value);
    formData.append("data_vencimento", document.getElementById("alerta-data").value);
    formData.append("id_tipo_alerta", document.getElementById("alerta-tipo").value);

    try {
        const data = await fetchJson("/api/alertas", { method: "POST", body: formData });
        toast(data.mensagem || "Alerta criado!", "sucesso");
        document.getElementById("form-alerta").reset();
        carregarAlertas();
        carregarLogs();
    } catch (err) {
        toast("Erro: " + err.message, "erro");
    }
}

// ============================================================================
// LOGS
// ============================================================================

async function carregarLogs() {
    const div = document.getElementById("lista-logs");
    if (!div) return;
    div.innerHTML = '<em style="padding: 15px; display: block;">Carregando...</em>';

    try {
        const logs = await fetchJson("/api/log-auditoria") || [];
        if (logs.length === 0) {
            div.innerHTML = '<em style="padding: 15px; display: block;">Nenhum log registrado.</em>';
            return;
        }
        div.innerHTML = "";
        logs.forEach(l => {
            const acao = (l.acao || "ACAO").toUpperCase();
            const classe = ["INSERT", "UPDATE", "DELETE"].includes(acao) ? acao : "UPDATE";
            const item = document.createElement("div");
            item.className = "log-item";
            item.innerHTML = `
                <span class="log-badge ${classe}">${escapeHtml(acao)}</span>
                <div style="flex: 1;">
                    <div style="font-size: 0.9rem;">${escapeHtml(l.descricao || '—')}</div>
                    <small style="color: var(--text-light);">
                        ${escapeHtml(l.data_formatada || '')} · por ${escapeHtml(l.nome_usuario || 'Sistema')}
                    </small>
                </div>
            `;
            div.appendChild(item);
        });
    } catch (err) {
        div.innerHTML = `<em style="padding: 15px; display: block; color: red;">Erro: ${escapeHtml(err.message)}</em>`;
    }
}

window.abrirTab = abrirTab;
window.alterarPerfil = alterarPerfil;
window.excluirUsuario = excluirUsuario;
window.criarAlerta = criarAlerta;