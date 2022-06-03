import logging
import json
import os
import time
from http import HTTPStatus
from logging.handlers import RotatingFileHandler

import requests
import telegram
from dotenv import load_dotenv

from exceptions import (GetApiAnswerException, ParametersApiException,
                        UnknownStatusException,)

load_dotenv()

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
handler = RotatingFileHandler('my_logger.log',
                              maxBytes=50000000,
                              backupCount=5
                              )
logger.addHandler(handler)
formatter = logging.Formatter(
    '%(asctime)s, %(levelname)s, %(message)s, %(funcName)s'
)
handler.setFormatter(formatter)


PRACTICUM_TOKEN = os.getenv('PRACTICUM_TOKEN')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

RETRY_TIME = 600
ENDPOINT = 'https://practicum.yandex.ru/api/user_api/homework_statuses/'
HEADERS = {'Authorization': f'OAuth {PRACTICUM_TOKEN}'}


HOMEWORK_STATUSES = {
    'approved': 'Работа проверена: ревьюеру всё понравилось. Ура!',
    'reviewing': 'Работа взята на проверку ревьюером.',
    'rejected': 'Работа проверена: у ревьюера есть замечания.'
}


def send_message(bot, message):
    """
    Отправляет сообщение в Telegram чат.
    Чат задан переменной окружения TELEGRAM_CHAT_ID.
    Принимает на вход два параметра: экземпляр класса Bot и
    строку с текстом сообщения.
    """
    try:
        bot.send_message(TELEGRAM_CHAT_ID, message)
        logger.info(f'Сообщение в чат {TELEGRAM_CHAT_ID}:{message}')
    except telegram.TelegramError:
        logger.info('Ошибка отправки сообщения')


def get_api_answer(current_timestamp):
    """
    Делает запрос к единственному эндпоинту API-сервиса.
    В качестве параметра функция получает временную метку.
    В случае успешного запроса должна вернуть ответ API,
    преобразовав его из формата json к типам данных Python.
    """
    timestamp = current_timestamp or int(time.time())
    params = {'from_date': timestamp}
    if timestamp is None or params is None:
        logger.error('Ошибка параметров для запроса к API')
        raise ParametersApiException('Ошибка параметров для запроса к API')
    try:
        homework_statuses = requests.get(ENDPOINT,
                                         headers=HEADERS,
                                         params=params,
                                         )
    except GetApiAnswerException as error:
        logging.error(f'Ошибка при запросе к API: {error}')
        raise GetApiAnswerException
    if homework_statuses.status_code != HTTPStatus.OK:
        status_code = homework_statuses.status_code
        logging.error(f'Ошибка {status_code}')
        raise GetApiAnswerException(f'Ошибка {status_code}')
    try:
        return homework_statuses.json()
    except json.decoder.JSONDecodeError as json_error:
        logger.error('Ошибка парсинга ответа из формата json')
        raise json_error
    except ConnectionError as conn_error:
        logger.error('Ошибка соединения')
        raise conn_error


def check_response(response):
    """
    Проверяет ответ API на коррекность.
    В качестве параметра функция получает ответ API.
    Ответ приведен к типам данных Python.
    Если ответ API соответствует ожиданиям то функция должна вернуть
    список домашних работ(он может быть и пустым)
    доступный в ответе по ключу API 'homeworks'
    """
    if not isinstance(response, dict):
        raise TypeError('Запрос не соответвует формату')
    homework = response.get('homeworks')
    if 'homeworks' in homework:
        raise KeyError('Нет ключа homeworks')
    if not isinstance(homework, list):
        raise TypeError('Ответ не является списком')
    return homework


def parse_status(homework):
    """
    Излекает из информации о конкретной домашней работе статус этой работы.
    В качестве параметра функция получает
    всего один элемент из списка домашних работ
    В случае успеха, функция возращает
    подготовленную для отправки в телеграмм строку,
    содержающую один из вердиктов словаря
    HOMEWORK_STATUSES.
    """
    if 'homework_name' not in homework:
        raise KeyError('Отсутствует ключ "homework_name" в ответе API')
    if 'homework_status' in homework:
        raise KeyError('Отсутствует ключ "status" в ответе API')
    homework_name = homework['homework_name']
    homework_status = homework['status']
    if homework_status not in HOMEWORK_STATUSES:
        raise UnknownStatusException('Неизвестный статус работы:')
    verdict = HOMEWORK_STATUSES[homework_status]
    return f'Изменился статус проверки работы "{homework_name}". {verdict}'


def check_tokens():
    """
    Проверяет доступность переменных окружения.
    необходимых для работы
    Если отсутствует хотя бы одна перменная окружения функция
    должна вернуть False или True
    """
    return all([PRACTICUM_TOKEN, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID])


def main():
    """Основная логика работы бота."""
    bot = telegram.Bot(token=TELEGRAM_TOKEN)
    current_timestamp = int(time.time())
    MESSAGE_STATUS = ''
    ERROR_CACHE_MESSAGE = ''
    if not check_tokens():
        logger.critical('Отсутствует одна или несколько переменных окружения')
        message = 'Отсутствует одна или несколько переменных окружения'
        raise Exception('Отсутствует одна или несколько переменных окружения')
    while True:
        try:
            response = get_api_answer(current_timestamp)
            current_timestamp = response.get('current_date')
            message = parse_status(check_response(response))
            if message != MESSAGE_STATUS:
                send_message(bot, message)
                MESSAGE_STATUS = message
        except Exception as error:
            logger.error(error)
            message_info = str(error)
            if message_info != ERROR_CACHE_MESSAGE:
                send_message(bot, message_info)
                ERROR_CACHE_MESSAGE = message_info
        finally:
            time.sleep(RETRY_TIME)


if __name__ == '__main__':
    main()
