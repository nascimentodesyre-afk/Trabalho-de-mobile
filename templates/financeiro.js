// ============================================================================
// MÓDULO FINANCEIRO - IPE (v3 - modo consulta)
// ============================================================================

let categoriasCache = [];
let movimentacoesCache = [];
let idParaExcluir = null;
let isAdmin = false;
let origensCache = [];
let origemSelecionada = "";
let filtroOrigemAtual = "";

document.addEventListener("DOMContentLoaded", async () => {
    await verificarPerfil();
    await carregarOrigens();
    carregarResumo();
    carregarGrafico();
    carregarCategorias();
    carregarVerbas();
    carregarMovimentacoes();

    const form = document.getElementById("form-mov");
    if (form) form.addEventListener("submit", salvarMovimentacao);
    const btnConfirma = document.getElementById("btn-confirma-sim");
    if (btnConfirma) btnConfirma.addEventListener("click", confirmarExclusao);
});

async function verificarPerfil() {
    try {
        const u = await obterPerfilAtual();
        isAdmin = u && u.id_perfil === 1;

        const btnDespesa = document.getElementById("btn-nova-despesa");
        const btnReceita = document.getElementById("btn-nova-receita");

        if (isAdmin) {
            if (btnDespesa) btnDespesa.style.display = "inline-block";
            if (btnReceita) btnReceita.style.display = "inline-block";
        } else {
            if (btnDespesa) btnDespesa.remove();
            if (btnReceita) btnReceita.remove();

            // Esconde a coluna "Ações" inteira
            const tabela = document.querySelector("#tabela-movimentacoes")?.closest("table");
            if (tabela) {
                tabela.classList.add("modo-consulta");
                tabela.querySelectorAll("th:last-child, td:last-child")
                    .forEach(el => el.classList.add("col-acoes"));
            }
        }
    } catch {}
}

function formatarBRL(valor) {
    return "R$ " + parseFloat(valor || 0).toFixed(2)
        .replace(".", ",")
        .replace(/\B(?=(\d{3})+(?!\d))/g, ".");
}

function abrirModal() { document.getElementById("modal-mov").classList.add("show"); }
function fecharModal() { document.getElementById("modal-mov").classList.remove("show"); }
function fecharConfirma() { document.getElementById("modal-confirma").classList.remove("show"); }

async function carregarResumo() {
    try {
        const r = await fetchJson("/api/financeiro/resumo");
        document.getElementById("card-entradas").innerText = formatarBRL(r.total_entradas);
        document.getElementById("card-saidas").innerText = formatarBRL(r.total_saidas);
        document.getElementById("card-saldo").innerText = formatarBRL(r.saldo_atual);
        document.getElementById("card-bloqueado").innerText = formatarBRL(r.saldo_bloqueado);
        const cardSaldo = document.getElementById("card-saldo");
        cardSaldo.style.color = r.saldo_atual >= 0 ? "#15803d" : "#991b1b";
    } catch (err) {
        console.error("Erro resumo:", err);
    }
}

async function carregarGrafico() {
    const div = document.getElementById("grafico-barras");
    if (!div) return;
    try {
        const dados = await fetchJson("/api/financeiro/grafico") || [];
        if (dados.length === 0) {
            div.innerHTML = '<em style="align-self:center;">Sem dados para exibir.</em>';
            return;
        }
        let max = 0;
        dados.forEach(d => { max = Math.max(max, d.entradas, d.saidas); });
        if (max === 0) max = 1;

        div.innerHTML = "";
        dados.forEach(d => {
            const altEntrada = (d.entradas / max) * 100;
            const altSaida = (d.saidas / max) * 100;
            const grupo = document.createElement("div");
            grupo.className = "barra-grupo";
            grupo.innerHTML = `
                <div class="barras" title="Entradas: ${formatarBRL(d.entradas)} | Saídas: ${formatarBRL(d.saidas)}">
                    <div class="barra entrada" style="height:${altEntrada}%;"></div>
                    <div class="barra saida" style="height:${altSaida}%;"></div>
                </div>
                <div class="barra-label">${escapeHtml(d.mes_label)}</div>
            `;
            div.appendChild(grupo);
        });
    } catch (err) {
        console.error("Erro gráfico:", err);
        div.innerHTML = `<em style="align-self:center; color:red;">Erro: ${escapeHtml(err.message)}</em>`;
    }
}

async function carregarCategorias() {
    try {
        categoriasCache = await fetchJson("/api/financeiro/categorias") || [];
        const select = document.getElementById("filtro-categoria");
        if (select) {
            select.innerHTML = '<option value="">Todas</option>';
            categoriasCache.forEach(c => {
                select.innerHTML += `<option value="${escapeAttr(c)}">${escapeHtml(c)}</option>`;
            });
        }
        const datalist = document.getElementById("lista-categorias");
        if (datalist) {
            datalist.innerHTML = "";
            categoriasCache.forEach(c => {
                datalist.innerHTML += `<option value="${escapeAttr(c)}">`;
            });
        }
    } catch (err) {
        console.error("Erro categorias:", err);
    }
}

async function carregarVerbas() {
    try {
        const verbas = await fetchJson("/api/financeiro/verbas") || [];
        const select = document.getElementById("mov-verba");
        if (!select) return;
        select.innerHTML = '<option value="">— Nenhuma —</option>';
        verbas.forEach(v => {
            select.innerHTML += `<option value="${v.id_verba}">${escapeHtml(v.nome)} (Saldo: ${formatarBRL(v.saldo_atual)})</option>`;
        });
    } catch (err) {
        console.error("Erro verbas:", err);
    }
}

async function carregarMovimentacoes() {
    const tbody = document.getElementById("tabela-movimentacoes");
    if (!tbody) return;
    tbody.innerHTML = '<tr><td colspan="9" style="text-align:center;">Carregando...</td></tr>';

    const params = new URLSearchParams();
    const tipo = document.getElementById("filtro-tipo")?.value || "";
    const categoria = document.getElementById("filtro-categoria")?.value || "";
    const busca = document.getElementById("filtro-busca")?.value.trim() || "";
    const dataIni = document.getElementById("filtro-data-ini")?.value || "";
    const dataFim = document.getElementById("filtro-data-fim")?.value || "";

    if (tipo) params.append("tipo", tipo);
    if (categoria) params.append("categoria", categoria);
    if (busca) params.append("busca", busca);
    if (dataIni) params.append("data_ini", dataIni);
    if (dataFim) params.append("data_fim", dataFim);
    if (filtroOrigemAtual) params.append("origem", filtroOrigemAtual);

    try {
        movimentacoesCache = await fetchJson("/api/financeiro/movimentacoes?" + params.toString()) || [];
        const contador = document.getElementById("contador-movs");
        if (contador) contador.innerText = `${movimentacoesCache.length} movimentação(ões) encontrada(s).`;

        if (movimentacoesCache.length === 0) {
            const colspan = isAdmin ? 9 : 8;
            tbody.innerHTML = `<tr><td colspan="${colspan}" class="empty-state">Nenhuma movimentação encontrada.</td></tr>`;
            return;
        }

        tbody.innerHTML = "";
        movimentacoesCache.forEach(m => {
            const ehReceita = m.tipo_movimento === "Receita";
            const categoria = m.categoria_despesa || (ehReceita ? "—" : "Sem categoria");

            let origemBadge = '<span style="color: var(--text-light); font-size: 0.75rem;">—</span>';
            if (m.origem) {
                origemBadge = `<span class="badge-origem" style="background:${escapeAttr(m.origem_cor)};">
                    ${escapeHtml(m.origem_icone)} ${escapeHtml(m.origem_nome)}
                </span>`;
            }

            const acoesHtml = isAdmin ? `
                <td class="col-acoes">
                    <button class="btn-mini edit" onclick="editarMovimentacao(${m.id_lancamento})">✏ Editar</button>
                    <button class="btn-mini del" onclick="excluirMovimentacao(${m.id_lancamento})">🗑</button>
                </td>
            ` : ``;

            const tr = document.createElement("tr");
            tr.innerHTML = `
                <td>#${m.id_lancamento}</td>
                <td>${escapeHtml(m.data_formatada)}</td>
                <td><span class="badge-tipo ${ehReceita ? 'receita' : 'despesa'}">${escapeHtml(m.tipo_movimento)}</span></td>
                <td>${escapeHtml(m.descricao || '—')}</td>
                <td>${escapeHtml(categoria)}</td>
                <td>${origemBadge}</td>
                <td style="font-weight:600; color:${ehReceita ? '#15803d' : '#991b1b'};">
                    ${ehReceita ? '+' : '-'} ${formatarBRL(m.valor)}
                </td>
                <td>
                    <span class="status ${m.status === 'Aprovado' || m.status === 'Recebido' ? 'ativo' : 'manutencao'}">
                        ${escapeHtml(m.status)}
                    </span>
                </td>
                ${acoesHtml}
            `;
            tbody.appendChild(tr);
        });
    } catch (err) {
        console.error("Erro movimentações:", err);
        tbody.innerHTML = `<tr><td colspan="9" style="text-align:center; color:red;">
            Erro: ${escapeHtml(err.message)}
        </td></tr>`;
    }
}

function limparFiltros() {
    ["filtro-busca", "filtro-categoria", "filtro-tipo", "filtro-data-ini", "filtro-data-fim"].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.value = "";
    });
    carregarMovimentacoes();
}

function setTipo(tipo) {
    document.getElementById("mov-tipo").value = tipo;
    document.getElementById("btn-tipo-receita").classList.toggle("active", tipo === "Receita");
    document.getElementById("btn-tipo-receita").classList.toggle("receita", tipo === "Receita");
    document.getElementById("btn-tipo-despesa").classList.toggle("active", tipo === "Despesa");
    document.getElementById("btn-tipo-despesa").classList.toggle("despesa", tipo === "Despesa");
    document.getElementById("grupo-aprovacao").style.display = tipo === "Despesa" ? "block" : "none";
}

function abrirModalNova(tipo = "Despesa") {
    if (!isAdmin) return;
    document.getElementById("modal-titulo").innerText = "Nova Movimentação";
    document.getElementById("form-mov").reset();
    document.getElementById("mov-id").value = "";
    document.getElementById("mov-aprovado").checked = true;
    const toggle = document.querySelector(".toggle-tipo");
    if (toggle) toggle.style.display = "inline-flex";
    setTipo(tipo);
    abrirModal();
}

function editarMovimentacao(id) {
    if (!isAdmin) return;
    const m = movimentacoesCache.find(x => x.id_lancamento === id);
    if (!m) return;

    document.getElementById("modal-titulo").innerText = "Editar Movimentação #" + id;
    document.getElementById("mov-id").value = id;
    document.getElementById("mov-descricao").value = m.descricao || "";
    document.getElementById("mov-valor").value = m.valor;
    document.getElementById("mov-forma").value = m.forma_pagamento || "Pix";
    document.getElementById("mov-categoria").value = m.categoria_despesa || "";
    document.getElementById("mov-doc").value = m.numero_documento || "";

    const toggle = document.querySelector(".toggle-tipo");
    if (toggle) toggle.style.display = "none";
    document.getElementById("mov-tipo").value = m.tipo_movimento;
    document.getElementById("grupo-aprovacao").style.display = m.tipo_movimento === "Despesa" ? "block" : "none";
    document.getElementById("mov-aprovado").checked = m.status === "Aprovado" || m.status === "Recebido";

    abrirModal();
}

async function salvarMovimentacao(e) {
    e.preventDefault();
    if (!isAdmin) { toast("Apenas administradores podem salvar movimentações.", "aviso"); return; }

    const id = document.getElementById("mov-id").value;
    const tipo = document.getElementById("mov-tipo").value;
    const descricao = document.getElementById("mov-descricao").value.trim();
    const valor = document.getElementById("mov-valor").value;
    const forma = document.getElementById("mov-forma").value;
    const categoria = document.getElementById("mov-categoria").value.trim();
    const doc = document.getElementById("mov-doc").value.trim();
    const verba = document.getElementById("mov-verba").value;
    const aprovado = document.getElementById("mov-aprovado").checked;

    if (!descricao) { toast("Informe uma descrição.", "aviso"); return; }
    if (!valor || parseFloat(valor) <= 0) { toast("Informe um valor válido.", "aviso"); return; }

    const formData = new FormData();
    if (!id) {
        formData.append("tipo_movimento", tipo);
        formData.append("descricao", descricao);
        formData.append("valor", valor);
        formData.append("categoria", categoria);
        formData.append("forma_pagamento", forma);
        formData.append("numero_documento", doc);
        formData.append("aprovacao", aprovado ? "1" : "0");
        if (verba) formData.append("id_verba", verba);
    } else {
        formData.append("descricao", descricao);
        formData.append("valor", valor);
        formData.append("categoria", categoria);
        formData.append("forma_pagamento", forma);
        formData.append("numero_documento", doc);
    }

    const url = id ? `/api/financeiro/movimentacoes/${id}` : "/api/financeiro/movimentacoes";
    const metodo = id ? "PUT" : "POST";
    const btnSalvar = document.getElementById("btn-salvar-mov");

    await comSpinner(btnSalvar, async () => {
        try {
            const data = await fetchJson(url, { method: metodo, body: formData });
            toast(data.mensagem || "Salvo!", "sucesso");
            fecharModal();
            const toggle = document.querySelector(".toggle-tipo");
            if (toggle) toggle.style.display = "inline-flex";
            carregarResumo();
            carregarGrafico();
            carregarMovimentacoes();
            carregarVerbas();
        } catch (err) {
            toast("Erro: " + err.message, "erro");
        }
    });
}

function excluirMovimentacao(id) {
    if (!isAdmin) return;
    const m = movimentacoesCache.find(x => x.id_lancamento === id);
    if (!m) return;

    idParaExcluir = id;
    document.getElementById("confirma-msg").innerText =
        `Tem certeza que deseja excluir a movimentação "${m.descricao}" (${formatarBRL(m.valor)})? Esta ação não pode ser desfeita.`;
    document.getElementById("modal-confirma").classList.add("show");
}

async function confirmarExclusao() {
    if (!idParaExcluir || !isAdmin) return;
    try {
        const data = await fetchJson(`/api/financeiro/movimentacoes/${idParaExcluir}`, { method: "DELETE" });
        toast(data.mensagem || "Excluído!", "sucesso");
        fecharConfirma();
        carregarResumo();
        carregarGrafico();
        carregarMovimentacoes();
    } catch (err) {
        toast("Erro: " + err.message, "erro");
    } finally {
        idParaExcluir = null;
    }
}

async function tentarNovaDespesa() {
    await protegerAcao("admin", () => abrirModalNova("Despesa"));
}

async function tentarNovaReceita() {
    await protegerAcao("admin", () => abrirModalNova("Receita"));
}

async function carregarOrigens() {
    try {
        origensCache = await fetchJson("/api/financeiro/origens") || [];
        renderizarOrigemSelector();
        renderizarResumoOrigens();
        renderizarFiltroOrigens();
    } catch (err) {
        console.error("Erro origens:", err);
    }
}

function renderizarOrigemSelector() {
    const div = document.getElementById("origem-selector");
    if (!div) return;
    div.innerHTML = origensCache.map(o => `
        <div class="origem-card" data-origem="${escapeAttr(o.id)}" onclick="selecionarOrigem('${escapeAttr(o.id)}')">
            <span class="origem-icone">${escapeHtml(o.icone)}</span>
            <div class="origem-info">
                <div class="origem-nome">${escapeHtml(o.nome)}</div>
                <div class="origem-desc">${escapeHtml(o.descricao)}</div>
            </div>
        </div>
    `).join("");
}

function selecionarOrigem(id) {
    origemSelecionada = (origemSelecionada === id) ? "" : id;
    document.querySelectorAll(".origem-card").forEach(c => {
        c.classList.toggle("selected", c.dataset.origem === origemSelecionada);
    });
}

async function renderizarResumoOrigens() {
    const div = document.getElementById("origens-resumo");
    if (!div) return;
    try {
        const dados = await fetchJson("/api/financeiro/resumo-por-origem") || [];
        if (dados.length === 0) {
            div.innerHTML = `<div style="grid-column: 1/-1; padding: 30px; text-align: center; color: var(--text-light);">
                <em>Nenhuma movimentação registrada por origem ainda.</em></div>`;
            return;
        }
        div.innerHTML = dados.map(o => `
            <div class="origem-resumo-card" style="border-left-color: ${escapeAttr(o.cor)};"
                 onclick="filtrarPorOrigem('${escapeAttr(o.id)}', null)">
                <span class="icone-origem">${escapeHtml(o.icone)}</span>
                <h4>${escapeHtml(o.nome)}</h4>
                <div class="valor" style="color: ${escapeAttr(o.cor)};">
                    R$ ${parseFloat(o.saldo).toFixed(2).replace('.', ',')}
                </div>
                <div class="subinfo">
                    <span>⬆ <span class="positivo">R$ ${parseFloat(o.entradas).toFixed(2).replace('.', ',')}</span></span>
                    <span>⬇ <span class="negativo">R$ ${parseFloat(o.saidas).toFixed(2).replace('.', ',')}</span></span>
                </div>
            </div>
        `).join("");
    } catch (err) {
        console.error("Erro resumo origens:", err);
    }
}

function renderizarFiltroOrigens() {
    const container = document.getElementById("filtro-origem-container");
    if (!container) return;
    let html = `<button type="button" class="filtro-origem-btn ${filtroOrigemAtual === '' ? 'ativo' : ''}"
                onclick="filtrarPorOrigem('', this)">Todas</button>`;
    origensCache.forEach(o => {
        if (o.total_movimentacoes > 0) {
            html += `<button type="button" class="filtro-origem-btn ${filtroOrigemAtual === o.id ? 'ativo' : ''}"
                            onclick="filtrarPorOrigem('${escapeAttr(o.id)}', this)">
                ${escapeHtml(o.icone)} ${escapeHtml(o.nome)}
                <span class="badge-qtd">${o.total_movimentacoes}</span>
            </button>`;
        }
    });
    container.innerHTML = html;
}

function filtrarPorOrigem(origem, btn) {
    filtroOrigemAtual = origem;
    document.querySelectorAll(".filtro-origem-btn").forEach(b => b.classList.remove("ativo"));
    if (btn) btn.classList.add("ativo");
    else {
        const botao = document.querySelector(`.filtro-origem-btn[onclick*="'${origem}'"]`);
        if (botao) botao.classList.add("ativo");
    }
    carregarMovimentacoes();
}

window.tentarNovaDespesa = tentarNovaDespesa;
window.tentarNovaReceita = tentarNovaReceita;
window.abrirModalNova = abrirModalNova;
window.editarMovimentacao = editarMovimentacao;
window.excluirMovimentacao = excluirMovimentacao;
window.limparFiltros = limparFiltros;
window.fecharModal = fecharModal;
window.fecharConfirma = fecharConfirma;
window.setTipo = setTipo;
window.selecionarOrigem = selecionarOrigem;
window.filtrarPorOrigem = filtrarPorOrigem;