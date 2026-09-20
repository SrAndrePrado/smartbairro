"""Testes das correcoes aplicadas ao SmartBairro.

Cada teste marcado com "REGRESSAO" cobre um bug que existia no entregavel do
PI 1 e que quebrava a aplicacao ou corrompia dados em uso normal.
"""

from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.db import connection

from .models import Post, Curtida, Comentario


class BaseComDados(TestCase):
    def setUp(self):
        self.ana = User.objects.create_user('ana', password='senha-de-teste-123')
        self.bob = User.objects.create_user('bob', password='senha-de-teste-123')
        self.post = Post.objects.create(
            titulo='Guarda-chuva preto',
            descricao='Achei na praca central',
            categoria='achados',
            usuario=self.ana,
            telefone='11999999999',
        )


class TestBusca(BaseComDados):
    """REGRESSAO: qualquer termo de busca derrubava a home com FieldError."""

    def test_busca_por_titulo_funciona(self):
        r = self.client.get('/?busca=guarda')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Guarda-chuva preto')

    def test_busca_por_nome_de_usuario_funciona(self):
        r = self.client.get('/?busca=ana')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Guarda-chuva preto')

    def test_busca_por_telefone_funciona(self):
        r = self.client.get('/?busca=11999')
        self.assertEqual(r.status_code, 200)

    def test_busca_sem_resultado_nao_quebra(self):
        r = self.client.get('/?busca=xyzabc123naoexiste')
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, 'Guarda-chuva preto')


class TestCriacaoDePost(BaseComDados):
    """REGRESSAO: formulario vazio causava IntegrityError (erro 500)."""

    def test_form_vazio_devolve_erro_e_nao_quebra(self):
        self.client.login(username='ana', password='senha-de-teste-123')
        r = self.client.post('/criar/', {})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Post.objects.count(), 1)

    def test_titulo_em_branco_e_rejeitado(self):
        self.client.login(username='ana', password='senha-de-teste-123')
        r = self.client.post('/criar/', {'titulo': '   ', 'descricao': 'x', 'categoria': 'venda'})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Post.objects.count(), 1)

    def test_categoria_invalida_e_rejeitada(self):
        """REGRESSAO: choices nao valida em objects.create(); 'LIXO' era salvo."""
        self.client.login(username='ana', password='senha-de-teste-123')
        r = self.client.post('/criar/', {
            'titulo': 'T', 'descricao': 'D', 'categoria': 'LIXO',
        })
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Post.objects.count(), 1)

    def test_post_valido_e_criado(self):
        self.client.login(username='ana', password='senha-de-teste-123')
        r = self.client.post('/criar/', {
            'titulo': 'Sofa 3 lugares', 'descricao': 'Bom estado',
            'categoria': 'venda', 'telefone': '11988887777',
        })
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Post.objects.count(), 2)
        novo = Post.objects.get(titulo='Sofa 3 lugares')
        self.assertEqual(novo.usuario, self.ana)
        self.assertEqual(novo.categoria, 'venda')


class TestEdicao(BaseComDados):
    """REGRESSAO: editar post de 'achados' trocava a categoria para 'servico'."""

    def test_template_de_edicao_oferece_todas_as_categorias(self):
        self.client.login(username='ana', password='senha-de-teste-123')
        r = self.client.get(f'/editar/{self.post.id}/')
        html = r.content.decode()
        for valor, _ in Post.CATEGORIAS:
            self.assertIn(f'value="{valor}"', html)

    def test_categoria_achados_vem_selecionada(self):
        import re
        self.client.login(username='ana', password='senha-de-teste-123')
        html = self.client.get(f'/editar/{self.post.id}/').content.decode()
        selecionadas = re.findall(r'value="([^"]+)"\s+selected', html)
        self.assertEqual(selecionadas, ['achados'])

    def test_editar_preserva_telefone_e_categoria(self):
        self.client.login(username='ana', password='senha-de-teste-123')
        self.client.post(f'/editar/{self.post.id}/', {
            'titulo': 'Guarda-chuva preto (atualizado)',
            'descricao': 'Achei na praca central',
            'categoria': 'achados',
            'telefone': '11999999999',
        })
        self.post.refresh_from_db()
        self.assertEqual(self.post.categoria, 'achados')
        self.assertEqual(self.post.telefone, '11999999999')

    def test_editar_permite_trocar_telefone(self):
        self.client.login(username='ana', password='senha-de-teste-123')
        self.client.post(f'/editar/{self.post.id}/', {
            'titulo': 'T', 'descricao': 'D', 'categoria': 'achados',
            'telefone': '11777776666',
        })
        self.post.refresh_from_db()
        self.assertEqual(self.post.telefone, '11777776666')

    def test_nao_dono_nao_edita(self):
        self.client.login(username='bob', password='senha-de-teste-123')
        self.client.post(f'/editar/{self.post.id}/', {
            'titulo': 'invadido', 'descricao': 'x', 'categoria': 'venda',
        })
        self.post.refresh_from_db()
        self.assertEqual(self.post.titulo, 'Guarda-chuva preto')


class TestExclusao(BaseComDados):
    """REGRESSAO: um GET simples apagava o post, sem CSRF e sem confirmacao."""

    def test_get_nao_apaga_apenas_pede_confirmacao(self):
        self.client.login(username='ana', password='senha-de-teste-123')
        r = self.client.get(f'/deletar/{self.post.id}/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Tem certeza')
        self.assertEqual(Post.objects.count(), 1)

    def test_post_apaga(self):
        self.client.login(username='ana', password='senha-de-teste-123')
        r = self.client.post(f'/deletar/{self.post.id}/')
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Post.objects.count(), 0)

    def test_nao_dono_nao_apaga(self):
        self.client.login(username='bob', password='senha-de-teste-123')
        self.client.post(f'/deletar/{self.post.id}/')
        self.assertEqual(Post.objects.count(), 1)


class TestLoginRequired(BaseComDados):
    """REGRESSAO: sem LOGIN_URL, usuario deslogado caia em /accounts/login/ (404)."""

    def test_redirect_de_criar_leva_a_pagina_de_login_existente(self):
        r = self.client.get('/criar/')
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.url.startswith('/login/'), f'redirecionou para {r.url}')
        self.assertEqual(self.client.get(r.url).status_code, 200)

    def test_anonimo_nao_curte(self):
        r = self.client.post(f'/curtir/{self.post.id}/')
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Curtida.objects.count(), 0)


class TestCurtida(BaseComDados):
    def test_toggle(self):
        self.client.login(username='bob', password='senha-de-teste-123')
        self.client.post(f'/curtir/{self.post.id}/')
        self.assertEqual(Curtida.objects.count(), 1)
        self.client.post(f'/curtir/{self.post.id}/')
        self.assertEqual(Curtida.objects.count(), 0)

    def test_get_nao_curte(self):
        self.client.login(username='bob', password='senha-de-teste-123')
        self.client.get(f'/curtir/{self.post.id}/')
        self.assertEqual(Curtida.objects.count(), 0)

    def test_banco_impede_curtida_duplicada(self):
        Curtida.objects.create(usuario=self.bob, post=self.post)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Curtida.objects.create(usuario=self.bob, post=self.post)


class TestComentario(BaseComDados):
    def test_comentario_vazio_nao_e_criado(self):
        self.client.login(username='bob', password='senha-de-teste-123')
        self.client.post(f'/comentar/{self.post.id}/', {'texto': '   '})
        self.assertEqual(Comentario.objects.count(), 0)

    def test_comentario_valido_e_criado(self):
        self.client.login(username='bob', password='senha-de-teste-123')
        self.client.post(f'/comentar/{self.post.id}/', {'texto': 'E meu!'})
        self.assertEqual(Comentario.objects.count(), 1)


class TestDesempenho(BaseComDados):
    """A home fazia uma consulta por card para usuario e contagem de curtidas."""

    def test_home_nao_multiplica_consultas_por_post(self):
        for i in range(6):
            Post.objects.create(
                titulo=f'Post {i}', descricao='d', categoria='venda', usuario=self.bob,
            )
        with CaptureQueriesContext(connection) as ctx:
            self.client.get('/')
        self.assertLess(
            len(ctx.captured_queries), 8,
            f'A home disparou {len(ctx.captured_queries)} consultas.',
        )


class TestSegredosNoRepositorio(TestCase):
    def test_template_de_login_nao_contem_credenciais(self):
        from pathlib import Path
        from django.conf import settings
        caminho = Path(settings.BASE_DIR) / 'posts/templates/posts/login.html'
        conteudo = caminho.read_text(encoding='utf-8').lower()
        for proibido in ('senha:', 'admin_teste', 'user_teste'):
            self.assertNotIn(proibido, conteudo)
