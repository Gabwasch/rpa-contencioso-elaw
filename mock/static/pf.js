/*
 * Mini "PrimeFaces" do mock — imita os comportamentos do eLaw que importam para o robô:
 *  - selectOneMenu: <div> visível + <select id="..._input"> OCULTO e SEM name. Quem vai para o
 *    servidor é um <input hidden> que só muda quando o usuário CLICA na opção (ou pela API do
 *    widget). Mudar o <select> por JS não registra nada — igual ao sistema real.
 *  - selectCheckboxMenu: checkboxes reais (com name) dentro de um painel movido para o <body>.
 *  - campos de data: o valor só chega ao servidor se foi DIGITADO (evento confiável).
 *  - diálogos em IFRAME, abas, painel "maleta" liga/desliga, máscara de carregamento.
 */
(function () {
  "use strict";
  const widgets = {};
  window.PrimeFaces = { widgets: widgets };
  const PF = (window.PF = {});

  function fecharPaineis(exceto) {
    document.querySelectorAll(".ui-selectonemenu-panel, .ui-selectcheckboxmenu-panel").forEach(function (p) {
      if (p !== exceto) p.hidden = true;
    });
  }

  function posicionar(painel, alvo) {
    const r = alvo.getBoundingClientRect();
    painel.style.left = r.left + window.scrollX + "px";
    painel.style.top = r.bottom + window.scrollY + 2 + "px";
    painel.style.minWidth = r.width + "px";
  }

  function iniciarSelect(div) {
    if (div.dataset.pfIniciado) return;
    div.dataset.pfIniciado = "1";
    const id = div.id;
    const sel = document.getElementById(id + "_input");
    const oculto = document.getElementById(id + "_valor");
    const painel = document.getElementById(id + "_panel");
    const rotulo = div.querySelector(".ui-selectonemenu-label");
    document.body.appendChild(painel); // como no PrimeFaces, o painel vive no <body>
    const w = {
      id: id,
      selectValue: function (v) {
        const o = Array.prototype.find.call(sel.options, function (o) { return o.value === v; });
        if (!o) return;
        sel.value = v;
        rotulo.textContent = o.text;
        if (oculto) oculto.value = v;
        painel.querySelectorAll("li").forEach(function (li) {
          li.classList.toggle("ui-state-highlight", li.dataset.value === v);
        });
        painel.hidden = true;
        div.dispatchEvent(new CustomEvent("pf:change", { bubbles: true, detail: { valor: v, rotulo: o.text } }));
      },
      getSelectedLabel: function () { return rotulo.textContent; },
    };
    widgets["widget_" + id.replace(/[^A-Za-z0-9]/g, "_")] = w;
    div.addEventListener("click", function (ev) {
      ev.stopPropagation();
      const abrir = painel.hidden;
      fecharPaineis();
      if (abrir) { posicionar(painel, div); painel.hidden = false; }
    });
    painel.querySelectorAll("li").forEach(function (li) {
      li.addEventListener("click", function (ev) { ev.stopPropagation(); w.selectValue(li.dataset.value); });
    });
  }

  function iniciarCheckMenu(div) {
    if (div.dataset.pfIniciado) return;
    div.dataset.pfIniciado = "1";
    const painel = document.getElementById(div.id + "_panel");
    const rotulo = div.querySelector(".ui-selectcheckboxmenu-label");
    document.body.appendChild(painel);
    function atualizar() {
      const n = painel.querySelectorAll("input:checked").length;
      rotulo.textContent = n ? n + " selecionado(s)" : "Selecione";
    }
    painel.addEventListener("click", function (ev) { ev.stopPropagation(); });
    painel.addEventListener("change", atualizar);
    div.addEventListener("click", function (ev) {
      ev.stopPropagation();
      const abrir = painel.hidden;
      fecharPaineis();
      if (abrir) { posicionar(painel, div); painel.hidden = false; }
    });
    atualizar();
  }

  function iniciarData(inp) {
    if (inp.dataset.pfIniciado) return;
    inp.dataset.pfIniciado = "1";
    const oculto = document.getElementById(inp.id.replace(/_input$/, ""));
    inp.addEventListener("input", function (ev) {
      if (ev.isTrusted && oculto) oculto.value = inp.value;
    });
  }

  PF.iniciar = function (raiz) {
    raiz = raiz || document;
    raiz.querySelectorAll(".ui-selectonemenu").forEach(iniciarSelect);
    raiz.querySelectorAll(".ui-selectcheckboxmenu").forEach(iniciarCheckMenu);
    raiz.querySelectorAll("input.ui-calendar").forEach(iniciarData);
  };

  PF.ocupado = function (sim) {
    let m = document.querySelector(".ui-blockui");
    if (!m) {
      m = document.createElement("div");
      m.className = "ui-blockui";
      m.innerHTML = '<div class="spinner"></div>';
      m.hidden = true;
      document.body.appendChild(m);
    }
    m.hidden = !sim;
  };

  // ---- diálogos em iframe (os modais do eLaw são páginas à parte dentro de um iframe) ----
  PF.abrirDialogo = function (url, titulo, largura) {
    PF.fecharDialogo();
    const mascara = document.createElement("div");
    mascara.className = "ui-dialog-mask";
    const dlg = document.createElement("div");
    dlg.className = "ui-dialog";
    dlg.style.width = (largura || 720) + "px";
    dlg.innerHTML = '<div class="ui-dialog-titlebar"><span></span></div><iframe class="ui-dialog-frame"></iframe>';
    dlg.querySelector("span").textContent = titulo || "";
    dlg.querySelector("iframe").src = url;
    document.body.appendChild(mascara);
    document.body.appendChild(dlg);
  };
  PF.fecharDialogo = function () {
    document.querySelectorAll(".ui-dialog, .ui-dialog-mask").forEach(function (e) { e.remove(); });
  };
  PF.fecharEsteDialogo = function (extra) {
    if (extra) window.parent.postMessage(extra, location.origin);
    window.parent.postMessage({ tipo: "fechar-dialogo" }, location.origin);
  };
  window.addEventListener("message", function (ev) {
    if (ev.origin !== location.origin) return;
    const d = ev.data || {};
    if (d.tipo === "fechar-dialogo") PF.fecharDialogo();
    if (d.tipo === "recarregar-anexos" && PF.recarregarAnexos) PF.recarregarAnexos();
  });

  // ---- abas (a[href="#tabViewProcesso:..."]) com carga "ajax" opcional (data-lazy) ----
  PF.abas = function () {
    const ancoras = document.querySelectorAll('.ui-tabs-nav a[href^="#"]');
    ancoras.forEach(function (a) {
      a.addEventListener("click", function (ev) {
        ev.preventDefault();
        const alvo = a.getAttribute("href").slice(1);
        ancoras.forEach(function (x) { x.parentElement.classList.toggle("ui-state-active", x === a); });
        document.querySelectorAll(".ui-tabs-panel").forEach(function (p) { p.hidden = p.id !== alvo; });
        const painel = document.getElementById(alvo);
        if (painel && painel.dataset.lazy) PF.carregar(painel);
      });
    });
  };
  PF.carregar = function (painel) {
    PF.ocupado(true);
    painel.innerHTML = "";
    // atraso de propósito: a aba chega depois do clique (o robô precisa esperar o elemento certo)
    setTimeout(function () {
      fetch(painel.dataset.lazy, { credentials: "same-origin" })
        .then(function (r) {
          if (r.redirected || r.url.indexOf("login.elaw") >= 0) { location.href = r.url; return ""; }
          return r.text();
        })
        .then(function (html) { painel.innerHTML = html; PF.iniciar(painel); })
        .finally(function () { PF.ocupado(false); });
    }, 600);
  };

  document.addEventListener("click", function () { fecharPaineis(); });
  document.addEventListener("keydown", function (ev) { if (ev.key === "Escape") fecharPaineis(); });
  document.addEventListener("DOMContentLoaded", function () {
    PF.iniciar();
    PF.abas();
    const maleta = document.querySelector("a.maleta");
    if (maleta) {
      maleta.addEventListener("click", function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        const p = document.querySelector(".notification-panel");
        p.hidden = !p.hidden; // liga/desliga, como no eLaw
      });
    }
    document.querySelectorAll(".ui-growl-item").forEach(function (g) {
      setTimeout(function () { g.classList.add("saindo"); }, 6000);
    });
  });
})();
