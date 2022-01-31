# Changelog

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.0] - 2022-01-31

### Added

 - Support for connections with multiple chains
 - Support for connections with multiple raiden nodes
 - Blockchain endpoint status now provide information about estimated gas fees
 - Ability for hub operators to import [token lists](https://tokenlists.org)
 - Ability for users to define which users they want to track
 - Faceted / Filtered search for tokens
 - API endpoints to provide meta-data about any token (whether
   is a stable token or not, if it is wrapper for another contract)
   and current information in relation to the blockchain status (cost to make a transfer)

### Changed
 - Improved process that listens and handles blockchain events.
   Instead of each function making as many queries as needed, there is
   now only one main process listening to blockchain events that
   notifies of every new block, and the handlers only make further
   requests if the transaction data indicates that it is relevant to
   the hub.

### Removed
 - Site-wide definition of tracked tokens
