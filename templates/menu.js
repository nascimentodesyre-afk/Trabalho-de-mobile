// ============================================================================
// MENU DINÂMICO - IPE (v3)
// Perfis:
//   Patrimônio (1) → vê tudo
//   Usuário Padrão (2) → só consulta (chamados, inventário, movimentações, etc.)
// A Direção (3) foi REMOVIDA do sistema.
// ============================================================================

(function () {
    "use strict";

    // ------------------------------------------------------------------------
    // CONFIGURAÇÃO
    // ------------------------------------------------------------------------

    const PERFIL_PATRIMONIO = 1;

    // Itens que o Usuário Padrão NÃO pode ver
    const ITENS_RESTRITOS = [
        "alugados.html",
        "baixa.html",
        "financeiro.html",
        "relatorios.html",
        "admin.html",
        "notificacoes-envio.html",
        "backup.html",
    ];

    // Ordem canônica do menu (índice define a posição; menor = mais acima)
    const ORDEM_MENU = [
        "perfil.html",
        "index.html",
        "inventario.html",
        "alugados.html",
        "movimentacoes.html",
        "baixa.html",
        "chamados.html",
        "reparos.html",
        "historico.html",
        "financeiro.html",
        "relatorios.html",
        "admin.html",
        "notificacoes-envio.html",
        "backup.html",
        "sobre.html",
    ];

    // ------------------------------------------------------------------------
    // HELPERS
    // ------------------------------------------------------------------------

    /**
     * Remove o <li> do link indicado, se existir.
     * Aceita tanto "arquivo.html" quanto "/arquivo.html".
     */
    function removerItem(nav, href) {
        const seletor = `a[href="${href}"], a[href="/${href}"]`;
        const li = nav.querySelector(seletor)?.closest("li");
        if (li) li.remove();
    }

    /**
     * Retorna o peso (posição) do <li> na ordem canônica.
     * Itens fora da lista vão para o fim.
     */
    function pesoItem(li) {
        const a = li.querySelector("a");
        if (!a) return 999;

        let href = a.getAttribute("href") || "";
        href = href.replace(/^\//, ""); // remove barra inicial

        const idx = ORDEM_MENU.indexOf(href);
        return idx === -1 ? 999 : idx;
    }

    /**
     * Reordena os <li> da nav conforme ORDEM_MENU.
     */
    function reordenarMenu(nav) {
        const itens = Array.from(nav.querySelectorAll("li"));
        itens
            .sort((a, b) => pesoItem(a) - pesoItem(b))
            .forEach((li) => nav.appendChild(li));
    }

    /**
     * Marca como "active" o link correspondente à página atual.
     * Útil se o Jinja não fizer isso (fallback do frontend).
     */
    function marcarAtivo(nav) {
        const path = window.location.pathname.replace(/^\//, "");
        const arquivo = path.split("/").pop() || "index.html";

        nav.querySelectorAll("a").forEach((a) => {
            const href = (a.getAttribute("href") || "").replace(/^\//, "");
            if (href === arquivo) {
                a.classList.add("active");
            }
        });
    }

    // ------------------------------------------------------------------------
    // APLICAÇÃO DAS REGRAS
    // ------------------------------------------------------------------------

    function aplicarRegras(nav, perfil) {
        const isPatrimonio = perfil === PERFIL_PATRIMONIO;

        // 1) Usuário Padrão: remove os itens restritos
        if (!isPatrimonio) {
            ITENS_RESTRITOS.forEach((href) => removerItem(nav, href));
        }

        // 2) Reordena o que sobrou
        reordenarMenu(nav);

        // 3) Marca o ativo da página atual (redundância segura)
        marcarAtivo(nav);
    }

    // ------------------------------------------------------------------------
    // EXECUÇÃO
    // ------------------------------------------------------------------------

    async function init() {
        const nav = document.querySelector(".sidebar nav ul");
        if (!nav) return; // páginas sem menu (login, cadastro, erros) — sai silencioso

        let perfil = null;

        try {
            const res = await fetch("/api/dados_usuario", {
                credentials: "same-origin",
            });

            if (res.ok) {
                const u = await res.json();
                perfil = u.id_perfil;
            }
        } catch (e) {
            // Falha de rede: mantém o menu como está (renderizado pelo Jinja)
            console.debug("[menu.js] não foi possível obter o perfil:", e.message);
            return;
        }

        if (perfil === null) return;

        aplicarRegras(nav, perfil);
    }

    // ------------------------------------------------------------------------
    // DEBUG (opcional) — expõe funções no console
    // ------------------------------------------------------------------------
    window.__ipeMenu = {
        removerItem,
        reordenarMenu,
        marcarAtivo,
        aplicarRegras,
        ITENS_RESTRITOS,
        ORDEM_MENU,
    };

    // ------------------------------------------------------------------------
    // BOOTSTRAP
    // ------------------------------------------------------------------------

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();