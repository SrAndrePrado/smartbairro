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

from . import classificacao
from .models import Post, MensagemRecebida

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
JA_PROCESSADA = 'ja_processada'


def processar_mensagem(mensagem, forcar=False):
    """Interpreta uma mensagem e cria o rascunho correspondente.

    Devolve a dupla (post, motivo). O post e None quando nada foi criado.

    Nada e publicado aqui: o post nasce com status 'rascunho' e so aparece no
    mural depois que alguem o aprovar no painel. A classificacao automatica
    substitui a digitacao, nao a decisao de publicar.
    """
    if mensagem.post_id and not forcar:
        return None, JA_PROCESSADA

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

    resumo = {CRIADO: 0, SEM_CONFIANCA: 0, JA_PROCESSADA: 0}
    for mensagem in fila:
        _, motivo = processar_mensagem(mensagem)
        resumo[motivo] += 1
    return resumo
