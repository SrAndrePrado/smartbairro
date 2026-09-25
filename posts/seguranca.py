"""Utilidades de seguranca: identificacao do visitante e limite de tentativas.

O limite usa o cache do Django. Na configuracao padrao o cache vive na memoria
do processo, o que significa que ele se perde quando o servidor reinicia e nao
e compartilhado entre processos. Para conter forca bruta e abuso de endpoint
num projeto deste porte, e suficiente -- e evita depender de um servico extra
como Redis, que nao cabe no plano gratuito.
"""

from django.core.cache import cache

# Quantas tentativas sao permitidas dentro da janela, por endereco de origem.
LIMITE_LOGIN = 10
JANELA_LOGIN = 5 * 60

LIMITE_INGESTAO = 60
JANELA_INGESTAO = 60


def identificar_origem(request):
    """Descobre o endereco de quem fez a requisicao.

    Em producao a aplicacao fica atras de um servidor intermediario, entao o
    endereco real do visitante chega no cabecalho X-Forwarded-For, e o primeiro
    valor da lista e o do visitante.
    """
    encaminhado = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if encaminhado:
        return encaminhado.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', 'desconhecido')


def registrar_tentativa(prefixo, request, janela):
    """Conta mais uma tentativa e devolve o total dentro da janela atual."""
    chave = f'limite:{prefixo}:{identificar_origem(request)}'

    # cache.add so cria a chave se ela ainda nao existir, ja com o prazo de
    # validade. Assim a janela comeca na primeira tentativa e nao e reiniciada
    # pelas seguintes, que e o comportamento correto.
    if cache.add(chave, 1, janela):
        return 1

    try:
        return cache.incr(chave)
    except ValueError:
        # A chave expirou entre a verificacao e o incremento.
        cache.set(chave, 1, janela)
        return 1


def excedeu(prefixo, request, limite, janela):
    return registrar_tentativa(prefixo, request, janela) > limite
