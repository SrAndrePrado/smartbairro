from django.contrib import admin

from . import classificacao, exportacao, ingestao
from .models import (Post, Curtida, Comentario, MensagemRecebida,
                     EventoDeUso, Consentimento)


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = ('titulo', 'categoria', 'status', 'origem', 'usuario', 'data_criacao')
    list_filter = ('status', 'origem', 'categoria')
    search_fields = ('titulo', 'descricao', 'telefone')
    actions = ['aprovar_rascunhos']

    @admin.action(description='Aprovar e publicar os rascunhos selecionados')
    def aprovar_rascunhos(self, request, queryset):
        publicados = queryset.filter(status='rascunho').update(status='publicado')
        self.message_user(request, f'{publicados} post(s) publicado(s).')


@admin.register(MensagemRecebida)
class MensagemRecebidaAdmin(admin.ModelAdmin):
    list_display = ('recebida_em', 'canal', 'remetente', 'resumo',
                    'categoria_sugerida', 'consentido', 'status', 'post')
    list_filter = ('canal', 'status')
    search_fields = ('texto', 'remetente', 'id_externo')
    readonly_fields = ('recebida_em',)
    actions = ['classificar_selecionadas']

    @admin.display(description='Mensagem')
    def resumo(self, obj):
        return obj.texto[:60] + ('...' if len(obj.texto) > 60 else '')

    @admin.display(description='Sugestão')
    def categoria_sugerida(self, obj):
        """Mostra o que o classificador diria, sem gravar nada.

        A coluna existe para o moderador conferir a sugestao antes de aceita-la,
        e para deixar visivel quando o sistema nao soube decidir. A interpretacao
        roda aqui a cada exibicao da lista, o que e aceitavel porque o custo e
        apenas de processamento de texto, sem consulta ao banco.
        """
        if obj.post_id:
            return '—'
        sugestao = classificacao.interpretar(obj.texto)
        if not sugestao['confiavel']:
            return 'sem confiança'
        rotulo = dict(Post.CATEGORIAS).get(sugestao['categoria'], sugestao['categoria'])
        return f"{rotulo} ({sugestao['pontuacao']})"

    @admin.display(description='Consentimento', boolean=True)
    def consentido(self, obj):
        """Mostra na fila se ha consentimento ativo para aquele remetente.

        Sem esta coluna o moderador so descobriria a ausencia depois de rodar a
        acao e ler o resumo, o que transforma uma informacao em uma tentativa.
        """
        return ingestao.tem_consentimento(obj.canal, obj.remetente)

    @admin.action(description='Classificar e criar rascunho das mensagens selecionadas')
    def classificar_selecionadas(self, request, queryset):
        resumo = {ingestao.CRIADO: 0, ingestao.SEM_CONFIANCA: 0,
                  ingestao.SEM_CONSENTIMENTO: 0, ingestao.JA_PROCESSADA: 0}

        for mensagem in queryset:
            _, motivo = ingestao.processar_mensagem(mensagem)
            resumo[motivo] += 1

        partes = [f"{resumo[ingestao.CRIADO]} rascunho(s) criado(s)"]
        if resumo[ingestao.SEM_CONFIANCA]:
            partes.append(
                f"{resumo[ingestao.SEM_CONFIANCA]} sem confiança, mantida(s) na fila"
            )
        if resumo[ingestao.SEM_CONSENTIMENTO]:
            partes.append(
                f"{resumo[ingestao.SEM_CONSENTIMENTO]} sem consentimento do remetente"
            )
        if resumo[ingestao.JA_PROCESSADA]:
            partes.append(f"{resumo[ingestao.JA_PROCESSADA]} já processada(s)")

        self.message_user(
            request,
            '. '.join(partes) + '. Os rascunhos continuam aguardando aprovação em Posts.'
        )


@admin.register(EventoDeUso)
class EventoDeUsoAdmin(admin.ModelAdmin):
    """Somente leitura: o registro de uso e gravado pelo middleware.

    Permitir edicao aqui tornaria os dados imprestaveis para analise e abriria
    a porta para alterar um registro depois do fato.
    """

    list_display = ('ocorrido_em', 'caminho', 'categoria', 'busca',
                    'autenticado', 'visita')
    list_filter = ('autenticado', 'categoria', 'ocorrido_em')
    search_fields = ('caminho', 'busca')
    date_hierarchy = 'ocorrido_em'
    actions = ['exportar_eventos', 'exportar_visitas']

    @admin.action(description='Exportar selecionados para CSV (uma linha por página vista)')
    def exportar_eventos(self, request, queryset):
        return exportacao.exportar_eventos_csv(queryset)

    @admin.action(description='Exportar resumo de visitas para CSV (uma linha por visita)')
    def exportar_visitas(self, request, queryset):
        return exportacao.exportar_visitas_csv(queryset)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Consentimento)
class ConsentimentoAdmin(admin.ModelAdmin):
    list_display = ('remetente', 'canal', 'concedido_em', 'politica_versao',
                    'situacao', 'revogado_em')
    list_filter = ('canal', 'politica_versao')
    search_fields = ('remetente',)
    readonly_fields = ('concedido_em',)

    @admin.display(description='Ativo', boolean=True)
    def situacao(self, obj):
        return obj.ativo


admin.site.register(Curtida)
admin.site.register(Comentario)
