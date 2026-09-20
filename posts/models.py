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

    titulo = models.CharField(max_length=100)
    descricao = models.TextField()
    categoria = models.CharField(max_length=20, choices=CATEGORIAS)
    data_criacao = models.DateTimeField(auto_now_add=True)
    usuario = models.ForeignKey(User, on_delete=models.CASCADE)
    imagem = models.ImageField(upload_to='posts/', null=True, blank=True)
    telefone = models.CharField(max_length=20, blank=True, null=True)

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
    
    