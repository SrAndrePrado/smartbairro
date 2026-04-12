from django.contrib.auth import views as auth_views
from django.urls import path
from . import views

urlpatterns = [
    path('', views.home),
    path('criar/', views.criar_post),
    path('post/<int:post_id>/', views.detalhe_post),
    path('editar/<int:post_id>/', views.editar_post),
    path('deletar/<int:post_id>/', views.deletar_post),
    path('login/', auth_views.LoginView.as_view(template_name='posts/login.html')),
    path('logout/', auth_views.LogoutView.as_view(next_page='/')),
    path('cadastro/', views.cadastro),
]