from hub20.apps.core.factories import PaymentNetworkFactory


class Web3PaymentNetworkFactory(PaymentNetworkFactory):
    name = "Ethereum-compatible blockchain"
    slug = "web3"
