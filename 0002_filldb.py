# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations

def myCustom(apps, schema_editor):
	# We can't import the Person model directly as it may be a newer
	# version than this migration expects. We use the historical version.
	Options = apps.get_model('heartbeat', 'Options')
	Options.objects.bulk_create([
		Options(name='maxMsgTotal', value='50000'),
		])



class Migration(migrations.Migration):

	dependencies = [
		('heartbeat', '0001_initial'),
	]

	operations = [
		migrations.RunPython(myCustom),
	]