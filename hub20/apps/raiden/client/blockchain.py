import logging

from eth_utils import to_checksum_address
from raiden_contracts.constants import (
    CONTRACT_CUSTOM_TOKEN,
    CONTRACT_SERVICE_REGISTRY,
    CONTRACT_TOKEN_NETWORK,
    CONTRACT_TOKEN_NETWORK_REGISTRY,
    CONTRACT_USER_DEPOSIT,
)
from raiden_contracts.contract_manager import (
    ContractManager,
    contracts_precompiled_path,
    get_contracts_deployment_info,
)
from raiden_contracts.utils.type_aliases import ChainID
from web3 import Web3

from hub20.apps.blockchain.client import make_web3, send_transaction
from hub20.apps.blockchain.models import Web3Provider
from hub20.apps.blockchain.typing import EthereumAccount_T
from hub20.apps.ethereum_money.abi import EIP20_ABI
from hub20.apps.ethereum_money.client import make_token
from hub20.apps.ethereum_money.models import EthereumToken, EthereumTokenAmount
from hub20.apps.raiden.models import Raiden, TokenNetwork

GAS_REQUIRED_FOR_DEPOSIT: int = 200_000
GAS_REQUIRED_FOR_APPROVE: int = 70_000
GAS_REQUIRED_FOR_MINT: int = 100_000


logger = logging.getLogger(__name__)


def _get_contract_data(chain_id: int, contract_name: str):
    try:
        contract_data = get_contracts_deployment_info(ChainID(chain_id))
        assert contract_data is not None
        return contract_data["contracts"][contract_name]
    except (KeyError, AssertionError):
        return None


def get_user_deposit_contract(w3: Web3):
    contract_manager = ContractManager(contracts_precompiled_path())
    contract_address = get_contract_address(int(w3.net.version), CONTRACT_USER_DEPOSIT)
    return w3.eth.contract(
        address=contract_address, abi=contract_manager.get_contract_abi(CONTRACT_USER_DEPOSIT)
    )


def _get_contract(w3: Web3, contract_name: str):
    chain_id = int(w3.net.version)
    manager = ContractManager(contracts_precompiled_path())

    contract_data = _get_contract_data(chain_id, contract_name)
    assert contract_data

    abi = manager.get_contract_abi(contract_name)
    return w3.eth.contract(abi=abi, address=contract_data["address"])


def get_token_network_contract(w3: Web3, token_network: TokenNetwork):
    manager = ContractManager(contracts_precompiled_path())
    abi = manager.get_contract_abi(CONTRACT_TOKEN_NETWORK)
    return w3.eth.contract(abi=abi, address=token_network.address)


def get_contract_address(chain_id, contract_name):
    try:
        contract_data = _get_contract_data(chain_id, contract_name)
        return contract_data["address"]
    except (TypeError, AssertionError, KeyError) as exc:
        raise ValueError(f"{contract_name} does not exist on chain id {chain_id}") from exc


def get_token_network_registry_contract(w3: Web3):
    return _get_contract(w3, CONTRACT_TOKEN_NETWORK_REGISTRY)


def get_service_token_address(chain_id: int):
    service_contract_data = _get_contract_data(chain_id, CONTRACT_SERVICE_REGISTRY)
    return service_contract_data["constructor_arguments"][0]


def get_service_token(w3: Web3) -> EthereumToken:
    chain_id = int(w3.net.version)
    service_token_address = get_service_token_address(chain_id)
    return make_token(w3=w3, address=service_token_address)


def get_service_token_contract(w3: Web3) -> EthereumToken:
    chain_id = int(w3.net.version)
    service_token_address = get_service_token_address(chain_id)
    return w3.eth.contract(address=service_token_address, abi=EIP20_ABI)


def mint_tokens(w3: Web3, account: EthereumAccount_T, amount: EthereumTokenAmount):
    logger.debug(f"Minting {amount.formatted}")
    contract_manager = ContractManager(contracts_precompiled_path())
    token_proxy = w3.eth.contract(
        address=to_checksum_address(amount.currency.address),
        abi=contract_manager.get_contract_abi(CONTRACT_CUSTOM_TOKEN),
    )

    send_transaction(
        w3=w3,
        contract_function=token_proxy.functions.mint,
        account=account,
        contract_args=(amount.as_wei,),
        gas=GAS_REQUIRED_FOR_MINT,
    )


def get_service_total_deposit(w3: Web3, raiden: Raiden) -> EthereumTokenAmount:
    user_deposit_contract = get_user_deposit_contract(w3=w3)
    token = get_service_token(w3=w3)
    return token.from_wei(user_deposit_contract.functions.total_deposit(raiden.address).call())


def get_service_deposit_balance(w3: Web3, raiden: Raiden) -> EthereumTokenAmount:
    user_deposit_contract = get_user_deposit_contract(w3=w3)
    token = get_service_token(w3=w3)
    return token.from_wei(user_deposit_contract.functions.effectiveBalance(raiden.address).call())


def get_token_networks():
    for provider in Web3Provider.available.exclude(chain__raiden__isnull=True):
        w3: Web3 = make_web3(provider=provider)

        try:
            token_registry_contract = get_token_network_registry_contract(w3=w3)
        except AssertionError:
            continue
        get_token_network_address = token_registry_contract.functions.token_to_token_networks

        for token in EthereumToken.ERC20tokens.filter(chain_id=provider.chain_id):
            token_network_address = get_token_network_address(token.address).call()
            if token_network_address != EthereumToken.NULL_ADDRESS:
                TokenNetwork.objects.update_or_create(
                    token=token, defaults={"address": token_network_address}
                )
