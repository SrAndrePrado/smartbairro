from django.contrib import admin

from .models import Post, Curtida, Comentario, MensagemRecebida


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
    list_display = ('recebida_em', 'canal', 'remetente', 'resumo', 'status', 'post')
    list_filter = ('canal', 'status')
    search_fields = ('texto', 'remetente', 'id_externo')
    readonly_fields = ('recebida_em',)

    @admin.display(description='Mensagem')
    def resumo(self, obj):
        return obj.texto[:60] + ('...' if len(obj.texto) > 60 else '')


admin.site.register(Curtida)
admin.site.register(Comentario)
