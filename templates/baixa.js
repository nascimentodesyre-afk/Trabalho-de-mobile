// ============================================================================
// MÓDULO DE BAIXA E INUTILIZAÇÃO - IPE (v3)
// Inclui: X no topo, botão Fechar no rodapé, Esc, clique fora
// ============================================================================

let patrimoniosDisponiveis = [];

document.addEventListener("DOMContentLoaded", () => {
    carregarResumo();
    carregarBaixas();
    carregarPatrimoniosSelect();

    const form = document.getElementById("form-baixa");
    if (form) form.addEventListener("submit", confirmarBaixa);

    // ✅ Fecha ao clicar fora do conteúdo
    const modalBaixa = document.getElementById("modal-baixa");
    if (modalBaixa) {
        modalBaixa.addEventListener("click", (e) => {
            if (e.target === modalBaixa) fecharModal();
        });
    }

    // ✅ Fecha com tecla Esc
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") {
            const modal = document.getElementById("modal-baixa");
            if (modal && modal.classList.contains("show")) fecharModal();
        }
    });
});

// ============================================================================
// CONTROLE DO MODAL
// ============================================================================

function abrirModal() {
    const modal = document.getElementById("modal-baixa");
    if (modal) modal.classList.add("show");
}

function fecharModal() {
    const modal = document.getElementById("modal-baixa");
    if (modal) modal.classList.remove("show");

    const form = document.getElementById("form-baixa");
    if (form) {
        form.reset();
        form.style.display = "none";
    }

    const area = document.getElementById("area-verificacao");
    if (area) {
        area.style.display = "none";
        area.innerHTML = "";
    }

    const sel = document.getElementById("sel-patrimonio");
    if (sel) sel.value = "";
}

function abrirModalBaixa() {
    // Sempre começa limpo
    fecharModal();

    // Reabre limpo
    setTimeout(() => {
        abrirModal();
        carregarPatrimoniosSelect();
    }, 50);
}

// ============================================================================
// HELPERS
// ============================================================================

function formatarBRL(v) {
    return "R$ " + parseFloat(v || 0).toFixed(2)
        .replace(".", ",")
        .replace(/\B(?=(\d{3})+(?!\d))/g, ".");
}

// ============================================================================
// RESUMO
// ============================================================================

async function carregarResumo() {
    try {
        const r = await fetchJson("/api/baixa/resumo");
        document.getElementById("stat-total-baixas").innerText = r.total_baixados;
        document.getElementById("stat-baixas-mes").innerText = r.baixas_mes_atual;
        document.getElementById("stat-valor-baixado").innerText = formatarBRL(r.valor_total_perdido);
        document.getElementById("stat-ultima-baixa").innerText = r.ultima_baixa || "—";
    } catch (err) {
        console.error("Erro resumo baixas:", err);
    }
}

// ============================================================================
// LISTAGEM DE BAIXAS
// ============================================================================

async function carregarBaixas() {
    const tbody = document.getElementById("tabela-baixas");
    if (!tbody) return;
    tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;">Carregando...</td></tr>';

    try {
        const bens = await fetchJson("/api/baixa/listar") || [];

        const contador = document.getElementById("contador-baixas");
        if (contador) contador.innerText = `${bens.length} bem(ns) baixado(s).`;

        if (bens.length === 0) {
            tbody.innerHTML = '<tr><td colspan="8" class="empty-state">Nenhuma baixa registrada ainda.</td></tr>';
            return;
        }

        tbody.innerHTML = "";
        bens.forEach(b => {
            const local = b.nome_sala !== "—"
                ? `${b.nome_sala}${b.bloco_sala ? ' (' + b.bloco_sala + ')' : ''}`
                : "—";

            const tr = document.createElement("tr");
            tr.innerHTML = `
                <td><strong>${escapeHtml(b.numero_patrimonio)}</strong></td>
                <td>${escapeHtml(b.nome)}</td>
                <td>${escapeHtml(b.nome_categoria)}</td>
                <td>${escapeHtml(local)}</td>
                <td><span class="badge-valor">${formatarBRL(b.valor_atual)}</span></td>
                <td><span class="badge-baixa">${escapeHtml(b.data_baixa)}</span></td>
                <td><span class="badge-motivo">${escapeHtml(b.motivo || "—")}</span></td>
                <td>
                    <button class="btn-mini info" onclick="verDetalhesBaixa(${b.id_patrimonio})">
                        👁 Detalhes
                    </button>
                </td>
            `;
            tbody.appendChild(tr);
        });
    } catch (err) {
        console.error("Erro ao carregar baixas:", err);
        tbody.innerHTML = `<tr><td colspan="8" style="text-align:center; color:red;">
            Erro: ${escapeHtml(err.message)}
        </td></tr>`;
    }
}

// ============================================================================
// SELECT DE PATRIMÔNIOS
// ============================================================================

async function carregarPatrimoniosSelect() {
    const sel = document.getElementById("sel-patrimonio");
    if (!sel) return;
    sel.innerHTML = '<option value="">Carregando...</option>';

    try {
        const bens = await fetchJson("/api/inventario/listar") || [];
        patrimoniosDisponiveis = bens.filter(b => !b.processo_baixa);

        if (patrimoniosDisponiveis.length === 0) {
            sel.innerHTML = '<option value="">Nenhum patrimônio disponível para baixa</option>';
            return;
        }

        sel.innerHTML = '<option value="">— Selecionar patrimônio —</option>' +
            patrimoniosDisponiveis.map(b =>
                `<option value="${b.id_patrimonio}">
                    Nº ${escapeHtml(b.numero_patrimonio)} — ${escapeHtml(b.nome)} (${escapeHtml(b.nome_sala)})
                </option>`
            ).join("");
    } catch (err) {
        console.error("Erro ao carregar patrimônios:", err);
        sel.innerHTML = `<option value="">Erro: ${escapeHtml(err.message)}</option>`;
    }
}

// ============================================================================
// VERIFICAÇÃO DE VIABILIDADE
// ============================================================================

async function verificarPatrimonio() {
    const id = document.getElementById("sel-patrimonio").value;
    const area = document.getElementById("area-verificacao");
    const form = document.getElementById("form-baixa");

    if (!id) {
        area.style.display = "none";
        form.style.display = "none";
        return;
    }

    area.style.display = "block";
    area.innerHTML = '<em style="color: var(--text-light);">Verificando viabilidade de baixa...</em>';
    form.style.display = "none";

    try {
        const data = await fetchJson(`/api/baixa/verificar/${id}`);
        const p = data.patrimonio;

        const infoHtml = `
            <div class="item-info">
                <p><strong>Nº Patrimônio:</strong> ${escapeHtml(p.numero_patrimonio)}</p>
                <p><strong>Nome:</strong> ${escapeHtml(p.nome)}</p>
                <p><strong>Valor Atual:</strong> ${formatarBRL(p.valor_atual)}</p>
                <p><strong>Data de Aquisição:</strong> ${escapeHtml(p.data_aquisicao)}</p>
                <p><strong>Status Atual:</strong> ${escapeHtml(p.nome_status)}</p>
                ${p.historico_manutencoes && p.historico_manutencoes.length > 0 ? `
                    <p style="margin-top: 10px;"><strong>Histórico de Manutenções:</strong></p>
                    <div class="historico-manutencoes">
                        ${p.historico_manutencoes.map(m => `
                            <div class="item">
                                <strong>${escapeHtml(m.data_inicio)}</strong> — ${escapeHtml(m.observacao || 'Sem observação')}
                            </div>
                        `).join("")}
                    </div>
                ` : ''}
            </div>
        `;

        if (!data.pode_baixar) {
            let chamadosHtml = "";
            if (data.chamados_ativos && data.chamados_ativos.length > 0) {
                chamadosHtml = `
                    <p style="margin-top: 10px;"><strong>Chamados ativos vinculados:</strong></p>
                    <ul>
                        ${data.chamados_ativos.map(c => `
                            <li>#${c.id_chamado} — ${escapeHtml(c.nome_status)} (${escapeHtml(c.data_abertura)}):
                                ${escapeHtml((c.descricao_problema || "").substring(0, 80))}...</li>
                        `).join("")}
                    </ul>
                `;
            }
            area.innerHTML = `
                ${infoHtml}
                <div class="alerta-bloqueio">
                    <h4>⛔ Baixa não permitida</h4>
                    <p>${escapeHtml(data.motivo)}</p>
                    ${chamadosHtml}
                </div>
            `;
            return;
        }

        area.innerHTML = `
            ${infoHtml}
            <div class="alerta-ok">
                ✅ Nenhum chamado ativo vinculado. A baixa pode ser registrada.
            </div>
        `;
        document.getElementById("baixa-id").value = p.id_patrimonio;
        form.style.display = "block";
    } catch (err) {
        area.innerHTML = `<div class="alerta-bloqueio">Erro: ${escapeHtml(err.message)}</div>`;
    }
}

// ============================================================================
// CONFIRMAR BAIXA
// ============================================================================

async function confirmarBaixa(e) {
    e.preventDefault();

    const id = document.getElementById("baixa-id").value;
    const motivo = document.getElementById("baixa-motivo").value;
    const laudo = document.getElementById("baixa-laudo").value.trim();
    const processo = document.getElementById("baixa-processo").value.trim();

    if (!id) { toast("Selecione um patrimônio.", "aviso"); return; }
    if (!motivo) { toast("Selecione o motivo.", "aviso"); return; }
    if (laudo.length < 10) { toast("O laudo precisa ter ≥10 caracteres.", "aviso"); return; }

    const bem = patrimoniosDisponiveis.find(p => String(p.id_patrimonio) === String(id));
    const nome = bem ? bem.nome : "patrimônio";
    const numero = bem ? bem.numero_patrimonio : id;

    const ok1 = await confirmarAcao(
        `⚠️ Confirmar a <strong>BAIXA DEFINITIVA</strong>?\n\nMotivo: <strong>${motivo}</strong>`,
        { titulo: "Registrar baixa", textoConfirmar: "Continuar", perigo: true }
    );
    if (!ok1) return;

    const ok2 = await confirmarAcao(
        `Confirma a baixa de <strong>${escapeHtml(nome)}</strong> (Nº ${escapeHtml(numero)})?\n\n` +
        `A baixa não pode ser desfeita.`,
        { titulo: "Confirmação final", textoConfirmar: "Sim, dar baixa", perigo: true }
    );
    if (!ok2) return;

    const formData = new FormData();
    formData.append("id_patrimonio", id);
    formData.append("motivo", motivo);
    formData.append("laudo", laudo);
    formData.append("processo", processo);

    const btn = e.target.querySelector('button[type="submit"]');

    await comSpinner(btn, async () => {
        try {
            const data = await fetchJson("/api/baixa/registrar", { method: "POST", body: formData });
            toast(data.mensagem, "sucesso");
            fecharModal();
            carregarBaixas();
            carregarResumo();
            carregarPatrimoniosSelect();
        } catch (err) {
            toast("Erro: " + err.message, "erro");
        }
    });
}

// ============================================================================
// DETALHES DE UMA BAIXA
// ============================================================================

async function verDetalhesBaixa(idPatrimonio) {
    try {
        const bens = await fetchJson("/api/inventario/listar");
        const b = (bens || []).find(x => x.id_patrimonio === idPatrimonio);
        if (!b) { toast("Patrimônio não encontrado.", "erro"); return; }
        toast(
            `Nº ${b.numero_patrimonio} · ${b.nome} · ${b.nome_categoria || '—'} · ` +
            `Local: ${b.nome_sala} · Valor: ${formatarBRL(b.valor_compra)}`,
            "info", 6000
        );
    } catch (err) {
        toast("Erro: " + err.message, "erro");
    }
}

// ============================================================================
// EXPORTA GLOBAIS
// ============================================================================

window.abrirModalBaixa = abrirModalBaixa;
window.fecharModal = fecharModal;
window.verificarPatrimonio = verificarPatrimonio;
window.confirmarBaixa = confirmarBaixa;
window.verDetalhesBaixa = verDetalhesBaixa;