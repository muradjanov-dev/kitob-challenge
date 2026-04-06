from modeltranslation.translator import register, TranslationOptions

from .models import RequiredGroup, TelegramButton, Group


@register(RequiredGroup)
class RequiredGroupTranslationOption(TranslationOptions):
    fields = ("title",)


@register(TelegramButton)
class TelegramButtonTranslationOption(TranslationOptions):
    fields = ("title", "text")


@register(Group)
class GroupTranslationOption(TranslationOptions):
    fields = ("title",)
    