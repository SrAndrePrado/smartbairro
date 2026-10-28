"""Classifica as mensagens pendentes e cria os rascunhos correspondentes.

Uso:
    python manage.py classificar_mensagens
    python manage.py classificar_mensagens --limite 10
    python manage.py classificar_mensagens --simular

O comando existe ao lado da acao do painel porque sao usos diferentes: a acao
serve ao moderador que esta olhando a fila, e o comando serve para rodar sobre
um lote grande, ou futuramente de forma agendada, sem ninguem na tela.

A opcao --simular mostra o que seria feito sem gravar nada. E a forma segura de
conferir o comportamento do classificador contra mensagens reais antes de
deixa-lo criar rascunhos.
"""

from django.core.management.base import BaseCommand

from posts import classificacao, ingestao


class Command(BaseCommand):
    help = 'Classifica mensagens recebidas pendentes e cria rascunhos de post.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--limite', type=int, default=None,
            help='Processa no maximo esta quantidade de mensagens.',
        )
        parser.add_argument(
            '--simular', action='store_true',
            help='Mostra a classificacao sem gravar nada no banco.',
        )

    def handle(self, *args, **opcoes):
        fila = ingestao.mensagens_pendentes()
        if opcoes['limite']:
            fila = fila[:opcoes['limite']]

        total = fila.count() if hasattr(fila, 'count') else len(fila)
        if not total:
            self.stdout.write('Nenhuma mensagem pendente para classificar.')
            return

        if opcoes['simular']:
            self._simular(fila)
            return

        resumo = {ingestao.CRIADO: 0, ingestao.SEM_CONFIANCA: 0,
                  ingestao.JA_PROCESSADA: 0}

        for mensagem in fila:
            post, motivo = ingestao.processar_mensagem(mensagem)
            resumo[motivo] += 1

            if motivo == ingestao.CRIADO:
                self.stdout.write(self.style.SUCCESS(
                    f'  #{mensagem.id} -> rascunho #{post.id} '
                    f'[{post.categoria}] {post.titulo}'
                ))
            elif motivo == ingestao.SEM_CONFIANCA:
                self.stdout.write(self.style.WARNING(
                    f'  #{mensagem.id} -> sem confianca, mantida na fila'
                ))

        self.stdout.write('')
        self.stdout.write(
            f'{resumo[ingestao.CRIADO]} rascunho(s) criado(s), '
            f'{resumo[ingestao.SEM_CONFIANCA]} sem confianca, '
            f'{resumo[ingestao.JA_PROCESSADA]} ja processada(s).'
        )
        if resumo[ingestao.CRIADO]:
            self.stdout.write(
                'Os rascunhos aguardam aprovacao no painel, em Posts.'
            )

    def _simular(self, fila):
        self.stdout.write('Simulacao: nada sera gravado.')
        self.stdout.write('')
        for mensagem in fila:
            sugestao = classificacao.interpretar(mensagem.texto)
            categoria = sugestao['categoria'] or 'SEM CONFIANCA'
            self.stdout.write(f'  #{mensagem.id} {mensagem.texto[:58]}')
            self.stdout.write(
                f'      categoria: {categoria} (pontuacao {sugestao["pontuacao"]})'
            )
            self.stdout.write(f'      titulo   : {sugestao["titulo"]}')
            self.stdout.write(f'      telefone : {sugestao["telefone"] or "-"}')
            self.stdout.write('')
