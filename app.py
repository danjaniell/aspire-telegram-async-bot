import startup
import shlex
import asyncio
import time
import flask
from flask import Flask
from kink import di
from app_config import Configuration
from aspire_util import append_trx
from telebot.callback_data import CallbackData
from telebot import types
from services import (
    Action,
    Formatting,
    TransactionData,
    DateUtil,
    KeyboardUtil,
    MyAsyncTeleBot
)
from gspread import Spreadsheet
from gevent.pywsgi import WSGIServer

# inject dependencies
startup.configure_services()


class App():
    @di[MyAsyncTeleBot].Instance.message_handler(state='*', commands=['cancel', 'q'])
    async def command_cancel(message):
        """
        Cancel transaction from any state
        """
        await di[MyAsyncTeleBot].Instance.delete_state(message.chat.id)
        await di[MyAsyncTeleBot].Instance.send_message(message.chat.id, 'Transaction cancelled.')

    @di[MyAsyncTeleBot].Instance.message_handler(state=[Action.outflow, Action.inflow], is_digit=False)
    async def invalid_amt(message):
        await di[MyAsyncTeleBot].Instance.reply_to(message, 'Please enter a number')

    async def quick_save(message):
        await di[MyAsyncTeleBot].Instance.set_state(message.from_user.id, Action.quick_end)
        await di[MyAsyncTeleBot].Instance.send_message(message.chat.id,
                                                       '\[Received Data]' +
                                                       f'\n{di[Formatting].format_data(di[TransactionData])}',
                                                       reply_markup=KeyboardUtil.create_save_keyboard('quick_save'))

    async def upload(message):
        """Upload info to aspire google sheet"""
        upload_data = [
            di[TransactionData]['Date'],
            di[TransactionData]['Outflow'],
            di[TransactionData]['Inflow'],
            di[TransactionData]['Category'],
            di[TransactionData]['Account'],
            di[TransactionData]['Memo'],
        ]
        append_trx(di[Spreadsheet], upload_data)
        di[TransactionData].reset()
        await di[MyAsyncTeleBot].Instance.reply_to(message, '✅ Transaction Saved\n')

    @di[MyAsyncTeleBot].Instance.message_handler(regexp='^(A|a)dd(I|i)nc.+$', restrict=True)
    async def income_trx(message):
        """Add income transaction using Today's date, Inflow Amount and Memo"""
        di[TransactionData].reset()
        text = message.text
        result = list(shlex.split(text))

        del result[0]

        paramCount = len(result)
        if paramCount != 2:
            await di[MyAsyncTeleBot].Instance.reply_to(
                message, f'Expected 2 parameters, received {paramCount}: [{result}]')
            return
        else:
            inflow, memo = result
            di[TransactionData]['Date'] = DateUtil.date_today()
            di[TransactionData]['Inflow'] = inflow
            di[TransactionData]['Memo'] = memo

        await App.quick_save(message)

    @di[MyAsyncTeleBot].Instance.message_handler(regexp='^(A|a)dd(E|e)xp.+$', restrict=True)
    async def expense_trx(message):
        """Add expense transaction using Today's date, Outflow Amount and Memo"""
        di[TransactionData].reset()
        text = message.text
        result = list(shlex.split(text))

        del result[0]

        paramCount = len(result)
        if paramCount != 2:
            await di[MyAsyncTeleBot].Instance.reply_to(
                message, f'Expected 2 parameters, received {paramCount}: [{result}]')
            return
        else:
            outflow, memo = result
            di[TransactionData]['Date'] = DateUtil.date_today()
            di[TransactionData]['Outflow'] = outflow
            di[TransactionData]['Memo'] = memo

        await App.quick_save(message)

    async def item_selected(action: Action, user_id, message_id):
        await di[MyAsyncTeleBot].Instance.set_state(user_id, action)

        data = di[TransactionData][action.name.capitalize()]
        if action == Action.outflow or action == Action.inflow:
            displayData = (di[Configuration]['currency'] +
                           f' {data}') if data != '' else '\'\''
        else:
            displayData = data if data != '' else '\'\''

        text = f'\[Current Value: ' + f' *{displayData}*]' + '\n' + \
            f'Enter {action.name.capitalize()} : '
        await di[MyAsyncTeleBot].Instance.edit_message_text(chat_id=user_id, message_id=message_id,
                                                            text=text, reply_markup=KeyboardUtil.create_save_keyboard('save'))

    @di[MyAsyncTeleBot].Instance.callback_query_handler(func=None, config=di[CallbackData].filter(), state=Action.start, restrict=True)
    async def actions_callback(call: types.CallbackQuery):
        callback_data: dict = di[CallbackData].parse(
            callback_data=call.data)
        actionId = int(callback_data['action_id'])
        action = Action(actionId)
        user_id = call.from_user.id
        message_id = call.message.message_id

        if (action == Action.end):
            await di[MyAsyncTeleBot].Instance.delete_state(call.message.chat.id)
            await di[MyAsyncTeleBot].Instance.edit_message_text(chat_id=user_id, message_id=message_id, text='Transaction cancelled.')
        else:
            await App.item_selected(action, user_id, message_id)

    @ di[MyAsyncTeleBot].Instance.message_handler(state=Action.outflow, restrict=True)
    async def get_outflow(message):
        di[TransactionData]['Outflow'] = message.text

    @ di[MyAsyncTeleBot].Instance.callback_query_handler(func=lambda c: c.data == 'save')
    async def save_callback(call: types.CallbackQuery):
        await di[MyAsyncTeleBot].Instance.set_state(call.from_user.id, Action.start)
        await di[MyAsyncTeleBot].Instance.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id,
                                                            text='Update:', reply_markup=KeyboardUtil.create_options_keyboard())

    @ di[MyAsyncTeleBot].Instance.callback_query_handler(func=lambda c: c.data == 'quick_save')
    async def savequick_callback(call: types.CallbackQuery):
        await di[MyAsyncTeleBot].Instance.delete_state(call.message.chat.id)
        await App.upload(call.message)

    @ di[MyAsyncTeleBot].Instance.message_handler(commands=['start', 's'], restrict=True)
    async def command_start(message):
        """
        Start the conversation and ask user for input.
        Initialize with options to fill in.
        """
        await di[MyAsyncTeleBot].Instance.set_state(message.from_user.id, Action.start)
        await di[MyAsyncTeleBot].Instance.send_message(message.chat.id, 'Select Option:', reply_markup=KeyboardUtil.create_default_options_keyboard())


WEBHOOK_URL_BASE = di['WEBHOOK_URL_BASE']
WEBHOOK_URL_PATH = "/%s/" % (di[Configuration]['secret'])

app = Flask(__name__)


@app.route('/start', methods=['GET'])
def start():
    asyncio.run(di[MyAsyncTeleBot].Instance.delete_webhook(
        drop_pending_updates=True))
    time.sleep(0.1)
    if (di[Configuration]['update_mode'] == 'polling'):
        asyncio.run(di[MyAsyncTeleBot].Instance.infinity_polling(
            skip_pending=True))
    elif (di[Configuration]['update_mode'] == 'webhook'):
        asyncio.run(di[MyAsyncTeleBot].Instance.set_webhook(
            url=WEBHOOK_URL_BASE + WEBHOOK_URL_PATH))
    return 'Bot started.'


@app.route(WEBHOOK_URL_PATH, methods=['POST'])
def webhook():
    if flask.request.headers.get('content-type') == 'application/json':
        json_string = flask.request.get_data().decode('utf-8')
        update = types.Update.de_json(json_string)
        asyncio.run(di[MyAsyncTeleBot].Instance.process_new_updates([update]))
        return ''
    else:
        flask.abort(403)


def start_server():
    http_server = WSGIServer(('', di[Configuration]['port']), app)
    http_server.serve_forever()


if __name__ == '__main__':
    start_server()
