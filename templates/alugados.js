// ============================================================================
// MÓDULO DE BENS ALUGADOS E TERCEIRIZADOS - IPE (v3 - modo consulta)
// ============================================================================

let bensCache = [];
let salasCache = [];
let isAdmin = false;

document.addEventListener("DOMContentLoaded", async () => {
    await verificarPerfil();
    carregarResumo();
    carregarSalas();
    carregarBens();

    const form = document.getElementById("form-bem");
    if (form) form.addEventListener("submit", salvarBem);
});

async function verificarPerfil() {
    try {
        const u = await obterPerfilAtual();
        isAdmin = u && u.id_perfil === 1;
        const btnNovo = document.getElementById("btn-novo-bem");
        if (isAdmin) {
            if (btnNovo) btnNovo.style.display = "inline-block";
        } else {
            if (btnNovo) btnNovo.remove();

            // Esconde a coluna "Ações" inteira
            const tabela = document.querySelector("#tabela-bens")?.closest("table");
            if (tabela) {
                tabela.classList.add("modo-consulta");
                tabela.querySelectorAll("th:last-child, td:last-child")
                    .forEach(el => el.classList.add("col-acoes"));
            }
        }
    } catch {}
}

function formatarBRL(v) {
    return "R$ " + parseFloat(v || 0).toFixed(2)
        .replace(".", ",")
        .replace(/\B(?=(\d{3})+(?!\d))/g, ".");
}

function abrirModal() { document.getElementById("modal-bem").classList.add("show"); }
function fecharModal() {
    document.getElementById("modal-bem").classList.remove("show");
    document.getElementById("form-bem").reset();
    document.getElementById("bem-id").value = "";
    document.getElementById("bem-tipo").disabled = false;
    document.getElementById("bem-numero").disabled = false;
}

async function carregarResumo() {
    try {
        const r = await fetchJson("/api/alugados/resumo");
        document.getElementById("stat-alugados").innerText = r.total_alugados;
        document.getElementById("stat-terceirizados").innerText = r.total_terceirizados;
        document.getElementById("stat-custo").innerText = formatarBRL(r.custo_mensal_total);
        document.getElementById("stat-vencendo").innerText = r.contratos_vencendo_30d;
    } catch (err) {
        console.error("Erro resumo:", err);
    }
}

async function carregarSalas() {
    try {
        salasCache = await fetchJson("/api/salas") || [];
        const sel = document.getElementById("bem-sala");
        if (!sel) return;
        sel.innerHTML = '<option value="">— Não alocado —</option>' +
            salasCache.map(s => `<option value="${s.id_sala}">${escapeHtml(s.nome)}${s.bloco ? ' - ' + escapeHtml(s.bloco) : ''}</option>`).join("");
    } catch (err) {
        console.error("Erro ao carregar salas:", err);
    }
}

async function carregarBens() {
    const tbody = document.getElementById("tabela-bens");
    if (!tbody) return;
    tbody.innerHTML = '<tr><td colspan="9" style="text-align:center;">Carregando...</td></tr>';

    const params = new URLSearchParams();
    const busca = document.getElementById("filtro-busca")?.value.trim() || "";
    const fornecedor = document.getElementById("filtro-fornecedor")?.value.trim() || "";
    const vencendo = document.getElementById("filtro-vencendo")?.value || "";

    if (busca) params.append("busca", busca);
    if (fornecedor) params.append("fornecedor", fornecedor);
    if (vencendo) params.append("vencendo", vencendo);

    try {
        bensCache = await fetchJson("/api/alugados/listar?" + params.toString()) || [];

        const contador = document.getElementById("contador-bens");
        if (contador) contador.innerText = `${bensCache.length} contrato(s) encontrado(s).`;

        if (bensCache.length === 0) {
            const colspan = isAdmin ? 9 : 8;
            tbody.innerHTML = `<tr><td colspan="${colspan}" class="empty-state">Nenhum bem alugado ou terceirizado cadastrado.</td></tr>`;
            return;
        }

        tbody.innerHTML = "";
        bensCache.forEach(b => {
            const tipoClasse = (b.tipo_posse || "").toLowerCase() === "terceirizado" ? "terceirizado" : "alugado";
            const statusClasse = (b.status_contrato || "Sem data").replace(" ", "");

            const acoesHtml = isAdmin ? `
                <td class="col-acoes">
                    <button class="btn-mini edit" onclick="editarBem(${b.id_patrimonio})">✏ Editar</button>
                    <button class="btn-mini del btn-excluir-bem" data-id="${b.id_patrimonio}" data-nome="${escapeAttr(b.nome)}">🗑</button>
                </td>
            ` : ``;

            const tr = document.createElement("tr");
            tr.innerHTML = `
                <td><strong>${escapeHtml(b.numero_patrimonio)}</strong></td>
                <td>${escapeHtml(b.nome)}</td>
                <td><span class="badge-tipo ${tipoClasse}">${escapeHtml(b.tipo_posse || "—")}</span></td>
                <td>${escapeHtml(b.fornecedor || "—")}</td>
                <td>${escapeHtml(b.data_inicio_contrato || "—")}</td>
                <td>${escapeHtml(b.data_fim_contrato || "—")}</td>
                <td><strong>${formatarBRL(b.valor_mensal)}</strong></td>
                <td>
                    <span class="badge-contrato ${statusClasse}">
                        ${escapeHtml(b.status_contrato || "Sem data")}
                        ${b.dias_restantes !== null && b.dias_restantes !== undefined ? `(${b.dias_restantes}d)` : ""}
                    </span>
                </td>
                ${acoesHtml}
            `;
            tbody.appendChild(tr);
        });

        tbody.querySelectorAll(".btn-excluir-bem").forEach(btn => {
            btn.addEventListener("click", () => excluirBem(parseInt(btn.dataset.id), btn.dataset.nome));
        });
    } catch (err) {
        console.error("Erro ao carregar bens:", err);
        tbody.innerHTML = `<tr><td colspan="9" style="text-align:center; color:red;">
            Erro: ${escapeHtml(err.message)}
        </td></tr>`;
    }
}

function limparFiltros() {
    document.getElementById("filtro-busca").value = "";
    document.getElementById("filtro-fornecedor").value = "";
    document.getElementById("filtro-vencendo").value = "";
    carregarBens();
}

function abrirModalNovo() {
    if (!isAdmin) return;
    document.getElementById("modal-titulo").innerText = "Cadastrar Bem Alugado";
    document.getElementById("btn-salvar").innerText = "Cadastrar";
    document.getElementById("form-bem").reset();
    document.getElementById("bem-id").value = "";
    document.getElementById("bem-tipo").disabled = false;
    document.getElementById("bem-numero").disabled = false;
    abrirModal();
}

async function tentarAbrirModalNovo() {
    await protegerAcao("admin", () => abrirModalNovo());
}

function editarBem(id) {
    if (!isAdmin) return;
    const b = bensCache.find(x => x.id_patrimonio === id);
    if (!b) return;

    document.getElementById("modal-titulo").innerText = `Editar Bem #${id}`;
    document.getElementById("btn-salvar").innerText = "Salvar Alterações";
    document.getElementById("bem-id").value = id;
    document.getElementById("bem-tipo").value = b.tipo_posse || "Alugado";
    document.getElementById("bem-tipo").disabled = true;
    document.getElementById("bem-nome").value = b.nome || "";
    document.getElementById("bem-numero").value = b.numero_patrimonio || "";
    document.getElementById("bem-numero").disabled = true;
    document.getElementById("bem-valor").value = b.valor_mensal || 0;
    document.getElementById("bem-fornecedor").value = b.fornecedor || "";
    document.getElementById("bem-inicio").value = b.data_inicio_contrato_iso || "";
    document.getElementById("bem-fim").value = b.data_fim_contrato_iso || "";
    document.getElementById("bem-sala").value = b.id_sala || "";

    let desc = b.descricao || "";
    const idx = desc.indexOf("[CONTRATO_ATE:");
    if (idx !== -1) {
        const fim = desc.indexOf("]", idx);
        if (fim !== -1) desc = desc.substring(fim + 1).trim();
    }
    document.getElementById("bem-descricao").value = desc;

    abrirModal();
}

async function salvarBem(e) {
    e.preventDefault();
    if (!isAdmin) {
        toast("Apenas administradores podem salvar bens alugados.", "aviso");
        return;
    }

    const btnSalvar = document.getElementById("btn-salvar");
    const id = document.getElementById("bem-id").value;

    const formData = new FormData();
    formData.append("nome", document.getElementById("bem-nome").value.trim());
    formData.append("numero_patrimonio", document.getElementById("bem-numero").value.trim());
    formData.append("valor_mensal", document.getElementById("bem-valor").value);
    formData.append("fornecedor", document.getElementById("bem-fornecedor").value.trim());
    formData.append("data_inicio", document.getElementById("bem-inicio").value);
    formData.append("data_fim", document.getElementById("bem-fim").value);
    formData.append("id_sala", document.getElementById("bem-sala").value);
    formData.append("descricao", document.getElementById("bem-descricao").value.trim());

    if (!id) formData.append("tipo_posse", document.getElementById("bem-tipo").value);

    const url = id ? `/api/alugados/${id}` : "/api/alugados/cadastrar";
    const metodo = id ? "PUT" : "POST";

    await comSpinner(btnSalvar, async () => {
        try {
            const data = await fetchJson(url, { method: metodo, body: formData });
            toast(data.mensagem || "Salvo com sucesso!", "sucesso");
            fecharModal();
            document.getElementById("bem-numero").disabled = false;
            document.getElementById("bem-tipo").disabled = false;
            carregarResumo();
            carregarBens();
        } catch (err) {
            toast("Erro: " + err.message, "erro");
        }
    });
}

async function excluirBem(id, nome) {
    if (!isAdmin) {
        toast("Apenas administradores podem excluir bens alugados.", "aviso");
        return;
    }

    const ok = await confirmarAcao(
        `Excluir o bem <strong>"${escapeHtml(nome)}"</strong>?\n\nEsta ação NÃO pode ser desfeita.`,
        { titulo: "Excluir bem", textoConfirmar: "Excluir", perigo: true }
    );
    if (!ok) return;

    try {
        const data = await fetchJson(`/api/alugados/${id}`, { method: "DELETE" });
        toast(data.mensagem || "Removido!", "sucesso");
        carregarResumo();
        carregarBens();
    } catch (err) {
        toast("Erro: " + err.message, "erro");
    }
}