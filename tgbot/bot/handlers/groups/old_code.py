group = user.group
#
# report_message, created = ReportMessage.objects.get_or_create(
# chat_id=chat_id,
# last_update=today,
# group=group,
# defaults={'message_count': 0, 'message_text': '', 'message_id': None, 'group': group}
# )
#
# report_message, created = ReportMessage.objects.get_or_create(
# chat_id=chat_id,
# last_update=today,
# group=group,
# defaults={'message_count': 0, 'message_text': '', 'message_id': None, 'group': group}
# )
#
# if report_message.last_update != today:
# new_message = await bot.send_message(
#     chat_id=chat_id,
#     message_thread_id=topic_id,
#     text=new_report_message,
#     parse_mode='HTML'
# )
#
# report_message.message_id = new_message.message_id
# report_message.topic_id = new_message.topic_id
# report_message.message_text = new_report_message
# report_message.message_count = 1
# report_message.last_update = today
# report_message.save()
#
# else:
# try:
#     updated_message_text = report_message.message_text + f"\n\n{new_report_message}"
#
#     if int(last_topic_instance.topic_id) == int(topic_id):
#         await bot.edit_message_text(
#             chat_id=chat_id,
#             message_id=report_message.message_id,
#             text=updated_message_text,
#             parse_mode='HTML'
#         )
#
#         report_message.message_text = updated_message_text
#         report_message.message_count += 1
#         report_message.save()
#
#     else:
#         new_message = await bot.send_message(
#             chat_id=chat_id,
#             message_thread_id=topic_id,
#             text=new_report_message,
#             parse_mode='HTML'
#         )
#
#         report_message.message_id = new_message.message_id
#         report_message.topic_id = topic_id
#         report_message.message_text = new_report_message
#         report_message.message_count = 1
#         report_message.last_update = today
#         report_message.save()
#
#         last_topic_instance.topic_id = topic_id
#         last_topic_instance.save()
#
# except Exception as e:
#     last_report_message = await bot.send_message(
#         chat_id=chat_id,
#         message_thread_id=topic_id,
#         text=new_report_message,
#         parse_mode='HTML'
#     )
#
#     report_message.message_id = last_report_message.message_id
#     report_message.message_text = new_report_message
#     report_message.message_count = 1
#     report_message.save()
#
#     last_topic_instance.topic_id = topic_id
#     last_topic_instance.save()
