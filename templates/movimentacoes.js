// ============================================================================
// MÓDULO DE HISTÓRICO DE MOVIMENTAÇÃO - IPE (v2 - modo consulta)
// ============================================================================

let salasCache = [];
let patrimoniosCache = [];
let selecionados = new Set();
let isAdmin = false;

document.addEventListener("DOMContentLoaded", async () => {
    await verificarPerfil();
    await carregarSalas();
    await carregarPatrimonios();
    carregarResumo();
    carregarMovimentacoes();

    const params = new URLSearchParams(window.location.search);
    const idPre = params.get("patrimonio");
    if (idPre && isAdmin) {
        selecionados.add(parseInt(idPre));
        abrirModalNova();
        setTimeout(() => {
            const cb = document.querySelector(`#lista-patrimonios input[value="${idPre}"]`);
            if (cb) cb.checked = true;
            atualizarPreview();
        }, 100);
    }

    document.getElementById("form-mov").addEventListener("submit", registrarMovimentacao);
});

async function verificarPerfil() {
    try {
        const res = await fetch("/api/dados_usuario");
        if (!res.ok) return;
        const u = await res.json();
        isAdmin = u.id_perfil === 1;

        const btnNova = document.getElementById("btn-nova-mov");
        if (isAdmin && btnNova) {
            btnNova.style.display = "inline-block";
        } else if (btnNova) {
            btnNova.remove();
        }

        if (!isAdmin) {
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

function abrirModal() { document.getElementById("modal-nova").classList.add("show"); }

function fecharModal() {
    document.getElementById("modal-nova").classList.remove("show");
    document.getElementById("form-mov").reset();
    selecionados.clear();
    document.getElementById("mov-busca-patr").value = "";
    renderizarListaPatrimonios(patrimoniosCache);
    atualizarPreview();
}

function fecharDetalhes() { document.getElementById("modal-detalhes").classList.remove("show"); }

async function carregarSalas() {
    try {
        const res = await fetch("/api/salas");
        salasCache = await res.json() || [];

        const optsModal = salasCache.map(s =>
            `<option value="${s.id_sala}">${escapeHtml(s.nome)}${s.bloco ? ' - ' + escapeHtml(s.bloco) : ''}</option>`
        ).join("");

        const optsFiltro = salasCache.map(s =>
            `<option value="${s.id_sala}">${escapeHtml(s.nome)}</option>`
        ).join("");

        document.getElementById("filtro-origem").innerHTML = '<option value="">Todas</option>' + optsFiltro;
        document.getElementById("filtro-destino").innerHTML = '<option value="">Todas</option>' + optsFiltro;

        document.getElementById("mov-origem").innerHTML =
            '<option value="">— Nenhuma (item sem alocação) —</option>' + optsModal;
        document.getElementById("mov-destino").innerHTML =
            '<option value="">— Selecionar —</option>' + optsModal;
    } catch (err) {
        console.error("Erro ao carregar salas:", err);
    }
}

async function carregarPatrimonios() {
    try {
        const res = await fetch("/api/inventario/listar");
        patrimoniosCache = await res.json() || [];
        renderizarListaPatrimonios(patrimoniosCache);
    } catch (err) {
        console.error("Erro ao carregar patrimônios:", err);
    }
}

function renderizarListaPatrimonios(lista) {
    const div = document.getElementById("lista-patrimonios");
    if (!lista || lista.length === 0) {
        div.innerHTML = '<em>Nenhum patrimônio cadastrado.</em>';
        return;
    }

    div.innerHTML = "";
    lista.forEach(p => {
        const label = document.createElement("label");
        label.className = "multi-item";
        label.innerHTML = `
            <input type="checkbox" value="${p.id_patrimonio}"
                   ${selecionados.has(p.id_patrimonio) ? "checked" : ""}
                   onchange="toggleSelecionado(${p.id_patrimonio}, this.checked)">
            <span>
                <strong>${escapeHtml(p.nome)}</strong>
                <small style="color: var(--text-light); display:block; font-size: 0.75rem;">
                    Nº ${escapeHtml(p.numero_patrimonio)} · ${escapeHtml(p.nome_sala)}${p.bloco_sala ? ' (' + escapeHtml(p.bloco_sala) + ')' : ''}
                </small>
            </span>
        `;
        div.appendChild(label);
    });
}

function filtrarPatrimonios() {
    const termo = document.getElementById("mov-busca-patr").value.toLowerCase().trim();
    if (!termo) {
        renderizarListaPatrimonios(patrimoniosCache);
        return;
    }
    const filtrados = patrimoniosCache.filter(p =>
        (p.nome || "").toLowerCase().includes(termo) ||
        String(p.numero_patrimonio || "").includes(termo)
    );
    renderizarListaPatrimonios(filtrados);
}

function toggleSelecionado(id, marcado) {
    if (marcado) selecionados.add(id);
    else selecionados.delete(id);
    atualizarPreview();
}

function atualizarPreview() {
    const div = document.getElementById("preview-itens");
    const texto = document.getElementById("preview-texto");
    if (selecionados.size === 0) {
        div.style.display = "none";
        return;
    }
    div.style.display = "block";
    const nomes = Array.from(selecionados).map(id => {
        const p = patrimoniosCache.find(x => x.id_patrimonio === id);
        return p ? p.nome : `#${id}`;
    });
    texto.innerText = `${selecionados.size} item(ns) — ${nomes.slice(0, 3).join(", ")}${nomes.length > 3 ? "..." : ""}`;
}

async function carregarResumo() {
    try {
        const res = await fetch("/api/movimentacoes/resumo");
        if (!res.ok) throw new Error();
        const r = await res.json();

        document.getElementById("stat-total-mov").innerText = r.total_movimentacoes;
        document.getElementById("stat-total-itens").innerText = r.total_itens_movimentados;
        document.getElementById("stat-salas").innerText = r.salas_envolvidas;
        document.getElementById("stat-ultima").innerText = r.ultima_movimentacao || "—";
    } catch (err) {
        console.error("Erro resumo:", err);
    }
}

async function carregarMovimentacoes() {
    const tbody = document.getElementById("tabela-movimentacoes");
    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;">Carregando...</td></tr>';

    const params = new URLSearchParams();
    const busca = document.getElementById("filtro-busca").value.trim();
    const origem = document.getElementById("filtro-origem").value;
    const destino = document.getElementById("filtro-destino").value;
    const dataIni = document.getElementById("filtro-data-ini").value;
    const dataFim = document.getElementById("filtro-data-fim").value;

    if (busca) params.append("busca", busca);
    if (origem) params.append("sala_origem", origem);
    if (destino) params.append("sala_destino", destino);
    if (dataIni) params.append("data_ini", dataIni);
    if (dataFim) params.append("data_fim", dataFim);

    try {
        const res = await fetch("/api/movimentacoes?" + params.toString());
        if (!res.ok) throw new Error("HTTP " + res.status);
        const movs = await res.json();

        document.getElementById("contador-movs").innerText =
            `${movs.length} movimentação(ões) encontrada(s).`;

        if (movs.length === 0) {
            const colspan = isAdmin ? 6 : 5;
            tbody.innerHTML = `<tr><td colspan="${colspan}" class="empty-state">Nenhuma movimentação encontrada.</td></tr>`;
            return;
        }

        tbody.innerHTML = "";
        movs.forEach(m => {
            const acoesHtml = isAdmin ? `
                <td class="col-acoes">
                    <button class="btn-mini ver" onclick="verDetalhes(${m.id_movimentacao})">👁 Detalhes</button>
                    <button class="btn-mini del" onclick="excluirMovimentacao(${m.id_movimentacao})">🗑</button>
                </td>
            ` : `
                <td class="col-acoes">
                    <button class="btn-mini ver" onclick="verDetalhes(${m.id_movimentacao})">👁 Detalhes</button>
                </td>
            `;

            const tr = document.createElement("tr");
            tr.innerHTML = `
                <td>#${m.id_movimentacao}</td>
                <td>${escapeHtml(m.data_formatada)}</td>
                <td>
                    <span class="badge-rota">
                        <span class="origem">${escapeHtml(m.sala_origem)}${m.bloco_origem ? ' · ' + escapeHtml(m.bloco_origem) : ''}</span>
                    </span>
                </td>
                <td>
                    <span class="badge-rota">
                        <span class="seta">→</span>
                        <span class="destino">${escapeHtml(m.sala_destino)}${m.bloco_destino ? ' · ' + escapeHtml(m.bloco_destino) : ''}</span>
                    </span>
                </td>
                <td><strong>${m.total_itens}</strong> item(ns)</td>
                ${acoesHtml}
            `;
            tbody.appendChild(tr);
        });
    } catch (err) {
        console.error("Erro ao carregar movimentações:", err);
        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center; color:red;">Erro ao carregar.</td></tr>';
    }
}

function limparFiltros() {
    document.getElementById("filtro-busca").value = "";
    document.getElementById("filtro-origem").value = "";
    document.getElementById("filtro-destino").value = "";
    document.getElementById("filtro-data-ini").value = "";
    document.getElementById("filtro-data-fim").value = "";
    carregarMovimentacoes();
}

function abrirModalNova() {
    if (!isAdmin) return;

    document.getElementById("form-mov").reset();
    document.getElementById("mov-busca-patr").value = "";
    renderizarListaPatrimonios(patrimoniosCache);
    atualizarPreview();
    abrirModal();
}

async function tentarAbrirModalNova() {
    await protegerAcao("admin", () => abrirModalNova());
}

async function registrarMovimentacao(e) {
    e.preventDefault();

    if (!isAdmin) {
        toast("Apenas administradores podem registrar movimentações.", "aviso");
        return;
    }

    const origem = document.getElementById("mov-origem").value;
    const destino = document.getElementById("mov-destino").value;
    const obs = document.getElementById("mov-obs").value.trim();

    if (!destino) { toast("Selecione a sala de destino.", "aviso"); return; }
    if (origem && origem === destino) { toast("Origem e destino não podem ser iguais.", "aviso"); return; }
    if (selecionados.size === 0) { toast("Selecione pelo menos um patrimônio.", "aviso"); return; }

    const formData = new FormData();
    if (origem) formData.append("id_sala_origem", origem);
    formData.append("id_sala_destino", destino);
    formData.append("observacao", obs);
    formData.append("itens", JSON.stringify(Array.from(selecionados)));

    try {
        const res = await fetch("/api/movimentacoes", { method: "POST", body: formData });
        const data = await res.json();

        if (res.ok) {
            toast(data.mensagem, "sucesso");
            fecharModal();
            carregarMovimentacoes();
            carregarResumo();
            carregarPatrimonios();
        } else {
            toast(data.erro || "Erro ao registrar.", "erro");
        }
    } catch (err) {
        toast("Erro de conexão: " + err.message, "erro");
    }
}

async function verDetalhes(id) {
    document.getElementById("detalhes-titulo").innerText = `Movimentação #${id}`;
    document.getElementById("detalhes-conteudo").innerHTML = "<em>Carregando...</em>";
    document.getElementById("modal-detalhes").classList.add("show");

    try {
        const res = await fetch(`/api/movimentacoes/${id}`);
        const m = await res.json();

        if (!res.ok) {
            document.getElementById("detalhes-conteudo").innerHTML =
                `<p style="color:red;">${escapeHtml(m.erro || "Erro ao carregar.")}</p>`;
            return;
        }

        let itensHtml = "";
        if (m.itens && m.itens.length > 0) {
            itensHtml = m.itens.map(i => `
                <div style="padding: 8px 12px; border-bottom: 1px solid var(--border);">
                    <strong>${escapeHtml(i.nome)}</strong>
                    <small style="color: var(--text-light); display:block;">
                        Nº ${escapeHtml(i.numero_patrimonio)}
                    </small>
                </div>
            `).join("");
        } else {
            itensHtml = "<em>Nenhum item vinculado.</em>";
        }

        document.getElementById("detalhes-conteudo").innerHTML = `
            <div style="background:#fafafa; padding:15px; border-radius:10px; margin-bottom:15px;">
                <p><strong>Data:</strong> ${escapeHtml(m.data_formatada)}</p>
                <p><strong>Origem:</strong> ${escapeHtml(m.sala_origem)}${m.bloco_origem ? ' · ' + escapeHtml(m.bloco_origem) : ''}</p>
                <p><strong>Destino:</strong> ${escapeHtml(m.sala_destino)}${m.bloco_destino ? ' · ' + escapeHtml(m.bloco_destino) : ''}</p>
            </div>
            <h4 style="margin-bottom: 10px;">Itens Movimentados (${m.itens.length})</h4>
            <div style="max-height: 250px; overflow-y: auto; border:1px solid var(--border); border-radius: 10px;">
                ${itensHtml}
            </div>
        `;
    } catch (err) {
        document.getElementById("detalhes-conteudo").innerHTML =
            `<p style="color:red;">Erro: ${escapeHtml(err.message)}</p>`;
    }
}

async function excluirMovimentacao(id) {
    if (!isAdmin) {
        toast("Apenas administradores podem excluir movimentações.", "aviso");
        return;
    }

    const ok = await confirmarAcao(
        `Excluir a movimentação <strong>#${id}</strong>?\n\nIsso NÃO irá reverter as salas dos patrimônios, apenas apaga o registro histórico.`,
        { titulo: "Excluir movimentação", textoConfirmar: "Excluir", perigo: true }
    );
    if (!ok) return;

    try {
        const res = await fetch(`/api/movimentacoes/${id}`, { method: "DELETE" });
        const data = await res.json();
        toast(data.mensagem || data.erro, data.mensagem ? "sucesso" : "erro");
        if (res.ok) {
            carregarMovimentacoes();
            carregarResumo();
        }
    } catch (err) {
        toast("Erro: " + err.message, "erro");
    }
}