from hub20.apps.core.validators import uri_parsable_scheme_validator

web3_url_validator = uri_parsable_scheme_validator(("http", "https", "ws", "wss", "ipc"))
