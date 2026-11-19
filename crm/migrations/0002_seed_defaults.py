from django.db import migrations


def seed(apps, schema_editor):
    from crm import defaults

    Reason = apps.get_model("crm", "Reason")
    Sector = apps.get_model("crm", "Sector")
    MessageTemplate = apps.get_model("crm", "MessageTemplate")
    Objection = apps.get_model("crm", "Objection")

    for order, (text, requires_detail, asks_contract_end) in enumerate(defaults.REJECTION_REASONS):
        Reason.objects.get_or_create(
            kind="rejection", text=text,
            defaults={"requires_detail": requires_detail, "asks_contract_end": asks_contract_end, "order": order},
        )
    for order, (text, requires_detail) in enumerate(defaults.CANCELLATION_REASONS):
        Reason.objects.get_or_create(
            kind="cancellation", text=text, defaults={"requires_detail": requires_detail, "order": order}
        )
    for order, name in enumerate(defaults.SECTORS):
        Sector.objects.get_or_create(name=name, defaults={"order": order})
    if not MessageTemplate.objects.exists():
        for order, (name, body) in enumerate(defaults.APPOINTMENT_TEMPLATES):
            MessageTemplate.objects.create(name=name, body=body, context="appointment", order=order)
        for order, (name, body) in enumerate(defaults.CUSTOMER_TEMPLATES):
            MessageTemplate.objects.create(name=name, body=body, context="customer", order=order)
    if not Objection.objects.exists():
        for order, (objection, response) in enumerate(defaults.GENERAL_OBJECTIONS):
            Objection.objects.create(objection=objection, response=response, order=order)


class Migration(migrations.Migration):
    dependencies = [("crm", "0001_initial")]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
