"""Versao vigente do aviso de privacidade.

A versao fica isolada neste modulo porque mais de um lugar precisa dela: a
pagina que exibe o aviso e o registro de consentimento, que guarda a qual
versao a pessoa concordou. Sem esse vinculo, uma alteracao no texto tornaria
impossivel saber com o que cada morador concordou de fato.

Ao alterar o conteudo do aviso de forma relevante, incremente a versao aqui e
atualize a data. Consentimentos registrados sob a versao anterior continuam
valendo para o que foi coletado naquele periodo.
"""

from datetime import date

POLITICA_VERSAO = '1.0'
POLITICA_ATUALIZADA_EM = date(2026, 10, 28)
