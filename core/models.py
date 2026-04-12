from django.db import models

class Tarefa(models.Model):
    titulo = models.CharField(max_length=100)
    descricao = models.TextField()
    concluida = models.BooleanField(default=False)

    def __str__(self):
        return self.titulo

# Create your models here.
