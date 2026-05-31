from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('tgbot', '0059_telegramprofile_congrats_dm_count'),
    ]

    operations = [
        migrations.CreateModel(
            name='ShopProduct',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Created at')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Updated at')),
                ('name', models.CharField(max_length=120)),
                ('description', models.TextField(blank=True, default='')),
                ('image', models.ImageField(blank=True, null=True, upload_to='shop/products/')),
                ('price_kitobcha', models.PositiveIntegerField(
                    help_text="Cost in Kitobcha. Deducted atomically from the buyer's ball.",
                )),
                ('stock_qty', models.PositiveIntegerField(
                    blank=True, null=True,
                    help_text='Leave blank for unlimited. Decremented on each purchase.',
                )),
                ('sort_order', models.IntegerField(
                    default=0,
                    help_text='Lower = shown first. Ties broken by newest-first.',
                )),
                ('is_active', models.BooleanField(default=True)),
            ],
            options={
                'verbose_name': 'Shop Product',
                'verbose_name_plural': 'Shop Products',
                'ordering': ('sort_order', '-created_at'),
            },
        ),
        migrations.CreateModel(
            name='ShopPurchase',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Created at')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Updated at')),
                ('product_name_snapshot', models.CharField(
                    max_length=120,
                    help_text='Name at time of purchase, kept even if product is deleted.',
                )),
                ('price_at_purchase', models.PositiveIntegerField()),
                ('code', models.CharField(
                    max_length=12, unique=True,
                    help_text='Short pickup code the user shows the admin.',
                )),
                ('status', models.CharField(
                    choices=[('pending', 'Pending'), ('fulfilled', 'Fulfilled'), ('refunded', 'Refunded')],
                    default='pending', max_length=16,
                )),
                ('product', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='purchases',
                    to='tgbot.shopproduct',
                )),
                ('user', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='shop_purchases',
                    to='tgbot.telegramprofile',
                )),
            ],
            options={
                'verbose_name': 'Shop Purchase',
                'verbose_name_plural': 'Shop Purchases',
                'ordering': ('-created_at',),
            },
        ),
    ]
