"""Interpretacao do texto livre de uma mensagem recebida.

Este modulo transforma a mensagem crua que o morador enviou - algo como
"vendo sofa 3 lugares 200 reais zap 11 99999-9999" - numa sugestao de post
com categoria, titulo, descricao e telefone separados.

Duas decisoes de projeto explicam o formato deste arquivo.

A primeira: ele **nao importa nada do Django**. Recebe uma string e devolve um
dicionario. Isso permite testar a interpretacao sem banco de dados, sem
servidor e sem requisicao, e permite trocar a estrategia mais adiante (regras,
modelo de linguagem, modelo treinado) sem tocar no resto da aplicacao.

A segunda: a sugestao **nunca publica sozinha**. O resultado daqui preenche um
rascunho que continua indo para a fila de moderacao. O ganho nao e eliminar o
moderador, e sim entregar a ele um formulario ja preenchido em vez de um texto
cru para digitar do zero.
"""

import re
import unicodedata

# ---------------------------------------------------------------------------
# Normalizacao
# ---------------------------------------------------------------------------


def normalizar(texto):
    """Reduz o texto a uma forma comparavel: minusculas e sem acentos.

    Mensagens de WhatsApp sao escritas com pressa: "doacao", "doação" e
    "DOAÇÃO" sao a mesma palavra para quem escreveu. Comparar as tres como
    iguais evita precisar listar cada variacao nas palavras-chave.

    A decomposicao NFD separa a letra do acento ("ç" vira "c" + cedilha) e o
    filtro descarta a parte do acento, que a tabela Unicode classifica como
    categoria "Mn" (mark, nonspacing).
    """
    decomposto = unicodedata.normalize('NFD', texto.lower())
    return ''.join(c for c in decomposto if unicodedata.category(c) != 'Mn')


# ---------------------------------------------------------------------------
# Telefone
# ---------------------------------------------------------------------------

# Numero brasileiro com ou sem DDD, com ou sem o nono digito, aceitando
# parenteses, espacos, pontos e hifens entre os grupos.
#
# O inicio usa (?<!\w) em vez de \b porque o numero pode comecar por parentese:
# \b exige um caractere de palavra ao lado, e "(" nao e. Com \b, "(11) 98888"
# comecaria a casar so no "1", devolvendo "11) 98888" com o parentese solto.
PADRAO_TELEFONE = re.compile(
    r'(?<!\w)(?:\(?\d{2}\)?[\s.\-]?)?(?:9[\s.\-]?)?\d{4}[\s.\-]?\d{4}(?!\d)'
)

# Precos escritos como "200 reais", "R$ 200", "200,00" - nao sao telefone.
PADRAO_PRECO = re.compile(r'r?\$?\s*\d+(?:[.,]\d{2})?\s*(?:reais|conto|pila)\b')


def extrair_telefone(texto):
    """Devolve o primeiro telefone encontrado no texto, ou string vazia.

    O numero e devolvido como o morador escreveu. Normalizar o formato seria
    facil, mas o moderador precisa conseguir conferir contra a mensagem
    original, e para isso o texto tem que bater.
    """
    for achado in PADRAO_TELEFONE.finditer(texto):
        bruto = achado.group(0)
        digitos = re.sub(r'\D', '', bruto)

        # Telefone brasileiro tem 8 digitos (fixo antigo), 9 (celular sem DDD),
        # 10 (fixo com DDD) ou 11 (celular com DDD). Fora disso e outra coisa.
        if len(digitos) not in (8, 9, 10, 11):
            continue

        # Um valor em reais pode ter oito digitos seguidos por coincidencia.
        # Se o trecho estiver logo antes de "reais", nao e telefone.
        depois = texto[achado.end():achado.end() + 12].lower()
        if re.match(r'\s*(reais|conto|pila|r\$)', depois):
            continue

        return bruto.strip()
    return ''


# ---------------------------------------------------------------------------
# Categoria
# ---------------------------------------------------------------------------

# Cada categoria tem dois grupos de pistas. As "fortes" praticamente decidem
# sozinhas (quem escreve "vendo" esta vendendo); as "fracas" so desempatam,
# porque aparecem em mais de um contexto ("retirar" cabe em venda e em doacao).
#
# Os termos ja estao normalizados: minusculos e sem acento, como sai de
# normalizar(). Acrescentar uma palavra aqui e a forma mais barata de melhorar
# a classificacao, e nao exige mexer em nenhuma outra parte do codigo.
PISTAS = {
    'venda': {
        'fortes': ['vendo', 'vende-se', 'vende se', 'a venda', 'to vendendo',
                   'estou vendendo', 'repassando', 'troco por'],
        'fracas': ['reais', 'r$', 'preco', 'valor', 'barato', 'seminovo',
                   'semi novo', 'usado', 'novo na caixa', 'aceito cartao',
                   'parcelo', 'conto', 'pila'],
    },
    'doacao': {
        'fortes': ['doando', 'doacao', 'doo ', 'de graca', 'gratis',
                   'gratuito', 'desapego', 'desapegando', 'quem quiser leva',
                   'nao quero nada'],
        'fracas': ['retirar no local', 'so buscar', 'pegar aqui'],
    },
    'servico': {
        'fortes': ['faco', 'ofereco', 'presto servico', 'aulas de', 'aula de',
                   'orcamento', 'atendo', 'trabalho com', 'conserto',
                   'diarista', 'pedreiro', 'eletricista', 'encanador',
                   'pintor', 'manicure', 'cabeleireira', 'costureira',
                   'professor', 'professora', 'marido de aluguel'],
        'fracas': ['servico', 'reforco', 'domicilio', 'experiencia',
                   'disponivel', 'agende'],
    },
    'achados': {
        'fortes': ['achei', 'encontrei', 'perdi', 'perdido', 'perdida',
                   'encontrado', 'encontrada', 'sumiu', 'desapareceu',
                   'alguem perdeu', 'esta comigo', 'fugiu de casa'],
        'fracas': ['coleira', 'carteira', 'chave', 'documento', 'rg', 'cnh',
                   'mochila', 'oculos'],
    },
    'aviso': {
        'fortes': ['aviso', 'atencao', 'comunicado', 'informo', 'fica o aviso',
                   'nao havera', 'nao vai ter', 'sera interditada',
                   'manutencao', 'assembleia', 'reuniao do condominio'],
        'fracas': ['amanha', 'hoje a noite', 'obra', 'falta de agua',
                   'falta de luz', 'rua interditada', 'horario'],
    },
}

PESO_FORTE = 3
PESO_FRACA = 1

# Abaixo desta pontuacao a sugestao nao e considerada confiavel e a mensagem
# segue para o moderador sem categoria preenchida. Errar em silencio e pior do
# que admitir que nao soube: um post na categoria errada some do lugar onde o
# morador procuraria por ele.
PONTUACAO_MINIMA = PESO_FORTE


def pontuar_categorias(texto):
    """Devolve a pontuacao de cada categoria para o texto dado.

    Cada ocorrencia de uma pista soma o peso do seu grupo. Devolver o mapa
    inteiro, e nao so o vencedor, facilita entender por que a classificacao
    escolheu o que escolheu - util no teste e no relatorio.
    """
    alvo = normalizar(texto)
    pontos = {}

    for categoria, grupos in PISTAS.items():
        total = 0
        for termo in grupos['fortes']:
            if termo in alvo:
                total += PESO_FORTE
        for termo in grupos['fracas']:
            if termo in alvo:
                total += PESO_FRACA
        pontos[categoria] = total

    return pontos


def escolher_categoria(texto):
    """Devolve (categoria, pontuacao) ou (None, 0) quando nao ha confianca.

    Em caso de empate entre duas categorias, devolve None: um empate significa
    que o texto tem pistas de ambas e a decisao e justamente o tipo de duvida
    que vale a pena mandar para uma pessoa.
    """
    pontos = pontuar_categorias(texto)
    maior = max(pontos.values())

    if maior < PONTUACAO_MINIMA:
        return None, maior

    vencedoras = [c for c, p in pontos.items() if p == maior]
    if len(vencedoras) > 1:
        return None, maior

    return vencedoras[0], maior


# ---------------------------------------------------------------------------
# Titulo
# ---------------------------------------------------------------------------

LIMITE_TITULO = 100          # o campo titulo do model aceita 100 caracteres
PALAVRAS_NO_TITULO = 8

# Palavras que costumam sobrar na ponta do titulo depois que o telefone sai:
# "... 200 reais zap" ou "... retirar no local falar com". Nao carregam
# informacao e so ocupam espaco no card do mural.
SOBRAS_NO_FIM = {'zap', 'whats', 'whatsapp', 'tel', 'telefone', 'contato',
                 'falar', 'com', 'chamar', 'no', 'na', 'e', 'ou', 'pelo',
                 'pela', 'meu', 'minha', 'o', 'a', 'de', 'do', 'da', 'para'}


def gerar_titulo(texto, telefone=''):
    """Monta um titulo curto a partir do inicio da mensagem.

    A estrategia e deliberadamente simples: tirar o telefone, cortar na
    primeira quebra de linha ou pontuacao final, limitar o numero de palavras,
    descartar as palavras de ligacao que sobram na ponta e colocar a primeira
    letra em maiuscula. Nao ha tentativa de reescrever ou corrigir o texto.

    O motivo de nao tentar mais: o titulo vai aparecer na fila de moderacao
    dentro de um campo editavel. Um titulo literal e previsivel, facil de
    corrigir e nunca inventa informacao que o morador nao escreveu - que e o
    risco real de qualquer reescrita automatica.
    """
    limpo = texto
    if telefone:
        limpo = limpo.replace(telefone, ' ')

    # Fica so com o primeiro trecho: ate a quebra de linha ou o fim da frase.
    limpo = re.split(r'[\n\r]|(?<=[.!?])\s', limpo.strip(), maxsplit=1)[0]

    palavras = limpo.split()[:PALAVRAS_NO_TITULO]

    # Remove da direita para a esquerda enquanto a ultima palavra for ligacao.
    while palavras and normalizar(palavras[-1]).strip(',;:-.') in SOBRAS_NO_FIM:
        palavras.pop()

    titulo = ' '.join(palavras).strip(' ,;:-')

    if not titulo:
        return 'Mensagem recebida'

    titulo = titulo[0].upper() + titulo[1:]
    return titulo[:LIMITE_TITULO]


# ---------------------------------------------------------------------------
# Ponto de entrada
# ---------------------------------------------------------------------------


def interpretar(texto):
    """Interpreta a mensagem e devolve a sugestao de post.

    Chaves devolvidas:
      categoria   - uma das categorias do model, ou None quando nao houve
                    confianca suficiente
      titulo      - titulo sugerido, sempre preenchido
      descricao   - o texto original, sem alteracao
      telefone    - telefone encontrado, ou string vazia
      pontuacao   - pontuacao da categoria escolhida
      confiavel   - True quando ha categoria; serve para o chamador decidir se
                    preenche o rascunho ou deixa a mensagem para triagem manual
      detalhe     - pontuacao de todas as categorias, para inspecao

    A descricao devolve o texto original de proposito. O que o morador escreveu
    e o registro do que ele quis dizer; qualquer limpeza automatica pode mudar
    o sentido, e o moderador tem o campo aberto para editar se precisar.
    """
    texto = (texto or '').strip()

    telefone = extrair_telefone(texto)
    categoria, pontuacao = escolher_categoria(texto)

    return {
        'categoria': categoria,
        'titulo': gerar_titulo(texto, telefone),
        'descricao': texto,
        'telefone': telefone,
        'pontuacao': pontuacao,
        'confiavel': categoria is not None,
        'detalhe': pontuar_categorias(texto),
    }
