import platform
import telebot
import shlex
from app_config import Configuration
from datetime import datetime
from telebot import TeleBot
from telebot.async_telebot import AsyncTeleBot
from telebot.custom_filters import SimpleCustomFilter
from telebot.custom_filters import StateFilter
from telebot.custom_filters import IsDigitFilter
from telebot.custom_filters import AdvancedCustomFilter
from telebot.asyncio_filters import SimpleCustomFilter as AsyncSimpleCustomFilter
from telebot.asyncio_filters import StateFilter as AsyncStateFilter
from telebot.asyncio_filters import IsDigitFilter as AsyncIsDigitFilter
from telebot.asyncio_filters import AdvancedCustomFilter as AsyncAdvancedCustomFilter
from telebot.callback_data import CallbackData, CallbackDataFilter
from telebot import types
from kink import di
from enum import IntEnum
from zoneinfo import ZoneInfo
from typing import Any, Dict
from logging import Logger
from functools import wraps
from asyncio.proactor_events import _ProactorBasePipeTransport


class ExceptionHandler(telebot.ExceptionHandler):
    def handle(self, exception):
        di[Logger].error(exception)


class AsyncRestrictAccessFilter(AsyncSimpleCustomFilter):
    key = "restrict"

    async def check(self, message: types.Message):
        return (
            di[Configuration]["restrict_access"]
            and message.from_user.id in di[Configuration]["list_of_users"]
        )


class AsyncActionsCallbackFilter(AsyncAdvancedCustomFilter):
    key = "config"

    async def check(self, call: types.CallbackQuery, config: CallbackDataFilter):
        return config.check(query=call)


class ActionsCallbackFilter(AdvancedCustomFilter):
    key = "config"

    def check(self, call: types.CallbackQuery, config: CallbackDataFilter):
        return config.check(query=call)


class RestrictAccessFilter(SimpleCustomFilter):
    key = "restrict"

    def check(self, message: types.Message):
        return (
            di[Configuration]["restrict_access"]
            and message.from_user.id in di[Configuration]["list_of_users"]
        )


class BotFactory:
    def __init__(
        self,
        restrict_access_filter,
        state_filter,
        is_digit_filter,
        actions_callback_filter,
        bot_instance,
    ):
        bot_instance.add_custom_filter(restrict_access_filter)
        bot_instance.add_custom_filter(state_filter)
        bot_instance.add_custom_filter(is_digit_filter)
        bot_instance.add_custom_filter(actions_callback_filter)
        self._instance = bot_instance

    def create_bot(self):
        return self._instance


class Action(IntEnum):
    date = 1
    outflow = 2
    inflow = 3
    category = 4
    account = 5
    memo = 6
    cancel = 10
    done = 11
    start = 100
    quick_end = 200
    category_list = 300
    category_end = 301


class TextUtil:
    def format_data(self, user_data: Dict[str, str]) -> str:
        """Helper function for formatting the gathered user info."""
        data = []
        for key, value in user_data.items():
            if key in ("Outflow", "Inflow") and value != "":
                data.append(
                    f"*{key}* : " + di[Configuration]["currency"] + f" {int(value):,}"
                )
            else:
                data.append(f"*{key}* : {value}")
        return "\n".join(data).join(["\n", "\n"])

    def text_splitter(text):
        lex = shlex.shlex(text)
        lex.quotes = '"'
        lex.whitespace_split = True
        lex.commenters = ""
        return list(lex)


class DateUtil:
    def date_today() -> str:
        today = datetime.now(tz=ZoneInfo("Hongkong"))
        today = str(today.strftime("%m/%d/%y"))
        return today


class TransactionData(dict[str, Any]):
    def reset(self):
        self["Date"] = ""
        self["Outflow"] = ""
        self["Inflow"] = ""
        self["Category"] = ""
        self["Account"] = ""
        self["Memo"] = ""


class KeyboardUtil:
    def create_save_keyboard(callback_data: str):
        return types.InlineKeyboardMarkup(
            keyboard=[
                [types.InlineKeyboardButton(text="???? Save", callback_data=callback_data)]
            ]
        )

    def create_default_options_keyboard():
        """
        Menu keyboard for start command
        """
        filtered_actions = list(filter(lambda x: x <= Action.cancel, list(Action)))
        keyboard = [
            filtered_actions[i : i + 2] for i in range(0, len(filtered_actions), 2)
        ]
        for i, x in enumerate(keyboard):
            for j, k in enumerate(x):
                keyboard[i][j] = types.InlineKeyboardButton(
                    k.name.capitalize(),
                    callback_data=di[CallbackData].new(action_id=int(k)),
                )
        return types.InlineKeyboardMarkup(keyboard)

    def create_options_keyboard():
        """
        Menu keyboard for updating transaction data
        """
        keyboard = []
        for action in list(filter(lambda x: x <= Action.done, list(Action))):
            if action == Action.done or action == Action.cancel:
                btnList = [
                    types.InlineKeyboardButton(
                        text=action.name.capitalize(),
                        callback_data=di[CallbackData].new(action_id=int(action)),
                    )
                ]
            else:
                data = di[TransactionData][action.name.capitalize()]
                if action == Action.outflow or action == Action.inflow:
                    displayData = (
                        f"{action.name.capitalize()}: "
                        + (di[Configuration]["currency"] + f" {data}")
                        if data != ""
                        else action.name.capitalize()
                    )
                else:
                    displayData = (
                        f"{action.name.capitalize()}: " + data
                        if data != ""
                        else action.name.capitalize()
                    )
                btnList = [
                    types.InlineKeyboardButton(
                        text=f"{displayData}",
                        callback_data=di[CallbackData].new(action_id=int(action)),
                    )
                ]
            keyboard.append(btnList)
        return types.InlineKeyboardMarkup(keyboard)


def silence_event_loop_closed(func):
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        try:
            return func(self, *args, **kwargs)
        except RuntimeError as e:
            if str(e) != "Event loop is closed":
                raise

    return wrapper


if platform.system() == "Windows":
    _ProactorBasePipeTransport.__del__ = silence_event_loop_closed(
        _ProactorBasePipeTransport.__del__
    )
