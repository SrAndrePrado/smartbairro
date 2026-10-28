"""Remove eventos de uso mais antigos que o prazo de retencao.

Uso:
    python manage.py limpar_eventos
    python manage.py limpar_eventos --dias 30
    python manage.py limpar_eventos --simular

O prazo existe por exigencia da LGPD: o art. 15 determina o termino do
tratamento quando os dados deixam de ser necessarios para a finalidade. Dados
de uso servem para entender tendencia recente; guardados indefinidamente, so
acumulam risco sem acrescentar resposta.

O prazo declarado no aviso de privacidade e o padrao deste comando. Alterar um
sem alterar o outro deixa a pagina mentindo sobre o sistema.
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from posts.models import EventoDeUso

DIAS_DE_RETENCAO = 90


class Command(BaseCommand):
    help = 'Apaga eventos de uso anteriores ao prazo de retencao.'

    def add_arguments(self, parser):
        parser.add_argument('--dias', type=int, default=DIAS_DE_RETENCAO,
                            help=f'Prazo de retencao (padrao: {DIAS_DE_RETENCAO}).')
        parser.add_argument('--simular', action='store_true',
                            help='Mostra quantos seriam apagados, sem apagar.')

    def handle(self, *args, **opcoes):
        corte = timezone.now() - timedelta(days=opcoes['dias'])
        antigos = EventoDeUso.objects.filter(ocorrido_em__lt=corte)
        total = antigos.count()

        if not total:
            self.stdout.write(
                f'Nenhum evento anterior a {corte:%d/%m/%Y}. Nada a apagar.'
            )
            return

        if opcoes['simular']:
            self.stdout.write(
                f'{total} evento(s) anteriores a {corte:%d/%m/%Y} seriam apagados.'
            )
            return

        antigos.delete()
        self.stdout.write(self.style.SUCCESS(
            f'{total} evento(s) anteriores a {corte:%d/%m/%Y} apagados.'
        ))
