"""Atende um pedido de eliminacao de dados feito pelo titular.

Uso:
    python manage.py esquecer_remetente --canal whatsapp --remetente 5511999998888
    python manage.py esquecer_remetente --canal whatsapp --remetente 5511999998888 --simular
    python manage.py esquecer_remetente --canal whatsapp --remetente 5511999998888 --apagar-posts

O art. 18, VI da Lei 13.709/2018 assegura ao titular a eliminacao dos dados
pessoais tratados com base no consentimento. Este comando executa isso.

A operacao e IRREVERSIVEL. Por isso --simular existe e deveria ser o primeiro
comando a rodar: ele mostra o que seria apagado sem apagar nada.
"""

from django.core.management.base import BaseCommand, CommandError

from posts import ingestao
from posts.models import MensagemRecebida


class Command(BaseCommand):
    help = 'Apaga os dados pessoais de um remetente a pedido do titular.'

    def add_arguments(self, parser):
        parser.add_argument('--canal', required=True,
                            help='Canal de origem (whatsapp, telegram, teste).')
        parser.add_argument('--remetente', required=True,
                            help='Identificador do remetente, como gravado.')
        parser.add_argument('--apagar-posts', action='store_true',
                            help='Apaga tambem as publicacoes geradas, e nao '
                                 'apenas o telefone de contato delas.')
        parser.add_argument('--simular', action='store_true',
                            help='Mostra o que seria feito, sem apagar nada.')

    def handle(self, *args, **opcoes):
        canal = opcoes['canal']
        remetente = opcoes['remetente']

        canais = [c[0] for c in MensagemRecebida.CANAIS]
        if canal not in canais:
            raise CommandError(f'Canal invalido. Aceitos: {", ".join(canais)}.')

        mensagens = MensagemRecebida.objects.filter(canal=canal, remetente=remetente)
        total = mensagens.count()
        com_post = mensagens.exclude(post__isnull=True).count()

        if not total:
            self.stdout.write(
                f'Nenhuma mensagem de {remetente} no canal {canal}. Nada a fazer.'
            )
            return

        if opcoes['simular']:
            self.stdout.write('Simulacao: nada sera apagado.')
            self.stdout.write(f'  mensagens a apagar ........ {total}')
            if opcoes['apagar_posts']:
                self.stdout.write(f'  publicacoes a APAGAR ...... {com_post}')
            else:
                self.stdout.write(f'  publicacoes a anonimizar .. {com_post}')
            self.stdout.write('  consentimento ............. sera revogado e anonimizado')
            return

        resumo = ingestao.esquecer_remetente(canal, remetente,
                                             apagar_posts=opcoes['apagar_posts'])

        self.stdout.write(self.style.SUCCESS('Pedido atendido.'))
        self.stdout.write(f'  mensagens apagadas ........ {resumo["mensagens_apagadas"]}')
        self.stdout.write(f'  publicacoes anonimizadas .. {resumo["posts_anonimizados"]}')
        self.stdout.write(f'  publicacoes apagadas ...... {resumo["posts_apagados"]}')
        self.stdout.write(
            '  consentimento ............. '
            + ('revogado e anonimizado' if resumo['consentimento_revogado']
               else 'nao havia registro')
        )
