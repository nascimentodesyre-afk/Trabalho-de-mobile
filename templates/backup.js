// ============================================================================
// MÓDULO DE BACKUP - IPE
// ============================================================================

document.addEventListener("DOMContentLoaded", () => {
    carregarInfo();
});

async function carregarInfo() {
    try {
        const res = await fetch("/api/backup/info");
        if (!res.ok) throw new Error("HTTP " + res.status);
        const info = await res.json();

        renderizarTabelas(info.tabelas, info.total_registros);
        renderizarBackups(info.backups);

    } catch (err) {
        console.error("Erro ao carregar info:", err);
        document.getElementById("tabela-grid").innerHTML =
            '<em style="color:red;">Erro ao carregar informações.</em>';
        document.getElementById("lista-backups").innerHTML =
            '<em style="color:red; padding:15px; display:block;">Erro ao carregar backups.</em>';
    }
}

function renderizarTabelas(tabelas, totalRegistros) {
    const grid = document.getElementById("tabela-grid");
    const contador = document.getElementById("contador-tabelas");

    if (!tabelas || tabelas.length === 0) {
        contador.innerText = "0 tabelas";
        grid.innerHTML = '<em style="color: var(--text-light);">Nenhuma tabela encontrada.</em>';
        return;
    }

    contador.innerText = `${tabelas.length} tabelas · ${totalRegistros.toLocaleString('pt-BR')} registros no total`;

    const comRegistros = tabelas.filter(t => t.total > 0);

    if (comRegistros.length === 0) {
        grid.innerHTML = '<em style="color: var(--text-light);">Nenhuma tabela com registros.</em>';
        return;
    }

    grid.innerHTML = "";

    comRegistros.forEach(t => {
        const div = document.createElement("div");
        div.className = "tabela-item";
        div.innerHTML = `
            <div>
                <strong>${escapeHtml(t.nome)}</strong><br>
                <span style="font-size:0.75rem; color:var(--text-light);">
                    ${t.total.toLocaleString('pt-BR')} registros
                </span>
            </div>
            <button class="btn-csv" onclick="exportarTabela('${t.nome}', this)">
                ⬇ CSV
            </button>
        `;
        grid.appendChild(div);
    });
}

function renderizarBackups(backups) {
    const div = document.getElementById("lista-backups");

    if (!backups || backups.length === 0) {
        div.innerHTML = '<div class="empty-state">Nenhum backup gerado ainda.</div>';
        return;
    }

    div.innerHTML = "";
    backups.forEach(b => {
        const item = document.createElement("div");
        item.className = "backup-item";
        item.innerHTML = `
            <div class="info">
                <div class="nome">📄 ${escapeHtml(b.nome)}</div>
                <div class="detalhes">${escapeHtml(b.data)} · ${b.tamanho_kb} KB</div>
            </div>
            <div class="backup-actions">
                <button class="btn-mini baixar btn-baixar-backup" data-nome="${escapeAttr(b.nome)}">⬇ Baixar</button>
                <button class="btn-mini excluir btn-excluir-backup" data-nome="${escapeAttr(b.nome)}">🗑</button>
            </div>
        `;
        div.appendChild(item);
    });

    div.querySelectorAll(".btn-baixar-backup").forEach(btn => {
        btn.addEventListener("click", () => baixarBackup(btn.dataset.nome));
    });
    div.querySelectorAll(".btn-excluir-backup").forEach(btn => {
        btn.addEventListener("click", () => excluirBackup(btn.dataset.nome));
    });
}

function exportar(tipo, btn) {
    // Feedback visual com spinner CSS já existente no backup.html
    const textoOriginal = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span>Gerando...';

    const url = `/api/backup/exportar-${tipo}`;
    const a = document.createElement("a");
    a.href = url;
    a.style.display = "none";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);

    setTimeout(() => {
        btn.disabled = false;
        btn.innerHTML = textoOriginal;
        carregarInfo();
    }, 3000);
}

function exportarTabela(nome, btn) {
    const textoOriginal = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span>';

    const a = document.createElement("a");
    a.href = `/api/backup/exportar-csv/${nome}`;
    a.style.display = "none";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);

    setTimeout(() => {
        btn.disabled = false;
        btn.innerHTML = textoOriginal;
        carregarInfo();
    }, 2500);
}

function baixarBackup(nome) {
    const a = document.createElement("a");
    a.href = `/api/backup/download/${encodeURIComponent(nome)}`;
    a.style.display = "none";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
}

async function excluirBackup(nome) {
    const ok = await confirmarAcao(
        `Excluir o backup <strong>"${escapeHtml(nome)}"</strong>?\n\nEsta ação não pode ser desfeita.`,
        { titulo: "Excluir backup", textoConfirmar: "Excluir", perigo: true }
    );
    if (!ok) return;

    try {
        const res = await fetch(`/api/backup/excluir/${encodeURIComponent(nome)}`, {
            method: "DELETE"
        });
        const data = await res.json();

        if (res.ok) {
            toast(data.mensagem || "Backup excluído!", "sucesso");
            carregarInfo();
        } else {
            toast(data.erro || "Erro ao excluir.", "erro");
        }
    } catch (err) {
        toast("Erro de conexão: " + err.message, "erro");
    }
}