from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Count
from .models import Post, Curtida, Comentario
from django.core.paginator import Paginator


# Categorias validas, derivadas do proprio model para nao duplicar a lista.
CATEGORIAS_VALIDAS = [c[0] for c in Post.CATEGORIAS]


def home(request):
    categoria = request.GET.get('categoria')
    busca = request.GET.get('busca')

    # select_related evita uma consulta extra por post para buscar o usuario e
    # annotate calcula as curtidas no banco, em vez de uma consulta por card.
    # A ordenacao explicita e necessaria porque o annotate agrupa a consulta e
    # descarta a ordenacao padrao do model, o que torna a paginacao instavel.
    posts = Post.objects.select_related('usuario').annotate(
        total_curtidas=Count('curtida', distinct=True)
    ).order_by('-data_criacao')

    if categoria:
        posts = posts.filter(categoria=categoria)

    if busca:
        posts = posts.filter(
            Q(titulo__icontains=busca) |
            Q(descricao__icontains=busca) |
            Q(usuario__username__icontains=busca) |
            Q(telefone__icontains=busca)
        )

    curtidas_usuario = []
    if request.user.is_authenticated:
        curtidas_usuario = list(
            Curtida.objects.filter(usuario=request.user).values_list('post_id', flat=True)
        )

    paginator = Paginator(posts, 6)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'posts/home.html', {
        'page_obj': page_obj,
        'curtidas_usuario': curtidas_usuario,
        'categorias': Post.CATEGORIAS,
    })


@login_required
def criar_post(request):
    if request.method == 'POST':
        titulo = (request.POST.get('titulo') or '').strip()
        descricao = (request.POST.get('descricao') or '').strip()
        categoria = (request.POST.get('categoria') or '').strip()
        imagem = request.FILES.get('imagem')
        telefone = (request.POST.get('telefone') or '').strip()

        erros = []
        if not titulo:
            erros.append('Informe um titulo para o post.')
        if not descricao:
            erros.append('Informe uma descricao para o post.')
        if categoria not in CATEGORIAS_VALIDAS:
            erros.append('Escolha uma categoria valida.')

        if erros:
            return render(request, 'posts/criar_post.html', {
                'erros': erros,
                'categorias': Post.CATEGORIAS,
                'valores': {
                    'titulo': titulo,
                    'descricao': descricao,
                    'categoria': categoria,
                    'telefone': telefone,
                },
            }, status=400)

        Post.objects.create(
            titulo=titulo,
            descricao=descricao,
            categoria=categoria,
            usuario=request.user,
            imagem=imagem,
            telefone=telefone,
        )

        return redirect('/')

    return render(request, 'posts/criar_post.html', {
        'categorias': Post.CATEGORIAS,
    })


def detalhe_post(request, post_id):
    post = get_object_or_404(Post.objects.select_related('usuario'), id=post_id)
    curtidas = Curtida.objects.filter(post=post).select_related('usuario')
    comentarios = Comentario.objects.filter(post=post).select_related('usuario')
    return render(request, 'posts/detalhe_post.html', {
        'post': post,
        'curtidas': curtidas,
        'comentarios': comentarios,
    })


@login_required
def editar_post(request, post_id):
    post = get_object_or_404(Post, id=post_id)

    if post.usuario != request.user:
        return redirect('/')

    if request.method == 'POST':
        titulo = (request.POST.get('titulo') or '').strip()
        descricao = (request.POST.get('descricao') or '').strip()
        categoria = (request.POST.get('categoria') or '').strip()
        telefone = (request.POST.get('telefone') or '').strip()

        erros = []
        if not titulo:
            erros.append('Informe um titulo para o post.')
        if not descricao:
            erros.append('Informe uma descricao para o post.')
        if categoria not in CATEGORIAS_VALIDAS:
            erros.append('Escolha uma categoria valida.')

        if erros:
            return render(request, 'posts/editar_post.html', {
                'post': post,
                'erros': erros,
                'categorias': Post.CATEGORIAS,
            }, status=400)

        post.titulo = titulo
        post.descricao = descricao
        post.categoria = categoria
        post.telefone = telefone

        nova_imagem = request.FILES.get('imagem')
        if nova_imagem:
            post.imagem = nova_imagem

        post.save()

        return redirect('/')

    return render(request, 'posts/editar_post.html', {
        'post': post,
        'categorias': Post.CATEGORIAS,
    })


@login_required
def deletar_post(request, post_id):
    post = get_object_or_404(Post, id=post_id)

    if post.usuario != request.user:
        return redirect('/')

    # Apagar so acontece via POST, protegido por CSRF. Um GET apenas exibe a
    # tela de confirmacao, para que nenhum link ou pre-carregamento do
    # navegador consiga remover um post sem a acao explicita do dono.
    if request.method == 'POST':
        post.delete()
        return redirect('/')

    return render(request, 'posts/confirmar_delete.html', {'post': post})


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


@login_required
def curtir_post(request, post_id):
    post = get_object_or_404(Post, id=post_id)

    if request.method != 'POST':
        return redirect(f'/post/{post_id}/')

    # evita duplicar curtida
    curtida, created = Curtida.objects.get_or_create(
        usuario=request.user,
        post=post,
    )

    # se ja existia, remove (toggle)
    if not created:
        curtida.delete()

    return redirect(f'/#post-{post_id}')


@login_required
def comentar_post(request, post_id):
    post = get_object_or_404(Post, id=post_id)

    if request.method == 'POST':
        texto = (request.POST.get('texto') or '').strip()

        if texto:
            Comentario.objects.create(
                usuario=request.user,
                post=post,
                texto=texto,
            )

    return redirect(f'/post/{post_id}/#comentarios')
