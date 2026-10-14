from django.db import migrations


def set_gemini_default(apps, schema_editor):
    WorkspaceSettings = apps.get_model("core", "WorkspaceSettings")
    WorkspaceSettings.objects.filter(pk=1).update(default_model="gemini-3.8-flash")


class Migration(migrations.Migration):
    dependencies = [("core", "0002_shared_workspace_no_auth")]

    operations = [migrations.RunPython(set_gemini_default, migrations.RunPython.noop)]
