from django.db import models
from django.contrib.auth.models import User   # 👈 IMPORTANTE

class Post(models.Model):
    CATEGORIAS = [
        ('servico', 'Serviços'),
        ('venda', 'Vendas'),
        ('doacao', 'Doações'),
        ('aviso', 'Avisos'),
    ]

    titulo = models.CharField(max_length=100)
    descricao = models.TextField()
    categoria = models.CharField(max_length=20, choices=CATEGORIAS)
    data_criacao = models.DateTimeField(auto_now_add=True)

    usuario = models.ForeignKey(User, on_delete=models.CASCADE)  

    imagem = models.ImageField(upload_to='posts/', null=True, blank=True)

    def __str__(self):
        return self.titulo