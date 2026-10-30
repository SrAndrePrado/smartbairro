"""Testes das correcoes aplicadas ao SmartBairro.

Cada teste marcado com "REGRESSAO" cobre um bug que existia no entregavel do
PI 1 e que quebrava a aplicacao ou corrompia dados em uso normal.
"""

import logging
import re
from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase, SimpleTestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from django.db import connection

from .models import (Post, Curtida, Comentario, MensagemRecebida,
                     EventoDeUso, Consentimento)
from . import classificacao, ingestao, privacidade


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


# ===========================================================================
# Camada de ingestao de mensagens
# ===========================================================================

import json

from django.test import override_settings


TOKEN = 'token-de-teste-123'


@override_settings(INGESTAO_TOKEN=TOKEN)
class TestIngestao(TestCase):
    url = '/api/ingestao/'

    def enviar(self, corpo, token=TOKEN, cru=False):
        return self.client.post(
            self.url,
            data=corpo if cru else json.dumps(corpo),
            content_type='application/json',
            headers={'x-ingestao-token': token} if token is not None else {},
        )

    # --- autenticacao ---

    def test_get_nao_e_aceito(self):
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 405)

    def test_sem_token_e_recusado(self):
        r = self.enviar({'canal': 'teste', 'remetente': '11999', 'texto': 'oi'}, token=None)
        self.assertEqual(r.status_code, 401)
        self.assertEqual(MensagemRecebida.objects.count(), 0)

    def test_token_errado_e_recusado(self):
        r = self.enviar({'canal': 'teste', 'remetente': '11999', 'texto': 'oi'}, token='errado')
        self.assertEqual(r.status_code, 401)
        self.assertEqual(MensagemRecebida.objects.count(), 0)

    # --- validacao do conteudo ---

    def test_json_invalido(self):
        r = self.enviar('isso nao e json', cru=True)
        self.assertEqual(r.status_code, 400)

    def test_canal_invalido(self):
        r = self.enviar({'canal': 'pombo', 'remetente': '11999', 'texto': 'oi'})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(MensagemRecebida.objects.count(), 0)

    def test_texto_vazio(self):
        r = self.enviar({'canal': 'teste', 'remetente': '11999', 'texto': '   '})
        self.assertEqual(r.status_code, 400)

    def test_remetente_vazio(self):
        r = self.enviar({'canal': 'teste', 'remetente': '', 'texto': 'oi'})
        self.assertEqual(r.status_code, 400)

    # --- gravacao ---

    def test_mensagem_valida_e_gravada(self):
        r = self.enviar({
            'canal': 'whatsapp',
            'remetente': '5511999998888',
            'texto': 'vendo sofa 3 lugares 200 reais',
        })
        self.assertEqual(r.status_code, 201)
        corpo = r.json()
        self.assertTrue(corpo['ok'])
        self.assertFalse(corpo['duplicada'])

        self.assertEqual(MensagemRecebida.objects.count(), 1)
        m = MensagemRecebida.objects.get()
        self.assertEqual(m.canal, 'whatsapp')
        self.assertEqual(m.texto, 'vendo sofa 3 lugares 200 reais')
        self.assertEqual(m.status, 'pendente')
        self.assertIsNone(m.post)

    def test_reenvio_com_mesmo_id_externo_nao_duplica(self):
        corpo = {
            'canal': 'whatsapp', 'remetente': '5511999998888',
            'texto': 'achei um guarda-chuva', 'id_externo': 'wamid.ABC123',
        }
        primeira = self.enviar(corpo)
        segunda = self.enviar(corpo)

        self.assertEqual(primeira.status_code, 201)
        self.assertEqual(segunda.status_code, 200)
        self.assertTrue(segunda.json()['duplicada'])
        self.assertEqual(segunda.json()['id'], primeira.json()['id'])
        self.assertEqual(MensagemRecebida.objects.count(), 1)

    def test_mensagens_sem_id_externo_nao_colidem(self):
        self.enviar({'canal': 'teste', 'remetente': 'a', 'texto': 'primeira'})
        self.enviar({'canal': 'teste', 'remetente': 'b', 'texto': 'segunda'})
        self.assertEqual(MensagemRecebida.objects.count(), 2)


class TestRascunhoNaoAparece(BaseComDados):
    """Post em rascunho fica fora do mural ate ser aprovado."""

    def test_publicado_aparece(self):
        r = self.client.get('/')
        self.assertContains(r, 'Guarda-chuva preto')

    def test_rascunho_nao_aparece(self):
        self.post.status = 'rascunho'
        self.post.save()
        r = self.client.get('/')
        self.assertNotContains(r, 'Guarda-chuva preto')

    def test_post_do_site_nasce_publicado(self):
        self.client.login(username='ana', password='senha-de-teste-123')
        self.client.post('/criar/', {
            'titulo': 'Bicicleta', 'descricao': 'Aro 26', 'categoria': 'venda',
        })
        novo = Post.objects.get(titulo='Bicicleta')
        self.assertEqual(novo.status, 'publicado')
        self.assertEqual(novo.origem, 'site')


# ===========================================================================
# Endpoints JSON usados pelo JavaScript
# ===========================================================================

class TestApiCurtir(BaseComDados):
    def url(self):
        return f'/api/curtir/{self.post.id}/'

    def test_anonimo_recebe_401_em_json(self):
        r = self.client.post(self.url())
        self.assertEqual(r.status_code, 401)
        self.assertFalse(r.json()['ok'])
        self.assertEqual(Curtida.objects.count(), 0)

    def test_get_nao_e_aceito(self):
        self.client.login(username='bob', password='senha-de-teste-123')
        self.assertEqual(self.client.get(self.url()).status_code, 405)

    def test_curtir_e_descurtir_devolvendo_total(self):
        self.client.login(username='bob', password='senha-de-teste-123')

        r1 = self.client.post(self.url())
        self.assertEqual(r1.status_code, 200)
        self.assertTrue(r1.json()['curtido'])
        self.assertEqual(r1.json()['total'], 1)

        r2 = self.client.post(self.url())
        self.assertFalse(r2.json()['curtido'])
        self.assertEqual(r2.json()['total'], 0)
        self.assertEqual(Curtida.objects.count(), 0)

    def test_nao_curte_post_em_rascunho(self):
        self.post.status = 'rascunho'
        self.post.save()
        self.client.login(username='bob', password='senha-de-teste-123')
        self.assertEqual(self.client.post(self.url()).status_code, 404)


class TestApiComentar(BaseComDados):
    def url(self):
        return f'/api/comentar/{self.post.id}/'

    def test_anonimo_recebe_401_em_json(self):
        r = self.client.post(self.url(), {'texto': 'oi'})
        self.assertEqual(r.status_code, 401)
        self.assertEqual(Comentario.objects.count(), 0)

    def test_texto_vazio_devolve_400_com_mensagem(self):
        self.client.login(username='bob', password='senha-de-teste-123')
        r = self.client.post(self.url(), {'texto': '   '})
        self.assertEqual(r.status_code, 400)
        self.assertIn('erro', r.json())
        self.assertEqual(Comentario.objects.count(), 0)

    def test_comentario_valido_devolve_o_comentario(self):
        self.client.login(username='bob', password='senha-de-teste-123')
        r = self.client.post(self.url(), {'texto': 'Ainda esta disponivel?'})
        self.assertEqual(r.status_code, 201)
        corpo = r.json()
        self.assertEqual(corpo['comentario']['usuario'], 'bob')
        self.assertEqual(corpo['comentario']['texto'], 'Ainda esta disponivel?')
        self.assertEqual(corpo['total'], 1)
        self.assertEqual(Comentario.objects.count(), 1)


class TestFallbackSemJavaScript(BaseComDados):
    """As rotas antigas continuam funcionando para quem esta sem JavaScript."""

    def test_curtir_pela_rota_tradicional(self):
        self.client.login(username='bob', password='senha-de-teste-123')
        r = self.client.post(f'/curtir/{self.post.id}/')
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Curtida.objects.count(), 1)

    def test_comentar_pela_rota_tradicional(self):
        self.client.login(username='bob', password='senha-de-teste-123')
        r = self.client.post(f'/comentar/{self.post.id}/', {'texto': 'sem js'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Comentario.objects.count(), 1)

    def test_pagina_carrega_o_script(self):
        r = self.client.get('/')
        self.assertContains(r, 'smartbairro.js')

    def test_home_marca_o_formulario_para_o_javascript(self):
        self.client.login(username='ana', password='senha-de-teste-123')
        r = self.client.get('/')
        self.assertContains(r, f'data-curtir="{self.post.id}"')
        self.assertContains(r, 'aria-pressed')

    def test_regiao_de_anuncios_existe(self):
        r = self.client.get('/')
        self.assertContains(r, 'aria-live="polite"')


# ===========================================================================
# Protecoes de seguranca
# ===========================================================================

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile

from . import seguranca


class TestTelefoneProtegido(BaseComDados):
    """O telefone do morador nao aparece para quem nao esta autenticado."""

    def test_visitante_nao_ve_o_telefone(self):
        r = self.client.get('/')
        self.assertNotContains(r, '11999999999')
        self.assertContains(r, 'para ver o contato')

    def test_usuario_logado_ve_o_telefone(self):
        self.client.login(username='bob', password='senha-de-teste-123')
        r = self.client.get('/')
        self.assertContains(r, '11999999999')

    def test_visitante_nao_busca_por_telefone(self):
        r = self.client.get('/?busca=11999')
        self.assertNotContains(r, 'Guarda-chuva preto')

    def test_usuario_logado_busca_por_telefone(self):
        self.client.login(username='bob', password='senha-de-teste-123')
        r = self.client.get('/?busca=11999')
        self.assertContains(r, 'Guarda-chuva preto')


class TestLimiteDeTentativas(BaseComDados):
    def setUp(self):
        super().setUp()
        cache.clear()

    def test_login_bloqueia_apos_muitas_tentativas(self):
        for _ in range(seguranca.LIMITE_LOGIN):
            r = self.client.post('/login/', {'username': 'ana', 'password': 'errada'})
            self.assertNotEqual(r.status_code, 429)

        r = self.client.post('/login/', {'username': 'ana', 'password': 'errada'})
        self.assertEqual(r.status_code, 429)

    def test_bloqueio_vale_mesmo_com_a_senha_certa(self):
        """Impede que o atacante acerte na ultima tentativa e entre."""
        for _ in range(seguranca.LIMITE_LOGIN):
            self.client.post('/login/', {'username': 'ana', 'password': 'errada'})

        r = self.client.post('/login/', {
            'username': 'ana', 'password': 'senha-de-teste-123',
        })
        self.assertEqual(r.status_code, 429)

    def test_ingestao_bloqueia_apos_muitas_requisicoes(self):
        import json
        from django.test import override_settings

        with override_settings(INGESTAO_TOKEN='tok'):
            corpo = json.dumps({'canal': 'teste', 'remetente': 'a', 'texto': 'oi'})
            for _ in range(seguranca.LIMITE_INGESTAO):
                self.client.post('/api/ingestao/', data=corpo,
                                 content_type='application/json',
                                 headers={'x-ingestao-token': 'tok'})

            r = self.client.post('/api/ingestao/', data=corpo,
                                 content_type='application/json',
                                 headers={'x-ingestao-token': 'tok'})
            self.assertEqual(r.status_code, 429)

    def test_limite_conta_por_origem(self):
        from django.test import RequestFactory
        pedido = RequestFactory().get('/')
        pedido.META['HTTP_X_FORWARDED_FOR'] = '203.0.113.9, 10.0.0.1'
        self.assertEqual(seguranca.identificar_origem(pedido), '203.0.113.9')


class TestUploadDeImagem(BaseComDados):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.client.login(username='ana', password='senha-de-teste-123')

    def imagem_valida(self, tamanho=(20, 20)):
        from io import BytesIO
        from PIL import Image

        buffer = BytesIO()
        Image.new('RGB', tamanho, 'blue').save(buffer, format='PNG')
        return SimpleUploadedFile('foto.png', buffer.getvalue(), 'image/png')

    def test_arquivo_que_nao_e_imagem_e_recusado(self):
        falso = SimpleUploadedFile('virus.png', b'isso nao e uma imagem', 'image/png')
        r = self.client.post('/criar/', {
            'titulo': 'T', 'descricao': 'D', 'categoria': 'venda', 'imagem': falso,
        })
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Post.objects.count(), 1)

    def test_imagem_grande_demais_e_recusada(self):
        from posts.views import IMAGEM_MAX_MB
        grande = SimpleUploadedFile(
            'grande.png', b'x' * ((IMAGEM_MAX_MB + 1) * 1024 * 1024), 'image/png',
        )
        r = self.client.post('/criar/', {
            'titulo': 'T', 'descricao': 'D', 'categoria': 'venda', 'imagem': grande,
        })
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Post.objects.count(), 1)

    def test_imagem_valida_e_aceita(self):
        r = self.client.post('/criar/', {
            'titulo': 'Sofa', 'descricao': 'Bom estado',
            'categoria': 'venda', 'imagem': self.imagem_valida(),
        })
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Post.objects.count(), 2)


class TestEnderecoDoAdmin(TestCase):
    def test_admin_responde_no_endereco_configurado(self):
        r = self.client.get('/admin/')
        # Redireciona para o login do admin, o que prova que a rota existe.
        self.assertIn(r.status_code, (200, 302))


# ---------------------------------------------------------------------------
# Interpretacao das mensagens recebidas
# ---------------------------------------------------------------------------
#
# Estes testes usam SimpleTestCase, e nao TestCase: o modulo de classificacao
# nao toca no banco de dados, entao nao ha motivo para o Django criar e
# destruir um banco de teste para cada um. A suite fica mais rapida e o teste
# documenta que aquela logica e independente do framework.


class TestExtracaoDeTelefone(SimpleTestCase):
    def test_encontra_formatos_comuns(self):
        casos = [
            ('Falar com (11) 98888-7777', '(11) 98888-7777'),
            ('zap 11 99999-9999', '11 99999-9999'),
            ('meu numero: 9999-8888', '9999-8888'),
            ('tel (11)98888.7777', '(11)98888.7777'),
            ('ligue 1140028922', '1140028922'),
        ]
        for texto, esperado in casos:
            with self.subTest(texto=texto):
                self.assertEqual(classificacao.extrair_telefone(texto), esperado)

    def test_nao_confunde_preco_com_telefone(self):
        """REGRESSAO: um valor em reais nao pode virar telefone do anunciante.

        Publicar um preco no campo de contato exporia o post como se tivesse
        telefone e deixaria o morador sem forma de ser encontrado.
        """
        self.assertEqual(classificacao.extrair_telefone('vendo por 200 reais'), '')
        self.assertEqual(classificacao.extrair_telefone('R$ 1.200,00 a vista'), '')

    def test_ignora_sequencia_longa_demais(self):
        texto = 'pedido 2024000112233 entregue'
        self.assertEqual(classificacao.extrair_telefone(texto), '')

    def test_sem_telefone_devolve_vazio(self):
        self.assertEqual(classificacao.extrair_telefone('bom dia a todos'), '')


class TestEscolhaDeCategoria(SimpleTestCase):
    def test_classifica_as_cinco_categorias(self):
        casos = [
            ('vendo sofa 3 lugares 200 reais', 'venda'),
            ('Doando sofá bege, retirar no local', 'doacao'),
            ('Faço aulas de reforço de matemática, atendo no bairro', 'servico'),
            ('Encontrei um cachorro caramelo com coleira azul', 'achados'),
            ('AVISO: manutenção da caixa d’água, não haverá água', 'aviso'),
        ]
        for texto, esperado in casos:
            with self.subTest(texto=texto):
                categoria, _ = classificacao.escolher_categoria(texto)
                self.assertEqual(categoria, esperado)

    def test_categorias_sugeridas_existem_no_model(self):
        """Impede que uma categoria inventada aqui quebre a criacao do post."""
        validas = {c[0] for c in Post.CATEGORIAS}
        self.assertEqual(set(classificacao.PISTAS.keys()), validas)

    def test_texto_sem_pista_nao_recebe_categoria(self):
        categoria, pontos = classificacao.escolher_categoria('bom dia pessoal tudo bem?')
        self.assertIsNone(categoria)
        self.assertEqual(pontos, 0)

    def test_empate_entre_categorias_nao_arrisca_palpite(self):
        """Com pistas fortes de duas categorias, a decisao fica com o humano.

        Errar a categoria em silencio e pior do que nao preencher: um post na
        categoria errada desaparece do lugar onde o morador iria procurar.
        """
        texto = 'vendo a geladeira, mas tambem to doando se ninguem quiser comprar'
        categoria, pontos = classificacao.escolher_categoria(texto)
        self.assertIsNone(categoria)
        self.assertGreater(pontos, 0)

    def test_acento_e_caixa_nao_mudam_o_resultado(self):
        a, _ = classificacao.escolher_categoria('DOAÇÃO de roupas')
        b, _ = classificacao.escolher_categoria('doacao de roupas')
        self.assertEqual(a, b)
        self.assertEqual(a, 'doacao')


class TestGeracaoDeTitulo(SimpleTestCase):
    def test_remove_o_telefone_do_titulo(self):
        texto = 'vendo sofa 3 lugares 200 reais zap 11 99999-9999'
        titulo = classificacao.gerar_titulo(texto, '11 99999-9999')
        self.assertNotIn('99999', titulo)

    def test_descarta_palavra_de_ligacao_no_fim(self):
        texto = 'vendo sofa 3 lugares 200 reais zap 11 99999-9999'
        titulo = classificacao.gerar_titulo(texto, '11 99999-9999')
        self.assertFalse(titulo.lower().endswith('zap'))

    def test_respeita_o_limite_do_campo(self):
        texto = 'palavra ' * 200
        titulo = classificacao.gerar_titulo(texto)
        self.assertLessEqual(len(titulo), 100)

    def test_texto_vazio_recebe_titulo_generico(self):
        self.assertEqual(classificacao.gerar_titulo(''), 'Mensagem recebida')

    def test_primeira_letra_em_maiuscula(self):
        self.assertTrue(classificacao.gerar_titulo('vendo bicicleta')[0].isupper())


class TestInterpretacaoCompleta(SimpleTestCase):
    def test_devolve_sugestao_pronta_para_virar_post(self):
        r = classificacao.interpretar(
            'Doando sofá bege em bom estado, retirar no local. Falar com (11) 98888-7777'
        )
        self.assertEqual(r['categoria'], 'doacao')
        self.assertEqual(r['telefone'], '(11) 98888-7777')
        self.assertTrue(r['confiavel'])
        self.assertTrue(r['titulo'])

    def test_descricao_preserva_o_texto_original(self):
        """O que o morador escreveu e o registro do que ele quis dizer."""
        texto = 'vendo   bike    aro 26!!! zap 11 99999-9999'
        self.assertEqual(classificacao.interpretar(texto)['descricao'], texto)

    def test_sem_confianca_sinaliza_para_triagem_manual(self):
        r = classificacao.interpretar('oi gente, alguem sabe que horas abre o mercado?')
        self.assertIsNone(r['categoria'])
        self.assertFalse(r['confiavel'])

    def test_nao_quebra_com_texto_vazio(self):
        r = classificacao.interpretar('')
        self.assertIsNone(r['categoria'])
        self.assertEqual(r['descricao'], '')


# ---------------------------------------------------------------------------
# Criacao de rascunho a partir da mensagem recebida
# ---------------------------------------------------------------------------


class TestProcessamentoDeMensagem(TestCase):
    REMETENTE = '5511999998888'

    def setUp(self):
        # Estes testes exercitam a classificacao, nao o consentimento. Sem o
        # registro, todos parariam em SEM_CONSENTIMENTO antes de chegar na
        # parte que lhes interessa.
        ingestao.registrar_consentimento('teste', self.REMETENTE)

    def nova_mensagem(self, texto, **extra):
        return MensagemRecebida.objects.create(
            canal='teste', remetente=self.REMETENTE, texto=texto, **extra
        )

    def test_mensagem_classificavel_vira_rascunho(self):
        mensagem = self.nova_mensagem('Doando sofá bege, retirar no local')
        post, motivo = ingestao.processar_mensagem(mensagem)

        self.assertEqual(motivo, ingestao.CRIADO)
        self.assertEqual(post.categoria, 'doacao')
        self.assertEqual(post.status, 'rascunho')
        self.assertEqual(post.origem, 'mensagem')

    def test_mensagem_fica_vinculada_ao_post(self):
        """O vinculo e o que permite reprocessar e auditar a origem do post."""
        mensagem = self.nova_mensagem('vendo bicicleta aro 26 por 300 reais')
        post, _ = ingestao.processar_mensagem(mensagem)

        mensagem.refresh_from_db()
        self.assertEqual(mensagem.post_id, post.id)
        self.assertEqual(mensagem.status, 'processada')

    def test_rascunho_gerado_nao_aparece_no_mural(self):
        """REGRESSAO: o recebimento nao pode publicar sozinho.

        E a garantia central do pipeline de moderacao. Se este teste falhar,
        qualquer mensagem enviada ao numero do SmartBairro vai direto ao ar.
        """
        mensagem = self.nova_mensagem('vendo geladeira 500 reais')
        post, _ = ingestao.processar_mensagem(mensagem)

        resposta = self.client.get('/')
        self.assertNotContains(resposta, post.titulo)

    def test_sem_confianca_nao_cria_post_e_mantem_na_fila(self):
        mensagem = self.nova_mensagem('bom dia pessoal, tudo certo por ai?')
        post, motivo = ingestao.processar_mensagem(mensagem)

        self.assertIsNone(post)
        self.assertEqual(motivo, ingestao.SEM_CONFIANCA)

        mensagem.refresh_from_db()
        self.assertEqual(mensagem.status, 'pendente')
        self.assertIsNone(mensagem.post_id)
        self.assertIn('confianca', mensagem.erro.lower())

    def test_nao_duplica_quando_processada_de_novo(self):
        """Clicar duas vezes na acao do painel nao pode gerar dois posts."""
        mensagem = self.nova_mensagem('vendo sofa 200 reais')
        ingestao.processar_mensagem(mensagem)
        mensagem.refresh_from_db()

        post, motivo = ingestao.processar_mensagem(mensagem)
        self.assertIsNone(post)
        self.assertEqual(motivo, ingestao.JA_PROCESSADA)
        self.assertEqual(Post.objects.filter(origem='mensagem').count(), 1)

    def test_telefone_da_mensagem_vai_para_o_campo_de_contato(self):
        mensagem = self.nova_mensagem('vendo mesa 150 reais zap (11) 98888-7777')
        post, _ = ingestao.processar_mensagem(mensagem)
        self.assertEqual(post.telefone, '(11) 98888-7777')
        self.assertNotIn('98888', post.titulo)

    def test_processar_pendentes_percorre_a_fila(self):
        self.nova_mensagem('Doando roupas infantis, retirar no local')
        self.nova_mensagem('vendo armario 400 reais')
        self.nova_mensagem('oi gente, bom dia')

        resumo = ingestao.processar_pendentes()
        self.assertEqual(resumo[ingestao.CRIADO], 2)
        self.assertEqual(resumo[ingestao.SEM_CONFIANCA], 1)


class TestUsuarioDoSistema(TestCase):
    def test_usuario_institucional_nao_consegue_autenticar(self):
        """A conta existe para constar como autor, nunca para alguem entrar.

        Ela nasce inativa e sem senha utilizavel; o Django recusa autenticacao
        de usuario inativo mesmo que a senha estivesse correta.
        """
        usuario = ingestao.obter_usuario_sistema()
        self.assertFalse(usuario.is_active)
        self.assertFalse(usuario.has_usable_password())
        self.assertFalse(self.client.login(username=usuario.username, password=''))

    def test_reaproveita_a_mesma_conta(self):
        primeiro = ingestao.obter_usuario_sistema()
        segundo = ingestao.obter_usuario_sistema()
        self.assertEqual(primeiro.id, segundo.id)
        self.assertEqual(User.objects.filter(username=primeiro.username).count(), 1)


class TestComandoClassificar(TestCase):
    def setUp(self):
        ingestao.registrar_consentimento('teste', '5511999998888')

    def test_comando_cria_rascunhos_das_pendentes(self):
        MensagemRecebida.objects.create(
            canal='teste', remetente='5511999998888',
            texto='Faço aulas de reforço de matemática, atendo no bairro',
        )
        saida = StringIO()
        call_command('classificar_mensagens', stdout=saida)

        self.assertEqual(Post.objects.filter(status='rascunho').count(), 1)
        self.assertIn('rascunho', saida.getvalue().lower())

    def test_simular_nao_grava_nada(self):
        """A simulacao serve para conferir o classificador sem efeito colateral."""
        MensagemRecebida.objects.create(
            canal='teste', remetente='5511999998888',
            texto='vendo bicicleta aro 26 por 300 reais',
        )
        saida = StringIO()
        call_command('classificar_mensagens', '--simular', stdout=saida)

        self.assertEqual(Post.objects.count(), 0)
        self.assertIn('venda', saida.getvalue())

    def test_fila_vazia_nao_quebra(self):
        saida = StringIO()
        call_command('classificar_mensagens', stdout=saida)
        self.assertIn('Nenhuma mensagem pendente', saida.getvalue())

# ---------------------------------------------------------------------------
# Aviso de privacidade
# ---------------------------------------------------------------------------


class TestAvisoDePrivacidade(TestCase):
    def test_pagina_abre_para_visitante_nao_autenticado(self):
        """O aviso tem que ser legivel por quem ainda nao tem conta.

        Exigir login para ler a politica inverteria a logica: a pessoa decide
        se quer se cadastrar depois de saber o que sera feito com os dados.
        """
        resposta = self.client.get('/privacidade/')
        self.assertEqual(resposta.status_code, 200)

    def test_informa_a_versao_vigente(self):
        resposta = self.client.get('/privacidade/')
        self.assertContains(resposta, privacidade.POLITICA_VERSAO)

    def test_link_aparece_em_todas_as_paginas(self):
        """O rodape fica no base.html, entao vale para o site inteiro."""
        for caminho in ['/', '/login/', '/cadastro/']:
            with self.subTest(caminho=caminho):
                self.assertContains(self.client.get(caminho), '/privacidade/')

    def test_descreve_os_dados_que_o_sistema_realmente_coleta(self):
        """REGRESSAO: aviso que descreve errado o sistema e pior que nenhum.

        Se um campo novo passar a ser coletado e o aviso nao mencionar, o
        tratamento fica sem a informacao exigida pelo art. 9 da LGPD.
        """
        corpo = self.client.get('/privacidade/').content.decode()
        for termo in ['senha', 'telefone', 'comentários', 'mensagem']:
            with self.subTest(termo=termo):
                self.assertIn(termo, corpo.lower())

    def test_cita_a_lei_e_os_direitos_do_titular(self):
        corpo = self.client.get('/privacidade/').content.decode()
        self.assertIn('13.709', corpo)
        self.assertIn('art. 18', corpo.lower())

# ---------------------------------------------------------------------------
# Registro pseudonimizado de uso
# ---------------------------------------------------------------------------


# User-Agent de navegador real. O cliente de teste do Django nao envia nenhum,
# e o middleware de telemetria descarta requisicao sem identificacao por
# considera-la automatizada - navegador de pessoa sempre manda um.
NAVEGADOR_DE_TESTE = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                      'AppleWebKit/537.36 (KHTML, like Gecko) '
                      'Chrome/120.0 Safari/537.36')


class ComNavegador:
    """Faz o cliente de teste se identificar como navegador.

    Sem isso o filtro de robos descarta a requisicao e nenhum evento de uso e
    gravado, o que faria qualquer teste de telemetria falhar por um motivo que
    nao tem relacao com o que ele quer verificar.
    """

    def setUp(self):
        super().setUp()
        self.client.defaults['HTTP_USER_AGENT'] = NAVEGADOR_DE_TESTE


class TestRegistroDeUso(ComNavegador, TestCase):
    def test_pagina_vista_gera_um_evento(self):
        self.client.get('/')
        self.assertEqual(EventoDeUso.objects.count(), 1)
        self.assertEqual(EventoDeUso.objects.get().caminho, '/')

    def test_guarda_categoria_e_termo_buscado(self):
        self.client.get('/?categoria=venda&busca=bicicleta')
        evento = EventoDeUso.objects.get()
        self.assertEqual(evento.categoria, 'venda')
        self.assertEqual(evento.busca, 'bicicleta')

    def test_nao_guarda_quem_e_a_pessoa(self):
        """O registro diz que havia alguem logado, nunca quem era.

        Se este teste falhar, o aviso de privacidade passa a descrever errado o
        sistema: ele afirma que a conta nao e vinculada ao registro de uso.
        """
        User.objects.create_user('carla', password='senha-de-teste-123')
        self.client.login(username='carla', password='senha-de-teste-123')
        self.client.get('/')

        evento = EventoDeUso.objects.get()
        self.assertTrue(evento.autenticado)

        campos = {c.name for c in EventoDeUso._meta.get_fields()}
        self.assertNotIn('usuario', campos)
        self.assertNotIn('ip', campos)
        for valor in evento.__dict__.values():
            self.assertNotIn('carla', str(valor))

    def test_paginas_da_mesma_visita_compartilham_o_identificador(self):
        self.client.get('/')
        self.client.get('/cadastro/')
        visitas = set(EventoDeUso.objects.values_list('visita', flat=True))
        self.assertEqual(len(visitas), 1)

    def test_identificador_nao_deriva_do_usuario(self):
        self.client.get('/')
        visita = EventoDeUso.objects.get().visita
        self.assertEqual(len(visita), 16)
        self.assertNotIn('carla', visita)

    def test_nao_registra_o_painel_administrativo(self):
        """O painel e manutencao do grupo, nao uso da comunidade."""
        self.client.get('/admin/')
        self.assertEqual(EventoDeUso.objects.count(), 0)

    def test_nao_registra_envio_de_formulario(self):
        self.client.post('/login/', {'username': 'x', 'password': 'y'})
        self.assertEqual(EventoDeUso.objects.count(), 0)

    def test_falha_do_registro_nao_derruba_a_pagina(self):
        """REGRESSAO: telemetria nunca pode quebrar o site.

        Se a gravacao falhar - banco fora do ar, migration pendente -, a pessoa
        tem que receber a pagina do mesmo jeito.
        """
        from unittest.mock import patch
        with patch.object(EventoDeUso.objects, 'create', side_effect=Exception('banco fora')):
            resposta = self.client.get('/')
        self.assertEqual(resposta.status_code, 200)


class TestRetencaoDeEventos(TestCase):
    def test_apaga_eventos_alem_do_prazo(self):
        from datetime import timedelta
        from django.utils import timezone

        antigo = EventoDeUso.objects.create(visita='a' * 16, caminho='/')
        recente = EventoDeUso.objects.create(visita='b' * 16, caminho='/')
        EventoDeUso.objects.filter(pk=antigo.pk).update(
            ocorrido_em=timezone.now() - timedelta(days=120)
        )

        call_command('limpar_eventos', stdout=StringIO())

        self.assertFalse(EventoDeUso.objects.filter(pk=antigo.pk).exists())
        self.assertTrue(EventoDeUso.objects.filter(pk=recente.pk).exists())

    def test_simular_nao_apaga(self):
        from datetime import timedelta
        from django.utils import timezone

        evento = EventoDeUso.objects.create(visita='c' * 16, caminho='/')
        EventoDeUso.objects.filter(pk=evento.pk).update(
            ocorrido_em=timezone.now() - timedelta(days=120)
        )
        call_command('limpar_eventos', '--simular', stdout=StringIO())
        self.assertTrue(EventoDeUso.objects.filter(pk=evento.pk).exists())


class TestAvisoCobreORegistroDeUso(TestCase):
    def test_aviso_declara_o_registro_de_uso(self):
        """O aviso tem que descrever o que o middleware realmente grava."""
        corpo = self.client.get('/privacidade/').content.decode().lower()
        for termo in ['registro de uso', 'pseudonimizado', '90 dias']:
            with self.subTest(termo=termo):
                self.assertIn(termo, corpo)

    def test_aviso_afirma_o_que_nao_e_coletado(self):
        corpo = self.client.get('/privacidade/').content.decode().lower()
        self.assertIn('não são registrados o endereço de origem', corpo)

# ---------------------------------------------------------------------------
# Exportacao em CSV
# ---------------------------------------------------------------------------


class TestExportacaoCsv(ComNavegador, TestCase):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_superuser(
            'chefe', 'chefe@example.com', 'senha-de-teste-123'
        )
        self.client.login(username='chefe', password='senha-de-teste-123')

    def gerar_uso(self):
        self.client.logout()
        self.client.get('/')
        self.client.get('/?busca=bicicleta')
        self.client.get('/cadastro/')
        self.client.login(username='chefe', password='senha-de-teste-123')

    def baixar(self, acao):
        self.gerar_uso()
        ids = list(EventoDeUso.objects.values_list('pk', flat=True))
        return self.client.post(
            reverse('admin:posts_eventodeuso_changelist'),
            {'action': acao, '_selected_action': ids},
        )

    def test_exporta_eventos_como_arquivo(self):
        resposta = self.baixar('exportar_eventos')
        self.assertEqual(resposta.status_code, 200)
        self.assertIn('attachment', resposta['Content-Disposition'])
        self.assertIn('smartbairro_uso.csv', resposta['Content-Disposition'])

    def test_csv_usa_ponto_e_virgula_e_bom(self):
        """Sem isso o Excel em portugues abre tudo numa coluna so e com acento quebrado."""
        conteudo = self.baixar('exportar_eventos').content
        self.assertTrue(conteudo.startswith(b'\xef\xbb\xbf'))
        primeira = conteudo.decode('utf-8-sig').splitlines()[0]
        self.assertIn(';', primeira)
        self.assertNotIn(',', primeira)

    def test_csv_traz_as_colunas_derivadas(self):
        corpo = self.baixar('exportar_eventos').content.decode('utf-8-sig')
        cabecalho = corpo.splitlines()[0]
        for coluna in ['data', 'hora', 'dia_da_semana', 'secao', 'busca', 'visita']:
            with self.subTest(coluna=coluna):
                self.assertIn(coluna, cabecalho)

    def test_exportacao_nao_vaza_identificacao(self):
        """REGRESSAO: o CSV sai do sistema e circula. Nao pode levar quem e."""
        corpo = self.baixar('exportar_eventos').content.decode('utf-8-sig')
        self.assertNotIn('chefe', corpo)

    def test_resumo_de_visitas_agrupa_por_visita(self):
        resposta = self.baixar('exportar_visitas')
        corpo = resposta.content.decode('utf-8-sig')
        linhas = [l for l in corpo.splitlines() if l.strip()]

        self.assertIn('smartbairro_visitas.csv', resposta['Content-Disposition'])
        self.assertIn('ultima_pagina', linhas[0])
        # tres paginas vistas na mesma sessao viram uma linha de visita
        self.assertEqual(len(linhas), 2)
        self.assertIn('3', linhas[1].split(';'))

    def test_visitante_sem_painel_nao_exporta(self):
        self.client.logout()
        resposta = self.client.post(
            reverse('admin:posts_eventodeuso_changelist'),
            {'action': 'exportar_eventos', '_selected_action': ['1']},
        )
        self.assertNotEqual(resposta.status_code, 200)

# ---------------------------------------------------------------------------
# Registro de erros
# ---------------------------------------------------------------------------


class TestConfiguracaoDeLog(SimpleTestCase):
    def test_erro_de_requisicao_vai_para_o_console(self):
        """REGRESSAO: sem isso, erro 500 em producao nao deixa rastro.

        O padrao do Django filtra o console com require_debug_true e manda o
        erro por e-mail em producao. Sem servidor de e-mail, o traceback some.
        """
        logger = logging.getLogger('django.request')
        handlers = [type(h).__name__ for h in logger.handlers]
        self.assertIn('StreamHandler', handlers)
        self.assertFalse(logger.propagate)

    def test_console_nao_depende_de_debug(self):
        """O filtro require_debug_true e justamente o que precisa nao existir."""
        for h in logging.getLogger('django.request').handlers:
            for f in getattr(h, 'filters', []):
                self.assertNotIn('debug', type(f).__name__.lower())

    def test_codigo_da_aplicacao_tambem_registra(self):
        logger = logging.getLogger('posts')
        self.assertTrue(logger.handlers)


class TestFalhaDaTelemetriaFicaVisivel(ComNavegador, TestCase):
    def test_falha_ao_gravar_evento_e_registrada(self):
        """Engolir a excecao mantem o site de pe; engolir calado esconde o bug.

        Era a segunda cegueira: tela vazia de eventos ficava igual a "ninguem
        navegou". Agora a falha aparece no log e a pagina continua sendo
        entregue.
        """
        from unittest.mock import patch

        with patch.object(EventoDeUso.objects, 'create',
                          side_effect=Exception('banco fora do ar')):
            with self.assertLogs('posts.telemetria', level='ERROR') as capturado:
                resposta = self.client.get('/')

        self.assertEqual(resposta.status_code, 200)
        self.assertIn('Falha ao registrar evento de uso', capturado.output[0])
        self.assertIn('banco fora do ar', capturado.output[0])

# ---------------------------------------------------------------------------
# Consentimento do remetente
# ---------------------------------------------------------------------------


@override_settings(INGESTAO_TOKEN=TOKEN)
class TestRegistroDeConsentimento(TestCase):
    def test_ingestao_com_consentimento_grava_o_registro(self):
        self.client.post(
            '/api/ingestao/',
            data=json.dumps({'canal': 'teste', 'remetente': '5511999998888',
                             'texto': 'vendo sofa 200 reais',
                             'consentimento': True}),
            content_type='application/json',
            headers={'x-ingestao-token': TOKEN},
        )
        registro = Consentimento.objects.get()
        self.assertEqual(registro.remetente, '5511999998888')
        self.assertTrue(registro.ativo)

    def test_guarda_a_versao_da_politica_vigente(self):
        """Sem isso nao da para dizer com que texto a pessoa concordou."""
        ingestao.registrar_consentimento('teste', '5511999998888')
        self.assertEqual(
            Consentimento.objects.get().politica_versao,
            privacidade.POLITICA_VERSAO,
        )

    def test_consentimento_vale_para_os_envios_seguintes(self):
        """O consentimento e da pessoa, nao da mensagem."""
        ingestao.registrar_consentimento('teste', '5511999998888')
        ingestao.registrar_consentimento('teste', '5511999998888')
        self.assertEqual(Consentimento.objects.count(), 1)

    def test_ingestao_sem_consentimento_nao_grava_registro(self):
        self.client.post(
            '/api/ingestao/',
            data=json.dumps({'canal': 'teste', 'remetente': '5511999998888',
                             'texto': 'vendo sofa 200 reais'}),
            content_type='application/json',
            headers={'x-ingestao-token': TOKEN},
        )
        self.assertEqual(Consentimento.objects.count(), 0)

    def test_mensagem_e_gravada_mesmo_sem_consentimento(self):
        """Receber e guardar e uma coisa; publicar e outra.

        O registro de que a mensagem chegou precisa existir de qualquer forma,
        nem que seja para documentar que chegou sem autorizacao de uso.
        """
        self.client.post(
            '/api/ingestao/',
            data=json.dumps({'canal': 'teste', 'remetente': '5511999998888',
                             'texto': 'vendo sofa 200 reais'}),
            content_type='application/json',
            headers={'x-ingestao-token': TOKEN},
        )
        self.assertEqual(MensagemRecebida.objects.count(), 1)

    def test_quem_revogou_e_voltou_recomeca_sob_a_politica_atual(self):
        registro = ingestao.registrar_consentimento('teste', '5511999998888')
        registro.revogado_em = timezone.now()
        registro.save(update_fields=['revogado_em'])

        ingestao.registrar_consentimento('teste', '5511999998888')
        registro.refresh_from_db()
        self.assertIsNone(registro.revogado_em)
        self.assertEqual(Consentimento.objects.count(), 1)


class TestPublicacaoDependeDeConsentimento(TestCase):
    def nova_mensagem(self, remetente='5511999998888'):
        return MensagemRecebida.objects.create(
            canal='teste', remetente=remetente,
            texto='Doando sofá bege, retirar no local',
        )

    def test_sem_consentimento_nao_vira_rascunho(self):
        """REGRESSAO: e a garantia de que o art. 7, I e cumprido no codigo.

        Se este teste falhar, conteudo de morador pode ser publicado sem que
        ele tenha autorizado - exatamente o que o aviso de privacidade promete
        que nao acontece.
        """
        mensagem = self.nova_mensagem()
        post, motivo = ingestao.processar_mensagem(mensagem)

        self.assertIsNone(post)
        self.assertEqual(motivo, ingestao.SEM_CONSENTIMENTO)
        self.assertEqual(Post.objects.count(), 0)

        mensagem.refresh_from_db()
        self.assertEqual(mensagem.status, 'pendente')
        self.assertIn('consentimento', mensagem.erro.lower())

    def test_com_consentimento_vira_rascunho_normalmente(self):
        ingestao.registrar_consentimento('teste', '5511999998888')
        post, motivo = ingestao.processar_mensagem(self.nova_mensagem())

        self.assertEqual(motivo, ingestao.CRIADO)
        self.assertEqual(post.categoria, 'doacao')
        self.assertEqual(post.status, 'rascunho')

    def test_revogacao_impede_novas_publicacoes(self):
        registro = ingestao.registrar_consentimento('teste', '5511999998888')
        registro.revogado_em = timezone.now()
        registro.save(update_fields=['revogado_em'])

        post, motivo = ingestao.processar_mensagem(self.nova_mensagem())
        self.assertIsNone(post)
        self.assertEqual(motivo, ingestao.SEM_CONSENTIMENTO)

    def test_consentimento_de_um_nao_vale_para_outro(self):
        ingestao.registrar_consentimento('teste', '5511999998888')
        post, motivo = ingestao.processar_mensagem(
            self.nova_mensagem(remetente='5511977776666')
        )
        self.assertIsNone(post)
        self.assertEqual(motivo, ingestao.SEM_CONSENTIMENTO)

    def test_consentimento_e_por_canal(self):
        """Autorizar no WhatsApp nao autoriza no Telegram."""
        ingestao.registrar_consentimento('whatsapp', '5511999998888')
        self.assertFalse(ingestao.tem_consentimento('telegram', '5511999998888'))


# ---------------------------------------------------------------------------
# Direito a eliminacao (art. 18, VI)
# ---------------------------------------------------------------------------


class TestEsquecerRemetente(TestCase):
    CANAL = 'teste'
    TITULAR = '5511999998888'
    OUTRO = '5511977776666'

    def setUp(self):
        for remetente in (self.TITULAR, self.OUTRO):
            ingestao.registrar_consentimento(self.CANAL, remetente)

    def mensagem_publicada(self, remetente, texto='vendo sofa 200 reais zap 11 98888-7777'):
        m = MensagemRecebida.objects.create(
            canal=self.CANAL, remetente=remetente, texto=texto
        )
        post, _ = ingestao.processar_mensagem(m)
        return m, post

    def test_apaga_as_mensagens_do_titular(self):
        self.mensagem_publicada(self.TITULAR)
        ingestao.esquecer_remetente(self.CANAL, self.TITULAR)
        self.assertFalse(
            MensagemRecebida.objects.filter(remetente=self.TITULAR).exists()
        )

    def test_revoga_e_anonimiza_o_consentimento(self):
        """A linha sobrevive sem o identificador: registra que houve revogacao."""
        ingestao.esquecer_remetente(self.CANAL, self.TITULAR)

        self.assertFalse(
            Consentimento.objects.filter(remetente=self.TITULAR).exists()
        )
        restante = Consentimento.objects.exclude(remetente=self.OUTRO).get()
        self.assertIn(ingestao.MARCA_REMOVIDO, restante.remetente)
        self.assertIsNotNone(restante.revogado_em)

    def test_tira_o_telefone_da_publicacao_mas_mantem_o_conteudo(self):
        _, post = self.mensagem_publicada(self.TITULAR)
        self.assertTrue(post.telefone)

        ingestao.esquecer_remetente(self.CANAL, self.TITULAR)

        post.refresh_from_db()
        self.assertEqual(post.telefone, '')
        self.assertTrue(post.titulo)

    def test_apaga_a_publicacao_quando_pedido(self):
        _, post = self.mensagem_publicada(self.TITULAR)
        ingestao.esquecer_remetente(self.CANAL, self.TITULAR, apagar_posts=True)
        self.assertFalse(Post.objects.filter(pk=post.pk).exists())

    def test_nao_toca_nos_dados_de_outro_remetente(self):
        """REGRESSAO: atender um pedido nao pode apagar dado de terceiro."""
        self.mensagem_publicada(self.TITULAR)
        outro_m, outro_post = self.mensagem_publicada(self.OUTRO)

        ingestao.esquecer_remetente(self.CANAL, self.TITULAR)

        self.assertTrue(MensagemRecebida.objects.filter(pk=outro_m.pk).exists())
        outro_post.refresh_from_db()
        self.assertTrue(outro_post.telefone)
        self.assertTrue(
            Consentimento.objects.filter(
                remetente=self.OUTRO, revogado_em__isnull=True
            ).exists()
        )

    def test_dois_pedidos_no_mesmo_canal_nao_colidem(self):
        """A marca de anonimizacao leva a chave da linha justamente por isso.

        Canal + remetente e unico no banco. Sem a chave na marca, o segundo
        pedido de exclusao quebraria com erro de unicidade.
        """
        ingestao.esquecer_remetente(self.CANAL, self.TITULAR)
        ingestao.esquecer_remetente(self.CANAL, self.OUTRO)
        self.assertEqual(Consentimento.objects.count(), 2)

    def test_depois_de_esquecido_nao_publica_mais(self):
        self.mensagem_publicada(self.TITULAR)
        ingestao.esquecer_remetente(self.CANAL, self.TITULAR)

        nova = MensagemRecebida.objects.create(
            canal=self.CANAL, remetente=self.TITULAR, texto='vendo mesa 100 reais'
        )
        post, motivo = ingestao.processar_mensagem(nova)
        self.assertIsNone(post)
        self.assertEqual(motivo, ingestao.SEM_CONSENTIMENTO)

    def test_pedido_de_quem_nunca_mandou_nada_nao_quebra(self):
        resumo = ingestao.esquecer_remetente(self.CANAL, '5511900000000')
        self.assertEqual(resumo['mensagens_apagadas'], 0)


class TestComandoEsquecerRemetente(TestCase):
    def setUp(self):
        ingestao.registrar_consentimento('teste', '5511999998888')
        MensagemRecebida.objects.create(
            canal='teste', remetente='5511999998888',
            texto='Doando sofá bege, retirar no local',
        )

    def test_simular_nao_apaga_nada(self):
        """A operacao e irreversivel, entao a simulacao e a primeira defesa."""
        saida = StringIO()
        call_command('esquecer_remetente', '--canal', 'teste',
                     '--remetente', '5511999998888', '--simular', stdout=saida)

        self.assertEqual(MensagemRecebida.objects.count(), 1)
        self.assertIn('Simulacao', saida.getvalue())

    def test_apaga_quando_executado_de_verdade(self):
        saida = StringIO()
        call_command('esquecer_remetente', '--canal', 'teste',
                     '--remetente', '5511999998888', stdout=saida)
        self.assertEqual(MensagemRecebida.objects.count(), 0)

    def test_canal_invalido_e_recusado(self):
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            call_command('esquecer_remetente', '--canal', 'pombo',
                         '--remetente', '5511999998888', stdout=StringIO())


# ---------------------------------------------------------------------------
# Filtro de robos, codigo de retorno e tempo de resposta
# ---------------------------------------------------------------------------


class TestFiltroDeRobos(TestCase):
    NAVEGADOR = NAVEGADOR_DE_TESTE

    def test_visita_de_pessoa_e_registrada(self):
        self.client.get('/', headers={'user-agent': self.NAVEGADOR})
        self.assertEqual(EventoDeUso.objects.count(), 1)

    def test_rastreadores_conhecidos_sao_descartados(self):
        """Sem isso a analise mede robo em vez de morador."""
        agentes = [
            'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)',
            'Mozilla/5.0 (compatible; bingbot/2.0)',
            'python-requests/2.31.0',
            'curl/8.4.0',
            'facebookexternalhit/1.1',
            'Mozilla/5.0 AhrefsBot/7.0',
        ]
        for agente in agentes:
            with self.subTest(agente=agente[:28]):
                EventoDeUso.objects.all().delete()
                self.client.get('/', headers={'user-agent': agente})
                self.assertEqual(EventoDeUso.objects.count(), 0)

    def test_requisicao_sem_identificacao_e_descartada(self):
        """Navegador de pessoa sempre manda User-Agent."""
        self.client.get('/', headers={'user-agent': ''})
        self.assertEqual(EventoDeUso.objects.count(), 0)

    def test_programa_do_navegador_nao_e_armazenado(self):
        """REGRESSAO: o User-Agent e lido para decidir, nunca guardado.

        O aviso de privacidade afirma isso. Se um campo passar a guarda-lo, a
        pagina publicada vira declaracao falsa.
        """
        self.client.get('/', headers={'user-agent': self.NAVEGADOR})
        evento = EventoDeUso.objects.get()
        for valor in evento.__dict__.values():
            self.assertNotIn('Mozilla', str(valor))
        self.assertNotIn('agente', {c.name for c in EventoDeUso._meta.get_fields()})


@override_settings(ALLOWED_HOSTS=['testserver'])
class TestCodigoDeRetornoETempo(TestCase):
    NAVEGADOR = 'Mozilla/5.0 (X11; Linux x86_64) Chrome/120.0 Safari/537.36'

    def navegar(self, caminho, metodo='get', **extra):
        funcao = getattr(self.client, metodo)
        return funcao(caminho, headers={'user-agent': self.NAVEGADOR}, **extra)

    def test_guarda_o_codigo_de_retorno(self):
        self.navegar('/')
        self.assertEqual(EventoDeUso.objects.get().status, 200)

    def test_guarda_o_tempo_de_processamento(self):
        self.navegar('/')
        self.assertGreaterEqual(EventoDeUso.objects.get().duracao_ms, 0)

    def test_pagina_inexistente_tambem_e_registrada(self):
        """Antes so o 200 entrava, entao erro de navegacao era invisivel."""
        self.navegar('/caminho-que-nao-existe/')
        self.assertEqual(EventoDeUso.objects.get().status, 404)

    def test_recusa_de_publicacao_vira_registro(self):
        """E o que a equipe pediu: contar quantas tentativas sao barradas.

        Recusa nao e defeito tecnico - o sistema funcionou como projetado. E
        sinal de usabilidade: se muita gente e barrada, o formulario pede
        demais, o que conversa com a justificativa do projeto.
        """
        User.objects.create_user('duda', password='senha-de-teste-123')
        self.client.login(username='duda', password='senha-de-teste-123')
        EventoDeUso.objects.all().delete()

        self.navegar('/criar/', 'post', data={'titulo': '', 'descricao': 'x'})

        evento = EventoDeUso.objects.filter(caminho='/criar/').last()
        self.assertIsNotNone(evento)
        self.assertEqual(evento.status, 400)

    def test_envio_de_credencial_nao_e_registrado(self):
        """Login e cadastro ficam fora: envolvem credencial."""
        self.navegar('/login/', 'post',
                     data={'username': 'x', 'password': 'y'})
        self.assertFalse(EventoDeUso.objects.filter(caminho='/login/').exists())

    def test_pagina_de_login_vista_continua_sendo_registrada(self):
        """So o ENVIO fica de fora; a visita a tela e navegacao normal."""
        self.navegar('/login/')
        self.assertTrue(EventoDeUso.objects.filter(caminho='/login/').exists())


class TestAvisoCobreAsMetricas(TestCase):
    def test_pagina_mostra_a_versao_vigente(self):
        """A pagina tem que anunciar a versao que o codigo considera em vigor.

        Antes este teste fixava o numero da versao, o que o obrigava a ser
        editado a cada alteracao do aviso - e um teste que se edita junto com o
        que ele verifica nao verifica nada. Comparar com a constante mantem a
        checagem valida em qualquer versao: o que importa e a pagina e o
        registro de consentimento falarem da mesma.
        """
        corpo = self.client.get('/privacidade/').content.decode()
        self.assertIn(privacidade.POLITICA_VERSAO, corpo)

    def test_aviso_declara_os_dados_novos(self):
        # O HTML quebra linha no meio das frases, entao comparar texto cru
        # falharia por formatacao e nao por conteudo ausente.
        corpo = re.sub(r'\s+', ' ',
                       self.client.get('/privacidade/').content.decode().lower())
        for termo in ['código de retorno', 'tempo de processamento',
                      'rastreadores', 'envios de formulário']:
            with self.subTest(termo=termo):
                self.assertIn(termo, corpo)

    def test_aviso_nega_guardar_conteudo_de_formulario(self):
        corpo = re.sub(r'\s+', ' ',
                       self.client.get('/privacidade/').content.decode().lower())
        self.assertIn('não é armazenado', corpo)

    def test_canal_de_contato_do_titular_esta_publicado(self):
        """REGRESSAO: sem canal informado o aviso nao cumpre o art. 9 da LGPD.

        O titular precisa de um meio concreto de exercer os direitos do art.
        18. Aviso que lista direitos sem dizer como exerce-los e decorativo.
        """
        corpo = self.client.get('/privacidade/').content.decode()
        self.assertIn('smartbairro.contato@gmail.com', corpo)
        self.assertIn('15 dias', corpo)

    def test_historico_de_versoes_esta_publicado(self):
        corpo = self.client.get('/privacidade/').content.decode()
        self.assertIn('Versão 1.0', corpo)
        self.assertIn('Versão 1.1', corpo)

# ---------------------------------------------------------------------------
# Acessibilidade
# ---------------------------------------------------------------------------


class TestHierarquiaDeTitulos(ComNavegador, BaseComDados):
    """Os niveis de titulo nao podem pular degraus.

    Leitor de tela monta o indice da pagina a partir dos titulos, e e assim que
    quem nao enxerga navega. Saltar de h1 para h5 produz um indice com buracos,
    como um sumario que vai do capitulo 1 para o 1.1.1.1.

    E o criterio 1.3.1 da WCAG 2.1, e foi um dos dois itens reprovados na
    auditoria de 29/10.
    """

    def niveis(self, caminho):
        corpo = self.client.get(caminho).content.decode()
        return [int(n) for n in re.findall(r'<h([1-6])[\s>]', corpo)]

    def verificar(self, caminho):
        niveis = self.niveis(caminho)
        self.assertTrue(niveis, f'{caminho} nao tem titulo nenhum')
        anterior = niveis[0]
        for atual in niveis[1:]:
            if atual > anterior:
                self.assertLessEqual(
                    atual, anterior + 1,
                    f'{caminho}: salto de h{anterior} para h{atual}',
                )
            anterior = atual

    def test_mural_nao_pula_nivel(self):
        self.verificar('/')

    def test_detalhe_do_post_nao_pula_nivel(self):
        self.verificar(f'/post/{self.post.id}/')

    def test_aviso_de_privacidade_nao_pula_nivel(self):
        self.verificar('/privacidade/')

    def test_mural_comeca_no_h1(self):
        self.assertEqual(self.niveis('/')[0], 1)
