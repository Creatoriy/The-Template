from typing import Optional

from loguru import logger


class Chain:
    """
    Класс для хранения информации о сети. Информацию о сети можно искать тут https://chainid.network/chains.json

    - name - название сети, в формате snake_case, при инициализации в класс Chains должно совпадать с именем переменной
    - param rpc: адрес провайдера в формате https://1rpc.io/ethereum, можно взять на https://chainlist.org/
    - chain_id: id сети, например 1 для Ethereum, можно искать тут https://chainid.network/chains.json, либо https://api.debank.com/chain/list
    - native_token: тикер нативного токена сети, по умолчанию 'ETH'
    - is_eip1559: если сеть поддерживает EIP-1559, то True, иначе False, можно взять тут https://api.debank.com/chain/list
    - metamask_name: название сети в metamask, по умолчанию берется из параметра name
    - okx_name: название сети в OKX, список сетей можно получить запустив метод bot.exchanges.okx.get_chains(), по умолчанию None
    - binance_name: название сети в Binance, список сетей можно получить запустив метод bot.exchanges.binance.get_chains(), по умолчанию None
    - multiplier: множитель для увеличения комиссии, если транзакции не проходят из-за низкой комиссии, по умолчанию 1.0
    """

    def __init__(
            self,
            name: str,
            rpc: str,
            *,
            chain_id: int,
            metamask_name: Optional[str] = None,
            native_token: str = 'ETH',
            is_eip1559: bool | None = None,
            okx_name: str | None = None,
            binance_name: str | None = None,
            multiplier: float = 1.0,
    ):
        self.name = name
        self.rpc = rpc
        self.chain_id = chain_id
        self.metamask_name = metamask_name if metamask_name else name
        self.native_token = native_token
        self.okx_name = okx_name
        self.binance_name = binance_name
        self.is_eip1559 = is_eip1559
        self.multiplier = multiplier

    def __str__(self):
        return self.rpc

    def __repr__(self):
        return f'Chain(name={self.name}, rpc={self.rpc}, chain_id={self.chain_id}, metamask_name={self.metamask_name}, native_token={self.native_token}, okx_name={self.okx_name})'

    def __eq__(self, other):
        if isinstance(other, Chain):
            return self.name == other.name
        elif isinstance(other, str):
            return self.name.lower() == other.lower()
        elif isinstance(other, int):
            return self.chain_id == other
        else:
            logger.error(f'Ошибка сравнения сетей {type(other)}')
            return False


if __name__ == '__main__':
    pass
