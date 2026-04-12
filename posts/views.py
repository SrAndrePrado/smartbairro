from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from .models import Post
from django.core.paginator import Paginator


def home(request):
    categoria = request.GET.get('categoria')
    busca = request.GET.get('busca')

    posts = Post.objects.all()

    if categoria:
        posts = posts.filter(categoria=categoria)

    if busca:
        posts = posts.filter(
            Q(titulo__icontains=busca) |
            Q(descricao__icontains=busca)
        )

    paginator = Paginator(posts, 6)

    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'posts/home.html', {'page_obj': page_obj})


@login_required
def criar_post(request):
    if request.method == 'POST':
        titulo = request.POST.get('titulo')
        descricao = request.POST.get('descricao')
        categoria = request.POST.get('categoria')
        imagem = request.FILES.get('imagem')

        Post.objects.create(
            titulo=titulo,
            descricao=descricao,
            categoria=categoria,
            usuario=request.user,
            imagem=imagem
        )

        return redirect('/')

    return render(request, 'posts/criar_post.html')


def detalhe_post(request, post_id):
    post = get_object_or_404(Post, id=post_id)
    return render(request, 'posts/detalhe_post.html', {'post': post})


@login_required
def editar_post(request, post_id):
    post = get_object_or_404(Post, id=post_id)

    if post.usuario != request.user:
        return redirect('/')

    if request.method == 'POST':
        post.titulo = request.POST.get('titulo')
        post.descricao = request.POST.get('descricao')
        post.categoria = request.POST.get('categoria')
        post.save()

        return redirect('/')

    return render(request, 'posts/editar_post.html', {'post': post})


@login_required
def deletar_post(request, post_id):
    post = get_object_or_404(Post, id=post_id)

    if post.usuario != request.user:
        return redirect('/')

    post.delete()
    return redirect('/')


def cadastro(request):
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect('/')
    else:
        form = UserCreationForm()

    return render(request, 'posts/cadastro.html', {'form': form})

# Create your views here.
