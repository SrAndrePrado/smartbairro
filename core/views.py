from django.http import HttpResponse
from .models import Tarefa

def home(request):
    tarefas = Tarefa.objects.all()

    texto = ""
    for tarefa in tarefas:
        texto += f"{tarefa.titulo} - {tarefa.descricao}<br>"

    return HttpResponse(texto)
# Create your views here.
