from typing import Iterator

from models.chain import Chain
from models.exceptions import ChainNameError


class Chains:
    """
    Класс для хранения списка сетей.
    Название переменных Chains и значение name в объекте Chain должны совпадать.
    Информация для добавления сети можно взять из https://chainlist.org/ (рекомендую 1rpc)
    и из https://chainid.network/chains.json, либо https://api.debank.com/chain/list

    Сети из данного списка можно использовать в скрипте вставляя в выбор или добавление сети
    метамаска, а так же для подключения к RPC ноде в Web3 транзакциях.

    Объект Chain содержит следующие поля:

    обязательные:

    - name - название сети, в формате snake_case, при инициализации в класс Chains должно совпадать с именем переменной
    - param rpc: адрес провайдера в формате https://1rpc.io/ethereum, можно взять на https://chainlist.org/
    - chain_id: id сети, например 1 для Ethereum, можно искать тут https://chainid.network/chains.json

    опциональные:

    - native_token: тикер нативного токена сети, по умолчанию 'ETH'
    - is_eip1559: если сеть поддерживает EIP-1559, то True, иначе False, можно взять тут https://api.debank.com/chain/list
    - metamask_name: название сети в metamask, по умолчанию берется из параметра name
    - okx_name: название сети в OKX, список сетей можно получить запустив метод bot.exchanges.okx.get_chains()
    - binance_name: название сети в Binance, список сетей можно получить запустив метод bot.exchanges.binance.get_chains()
    - multiplier: множитель для увеличения комиссии, если транзакции не проходят из-за низкой комиссии, по умолчанию 1.0


    """
    # аргумент для хранения списка сетей
    _chains = None

    ETHEREUM = Chain(
        name='ethereum',
        rpc='https://1rpc.io/eth',
        chain_id=1,
        metamask_name='Ethereum Mainnet',
        okx_name='ERC20',
        binance_name='ETH'
    )

    LINEA = Chain(
        name='linea',
        rpc='https://rpc.ankr.com/linea/',
        chain_id=59144,
        metamask_name='Linea',
        okx_name='Linea',
        multiplier=1.5
    )

    ARBITRUM_ONE = Chain(
        name='arbitrum_one',
        rpc='https://rpc.ankr.com/arbitrum/',
        chain_id=42161,
        metamask_name='Arbitrum One',
        okx_name='Arbitrum One'
    )

    BSC = Chain(
        name='bsc',
        rpc='https://rpc.ankr.com/bsc/',
        chain_id=56,
        metamask_name='Binance Smart Chain',
        native_token='BNB',
        okx_name='BSC',
        binance_name='BSC'
    )

    OP = Chain(
        name='op',
        rpc='https://1rpc.io/op',
        chain_id=10,
        metamask_name='Optimism Mainnet',
        okx_name='Optimism'
    )

    POLYGON = Chain(
        name='polygon',
        rpc='https://rpc.ankr.com/polygon/',
        chain_id=137,
        native_token='POL',
        metamask_name='Polygon',
        okx_name='Polygon'
    )

    AVALANCHE = Chain(
        name='avalanche',
        rpc='https://1rpc.io/avax/c',
        chain_id=43114,
        native_token='AVAX',
        metamask_name='Avalanche',
        okx_name='Avalanche C'
    )

    ZKSYNC = Chain(
        name='zksync',
        rpc='https://rpc.ankr.com/zksync_era/',
        chain_id=324,
        metamask_name='zkSync',
        okx_name='zkSync Era'
    )

    CORE = Chain(
        name='core',
        rpc='https://rpc.ankr.com/core/',
        chain_id=1116,
        native_token='CORE',
        metamask_name='Core',
        okx_name='core'
    )

    SONEIUM = Chain(
        name='soneium',
        rpc='https://rpc.soneium.org',
        chain_id=1868,
        metamask_name='Soneium',
    )
    FTM = Chain(
        name='ftm',
        rpc='https://rpc.ankr.com/fantom/',
        chain_id=250,
    )

    def __iter__(self) -> Iterator[Chain]:
        """
        Метод для итерации по сетям, работает только при инициализации объекта Chains
        :return: итератор по сетям
        """
        return iter(self.get_chains_list())

    @classmethod
    def get_chain(cls, name: str) -> Chain:
        """
        Находит сеть по имени, сначала ищет по названию переменной с сетью, если
        не находит, ищет среди имен объектов класса Chain.
        :param name: имя сети
        :return: объект сети Chain, если не находит, бросает исключение ChainNameError
        """
        if not isinstance(name, str):
            raise TypeError(
                f'Ошибка поиска сети, для поиска нужно передать str, передано:  {type(name)}')

        name = name.upper()
        try:
            chain = getattr(cls, name)
            return chain
        except AttributeError:
            for chain in cls.__dict__.values():
                if isinstance(chain, Chain):
                    if chain.name.upper() == name:
                        return chain
            raise ChainNameError(
                f'Сеть {name} не найдена, добавьте ее в config/Chains, имена должны совпадать')

    @classmethod
    def get_chains_list(cls) -> list[Chain]:
        """
        Возвращает список сетей, можно использовать для итерации по сетям.
        :return: список сетей
        """
        if not cls._chains:
            cls._chains = [
                chain for chain in cls.__dict__.values() if isinstance(chain, Chain)]
        return cls._chains


if __name__ == '__main__':
    pass
