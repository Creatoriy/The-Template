from loguru import logger

from core.browser import Ads, Metamask
from core.excel import Excel
from core.exchanges import Exchanges
from core.onchain import Onchain
from models.chain import Chain
from models.account import Account
from config import config


class Bot:
    """
    Центральный класс для управления всеми модулями автоматизации.

    Bot объединяет все модули проекта и предоставляет единый интерфейс для работы с:
    - ADS Power браузером (ads)
    - Кошельком Metamask (metamask)
    - Блокчейном (onchain)
    - Excel таблицами (excel)
    - Биржами OKX/Binance (exchanges)

    Класс реализует context manager протокол, что обеспечивает:
    - Автоматическое закрытие браузера при завершении работы
    - Корректную обработку ошибок
    - Логирование статуса выполнения

    Attributes:
        account (Account): Объект аккаунта с данными профиля
        chain (Chain): Текущая блокчейн сеть для работы
        ads (Ads): Модуль для управления браузером ADS Power
        metamask (Metamask): Модуль для работы с кошельком Metamask
        onchain (Onchain): Модуль для работы с блокчейном
        excel (Excel): Модуль для работы с Excel таблицами
        exchanges (Exchanges): Модуль для работы с биржами

    Example:
        >>> from core.bot import Bot
        >>> from models.account import Account
        >>> 
        >>> account = Account(profile_number=12345)
        >>> with Bot(account) as bot:
        ...     bot.ads.open_url('https://google.com')
        ...     balance = bot.onchain.get_balance()
        ...     bot.excel.set_cell('Balance', balance.ether)
    """

    def __init__(self, account: Account, chain: Chain = config.start_chain) -> None:
        logger.info(f'{account.profile_number} Запуск профиля')
        self.chain = chain
        self.account = account
        self.ads = Ads(account)
        self.excel = Excel(account)
        self.metamask = Metamask(self.ads, account, self.excel)
        self.exchanges = Exchanges(account)
        self.onchain = Onchain(account, self.chain)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.ads.close_browser()
        if exc_type is None:
            logger.success(
                f'{self.account.profile_number} Аккаунт завершен успешно')
        elif issubclass(exc_type, TimeoutError):
            logger.error(
                f'{self.account.profile_number} Аккаунт завершен по таймауту')
        else:
            if 'object has no attribute: page' in str(exc_val):
                logger.error(f'{self.account.profile_number} Аккаунт завершен с ошибкой, возможно вы '
                             f'выключили работу браузера и пытаетесь сделать логику работу с браузером. {exc_val}')
            else:
                logger.critical(
                    f'{self.account.profile_number} Аккаунт завершен с ошибкой {exc_val}')
        return True
