"""Registro pseudonimizado do uso do site.

O que este modulo grava, e o que ele deliberadamente nao grava, e a parte mais
importante do arquivo.

GRAVA: o caminho da pagina, a data e hora, se havia alguem autenticado (apenas
sim ou nao), a categoria filtrada, o termo buscado, o codigo de retorno, o
tempo de processamento e um identificador aleatorio de visita, que permite
reconstruir a sequencia de paginas de uma mesma sessao.

NAO GRAVA: endereco de origem, identificacao da conta, nome de usuario, agente
do navegador (que e lido apenas para descartar rastreador), conteudo de
formulario. Nenhum desses e necessario para responder as perguntas que
motivaram o registro - quais paginas sao mais vistas, o que a comunidade
procura e em que ponto as visitas se interrompem.

O identificador de visita e um numero aleatorio guardado na sessao. Ele nao
deriva de nada da pessoa, mas, enquanto a sessao existir e houver login, a
reassociacao seria tecnicamente possivel por quem tem acesso ao banco. Por isso
o tratamento e descrito como PSEUDONIMIZADO, e nao como anonimo: a LGPD trata
dado pseudonimizado como dado pessoal, e afirmar anonimato aqui seria impreciso.
"""

import logging
import secrets
import time

from django.conf import settings

from .models import EventoDeUso

logger = logging.getLogger(__name__)

# Uma visita termina depois deste tempo sem nenhuma requisicao. E a definicao
# usual de sessao em analise de uso: passado esse intervalo, o retorno conta
# como visita nova.
JANELA_DA_VISITA = 30 * 60

CHAVE_VISITA = 'visita_id'
CHAVE_ULTIMA = 'visita_em'

# Prefixos que nao sao navegacao de morador e so poluiriam a analise.
PREFIXOS_IGNORADOS = ('/static/', '/media/', '/api/')

# Envios de formulario que lidam com credencial. Sao registrados como pagina
# vista (o GET), mas o envio em si fica de fora: nao acrescenta nada ao que se
# quer medir e evita manter um registro de tentativas de autenticacao.
CAMINHOS_SEM_ENVIO = ('/login/', '/cadastro/')

# Marcas que aparecem no User-Agent de rastreadores e ferramentas automatizadas.
#
# O site e publico, entao buscadores e varredores o visitam sozinhos. Sem este
# filtro, a analise mediria robo em vez de morador - e com o trafego humano
# baixo que o projeto tem, provavelmente mais robo do que morador.
#
# O User-Agent e lido para DECIDIR se grava, e nao e armazenado em lugar
# nenhum. Inspecionar sem guardar nao altera o que o aviso de privacidade
# declara que e coletado.
MARCAS_DE_ROBO = (
    'bot', 'crawl', 'spider', 'slurp', 'archiver', 'scrapy',
    'curl', 'wget', 'python-requests', 'httpx', 'go-http-client',
    'headlesschrome', 'phantomjs', 'puppeteer', 'playwright',
    'facebookexternalhit', 'whatsapp', 'telegrambot', 'discordbot',
    'uptime', 'pingdom', 'semrush', 'ahrefs', 'dataprovider',
)


def e_robo(request):
    """Diz se a requisicao parece vir de um rastreador.

    Requisicao sem User-Agent nenhum tambem conta: navegador de pessoa sempre
    envia um. A deteccao nao e infalivel - um robo pode se disfarcar -, mas
    pega a grande maioria, que se identifica honestamente.
    """
    agente = request.META.get('HTTP_USER_AGENT', '').lower()
    if not agente:
        return True
    return any(marca in agente for marca in MARCAS_DE_ROBO)


def _ignorar(request):
    caminho = request.path

    if request.method not in ('GET', 'POST'):
        return True
    if request.method == 'POST' and caminho.startswith(CAMINHOS_SEM_ENVIO):
        return True
    if caminho.startswith(PREFIXOS_IGNORADOS):
        return True

    # O painel administrativo e trabalho do grupo, nao uso da comunidade.
    admin_url = '/' + str(getattr(settings, 'ADMIN_URL', 'admin/')).lstrip('/')
    if caminho.startswith(admin_url):
        return True

    if e_robo(request):
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
    """Grava um evento por requisicao de pessoa.

    Registra tanto paginas vistas quanto envios de formulario, com o codigo de
    retorno e o tempo de processamento. Requisicoes de rastreador sao
    descartadas, e o tempo e medido com time.monotonic, que nao anda para tras
    se o relogio do sistema for ajustado no meio da requisicao.

    O registro acontece depois da resposta estar pronta e e envolvido por um
    try/except amplo de proposito: telemetria nunca pode derrubar o site. Se a
    gravacao falhar - banco indisponivel, migration pendente -, a pessoa recebe
    a pagina normalmente e o evento simplesmente nao e contabilizado.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        comecou = time.monotonic()
        resposta = self.get_response(request)
        duracao = int((time.monotonic() - comecou) * 1000)

        try:
            if not _ignorar(request):
                EventoDeUso.objects.create(
                    visita=obter_visita(request),
                    caminho=request.path[:200],
                    autenticado=request.user.is_authenticated,
                    categoria=(request.GET.get('categoria') or '')[:20],
                    busca=(request.GET.get('busca') or '').strip()[:100],
                    status=resposta.status_code,
                    duracao_ms=duracao,
                )
        except Exception:
            # Engolir a excecao mantem o site de pe, mas engolir em silencio
            # tornaria uma falha de gravacao indistinguivel de "ninguem
            # navegou". logger.exception registra o traceback completo sem
            # interromper a resposta: a pessoa recebe a pagina e o problema
            # fica visivel no log.
            logger.exception('Falha ao registrar evento de uso')

        return resposta
