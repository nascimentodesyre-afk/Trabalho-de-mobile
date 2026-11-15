// ============================================================================
// SISTEMA DE GESTÃO DE PATRIMÔNIO - HISTÓRICO / LOG DE AUDITORIA (JS)
// ============================================================================

let historicoCache = [];

document.addEventListener("DOMContentLoaded", () => {
    carregarHistoricoGeral();
});

async function carregarHistoricoGeral() {
    const tbody = document.getElementById("tabela-historico");
    if (!tbody) return;

    tbody.innerHTML = `<tr><td colspan="5" style="text-align:center;">Carregando...</td></tr>`;

    try {
        const response = await fetch("/api/historico");
        if (!response.ok) throw new Error("Erro ao carregar histórico.");

        historicoCache = await response.json() || [];

        atualizarResumo(historicoCache);
        renderizarTabela(historicoCache);

    } catch (error) {
        console.error("Erro ao carregar histórico:", error);
        tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; color:red;">Erro ao carregar os dados.</td></tr>`;
    }
}

function atualizarResumo(lista) {
    const elTotal = document.getElementById("resumo-total");
    const elHoje = document.getElementById("resumo-hoje");
    const elChamados = document.getElementById("resumo-chamados");
    if (!elTotal || !elHoje || !elChamados) return;

    const hojeISO = new Date().toISOString().slice(0, 10);

    const eventosHoje = lista.filter(h => h.data_evento_iso === hojeISO).length;
    const chamadosUnicos = new Set(lista.map(h => h.id_chamado)).size;

    elTotal.innerText = lista.length;
    elHoje.innerText = eventosHoje;
    elChamados.innerText = chamadosUnicos;
}

// Filtra o cache local (sem novo fetch) por texto livre e/ou número do chamado
function aplicarFiltros() {
    const termo = (document.getElementById("filtro-busca")?.value || "").toLowerCase().trim();
    const numeroChamado = (document.getElementById("filtro-chamado")?.value || "").trim();

    const filtrados = historicoCache.filter(h => {
        if (numeroChamado && String(h.id_chamado) !== numeroChamado) return false;

        if (termo) {
            const alvo = [
                h.descricao,
                h.descricao_problema,
                h.nome_usuario,
                h.id_chamado
            ].join(" ").toLowerCase();
            if (!alvo.includes(termo)) return false;
        }

        return true;
    });

    renderizarTabela(filtrados);
}

function limparFiltros() {
    document.getElementById("filtro-busca").value = "";
    document.getElementById("filtro-chamado").value = "";
    renderizarTabela(historicoCache);
}

function renderizarTabela(lista) {
    const tbody = document.getElementById("tabela-historico");
    const contador = document.getElementById("filtro-contador");
    if (!tbody) return;

    if (contador) {
        const total = historicoCache.length;
        contador.innerText = (lista.length === total)
            ? `${total} evento(s) no total.`
            : `Mostrando ${lista.length} de ${total} evento(s).`;
    }

    if (!lista || lista.length === 0) {
        tbody.innerHTML = `<tr><td colspan="5" style="text-align:center;">Nenhum evento encontrado.</td></tr>`;
        return;
    }

    tbody.innerHTML = "";

        for (const h of lista) {
        const prioridadeSafe = h.prioridade ? String(h.prioridade).toLowerCase() : null;
        const tr = document.createElement("tr");
        tr.innerHTML = `
            <td>${escapeHtml(h.data_evento || '-')}</td>
            <td>
                <strong>#${h.id_chamado ?? '-'}</strong><br>
                <small class="text-muted">${escapeHtml(h.descricao_problema || 'Chamado não encontrado')}</small>
            </td>
            <td>${escapeHtml(h.nome_usuario || 'Sistema')}</td>
            <td>${prioridadeSafe ? `<span class="status ${prioridadeSafe}">${escapeHtml(h.prioridade)}</span>` : '-'}</td>
            <td>${escapeHtml(h.descricao || '')}</td>
        `;
        tbody.appendChild(tr);
    }
}