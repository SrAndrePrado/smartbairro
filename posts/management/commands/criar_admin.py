"""Cria o usuario administrador a partir de variaveis de ambiente.

O plano gratuito do Render nao da acesso a terminal no servidor, entao nao ha
como rodar createsuperuser manualmente depois do deploy. Este comando e
chamado pelo build.sh e resolve isso.

E seguro rodar a cada deploy: se o usuario ja existir, nada acontece. E se as
variaveis nao estiverem definidas, ele apenas avisa e sai sem erro, para nao
derrubar o deploy.
"""

import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Cria o superusuario a partir de DJANGO_SUPERUSER_* se ainda nao existir.'

    def handle(self, *args, **opcoes):
        usuario = os.environ.get('DJANGO_SUPERUSER_USERNAME')
        senha = os.environ.get('DJANGO_SUPERUSER_PASSWORD')
        email = os.environ.get('DJANGO_SUPERUSER_EMAIL', '')

        if not usuario or not senha:
            self.stdout.write(
                'DJANGO_SUPERUSER_USERNAME e DJANGO_SUPERUSER_PASSWORD nao '
                'definidas. Nenhum administrador foi criado.'
            )
            return

        User = get_user_model()

        if User.objects.filter(username=usuario).exists():
            self.stdout.write(f'Administrador "{usuario}" ja existe. Nada a fazer.')
            return

        User.objects.create_superuser(username=usuario, email=email, password=senha)
        self.stdout.write(self.style.SUCCESS(f'Administrador "{usuario}" criado.'))
