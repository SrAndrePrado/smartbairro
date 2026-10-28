"""Registro pseudonimizado do uso do site.

O que este modulo grava, e o que ele deliberadamente nao grava, e a parte mais
importante do arquivo.

GRAVA: o caminho da pagina, a data e hora, se havia alguem autenticado (apenas
sim ou nao), a categoria filtrada, o termo buscado e um identificador aleatorio
de visita, que permite reconstruir a sequencia de paginas de uma mesma sessao.

NAO GRAVA: endereco de origem, identificacao da conta, nome de usuario, agente
do navegador. Nenhum desses e necessario para responder as perguntas que
motivaram o registro - quais paginas sao mais vistas, o que a comunidade
procura e em que ponto as visitas se interrompem.

O identificador de visita e um numero aleatorio guardado na sessao. Ele nao
deriva de nada da pessoa, mas, enquanto a sessao existir e houver login, a
reassociacao seria tecnicamente possivel por quem tem acesso ao banco. Por isso
o tratamento e descrito como PSEUDONIMIZADO, e nao como anonimo: a LGPD trata
dado pseudonimizado como dado pessoal, e afirmar anonimato aqui seria impreciso.
"""

import secrets
import time

from django.conf import settings

from .models import EventoDeUso

# Uma visita termina depois deste tempo sem nenhuma requisicao. E a definicao
# usual de sessao em analise de uso: passado esse intervalo, o retorno conta
# como visita nova.
JANELA_DA_VISITA = 30 * 60

CHAVE_VISITA = 'visita_id'
CHAVE_ULTIMA = 'visita_em'

# Prefixos que nao sao navegacao de morador e so poluiriam a analise.
PREFIXOS_IGNORADOS = ('/static/', '/media/', '/api/')


def _ignorar(request):
    caminho = request.path

    if request.method != 'GET':
        return True
    if caminho.startswith(PREFIXOS_IGNORADOS):
        return True

    # O painel administrativo e trabalho do grupo, nao uso da comunidade.
    admin_url = '/' + str(getattr(settings, 'ADMIN_URL', 'admin/')).lstrip('/')
    if caminho.startswith(admin_url):
        return True

    return False


def obter_visita(request):
    """Devolve o identificador da visita atual, criando um quando preciso.

    O identificador e sorteado, nao derivado de nada da pessoa. Passados 30
    minutos sem requisicao, um novo e sorteado e a visita anterior se encerra.
    """
    agora = time.time()
    visita = request.session.get(CHAVE_VISITA)
    ultima = request.session.get(CHAVE_ULTIMA, 0)

    if not visita or (agora - ultima) > JANELA_DA_VISITA:
        visita = secrets.token_hex(8)
        request.session[CHAVE_VISITA] = visita

    request.session[CHAVE_ULTIMA] = agora
    return visita


class RegistroDeUsoMiddleware:
    """Grava um evento por pagina vista.

    O registro acontece depois da resposta estar pronta e e envolvido por um
    try/except amplo de proposito: telemetria nunca pode derrubar o site. Se a
    gravacao falhar - banco indisponivel, migration pendente -, a pessoa recebe
    a pagina normalmente e o evento simplesmente nao e contabilizado.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        resposta = self.get_response(request)

        try:
            if not _ignorar(request) and resposta.status_code == 200:
                EventoDeUso.objects.create(
                    visita=obter_visita(request),
                    caminho=request.path[:200],
                    autenticado=request.user.is_authenticated,
                    categoria=(request.GET.get('categoria') or '')[:20],
                    busca=(request.GET.get('busca') or '').strip()[:100],
                )
        except Exception:
            pass

        return resposta
