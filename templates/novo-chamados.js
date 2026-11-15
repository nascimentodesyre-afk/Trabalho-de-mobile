// ============================================================================
// NOVO CHAMADO - IPE (v5 - Forçando carregamento)
// ============================================================================

async function iniciarNovoChamado() {
    const selectPatrimonios = document.getElementById("id_patrimonio");
    const selectTipos = document.getElementById("id_tipo_chamado");

    if (selectPatrimonios) selectPatrimonios.innerHTML = '<option value="">Carregando patrimônios...</option>';
    if (selectTipos) selectTipos.innerHTML = '<option value="">Carregando tipos...</option>';

    try {
        // Carrega os patrimônios
        const resPatr = await fetch("/api/patrimonios");
        if (resPatr.ok) {
            const patrimonios = await resPatr.json();
            if (patrimonios.length === 0) {
                selectPatrimonios.innerHTML = '<option value="">Nenhum patrimônio ativo encontrado</option>';
            } else {
                selectPatrimonios.innerHTML = '<option value="">— Selecione o patrimônio —</option>' +
                    patrimonios.map(p => `<option value="${p.id_patrimonio}">Nº ${p.numero_patrimonio} — ${p.nome}</option>`).join("");
            }
        } else {
            selectPatrimonios.innerHTML = '<option value="">Erro ao carregar patrimônios</option>';
        }

        // Carrega os tipos de chamado
        const resTipos = await fetch("/api/tipos-chamado");
        if (resTipos.ok) {
            const tipos = await resTipos.json();
            selectTipos.innerHTML = '<option value="">— Selecione o tipo —</option>' +
                tipos.map(t => `<option value="${t.id_tipo_chamado}">${t.nome}</option>`).join("");
        } else {
            selectTipos.innerHTML = '<option value="">Erro ao carregar tipos</option>';
        }

    } catch (err) {
        console.error("Erro na requisição:", err);
        if (selectPatrimonios) selectPatrimonios.innerHTML = '<option value="">Erro de conexão</option>';
    }
}

// Garante que vai rodar quando a página carregar
if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", iniciarNovoChamado);
} else {
    iniciarNovoChamado();
}

// Função de cadastro
async function cadastrarChamado(event) {
    event.preventDefault();
    const form = event.target;
    const formData = new FormData(form);
    const btnSubmit = document.getElementById("btn-cadastrar");

    if (!formData.get("id_patrimonio")) {
        toast("Selecione um patrimônio.", "aviso");
        return;
    }

    await comSpinner(btnSubmit, async () => {
        try {
            const res = await fetch("/api/chamado/cadastrar", {
                method: "POST",
                body: formData
            });
            const data = await res.json();

            if (res.ok) {
                toast(data.mensagem || "Chamado aberto com sucesso!", "sucesso");
                setTimeout(() => {
                    window.location.href = "chamados.html";
                }, 1500);
            } else {
                toast(data.erro || "Erro ao registrar o chamado.", "erro");
            }
        } catch (err) {
            toast("Erro de conexão: " + err.message, "erro");
        }
    });
}

// Vincula o evento de submit ao formulário
document.addEventListener("DOMContentLoaded", () => {
    const form = document.getElementById("form-novo-chamado");
    if (form) form.addEventListener("submit", cadastrarChamado);
});