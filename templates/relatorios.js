// ============================================================================
// MÓDULO DE RELATÓRIOS - IPE
// ============================================================================

let anoAtual = new Date().getFullYear();
let periodoAtual = "bimestral";
let dadosRelatorio = null;

document.addEventListener("DOMContentLoaded", () => {
    inicializarAnos();
    carregarRelatorio();
});

// ============================================================================
// HELPERS
// ============================================================================

function formatarBRL(v) {
    return "R$ " + parseFloat(v || 0).toFixed(2)
        .replace(".", ",")
        .replace(/\B(?=(\d{3})+(?!\d))/g, ".");
}

function inicializarAnos() {
    const sel = document.getElementById("ano-selector");
    const anoAtualReal = new Date().getFullYear();

    sel.innerHTML = "";
    // Últimos 5 anos + o próximo
    for (let a = anoAtualReal + 1; a >= anoAtualReal - 5; a--) {
        const opt = document.createElement("option");
        opt.value = a;
        opt.textContent = a;
        if (a === anoAtualReal) opt.selected = true;
        sel.appendChild(opt);
    }

    anoAtual = parseInt(sel.value);
}

function setPeriodo(p, btn) {
    periodoAtual = p;
    document.querySelectorAll(".periodo-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    carregarRelatorio();
}

// ============================================================================
// CARREGAR RELATÓRIO
// ============================================================================

async function carregarRelatorio() {
    anoAtual = parseInt(document.getElementById("ano-selector").value);

    const loading = document.getElementById("loading");
    const conteudo = document.getElementById("relatorio-conteudo");

    loading.classList.add("show");
    conteudo.style.display = "none";

    try {
        const res = await fetch(`/api/relatorios/resumo?ano=${anoAtual}&periodo=${periodoAtual}`);
        if (!res.ok) throw new Error("HTTP " + res.status);

        dadosRelatorio = await res.json();
        renderizarRelatorio(dadosRelatorio);

    } catch (err) {
        console.error("Erro relatório:", err);
        conteudo.innerHTML = `
            <div class="empty-state-rel">
                <span class="icone">⚠️</span>
                <p>Erro ao carregar o relatório: ${escapeHtml(err.message)}</p>
            </div>
        `;
    } finally {
        loading.classList.remove("show");
        conteudo.style.display = "block";
    }
}

// ============================================================================
// RENDERIZAR RELATÓRIO
// ============================================================================

function renderizarRelatorio(data) {
    const conteudo = document.getElementById("relatorio-conteudo");
    const r = data.resumo_geral;

    if (r.total_movimentacoes === 0) {
        conteudo.innerHTML = `
            <div class="empty-state-rel">
                <span class="icone">📭</span>
                <h3>Nenhuma movimentação em ${anoAtual}</h3>
                <p>Não há dados financeiros registrados neste ano.</p>
            </div>
        `;
        return;
    }

    let html = "";

    // ---- 1. CARDS DE RESUMO ----
    html += `
        <div class="rel-resumo-grid">
            <div class="rel-card entrada">
                <h4>💰 Total de Entradas</h4>
                <div class="valor-grande">${formatarBRL(r.total_entradas)}</div>
                <div class="sub-info">Receitas do período</div>
            </div>
            <div class="rel-card saida">
                <h4>📉 Total de Saídas</h4>
                <div class="valor-grande">${formatarBRL(r.total_saidas)}</div>
                <div class="sub-info">Despesas do período</div>
            </div>
            <div class="rel-card saldo">
                <h4>📊 Saldo do Período</h4>
                <div class="valor-grande" style="color: ${r.saldo >= 0 ? '#15803d' : '#991b1b'};">
                    ${formatarBRL(r.saldo)}
                </div>
                <div class="sub-info">${r.saldo >= 0 ? '✅ Superávit' : '⚠️ Déficit'}</div>
            </div>
            <div class="rel-card total">
                <h4>🔢 Movimentações</h4>
                <div class="valor-grande">${r.total_movimentacoes}</div>
                <div class="sub-info">No ano ${anoAtual}</div>
            </div>
        </div>
    `;

    // ---- 2. GRÁFICO DE BARRAS ----
    html += renderizarGrafico(data.por_periodo);

    // ---- 3. DETALHAMENTO POR PERÍODO ----
    html += renderizarDetalhamento(data.detalhamento, data.periodo);

    // ---- 4. POR ORIGEM DA VERBA ----
    if (data.por_origem && data.por_origem.length > 0) {
        html += renderizarPorOrigem(data.por_origem);
    }

    // ---- 5. POR CATEGORIA ----
    if (data.por_categoria && data.por_categoria.length > 0) {
        html += renderizarPorCategoria(data.por_categoria);
    }

    conteudo.innerHTML = html;
}

function renderizarGrafico(porPeriodo) {
    if (!porPeriodo || porPeriodo.length === 0) {
        return "";
    }

    // Calcula escala
    let max = 0;
    porPeriodo.forEach(p => {
        max = Math.max(max, p.entradas, p.saidas);
    });
    if (max === 0) max = 1;

    let barras = "";
    porPeriodo.forEach(p => {
        const altEntrada = (p.entradas / max) * 100;
        const altSaida = (p.saidas / max) * 100;

        barras += `
            <div class="barra-periodo-grupo">
                <div class="barra-periodo-par">
                    <div class="barra-periodo entrada" style="height: ${altEntrada}%;"
                         title="Entradas: ${formatarBRL(p.entradas)}"></div>
                    <div class="barra-periodo saida" style="height: ${altSaida}%;"
                         title="Saídas: ${formatarBRL(p.saidas)}"></div>
                </div>
                <div class="barra-periodo-label">${p.mes_nome}</div>
            </div>
        `;
    });

    return `
        <div class="rel-grafico">
            <div class="rel-grafico-titulo">
                📈 Entradas x Saídas por Mês (${anoAtual})
            </div>
            <div class="barras-periodo">
                ${barras}
            </div>
            <div class="rel-legenda">
                <span><div class="cor" style="background: #15803d;"></div> Entradas</span>
                <span><div class="cor" style="background: #991b1b;"></div> Saídas</span>
            </div>
        </div>
    `;
}

function renderizarDetalhamento(detalhamento, periodo) {
    if (!detalhamento || detalhamento.length === 0) {
        return "";
    }

    const tituloPeriodo = {
        "mensal": "Detalhamento Mensal",
        "bimestral": "Detalhamento Bimestral",
        "trimestral": "Detalhamento Trimestral",
        "semestral": "Detalhamento Semestral",
        "anual": "Resumo Anual"
    }[periodo] || "Detalhamento";

    let totalEnt = 0, totalSai = 0, totalMov = 0;

    let linhas = detalhamento.map(d => {
        totalEnt += d.entradas;
        totalSai += d.saidas;
        totalMov += d.movimentacoes;

        const saldoClass = d.saldo >= 0 ? "positivo" : "negativo";

        return `
            <tr>
                <td><strong>${escapeHtml(d.label)}</strong></td>
                <td class="valor-positivo">${formatarBRL(d.entradas)}</td>
                <td class="valor-negativo">${formatarBRL(d.saidas)}</td>
                <td class="valor-saldo ${saldoClass}">${formatarBRL(d.saldo)}</td>
                <td>${d.movimentacoes}</td>
            </tr>
        `;
    }).join("");

    const saldoFinal = totalEnt - totalSai;
    const saldoClassTotal = saldoFinal >= 0 ? "positivo" : "negativo";

    return `
        <div class="rel-tabela-wrapper">
            <div class="rel-tabela-titulo">
                📊 ${tituloPeriodo} — ${anoAtual}
            </div>
            <table class="rel-tabela">
                <thead>
                    <tr>
                        <th>Período</th>
                        <th>Entradas</th>
                        <th>Saídas</th>
                        <th>Saldo</th>
                        <th>Movimentações</th>
                    </tr>
                </thead>
                <tbody>
                    ${linhas}
                </tbody>
                <tfoot>
                    <tr>
                        <td>TOTAL DO ANO</td>
                        <td class="valor-positivo">${formatarBRL(totalEnt)}</td>
                        <td class="valor-negativo">${formatarBRL(totalSai)}</td>
                        <td class="valor-saldo ${saldoClassTotal}">${formatarBRL(saldoFinal)}</td>
                        <td>${totalMov}</td>
                    </tr>
                </tfoot>
            </table>
        </div>
    `;
}

function renderizarPorOrigem(porOrigem) {
    // Calcula total para percentuais
    const total = porOrigem.reduce((acc, o) => acc + o.entradas + o.saidas, 0);

    let linhas = porOrigem.map(o => {
        const subtotal = o.entradas + o.saidas;
        const perc = total > 0 ? ((subtotal / total) * 100).toFixed(1) : 0;

        return `
            <tr>
                <td>
                    <span class="badge-origem-rel" style="background: ${o.cor};">
                        ${escapeHtml(o.icone)} ${escapeHtml(o.nome)}
                    </span>
                </td>
                <td class="valor-positivo">${formatarBRL(o.entradas)}</td>
                <td class="valor-negativo">${formatarBRL(o.saidas)}</td>
                <td class="valor-saldo ${o.saldo >= 0 ? 'positivo' : 'negativo'}">
                    ${formatarBRL(o.saldo)}
                </td>
                <td>
                    <div style="font-weight: 600;">${perc}%</div>
                    <div class="barra-progresso">
                        <div class="barra-progresso-fill" style="width: ${perc}%; background: ${o.cor};"></div>
                    </div>
                </td>
            </tr>
        `;
    }).join("");

    return `
        <div class="rel-tabela-wrapper">
            <div class="rel-tabela-titulo">
                🏷️ Distribuição por Origem da Verba
            </div>
            <table class="rel-tabela">
                <thead>
                    <tr>
                        <th>Origem</th>
                        <th>Entradas</th>
                        <th>Saídas</th>
                        <th>Saldo</th>
                        <th>% do Total</th>
                    </tr>
                </thead>
                <tbody>
                    ${linhas}
                </tbody>
            </table>
        </div>
    `;
}

function renderizarPorCategoria(porCategoria) {
    const total = porCategoria.reduce((acc, c) => acc + c.total, 0);

    let linhas = porCategoria.map(c => {
        const perc = total > 0 ? ((c.total / total) * 100).toFixed(1) : 0;

        return `
            <tr>
                <td><strong>${escapeHtml(c.categoria)}</strong></td>
                <td class="valor-negativo">${formatarBRL(c.total)}</td>
                <td>${c.quantidade}</td>
                <td>
                    <div style="font-weight: 600;">${perc}%</div>
                    <div class="barra-progresso">
                        <div class="barra-progresso-fill" style="width: ${perc}%;"></div>
                    </div>
                </td>
            </tr>
        `;
    }).join("");

    return `
        <div class="rel-tabela-wrapper">
            <div class="rel-tabela-titulo">
                📂 Despesas por Categoria
            </div>
            <table class="rel-tabela">
                <thead>
                    <tr>
                        <th>Categoria</th>
                        <th>Total Gasto</th>
                        <th>Qtd</th>
                        <th>% das Despesas</th>
                    </tr>
                </thead>
                <tbody>
                    ${linhas}
                </tbody>
            </table>
        </div>
    `;
}

// ============================================================================
// EXPORTAR CSV
// ============================================================================

function exportarCSV() {
    const url = `/api/relatorios/exportar-csv?ano=${anoAtual}&periodo=${periodoAtual}`;

    // Cria link temporário para download
    const a = document.createElement("a");
    a.href = url;
    a.style.display = "none";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
}
async function exportarExcel() {
    try {
        const res = await fetch(`/api/relatorios/exportar-excel?ano=${anoAtual}&periodo=${periodoAtual}`);
        if (!res.ok) {
            let msg = "Erro ao gerar o Excel.";
            try { const d = await res.json(); msg = d.erro || msg; } catch {}
            toast(msg, "erro");
            return;
        }
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `relatorio_${periodoAtual}_${anoAtual}.xlsx`;
        a.style.display = "none";
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (err) {
        toast("Erro de conexão: " + err.message, "erro");
    }
}