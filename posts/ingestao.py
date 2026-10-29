"""Transforma mensagens recebidas em rascunhos de post.

Esta camada fica entre a interpretacao do texto e o banco de dados. A divisao
e proposital e tem tres niveis:

    classificacao.py  - logica pura, sem Django: texto entra, dicionario sai
    ingestao.py       - este arquivo: usa a interpretacao e grava no banco
    admin.py / comando - pontos de entrada que um humano aciona

Separar assim permite testar a interpretacao sem banco, trocar a estrategia de
classificacao sem mexer na gravacao, e acionar a mesma rotina tanto pelo painel
quanto por linha de comando sem duplicar codigo.
"""

from django.contrib.auth.models import User
from django.db import transaction
from django.utils import timezone

from . import classificacao
from .privacidade import POLITICA_VERSAO
from .models import Post, MensagemRecebida, Consentimento

# Nome do usuario que figura como autor dos posts nascidos de mensagens.
#
# O campo usuario do model Post e obrigatorio, e quem enviou a mensagem pelo
# WhatsApp nao tem conta no site. Criar uma conta por remetente seria pior sob
# a LGPD: transformaria um numero de telefone em cadastro permanente. A saida e
# um unico usuario institucional, com o remetente real preservado na mensagem
# vinculada, acessivel apenas a quem tem acesso ao painel.
USUARIO_SISTEMA = 'mural'


def obter_usuario_sistema():
    """Devolve o usuario institucional, criando-o na primeira chamada.

    A conta nasce inativa e com senha inutilizavel: ela existe para constar
    como autor, nunca para alguem entrar com ela. O Django recusa autenticacao
    de usuario inativo, entao mesmo que a senha vazasse nao haveria acesso.
    """
    usuario, criado = User.objects.get_or_create(
        username=USUARIO_SISTEMA,
        defaults={'first_name': 'Mural', 'is_active': False},
    )
    if criado:
        usuario.set_unusable_password()
        usuario.save(update_fields=['password'])
    return usuario


# Motivos devolvidos por processar_mensagem, para o chamador montar o resumo.
CRIADO = 'criado'
SEM_CONFIANCA = 'sem_confianca'
SEM_CONSENTIMENTO = 'sem_consentimento'
JA_PROCESSADA = 'ja_processada'


def registrar_consentimento(canal, remetente):
    """Grava o consentimento do remetente, ou reativa um que fora revogado.

    Devolve o registro. A versao da politica vigente fica gravada junto: sem
    ela nao seria possivel dizer com que texto a pessoa concordou.
    """
    registro, criado = Consentimento.objects.get_or_create(
        canal=canal,
        remetente=remetente,
        defaults={'politica_versao': POLITICA_VERSAO},
    )
    if not criado and registro.revogado_em is not None:
        # Quem revogou e voltou a consentir recomeca sob a politica atual.
        registro.revogado_em = None
        registro.politica_versao = POLITICA_VERSAO
        registro.save(update_fields=['revogado_em', 'politica_versao'])
    return registro


def tem_consentimento(canal, remetente):
    """Diz se ha consentimento ativo para aquele remetente naquele canal."""
    return Consentimento.objects.filter(
        canal=canal, remetente=remetente, revogado_em__isnull=True
    ).exists()


def processar_mensagem(mensagem, forcar=False):
    """Interpreta uma mensagem e cria o rascunho correspondente.

    Devolve a dupla (post, motivo). O post e None quando nada foi criado.

    Nada e publicado aqui: o post nasce com status 'rascunho' e so aparece no
    mural depois que alguem o aprovar no painel. A classificacao automatica
    substitui a digitacao, nao a decisao de publicar.
    """
    if mensagem.post_id and not forcar:
        return None, JA_PROCESSADA

    # Receber uma mensagem e guarda-la e uma coisa; publicar o conteudo dela e
    # outra. A segunda depende de consentimento do titular, verificado aqui e
    # nao na recepcao: a mensagem precisa ser gravada de qualquer forma, nem
    # que seja para registrar que chegou sem autorizacao de uso.
    if not tem_consentimento(mensagem.canal, mensagem.remetente):
        mensagem.erro = (
            'Sem consentimento ativo registrado para este remetente. '
            'O conteudo nao pode ser publicado (Lei 13.709/2018, art. 7, I).'
        )
        mensagem.save(update_fields=['erro'])
        return None, SEM_CONSENTIMENTO

    sugestao = classificacao.interpretar(mensagem.texto)

    if not sugestao['confiavel']:
        # A mensagem continua pendente de proposito. O campo erro guarda o
        # diagnostico da ultima tentativa, para o moderador distinguir "ainda
        # nao foi analisada" de "foi analisada e o sistema nao soube decidir".
        mensagem.erro = (
            'Classificacao automatica sem confianca suficiente '
            f'(pontuacao {sugestao["pontuacao"]}). Requer triagem manual.'
        )
        mensagem.save(update_fields=['erro'])
        return None, SEM_CONFIANCA

    # A transacao garante que nunca exista um post criado sem a mensagem
    # apontando para ele: ou as duas gravacoes acontecem, ou nenhuma.
    with transaction.atomic():
        post = Post.objects.create(
            titulo=sugestao['titulo'],
            descricao=sugestao['descricao'],
            categoria=sugestao['categoria'],
            telefone=sugestao['telefone'],
            usuario=obter_usuario_sistema(),
            status='rascunho',
            origem='mensagem',
        )
        mensagem.post = post
        mensagem.status = 'processada'
        mensagem.erro = ''
        mensagem.save(update_fields=['post', 'status', 'erro'])

    return post, CRIADO


def mensagens_pendentes():
    """Fila de trabalho: pendentes que ainda nao tem post vinculado."""
    return MensagemRecebida.objects.filter(status='pendente', post__isnull=True)


def processar_pendentes(limite=None):
    """Processa as mensagens pendentes que ainda nao geraram post.

    Devolve um dicionario com a contagem de cada desfecho, usado tanto pelo
    comando de linha quanto pela acao do painel para montar o resumo.
    """
    fila = mensagens_pendentes()
    if limite:
        fila = fila[:limite]

    resumo = {CRIADO: 0, SEM_CONFIANCA: 0, SEM_CONSENTIMENTO: 0, JA_PROCESSADA: 0}
    for mensagem in fila:
        _, motivo = processar_mensagem(mensagem)
        resumo[motivo] += 1
    return resumo


# ---------------------------------------------------------------------------
# Direito a eliminacao (Lei 13.709/2018, art. 18, VI)
# ---------------------------------------------------------------------------

# O identificador some, mas a linha do consentimento permanece: ela registra
# que houve revogacao e quando, sem dizer de quem. E o que responde, mais
# tarde, "voces atenderam aquele pedido?".
MARCA_REMOVIDO = '[removido a pedido do titular]'


def esquecer_remetente(canal, remetente, apagar_posts=False):
    """Atende um pedido de eliminacao de dados feito pelo titular.

    O que acontece:
      - o consentimento e revogado e o identificador, anonimizado;
      - as mensagens cruas daquele remetente sao apagadas;
      - o telefone de contato sai dos posts que nasceram delas.

    O que NAO acontece por padrao: apagar os posts. Um anuncio sem telefone e
    sem remetente deixou de identificar alguem, e pode ser conteudo que a
    comunidade ainda usa. Mas o parametro apagar_posts existe porque a decisao
    e do titular, nao nossa - se ele pedir a remocao completa, o pedido manda.

    Fora do alcance desta rotina: comentarios e curtidas feitos por uma CONTA
    do site. Sao outra identidade, com outra base legal, e se apagam pelo
    cadastro do usuario.

    Devolve um resumo com as contagens, para quem chamou relatar ao titular o
    que foi feito.
    """
    mensagens = MensagemRecebida.objects.filter(canal=canal, remetente=remetente)
    ids_de_posts = [m.post_id for m in mensagens if m.post_id]

    resumo = {
        'mensagens_apagadas': 0,
        'posts_anonimizados': 0,
        'posts_apagados': 0,
        'consentimento_revogado': False,
    }

    # Tudo numa transacao: um pedido de exclusao atendido pela metade seria
    # pior do que um nao atendido, porque ninguem saberia o que sobrou.
    with transaction.atomic():
        registro = Consentimento.objects.filter(
            canal=canal, remetente=remetente
        ).first()
        if registro:
            # A marca leva a chave da propria linha porque canal + remetente e
            # unico: sem isso, o segundo pedido de exclusao no mesmo canal
            # colidiria com o primeiro. A chave nao revela nada sobre a pessoa.
            registro.remetente = f'{MARCA_REMOVIDO}#{registro.pk}'[:64]
            registro.revogado_em = timezone.now()
            registro.save(update_fields=['remetente', 'revogado_em'])
            resumo['consentimento_revogado'] = True

        posts = Post.objects.filter(id__in=ids_de_posts)
        if apagar_posts:
            resumo['posts_apagados'] = posts.count()
            posts.delete()
        else:
            resumo['posts_anonimizados'] = posts.update(telefone='')

        resumo['mensagens_apagadas'] = mensagens.count()
        mensagens.delete()

    return resumo


def remetentes_distintos(queryset):
    """Extrai os pares (canal, remetente) unicos de um conjunto de mensagens.

    Usado pela acao do painel: o moderador seleciona mensagens, mas o pedido de
    exclusao e da PESSOA - atender uma mensagem de cada vez deixaria as outras
    daquele mesmo remetente para tras.
    """
    return sorted(set(queryset.values_list('canal', 'remetente')))
