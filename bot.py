import asyncio
import json
import logging
import sys
import typing as tp

import yaml
from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.utils.markdown import hbold, hitalic
from aiohttp import ClientSession

from db import init_database, get_history, write_history, get_stats, write_stats

with open('config.yaml') as fh:
    read_data = yaml.load(fh, Loader=yaml.FullLoader)

TOKEN = read_data['token']['bot']
KP_TOKEN = read_data['token']['kp-api']
KP_API_URL = read_data['url']['kp-api']
HEADERS = {"X-API-KEY": KP_TOKEN, "Content-Type": "application/json"}

dp = Dispatcher()


@dp.message(CommandStart())
async def command_start_handler(message: types.Message) -> None:
    """
    This handler greets user.
    """
    text = (f"Привет, {hbold(message.from_user.full_name)}!\n"
            f"Я бот для поиска фильмов в КинопоискHD\n"
            f"Напиши {hitalic('/help')} для дополнительной информации")
    await message.answer(text=text)


@dp.message(Command('help'))
async def help_handler(message: types.Message) -> None:
    """
    This handler receives messages with `/help` command.
    """
    text = ("Этот бот позволяет искать фильмы по названию\n"
            "Просто напиши название фильма, сериала или аниме, а я выведу информацию о нем\n"
            f"Используй {hitalic('/history')} чтобы отобразить историю запросов\n"
            f"Используй {hitalic('/stats')} чтобы посмотреть статистику")
    await message.answer(text=text)


@dp.message(Command('history'))
async def history_handler(message: types.Message) -> None:
    """
    This handler returns last 5 history searches (or less) for user.
    """
    result = await get_history(message.from_user.id)
    if len(result) == 0:
        answer = 'Вы еще ничего не искали'
    else:
        answer = "Ваши последние запросы: \n" + '\n'.join([item[0] for item in result])
    await message.answer(answer)


@dp.message(Command('stats'))
async def stats_handler(message: types.Message) -> None:
    """
    This handler returns statists for user searches, top 5 most popular or less.
    """
    result = await get_stats(message.from_user.id)
    if len(result) == 0:
        answer = 'Вы еще ничего не искали'
    else:
        answer = "Ваша самые популярные запросы: \n" + '\n'.join([' - '.join(map(str, item)) for item in result])
    await message.answer(answer)


def parse_film_name(film_info: dict[str, tp.Any]) -> str:
    if 'nameRu' in film_info:
        name = film_info["nameRu"]
    elif 'nameEn' in film_info:
        name = film_info["nameEn"]
    else:
        name = 'Unknown'

    return name


def create_films_keyboard(films: tp.List[dict[str, tp.Any]]) -> types.InlineKeyboardMarkup:
    """
        This method creates inlined keyboard which user uses to choose most relevant films.
        https://core.telegram.org/bots/features#keyboards
    """
    n = min(len(films), 5)
    buttons = []

    for i in range(n):
        film_info = films[i]
        film_id = films[i]['filmId']

        name = parse_film_name(film_info)
        year = film_info['year']

        text = f"{name} ({year})\n"
        buttons.append([types.InlineKeyboardButton(text=text, callback_data=f"film_{film_id}")])

    keyboard = types.InlineKeyboardMarkup(inline_keyboard=buttons)
    return keyboard


class EnrichedFilmInfo:

    def __init__(self, poster_url, caption, markup, film_title):
        self.poster_url = poster_url
        self.caption = caption
        self.markup = markup
        self.film_title = film_title


@dp.callback_query(F.data.startswith("film_"))
async def handle_film_selection_callback(callback: types.CallbackQuery) -> None:
    """
        This method handles callback from user pressing the keyboard and sends information about that film.
        https://core.telegram.org/bots/api#inlinekeyboardbutton
    """
    user_id = callback.from_user.id
    film_id = int(callback.data.split("_")[1])

    film_info = await enrich_film_info(film_id)

    await write_stats(user_id, film_id, film_info.film_title)

    if film_info.markup is not None:
        await callback.message.answer_photo(
            photo=film_info.poster_url,
            caption=film_info.caption,
            parse_mode='markdown',
            reply_markup=film_info.markup)
    else:
        await callback.message.answer_photo(
            photo=film_info.poster_url,
            caption=film_info.caption,
            parse_mode='markdown')


@dp.message()
async def main_handler(message: types.Message) -> None:
    """
    This handler processes main logic of searching films.
    """
    user_id = message.from_user.id
    search_query = message.text

    async with ClientSession(headers=HEADERS) as session:
        search_url = f"{KP_API_URL}/api/v2.1/films/search-by-keyword?keyword={search_query}"
        async with session.get(search_url) as response:
            films = json.loads(await response.text())["films"]

    await write_history(user_id, search_query)
    await message.answer(f"Результаты поиска по запросу: {message.text}", reply_markup=create_films_keyboard(films))


async def enrich_film_info(film_id: int) -> EnrichedFilmInfo:
    """
        This method enriches film info using film id and unofficial kinopoisk api.
        https://kinopoiskapiunofficial.tech/documentation/api/#/films/get_api_v2_2_films__id_
    """
    film_info_url = f"{KP_API_URL}/api/v2.2/films/{film_id}"
    async with ClientSession(headers=HEADERS) as session:
        async with session.get(film_info_url) as response:
            film_info = json.loads(await response.text())

    name = parse_film_name(film_info)
    result = f"{name} ({film_info['year']})\n\n"
    result += f"IMDb: {film_info['ratingImdb']}\nКинопоиск: {film_info['ratingKinopoisk']}\n\n"

    if film_info["shortDescription"] is not None:
        result += f"{film_info['shortDescription']}\n\n"
    elif film_info["description"] is not None:
        result += f"{film_info['description']}\n\n"

    kinopoisk_hd = film_info["kinopoiskHDId"]
    if kinopoisk_hd is None:
        markup = None
    else:
        film_link = f"https://hd.kinopoisk.ru/film/{kinopoisk_hd}"
        builder = InlineKeyboardBuilder()
        builder.row(types.InlineKeyboardButton(text="КинопоискHD", url=film_link))
        markup = builder.as_markup()

    poster_url = film_info["posterUrlPreview"]
    return EnrichedFilmInfo(poster_url, result, markup, name)


async def main() -> None:
    bot = Bot(TOKEN, parse_mode=ParseMode.HTML)
    await dp.start_polling(bot)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    asyncio.run(init_database())
    asyncio.run(main())
