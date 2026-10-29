from django.db import models
from django.contrib.auth.models import User   # IMPORTANTE

class Post(models.Model):
    CATEGORIAS = [
        ('servico', 'Serviços'),
        ('venda', 'Vendas'),
        ('doacao', 'Doações & Desapego'),
        ('aviso', 'Avisos'),
        ('achados', 'Achados e Perdidos'),
    ]

    # Um post criado a partir de uma mensagem recebida nasce como rascunho e
    # so aparece no mural depois de aprovado. Posts criados pelo formulario do
    # site continuam sendo publicados diretamente.
    STATUS = [
        ('rascunho', 'Rascunho'),
        ('publicado', 'Publicado'),
    ]

    ORIGENS = [
        ('site', 'Formulário do site'),
        ('mensagem', 'Mensagem recebida'),
    ]

    titulo = models.CharField(max_length=100)
    descricao = models.TextField()
    categoria = models.CharField(max_length=20, choices=CATEGORIAS)
    data_criacao = models.DateTimeField(auto_now_add=True)
    usuario = models.ForeignKey(User, on_delete=models.CASCADE)
    imagem = models.ImageField(upload_to='posts/', null=True, blank=True)
    telefone = models.CharField(max_length=20, blank=True, null=True)
    status = models.CharField(max_length=10, choices=STATUS, default='publicado')
    origem = models.CharField(max_length=10, choices=ORIGENS, default='site')

    class Meta:
        ordering = ['-data_criacao']

    def __str__(self):
        return self.titulo


class Curtida(models.Model):
    usuario = models.ForeignKey(User, on_delete=models.CASCADE)
    post = models.ForeignKey(Post, on_delete=models.CASCADE)

    class Meta:
        # Garante no banco o que a view ja tentava garantir com get_or_create.
        constraints = [
            models.UniqueConstraint(
                fields=['usuario', 'post'],
                name='curtida_unica_por_usuario_e_post',
            )
        ]

    def __str__(self):
        return f"{self.usuario} curtiu {self.post}"


class Comentario(models.Model):
    usuario = models.ForeignKey(User, on_delete=models.CASCADE)
    post = models.ForeignKey(Post, on_delete=models.CASCADE)
    texto = models.TextField()
    data_criacao = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['data_criacao']

    def __str__(self):
        return f"{self.usuario} comentou"
    
    

class MensagemRecebida(models.Model):
    """Mensagem crua recebida de um canal de mensageria, antes de virar post.

    Guardar a mensagem original separada do post tem tres motivos: permite
    reprocessar se a interpretacao melhorar, deixa rastro do que o morador
    realmente escreveu, e e a base de dados para treinar a classificacao
    automatica mais adiante.

    O campo remetente guarda um identificador pessoal do morador e, por isso,
    esta sujeito as regras de retencao e exclusao definidas para o projeto.
    """

    CANAIS = [
        ('whatsapp', 'WhatsApp'),
        ('telegram', 'Telegram'),
        ('teste', 'Teste'),
    ]

    STATUS = [
        ('pendente', 'Pendente'),
        ('processada', 'Processada'),
        ('descartada', 'Descartada'),
        ('erro', 'Erro'),
    ]

    canal = models.CharField(max_length=20, choices=CANAIS)
    remetente = models.CharField(max_length=64)
    texto = models.TextField()
    # Identificador da mensagem no canal de origem. Serve para nao gravar duas
    # vezes a mesma mensagem quando o servico reenvia o webhook.
    id_externo = models.CharField(max_length=128, blank=True)
    recebida_em = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=12, choices=STATUS, default='pendente')
    erro = models.TextField(blank=True)
    post = models.ForeignKey(
        Post,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='mensagens',
    )

    class Meta:
        ordering = ['-recebida_em']
        verbose_name = 'mensagem recebida'
        verbose_name_plural = 'mensagens recebidas'
        constraints = [
            models.UniqueConstraint(
                fields=['canal', 'id_externo'],
                condition=~models.Q(id_externo=''),
                name='mensagem_unica_por_canal_e_id_externo',
            )
        ]

    def __str__(self):
        return f"{self.get_canal_display()} - {self.texto[:40]}"


class EventoDeUso(models.Model):
    """Registro pseudonimizado de uma pagina vista.

    Guarda o necessario para responder tres perguntas: quais paginas e
    categorias sao mais procuradas, o que a comunidade busca, e em que ponto as
    visitas se interrompem.

    Nao guarda endereco de origem nem vinculo com a conta. O campo visita e um
    numero sorteado, que permite ordenar as paginas de uma mesma sessao sem
    identificar quem navegou. Ver posts/telemetria.py para o detalhe de por que
    o tratamento e descrito como pseudonimizado, e nao como anonimo.
    """

    visita = models.CharField(max_length=32, db_index=True)
    caminho = models.CharField(max_length=200)
    ocorrido_em = models.DateTimeField(auto_now_add=True, db_index=True)
    autenticado = models.BooleanField(default=False)
    categoria = models.CharField(max_length=20, blank=True)
    busca = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ['-ocorrido_em']
        verbose_name = 'evento de uso'
        verbose_name_plural = 'eventos de uso'

    def __str__(self):
        return f'{self.ocorrido_em:%d/%m %H:%M} {self.caminho}'


class Consentimento(models.Model):
    """Registro de que um remetente autorizou a publicacao das suas mensagens.

    O consentimento pertence a PESSOA, nao a mensagem. Quem envia pelo canal
    externo concorda uma vez, no primeiro contato, e aquilo vale para os envios
    seguintes ate ser revogado. Guardar um registro por mensagem repetiria o
    mesmo dado e tornaria a revogacao trabalhosa, porque seria preciso varrer
    todas as mensagens em vez de desligar um unico registro.

    O campo politica_versao existe porque o texto do aviso de privacidade pode
    mudar. Sem ele, seria impossivel dizer com o que cada pessoa concordou de
    fato - o que esvazia o proprio registro.

    A revogacao nao apaga a linha: marca a data em revogado_em. Isso preserva a
    prova de que houve consentimento durante determinado periodo, que e o que
    responde a pergunta "com que base voces publicaram aquilo em setembro?".
    """

    canal = models.CharField(max_length=20, choices=MensagemRecebida.CANAIS)
    remetente = models.CharField(max_length=64)
    concedido_em = models.DateTimeField(auto_now_add=True)
    politica_versao = models.CharField(max_length=20)
    revogado_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-concedido_em']
        verbose_name = 'consentimento'
        verbose_name_plural = 'consentimentos'
        constraints = [
            models.UniqueConstraint(
                fields=['canal', 'remetente'],
                name='consentimento_unico_por_canal_e_remetente',
            )
        ]

    def __str__(self):
        situacao = 'revogado' if self.revogado_em else 'ativo'
        return f'{self.get_canal_display()} {self.remetente} ({situacao})'

    @property
    def ativo(self):
        return self.revogado_em is None
