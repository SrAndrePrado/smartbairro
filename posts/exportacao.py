"""Exportacao dos registros de uso em CSV.

O plano gratuito do Render nao da acesso a terminal no servidor, entao um
comando que gerasse arquivo la dentro ficaria inalcancavel. A exportacao
acontece pelo painel administrativo, como download do navegador: quem tem
acesso ao painel seleciona os registros e baixa o CSV.
"""

from django.utils import timezone

import csv
from io import StringIO as _StringIO

from django.http import HttpResponse

# Dias da semana por extenso, para quem for montar o grafico nao precisar
# traduzir numero. weekday() devolve 0 para segunda-feira.
DIAS_DA_SEMANA = ['segunda', 'terça', 'quarta', 'quinta', 'sexta',
                  'sábado', 'domingo']


def _mediana(valores):
    """Mediana de uma lista de inteiros, ou zero se estiver vazia."""
    if not valores:
        return 0
    ordenados = sorted(valores)
    meio = len(ordenados) // 2
    if len(ordenados) % 2:
        return ordenados[meio]
    return (ordenados[meio - 1] + ordenados[meio]) // 2


def _secao(caminho):
    """Agrupa o caminho numa secao legivel, para facilitar o agrupamento.

    Sem isso, cada post vira um valor diferente de caminho (/post/1/, /post/2/)
    e o grafico de paginas mais vistas fica com uma barra por post em vez de
    uma barra para "detalhe de post".
    """
    if caminho == '/':
        return 'mural'
    for prefixo, nome in [('/post/', 'detalhe do post'),
                          ('/criar/', 'criar post'),
                          ('/editar/', 'editar post'),
                          ('/login/', 'login'),
                          ('/cadastro/', 'cadastro'),
                          ('/privacidade/', 'aviso de privacidade')]:
        if caminho.startswith(prefixo):
            return nome
    return 'outro'


def _resposta_csv(nome_arquivo, cabecalho, linhas):
    """Monta a resposta CSV pronta para abrir no Excel e no Power BI.

    Duas escolhas praticas: o separador e ponto e virgula e a codificacao leva
    BOM (utf-8-sig). O Excel em portugues espera ponto e virgula como separador
    de lista, e sem o BOM ele abre os acentos errados. Com os dois, o arquivo
    abre limpo com dois cliques, sem assistente de importacao.
    """
    buffer = _StringIO()
    escritor = csv.writer(buffer, delimiter=';')
    escritor.writerow(cabecalho)
    escritor.writerows(linhas)

    resposta = HttpResponse(
        buffer.getvalue().encode('utf-8-sig'),
        content_type='text/csv; charset=utf-8',
    )
    resposta['Content-Disposition'] = f'attachment; filename="{nome_arquivo}"'
    return resposta


def exportar_eventos_csv(queryset):
    """Uma linha por pagina vista, com colunas ja derivadas para analise."""
    linhas = []
    for e in queryset.order_by('ocorrido_em'):
        momento = timezone.localtime(e.ocorrido_em)
        linhas.append([
            momento.strftime('%Y-%m-%d %H:%M:%S'),
            momento.strftime('%Y-%m-%d'),
            momento.hour,
            DIAS_DA_SEMANA[momento.weekday()],
            e.caminho,
            _secao(e.caminho),
            e.categoria,
            e.busca,
            'sim' if e.autenticado else 'nao',
            e.status,
            'sim' if e.status < 400 else 'nao',
            e.duracao_ms,
            e.visita,
        ])

    return _resposta_csv(
        'smartbairro_uso.csv',
        ['ocorrido_em', 'data', 'hora', 'dia_da_semana', 'caminho', 'secao',
         'categoria', 'busca', 'autenticado', 'status', 'aceito',
         'duracao_ms', 'visita'],
        linhas,
    )


def exportar_visitas_csv(queryset):
    """Uma linha por visita: quantas paginas teve e em qual parou.

    E a tabela que responde "onde as pessoas param". A ultima pagina de cada
    visita e o ponto de abandono; contar quantas visitas terminam em cada secao
    da o funil, sem precisar de ferramenta externa.
    """
    visitas = {}
    for e in queryset.order_by('ocorrido_em'):
        v = visitas.setdefault(e.visita, {
            'inicio': e.ocorrido_em, 'fim': e.ocorrido_em,
            'paginas': 0, 'ultimo': e.caminho, 'autenticado': False,
            'buscas': 0, 'recusas': 0, 'duracoes': [],
        })
        v['fim'] = e.ocorrido_em
        v['paginas'] += 1
        v['ultimo'] = e.caminho
        v['autenticado'] = v['autenticado'] or e.autenticado
        if e.busca:
            v['buscas'] += 1
        if e.status >= 400:
            v['recusas'] += 1
        v['duracoes'].append(e.duracao_ms)

    linhas = []
    for identificador, v in visitas.items():
        inicio = timezone.localtime(v['inicio'])
        duracao = int((v['fim'] - v['inicio']).total_seconds())
        linhas.append([
            identificador,
            inicio.strftime('%Y-%m-%d %H:%M:%S'),
            inicio.strftime('%Y-%m-%d'),
            DIAS_DA_SEMANA[inicio.weekday()],
            v['paginas'],
            duracao,
            v['ultimo'],
            _secao(v['ultimo']),
            v['buscas'],
            v['recusas'],
            # Mediana, e nao media: uma unica requisicao lenta - tipicamente a
            # primeira apos a hibernacao - distorceria a media da visita
            # inteira e faria o site parecer pior do que e.
            _mediana(v['duracoes']),
            'sim' if v['autenticado'] else 'nao',
        ])
    linhas.sort(key=lambda l: l[1])

    return _resposta_csv(
        'smartbairro_visitas.csv',
        ['visita', 'inicio', 'data', 'dia_da_semana', 'paginas_vistas',
         'duracao_segundos', 'ultima_pagina', 'secao_de_saida', 'buscas',
         'recusas', 'ms_mediana', 'teve_login'],
        linhas,
    )
