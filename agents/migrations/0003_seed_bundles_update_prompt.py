from django.db import migrations


def seed_bundles_update_prompt(apps, schema_editor):
    AgentPrompt = apps.get_model("agents", "AgentPrompt")
    table_name = AgentPrompt._meta.db_table

    # Safety: some environments may have migration history that marks 0001 applied
    # even though the underlying table was never created. Ensure the table exists
    # before querying/seeding.
    if table_name not in schema_editor.connection.introspection.table_names():
        schema_editor.create_model(AgentPrompt)

    payload = {
        "agent_name": "bundles_agent",
        "method": "update",
        "function": "extract_option_updates",
    }

    # Avoid duplicates if it already exists
    if AgentPrompt.objects.filter(**payload).exists():
        return

    AgentPrompt.objects.create(
        **payload,
        system_instructions=(
            "You extract bundle option updates from a user message and return STRICT JSON.\n"
            "Output must be an array where each item represents a bundle whose options will be updated.\n"
        ),
        system_rules=(
            "- Do NOT confirm changes; only return parsed data.\n"
            "- Use null when data is missing.\n"
            "- Use boolean true/false for is_required and default_selected.\n"
            "- Quantities and min/max are integers when provided.\n"
            "- Accept bundle/product by SKU or name; put them in both *_sku and *_name when available.\n"
            "- No extra text, markdown, or comments—JSON only.\n"
        ),
        agent_message="",
        agent_summary="",
        temperature=0,
    )


def remove_bundles_update_prompt(apps, schema_editor):
    AgentPrompt = apps.get_model("agents", "AgentPrompt")
    table_name = AgentPrompt._meta.db_table
    if table_name not in schema_editor.connection.introspection.table_names():
        return
    AgentPrompt.objects.filter(
        agent_name="bundles_agent",
        method="update",
        function="extract_option_updates",
    ).delete()


class Migration(migrations.Migration):
    # This migration may need to run DDL (create the AgentPrompt table) in
    # environments where migration history is inconsistent. MySQL prohibits DDL
    # inside a transaction when it can't be rolled back, so disable atomicity.
    atomic = False

    dependencies = [
        ('agents', '0002_single_record_layout'),
    ]

    operations = [
        migrations.RunPython(seed_bundles_update_prompt, remove_bundles_update_prompt),
    ]
