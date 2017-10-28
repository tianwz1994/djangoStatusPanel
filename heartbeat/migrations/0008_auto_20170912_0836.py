# -*- coding: utf-8 -*-
# Generated by Django 1.11.5 on 2017-09-12 05:36
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('heartbeat', '0007_auto_20170911_1614'),
    ]

    operations = [
        migrations.AddField(
            model_name='hosts',
            name='config',
            field=models.TextField(default=''),
        ),
        migrations.AlterField(
            model_name='servergroups',
            name='servers',
            field=models.ManyToManyField(to='heartbeat.Servers', verbose_name='Серверы'),
        ),
    ]