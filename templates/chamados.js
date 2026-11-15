// ============================================================================
// CHAMADOS - IPE (v9 - Correção de Múltiplos Bens e Relação 1:N)
// ============================================================================

let chamadosCache = [];
let chamadoAtualId = null;
let isAdmin = false;
let _carregando = false;
let _ultimoFetch = 0;
const CACHE_TTL_MS = 5 * 60 * 1000; // 5 minutos

const ETAPAS = [
    { status: 1, label: "Aberto", icone: "📩" },
    { status: 2, label: "Em Atendimento", icone: "🔧" },
    { status: 3, label: "Concluído", icone: "✅" },
];

document.addEventListener("DOMContentLoaded", async () => {
    await verificarPerfil();
    configurarHandlers();
    aplicarModoConsulta();
    carregarChamados();
});

async function verificarPerfil() {
    try {
        const u = await obterPerfilAtual();
        isAdmin = u && u.id_perfil === 1;
    } catch {}
}

function aplicarModoConsulta() {
    const tabela = document.getElementById("tabela-chamados-wrapper");
    if (!tabela) return;

    if (isAdmin) {
        tabela.classList.remove("modo-consulta", "sem-acoes");
        const formStatus = document.getElementById("form-status");
        if (formStatus) formStatus.style.display = "block";
    } else {
        tabela.classList.add("modo-consulta", "sem-acoes");
        
        // Oculta formulários de alteração
        const formStatus = document.getElementById("form-status");
        if (formStatus) formStatus.style.display = "none";
        
        const prioContainer = document.getElementById("prioridade-container");
        if (prioContainer) prioContainer.style.display = "none";

        // Banner de aviso
        if (!document.querySelector(".aviso-somente-leitura")) {
            const banner = document.createElement("div");
            banner.className = "aviso-somente-leitura";
            banner.innerHTML = `
                <span class="icone">👁</span>
                <span>Você está no modo <strong>consulta</strong>. Apenas a equipe de Patrimônio pode gerenciar os status dos chamados.</span>
            `;
            const section = document.querySelector(".inventory-section");
            const titulo = section ? section.querySelector(".section-title") : null;
            if (titulo) titulo.insertAdjacentElement("afterend", banner);
        }
    }
}

function configurarHandlers() {
    document.getElementById("btn-salvar-status")?.addEventListener("click", (e) => { e.preventDefault(); salvarStatus(); });
    document.getElementById("btn-enviar-foto")?.addEventListener("click", (e) => { e.preventDefault(); enviarFoto(); });
    
    document.getElementById("filtro-busca")?.addEventListener("input", aplicarFiltros);
    document.getElementById("filtro-status")?.addEventListener("change", aplicarFiltros);
    document.getElementById("filtro-prioridade")?.addEventListener("change", aplicarFiltros);

    document.getElementById("btn-iniciar-reparo")?.addEventListener("click", iniciarReparo);
    document.getElementById("btn-finalizar-reparo")?.addEventListener("click", () => abrirModalFinalizar());
    document.getElementById("btn-cancelar-chamado")?.addEventListener("click", cancelarChamado);
    document.getElementById("btn-reabrir-chamado")?.addEventListener("click", reabrirChamado);
    document.getElementById("btn-excluir-chamado")?.addEventListener("click", excluirChamado);
    document.getElementById("btn-salvar-prioridade")?.addEventListener("click", salvarPrioridade);

    document.getElementById("form-finalizar")?.addEventListener("submit", confirmarFinalizar);
}

// ============================================================================
// LISTAGEM E CACHE
// ============================================================================

async function carregarChamados(forcar = false) {
    const tbody = document.getElementById("tabela-chamados");
    if (!tbody) return;

    if (!forcar && chamadosCache.length > 0 && (Date.now() - _ultimoFetch) < CACHE_TTL_MS) {
        aplicarFiltros(); return;
    }
    if (_carregando) return;
    _carregando = true;

    tbody.innerHTML = `<tr><td colspan="8" style="text-align:center;">Carregando...</td></tr>`;

    try {
        const data = await fetchJson("/api/chamados");
        chamadosCache = Array.isArray(data) ? data : [];
        _ultimoFetch = Date.now();
        
        atualizarResumo();
        aplicarFiltros();
    } catch (err) {
        tbody.innerHTML = `<tr><td colspan="8" style="text-align:center;color:red;">Erro: ${escapeHtml(err.message)}</td></tr>`;
    } finally {
        _carregando = false;
    }
}

function atualizarResumo() {
    const a = document.getElementById("resumo-abertos");
    const b = document.getElementById("resumo-andamento");
    const c = document.getElementById("resumo-concluidos");
    const totalEl = document.getElementById("qtd-meus-chamados");
    
    if (!a || !b || !c) return;
    
    let ab = 0, an = 0, co = 0;
    for (const x of chamadosCache) {
        if (x.id_status === 1) ab++;
        else if (x.id_status === 2) an++;
        else if (x.id_status === 3) co++;
    }
    
    a.innerText = ab; 
    b.innerText = an; 
    c.innerText = co;
    
    if (totalEl) totalEl.innerText = chamadosCache.length;
}

function aplicarFiltros() {
    const termo = (document.getElementById("filtro-busca")?.value || "").toLowerCase().trim();
    const status = document.getElementById("filtro-status")?.value || "";
    const prioridade = document.getElementById("filtro-prioridade")?.value || "";

    const filtrados = chamadosCache.filter(c => {
        if (status && String(c.id_status) !== status) return false;
        if (prioridade && c.prioridade !== prioridade) return false;
        if (termo) {
            // Inclui os nomes dos bens na busca
            const nomesBens = (c.bens || []).map(b => b.nome).join(" ");
            const alvo = [c.descricao_problema, c.nome_patrimonio, c.numero_patrimonio, c.nome_usuario, c.id_chamado, nomesBens].join(" ").toLowerCase();
            if (!alvo.includes(termo)) return false;
        }
        return true;
    });
    renderizarTabela(filtrados);
}

function renderizarTabela(lista) {
    const tbody = document.getElementById("tabela-chamados");
    const contador = document.getElementById("filtro-contador");

    if (contador) {
        contador.innerText = (lista.length === chamadosCache.length)
            ? `Mostrando todos os ${lista.length} chamado(s).`
            : `Mostrando ${lista.length} de ${chamadosCache.length}.`;
    }

    const colspan = isAdmin ? 8 : 7;

    if (!lista || lista.length === 0) {
        tbody.innerHTML = `<tr><td colspan="${colspan}" style="text-align:center;">Nenhum chamado encontrado.</td></tr>`;
        return;
    }

    const frag = document.createDocumentFragment();
    for (const c of lista) {
        const statusClasse = (c.nome_status || "").toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/\s+/g, "-");
        const prioridadeClasse = (c.prioridade || "").toLowerCase();
        
        // ✅ CORREÇÃO NA TABELA: Monta o HTML dos bens mostrando todos
        const bens = c.bens || [];
        let bensHtml = "";
        
        if (bens.length > 0) {
            const principal = bens[0];
            const qtdExtras = bens.length - 1;
            
            bensHtml = `<strong>${escapeHtml(principal.nome)}</strong>`;
            if (principal.numero) {
                bensHtml += ` <small style="color:var(--text-light);">(Nº ${escapeHtml(String(principal.numero))})</small>`;
            }
            if (qtdExtras > 0) {
                bensHtml += ` <span class="badge-mais-bens" style="background:#fef3c7; color:#b45309; padding:2px 6px; border-radius:6px; font-size:0.72rem; font-weight:700; margin-left:4px;" title="${escapeHtml(bens.slice(1).map(b => b.nome).join(', '))}">+${qtdExtras}</span>`;
            }
        } else {
            bensHtml = escapeHtml(c.nome_patrimonio || "—") + (c.numero_patrimonio ? ` (Nº ${escapeHtml(String(c.numero_patrimonio))})` : '');
        }

        const acoesHtml = isAdmin
            ? `<button class="btn-acao primario" data-acao-id="${c.id_chamado}">
                   <span class="icone">⚙️</span> Gerenciar
               </button>`
            : `<button class="btn-acao secundario" data-acao-id="${c.id_chamado}">
                   <span class="icone">👁</span> Detalhes
               </button>`;

        const tdAcoes = `<td class="col-acoes">${acoesHtml}</td>`;

        const tr = document.createElement("tr");
        tr.innerHTML = `
            <td>#${c.id_chamado}</td>
            <td>${escapeHtml(c.data_abertura)}</td>
            <td>${escapeHtml(c.nome_usuario)}</td>
            <td>${bensHtml}</td>
            <td style="max-width:280px;" title="${escapeHtml(c.descricao_problema)}">${escapeHtml((c.descricao_problema || '').substring(0, 60))}${(c.descricao_problema || '').length > 60 ? '...' : ''}</td>
            <td><span class="status ${prioridadeClasse}">${escapeHtml(c.prioridade)}</span></td>
            <td><span class="status ${statusClasse === 'em-atendimento' ? 'manutencao' : 'ativo'}">${escapeHtml(c.nome_status)}</span></td>
            ${tdAcoes}
        `;
        frag.appendChild(tr);
    }
    tbody.innerHTML = "";
    tbody.appendChild(frag);

    tbody.querySelectorAll("button[data-acao-id]").forEach(btn => {
        btn.addEventListener("click", () => abrirModalAcao(parseInt(btn.dataset.acaoId)));
    });
}

function limparFiltros() {
    ["filtro-busca", "filtro-status", "filtro-prioridade"].forEach(id => {
        const el = document.getElementById(id); if (el) el.value = "";
    });
    aplicarFiltros();
}

// ============================================================================
// DETALHES DO CHAMADO E STEPPER
// ============================================================================

function renderizarStepper(detalhes) {
    const div = document.getElementById("stepper-status");
    if (!div) return;

    const statusAtual = detalhes.id_status;
    const cancelado = statusAtual === 4;

    const datasPorStatus = {};
    (detalhes.historico || []).forEach(h => {
        const m = (h.descricao || "").match(/Status.*?"(.*?)"/i);
        if (m) {
            const nome = m[1];
            if (!datasPorStatus[nome]) datasPorStatus[nome] = h.data_evento;
        }
    });

    let html = "";
    ETAPAS.forEach(etapa => {
        let classe = "";
        if (cancelado) classe = "cancelado";
        else if (etapa.status < statusAtual) classe = "feito";
        else if (etapa.status === statusAtual) classe = "atual";

        const dataMostrar = datasPorStatus[etapa.label] || "";
        const icone = etapa.status < statusAtual ? "✓" : etapa.icone;

        html += `
            <div class="stepper-etapa ${classe}">
                <div class="stepper-bolinha">${icone}</div>
                <div class="stepper-label">${etapa.label}</div>
            </div>
        `;
    });

    if (cancelado) {
        html = `<div style="text-align:center;padding:15px;background:#fee2e2;border-radius:10px;color:#991b1b;font-weight:600; width:100%;">
            ❌ Chamado Cancelado
        </div>`;
    }

    div.innerHTML = html;
}

// ✅ CORREÇÃO CRUCIAL: Renderiza todos os bens vinculados
function renderizarBens(bens) {
    const div = document.getElementById("lista-bens");
    if (!div) return;
    
    if (!bens || bens.length === 0) {
        div.innerHTML = "<em>Nenhum bem vinculado.</em>";
        return;
    }
    
    div.innerHTML = bens.map(b => `
        <div style="padding:10px 0; border-bottom:1px solid #eee; display:flex; align-items:center; gap:10px;">
            <span style="font-size:1.4rem; color:var(--primary-dark);">📦</span>
            <div style="flex:1;">
                <strong style="color:var(--dark); font-size:0.95rem;">${escapeHtml(b.nome || "—")}</strong>
                ${b.numero ? `<small style="color:var(--text-light); display:block; margin-top:2px;">Nº do Patrimônio: <strong>${escapeHtml(String(b.numero))}</strong></small>` : ""}
            </div>
        </div>
    `).join("");
}

function renderizarAnexos(anexos) {
    const div = document.getElementById("lista-anexos");
    if (!div) return;
    if (!anexos || anexos.length === 0) {
        div.innerHTML = "<em>Nenhum anexo.</em>"; return;
    }
    div.innerHTML = anexos.map(a => {
        const nome = (a.caminho || "").split('/').pop();
        return `<div class="anexo-item" style="padding:6px 0; border-bottom:1px solid #eef0f2;">
            <a href="/${a.caminho}" target="_blank" style="color:var(--primary-dark); font-weight:600; text-decoration:none;">📎 ${escapeHtml(nome)}</a>
            <small style="color:var(--text-light);"> (${escapeHtml(a.data_upload)})</small>
        </div>`;
    }).join("");
}

function renderizarHistorico(historico) {
    const div = document.getElementById("lista-historico");
    if (!div) return;
    if (!historico || historico.length === 0) {
        div.innerHTML = "<em>Nenhum evento.</em>"; return;
    }
    const reversed = [...historico].reverse();
    div.innerHTML = reversed.map(h => `
        <div class="historico-item">
            <strong>${escapeHtml(h.data_evento)}</strong> — ${escapeHtml(h.descricao)}
        </div>
    `).join("");
}

function atualizarBotoesAcao(detalhes) {
    const st = detalhes.id_status;
    const btnIniciar   = document.getElementById("btn-iniciar-reparo");
    const btnFinalizar = document.getElementById("btn-finalizar-reparo");
    const btnCancelar  = document.getElementById("btn-cancelar-chamado");
    const btnReabrir   = document.getElementById("btn-reabrir-chamado");
    const btnExcluir   = document.getElementById("btn-excluir-chamado");

    if (!isAdmin) {
        [btnIniciar, btnFinalizar, btnCancelar, btnReabrir, btnExcluir].forEach(b => b && (b.style.display = "none"));
        return;
    }

    btnIniciar.style.display   = (st === 1) ? "inline-flex" : "none";
    btnFinalizar.style.display = (st === 2) ? "inline-flex" : "none";
    btnCancelar.style.display  = (st === 1 || st === 2) ? "inline-flex" : "none";
    btnReabrir.style.display   = (st === 3 || st === 4) ? "inline-flex" : "none";
    btnExcluir.style.display   = (st !== 2) ? "inline-flex" : "none";
}

function atualizarPainelManutencao(manut) {
    const painel = document.getElementById("painel-manutencao");
    const info = document.getElementById("manutencao-info");
    if (!painel || !info) return;

    if (!manut) { painel.style.display = "none"; return; }

    painel.style.display = "block";
    const partes = [];
    if (manut.data_inicio_manutencao) partes.push(`<strong>Início:</strong> ${escapeHtml(manut.data_inicio_manutencao)}`);
    if (manut.data_fim_manutencao)    partes.push(`<strong>Fim:</strong> ${escapeHtml(manut.data_fim_manutencao)}`);
    if (manut.duracao_dias != null)   partes.push(`<strong>Duração:</strong> ${manut.duracao_dias} dia(s)`);
    if (manut.observacao_manutencao)  partes.push(`<br><strong>Serviço:</strong> ${escapeHtml(manut.observacao_manutencao)}`);
    info.innerHTML = partes.join(" · ") || "—";
}

async function abrirModalAcao(id) {
    chamadoAtualId = id;
    document.getElementById("modal-id-chamado").innerText = `#${id}`;
    document.getElementById("modal-acao").classList.add("show");

    document.getElementById("stepper-status").innerHTML = "<em>Carregando...</em>";
    document.getElementById("lista-bens").innerHTML = "<em>Carregando...</em>";
    document.getElementById("lista-anexos").innerHTML = "<em>Carregando...</em>";
    document.getElementById("lista-historico").innerHTML = "<em>Carregando...</em>";
    document.getElementById("modal-descricao").innerText = "—";
    document.getElementById("painel-manutencao").style.display = "none";

    try {
        const detalhes = await fetchJson(`/api/chamado/${id}/detalhes`);
        
        renderizarStepper(detalhes);
        
        // ✅ Chama a função corrigida que lista todos os bens
        renderizarBens(detalhes.bens);
        
        renderizarAnexos(detalhes.anexos);
        renderizarHistorico(detalhes.historico);
        atualizarBotoesAcao(detalhes);
        atualizarPainelManutencao(detalhes.manutencao || null);

        document.getElementById("modal-descricao").innerText = detalhes.descricao_problema || "—";

        const prevBox = document.getElementById("modal-previsao");
        const prevTxt = document.getElementById("previsao-texto");
        if (detalhes.data_previsao_fmt) {
            prevBox.style.display = "block";
            prevTxt.innerText = detalhes.data_previsao_fmt;
        } else {
            prevBox.style.display = "none";
        }

        const sel = document.getElementById("select-status");
        if (sel) sel.value = String(detalhes.id_status || 1);

        const selPrio = document.getElementById("select-prioridade");
        if (selPrio) selPrio.value = detalhes.prioridade || "Media";

    } catch (err) {
        document.getElementById("stepper-status").innerHTML =
            `<div style="color:red; width:100%; text-align:center;">Erro: ${escapeHtml(err.message)}</div>`;
    }
}

// ============================================================================
// AÇÕES (Apenas ADMIN)
// ============================================================================

async function salvarStatus() {
    if (!chamadoAtualId || !isAdmin) return;
    const sel = document.getElementById("select-status");
    if (!sel) return;

    const formData = new FormData();
    formData.append("id_chamado", chamadoAtualId);
    formData.append("id_status", sel.value);

    const overlay = toastCarregando("Atualizando status...");
    try {
        const data = await fetchJson("/api/chamado/atualizar-status", { method: "POST", body: formData });
        overlay.remove();
        toast(data.mensagem || "Status atualizado!", "sucesso");
        carregarChamados(true);
        abrirModalAcao(chamadoAtualId);
    } catch (err) {
        overlay.remove();
        toast("Erro: " + err.message, "erro");
    }
}

async function iniciarReparo() {
    if (!chamadoAtualId || !isAdmin) return;
    const ok = await confirmarAcao("Marcar este chamado como <strong>Em Atendimento</strong> e iniciar a manutenção?", {
        titulo: "Iniciar reparo", textoConfirmar: "Iniciar"
    });
    if (!ok) return;
    
    const formData = new FormData();
    formData.append("id_chamado", chamadoAtualId);
    try {
        const data = await fetchJson("/api/manutencao/iniciar", { method: "POST", body: formData });
        toast(data.mensagem || "Reparo iniciado!", "sucesso");
        carregarChamados(true);
        abrirModalAcao(chamadoAtualId);
    } catch (err) {
        toast("Erro: " + err.message, "erro");
    }
}

function abrirModalFinalizar() {
    if (!isAdmin) return;
    document.getElementById("form-finalizar").reset();
    document.getElementById("modal-finalizar").classList.add("show");
}

async function confirmarFinalizar(e) {
    e.preventDefault();
    if (!chamadoAtualId || !isAdmin) return;

    const obs = document.getElementById("finalizar-obs").value.trim();
    const custo = document.getElementById("finalizar-custo").value;

    if (obs.length < 10) { toast("Observação precisa ter ≥10 caracteres.", "aviso"); return; }

    const formData = new FormData();
    formData.append("id_chamado", chamadoAtualId);
    formData.append("custo_final", custo || "0");
    formData.append("descricao_servico", obs);

    try {
        const data = await fetchJson("/api/manutencao/finalizar", { method: "POST", body: formData });
        toast(data.mensagem || "Reparo concluído!", "sucesso");
        document.getElementById("modal-finalizar").classList.remove("show");
        carregarChamados(true);
        abrirModalAcao(chamadoAtualId);
    } catch (err) {
        toast("Erro: " + err.message, "erro");
    }
}

async function cancelarChamado() {
    if (!chamadoAtualId || !isAdmin) return;

    const motivo = await modalInput({
        titulo: "Cancelar chamado",
        label: "Motivo do cancelamento *",
        placeholder: "Descreva brevemente o motivo (mín. 5 caracteres)",
        textoConfirmar: "Cancelar chamado",
        textoCancelar: "Voltar",
        minLength: 5,
    });

    if (!motivo) return;

    const formData = new FormData();
    formData.append("motivo", motivo);

    const overlay = toastCarregando("Cancelando...");
    try {
        const data = await fetchJson(`/api/chamado/${chamadoAtualId}/cancelar`, { method: "POST", body: formData });
        overlay.remove();
        toast(data.mensagem || "Chamado cancelado.", "sucesso");
        carregarChamados(true);
        abrirModalAcao(chamadoAtualId);
    } catch (err) {
        overlay.remove();
        toast("Erro: " + err.message, "erro");
    }
}

async function reabrirChamado() {
    if (!chamadoAtualId || !isAdmin) return;
    const ok = await confirmarAcao("Reabrir este chamado? Ele voltará para o status <strong>Aberto</strong>.", {
        titulo: "Reabrir", textoConfirmar: "Reabrir"
    });
    if (!ok) return;
    try {
        const data = await fetchJson(`/api/chamado/${chamadoAtualId}/reabrir`, { method: "POST" });
        toast(data.mensagem || "Chamado reaberto.", "sucesso");
        carregarChamados(true);
        abrirModalAcao(chamadoAtualId);
    } catch (err) {
        toast("Erro: " + err.message, "erro");
    }
}

async function excluirChamado() {
    if (!chamadoAtualId || !isAdmin) return;
    const ok = await confirmarAcao(
        `Excluir o chamado <strong>#${chamadoAtualId}</strong>?<br><br>Esta ação apaga anexos, histórico e manutenções vinculadas.`,
        { titulo: "Excluir", textoConfirmar: "Sim, excluir", perigo: true }
    );
    if (!ok) return;

    const overlay = toastCarregando("Excluindo chamado...");
    try {
        const data = await fetchJson(`/api/chamado/${chamadoAtualId}`, { method: "DELETE" });
        overlay.remove();
        toast(data.mensagem || "Chamado excluído.", "sucesso");
        document.getElementById("modal-acao").classList.remove("show");
        chamadoAtualId = null;
        carregarChamados(true);
    } catch (err) {
        overlay.remove();
        toast("Erro: " + err.message, "erro");
    }
}

async function salvarPrioridade() {
    if (!chamadoAtualId || !isAdmin) return;
    const sel = document.getElementById("select-prioridade");
    if (!sel) return;
    const formData = new FormData();
    formData.append("prioridade", sel.value);
    try {
        const data = await fetchJson(`/api/chamado/${chamadoAtualId}/prioridade`, { method: "POST", body: formData });
        toast(data.mensagem || "Prioridade atualizada!", "sucesso");
        carregarChamados(true);
        abrirModalAcao(chamadoAtualId);
    } catch (err) {
        toast("Erro: " + err.message, "erro");
    }
}

async function enviarFoto() {
    if (!chamadoAtualId) return;
    const input = document.getElementById("input-foto");
    if (!input || !input.files[0]) { toast("Selecione uma imagem.", "aviso"); return; }

    const formData = new FormData();
    formData.append("id_chamado", chamadoAtualId);
    formData.append("foto", input.files[0]);

    const overlay = toastCarregando("Enviando anexo...");
    try {
        await fetchJson("/api/chamado/anexar-foto", { method: "POST", body: formData });
        overlay.remove();
        toast("Anexo enviado!", "sucesso");
        input.value = "";
        abrirModalAcao(chamadoAtualId);
    } catch (err) {
        overlay.remove();
        toast("Erro: " + err.message, "erro");
    }
}