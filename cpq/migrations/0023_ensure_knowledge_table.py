from django.db import migrations


def ensure_knowledge_table(apps, schema_editor):
    Knowledge = apps.get_model("cpq", "Knowledge")
    table_name = Knowledge._meta.db_table
    existing_tables = schema_editor.connection.introspection.table_names()
    if table_name in existing_tables:
        return
    schema_editor.create_model(Knowledge)


class Migration(migrations.Migration):
    atomic = False
    dependencies = [
        ("cpq", "0022_partnerprofile"),
    ]

    operations = [
        migrations.RunPython(ensure_knowledge_table, migrations.RunPython.noop),
    ]
