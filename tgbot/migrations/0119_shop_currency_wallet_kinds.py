from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tgbot", "0118_quizgame_self_paced"),
    ]

    operations = [
        migrations.AddField(
            model_name="shopproduct",
            name="currency",
            field=models.CharField(
                choices=[("kitobcha", "Kitobcha"), ("som", "So'm (hamyon)")], default="kitobcha", max_length=10,
                help_text="Kitobcha — balansdan; so'm — hamyondan (narx, boshlang'ich taklif va takliflar shu valyutada).",
            ),
        ),
        migrations.AddField(
            model_name="shoppurchase",
            name="currency",
            field=models.CharField(choices=[("kitobcha", "Kitobcha"), ("som", "So'm (hamyon)")],
                                   default="kitobcha", max_length=10),
        ),
        migrations.AlterField(
            model_name="shopproduct",
            name="price_kitobcha",
            field=models.PositiveIntegerField(
                help_text="Narx — mahsulot valyutasida (Kitobcha yoki so'm). Xaridorning Kitobchasidan yoki "
                          "hamyonidan atomik yechiladi."),
        ),
        migrations.AlterField(
            model_name="shopproduct",
            name="min_start_bid",
            field=models.PositiveIntegerField(default=100, help_text="Minimal boshlang'ich taklif — mahsulot valyutasida."),
        ),
        migrations.AlterField(
            model_name="shopauctionbid",
            name="amount",
            field=models.PositiveIntegerField(help_text="Total active bid placed by this user, in the product's currency."),
        ),
        migrations.AlterField(
            model_name="wallettransaction",
            name="kind",
            field=models.CharField(choices=[
                ("topup", "To'ldirish"), ("bonus", "Bonus"), ("premium_conversion", "Premium → hamyon"),
                ("report_fee", "Kunlik to'lov"), ("report_extra", "Qo'shimcha hisobot"), ("refund", "Qaytarildi"),
                ("referral", "Referal mukofoti"), ("cashback", "Kitob hamyonchasidan"), ("mentor", "Ustoz sovg'asi"),
                ("admin", "Admin tuzatishi"), ("report_bonus", "Hisobot bonusi"),
                ("streak_bonus", "Ketma-ketlik mukofoti"), ("daily_gift", "Kunning sovg'asi"), ("shop", "Do'kon"),
                ("shop_refund", "Do'kon qaytimi"),
            ], max_length=24),
        ),
    ]
