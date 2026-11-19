from django.contrib.auth import views as auth_views
from django.urls import path

from .views import appointments, calls, customers, dashboard, pipeline, products, reports, settings, subscriptions

urlpatterns = [
    path("login/", auth_views.LoginView.as_view(redirect_authenticated_user=True), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", dashboard.dashboard, name="dashboard"),

    # قائمة الاتصال وشاشة المكالمة
    path("queue/", calls.queue, name="queue"),
    path("queue/next/", calls.queue_next, name="queue_next"),
    path("customers/<int:pk>/call/", calls.call_screen, name="call"),

    # العملاء
    path("customers/", customers.customer_list, name="customer_list"),
    path("customers/new/", customers.customer_create, name="customer_new"),
    path("customers/export/", customers.customer_export, name="customer_export"),
    path("customers/bulk/", customers.customer_bulk, name="customer_bulk"),
    path("customers/<int:pk>/", customers.customer_detail, name="customer_detail"),
    path("customers/<int:pk>/edit/", customers.customer_edit, name="customer_edit"),
    path("customers/<int:pk>/delete/", customers.customer_delete, name="customer_delete"),
    path("customers/<int:pk>/note/", customers.customer_note, name="customer_note"),
    path("customers/<int:pk>/followup/", customers.customer_followup, name="customer_followup"),
    path("customers/<int:pk>/stage/", customers.customer_stage, name="customer_stage"),
    path("customers/<int:pk>/whatsapp/<int:template_id>/", customers.customer_whatsapp, name="customer_whatsapp"),
    path("customers/<int:pk>/appointments/new/", appointments.appointment_new, name="appointment_new"),
    path("customers/<int:pk>/subscriptions/new/", subscriptions.subscription_new, name="subscription_new"),

    # مراحل البيع والفرص
    path("pipeline/", pipeline.pipeline, name="pipeline"),
    path("opportunities/", pipeline.opportunities, name="opportunities"),

    # المواعيد
    path("appointments/", appointments.appointment_list, name="appointment_list"),
    path("appointments/<int:pk>/", appointments.appointment_detail, name="appointment_detail"),
    path("appointments/<int:pk>/edit/", appointments.appointment_edit, name="appointment_edit"),
    path("appointments/<int:pk>/confirm/", appointments.appointment_confirm, name="appointment_confirm"),
    path("appointments/<int:pk>/attended/", appointments.appointment_attended, name="appointment_attended"),
    path("appointments/<int:pk>/no-show/", appointments.appointment_no_show, name="appointment_no_show"),
    path("appointments/<int:pk>/reschedule/", appointments.appointment_reschedule, name="appointment_reschedule"),
    path("appointments/<int:pk>/cancel/", appointments.appointment_cancel, name="appointment_cancel"),
    path("appointments/<int:pk>/whatsapp/<int:template_id>/", appointments.appointment_whatsapp, name="appointment_whatsapp"),

    # التطبيقات والاشتراكات
    path("products/", products.product_list, name="product_list"),
    path("products/new/", products.product_form, name="product_new"),
    path("products/<int:pk>/", products.product_detail, name="product_detail"),
    path("products/<int:pk>/edit/", products.product_form, name="product_edit"),
    path("subscriptions/", subscriptions.subscription_list, name="subscription_list"),
    path("subscriptions/<int:pk>/edit/", subscriptions.subscription_edit, name="subscription_edit"),
    path("subscriptions/<int:pk>/cancel/", subscriptions.subscription_cancel, name="subscription_cancel"),

    # التقارير
    path("reports/", reports.reports, name="reports"),

    # الإعدادات
    path("settings/", settings.settings_index, name="settings"),
    path("settings/users/", settings.user_list, name="user_list"),
    path("settings/users/new/", settings.user_create, name="user_new"),
    path("settings/users/<int:pk>/", settings.user_edit, name="user_edit"),
    path("settings/users/<int:pk>/password/", settings.user_password, name="user_password"),
    path("settings/import/", settings.import_upload, name="import_upload"),
    path("settings/import/<str:token>/", settings.import_map, name="import_map"),
    path("settings/backup/", settings.settings_backup, name="settings_backup"),
    path("settings/backup/download/", settings.backup_download, name="backup_download"),
]

for crud in settings.CRUDS:
    urlpatterns += crud.urls()
