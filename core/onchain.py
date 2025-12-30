from __future__ import annotations

from typing import Optional

from eth_account import Account as EthAccount
from eth_typing import ChecksumAddress
from loguru import logger
from web3 import Web3
from web3.contract import Contract

from config import config, Tokens, Chains
from models.account import Account
from models.amount import Amount
from models.chain import Chain
from models.contract_raw import ContractRaw
from models.token import Token, TokenTypes
from utils.utils import to_checksum, random_sleep, get_multiplayer, prepare_proxy_requests, get_user_agent, \
    get_response


class Onchain:
    def __init__(self, account: Account, chain: Chain):
        self.account = account
        self.chain = chain

        self.w3 = self._prepare_w3(chain)
        if self.account.private_key:
            if not self.account.address:
                self.account.address = self.w3.eth.account.from_key(
                    self.account.private_key).address

    def _prepare_w3(self, chain: Chain) -> Web3:
        request_kwargs = {
            'headers': {
                'User-Agent': get_user_agent(),
                "Content-Type": "application/json",
            },
            'proxies': None
        }
        if config.is_web3_proxy:
            request_kwargs['proxies'] = prepare_proxy_requests(
                self.account.proxy)
        self.w3 = Web3(Web3.HTTPProvider(
            chain.rpc, request_kwargs=request_kwargs))
        return self.w3

    def change_chain(self, chain: Chain):
        """
        Изменение сети для работы с блокчейном.

        Переключает RPC endpoint и параметры сети без переинициализации объекта.
        Приватный ключ и данные аккаунта сохраняются.

        :param chain: объект Chain новой сети
        :return: None

        Examples:
            >>> # Переключиться на Ethereum
            >>> onchain.change_chain(Chains.ETHEREUM)
            >>> eth_balance = onchain.get_balance()

            >>> # Переключиться на Arbitrum
            >>> onchain.change_chain(Chains.ARBITRUM_ONE)
            >>> arb_balance = onchain.get_balance()
        """
        self.chain = chain
        self.w3 = self._prepare_w3(chain)

    def _get_token_params(self, token_address: str | ChecksumAddress) -> tuple[str, int]:
        """
        Получение параметров токена (symbol, decimals) по адресу контракта токена
        :param token_address:  адрес контракта токена
        :return: кортеж (symbol, decimals)
        """
        token_contract_address = to_checksum(token_address)

        if token_contract_address == Tokens.NATIVE_TOKEN.address:
            return self.chain.native_token, Tokens.NATIVE_TOKEN.decimals

        token_contract_raw = ContractRaw(
            token_contract_address, 'erc20', self.chain)
        token_contract = self._get_contract(token_contract_raw)
        decimals = token_contract.functions.decimals().call()
        symbol = token_contract.functions.symbol().call()
        return symbol, decimals

    def _get_contract(self, contract_raw: ContractRaw) -> Contract:
        """
        Получение инициализированного объекта контракта
        :param contract_raw: объект ContractRaw
        :return: объект контракта
        """
        return self.w3.eth.contract(contract_raw.address, abi=contract_raw.abi)

    def _estimate_gas(self, tx_params: dict) -> dict:
        """
        Оценивает стоимость газа для транзакции и добавляет исходный словарь tx параметр gas
        :param tx: параметры транзакции
        """
        tx_params['gas'] = int(self.w3.eth.estimate_gas(
            tx_params) * get_multiplayer())
        return tx_params

    def _get_fee(self, tx_params: dict[str, str | int] | None = None) -> dict[str, str | int]:
        """
        Подготовка параметров транзакции с учетом EIP-1559. Берет значение EIP-1559 из self.chain.is_eip1559,
        если не определено, то запрашивает и сохраняет значение на время сессии.
        Если сеть не поддерживает EIP-1559, то устанавливает параметр gasPrice,
        если поддерживает, то устанавливает параметры maxFeePerGas и maxPriorityFeePerGas.
        :param tx_params: параметры транзакции без параметров комиссии либо None, если передан None, то создается новый словарь
        """
        if tx_params is None:
            tx_params = {}

        fee_history = None

        # Проверяем, известна ли поддержка EIP-1559 для этой сети
        if self.chain.is_eip1559 is None:
            # Запрашиваем историю комиссий за последние 20 блоков (40-й перцентиль)
            fee_history = self.w3.eth.fee_history(20, 'latest', [40])

            # Определяем поддержку EIP-1559 по наличию baseFeePerGas
            # Если есть хотя бы один ненулевой baseFee - сеть поддерживает EIP-1559
            self.chain.is_eip1559 = any(fee_history.get('baseFeePerGas', [0]))

        # Legacy режим (без EIP-1559): используем простой gasPrice
        if self.chain.is_eip1559 is False:
            tx_params['gasPrice'] = self._multiply(self.w3.eth.gas_price)
            return tx_params

        # EIP-1559 режим: рассчитываем maxFeePerGas и maxPriorityFeePerGas

        # Получаем fee_history (используем уже запрошенный или делаем новый запрос)
        fee_history = fee_history or self.w3.eth.fee_history(
            20, 'latest', [40])

        # Берем последний baseFee (базовая комиссия сети, сжигается)
        base_fee = fee_history.get('baseFeePerGas', [0])[-1]

        # Собираем priority fees (чаевые майнерам) из истории, исключая нулевые
        priority_fees = [fee[0] for fee in fee_history.get(
            'reward', [[0]]) if fee[0] != 0] or [0]

        # Находим медианное значение priority fee для стабильности
        median_index = len(priority_fees) // 2
        priority_fees.sort()
        median_priority_fee = priority_fees[median_index]

        # Применяем множители для гарантии прохождения транзакции
        priority_fee = self._multiply(median_priority_fee)

        # maxFeePerGas = baseFee + priorityFee (с учетом множителей)
        # Это максимум, который готовы заплатить (реально может быть меньше)
        max_fee = self._multiply(base_fee + priority_fee)

        # Устанавливаем тип транзакции 0x2 (EIP-1559)
        tx_params['type'] = '0x2'
        tx_params['maxFeePerGas'] = max_fee
        tx_params['maxPriorityFeePerGas'] = priority_fee

        return tx_params

    def _multiply(self, value: int, min_mult: float = 1.03, max_mult: float = 1.1) -> int:
        """
        Умножение значения газа на переданный множитель и множитель сети
        :param value: значение
        :return: умноженное значение
        """
        return int(value * get_multiplayer(min_mult, max_mult) * self.chain.multiplier)

    def _get_l1_fee(self, tx_params: dict[str, str | int]) -> Amount:
        """
        Получение комиссии для L1 сети Optimism

        Optimism - это L2 решение, которое публикует данные транзакций в Ethereum (L1).
        За публикацию данных в L1 взимается дополнительная комиссия (L1 Data Fee),
        которая рассчитывается на основе размера calldata транзакции.

        Эта комиссия специфична только для Optimism и подобных Optimistic Rollup решений.
        Другие L2 (Arbitrum, zkSync) используют другие механизмы расчета комиссий.

        Подробнее: https://community.optimism.io/docs/developers/build/transaction-fees/

        :param tx_params: параметры транзакции
        :return: комиссия L1 в wei (0 для всех сетей кроме Optimism)
        """
        # Проверяем, что это сеть Optimism
        if self.chain.name != 'op':
            return Amount(0, wei=True)

        # ABI контракта GasPriceOracle для получения L1 комиссии
        abi = [
            {
                "inputs": [{"internalType": "bytes", "name": "_data", "type": "bytes"}],
                "name": "getL1Fee",
                "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
                "stateMutability": "view",
                "type": "function"
            }
        ]
        # Адрес предустановленного контракта GasPriceOracle в Optimism
        oracle_address = self.w3.to_checksum_address(
            '0x420000000000000000000000000000000000000F')
        contract = self.w3.eth.contract(address=oracle_address, abi=abi)

        # Получаем calldata транзакции (если нет, используем пустой)
        tx_params['data'] = tx_params.get('data', '0x')

        # Вызываем контракт для расчета L1 комиссии на основе размера данных
        l1_fee = contract.functions.getL1Fee(tx_params['data']).call()
        return Amount(l1_fee, wei=True)

    def _prepare_tx(self, value: Optional[Amount] = None,
                    to_address: Optional[str | ChecksumAddress] = None) -> dict:
        """
        Подготовка параметров транзакции
        :param value: сумма перевода ETH, если ETH нужно приложить к транзакции
        :param to_address: адрес получателя транзакции, для перевода нативного токена
        или если НЕ используете build_transaction (он автоматически укажет адрес получателя)
        :return: параметры транзакции
        """
        # получаем параметры комиссии
        tx_params = self._get_fee()

        # добавляем параметры транзакции
        tx_params['from'] = self.account.address
        tx_params['nonce'] = self.w3.eth.get_transaction_count(
            self.account.address)
        tx_params['chainId'] = self.chain.chain_id

        # если передана сумма перевода, то добавляем ее в транзакцию
        if value:
            tx_params['value'] = value.wei

        # если передан адрес получателя, то добавляем его в транзакцию
        # нужно для отправки нативных токенов на адрес, а не на смарт контракт
        if to_address:
            tx_params['to'] = to_address

        return tx_params

    def _sign_and_send(self, tx: dict) -> str:
        """
        Подпись и отправка транзакции
        :param tx: параметры транзакции
        :return: хэш транзакции
        """
        signed_tx = self.w3.eth.account.sign_transaction(
            tx, self.account.private_key)
        tx_hash = self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        tx_receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)
        return tx_receipt['transactionHash'].hex()

    def get_balance(
            self,
            *,
            token: Optional[Token | str | ChecksumAddress] = None,
            address: Optional[str | ChecksumAddress] = None
    ) -> Amount:
        """
        Получение баланса кошелька в нативных или erc20 токенах, в формате Amount.

        :param token: объект Token или адрес смарт контракта токена, если не указан, то нативный баланс
        :param address: адрес кошелька, если не указан, то берется адрес аккаунта
        :return: объект Amount с балансом

        :raises ValueError: если токен принадлежит другой сети

        Examples:
            >>> # Получить баланс нативного токена
            >>> balance = onchain.get_balance()
            >>> print(f'ETH: {balance.ether}')

            >>> # Получить баланс ERC-20 токена
            >>> usdt_balance = onchain.get_balance(token=Tokens.USDT_ARBITRUM_ONE)
            >>> print(f'USDT: {usdt_balance.ether}')

            >>> # Проверить баланс другого кошелька
            >>> other_balance = onchain.get_balance(address='0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb5')

            >>> # Использовать адрес контракта напрямую
            >>> token_balance = onchain.get_balance(token='0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9')
        """

        if token is None:
            token = Tokens.NATIVE_TOKEN
            token.chain = self.chain

        # если не указан адрес, то берем адрес аккаунта
        if not address:
            address = self.account.address

        # приводим адрес к формату checksum
        address = to_checksum(address)

        # если передан адрес контракта, то получаем параметры токена и создаем объект Token
        if isinstance(token, str):
            symbol, decimals = self._get_token_params(token)
            token = Token(symbol, token, self.chain, decimals)

        if token.chain != self.chain:
            logger.error(
                f'Токен на другой сети {token.chain.name} проверяется в {self.chain.name}')
            raise ValueError('Токен на другой сети')

        # если токен не передан или передан нативный токен
        if token.type_token == TokenTypes.NATIVE:
            # получаем баланс нативного токена
            native_balance = self.w3.eth.get_balance(address)
            balance = Amount(native_balance, wei=True)
        else:
            # получаем баланс erc20 токена
            contract = self._get_contract(token)
            erc20_balance_wei = contract.functions.balanceOf(address).call()
            balance = Amount(erc20_balance_wei,
                             decimals=token.decimals, wei=True)
        return balance

    def _validate_native_transfer_value(self, tx_params: dict) -> None:
        """
        Проверка возможности отправки нативного токена и корректировка суммы перевода, если недостаточно средств
        в исходном словаре tx_params

        Алгоритм работы:
        1. Рассчитывает примерную комиссию транзакции (gas + L1 fee для Optimism)
        2. Проверяет, хватит ли баланса на сумму перевода + комиссию
        3. Если не хватает - автоматически корректирует сумму, отправляя максимум доступных средств
        4. Если даже на комиссию не хватает - выбрасывает исключение

        :param tx_params: параметры транзакции c указанным value
        :raises ValueError: если баланс недостаточен даже для оплаты комиссии
        """
        # Шаг 1: Получаем сумму перевода из параметров транзакции
        amount = Amount(tx_params['value'], wei=True)

        # Шаг 2: Рассчитываем L1 комиссию (для Optimism, для других сетей = 0)
        l1_fee = self._get_l1_fee(tx_params)

        # Шаг 3: Оцениваем примерный gas для транзакции
        # Используем простую транзакцию самому себе для оценки
        gues_gas = self.w3.eth.estimate_gas(
            {'from': self.account.address, 'to': self.account.address, 'value': 1})

        # Шаг 4: Получаем цену газа (для EIP-1559 используем maxFeePerGas, иначе gasPrice)
        gues_gas_price = tx_params.get(
            'maxFeePerGas', tx_params.get('gasPrice'))

        # Шаг 5: Рассчитываем общую комиссию с запасом 10-20%
        # Формула: (L1_fee + gas * gas_price) * (1.1 - 1.2)
        fee_spend = self._multiply(
            l1_fee.wei + gues_gas * gues_gas_price, 1.1, 1.2)

        # Шаг 6: Получаем текущий баланс
        balance = self.get_balance()

        # Шаг 7: Проверяем, хватает ли средств на перевод + комиссию
        if balance.wei - fee_spend - amount.wei >= 0:
            return  # Все ОК, средств достаточно

        # Шаг 8: Средств недостаточно - пытаемся отправить максимум доступных
        message = f'баланс {self.chain.native_token}: {balance}, сумма: {amount} to {tx_params["to"]}'
        logger.warning(
            f'{self.account.profile_number} Недостаточно средств для отправки транзакции, {message}'
            f'Отправляем все доступные средства')

        # Шаг 9: Корректируем сумму перевода = баланс - комиссия (с запасом)
        tx_params['value'] = int(
            balance.wei - self._multiply(fee_spend, 1.1, 1.2))

        # Шаг 10: Проверяем, что после вычета комиссии осталось что-то для отправки
        if tx_params['value'] > 0:
            return  # Отправляем скорректированную сумму

        # Шаг 11: Даже на комиссию не хватает - выбрасываем исключение
        logger.error(
            f'{self.account.profile_number} Недостаточно средств для отправки транзакции')
        raise ValueError('Недостаточно средств для отправки нативного токена')

    def send_token(self,
                   to_address: str | ChecksumAddress,
                   amount: Amount | int | float | None = None,
                   token: Optional[Token | str | ChecksumAddress] = None
                   ) -> str:
        """
        Отправка любых типов токенов, если не указан токен или адрес контракта токена, то отправка нативного токена,
        если при отправке токена не хватает средств, то отправляется все доступное количество.
        Если не передана сумма, отправляются все доступные токены.

        :param to_address: адрес получателя
        :param amount: сумма перевода, может быть объектом Amount, int, float или None (отправить весь баланс)
        :param token: объект Token или адрес контракта токена, если оставить пустым будет отправлен нативный токен
        :return: хэш транзакции

        :raises ValueError: если недостаточно средств для отправки нативного токена (включая комиссию)

        Examples:
            >>> # Отправить нативный токен (ETH)
            >>> tx_hash = onchain.send_token(
            ...     to_address='0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb5',
            ...     amount=0.01
            ... )

            >>> # Отправить ERC-20 токен
            >>> tx_hash = onchain.send_token(
            ...     to_address='0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb5',
            ...     token=Tokens.USDT_ARBITRUM_ONE,
            ...     amount=100
            ... )

            >>> # Отправить весь баланс токена (amount=None)
            >>> tx_hash = onchain.send_token(
            ...     to_address='0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb5',
            ...     token=Tokens.USDT_ARBITRUM_ONE,
            ...     amount=None
            ... )

            >>> # Использовать объект Amount для точности
            >>> amount_to_send = Amount(0.5, decimals=18)
            >>> tx_hash = onchain.send_token(
            ...     to_address='0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb5',
            ...     amount=amount_to_send
            ... )
        """
        # если не передан токен, то отправляем нативный токен
        if token is None:
            token = Tokens.NATIVE_TOKEN
            token.chain = self.chain
            token.symbol = self.chain.native_token

        if amount is None:
            amount = Amount(self.get_balance(token=token).wei,
                            decimals=token.decimals, wei=True)

        # приводим адрес к формату checksum
        to_address = to_checksum(to_address)

        # если передан адрес контракта, то получаем параметры токена и создаем объект Token
        if isinstance(token, str):
            symbol, decimals = self._get_token_params(token)
            token = Token(symbol, token, self.chain, decimals)

        # если передана сумма в виде числа, то создаем объект Amount
        if not isinstance(amount, Amount):
            amount = Amount(amount, decimals=token.decimals)

        # если передан нативный токен
        if token.type_token == TokenTypes.NATIVE:
            tx_params = self._prepare_tx(amount, to_address)
            self._validate_native_transfer_value(tx_params)
            amount = Amount(tx_params['value'], wei=True)
        else:
            # получаем баланс кошелька
            balance = self.get_balance(token=token)
            # проверка наличия средств на балансе
            if balance.wei < amount.wei:
                # если недостаточно средств, отправляем все доступные
                amount = balance
            # получаем контракт токена
            contract = self._get_contract(token)
            tx_params = self._prepare_tx()
            # создаем транзакцию
            tx_params = contract.functions.transfer(
                to_address, amount.wei).build_transaction(tx_params)

        self._estimate_gas(tx_params)
        # подписываем и отправляем транзакцию
        tx_hash = self._sign_and_send(tx_params)
        message = f' {amount} {token.symbol} на адрес {to_address} '
        logger.info(
            f'{self.account.profile_number} Транзакция отправлена [{message}] хэш: {tx_hash}')
        return tx_hash

    def _get_allowance(self, token: Token | str, spender: str | ChecksumAddress | ContractRaw) -> Amount:
        """
        Получение разрешенной суммы токенов на снятие
        :param token: объект Token или адрес контракта токена
        :param spender: адрес контракта, который получил разрешение на снятие токенов
        :return: объект Amount с разрешенной суммой
        """
        if token is None or token.type_token == TokenTypes.NATIVE:
            return Amount(0, wei=True)

        if isinstance(token, str):
            symbol, decimals = self._get_token_params(token)
            token = Token(symbol, token, self.chain, decimals)

        if isinstance(spender, ContractRaw):
            spender = spender.address

        if isinstance(spender, str):
            spender = Web3.to_checksum_address(spender)

        contract = self._get_contract(token)
        allowance = contract.functions.allowance(
            self.account.address, spender).call()
        return Amount(allowance, decimals=token.decimals, wei=True)

    def approve(self, token: Optional[Token, str], amount: Amount | int | float,
                spender: str | ChecksumAddress | ContractRaw) -> None:
        """
        Одобрение транзакции на снятие токенов (approve).

        Метод автоматически проверяет текущее одобрение и пропускает транзакцию,
        если уже одобрено достаточно средств. Для нативных токенов approve не требуется.

        :param token: токен, который одобряем или адрес контракта токена
        :param amount: сумма одобрения (может быть Amount, int, float). Для отзыва одобрения используйте 0
        :param spender: адрес контракта или объект ContractRaw, который получит разрешение на снятие токенов
        :return: None

        Examples:
            >>> # Одобрить 100 USDT для DEX контракта
            >>> onchain.approve(
            ...     token=Tokens.USDT_ARBITRUM_ONE,
            ...     amount=100,
            ...     spender='0xcontractAddress...'
            ... )

            >>> # Infinite approve (максимальная сумма)
            >>> onchain.approve(
            ...     token=Tokens.USDT_ARBITRUM_ONE,
            ...     amount=2**256 - 1,
            ...     spender='0xcontractAddress...'
            ... )

            >>> # Отозвать одобрение (установить в 0)
            >>> onchain.approve(
            ...     token=Tokens.USDT_ARBITRUM_ONE,
            ...     amount=0,
            ...     spender='0xcontractAddress...'
            ... )

            >>> # Использование с объектом ContractRaw
            >>> from models.contract_raw import ContractRaw
            >>> dex_contract = ContractRaw(
            ...     address='0xcontractAddress...',
            ...     abi_name='uniswap_router',
            ...     chain=Chains.ARBITRUM_ONE
            ... )
            >>> onchain.approve(
            ...     token=Tokens.USDT_ARBITRUM_ONE,
            ...     amount=50,
            ...     spender=dex_contract
            ... )
        """
        if token is None or token.type_token == TokenTypes.NATIVE:
            return

        if isinstance(token, str):
            symbol, decimals = self._get_token_params(token)
            token = Token(symbol, token, self.chain, decimals)

        if isinstance(amount, (int, float)):
            amount = Amount(amount, decimals=token.decimals)

        allowed = self._get_allowance(token, spender)

        if amount.wei == 0 and allowed.wei == 0:
            return

        if amount.wei != 0 and allowed.wei >= amount.wei:
            return

        if isinstance(spender, ContractRaw):
            spender = spender.address

        contract = self._get_contract(token)
        tx_params = self._prepare_tx()
        tx_params = self._get_fee(tx_params)

        tx_params = contract.functions.approve(
            spender, amount.wei).build_transaction(tx_params)
        self._estimate_gas(tx_params)
        self._sign_and_send(tx_params)
        message = f'approve {amount} {token.symbol} to {spender}'
        logger.info(
            f'{self.account.profile_number} Транзакция отправлена {message}')

    def get_gas_price(self, gwei: bool = True) -> int:
        """
        Получение текущей ставки газа в сети.

        :param gwei: если True, возвращает значение в gwei, иначе в wei
        :return: ставка газа в gwei или wei

        Examples:
            >>> # Получить цену газа в gwei
            >>> gas_price = onchain.get_gas_price(gwei=True)
            >>> print(f'Текущий газ: {gas_price} gwei')

            >>> # Получить цену газа в wei
            >>> gas_price_wei = onchain.get_gas_price(gwei=False)
        """
        gas_price = self.w3.eth.gas_price
        if gwei:
            return gas_price / 10 ** 9
        return gas_price

    def gas_price_wait(self, gas_limit: int = None) -> None:
        """
        Ожидание пока ставка газа не станет меньше лимита.

        Осуществляется запрос каждые 5-10 секунд до достижения нужной цены газа.

        :param gas_limit: лимит ставки газа в gwei, если не передан, берется из config.gas_price_limit
        :return: None

        Examples:
            >>> # Ждать пока газ не упадет ниже 30 gwei
            >>> onchain.gas_price_wait(gas_limit=30)
            >>> print('Газ упал ниже 30 gwei, продолжаем работу')

            >>> # Использовать лимит из конфига
            >>> onchain.gas_price_wait()  # использует config.gas_price_limit
        """
        if not gas_limit:
            gas_limit = config.gas_price_limit

        while self.get_gas_price() > gas_limit:
            random_sleep(5, 10)

    def get_pk_from_seed(self, seed: str | list, index: int = 0) -> str:
        """
        Получение приватного ключа из seed фразы с использованием BIP-44 стандарта (как в MetaMask).

        Генерирует приватные ключи детерминированно по порядку, используя путь деривации:
        m/44'/60'/0'/0/{index}

        :param seed: seed фраза в виде строки или списка слов
        :param index: номер приватного ключа (0, 1, 2, ...), по умолчанию 0
        :return: приватный ключ в формате hex строки

        Examples:
            >>> # Первый приватный ключ (index=0, по умолчанию)
            >>> seed = "word1 word2 word3 ... word12"
            >>> private_key_0 = onchain.get_pk_from_seed(seed)
            >>> print(f'Private key 0: {private_key_0}')

            >>> # Второй приватный ключ (index=1)
            >>> private_key_1 = onchain.get_pk_from_seed(seed, index=1)
            >>> print(f'Private key 1: {private_key_1}')

            >>> # Третий приватный ключ (index=2)
            >>> private_key_2 = onchain.get_pk_from_seed(seed, index=2)
            >>> print(f'Private key 2: {private_key_2}')

            >>> # Из списка слов
            >>> seed_list = ["word1", "word2", "word3", ..., "word12"]
            >>> private_key = onchain.get_pk_from_seed(seed_list, index=0)
        """
        EthAccount.enable_unaudited_hdwallet_features()
        if isinstance(seed, list):
            seed = ' '.join(seed)

        # BIP-44 путь деривации для Ethereum: m/44'/60'/0'/0/{index}
        # 44' - BIP-44 стандарт
        # 60' - Ethereum coin type
        # 0' - account number
        # 0 - change (0 для внешних адресов)
        # index - номер приватного ключа
        account_path = f"m/44'/60'/0'/0/{index}"
        return EthAccount.from_mnemonic(seed, account_path=account_path).key.hex()

    def is_eip_1559(self) -> bool:
        """
        Проверка наличия EIP-1559 на сети.

        EIP-1559 - это механизм динамического расчета комиссий с базовой комиссией (baseFee)
        и чаевыми (priorityFee). Поддерживается большинством современных EVM сетей.

        :return: True если EIP-1559 включен, False если используется legacy режим

        Examples:
            >>> # Проверить поддержку EIP-1559
            >>> is_eip1559 = onchain.is_eip_1559()
            >>> print(f'EIP-1559 supported: {is_eip1559}')
        """
        fees_data = self.w3.eth.fee_history(50, 'latest')
        base_fee = fees_data['baseFeePerGas']
        if any(base_fee):
            return True
        return False

    def remove_approves(self):
        """
        Удаление всех активных approves (одобрений) токенов для смарт-контрактов

        Этот метод полезен для повышения безопасности кошелька, так как отзывает
        все ранее выданные разрешения на использование токенов смарт-контрактами.

        Алгоритм работы:
        1. Получает все исторические события Approval через Etherscan API
        2. Извлекает уникальные пары (токен, spender)
        3. Для каждой пары вызывает approve с amount=0 (отзыв разрешения)

        Требования:
        - Необходим ETHERSCAN_API_KEY в .env файле
        - Работает только с сетями, поддерживаемыми Etherscan API

        Примечание: Каждый отзыв - это отдельная транзакция с комиссией
        """
        # Проверяем наличие API ключа Etherscan
        if not config.ETHERSCAN_API_KEY:
            logger.error(
                '[onchain.remove_approves] Не указан ключ для etherscan')
            return

        # Получаем все логи событий Approval для данного адреса
        logs = self._get_approval_logs()
        if not logs:
            logger.info('[onchain.remove_approves] Нет логов Approval')
            return

        # Используем set для хранения уникальных пар (токен, spender)
        # Это исключает дубликаты, если было несколько approve для одной пары
        approved = set()

        # Кэш для токенов, чтобы не запрашивать параметры повторно
        tokens_cache = {}

        # Парсим логи и извлекаем адреса токенов и spender'ов
        for log in logs:
            # address в логе - это адрес контракта токена
            token_address = log.get('address')

            # topics[2] содержит адрес spender (контракт, получивший approve)
            # Обрезаем первые 26 символов (64 - 40 = 24 нуля + '0x'), оставляя адрес
            spender_address = '0x' + log.get('topics')[2][26:]

            # Добавляем пару в set (автоматически исключаются дубликаты)
            approved.add((token_address, spender_address))

        # Отзываем каждое одобрение
        for token_address, spender_address in approved:
            # Проверяем кэш токенов
            token = tokens_cache.get(token_address)

            # Если токена нет в кэше, получаем его параметры из контракта
            if not token:
                symbol, decimals = self._get_token_params(token_address)
                token = Token(symbol, token_address, self.chain, decimals)
                # Кэшируем токен для последующих использований
                tokens_cache[token_address] = token

            # Отзываем approve, устанавливая amount в 0
            self.approve(token, 0, spender_address)

    def _get_approval_logs(self):
        """
        Получение логов Approval(address,address,uint256) по адресу отправителя
        :return: список логов Approval из etherscan по блокчейну Chain
        """
        url = f'https://api.etherscan.io/v2/api'
        params = {
            'chainid': self.chain.chain_id,
            'module': 'logs',
            'action': 'getLogs',
            'fromBlock': 0,
            'toBlock': 'latest',
            'topic0': '0x' + self.w3.keccak(text='Approval(address,address,uint256)').hex(),
            'topic0_1': 'and',
            'topic1': '0x' + self.account.address[2:].rjust(64, '0'),
            'apikey': config.ETHERSCAN_API_KEY,
        }
        response = get_response(url, params)
        return response.get('result', [])


if __name__ == '__main__':
    pass
