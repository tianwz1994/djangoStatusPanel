# -*- coding: utf-8 -*-
# Generated by Django 1.11.2 on 2017-07-20 15:38
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('heartbeat', '0003_servers_qosguialarm'),
    ]

    operations = [
        migrations.CreateModel(
            name='Hosts',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('agentkey', models.CharField(max_length=255, verbose_name='Ключ БК')),
                ('enabled', models.BooleanField(default=True, verbose_name='Включен')),
                ('comment', models.CharField(blank=True, max_length=255, verbose_name='Комментарий')),
            ],
            options={
                'verbose_name': 'блок контроля',
                'verbose_name_plural': 'блоки контроля (hosts)',
            },
        ),
        migrations.CreateModel(
            name='Items',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255, verbose_name='Имя')),
                ('enabled', models.BooleanField(default=True, verbose_name='Включен')),
                ('type', models.CharField(max_length=255, verbose_name='Тип опроса')),
                ('unit', models.CharField(max_length=255, verbose_name='Единица измерения')),
                ('config', models.TextField(default='')),
            ],
            options={
                'verbose_name': 'сборщик данных',
                'verbose_name_plural': 'сборщики данных (items)',
            },
        ),
        migrations.CreateModel(
            name='TaskSets',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255, verbose_name='Имя')),
                ('enabled', models.BooleanField(default=True, verbose_name='Включена')),
                ('hosts', models.ManyToManyField(blank=True, to='heartbeat.Hosts', verbose_name='Блоки контроля')),
                ('items', models.ManyToManyField(blank=True, to='heartbeat.Items', verbose_name='Сборщики данных')),
                ('server', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='heartbeat.Servers', verbose_name='Сервер')),
            ],
            options={
                'verbose_name': 'Задача сбора данных',
                'verbose_name_plural': 'Задачи сбора данных',
            },
        ),
        migrations.CreateModel(
            name='Triggers',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('operator', models.CharField(max_length=2, verbose_name='Тип порога')),
                ('value', models.CharField(max_length=255, verbose_name='Значение порога')),
                ('severity', models.CharField(max_length=20, verbose_name='Важность')),
                ('item', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='heartbeat.Items', verbose_name='Сборщик данных')),
            ],
            options={
                'verbose_name': 'порог оповещения',
                'verbose_name_plural': 'пороги оповещения (triggers)',
            },
        ),
    ]