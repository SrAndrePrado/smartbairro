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
