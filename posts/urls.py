from django.contrib.auth import views as auth_views
from django.urls import path
from . import views

urlpatterns = [
    path('', views.home),
    path('criar/', views.criar_post),
    path('post/<int:post_id>/', views.detalhe_post),
    path('editar/<int:post_id>/', views.editar_post),
    path('deletar/<int:post_id>/', views.deletar_post),
    path('login/', views.LoginComLimite.as_view(), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='/')),
    path('cadastro/', views.cadastro),
    path('curtir/<int:post_id>/', views.curtir_post),
    path('comentar/<int:post_id>/', views.comentar_post),

    # API de ingestao: recebe mensagens enviadas pelos moradores por mensageria.
    path('api/ingestao/', views.api_ingestao, name='api_ingestao'),

    # Endpoints consumidos pelo JavaScript da propria pagina.
    path('api/curtir/<int:post_id>/', views.api_curtir, name='api_curtir'),
    path('api/comentar/<int:post_id>/', views.api_comentar, name='api_comentar'),
]