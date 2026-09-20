/*
 * SmartBairro - interacoes sem recarregar a pagina
 * ------------------------------------------------
 * Este arquivo usa "aprimoramento progressivo": os formularios de curtir e
 * comentar funcionam normalmente sem JavaScript, do jeito tradicional. O que
 * o script faz e interceptar o envio e conversar com a API em segundo plano,
 * atualizando so o pedaco da tela que mudou.
 *
 * Se este arquivo falhar ao carregar, o site continua inteiro funcionando.
 */

(function () {
  'use strict';

  /**
   * Le o token CSRF do cookie.
   *
   * O Django exige esse token em qualquer POST vindo do navegador, para provar
   * que a requisicao partiu do proprio site e nao de uma pagina de terceiros.
   * Um formulario normal envia o token num campo escondido; como aqui quem
   * envia e o JavaScript, precisamos mandar o mesmo valor no cabecalho.
   */
  function obterTokenCsrf() {
    const nome = 'csrftoken=';
    const partes = document.cookie.split(';');
    for (let parte of partes) {
      parte = parte.trim();
      if (parte.startsWith(nome)) {
        return decodeURIComponent(parte.substring(nome.length));
      }
    }
    return '';
  }

  /**
   * Anuncia uma mudanca para quem usa leitor de tela.
   *
   * Quando a pagina recarrega, o leitor de tela le tudo de novo e o usuario
   * percebe o que aconteceu. Atualizando so um pedaco via JavaScript, essa
   * pista desaparece. A regiao com aria-live resolve isso: o que for escrito
   * nela e lido em voz alta sem tirar o foco de onde a pessoa esta.
   */
  function anunciar(mensagem) {
    const regiao = document.getElementById('anuncios');
    if (regiao) {
      regiao.textContent = mensagem;
    }
  }

  async function enviar(url, corpo) {
    const resposta = await fetch(url, {
      method: 'POST',
      headers: {
        'X-CSRFToken': obterTokenCsrf(),
        'X-Requested-With': 'XMLHttpRequest',
      },
      body: corpo,
    });
    const dados = await resposta.json().catch(() => ({}));
    return { ok: resposta.ok, status: resposta.status, dados: dados };
  }

  // -------------------------------------------------------------------------
  // Curtir
  // -------------------------------------------------------------------------

  function ligarCurtidas() {
    document.querySelectorAll('form[data-curtir]').forEach(function (form) {
      form.addEventListener('submit', async function (evento) {
        // Impede o envio tradicional, que recarregaria a pagina inteira.
        evento.preventDefault();

        const botao = form.querySelector('button');
        const postId = form.dataset.curtir;
        const contador = document.querySelector('[data-contador-curtidas="' + postId + '"]');

        botao.disabled = true;
        const resultado = await enviar('/api/curtir/' + postId + '/', new FormData(form));
        botao.disabled = false;

        if (resultado.status === 401) {
          anunciar('Entre na sua conta para curtir.');
          window.location.href = '/login/';
          return;
        }
        if (!resultado.ok) {
          // Em caso de erro inesperado, envia do jeito tradicional.
          form.submit();
          return;
        }

        const curtido = resultado.dados.curtido;
        const total = resultado.dados.total;

        botao.textContent = curtido ? 'Curtido' : 'Curtir';
        botao.className = curtido ? 'btn btn-danger btn-sm' : 'btn btn-outline-danger btn-sm';
        // aria-pressed informa ao leitor de tela se o botao esta "ligado".
        botao.setAttribute('aria-pressed', curtido ? 'true' : 'false');

        if (contador) {
          contador.textContent = total + (total === 1 ? ' curtida' : ' curtidas');
        }
        anunciar(curtido ? 'Post curtido. Total: ' + total : 'Curtida removida. Total: ' + total);
      });
    });
  }

  // -------------------------------------------------------------------------
  // Comentar
  // -------------------------------------------------------------------------

  function ligarComentarios() {
    const form = document.querySelector('form[data-comentar]');
    if (!form) {
      return;
    }

    form.addEventListener('submit', async function (evento) {
      evento.preventDefault();

      const postId = form.dataset.comentar;
      const campo = form.querySelector('textarea');
      const botao = form.querySelector('button');
      const lista = document.getElementById('lista-comentarios');
      const aviso = document.getElementById('erro-comentario');

      if (aviso) {
        aviso.textContent = '';
      }

      botao.disabled = true;
      const resultado = await enviar('/api/comentar/' + postId + '/', new FormData(form));
      botao.disabled = false;

      if (resultado.status === 401) {
        window.location.href = '/login/';
        return;
      }
      if (!resultado.ok) {
        const mensagem = resultado.dados.erro || 'Nao foi possivel enviar o comentario.';
        if (aviso) {
          aviso.textContent = mensagem;
        }
        anunciar(mensagem);
        return;
      }

      // Remove o aviso de "seja o primeiro a comentar", se estiver na tela.
      const vazio = document.getElementById('sem-comentarios');
      if (vazio) {
        vazio.remove();
      }

      const item = document.createElement('p');
      const autor = document.createElement('strong');
      autor.textContent = resultado.dados.comentario.usuario;
      item.appendChild(autor);
      // Usar textContent, e nao innerHTML, garante que o que o usuario
      // escreveu seja tratado como texto puro. Se alguem digitar uma tag
      // HTML, ela aparece escrita, nao e executada pelo navegador.
      item.appendChild(document.createTextNode(': ' + resultado.dados.comentario.texto));

      if (lista) {
        lista.appendChild(item);
      }
      campo.value = '';
      campo.focus();
      anunciar('Comentario publicado.');
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    ligarCurtidas();
    ligarComentarios();
  });
})();
