#!/usr/bin/env bash
# Script executado pelo Render a cada deploy.
# set -o errexit faz o script parar no primeiro erro, em vez de seguir adiante
# e publicar uma versao quebrada.
set -o errexit

pip install -r requirements.txt

# Reune CSS e JavaScript numa pasta unica para o WhiteNoise servir.
python manage.py collectstatic --no-input

# Aplica as alteracoes de estrutura no banco de dados.
python manage.py migrate

# Cria o administrador na primeira vez. Nas demais, nao faz nada.
python manage.py criar_admin
