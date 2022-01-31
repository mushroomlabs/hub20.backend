from hub20.apps.blockchain.validators import uri_parsable_scheme_validator

tokenlist_uri_validator = uri_parsable_scheme_validator(("https", "http", "ipfs", "ens"))
