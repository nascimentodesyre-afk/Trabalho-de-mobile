// ============================================================================
// MÓDULO DE HISTÓRICO DE REPAROS - IPE
// ============================================================================

let rankingCache = [];
let isAdmin = false;

document.addEventListener("DOMContentLoaded", async () => {
    await verificarPerfil();
    carregarResumo();
    carregarRanking();
});

// ============================================================================
// VERIFICAR PERFIL
// ============================================================================

async function verificarPerfil() {
    try {
        const res = await fetch("/api/dados_usuario");
        if (!res.ok) return;
        const u = await res.json();
        isAdmin = u.id_perfil === 1;
    } catch {}
}

// ============================================================================
// HELPERS
// ============================================================================

function formatarBRL(v) {
    return "R$ " + parseFloat(v || 0).toFixed(2)
        .replace(".", ",")
        .replace(/\B(?=(\d{3})+(?!\d))/g, ".");
}

function fecharDetalhes() {
    document.getElementById("modal-detalhes").classList.remove("show");
}

// ============================================================================
// RESUMO
// ============================================================================

async function carregarResumo() {
    try {
        const res = await fetch("/api/reparos/resumo");
        const r = await res.json();

        document.getElementById("stat-total-reparos").innerText = r.total_reparos;
        document.getElementById("stat-bens-criticos").innerText = r.bens_criticos;
        document.getElementById("stat-custo").innerText = formatarBRL(r.custo_total_manutencoes);
        document.getElementById("stat-tempo").innerText = r.tempo_medio_reparo_dias + " dias";
    } catch (err) {
        console.error("Erro resumo:", err);
    }
}

// ============================================================================
// RANKING
// ============================================================================

async function carregarRanking() {
    const tbody = document.getElementById("tabela-ranking");
    tbody.innerHTML = '<tr><td colspan="10" style="text-align:center;">Carregando...</td></tr>';

    const periodo = document.getElementById("filtro-periodo").value || 365;
    const params = new URLSearchParams({ periodo: periodo, limite: 100 });

    try {
        const res = await fetch("/api/reparos/ranking?" + params.toString());
        if (!res.ok) throw new Error("HTTP " + res.status);
        rankingCache = await res.json();

        aplicarFiltroNivel();
    } catch (err) {
        console.error("Erro ranking:", err);
        tbody.innerHTML = '<tr><td colspan="10" style="text-align:center; color:red;">Erro ao carregar.</td></tr>';
    }
}

function aplicarFiltroNivel() {
    const termo = document.getElementById("filtro-busca").value.toLowerCase().trim();
    const nivel = document.getElementById("filtro-nivel").value;

    let filtrados = rankingCache;

    if (nivel) {
        filtrados = filtrados.filter(r => r.nivel_reincidencia === nivel);
    }

    if (termo) {
        filtrados = filtrados.filter(r => {
            const alvo = [r.nome, r.numero_patrimonio, r.nome_sala, r.bloco_sala, r.nome_categoria]
                .join(" ").toLowerCase();
            return alvo.includes(termo);
        });
    }

    renderizarTabela(filtrados);
}

function renderizarTabela(lista) {
    const tbody = document.getElementById("tabela-ranking");
    const contador = document.getElementById("contador-ranking");

    contador.innerText = `${lista.length} equipamento(s) com chamados registrados.`;

    if (lista.length === 0) {
        tbody.innerHTML = '<tr><td colspan="10" class="empty-state">Nenhum equipamento com chamados no período.</td></tr>';
        return;
    }

    tbody.innerHTML = "";
    lista.forEach((r, idx) => {
        const local = r.nome_sala !== "Não Alocado"
            ? `${escapeHtml(r.nome_sala)}${r.bloco_sala ? ' (' + escapeHtml(r.bloco_sala) + ')' : ''}`
            : "—";

        const tr = document.createElement("tr");
        tr.innerHTML = `
            <td><strong>${idx + 1}º</strong></td>
            <td>${escapeHtml(r.numero_patrimonio)}</td>
            <td>${escapeHtml(r.nome)}</td>
            <td>${escapeHtml(local)}</td>
            <td><strong>${r.total_chamados}</strong></td>
            <td>${r.total_manutencoes}</td>
            <td>${formatarBRL(r.valor_total_gasto)}</td>
            <td>
                <span class="badge-reincidencia ${r.nivel_reincidencia}">
                    ${r.nivel_reincidencia}
                </span>
            </td>
            <td style="font-size: 0.8rem; color: var(--text-light);">${r.ultimo_chamado || '—'}</td>
            <td>
                <button class="btn-mini ver" onclick="verDetalhes(${r.id_patrimonio})">
                    👁 Histórico
                </button>
            </td>
        `;
        tbody.appendChild(tr);
    });
}

function limparFiltros() {
    document.getElementById("filtro-busca").value = "";
    document.getElementById("filtro-periodo").value = "365";
    document.getElementById("filtro-nivel").value = "";
    carregarRanking();
}

// ============================================================================
// MODAL DE DETALHES
// ============================================================================

async function verDetalhes(idPatrimonio) {
    document.getElementById("detalhes-titulo").innerText = "Carregando...";
    document.getElementById("detalhes-conteudo").innerHTML = "<em>Carregando histórico...</em>";
    document.getElementById("modal-detalhes").classList.add("show");

    try {
        const res = await fetch(`/api/reparos/patrimonio/${idPatrimonio}`);
        const data = await res.json();

        if (!res.ok) {
            document.getElementById("detalhes-conteudo").innerHTML =
                `<p style="color:red;">${escapeHtml(data.erro || "Erro ao carregar.")}</p>`;
            return;
        }

        const p = data.patrimonio;
        const est = data.estatisticas;
        const reparos = data.reparos;

        document.getElementById("detalhes-titulo").innerText =
            `${p.nome} (Nº ${p.numero_patrimonio})`;

        // Botão de PDF: só aparece para ADM
        const botaoPdfHtml = isAdmin
            ? `
                <button onclick="exportarPDFReparos(${p.id_patrimonio})"
                        style="position: absolute; top: 15px; right: 15px;
                               background: linear-gradient(135deg, #F29310, #d97e0b);
                               color: white; border: none; padding: 10px 18px;
                               border-radius: 10px; cursor: pointer;
                               font-family: 'Poppins', sans-serif; font-weight: 600;
                               font-size: 0.85rem; box-shadow: 0 3px 8px rgba(242,147,16,0.3);">
                    📄 Exportar PDF
                </button>
            `
            : '';

        const bemHtml = `
            <div class="bem-header" style="position: relative;">
                <p><strong>Sala:</strong> ${escapeHtml(p.nome_sala)}${p.bloco_sala ? ' · ' + escapeHtml(p.bloco_sala) : ''}</p>
                <p><strong>Categoria:</strong> ${escapeHtml(p.nome_categoria)}</p>
                <p><strong>Data de Aquisição:</strong> ${p.data_aquisicao || '—'}</p>
                <p><strong>Valor Original:</strong> ${formatarBRL(p.valor_atual)}</p>
                ${botaoPdfHtml}
            </div>

            <div class="stats-grid">
                <div class="stat-box">
                    <small>Total de Chamados</small>
                    <strong>${est.total_chamados}</strong>
                </div>
                <div class="stat-box">
                    <small>Reparos Realizados</small>
                    <strong>${est.total_reparos}</strong>
                </div>
                <div class="stat-box">
                    <small>Custo Total</small>
                    <strong>${formatarBRL(est.valor_total_gasto)}</strong>
                </div>
                <div class="stat-box">
                    <small>Tempo Médio</small>
                    <strong>${est.tempo_medio_reparo_dias}d</strong>
                </div>
                <div class="stat-box">
                    <small>Reincidência</small>
                    <strong><span class="badge-reincidencia ${est.nivel_reincidencia}">
                        ${est.nivel_reincidencia}
                    </span></strong>
                </div>
            </div>
        `;

        let timelineHtml = "";
        if (reparos.length === 0) {
            timelineHtml = "<p style='color: var(--text-light); padding: 20px; text-align: center;'>Nenhum reparo registrado ainda.</p>";
        } else {
            timelineHtml = '<div class="timeline">';
            reparos.forEach(r => {
                const statusClass = (r.nome_status || "").toLowerCase()
                    .normalize("NFD").replace(/[\u0300-\u036f]/g, "")
                    .replace(" ", "-");

                let anexosHtml = "";
                if (r.anexos && r.anexos.length > 0) {
                    anexosHtml = `
                        <div class="anexos-list">
                            ${r.anexos.map(a => {
                                const nome = a.caminho.split('/').pop();
                                return `<a class="anexo-tag" href="/${escapeAttr(a.caminho)}" target="_blank">📎 ${escapeHtml(nome)}</a>`;
                            }).join("")}
                        </div>
                    `;
                }

                timelineHtml += `
                    <div class="timeline-item ${statusClass}">
                        <div class="timeline-header">
                            <div>
                                <div class="timeline-title">Chamado #${r.id_chamado} — ${escapeHtml(r.tipo_chamado)}</div>
                                <div class="timeline-date">${escapeHtml(r.data_abertura)}</div>
                            </div>
                            <span class="badge-status ${r.nome_status.split(' ')[0]}">${escapeHtml(r.nome_status)}</span>
                        </div>
                        <div class="timeline-body">
                            <strong>Problema:</strong> ${escapeHtml(r.descricao_problema)}
                        </div>
                        ${r.observacao_manutencao ? `
                            <div class="timeline-body">
                                <strong>Serviço realizado:</strong> ${escapeHtml(r.observacao_manutencao)}
                            </div>
                        ` : ''}
                        <div class="timeline-meta">
                            <span><strong>Prioridade:</strong> ${escapeHtml(r.prioridade)}</span>
                            <span><strong>Solicitante:</strong> ${escapeHtml(r.nome_solicitante)}</span>
                            ${r.data_inicio_manutencao ? `<span><strong>Início reparo:</strong> ${escapeHtml(r.data_inicio_manutencao)}</span>` : ''}
                            ${r.data_fim_manutencao ? `<span><strong>Fim reparo:</strong> ${escapeHtml(r.data_fim_manutencao)}</span>` : ''}
                            ${r.duracao_dias !== null && r.duracao_dias !== undefined ? `<span><strong>Duração:</strong> ${r.duracao_dias} dia(s)</span>` : ''}
                        </div>
                        ${anexosHtml}
                    </div>
                `;
            });
            timelineHtml += "</div>";
        }

        document.getElementById("detalhes-conteudo").innerHTML = bemHtml + timelineHtml;

    } catch (err) {
        document.getElementById("detalhes-conteudo").innerHTML =
            `<p style="color:red;">Erro: ${escapeHtml(err.message)}</p>`;
    }
}

// ============================================================================
// EXPORTAR PDF
// ============================================================================

function exportarPDFReparos(idPatrimonio) {
    if (!isAdmin) {
        alert("Apenas administradores podem exportar o relatório em PDF.");
        return;
    }
    window.open(`/api/reparos/patrimonio/${idPatrimonio}/pdf`, "_blank");
}